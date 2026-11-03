import time
from django.contrib import auth
from django.shortcuts import redirect, render
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse


class MaintenanceModeMiddleware:
    """
    Global System Maintenance Mode Interceptor.
    When enabled in SystemSettings:
    - Non-superadmin visitors (students, staff, anonymous, APIs) receive HTTP 503 Service Unavailable.
    - Super Admins retain full access to manage the system and disable maintenance mode.
    - Login and logout routes remain accessible so Super Admins can log in to manage maintenance.
    - Static and media files are allowed so assets and icons render properly.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from authentication.models import SystemSettings
            settings_obj = SystemSettings.get_settings()
        except Exception:
            settings_obj = None

        if settings_obj and getattr(settings_obj, 'maintenance_mode', False):
            path = request.path

            # Allow static and media assets unconditionally
            if path.startswith('/static/') or path.startswith('/media/'):
                return self.get_response(request)

            # Check if user is Super Admin
            if request.user.is_authenticated:
                is_super = request.user.is_superuser
                if not is_super:
                    profile = getattr(request.user, 'profile', None)
                    if profile and profile.role and profile.role.name == 'Super Admin':
                        is_super = True
                if is_super:
                    return self.get_response(request)

            # Allow login and logout so Super Admins can log in if needed
            exempt_auth_paths = [
                '/authentication/login/',
                '/authentication/logout/',
            ]
            if path in exempt_auth_paths:
                return self.get_response(request)

            # Return 503 JSON for AJAX or API calls
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or path.startswith('/api/'):
                return JsonResponse({
                    'status': 'maintenance',
                    'error': 'Service Unavailable (503)',
                    'message': settings_obj.maintenance_message or 'The system is undergoing scheduled maintenance.',
                    'estimated_restoration_time': settings_obj.estimated_restoration_time or 'Soon',
                }, status=503)

            # Render full 503 maintenance page
            return render(request, 'maintenance.html', {
                'system_settings': settings_obj,
                'maintenance_message': settings_obj.maintenance_message,
                'estimated_restoration_time': settings_obj.estimated_restoration_time,
            }, status=503)

        return self.get_response(request)


class AutoLogout:
    """
    Dynamically auto-logs out inactive users based on SystemSettings.session_timeout.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            last_activity = request.session.get('_last_activity')
            now_ts = int(time.time())

            # Read dynamic session timeout from SystemSettings
            try:
                from authentication.models import SystemSettings
                settings_obj = SystemSettings.get_settings()
                timeout = getattr(settings_obj, 'session_timeout', 1800) or 1800
            except Exception:
                timeout = getattr(settings, 'SESSION_COOKIE_AGE', 1800)

            if last_activity is not None and (now_ts - last_activity > timeout):
                auth.logout(request)
                return redirect('login')

            request.session['_last_activity'] = now_ts

        return self.get_response(request)


class PasswordExpiryMiddleware:
    """
    Enforces password change when Password Expiry Cycle (Days) is exceeded.
    Without changing the password, the user is permanently blocked from other routes.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                from authentication.models import SystemSettings
                settings_obj = SystemSettings.get_settings()
                expiry_days = getattr(settings_obj, 'password_expiry_days', 0) or 0
            except Exception:
                expiry_days = 0

            if expiry_days > 0:
                profile = getattr(request.user, 'profile', None)
                last_changed = None
                if profile and profile.password_changed_at:
                    last_changed = profile.password_changed_at
                elif request.user.date_joined:
                    last_changed = request.user.date_joined

                if last_changed:
                    days_elapsed = (timezone.now() - last_changed).days
                    if days_elapsed >= expiry_days:
                        # Expiry cycle reached: block all navigation except password change & logout
                        exempt_paths = [
                            '/authentication/password-expired/',
                            '/authentication/logout/',
                            '/static/',
                            '/media/',
                        ]
                        if not any(request.path.startswith(p) for p in exempt_paths):
                            return redirect('password_expired')

        return self.get_response(request)


class NoRoleAccessMiddleware:
    """
    Middleware that intercepts requests from logged-in non-superusers.
    If the user has no assigned role (profile.role is None), restricts them
    from accessing system endpoints and redirects to the 'no_role' page.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            path = request.path
            exempt_paths = [
                '/authentication/no-role/',
                '/authentication/logout/',
                '/authentication/login/',
                '/authentication/keep-alive/',
                '/authentication/password-expired/',
                '/static/',
                '/media/',
            ]
            if not any(path.startswith(p) for p in exempt_paths):
                profile = getattr(request.user, 'profile', None)
                if not profile or not profile.role:
                    return redirect('no_role')

        return self.get_response(request)
