from django.utils import timezone
from django.test import TestCase, RequestFactory

from django.contrib.auth.models import User, AnonymousUser

from django.contrib.sessions.middleware import SessionMiddleware

from django.contrib.messages.middleware import MessageMiddleware

from .middleware import AutoLogout

from .models import Role, PermissionElement, RoleElementPermission, UserProfile

from .decorators import check_element_perm

from .templatetags.rbac_tags import has_element_perm





class AutoLogoutMiddlewareTest(TestCase):

    def setUp(self):

        self.factory = RequestFactory()

        self.user = User.objects.create_user(username='testuser', password='password')



    def test_anonymous_user_passes_through(self):

        request = self.factory.get('/')

        request.user = AnonymousUser()

        

        middleware = AutoLogout(lambda req: "passed")

        response = middleware(request)

        self.assertEqual(response, "passed")



    def test_authenticated_user_passes_through_active_session(self):

        request = self.factory.get('/')

        request.user = self.user

        

        # Setup session support

        middleware_session = SessionMiddleware(lambda req: None)

        middleware_session.process_request(request)

        request.session.save()

        

        # Setup messages support

        middleware_msg = MessageMiddleware(lambda req: None)

        middleware_msg.process_request(request)



        middleware = AutoLogout(lambda req: "passed")

        response = middleware(request)

        self.assertEqual(response, "passed")





class RoleElementPermissionTest(TestCase):

    def setUp(self):

        self.role = Role.objects.create(name='WardenTest', description='Temporary test role')

        self.user = User.objects.create_user(username='wardentest', password='password')

        self.profile = UserProfile.objects.create(user=self.user, role=self.role)

        

        self.element = PermissionElement.objects.create(

            code='btn_test_action',

            name='Test Action Button',

            category='button'

        )



    def test_permission_denied_by_default(self):

        # By default, without RoleElementPermission record, access is denied

        self.assertFalse(check_element_perm(self.user, 'btn_test_action'))

        self.assertFalse(has_element_perm(self.user, 'btn_test_action'))



    def test_permission_allowed_when_enabled(self):

        # Create permission record and set is_enabled = True

        RoleElementPermission.objects.create(

            role=self.role,

            element=self.element,

            is_enabled=True

        )

        self.assertTrue(check_element_perm(self.user, 'btn_test_action'))

        self.assertTrue(has_element_perm(self.user, 'btn_test_action'))



    def test_permission_denied_when_disabled(self):

        # Create permission record and set is_enabled = False

        RoleElementPermission.objects.create(

            role=self.role,

            element=self.element,

            is_enabled=False

        )

        self.assertFalse(check_element_perm(self.user, 'btn_test_action'))

        self.assertFalse(has_element_perm(self.user, 'btn_test_action'))



    def test_superadmin_always_allowed(self):

        # Role name super admin or is_superuser should pass regardless

        sa_role = Role.objects.create(name='Super Admin', description='Super admin role', is_superadmin=True)

        sa_user = User.objects.create_user(username='sa', password='password')

        UserProfile.objects.create(user=sa_user, role=sa_role)

        

        self.assertTrue(check_element_perm(sa_user, 'btn_test_action'))

        self.assertTrue(has_element_perm(sa_user, 'btn_test_action'))



from django.urls import reverse

from .models import SystemSettings





class SystemSettingsVerificationTest(TestCase):

    def setUp(self):

        self.user = User.objects.create_superuser(username='superadmin', password='password')

        self.role = Role.objects.create(name='Super Admin', description='SA role', is_superadmin=True)

        UserProfile.objects.create(user=self.user, role=self.role)



    def test_system_settings_save_and_retrieve(self):

        self.client.force_login(self.user)

        url = reverse('system_settings_view')

        response = self.client.post(url, {

            'system_name': 'Test Hostel',

            'organization_name': 'Test Org',

            'theme_color': '#6366f1',

            'timezone': 'UTC',

            'date_format': 'Y-m-d',

            'time_format': 'H:i:s',

            'currency': 'USD',

            'language': 'en',

            'system_version': '1.0.0',

            'session_timeout': 3600,

            'login_attempt_limit': 10,

            'allowed_ips': '192.168.1.1, 10.0.0.0/24',

            'enable_audit_logs': True,

            'password_expiry_days': 30,

            'backup_frequency': 'weekly',

        })

        self.assertEqual(response.status_code, 302)

        

        settings = SystemSettings.get_settings()

        self.assertEqual(settings.system_name, 'Test Hostel')

        self.assertEqual(settings.session_timeout, 3600)

        self.assertEqual(settings.login_attempt_limit, 10)

        self.assertEqual(settings.allowed_ips, '192.168.1.1, 10.0.0.0/24')

        self.assertTrue(settings.enable_audit_logs)

        self.assertEqual(settings.password_expiry_days, 30)

        self.assertEqual(settings.backup_frequency, 'weekly')



    def test_user_delete_with_student(self):

        from student.models import Student

        target_user = User.objects.create_user(username='std_to_delete', password='password')

        Student.objects.create(user=target_user, name='Delete Me', email='delme@example.com')

        

        self.client.force_login(self.user)

        url = reverse('user_delete', kwargs={'pk': target_user.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        self.assertFalse(User.objects.filter(pk=target_user.pk).exists())





class NoRoleAndAutoStudentRoleTests(TestCase):

    def test_user_without_role_redirected_to_no_role_page(self):

        norole_user = User.objects.create_user(username='noroleuser', password='password')

        UserProfile.objects.create(user=norole_user, role=None)

        

        self.client.force_login(norole_user)

        response = self.client.get('/roles/', follow=False)

        self.assertEqual(response.status_code, 302)

        self.assertEqual(response.url, reverse('no_role'))

        

        no_role_res = self.client.get(reverse('no_role'))

        self.assertEqual(no_role_res.status_code, 200)

        self.assertContains(no_role_res, "No Role Assigned")



    def test_student_registration_auto_creates_and_assigns_student_role(self):

        # Ensure 'Student' role does not exist prior to test

        Role.objects.filter(name='Student').delete()

        self.assertFalse(Role.objects.filter(name='Student').exists())



        response = self.client.post(reverse('register'), {

            'username': 'newstudentreg',

            'email': 'newstudentreg@example.com',

            'password': 'password123',

            'role': ''

        })

        self.assertEqual(response.status_code, 302)

        

        # Verify Student role was auto-created and assigned

        self.assertTrue(Role.objects.filter(name='Student').exists())

        user = User.objects.get(username='newstudentreg')

        self.assertIsNotNone(user.profile.role)

        self.assertEqual(user.profile.role.name, 'Student')



from django.core.files.uploadedfile import SimpleUploadedFile



class DynamicBrandingTests(TestCase):

    def setUp(self):

        self.superadmin = User.objects.create_superuser(username='branding_admin', password='password')

        self.role = Role.objects.create(name='Super Admin', description='SA', is_superadmin=True)

        UserProfile.objects.create(user=self.superadmin, role=self.role)



    def test_dynamic_branding_reflection(self):

        # 1. Update settings directly

        settings = SystemSettings.get_settings()

        settings.system_name = 'Horizon Living'

        settings.organization_name = 'Horizon Group'

        settings.save()



        # 2. Check login page displays configured system name and title

        login_res = self.client.get(reverse('login'))

        self.assertEqual(login_res.status_code, 200)

        self.assertContains(login_res, 'Horizon Living')

        self.assertContains(login_res, '<title>Horizon Living')



        # 3. Check dashboard displays configured system name in sidebar and title

        self.client.force_login(self.superadmin)

        dash_res = self.client.get(reverse('superadmin_dashboard'))

        self.assertEqual(dash_res.status_code, 200)

        self.assertContains(dash_res, 'Horizon Living')

        self.assertContains(dash_res, 'Horizon Group')

        self.assertContains(dash_res, '<title>Horizon Living')



        # 4. Upload logo and favicon via system_settings_view

        small_gif = (

            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'

            b'\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'

            b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'

        )

        logo_file = SimpleUploadedFile('test_logo.png', small_gif, content_type='image/png')

        favicon_file = SimpleUploadedFile('test_fav.png', small_gif, content_type='image/png')



        post_res = self.client.post(reverse('system_settings_view'), {

            'system_name': 'Starlight Residency',

            'organization_name': 'Starlight HQ',

            'logo': logo_file,

            'favicon': favicon_file,

            'theme_color': '#6366f1',

            'timezone': 'UTC',

            'date_format': 'Y-m-d',

            'time_format': 'H:i:s',

            'currency': 'USD',

            'language': 'en',

            'system_version': '1.0.0',

            'session_timeout': 1800,

            'login_attempt_limit': 5,

            'allowed_ips': '',

            'enable_audit_logs': True,

            'password_expiry_days': 90,

            'backup_frequency': 'daily',

        })

        self.assertEqual(post_res.status_code, 302)



        # 5. Verify settings updated in DB with base64 data

        updated_settings = SystemSettings.get_settings()

        self.assertEqual(updated_settings.system_name, 'Starlight Residency')

        self.assertIsNotNone(updated_settings.logo_url)

        self.assertIsNotNone(updated_settings.favicon_url)

        self.assertTrue(updated_settings.logo_url.startswith('data:image/'))

        self.assertTrue(updated_settings.favicon_url.startswith('data:image/'))



        # 6. Verify dashboard displays updated name, logo and favicon

        dash_res2 = self.client.get(reverse('superadmin_dashboard'))

        self.assertEqual(dash_res2.status_code, 200)

        self.assertContains(dash_res2, 'Starlight Residency')

        self.assertContains(dash_res2, 'Starlight HQ')

        self.assertContains(dash_res2, '<title>Starlight Residency')

        self.assertContains(dash_res2, updated_settings.logo_url)

        self.assertContains(dash_res2, updated_settings.favicon_url)



        # 7. Verify login page displays updated name, logo and favicon

        self.client.logout()

        login_res2 = self.client.get(reverse('login'))

        self.assertEqual(login_res2.status_code, 200)

        self.assertContains(login_res2, 'Starlight Residency')

        self.assertContains(login_res2, '<title>Starlight Residency')

        self.assertContains(login_res2, updated_settings.logo_url)

        self.assertContains(login_res2, updated_settings.favicon_url)



class GlobalThemeStylingTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='theme_admin', password='password')
        self.role = Role.objects.create(name='Super Admin', description='SA', is_superadmin=True)
        UserProfile.objects.create(user=self.superadmin, role=self.role)

    def test_theme_color_properties(self):
        settings = SystemSettings.get_settings()
        settings.theme_color = '#10b981'
        settings.dark_mode_default = False
        settings.save()

        # Test RGB calculation
        self.assertEqual(settings.theme_color_rgb, '16, 185, 129')
        # Test hover calculation
        self.assertTrue(settings.theme_color_hover.startswith('#'))
        # Test glow calculation
        self.assertIn('rgba(16, 185, 129,', settings.theme_color_glow)
        # Test subtle calculation
        self.assertIn('rgba(16, 185, 129,', settings.theme_color_subtle)

    def test_theme_and_dark_mode_template_rendering(self):
        settings = SystemSettings.get_settings()
        # Test Light Mode Default with Emerald theme
        settings.theme_color = '#10b981'
        settings.dark_mode_default = False
        settings.save()

        res_login = self.client.get(reverse('login'))
        self.assertEqual(res_login.status_code, 200)
        self.assertContains(res_login, 'data-theme="light"')
        self.assertContains(res_login, '--theme-hex: #10b981')
        self.assertContains(res_login, '--theme-hex-rgb: 16, 185, 129')
        self.assertContains(res_login, 'class="auth-page"')

        # Test Dark Mode Default with Indigo theme
        settings.theme_color = '#6366f1'
        settings.dark_mode_default = True
        settings.save()

        self.client.force_login(self.superadmin)
        res_dash = self.client.get(reverse('superadmin_dashboard'))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, 'data-theme="dark"')
        self.assertContains(res_dash, '--theme-hex: #6366f1')
        self.assertContains(res_dash, '--theme-hex-rgb: 99, 102, 241')

    def test_ajax_theme_settings_save(self):
        self.client.force_login(self.superadmin)
        url = reverse('system_settings_view')
        post_data = {
            'system_name': 'Emerald Hostel',
            'organization_name': 'Green Group',
            'theme_color': '#059669',
            'dark_mode_default': False,
            'timezone': 'Asia/Kolkata',
            'date_format': 'Y-m-d',
            'time_format': 'H:i:s',
            'currency': 'INR',
            'language': 'en',
            'system_version': '1.0.0',
            'session_timeout': 1800,
            'login_attempt_limit': 5,
            'allowed_ips': '',
            'enable_audit_logs': True,
            'password_expiry_days': 90,
            'backup_frequency': 'daily',
        }
        res = self.client.post(url, post_data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get('status'), 'success')
        self.assertEqual(res.json().get('theme_color'), '#059669')
        self.assertEqual(res.json().get('dark_mode_default'), False)

        # Check DB was updated
        settings = SystemSettings.get_settings()
        self.assertEqual(settings.theme_color, '#059669')
        self.assertFalse(settings.dark_mode_default)


class SystemSettingsAdvancedFeaturesTests(TestCase):
    def setUp(self):
        self.superadmin_role = Role.objects.create(name='Super Admin', description='Super Admin Role')
        self.superadmin = User.objects.create_superuser('superboss', 'boss@test.com', 'BossPass123!')
        UserProfile.objects.create(user=self.superadmin, role=self.superadmin_role)

        self.student_role = Role.objects.create(name='Student', description='Student Role')
        self.student_user = User.objects.create_user('student1', 'student1@test.com', 'OldPass123!')
        self.student_profile = UserProfile.objects.create(
            user=self.student_user,
            role=self.student_role,
            password_changed_at=timezone.now()
        )
        from student.models import Student
        self.student = Student.objects.create(
            user=self.student_user,
            name='Student One',
            email='student1@test.com',
            gender='Male'
        )

        self.settings = SystemSettings.get_settings()
        self.settings.maintenance_mode = False
        self.settings.show_theme_toggle = True
        self.settings.password_expiry_days = 90
        self.settings.login_attempt_limit = 3
        self.settings.save()

    def test_show_theme_toggle_controls_visibility(self):
        # When show_theme_toggle is True
        self.settings.show_theme_toggle = True
        self.settings.save()

        res = self.client.get(reverse('login'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="themeToggleBtn"')

        # When show_theme_toggle is False
        self.settings.show_theme_toggle = False
        self.settings.save()

        res_hidden = self.client.get(reverse('login'))
        self.assertEqual(res_hidden.status_code, 200)
        self.assertNotContains(res_hidden, 'id="themeToggleBtn"')

    def test_password_expiry_enforcement(self):
        # Set user password changed 95 days ago
        self.settings.password_expiry_days = 90
        self.settings.save()

        self.student_profile.password_changed_at = timezone.now() - timezone.timedelta(days=95)
        self.student_profile.save()

        self.client.force_login(self.student_user)

        # Attempt to access student portal -> should be redirected to password_expired
        res = self.client.get(reverse('student_app:student_dashboard'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/authentication/password-expired/', res.url)

        # Following redirect leads to password expired change page
        res_page = self.client.get(reverse('password_expired'))
        self.assertEqual(res_page.status_code, 200)
        self.assertContains(res_page, 'Password Expired')

        # Submit new password
        post_data = {
            'current_password': 'OldPass123!',
            'new_password': 'BrandNewSecurePass456!',
            'confirm_password': 'BrandNewSecurePass456!',
        }
        res_change = self.client.post(reverse('password_expired'), post_data)
        self.assertEqual(res_change.status_code, 302)

        # Verify password was updated in DB and password_changed_at refreshed
        self.student_user.refresh_from_db()
        self.student_profile.refresh_from_db()
        self.assertTrue(self.student_user.check_password('BrandNewSecurePass456!'))
        days_since = (timezone.now() - self.student_profile.password_changed_at).days
        self.assertEqual(days_since, 0)

    def test_login_rate_limiting(self):
        from django.core.cache import cache
        cache.clear()

        self.settings.login_attempt_limit = 2
        self.settings.save()

        login_url = reverse('login')

        # 1st invalid attempt
        res1 = self.client.post(login_url, {'username': 'testuser', 'password': 'wrong1'})
        self.assertEqual(res1.status_code, 200)
        self.assertContains(res1, '1 attempt(s) remaining')

        # 2nd invalid attempt
        res2 = self.client.post(login_url, {'username': 'testuser', 'password': 'wrong2'})
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, 'Too many failed login attempts')

        # 3rd attempt: blocked by rate limiter
        res3 = self.client.post(login_url, {'username': 'testuser', 'password': 'wrong3'})
        self.assertEqual(res3.status_code, 200)
        self.assertContains(res3, 'Too many failed login attempts')

    def test_maintenance_mode_enforcement(self):
        self.settings.maintenance_mode = True
        self.settings.maintenance_message = "Upgrading database cluster"
        self.settings.estimated_restoration_time = "30 minutes"
        self.settings.save()

        # Regular student visitor -> 503 Service Unavailable
        self.client.force_login(self.student_user)
        res_student = self.client.get(reverse('student_app:student_dashboard'))
        self.assertEqual(res_student.status_code, 503)
        self.assertContains(res_student, 'System Under Maintenance', status_code=503)
        self.assertContains(res_student, 'Upgrading database cluster', status_code=503)
        self.assertContains(res_student, '30 minutes', status_code=503)

        # AJAX request during maintenance -> 503 JSON
        res_ajax = self.client.get(reverse('student_app:student_dashboard'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ajax.status_code, 503)
        self.assertEqual(res_ajax.json().get('status'), 'maintenance')

        # Super Admin visitor -> 200 OK (Exempt from maintenance lockout)
        self.client.force_login(self.superadmin)
        res_super = self.client.get(reverse('superadmin_dashboard'))
        self.assertEqual(res_super.status_code, 200)

        # Disable maintenance mode -> immediate 200 restoration for regular student
        self.settings.maintenance_mode = False
        self.settings.save()

        self.client.force_login(self.student_user)
        res_restored = self.client.get(reverse('student_app:student_dashboard'))
        self.assertEqual(res_restored.status_code, 200)

from unittest.mock import patch
from authentication.health import SystemHealthService
from authentication.models import AuditLog

class MaintenanceModeComprehensiveTests(TestCase):
    def setUp(self):
        from student.models import Student
        self.superadmin_role = Role.objects.create(name='Super Admin', description='Super Admin Role')
        self.superadmin = User.objects.create_superuser('maintsuper', 'maintsuper@test.com', 'SuperPass123!')
        UserProfile.objects.create(user=self.superadmin, role=self.superadmin_role)

        self.student_role = Role.objects.create(name='Student', description='Student Role')
        self.student_user = User.objects.create_user('maintstudent', 'maintstudent@test.com', 'StudPass123!')
        self.student_profile = UserProfile.objects.create(user=self.student_user, role=self.student_role)
        self.student = Student.objects.create(
            user=self.student_user,
            name='Maint Student',
            email='maintstudent@test.com',
            gender='Female'
        )

        self.staff_role = Role.objects.create(name='Staff', description='Staff Role')
        self.staff_user = User.objects.create_user('maintstaff', 'maintstaff@test.com', 'StaffPass123!')
        UserProfile.objects.create(user=self.staff_user, role=self.staff_role)

        self.settings = SystemSettings.get_settings()
        self.settings.maintenance_mode = False
        self.settings.auto_recovery_enabled = True
        self.settings.maintenance_type = 'automatic'
        self.settings.consecutive_success_required = 3
        self.settings.consecutive_success_count = 0
        self.settings.estimated_restoration_time = "3600"
        self.settings.save()

    def test_01_super_admin_manually_enables_maintenance(self):
        """Scenario 1: Super Admin manually enables maintenance mode via Secure Access route."""
        self.client.force_login(self.superadmin)
        res = self.client.post('/system-control/secure-access/', {'action': 'toggle_maintenance'})
        self.assertEqual(res.status_code, 302)
        
        self.settings.refresh_from_db()
        self.assertTrue(self.settings.maintenance_mode)
        self.assertEqual(self.settings.maintenance_status, 'active')
        
        # Verify AuditLog created
        log = AuditLog.objects.filter(action='maintenance_enabled').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.superadmin)

    def test_02_ordinary_users_cannot_access_pages_or_apis(self):
        """Scenario 2 & 12: Ordinary users blocked with 503 and Retry-After header; APIs receive 503 JSON."""
        self.settings.maintenance_mode = True
        self.settings.estimated_restoration_time = "3600"
        self.settings.save()

        # Regular student receives 503
        self.client.force_login(self.student_user)
        res_page = self.client.get('/student_app/dashboard/')
        self.assertEqual(res_page.status_code, 503)
        self.assertEqual(res_page['Retry-After'], '3600')
        self.assertContains(res_page, 'System Under Maintenance', status_code=503)

        # AJAX / API request receives 503 JSON
        res_api = self.client.get('/student_app/dashboard/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_api.status_code, 503)
        self.assertEqual(res_api.json().get('status'), 'maintenance')
        self.assertEqual(res_api['Retry-After'], '3600')

    def test_03_hidden_super_admin_route_available_and_secured(self):
        """Scenario 3: Hidden route /system-control/secure-access/ is accessible to Super Admin and protected."""
        self.settings.maintenance_mode = True
        self.settings.save()

        # Authenticated Super Admin gets full command center
        self.client.force_login(self.superadmin)
        res = self.client.get('/system-control/secure-access/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Super Admin Maintenance Command Center')

        # Unauthenticated visitor gets clean login form
        self.client.logout()
        res_anon = self.client.get('/system-control/secure-access/')
        self.assertEqual(res_anon.status_code, 200)
        self.assertContains(res_anon, 'Super Admin Access')

    def test_04_unauthorized_users_cannot_bypass_maintenance(self):
        """Scenario 4: Non-superadmin authenticated users cannot access hidden route or bypass maintenance."""
        self.settings.maintenance_mode = True
        self.settings.save()

        # Student accessing hidden route -> 403 Forbidden
        self.client.force_login(self.student_user)
        res_student = self.client.get('/system-control/secure-access/')
        self.assertEqual(res_student.status_code, 403)
        self.assertContains(res_student, 'Access Denied', status_code=403)

        # Staff accessing hidden route -> 403 Forbidden
        self.client.force_login(self.staff_user)
        res_staff = self.client.get('/system-control/secure-access/')
        self.assertEqual(res_staff.status_code, 403)

        # Security violation logged
        violation_log = AuditLog.objects.filter(action='security_violation').first()
        self.assertIsNotNone(violation_log)

    def test_05_pending_migrations_block_recovery(self):
        """Scenario 5: When a migration is running or pending, health check fails and blocks recovery."""
        self.settings.maintenance_mode = True
        self.settings.auto_recovery_enabled = True
        self.settings.save()

        with patch('authentication.health.MigrationExecutor') as MockExecutor:
            mock_inst = MockExecutor.return_value
            mock_inst.loader.graph.leaf_nodes.return_value = []
            # Simulate 2 pending migrations in the migration plan
            mock_inst.migration_plan.return_value = [('authentication', '0099_fake_migration'), ('authentication', '0100_fake_migration')]

            mig_check = SystemHealthService.check_migrations()
            self.assertFalse(mig_check['passed'])
            self.assertEqual(mig_check['pending_count'], 2)

            res = SystemHealthService.evaluate_and_recover(trigger='auto')
            self.assertFalse(res['recovered'])
            self.settings.refresh_from_db()
            self.assertTrue(self.settings.maintenance_mode)
            self.assertEqual(self.settings.consecutive_success_count, 0)

    def test_06_critical_health_check_failure_blocks_recovery(self):
        """Scenario 6: A critical health failure resets consecutive count and retains maintenance."""
        self.settings.maintenance_mode = True
        self.settings.consecutive_success_count = 2
        self.settings.save()

        with patch.object(SystemHealthService, 'check_database') as mock_db:
            mock_db.return_value = {
                'name': 'Database Connectivity',
                'status': 'unhealthy',
                'passed': False,
                'message': 'Simulated connection timeout'
            }
            res = SystemHealthService.evaluate_and_recover(trigger='auto')
            self.assertFalse(res['recovered'])
            self.settings.refresh_from_db()
            self.assertTrue(self.settings.maintenance_mode)
            self.assertEqual(self.settings.consecutive_success_count, 0)

    def test_07_and_08_automatic_recovery_when_healthy_and_enabled(self):
        """Scenarios 7 & 8: Consecutive passes reach threshold; maintenance automatically turns OFF."""
        self.settings.maintenance_mode = True
        self.settings.auto_recovery_enabled = True
        self.settings.consecutive_success_required = 3
        self.settings.consecutive_success_count = 0
        self.settings.save()

        with patch.object(SystemHealthService, 'perform_full_health_check') as mock_health:
            mock_health.return_value = {
                'healthy': True,
                'status': 'healthy',
                'timestamp': '2026-11-03T12:00:00Z',
                'checks': [{'name': 'Test', 'passed': True, 'message': 'OK'}],
                'summary': 'All operational'
            }

            # Check 1: Count becomes 1, maintenance remains True
            res1 = SystemHealthService.evaluate_and_recover(trigger='auto')
            self.assertFalse(res1['recovered'])
            self.settings.refresh_from_db()
            self.assertEqual(self.settings.consecutive_success_count, 1)
            self.assertTrue(self.settings.maintenance_mode)

            # Check 2: Count becomes 2, maintenance remains True
            res2 = SystemHealthService.evaluate_and_recover(trigger='auto')
            self.assertFalse(res2['recovered'])
            self.settings.refresh_from_db()
            self.assertEqual(self.settings.consecutive_success_count, 2)
            self.assertTrue(self.settings.maintenance_mode)

            # Check 3: Threshold reached (3/3) -> Automatically recovers and disables maintenance!
            res3 = SystemHealthService.evaluate_and_recover(trigger='auto')
            self.assertTrue(res3['recovered'])
            self.settings.refresh_from_db()
            self.assertFalse(self.settings.maintenance_mode)
            self.assertEqual(self.settings.maintenance_status, 'restored')
            self.assertIsNotNone(self.settings.maintenance_restored_at)

            # AuditLog verified
            rec_log = AuditLog.objects.filter(action='maintenance_auto_recovered').first()
            self.assertIsNotNone(rec_log)

    def test_09_maintenance_remains_active_when_auto_recovery_disabled(self):
        """Scenario 9: Maintenance remains active when auto-recovery is disabled even when healthy."""
        self.settings.maintenance_mode = True
        self.settings.auto_recovery_enabled = False
        self.settings.consecutive_success_required = 2
        self.settings.consecutive_success_count = 0
        self.settings.save()

        with patch.object(SystemHealthService, 'perform_full_health_check') as mock_health:
            mock_health.return_value = {
                'healthy': True,
                'status': 'healthy',
                'timestamp': '2026-11-03T12:00:00Z',
                'checks': [{'name': 'Test', 'passed': True, 'message': 'OK'}],
                'summary': 'All operational'
            }
            # Run 5 consecutive checks
            for _ in range(5):
                SystemHealthService.evaluate_and_recover(trigger='auto')

            self.settings.refresh_from_db()
            # Maintenance mode MUST remain True because auto_recovery_enabled is False!
            self.assertTrue(self.settings.maintenance_mode)

    def test_10_application_remains_in_maintenance_across_restart(self):
        """Scenario 10: Maintenance state is persistently stored in DB and preserved across fresh queries."""
        self.settings.maintenance_mode = True
        self.settings.maintenance_title = "Cluster Overhaul"
        self.settings.save()

        # Simulate fresh process query
        fresh_settings = SystemSettings.objects.get(pk=1)
        self.assertTrue(fresh_settings.maintenance_mode)
        self.assertEqual(fresh_settings.maintenance_title, "Cluster Overhaul")

    def test_11_original_destination_url_works_after_service_restoration(self):
        """Scenario 11: Destination URL is preserved in cookie and redirected after service restored."""
        self.settings.maintenance_mode = True
        self.settings.save()

        # Visit protected student dashboard during maintenance
        res_maint = self.client.get('/student_app/dashboard/')
        self.assertEqual(res_maint.status_code, 503)
        self.assertIn('pre_maintenance_url', res_maint.cookies)
        self.assertEqual(res_maint.cookies['pre_maintenance_url'].value, '/student_app/dashboard/')

        # Restore maintenance
        self.settings.maintenance_mode = False
        self.settings.save()

        # User returns to homepage '/' with cookie set
        self.client.force_login(self.student_user)
        self.client.cookies['pre_maintenance_url'] = '/student_app/dashboard/'
        res_restored = self.client.get('/')
        self.assertEqual(res_restored.status_code, 302)
        self.assertEqual(res_restored.url, '/student_app/dashboard/')
    def test_12_logout_via_get_request(self):
        """LogoutView accepts GET requests and logs the user out."""
        self.client.force_login(self.super_user)
        res = self.client.get('/logout/')
        self.assertEqual(res.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_13_manual_maintenance_not_lifted_by_auto_recovery(self):
        """When maintenance_type is manual, background auto-checks do not auto-lift maintenance."""
        self.settings.maintenance_mode = True
        self.settings.maintenance_type = 'manual'
        self.settings.auto_recovery_enabled = True
        self.settings.consecutive_success_count = 0
        self.settings.consecutive_success_required = 2
        self.settings.save()

        for _ in range(4):
            SystemHealthService.evaluate_and_recover(trigger='auto')

        self.settings.refresh_from_db()
        self.assertTrue(self.settings.maintenance_mode)

