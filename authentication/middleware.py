import time
from django.contrib import auth
from django.shortcuts import redirect, render
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse


def get_retry_after(estimated_time_str):
    """
    Computes a valid Retry-After header value in seconds.
    Supports integers, ISO datetimes, or returns a safe 300s default.
    """
    if not estimated_time_str:
        return '300'
    val = str(estimated_time_str).strip()
    if val.isdigit():
        return str(max(30, int(val)))
    try:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(val)
        if dt:
            delta = int((dt - timezone.now()).total_seconds())
            return str(max(30, delta))
    except Exception:
        pass
    return '300'


class MaintenanceModeMiddleware:
    """
    Global System Maintenance Mode Interceptor.
    Enforces complete maintenance mode across the entire application:
    - Blocked requests receive HTTP 503 Service Unavailable with Retry-After header.
    - AJAX and API requests receive HTTP 503 JSON.
    - Super Admins retain full access to manage the system and disable maintenance mode.
    - Dedicated hidden Super Admin access route (/system-control/secure-access/) remains accessible.
    - Static, media assets, logout, and health check endpoints remain accessible.
    - Preserves user destination URLs and redirects them upon service restoration.
    - Periodically triggers automatic health evaluation and recovery when auto_recovery_enabled is True.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        try:
            from authentication.models import SystemSettings
            settings_obj = SystemSettings.get_settings()
        except Exception:
            settings_obj = None

        # 1. When maintenance is NOT active: check for post-restoration destination redirect
        if not (settings_obj and getattr(settings_obj, 'maintenance_mode', False)):
            pre_url = request.COOKIES.get('pre_maintenance_url')
            if pre_url and request.method == 'GET' and path in ['/', '/authentication/login/'] and not (request.headers.get('x-requested-with') == 'XMLHttpRequest'):
                response = redirect(pre_url)
                response.delete_cookie('pre_maintenance_url')
                return response
            return self.get_response(request)

        # 2. Maintenance is ACTIVE: Check if automatic recovery check is due
        if getattr(settings_obj, 'auto_recovery_enabled', False):
            last_check = getattr(settings_obj, 'last_health_check_at', None)
            interval = getattr(settings_obj, 'health_check_interval', 30) or 30
            if not last_check or (timezone.now() - last_check).total_seconds() >= interval:
                try:
                    from authentication.health import SystemHealthService
                    recovery_result = SystemHealthService.evaluate_and_recover(
                        trigger='auto',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )
                    if recovery_result.get('recovered'):
                        # System was recovered and maintenance lifted!
                        settings_obj = SystemSettings.get_settings()
                        # If normal service is restored, redirect pre_url or continue
                        pre_url = request.COOKIES.get('pre_maintenance_url')
                        if pre_url and request.method == 'GET' and not (request.headers.get('x-requested-with') == 'XMLHttpRequest'):
                            response = redirect(pre_url)
                            response.delete_cookie('pre_maintenance_url')
                            return response
                        return self.get_response(request)
                except Exception:
                    pass

        # 3. Allow static and media assets unconditionally
        if path.startswith('/static/') or path.startswith('/media/'):
            return self.get_response(request)

        # 4. Allow designated maintenance infrastructure endpoints
        exempt_paths = [
            '/system-control/secure-access/',
            '/system-control/health/',
            '/authentication/logout/',
            '/manifest.json',
            '/service-worker.js',
        ]
        if any(path.startswith(p) for p in exempt_paths):
            return self.get_response(request)

        # 5. Check if user is an authenticated Super Admin
        if request.user.is_authenticated:
            is_super = request.user.is_superuser
            if not is_super:
                profile = getattr(request.user, 'profile', None)
                if profile and profile.role and profile.role.name == 'Super Admin':
                    is_super = True
            if is_super:
                return self.get_response(request)

        # 6. User is NOT Super Admin -> Enforce HTTP 503 Maintenance Lockout
        retry_after = get_retry_after(getattr(settings_obj, 'estimated_restoration_time', ''))

        # Return 503 JSON for AJAX or API calls
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or path.startswith('/api/'):
            resp = JsonResponse({
                'status': 'maintenance',
                'error': 'Service Unavailable (503)',
                'maintenance_status': getattr(settings_obj, 'maintenance_status', 'active'),
                'title': getattr(settings_obj, 'maintenance_title', 'System Under Maintenance'),
                'message': getattr(settings_obj, 'maintenance_message', 'The system is undergoing scheduled maintenance.'),
                'reason': getattr(settings_obj, 'maintenance_reason', 'Scheduled Infrastructure Maintenance'),
                'stage': getattr(settings_obj, 'maintenance_stage', 'Maintenance & Verification'),
                'progress': getattr(settings_obj, 'maintenance_progress', 50),
                'estimated_restoration_time': getattr(settings_obj, 'estimated_restoration_time', '') or None,
            }, status=503)
            resp['Retry-After'] = retry_after
            return resp

        # Render full 503 maintenance page
        context = {
            'system_settings': settings_obj,
            'maintenance_title': getattr(settings_obj, 'maintenance_title', 'System Under Maintenance'),
            'maintenance_message': getattr(settings_obj, 'maintenance_message', 'We are currently performing scheduled maintenance.'),
            'maintenance_reason': getattr(settings_obj, 'maintenance_reason', 'Scheduled Infrastructure Maintenance'),
            'maintenance_status': getattr(settings_obj, 'maintenance_status', 'active'),
            'maintenance_stage': getattr(settings_obj, 'maintenance_stage', 'System Diagnostics & Integrity Checks'),
            'maintenance_progress': getattr(settings_obj, 'maintenance_progress', 50),
            'estimated_restoration_time': getattr(settings_obj, 'estimated_restoration_time', ''),
            'maintenance_activated_at': getattr(settings_obj, 'maintenance_activated_at', None),
            'last_health_check_at': getattr(settings_obj, 'last_health_check_at', None),
            'support_email': getattr(settings_obj, 'support_email', ''),
            'support_phone': getattr(settings_obj, 'support_phone', ''),
            'helpdesk_url': getattr(settings_obj, 'helpdesk_url', ''),
        }
        resp = render(request, 'maintenance.html', context, status=503)
        resp['Retry-After'] = retry_after

        # Preserve the visitor's destination URL so they can resume after service restoration
        if request.method == 'GET' and not path.startswith('/system-control/'):
            resp.set_cookie('pre_maintenance_url', request.get_full_path(), max_age=86400, samesite='Lax')

        return resp


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
                '/static/',
                '/media/',
            ]
            if not any(path.startswith(p) for p in exempt_paths):
                profile = getattr(request.user, 'profile', None)
                if not profile or not profile.role:
                    return redirect('no_role')

        return self.get_response(request)
