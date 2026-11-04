import datetime
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse

from authentication.models import Role, Module, RolePermission, UserProfile, Hostel, AuditLog
from hms.models import (
    StaffProfile, Duty, DutyPermission, DutyAssignment,
    UserDashboardPreference, RoleDashboardConfig, ComplaintTicket
)
from room.models import HostelBuilding, Room, Bed
from student.models import Student, Attendance, StudentFeePayment
from leave.models import HostelLeave
from hms.dashboard_services import DynamicDashboardService, UserDashboardContext


class DynamicDashboardTestSuite(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Modules
        self.mod_student, _ = Module.objects.get_or_create(code='student', defaults={'name': 'Student Registry'})
        self.mod_room, _ = Module.objects.get_or_create(code='room', defaults={'name': 'Rooms & Beds'})
        self.mod_leave, _ = Module.objects.get_or_create(code='leave', defaults={'name': 'Leave & Gate Pass'})
        self.mod_fee, _ = Module.objects.get_or_create(code='fee', defaults={'name': 'Fee Management'})
        self.mod_complaint, _ = Module.objects.get_or_create(code='complaint', defaults={'name': 'Complaints Desk'})

        # 2. Roles
        self.superadmin_role = Role.objects.create(name='Super Admin', is_superadmin=True, is_active=True)
        self.warden_role = Role.objects.create(name='Hostel Warden', is_superadmin=False, is_active=True)
        self.guard_role = Role.objects.create(name='Security Guard', is_superadmin=False, is_active=True)
        self.accountant_role = Role.objects.create(name='Accountant', is_superadmin=False, is_active=True)
        self.student_role = Role.objects.create(name='Student', is_superadmin=False, is_active=True)
        self.inactive_role = Role.objects.create(name='Archived Staff', is_superadmin=False, is_active=False)

        # Base permissions for Warden: student view/edit, leave view/approve, room view
        RolePermission.objects.create(role=self.warden_role, module=self.mod_student, can_view=True, can_edit=True)
        RolePermission.objects.create(role=self.warden_role, module=self.mod_leave, can_view=True, can_approve=True)
        RolePermission.objects.create(role=self.warden_role, module=self.mod_room, can_view=True)

        # Base permissions for Guard: leave view/verify
        RolePermission.objects.create(role=self.guard_role, module=self.mod_leave, can_view=True, can_approve=True)

        # Base permissions for Accountant: fee view/add
        RolePermission.objects.create(role=self.accountant_role, module=self.mod_fee, can_view=True, can_add=True)

        # 3. Users
        self.super_user = User.objects.create_superuser(username='superadmin', email='super@example.com', password='password123')
        UserProfile.objects.create(user=self.super_user, role=self.superadmin_role)

        self.warden_user = User.objects.create_user(username='warden_john', email='warden@example.com', password='password123')
        UserProfile.objects.create(user=self.warden_user, role=self.warden_role)
        self.warden_staff = StaffProfile.objects.create(user=self.warden_user, name='John Warden', email='warden@example.com', status='active')

        self.guard_user = User.objects.create_user(username='guard_ram', email='guard@example.com', password='password123')
        UserProfile.objects.create(user=self.guard_user, role=self.guard_role)
        self.guard_staff = StaffProfile.objects.create(user=self.guard_user, name='Ram Guard', email='guard@example.com', status='active')

        self.accountant_user = User.objects.create_user(username='acc_lisa', email='acc@example.com', password='password123')
        UserProfile.objects.create(user=self.accountant_user, role=self.accountant_role)
        self.acc_staff = StaffProfile.objects.create(user=self.accountant_user, name='Lisa Accountant', email='acc@example.com', status='active')

        self.student_user = User.objects.create_user(username='stu_alex', email='alex@example.com', password='password123')
        UserProfile.objects.create(user=self.student_user, role=self.student_role)

        self.norole_user = User.objects.create_user(username='norole_user', email='norole@example.com', password='password123')
        UserProfile.objects.create(user=self.norole_user, role=self.inactive_role)

        # 4. Hostels and Buildings
        self.hostel = Hostel.objects.create(name='Main Campus Hostel', code='H01')
        self.bldg_a = HostelBuilding.objects.create(name='Building Alpha', total_floors=3, blocks='Block A, Block B')
        self.bldg_b = HostelBuilding.objects.create(name='Building Beta', total_floors=3, blocks='Block A, Block B')

        # Rooms & Beds in Building A
        self.room_a1 = Room.objects.create(building=self.bldg_a, room_number='A-101', floor=1, block='A', capacity=2)
        self.bed_a1_1 = Bed.objects.create(room=self.room_a1, bed_number='Bed 1')
        self.bed_a1_2 = Bed.objects.create(room=self.room_a1, bed_number='Bed 2')

        # Rooms & Beds in Building B
        self.room_b1 = Room.objects.create(building=self.bldg_b, room_number='B-101', floor=1, block='A', capacity=2)
        self.bed_b1_1 = Bed.objects.create(room=self.room_b1, bed_number='Bed 1')

        # Students
        self.stu_a = Student.objects.create(
            user=self.student_user,
            name='Student Alpha',
            roll='STU-001',
            email='stu_a@example.com',
            gender='Male',
            status='Active',
            hostel=self.hostel
        )
        self.bed_a1_1.student = self.stu_a
        self.bed_a1_1.save()

        self.student_user_b = User.objects.create_user(username='stu_beta', email='beta@example.com', password='password123')
        self.stu_b = Student.objects.create(
            user=self.student_user_b,
            name='Student Beta',
            roll='STU-002',
            email='stu_b@example.com',
            gender='Female',
            status='Active',
            hostel=self.hostel
        )
        self.bed_b1_1.student = self.stu_b
        self.bed_b1_1.save()

    def test_superadmin_dashboard_preservation(self):
        """Super Admin dashboard is completely preserved without interference or replacement."""
        self.client.force_login(self.super_user)

        # 1. Root / redirects to superadmin_dashboard
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('superadmin_dashboard'), resp.url)

        # 2. Accessing superadmin_dashboard directly returns 200 and renders original template
        resp_sa = self.client.get(reverse('superadmin_dashboard'))
        self.assertEqual(resp_sa.status_code, 200)
        self.assertTemplateUsed(resp_sa, 'hms/superadmin_dashboard.html')

        # 3. Super admin trying to access dynamic-dashboard redirects back to superadmin_dashboard
        resp_dyn = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp_dyn.status_code, 302)
        self.assertIn(reverse('superadmin_dashboard'), resp_dyn.url)

    def test_student_dashboard_routing(self):
        """Student accessing / or /dynamic-dashboard/ redirects to student_dashboard."""
        self.client.force_login(self.student_user)

        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('student_app:student_dashboard'), resp.url)

        resp_dyn = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp_dyn.status_code, 302)
        self.assertIn(reverse('student_app:student_dashboard'), resp_dyn.url)

    def test_fail_closed_security_for_missing_or_inactive_role(self):
        """User with missing/inactive role gets fail-closed security and warning alert."""
        self.client.force_login(self.norole_user)

        resp = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'hms/dynamic_dashboard.html')

        ctx = resp.context['ctx']
        self.assertFalse(ctx.is_role_valid)
        self.assertEqual(ctx.role_name, "Role Missing – Reassignment Required")
        # Deny all permissions
        self.assertFalse(ctx.can('student', 'view'))
        self.assertFalse(ctx.can('room', 'view'))
        self.assertFalse(ctx.can('leave', 'approve'))

        # Check alert banner rendered in HTML
        self.assertContains(resp, "Role Missing – Reassignment Required")

    def test_dynamic_dashboard_for_accountant(self):
        """Dynamic dashboard dynamically generates Fee KPI and shortcuts for Accountant role without hardcoding."""
        StudentFeePayment.objects.create(student=self.stu_a, amount_paid=5000, payment_method='CASH')

        self.client.force_login(self.accountant_user)
        resp = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp.status_code, 200)

        ctx = resp.context['ctx']
        self.assertTrue(ctx.is_role_valid)
        self.assertEqual(ctx.role_name, 'Accountant')
        self.assertTrue(ctx.can('fee', 'view'))
        self.assertFalse(ctx.can('room', 'view'))  # Accountant does not have room permission

        kpis = resp.context['kpis']
        self.assertIn('fee', kpis)
        self.assertEqual(kpis['fee']['total_collected'], 5000.0)
        self.assertNotIn('room', kpis)  # Room KPI omitted for Accountant

    def test_location_based_scoping_for_building_warden(self):
        """Warden assigned to Building A sees only Building A students and beds in KPIs."""
        duty_warden = Duty.objects.create(
            name='Building A Warden Duty',
            category='supervision',
            data_scope='BUILDING',
            status='active'
        )
        DutyPermission.objects.create(duty=duty_warden, module_name='student', can_view=True)
        DutyPermission.objects.create(duty=duty_warden, module_name='room', can_view=True)

        DutyAssignment.objects.create(
            duty=duty_warden,
            staff=self.warden_staff,
            building=self.bldg_a,
            is_active=True,
            status='ACTIVE',
            start_date=timezone.now().date()
        )

        self.client.force_login(self.warden_user)
        resp = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp.status_code, 200)

        ctx = resp.context['ctx']
        self.assertIn(self.bldg_a.id, ctx.scoped_building_ids)
        self.assertNotIn(self.bldg_b.id, ctx.scoped_building_ids)

        kpis = resp.context['kpis']
        # Student count should only be 1 (stu_a in Building A), NOT stu_b (Building B)
        self.assertEqual(kpis['student']['total'], 1)
        # Room count should only be 1 (room_a1 in Building A), NOT room_b1
        self.assertEqual(kpis['room']['total_rooms'], 1)

    def test_multiple_active_duty_assignments(self):
        """User with multiple active duties sees all duties in context and on dashboard."""
        duty_night = Duty.objects.create(name='Night Patrolling', category='security', status='active')
        duty_gate = Duty.objects.create(name='Main Gate Security', category='security', status='active')

        DutyAssignment.objects.create(
            duty=duty_night,
            staff=self.guard_staff,
            building=self.bldg_a,
            is_active=True,
            status='ACTIVE',
            start_date=timezone.now().date()
        )
        DutyAssignment.objects.create(
            duty=duty_gate,
            staff=self.guard_staff,
            specific_location='Main Campus North Gate',
            is_active=True,
            status='ACTIVE',
            start_date=timezone.now().date()
        )

        self.client.force_login(self.guard_user)
        resp = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp.status_code, 200)

        ctx = resp.context['ctx']
        self.assertEqual(len(ctx.active_duties), 2)
        self.assertContains(resp, "Night Patrolling")
        self.assertContains(resp, "Main Gate Security")

    def test_privilege_ceiling_enforcement(self):
        """Duty cannot grant permissions beyond privilege ceiling role."""
        ceiling_role = Role.objects.create(name='Restricted Ceiling Role', is_active=True)
        # Ceiling role only allows viewing students, NOT deleting students
        RolePermission.objects.create(role=ceiling_role, module=self.mod_student, can_view=True, can_delete=False)

        duty = Duty.objects.create(
            name='Temporary Admin Duty',
            status='active',
            privilege_ceiling_role=ceiling_role
        )
        # Duty template attempts to grant student deletion
        DutyPermission.objects.create(duty=duty, module_name='student', can_view=True, can_delete=True)

        DutyAssignment.objects.create(
            duty=duty,
            staff=self.guard_staff,
            is_active=True,
            status='ACTIVE',
            start_date=timezone.now().date()
        )

        ctx = DynamicDashboardService.build_user_dashboard_context(self.guard_user)
        # can_view is permitted by ceiling
        self.assertTrue(ctx.can('student', 'view'))
        # can_delete MUST be blocked by privilege ceiling!
        self.assertFalse(ctx.can('student', 'delete'))

    def test_widget_preferences_save_and_load(self):
        """User can customize dashboard widget visibility and preferences are saved."""
        self.client.force_login(self.warden_user)

        enabled = ['kpis', 'quick_actions']
        resp = self.client.post(reverse('dashboard_save_widgets'), {'widgets': enabled})
        self.assertEqual(resp.status_code, 302)

        # Check saved in DB
        pref = UserDashboardPreference.objects.get(user=self.warden_user)
        self.assertEqual(pref.enabled_widgets, enabled)

        # Reload dashboard
        resp2 = self.client.get(reverse('dynamic_dashboard'))
        self.assertEqual(resp2.context['enabled_widgets'], enabled)

    def test_live_kpi_ajax_endpoint(self):
        """Live KPI AJAX endpoint returns scoped statistics in JSON."""
        self.client.force_login(self.warden_user)
        resp = self.client.get(reverse('dashboard_live_kpis'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('kpis', data)

    def test_quick_approve_leave_action(self):
        """Authorized user can 1-click approve leave from actionable tasks."""
        leave = HostelLeave.objects.create(
            student=self.stu_a,
            leave_from=timezone.now().date(),
            leave_to=timezone.now().date() + datetime.timedelta(days=2),
            reason='Family visit',
            status='pending'
        )

        self.client.force_login(self.warden_user)
        resp = self.client.post(reverse('dashboard_quick_approve_leave', args=[leave.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')

        leave.refresh_from_db()
        self.assertEqual(leave.status, 'approved')
        self.assertEqual(leave.approved_by, self.warden_user)
