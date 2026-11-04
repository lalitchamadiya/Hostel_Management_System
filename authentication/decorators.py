from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from functools import wraps


# ──────────────────────────────────────────────────────────────────────────────
# Utility helper — callable anywhere in views
# ──────────────────────────────────────────────────────────────────────────────

def check_perm(user, module_code, action, target_obj=None):
    """
    Returns True if the user has the given action permission on the module.
    Actions: view, add, edit, delete, approve, reject, verify, export, print, download, assign
    Always returns True for super-admins or Django superusers.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = None
    try:
        profile = user.profile
    except Exception:
        pass

    if profile and profile.role and profile.role.is_superadmin:
        return True

    # 1. Overlay/intercept active duty permissions via Enterprise DutyAuthorizationService
    try:
        from hms.duty_services import DutyAuthorizationService
        granted, _ = DutyAuthorizationService.evaluate_duty_permission(user, module_code, action, target_obj=target_obj)
        if granted:
            return True
    except Exception:
        pass

    # 2. Fall back to standard Role-based check (Fail-Closed: role must be active)
    if profile and profile.role and profile.role.is_active:
        perm = profile.role.permissions.filter(module__code=module_code).first()
        if perm:
            return getattr(perm, f'can_{action}', False)
    return False


def check_scoped_perm(user, module_code, action, target_obj=None):
    """Convenience helper to check action permission against a specific target object scope."""
    return check_perm(user, module_code, action, target_obj=target_obj)


# ──────────────────────────────────────────────────────────────────────────────
# role_required — guard by role name(s)
# ──────────────────────────────────────────────────────────────────────────────

def role_required(*role_names):
    """
    Decorator that checks whether the logged-in user has one of the specified roles.
    Super Admin and Django superusers always pass.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            # Super Admin bypass
            profile = None
            try:
                profile = request.user.profile
            except Exception:
                pass

            if request.user.is_superuser or (
                profile and
                profile.role and
                profile.role.is_superadmin
            ):
                return view_func(request, *args, **kwargs)

            if profile and profile.role:
                if profile.role.name in role_names:
                    return view_func(request, *args, **kwargs)

            raise PermissionDenied
        return _wrapped_view
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# permission_required — guard by module + action (redirects on fail)
# ──────────────────────────────────────────────────────────────────────────────

def permission_required(module_code, action):
    """
    Decorator that checks whether the user's role has a specific permission for a module.
    Raises PermissionDenied (→ 403 HTML page) on failure.
    Actions: view, add, edit, delete, approve, reject, export, print, import, hide, disable
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if check_perm(request.user, module_code, action):
                return view_func(request, *args, **kwargs)

            raise PermissionDenied
        return _wrapped_view
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# api_permission_required — guard AJAX/API endpoints (returns JSON 403)
# ──────────────────────────────────────────────────────────────────────────────

def api_permission_required(module_code, action):
    """
    Decorator for AJAX / JSON API views.
    Returns JsonResponse({'error': 'Forbidden'}, status=403) instead of raising PermissionDenied.
    This avoids Django's default HTML error page format which breaks JSON clients.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Authentication required'}, status=401)

            if check_perm(request.user, module_code, action):
                return view_func(request, *args, **kwargs)

            return JsonResponse(
                {'error': 'Forbidden: you do not have permission to perform this action.'},
                status=403
            )
        return _wrapped_view
    return decorator


def check_element_perm(user, element_code):
    """
    Returns True if the user has the given element permission enabled.
    Always returns True for super-admins or Django superusers.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = None
    try:
        profile = user.profile
    except Exception:
        pass

    if profile and profile.role and profile.role.is_superadmin:
        return True
    if profile and profile.role:
        perm = profile.role.element_permissions.filter(element__code=element_code).first()
        if perm:
            return perm.is_enabled
    return False


def element_permission_required(element_code):
    """
    Decorator that checks whether the user's role has the designated permission element enabled.
    Redirects to 403 PermissionDenied if not allowed.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if check_element_perm(request.user, element_code):
                return view_func(request, *args, **kwargs)

            raise PermissionDenied
        return _wrapped_view
    return decorator

