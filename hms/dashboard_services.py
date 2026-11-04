import datetime
import hashlib
from django.utils import timezone
from django.db.models import Q, Count, Sum
from django.core.cache import cache

from authentication.models import Role, RolePermission, UserProfile, AuditLog, Module
from hms.models import (
    StaffProfile, ComplaintTicket, DutyAssignment, Duty, DutyPermission,
    UserDashboardPreference, RoleDashboardConfig
)
from hms.duty_services import DutyAuthorizationService
from room.models import HostelBuilding, Room, Bed
from student.models import Student, Attendance, StudentFeePayment
from leave.models import HostelLeave


class UserDashboardContext:
    """Encapsulates all role, duty, permission, and location metadata for the dashboard session."""
    def __init__(self, user, staff, role, is_role_valid, role_name, active_duties,
                 effective_perms, scoped_hostel_id, scoped_building_ids, scoped_block_names,
                 scoped_floor_numbers, scoped_room_ids, scoped_specific_locations,
                 is_global_org_scoped, is_own_only):
        self.user = user
        self.staff = staff
        self.role = role
        self.is_role_valid = is_role_valid
        self.role_name = role_name
        self.active_duties = active_duties
        self.effective_perms = effective_perms
        self.scoped_hostel_id = scoped_hostel_id
        self.scoped_building_ids = scoped_building_ids
        self.scoped_block_names = scoped_block_names
        self.scoped_floor_numbers = scoped_floor_numbers
        self.scoped_room_ids = scoped_room_ids
        self.scoped_specific_locations = scoped_specific_locations
        self.is_global_org_scoped = is_global_org_scoped
        self.is_own_only = is_own_only

    def can(self, module_code, action='view'):
        """Checks if user has effective permission for (module_code, action)."""
        if not self.is_role_valid:
            return False  # Fail-closed security
        mod_perms = self.effective_perms.get(module_code, {})
        return bool(mod_perms.get(action, False))

    def has_any_perm(self, module_code):
        if not self.is_role_valid:
            return False
        mod_perms = self.effective_perms.get(module_code, {})
        return any(mod_perms.values())


class DynamicDashboardService:
    """Core enterprise engine to dynamically assemble role & duty-based dashboards."""

    SUPPORTED_MODULES = [
        'student', 'room', 'leave', 'attendance', 'complaint',
        'fee', 'visitor', 'duty_management', 'user_management', 'rbac'
    ]

    MODULE_ALIAS_MAP = {
        'student': 'students',
        'students': 'student',
        'room': 'rooms',
        'rooms': 'room',
        'complaint': 'complaints',
        'complaints': 'complaint',
        'fee': 'fees',
        'fees': 'fee',
        'visitor': 'visitors',
        'visitors': 'visitor',
        'duty_management': 'duty_management',
        'leave': 'leave',
        'attendance': 'attendance',
    }

    ALL_WIDGETS = [
        {'key': 'active_duties', 'name': 'Active Duties & Shifts', 'icon': 'bi-shield-check', 'desc': 'Current assignments, schedules and shift status'},
        {'key': 'kpis', 'name': 'KPI Metrics & Statistics', 'icon': 'bi-graph-up-arrow', 'desc': 'Permission-scoped operational KPI numbers'},
        {'key': 'actionable_tasks', 'name': 'Actionable Tasks Queue', 'icon': 'bi-check2-square', 'desc': 'Assigned complaints, tasks and duties'},
        {'key': 'pending_approvals', 'name': 'Pending Approvals Queue', 'icon': 'bi-hourglass-split', 'desc': 'Leaves and duty signoffs awaiting action'},
        {'key': 'shift_calendar', 'name': 'Weekly Shift Schedule', 'icon': 'bi-calendar3', 'desc': '7-day shift rotation and duty calendar'},
        {'key': 'location_overview', 'name': 'Assigned Location Status', 'icon': 'bi-geo-alt', 'desc': 'Scoped infrastructure and occupancy summary'},
        {'key': 'quick_actions', 'name': 'Quick Action Shortcuts', 'icon': 'bi-lightning-charge', 'desc': 'Direct shortcuts to authorized module actions'},
        {'key': 'operational_alerts', 'name': 'Operational Alerts & Notices', 'icon': 'bi-bell', 'desc': 'Live shift alerts and urgent warnings'},
        {'key': 'recent_activities', 'name': 'Scoped Activity Feed', 'icon': 'bi-clock-history', 'desc': 'Recent operations in assigned area'},
    ]

    @classmethod
    def build_user_dashboard_context(cls, user, target_dt=None):
        """Assembles user role, active duties, effective permissions, and location boundaries."""
        if not target_dt:
            target_dt = timezone.localtime(timezone.now())

        staff = getattr(user, 'staff_profile', None)
        profile = getattr(user, 'profile', None)
        role = profile.role if profile else None
        is_role_valid = bool(role and role.is_active)
        role_name = role.name if is_role_valid else "Role Missing – Reassignment Required"

        # 1. Fetch active duty assignments
        active_duties = []
        if staff and staff.status == 'active':
            assignments = DutyAssignment.objects.filter(
                staff=staff,
                is_active=True,
                status__in=['ACTIVE', 'APPROVED']
            ).select_related('duty', 'duty__privilege_ceiling_role', 'building', 'room', 'hostel', 'supervisor')

            for a in assignments:
                # Attach live shift indicator
                a.is_on_shift_now = DutyAuthorizationService.is_assignment_active_now(a, target_dt=target_dt)
                active_duties.append(a)

        # 2. Base System Role Permissions
        effective_perms = {m: {act: False for act in [
            'view', 'add', 'edit', 'delete', 'approve', 'reject',
            'verify', 'export', 'print', 'download', 'assign'
        ]} for m in cls.SUPPORTED_MODULES}

        if is_role_valid:
            role_perms = RolePermission.objects.filter(role=role).select_related('module')
            for rp in role_perms:
                m_code = rp.module.code
                norm_code = cls.MODULE_ALIAS_MAP.get(m_code, m_code)
                for code_key in (m_code, norm_code):
                    if code_key in effective_perms:
                        effective_perms[code_key]['view'] = bool(rp.can_view)
                        effective_perms[code_key]['add'] = bool(rp.can_add)
                        effective_perms[code_key]['edit'] = bool(rp.can_edit)
                        effective_perms[code_key]['delete'] = bool(rp.can_delete)
                        effective_perms[code_key]['approve'] = bool(rp.can_approve)
                        effective_perms[code_key]['reject'] = bool(rp.can_reject)
                        effective_perms[code_key]['export'] = bool(rp.can_export)
                        effective_perms[code_key]['print'] = bool(rp.can_print)
                        effective_perms[code_key]['verify'] = bool(rp.can_approve)

        # 3. Duty Permissions Overlay (with Privilege Ceiling check)
        for a in active_duties:
            duty = a.duty
            if not duty or duty.status != 'active':
                continue

            duty_perms = duty.permissions.all()
            ceiling_role = duty.privilege_ceiling_role
            ceiling_perm_map = {}
            if ceiling_role:
                for cp in ceiling_role.permissions.select_related('module').all():
                    ceiling_perm_map[cp.module.code] = cp
                    ceiling_perm_map[cls.MODULE_ALIAS_MAP.get(cp.module.code, cp.module.code)] = cp

            for dp in duty_perms:
                m_code = dp.module_name
                norm_code = cls.MODULE_ALIAS_MAP.get(m_code, m_code)

                for code_key in (m_code, norm_code):
                    if code_key in effective_perms:
                        for act in ['view', 'add', 'edit', 'delete', 'approve', 'reject', 'verify', 'export', 'print', 'download', 'assign']:
                            val = getattr(dp, f'can_{act}', False)
                            if val:
                                # Ceiling check: if ceiling exists, action must be enabled in ceiling role!
                                if ceiling_role:
                                    cp = ceiling_perm_map.get(code_key)
                                    if not cp or not getattr(cp, f'can_{act}', False):
                                        continue  # Blocked by privilege ceiling!
                                effective_perms[code_key][act] = True

        # 4. Location Boundaries aggregation
        scoped_hostel_id = None
        if profile and profile.hostel_id:
            scoped_hostel_id = profile.hostel_id
        elif staff and staff.hostel_id:
            scoped_hostel_id = staff.hostel_id

        scoped_building_ids = set()
        scoped_block_names = set()
        scoped_floor_numbers = set()
        scoped_room_ids = set()
        scoped_specific_locations = []
        is_global_org_scoped = False
        is_own_only = False

        if active_duties:
            for a in active_duties:
                duty = a.duty
                scope = duty.data_scope if duty else 'BUILDING'

                if scope == 'ORGANIZATION':
                    is_global_org_scoped = True
                    if a.hostel_id:
                        scoped_hostel_id = a.hostel_id
                elif scope == 'OWN':
                    is_own_only = True
                elif scope == 'BUILDING':
                    if a.building_id:
                        scoped_building_ids.add(a.building_id)
                elif scope == 'LOCATION':
                    if a.building_id:
                        scoped_building_ids.add(a.building_id)
                    if a.block:
                        scoped_block_names.add(a.block.strip().upper())
                    if a.floor is not None:
                        scoped_floor_numbers.add(a.floor)
                    if a.room_id:
                        scoped_room_ids.add(a.room_id)
                    if a.specific_location:
                        scoped_specific_locations.append(a.specific_location)
        else:
            # No duties: fallback to entire assigned hostel or own records
            is_global_org_scoped = True

        return UserDashboardContext(
            user=user,
            staff=staff,
            role=role,
            is_role_valid=is_role_valid,
            role_name=role_name,
            active_duties=active_duties,
            effective_perms=effective_perms,
            scoped_hostel_id=scoped_hostel_id,
            scoped_building_ids=list(scoped_building_ids),
            scoped_block_names=list(scoped_block_names),
            scoped_floor_numbers=list(scoped_floor_numbers),
            scoped_room_ids=list(scoped_room_ids),
            scoped_specific_locations=scoped_specific_locations,
            is_global_org_scoped=is_global_org_scoped,
            is_own_only=is_own_only
        )

    @classmethod
    def get_scoped_kpis(cls, ctx):
        """Calculates statistical KPIs strictly scoped to user's authorized locations."""
        if not ctx.is_role_valid:
            return {}

        kpis = {}
        today = timezone.localtime(timezone.now()).date()

        # ── 1. Students KPI ──
        if ctx.can('student', 'view'):
            sqs = Student.objects.all()
            if ctx.scoped_hostel_id:
                sqs = sqs.filter(hostel_id=ctx.scoped_hostel_id)
            if ctx.scoped_building_ids:
                sqs = sqs.filter(allocated_beds__room__building_id__in=ctx.scoped_building_ids)
            if ctx.scoped_block_names:
                sqs = sqs.filter(allocated_beds__room__block__in=ctx.scoped_block_names)
            if ctx.scoped_floor_numbers:
                sqs = sqs.filter(allocated_beds__room__floor__in=ctx.scoped_floor_numbers)
            if ctx.scoped_room_ids:
                sqs = sqs.filter(allocated_beds__room_id__in=ctx.scoped_room_ids)
            sqs = sqs.distinct()

            total_s = sqs.count()
            active_s = sqs.filter(status='Active').count()
            kpis['student'] = {
                'total': total_s,
                'active': active_s,
                'inactive': total_s - active_s,
                'male': sqs.filter(gender='Male').count(),
                'female': sqs.filter(gender='Female').count(),
            }

        # ── 2. Rooms & Beds KPI ──
        if ctx.can('room', 'view'):
            rqs = Room.objects.all()
            if ctx.scoped_building_ids:
                rqs = rqs.filter(building_id__in=ctx.scoped_building_ids)
            if ctx.scoped_block_names:
                rqs = rqs.filter(block__in=ctx.scoped_block_names)
            if ctx.scoped_floor_numbers:
                rqs = rqs.filter(floor__in=ctx.scoped_floor_numbers)
            if ctx.scoped_room_ids:
                rqs = rqs.filter(id__in=ctx.scoped_room_ids)

            total_rooms = rqs.count()
            bed_qs = Bed.objects.filter(room__in=rqs)
            total_beds = bed_qs.count()
            occupied_beds = bed_qs.filter(student__isnull=False).count()
            vacant_beds = total_beds - occupied_beds
            occ_pct = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0.0

            kpis['room'] = {
                'total_rooms': total_rooms,
                'total_beds': total_beds,
                'occupied_beds': occupied_beds,
                'vacant_beds': vacant_beds,
                'occupancy_pct': occ_pct
            }

        # ── 3. Leaves & Gate Activity KPI ──
        if ctx.can('leave', 'view'):
            lqs = HostelLeave.objects.all()
            if ctx.scoped_hostel_id:
                lqs = lqs.filter(student__hostel_id=ctx.scoped_hostel_id)
            if ctx.scoped_building_ids:
                lqs = lqs.filter(student__allocated_beds__room__building_id__in=ctx.scoped_building_ids)

            pending_leaves = lqs.filter(status='pending').count()
            approved_today = lqs.filter(status='approved', leave_from=today).count()
            students_outside = lqs.filter(status='approved', exit_verified=True, entry_verified=False).count()
            pending_exits = lqs.filter(status='approved', exit_verified=False, leave_from__lte=today).count()

            kpis['leave'] = {
                'pending_leaves': pending_leaves,
                'approved_today': approved_today,
                'students_outside': students_outside,
                'pending_exits': pending_exits,
            }

        # ── 4. Complaints & Tasks KPI ──
        if ctx.can('complaint', 'view') or ctx.staff:
            cqs = ComplaintTicket.objects.all()
            if ctx.scoped_building_ids:
                cqs = cqs.filter(student__allocated_beds__room__building_id__in=ctx.scoped_building_ids)

            my_assigned = cqs.filter(assigned_to=ctx.staff, status__in=['pending', 'assigned', 'in_progress']).count() if ctx.staff else 0
            open_count = cqs.filter(status__in=['pending', 'assigned', 'in_progress']).count()
            resolved_count = cqs.filter(status='resolved').count()

            kpis['complaint'] = {
                'my_assigned': my_assigned,
                'open_tickets': open_count,
                'resolved': resolved_count,
            }

        # ── 5. Attendance KPI ──
        if ctx.can('attendance', 'view'):
            att_qs = Attendance.objects.filter(date=today)
            if ctx.scoped_building_ids:
                att_qs = att_qs.filter(student__allocated_beds__room__building_id__in=ctx.scoped_building_ids)

            present_count = att_qs.filter(status='Present').count()
            absent_count = att_qs.filter(status='Absent').count()
            total_marked = att_qs.count()
            att_pct = round((present_count / total_marked * 100), 1) if total_marked > 0 else 0.0

            kpis['attendance'] = {
                'marked_today': total_marked,
                'present': present_count,
                'absent': absent_count,
                'attendance_pct': att_pct,
            }

        # ── 6. Fee Collections KPI (e.g. Accountant) ──
        if ctx.can('fee', 'view'):
            fqs = StudentFeePayment.objects.all()
            if ctx.scoped_hostel_id:
                fqs = fqs.filter(student__hostel_id=ctx.scoped_hostel_id)
            if ctx.scoped_building_ids:
                fqs = fqs.filter(student__allocated_beds__room__building_id__in=ctx.scoped_building_ids)

            month_start = today.replace(day=1)
            monthly_total = fqs.filter(payment_date__gte=month_start).aggregate(s=Sum('amount_paid'))['s'] or 0.0
            total_collected = fqs.aggregate(s=Sum('amount_paid'))['s'] or 0.0

            kpis['fee'] = {
                'monthly_collected': float(monthly_total),
                'total_collected': float(total_collected),
                'transaction_count': fqs.count(),
            }

        # ── 7. Duty & Shift Compliance KPI ──
        active_count = len(ctx.active_duties)
        on_shift_count = sum(1 for a in ctx.active_duties if getattr(a, 'is_on_shift_now', False))
        kpis['duty'] = {
            'total_active': active_count,
            'on_shift_now': on_shift_count,
            'is_on_shift': on_shift_count > 0,
            'has_duties': active_count > 0,
        }

        return kpis

    @classmethod
    def get_actionable_tasks(cls, ctx):
        """Assembles actionable items (complaints assigned to staff, approvals, gate exit checks)."""
        if not ctx.is_role_valid:
            return []

        tasks = []
        today = timezone.localtime(timezone.now()).date()

        # 1. Complaints assigned directly to this staff
        if ctx.staff:
            assigned_c = ComplaintTicket.objects.filter(
                assigned_to=ctx.staff,
                status__in=['pending', 'assigned', 'in_progress']
            ).select_related('student').order_by('-created_at')[:6]

            for c in assigned_c:
                tasks.append({
                    'id': f"complaint_{c.id}",
                    'category': 'Maintenance / Complaint',
                    'title': f"#{c.id} - {c.title}",
                    'description': c.description[:120] + ('...' if len(c.description) > 120 else ''),
                    'priority': 'high' if c.category in ('electricity', 'room') else 'medium',
                    'status': c.get_status_display(),
                    'created_at': c.created_at,
                    'action_url': f"/complaints/",
                    'action_label': 'Resolve',
                    'type': 'complaint'
                })

        # 2. Pending leaves needing approval
        if ctx.can('leave', 'approve'):
            lqs = HostelLeave.objects.filter(status='pending').select_related('student')
            if ctx.scoped_building_ids:
                lqs = lqs.filter(student__allocated_beds__room__building_id__in=ctx.scoped_building_ids)
            lqs = lqs.order_by('-created_at')[:6]

            for l in lqs:
                tasks.append({
                    'id': f"leave_{l.id}",
                    'category': 'Leave Approval',
                    'title': f"Leave Request: {l.student.name}",
                    'description': f"Reason: {l.reason or 'Personal'} ({l.leave_from} to {l.leave_to})",
                    'priority': 'medium',
                    'status': 'Pending Approval',
                    'created_at': l.created_at if hasattr(l, 'created_at') else None,
                    'action_url': f"/leave/pending_leave/",
                    'action_label': 'Review',
                    'leave_id': l.id,
                    'type': 'leave_approval'
                })

        # 3. Gate Pass Verifications (if user has gate/security duty)
        if ctx.can('leave', 'verify'):
            exits = HostelLeave.objects.filter(
                status='approved',
                exit_verified=False,
                leave_from__lte=today
            ).select_related('student').order_by('leave_from')[:6]

            for ex in exits:
                tasks.append({
                    'id': f"gate_exit_{ex.id}",
                    'category': 'Gate Pass Verification',
                    'title': f"Exit Verification: {ex.student.name}",
                    'description': f"Scheduled exit today. Destination: {getattr(ex, 'destination', 'Local')}",
                    'priority': 'critical',
                    'status': 'Awaiting Exit Verification',
                    'created_at': None,
                    'action_url': f"/leave/gate_pass_management/",
                    'action_label': 'Verify Exit',
                    'leave_id': ex.id,
                    'type': 'gate_verification'
                })

        # 4. Active Duty Instructions
        for a in ctx.active_duties:
            if a.description:
                tasks.append({
                    'id': f"duty_task_{a.id}",
                    'category': 'Duty Protocol',
                    'title': f"{a.duty_title} Standing Orders",
                    'description': a.description,
                    'priority': a.duty.priority if a.duty else 'medium',
                    'status': 'Active Protocol',
                    'created_at': None,
                    'action_url': '#',
                    'action_label': 'Acknowledge',
                    'type': 'duty_order'
                })

        return tasks

    @classmethod
    def get_shift_schedule(cls, ctx):
        """Builds a 7-day schedule array with visual status indicators."""
        today = timezone.localtime(timezone.now()).date()
        weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
        current_day_code = weekday_map.get(today.weekday())

        days = [
            {'code': 'MON', 'name': 'Monday', 'is_today': current_day_code == 'MON', 'duties': []},
            {'code': 'TUE', 'name': 'Tuesday', 'is_today': current_day_code == 'TUE', 'duties': []},
            {'code': 'WED', 'name': 'Wednesday', 'is_today': current_day_code == 'WED', 'duties': []},
            {'code': 'THU', 'name': 'Thursday', 'is_today': current_day_code == 'THU', 'duties': []},
            {'code': 'FRI', 'name': 'Friday', 'is_today': current_day_code == 'FRI', 'duties': []},
            {'code': 'SAT', 'name': 'Saturday', 'is_today': current_day_code == 'SAT', 'duties': []},
            {'code': 'SUN', 'name': 'Sunday', 'is_today': current_day_code == 'SUN', 'duties': []},
        ]

        for a in ctx.active_duties:
            active_days = a.working_days_list
            time_display = "--:--"
            if a.shift_start and a.shift_end:
                time_display = f"{a.shift_start.strftime('%H:%M')} – {a.shift_end.strftime('%H:%M')}"
            elif a.duty and a.duty.start_time and a.duty.end_time:
                time_display = f"{a.duty.start_time.strftime('%H:%M')} – {a.duty.end_time.strftime('%H:%M')}"

            for d in days:
                if d['code'] in active_days:
                    d['duties'].append({
                        'title': a.duty_title,
                        'time': time_display,
                        'location': a.location_display,
                        'priority': a.duty.priority if a.duty else 'medium',
                        'is_live': d['is_today'] and getattr(a, 'is_on_shift_now', False)
                    })

        return days

    @classmethod
    def get_quick_actions(cls, ctx):
        """Returns authorized action shortcuts based on effective permissions."""
        if not ctx.is_role_valid:
            return []

        actions = []

        if ctx.can('student', 'add'):
            actions.append({
                'title': 'Add Student',
                'url': '/student/create/',
                'icon': 'bi-person-plus-fill',
                'bg': 'primary',
                'desc': 'Register student record'
            })

        if ctx.can('leave', 'verify'):
            actions.append({
                'title': 'Gate Pass Verification',
                'url': '/leave/gate_pass_management/',
                'icon': 'bi-qr-code-scan',
                'bg': 'success',
                'desc': 'Scan QR or verify student entry/exit'
            })

        if ctx.can('leave', 'approve'):
            actions.append({
                'title': 'Approve Leaves',
                'url': '/leave/pending_leave/',
                'icon': 'bi-card-checklist',
                'bg': 'warning',
                'desc': 'Review student leave applications'
            })

        if ctx.can('complaint', 'add') or ctx.can('complaint', 'edit'):
            actions.append({
                'title': 'Complaints Desk',
                'url': '/complaints/',
                'icon': 'bi-tools',
                'bg': 'danger',
                'desc': 'Track and resolve maintenance issues'
            })

        if ctx.can('room', 'view'):
            actions.append({
                'title': 'Rooms & Beds',
                'url': '/room/',
                'icon': 'bi-building-gear',
                'bg': 'info',
                'desc': 'View rooms and check occupancy'
            })

        if ctx.can('attendance', 'add') or ctx.can('attendance', 'edit'):
            actions.append({
                'title': 'Take Attendance',
                'url': '/leave/attendance/',
                'icon': 'bi-calendar-check-fill',
                'bg': 'secondary',
                'desc': 'Record daily student roll call'
            })

        if ctx.can('fee', 'view'):
            actions.append({
                'title': 'Fee Management',
                'url': '/student/fees/',
                'icon': 'bi-cash-stack',
                'bg': 'success',
                'desc': 'Review collections and dues'
            })

        if ctx.active_duties:
            actions.append({
                'title': 'Duty Handover',
                'url': '#modalHandoverRequest',
                'modal': True,
                'icon': 'bi-arrow-left-right',
                'bg': 'dark',
                'desc': 'Initiate shift handover to colleague'
            })

        return actions

    @classmethod
    def get_location_overview(cls, ctx):
        """Assembles overview of assigned building, blocks, floors, and rooms."""
        if not ctx.is_role_valid:
            return None

        buildings_data = []
        if ctx.scoped_building_ids:
            buildings = HostelBuilding.objects.filter(id__in=ctx.scoped_building_ids, is_archived=False)
        elif ctx.scoped_hostel_id:
            buildings = HostelBuilding.objects.filter(hostel_id=ctx.scoped_hostel_id, is_archived=False)
        else:
            buildings = HostelBuilding.objects.filter(is_active=True, is_archived=False)[:3]

        for b in buildings:
            room_count = b.rooms.count()
            bed_count = Bed.objects.filter(room__building=b).count()
            occ_count = Bed.objects.filter(room__building=b, student__isnull=False).count()
            pct = round((occ_count / bed_count * 100), 1) if bed_count > 0 else 0.0

            buildings_data.append({
                'id': b.id,
                'name': b.name,
                'gender': b.gender,
                'total_floors': b.total_floors,
                'blocks': b.blocks,
                'room_count': room_count,
                'bed_count': bed_count,
                'occupied_count': occ_count,
                'vacant_count': bed_count - occ_count,
                'occupancy_pct': pct
            })

        return {
            'buildings': buildings_data,
            'assigned_blocks': ctx.scoped_block_names,
            'assigned_floors': ctx.scoped_floor_numbers,
            'assigned_rooms': ctx.scoped_room_ids,
            'specific_locations': ctx.scoped_specific_locations,
        }

    @classmethod
    def get_operational_alerts(cls, ctx):
        """Produces live warnings and alerts based on role and active assignments."""
        alerts = []

        if not ctx.is_role_valid:
            alerts.append({
                'type': 'danger',
                'icon': 'bi-shield-slash-fill',
                'title': 'Role Missing – Reassignment Required',
                'message': 'Your account does not have an active system role assigned. Access is currently locked under default-deny security. Please contact your Super Administrator.'
            })
            return alerts

        # On duty notification
        on_shift_duties = [a for a in ctx.active_duties if getattr(a, 'is_on_shift_now', False)]
        if on_shift_duties:
            duty_names = ", ".join(a.duty_title for a in on_shift_duties)
            alerts.append({
                'type': 'success',
                'icon': 'bi-broadcast-pin',
                'title': 'Active On Shift',
                'message': f"You are currently on duty for: {duty_names} ({on_shift_duties[0].location_display})."
            })
        elif ctx.active_duties:
            alerts.append({
                'type': 'info',
                'icon': 'bi-clock',
                'title': 'Duty Standby',
                'message': f"You have {len(ctx.active_duties)} assigned duty schedule(s). Check your weekly timetable below."
            })
        else:
            alerts.append({
                'type': 'secondary',
                'icon': 'bi-info-circle',
                'title': 'No Active Duty Assignment',
                'message': 'You currently have no active duty assignments. Standard base role permissions apply.'
            })

        # Overdue Complaints in assigned area
        if ctx.can('complaint', 'view') and ctx.scoped_building_ids:
            overdue_c = ComplaintTicket.objects.filter(
                student__allocated_beds__room__building_id__in=ctx.scoped_building_ids,
                status='pending',
                created_at__lte=timezone.now() - datetime.timedelta(days=2)
            ).count()
            if overdue_c > 0:
                alerts.append({
                    'type': 'warning',
                    'icon': 'bi-exclamation-triangle-fill',
                    'title': 'Overdue Complaints Pending Attention',
                    'message': f"There are {overdue_c} complaint(s) in your assigned building older than 48 hours requiring attention."
                })

        return alerts

    @classmethod
    def get_recent_activities(cls, ctx, limit=8):
        """Fetches scoped recent audit log records."""
        if not ctx.is_role_valid:
            return []

        qs = AuditLog.objects.select_related('actor', 'target_user').order_by('-timestamp')

        # If user is scoped to a hostel:
        if ctx.scoped_hostel_id:
            qs = qs.filter(Q(hostel_id=ctx.scoped_hostel_id) | Q(actor=ctx.user))
        else:
            qs = qs.filter(actor=ctx.user)

        return qs[:limit]

    @classmethod
    def get_widget_preferences(cls, user, role):
        """Returns the list of enabled widget keys for this user."""
        all_keys = [w['key'] for w in cls.ALL_WIDGETS]

        # 1. Check User Dashboard Preference
        user_pref = UserDashboardPreference.objects.filter(user=user).first()
        if user_pref and user_pref.enabled_widgets:
            return user_pref.enabled_widgets

        # 2. Check Role Dashboard Config
        if role:
            role_config = RoleDashboardConfig.objects.filter(role=role).first()
            if role_config and role_config.default_widgets:
                return role_config.default_widgets

        # 3. Default: all widgets enabled
        return all_keys

    @classmethod
    def save_widget_preferences(cls, user, enabled_keys):
        """Saves user widget customization preferences."""
        valid_keys = [w['key'] for w in cls.ALL_WIDGETS if w['key'] in enabled_keys]
        pref, _ = UserDashboardPreference.objects.get_or_create(user=user)
        pref.enabled_widgets = valid_keys
        pref.save()
        return pref
