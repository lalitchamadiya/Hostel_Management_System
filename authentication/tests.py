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
        self.assertContains(res_login, '--primary: #10b981')
        self.assertContains(res_login, '--primary-rgb: 16, 185, 129')

        # Test Dark Mode Default with Indigo theme
        settings.theme_color = '#6366f1'
        settings.dark_mode_default = True
        settings.save()

        self.client.force_login(self.superadmin)
        res_dash = self.client.get(reverse('superadmin_dashboard'))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, 'data-theme="dark"')
        self.assertContains(res_dash, '--primary: #6366f1')
        self.assertContains(res_dash, '--primary-rgb: 99, 102, 241')

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
