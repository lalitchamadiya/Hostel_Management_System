import datetime
from django.utils import timezone
from django.db.models import Q
from django.core.exceptions import PermissionDenied

from hms.models import Duty, DutyPermission, DutyAssignment, DutyApprovalLog, StaffProfile
from authentication.models import Role, UserProfile, AuditLog
from room.models import HostelBuilding, Room


class DutyConflictService:
    """Service to detect shift conflicts, overlapping schedules, and location hierarchy validation."""

    WEEKDAY_MAP = {
        0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'
    }

    @classmethod
    def _parse_working_days(cls, days_str):
        if not days_str:
            return set(cls.WEEKDAY_MAP.values())
        return set(d.strip().upper() for d in str(days_str).split(',') if d.strip())

    @classmethod
    def _times_overlap(cls, s1, e1, s2, e2):
        """Helper to check if two time ranges [s1, e1] and [s2, e2] overlap, supporting overnight shifts."""
        if not s1 or not e1 or not s2 or not e2:
            return True  # If any time is unbounded, assume overlap

        def to_minutes_ranges(start, end):
            st = start.hour * 60 + start.minute
            et = end.hour * 60 + end.minute
            if st <= et:
                return [(st, et)]
            else:
                # Overnight shift, splits across midnight: [st, 1440) and [0, et]
                return [(st, 1440), (0, et)]

        r1 = to_minutes_ranges(s1, e1)
        r2 = to_minutes_ranges(s2, e2)

        for a_start, a_end in r1:
            for b_start, b_end in r2:
                if max(a_start, b_start) < min(a_end, b_end):
                    return True
        return False

    @classmethod
    def detect_conflict(cls, staff_id, start_date, end_date=None, shift_start=None, shift_end=None,
                        working_days='MON,TUE,WED,THU,FRI,SAT,SUN', exclude_id=None):
        """
        Inspects existing active/approved duty assignments for the given staff member.
        Returns: (has_conflict: bool, conflicting_assignment: DutyAssignment or None, reason: str)
        """
        if isinstance(start_date, str):
            start_date = datetime.date.fromisoformat(start_date)
        if isinstance(end_date, str) and end_date:
            end_date = datetime.date.fromisoformat(end_date)
        elif not end_date:
            end_date = None

        new_days = cls._parse_working_days(working_days)

        # Query all active or approved assignments for this staff
        qs = DutyAssignment.objects.filter(
            staff_id=staff_id,
            is_active=True,
            status__in=['ACTIVE', 'APPROVED', 'PENDING_APPROVAL']
        )
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)

        for existing in qs:
            # 1. Date overlap check
            # existing [start_date, end_date] vs new [start_date, end_date]
            ex_start = existing.start_date
            ex_end = existing.end_date

            date_overlap = True
            if ex_end and start_date > ex_end:
                date_overlap = False
            if end_date and ex_start > end_date:
                date_overlap = False

            if not date_overlap:
                continue

            # 2. Weekday overlap check
            ex_days = cls._parse_working_days(existing.working_days)
            common_days = new_days.intersection(ex_days)
            if not common_days:
                continue

            # 3. Shift time overlap check
            ex_st = existing.shift_start or (existing.duty.start_time if existing.duty else None)
            ex_et = existing.shift_end or (existing.duty.end_time if existing.duty else None)

            if cls._times_overlap(shift_start, shift_end, ex_st, ex_et):
                time_str = f"{ex_st.strftime('%H:%M') if ex_st else '--'} to {ex_et.strftime('%H:%M') if ex_et else '--'}"
                days_str = ", ".join(sorted(common_days))
                return True, existing, (
                    f"Overlaps with existing duty '{existing.duty_title}' "
                    f"on days [{days_str}] during shift [{time_str}] (Status: {existing.get_status_display()})."
                )

        return False, None, ""

    @classmethod
    def check_staff_leave_conflict(cls, staff_id, start_date, end_date=None):
        """Checks if staff member is currently on leave or has leave scheduled."""
        staff = StaffProfile.objects.filter(pk=staff_id).first()
        if not staff:
            return False, ""
        if staff.status == 'on_leave':
            return True, f"Staff member '{staff.name}' is currently marked as 'On Leave'."
        return False, ""

    @classmethod
    def validate_location_hierarchy(cls, hostel_id=None, building_id=None, block=None, floor=None, room_id=None):
        """
        Validates the cascading hierarchy: Hostel -> Building -> Block -> Floor -> Room.
        Returns: (is_valid: bool, error: str or None)
        """
        building = None
        if building_id:
            building = HostelBuilding.objects.filter(pk=building_id).first()
            if not building:
                return False, f"Building with ID {building_id} does not exist."

        if floor is not None and floor != '':
            try:
                floor_int = int(floor)
                if building and (floor_int < 0 or floor_int > building.total_floors):
                    return False, f"Floor {floor_int} exceeds building total floors ({building.total_floors})."
            except (ValueError, TypeError):
                return False, f"Invalid floor value: {floor}"

        if room_id:
            room = Room.objects.filter(pk=room_id).first()
            if not room:
                return False, f"Room with ID {room_id} does not exist."
            if building and room.building_id != building.id:
                return False, f"Room {room.room_number} does not belong to building '{building.name}'."
            if floor is not None and floor != '' and room.floor != int(floor):
                return False, f"Room {room.room_number} is on floor {room.floor}, not floor {floor}."
            if block and room.block and room.block.strip().upper() != block.strip().upper():
                return False, f"Room {room.room_number} is in block {room.block}, not block {block}."

        return True, None


class DutyAuthorizationService:
    """Service to evaluate dynamic effective permissions with temporal shift and location scoping."""

    MODULE_ALIAS_MAP = {
        'student': 'students',
        'students': 'students',
        'leave': 'leave',
        'attendance': 'attendance',
        'room': 'rooms',
        'rooms': 'rooms',
        'complaint': 'complaints',
        'complaints': 'complaints',
        'fee': 'fee',
        'fees': 'fee',
        'visitor': 'visitors',
        'visitors': 'visitors',
        'duty_management': 'duty_management',
    }

    @classmethod
    def is_assignment_active_now(cls, assignment, target_dt=None, grace_minutes=15):
        """
        Evaluates whether an assignment is active right now (or at target_dt).
        Applies a grace_minutes buffer around shift start and end.
        """
        if not assignment.is_active or assignment.status not in ('ACTIVE', 'APPROVED'):
            return False

        if not target_dt:
            target_dt = timezone.localtime(timezone.now())

        current_date = target_dt.date()
        if assignment.start_date and current_date < assignment.start_date:
            return False
        if assignment.end_date and current_date > assignment.end_date:
            return False

        # Weekday check
        weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
        current_day = weekday_map.get(current_date.weekday())
        working_days = assignment.working_days_list
        if working_days and current_day not in working_days:
            return False

        # Shift timing check
        st = assignment.shift_start or (assignment.duty.start_time if assignment.duty else None)
        et = assignment.shift_end or (assignment.duty.end_time if assignment.duty else None)

        if st and et:
            cur_min = target_dt.hour * 60 + target_dt.minute
            s_min = max(0, st.hour * 60 + st.minute - grace_minutes)
            e_min = min(1440, et.hour * 60 + et.minute + grace_minutes)

            if s_min <= e_min:
                if not (s_min <= cur_min <= e_min):
                    return False
            else:
                # Overnight shift
                if not (cur_min >= s_min or cur_min <= e_min):
                    return False

        return True

    @classmethod
    def get_active_duties_for_user(cls, user, target_dt=None):
        """Returns all DutyAssignment instances currently active and valid for the user."""
        if not user or not user.is_authenticated:
            return []

        staff = getattr(user, 'staff_profile', None)
        if not staff or staff.status != 'active':
            return []

        assignments = DutyAssignment.objects.filter(
            staff=staff,
            is_active=True,
            status__in=['ACTIVE', 'APPROVED']
        ).select_related('duty', 'building', 'room', 'hostel')

        active_list = []
        for a in assignments:
            if cls.is_assignment_active_now(a, target_dt=target_dt):
                active_list.append(a)
        return active_list

    @classmethod
    def evaluate_duty_permission(cls, user, module_code, action, target_obj=None, target_dt=None):
        """
        Evaluates whether user has permission for (module_code, action) through active duties.
        Checks:
        1. Active shift validity.
        2. Module action permission in DutyPermission (10 actions).
        3. Privilege ceiling enforcement (cannot exceed duty.privilege_ceiling_role if specified).
        4. Location and data scoping against target_obj.
        Returns: (granted: bool, reason: str)
        """
        active_assignments = cls.get_active_duties_for_user(user, target_dt=target_dt)
        if not active_assignments:
            return False, "No active duty assignments during current shift window."

        norm_module = cls.MODULE_ALIAS_MAP.get(module_code, module_code)

        for a in active_assignments:
            duty = a.duty
            if not duty:
                continue

            # Look up duty permission for this module
            dp = duty.permissions.filter(
                Q(module_name=norm_module) | Q(module_name=module_code)
            ).first()

            if not dp:
                continue

            field_name = f"can_{action}"
            if not getattr(dp, field_name, False):
                continue

            # Privilege ceiling check: ensure ceiling role does not forbid this action
            if duty.privilege_ceiling_role:
                ceiling_perm = duty.privilege_ceiling_role.permissions.filter(
                    Q(module__code=module_code) | Q(module__code=norm_module)
                ).first()
                if not ceiling_perm or not getattr(ceiling_perm, field_name, False):
                    continue  # Blocked by privilege ceiling!

            # Object-level data scope check
            if target_obj is not None:
                scope = duty.data_scope
                if not cls._check_object_scope(user, a, scope, target_obj):
                    continue  # Object falls outside assigned location or ownership boundary

            return True, f"Granted by active duty '{a.duty_title}' with scope {duty.data_scope}."

        return False, "Action not authorized under any active duty assignment."

    @classmethod
    def _check_object_scope(cls, user, assignment, scope, target_obj):
        """Validates if target_obj falls within assignment location and scope."""
        if scope == 'ORGANIZATION':
            # Check hostel boundary
            if assignment.hostel and hasattr(target_obj, 'hostel'):
                return target_obj.hostel_id == assignment.hostel_id
            return True

        if scope == 'BUILDING':
            if not assignment.building:
                return True
            # Check if target_obj relates to assignment.building
            if hasattr(target_obj, 'building'):
                return target_obj.building_id == assignment.building_id
            if hasattr(target_obj, 'room') and target_obj.room:
                return target_obj.room.building_id == assignment.building_id
            if hasattr(target_obj, 'allocated_beds'):
                bed = target_obj.allocated_beds.first()
                if bed and bed.room:
                    return bed.room.building_id == assignment.building_id
            return True

        if scope == 'LOCATION':
            # Block / Floor / Room scoping
            if assignment.room:
                if hasattr(target_obj, 'room_id'):
                    return target_obj.room_id == assignment.room_id
                if hasattr(target_obj, 'pk') and isinstance(target_obj, Room):
                    return target_obj.pk == assignment.room_id
                if hasattr(target_obj, 'allocated_beds'):
                    bed = target_obj.allocated_beds.first()
                    return bed and bed.room_id == assignment.room_id
            if assignment.floor is not None:
                if hasattr(target_obj, 'floor'):
                    return target_obj.floor == assignment.floor
                if hasattr(target_obj, 'room') and target_obj.room:
                    return target_obj.room.floor == assignment.floor
            if assignment.block:
                if hasattr(target_obj, 'block'):
                    return str(target_obj.block).strip().upper() == str(assignment.block).strip().upper()
                if hasattr(target_obj, 'room') and target_obj.room:
                    return str(target_obj.room.block).strip().upper() == str(assignment.block).strip().upper()
            if assignment.building:
                if hasattr(target_obj, 'building_id'):
                    return target_obj.building_id == assignment.building_id
            return True

        if scope == 'OWN':
            # Check ownership or assignment to this staff/user
            if hasattr(target_obj, 'created_by'):
                if target_obj.created_by == user:
                    return True
            if hasattr(target_obj, 'assigned_to'):
                staff = getattr(user, 'staff_profile', None)
                if staff and target_obj.assigned_to == staff:
                    return True
            if hasattr(target_obj, 'user'):
                if target_obj.user == user:
                    return True
            return False

        return True


class DutyWorkflowService:
    """Service handling assignment submission, approvals, handover, and emergency revocation."""

    @classmethod
    def approve_assignment(cls, assignment, approved_by_user, notes='', ip_address=None):
        """
        Approves an assignment.
        Enforces: Self-approval is strictly forbidden.
        """
        if assignment.staff.user and assignment.staff.user == approved_by_user:
            raise PermissionDenied("Self-approval violation: You cannot approve your own duty assignment.")

        assignment.status = 'APPROVED'
        assignment.approved_by = approved_by_user
        assignment.approved_at = timezone.now()
        assignment.approval_notes = notes.strip()
        assignment.is_active = True
        assignment.save()

        DutyApprovalLog.objects.create(
            assignment=assignment,
            action='APPROVED',
            performed_by=approved_by_user,
            notes=notes.strip() or "Duty assignment approved.",
            ip_address=ip_address
        )

        try:
            AuditLog.objects.create(
                actor=approved_by_user,
                action='edit',
                details=f"Approved duty '{assignment.duty_title}' for staff '{assignment.staff.name}'."
            )
        except Exception:
            pass
        return assignment

    @classmethod
    def reject_assignment(cls, assignment, rejected_by_user, reason, ip_address=None):
        """Rejects an assignment. Mandatory non-empty reason required."""
        if not reason or not reason.strip():
            raise ValueError("A mandatory rejection reason is required.")

        assignment.status = 'REJECTED'
        assignment.approval_notes = reason.strip()
        assignment.save()

        DutyApprovalLog.objects.create(
            assignment=assignment,
            action='REJECTED',
            performed_by=rejected_by_user,
            notes=reason.strip(),
            ip_address=ip_address
        )

        try:
            AuditLog.objects.create(
                actor=rejected_by_user,
                action='edit',
                details=f"Rejected duty '{assignment.duty_title}' for staff '{assignment.staff.name}'. Reason: {reason.strip()}"
            )
        except Exception:
            pass
        return assignment

    @classmethod
    def handover_duty(cls, assignment, substitute_staff, performed_by_user, reason='', ip_address=None):
        """Transfers duty assignment to substitute staff in emergency or handover."""
        if not substitute_staff.status == 'active':
            raise ValueError("Substitute staff member must be active.")

        original_staff = assignment.staff
        assignment.handover_from = original_staff
        assignment.handover_to = substitute_staff
        assignment.handover_at = timezone.now()
        assignment.handover_reason = reason.strip()
        assignment.staff = substitute_staff
        assignment.save()

        DutyApprovalLog.objects.create(
            assignment=assignment,
            action='HANDOVER',
            performed_by=performed_by_user,
            notes=f"Handed over from {original_staff.name} to {substitute_staff.name}. Reason: {reason.strip()}",
            ip_address=ip_address
        )

        try:
            AuditLog.objects.create(
                actor=performed_by_user,
                action='edit',
                details=f"Transferred duty '{assignment.duty_title}' from '{original_staff.name}' to '{substitute_staff.name}'."
            )
        except Exception:
            pass
        return assignment

    @classmethod
    def revoke_duty(cls, assignment, revoked_by_user, reason='', ip_address=None):
        """Emergency killswitch: instantly revokes duty assignment and cuts access."""
        assignment.status = 'REVOKED'
        assignment.is_active = False
        assignment.revoked_by = revoked_by_user
        assignment.revoked_at = timezone.now()
        assignment.revocation_reason = reason.strip()
        assignment.save()

        DutyApprovalLog.objects.create(
            assignment=assignment,
            action='REVOKED',
            performed_by=revoked_by_user,
            notes=reason.strip() or "Emergency revocation applied.",
            ip_address=ip_address
        )

        try:
            AuditLog.objects.create(
                actor=revoked_by_user,
                action='edit',
                details=f"Revoked duty assignment '{assignment.duty_title}' for '{assignment.staff.name}'. Reason: {reason.strip()}"
            )
        except Exception:
            pass
        return assignment
