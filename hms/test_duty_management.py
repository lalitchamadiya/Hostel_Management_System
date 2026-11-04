import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied

from authentication.models import Hostel, Role, RolePermission, Module, UserProfile, AuditLog
from room.models import HostelBuilding, Room
from student.models import Student
from hms.models import StaffProfile, Duty, DutyPermission, DutyAssignment, DutyApprovalLog
from hms.duty_services import DutyConflictService, DutyAuthorizationService, DutyWorkflowService


class EnterpriseDutyManagementTests(TestCase):
    def setUp(self):
        # 1. Base Organization & Buildings
        self.hostel = Hostel.objects.create(name='Test Campus Hostel', code='TCH01', is_active=True)
        self.building_a = HostelBuilding.objects.create(name='Block Alpha', total_floors=3, blocks='A,B', is_active=True)
        self.building_b = HostelBuilding.objects.create(name='Block Beta', total_floors=2, blocks='C', is_active=True)
        self.room_101 = Room.objects.create(building=self.building_a, room_number='101', floor=1, block='A')
        self.room_201 = Room.objects.create(building=self.building_b, room_number='201', floor=2, block='C')

        # 2. Modules
        self.mod_student = Module.objects.create(name='Student Management', code='student')
        self.mod_room = Module.objects.create(name='Room Management', code='room')
        self.mod_duty = Module.objects.create(name='Duty Management', code='duty_management')

        # 3. Roles
        self.super_role = Role.objects.create(name='SuperAdmin', is_superadmin=True, is_active=True)
        self.warden_role = Role.objects.create(name='Warden Role', is_active=True)
        self.guard_role = Role.objects.create(name='Guard Role', is_active=True)

        # Base role permissions
        RolePermission.objects.create(role=self.warden_role, module=self.mod_student, can_view=True, can_add=True, can_edit=True)
        RolePermission.objects.create(role=self.warden_role, module=self.mod_duty, can_view=True, can_add=True, can_edit=True, can_approve=True, can_reject=True)
        RolePermission.objects.create(role=self.guard_role, module=self.mod_student, can_view=True)

        # 4. Users and Staff
        # Supervisor
        self.user_supervisor = User.objects.create_user(username='supervisor1', password='password123', email='supervisor@hms.com')
        UserProfile.objects.create(user=self.user_supervisor, role=self.warden_role, hostel=self.hostel)
        self.staff_supervisor = StaffProfile.objects.create(
            user=self.user_supervisor, hostel=self.hostel, name='Senior Supervisor', email='supervisor@hms.com', phone='+919876543210', status='active'
        )

        # Staff 1
        self.user_staff1 = User.objects.create_user(username='staff1', password='password123', email='staff1@hms.com')
        UserProfile.objects.create(user=self.user_staff1, role=self.guard_role, hostel=self.hostel)
        self.staff1 = StaffProfile.objects.create(
            user=self.user_staff1, hostel=self.hostel, name='Ramesh Guard', email='staff1@hms.com', phone='+919876543211', status='active'
        )

        # Staff 2 (Substitute)
        self.user_staff2 = User.objects.create_user(username='staff2', password='password123', email='staff2@hms.com')
        UserProfile.objects.create(user=self.user_staff2, role=self.guard_role, hostel=self.hostel)
        self.staff2 = StaffProfile.objects.create(
            user=self.user_staff2, hostel=self.hostel, name='Suresh Guard', email='staff2@hms.com', phone='+919876543212', status='active'
        )

        # 5. Duty Template
        self.duty_template = Duty.objects.create(
            name='Night Security Guard',
            category='Security',
            priority='high',
            data_scope='BUILDING',
            requires_approval=True,
            working_days='MON,TUE,WED,THU,FRI,SAT,SUN',
            start_time=datetime.time(20, 0),
            end_time=datetime.time(6, 0),
            repeat_type='daily',
            status='active'
        )
        # Grant view and verify permissions to students module
        DutyPermission.objects.create(
            duty=self.duty_template,
            module_name='student',
            can_view=True,
            can_verify=True,
            can_delete=False
        )

        self.client = Client()

    def test_dynamic_role_integration(self):
        """Verify dynamic role properties on StaffProfile."""
        self.assertEqual(self.staff1.assigned_role, self.guard_role)
        self.assertTrue(self.staff1.has_valid_role)
        self.assertEqual(self.staff1.role_display_name, 'Guard Role')

    def test_privilege_ceiling_enforcement(self):
        """Verify that duty permissions cannot exceed privilege ceiling role."""
        ceiling_role = Role.objects.create(name='Restricted Ceiling', is_active=True)
        RolePermission.objects.create(role=ceiling_role, module=self.mod_student, can_view=True, can_delete=False)

        duty_with_ceiling = Duty.objects.create(
            name='Ceiling Restricted Duty',
            data_scope='BUILDING',
            privilege_ceiling_role=ceiling_role,
            status='active'
        )
        DutyPermission.objects.create(
            duty=duty_with_ceiling,
            module_name='student',
            can_view=True,
            can_delete=True
        )

        assignment = DutyAssignment.objects.create(
            duty=duty_with_ceiling,
            staff=self.staff1,
            duty_title='Checkpoint Guard',
            building=self.building_a,
            status='ACTIVE',
            is_active=True
        )

        # can_view is allowed by ceiling
        granted_view, _ = DutyAuthorizationService.evaluate_duty_permission(self.user_staff1, 'student', 'view')
        self.assertTrue(granted_view)

        # can_delete is blocked because ceiling role does not have can_delete!
        granted_delete, _ = DutyAuthorizationService.evaluate_duty_permission(self.user_staff1, 'student', 'delete')
        self.assertFalse(granted_delete)

    def test_temporal_shift_validity_and_fail_closed(self):
        """Verify shift window check and fail-closed out-of-shift behavior."""
        today = timezone.localtime(timezone.now()).date()
        weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
        today_code = weekday_map[today.weekday()]

        # Active today with daytime hours 08:00 to 18:00
        assignment = DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff1,
            duty_title='Day Warden',
            building=self.building_a,
            start_date=today,
            end_date=today,
            shift_start=datetime.time(8, 0),
            shift_end=datetime.time(18, 0),
            working_days=today_code,
            status='ACTIVE',
            is_active=True
        )

        # Test within shift window (12:00 PM today)
        dt_during = timezone.make_aware(datetime.datetime.combine(today, datetime.time(12, 0)))
        self.assertTrue(DutyAuthorizationService.is_assignment_active_now(assignment, target_dt=dt_during))

        # Test outside shift window (22:00 PM today)
        dt_after = timezone.make_aware(datetime.datetime.combine(today, datetime.time(22, 0)))
        self.assertFalse(DutyAuthorizationService.is_assignment_active_now(assignment, target_dt=dt_after))

        # Test day not in working days (e.g. exclude today)
        other_days = [d for d in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] if d != today_code]
        assignment.working_days = ",".join(other_days)
        assignment.save()
        self.assertFalse(DutyAuthorizationService.is_assignment_active_now(assignment, target_dt=dt_during))

    def test_location_based_scoping_and_anti_idor(self):
        """Verify building and room scope enforcement."""
        duty_all_day = Duty.objects.create(
            name='All Day Scoped Duty',
            data_scope='BUILDING',
            status='active'
        )
        DutyPermission.objects.create(
            duty=duty_all_day,
            module_name='student',
            can_view=True
        )

        assignment = DutyAssignment.objects.create(
            duty=duty_all_day,
            staff=self.staff1,
            duty_title='Building Alpha Duty',
            building=self.building_a,
            status='ACTIVE',
            is_active=True
        )

        # Object in Building A passes
        granted_a, _ = DutyAuthorizationService.evaluate_duty_permission(
            self.user_staff1, 'student', 'view', target_obj=self.room_101
        )
        self.assertTrue(granted_a)

        # Object in Building B is blocked!
        granted_b, _ = DutyAuthorizationService.evaluate_duty_permission(
            self.user_staff1, 'student', 'view', target_obj=self.room_201
        )
        self.assertFalse(granted_b)

        # Location Hierarchy validation helper
        valid, err = DutyConflictService.validate_location_hierarchy(
            building_id=self.building_a.id, floor=1, room_id=self.room_101.id
        )
        self.assertTrue(valid)

        # Invalid: Room 201 does not belong to Building Alpha
        invalid, err_msg = DutyConflictService.validate_location_hierarchy(
            building_id=self.building_a.id, floor=1, room_id=self.room_201.id
        )
        self.assertFalse(invalid)
        self.assertIn("does not belong", err_msg)

    def test_shift_conflict_detection(self):
        """Verify overlapping shift detection on matching days and hours."""
        today = timezone.localtime(timezone.now()).date()

        # Existing assignment: 09:00 to 17:00 Mon-Fri
        DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff1,
            duty_title='Morning Guard',
            start_date=today,
            shift_start=datetime.time(9, 0),
            shift_end=datetime.time(17, 0),
            working_days='MON,TUE,WED,THU,FRI',
            status='ACTIVE',
            is_active=True
        )

        # Conflicting assignment: 14:00 to 22:00 on Wednesday
        has_conf, conf_assign, reason = DutyConflictService.detect_conflict(
            staff_id=self.staff1.id,
            start_date=today,
            shift_start=datetime.time(14, 0),
            shift_end=datetime.time(22, 0),
            working_days='WED'
        )
        self.assertTrue(has_conf)
        self.assertIn("Overlaps with existing duty", reason)

        # Non-conflicting: Weekend only
        no_conf, _, _ = DutyConflictService.detect_conflict(
            staff_id=self.staff1.id,
            start_date=today,
            shift_start=datetime.time(14, 0),
            shift_end=datetime.time(22, 0),
            working_days='SAT,SUN'
        )
        self.assertFalse(no_conf)

    def test_approval_workflow_and_self_approval_prevention(self):
        """Verify supervisor approval workflow and strict self-approval guard."""
        # Assignment requiring approval
        assignment = DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff1,
            duty_title='Patrol Guard',
            supervisor=self.user_supervisor,
            status='PENDING_APPROVAL',
            is_active=True
        )

        # Senior supervisor approves assignment
        DutyWorkflowService.approve_assignment(assignment, self.user_supervisor, notes='All verified')
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, 'APPROVED')
        self.assertEqual(assignment.approved_by, self.user_supervisor)
        self.assertTrue(DutyApprovalLog.objects.filter(assignment=assignment, action='APPROVED').exists())

        # Self-approval guard test: staff cannot approve their own duty!
        self_assignment = DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff_supervisor,
            duty_title='Supervisor Field Patrol',
            status='PENDING_APPROVAL',
            is_active=True
        )
        with self.assertRaises(PermissionDenied):
            DutyWorkflowService.approve_assignment(self_assignment, self.user_supervisor)

    def test_emergency_handover(self):
        """Verify duty handover to substitute staff with audit log."""
        assignment = DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff1,
            duty_title='Main Gate Duty',
            status='ACTIVE',
            is_active=True
        )

        DutyWorkflowService.handover_duty(
            assignment, self.staff2, self.user_supervisor, reason='Medical emergency leave'
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.staff, self.staff2)
        self.assertEqual(assignment.handover_from, self.staff1)
        self.assertEqual(assignment.handover_to, self.staff2)
        self.assertEqual(assignment.handover_reason, 'Medical emergency leave')
        self.assertTrue(DutyApprovalLog.objects.filter(assignment=assignment, action='HANDOVER').exists())

    def test_immediate_revocation_killswitch(self):
        """Verify emergency killswitch cuts access immediately."""
        assignment = DutyAssignment.objects.create(
            duty=self.duty_template,
            staff=self.staff1,
            duty_title='Sensitive Archive Access',
            status='ACTIVE',
            is_active=True
        )

        DutyWorkflowService.revoke_duty(
            assignment, self.user_supervisor, reason='Security breach protocol'
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, 'REVOKED')
        self.assertFalse(assignment.is_active)
        self.assertFalse(DutyAuthorizationService.is_assignment_active_now(assignment))

    def test_views_and_ajax_endpoints(self):
        """Verify HTTP endpoints for duty dashboard and AJAX hierarchy."""
        self.client.force_login(self.user_supervisor)

        # GET /staff/duties/
        res = self.client.get(reverse('duty_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Staff Duties & Workforce Access Control')
        self.assertContains(res, 'Active Assignments')
        self.assertContains(res, 'Calendar Scheduler')
        self.assertContains(res, 'RBDAC Duty Permissions')

        # GET /staff/duties/ajax/get-floors/?building_id=...
        res_floors = self.client.get(reverse('duty_get_floors'), {'building_id': self.building_a.id})
        self.assertEqual(res_floors.status_code, 200)
        data = res_floors.json()
        self.assertEqual(len(data['floors']), 3)
        self.assertIn('A', data['blocks'])

        # GET /staff/duties/ajax/get-rooms/?building_id=...&floor=1
        res_rooms = self.client.get(reverse('duty_get_rooms'), {'building_id': self.building_a.id, 'floor': 1})
        self.assertEqual(res_rooms.status_code, 200)
        rooms_data = res_rooms.json()
        self.assertEqual(len(rooms_data['rooms']), 1)
        self.assertEqual(rooms_data['rooms'][0]['room_number'], '101')
