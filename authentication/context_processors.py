"""
RBAC Context Processor.

Injects permission data and sidebar-visible modules into every template context.
Result is cached on the request object to avoid multiple DB hits per request.
"""

from .models import Module, RolePermission


def rbac_context(request):
    """
    Adds to template context:
      user_permissions  — dict  {module_code: {action: bool, ...}}
      visible_modules   — list  of Module objects the user has can_view=True on
      is_superadmin     — bool
      user_element_permissions — dict {element_code: bool}
    """
    if not request.user.is_authenticated:
        return {
            'user_permissions': {},
            'visible_modules': [],
            'is_superadmin': False,
            'user_element_permissions': {},
        }

    # Use per-request cache to avoid duplicate DB queries
    if hasattr(request, '_rbac_cache'):
        return request._rbac_cache

    profile = None
    try:
        profile = request.user.profile
    except Exception:
        pass

    is_super = (
        request.user.is_superuser or (
            profile and
            profile.role and
            profile.role.is_superadmin
        )
    )

    all_modules = list(Module.objects.order_by('order', 'name'))
    from .models import PermissionElement, RoleElementPermission

    if is_super:
        # Super admin sees everything with all actions enabled
        ALL_ACTIONS = ['view', 'add', 'edit', 'delete', 'approve', 'reject',
                       'export', 'print', 'import', 'hide', 'disable']
        user_permissions = {
            m.code: {action: True for action in ALL_ACTIONS}
            for m in all_modules
        }
        visible_modules = all_modules
        user_element_permissions = {el.code: True for el in PermissionElement.objects.all()}
    else:
        user_permissions = {}
        visible_modules = []
        user_element_permissions = {}

        if profile and profile.role:
            role = request.user.profile.role
            perms = RolePermission.objects.filter(role=role).select_related('module')

            perm_map = {p.module.code: p for p in perms}

            for module in all_modules:
                perm = perm_map.get(module.code)
                if perm:
                    module_perms = {
                        'view':    perm.can_view,
                        'add':     perm.can_add,
                        'edit':    perm.can_edit,
                        'delete':  perm.can_delete,
                        'approve': perm.can_approve,
                        'reject':  perm.can_reject,
                        'export':  perm.can_export,
                        'print':   perm.can_print,
                        'import':  perm.can_import,
                        'hide':    perm.can_hide,
                        'disable': perm.can_disable,
                    }
                    user_permissions[module.code] = module_perms
                    if perm.can_view and module.url_name:
                        visible_modules.append(module)
                else:
                    user_permissions[module.code] = {
                        action: False
                        for action in ['view', 'add', 'edit', 'delete', 'approve',
                                       'reject', 'export', 'print', 'import', 'hide', 'disable']
                    }
            
            # Load granular element permissions
            role_el_perms = RoleElementPermission.objects.filter(role=role, is_enabled=True).select_related('element')
            for rep in role_el_perms:
                user_element_permissions[rep.element.code] = True

            # Overlay/intercept active duty permissions
            from hms.models import DutyAssignment
            assignment = DutyAssignment.objects.filter(staff__user=request.user, is_active=True).first()
            if assignment and assignment.duty:
                duty_perms = {dp.module_name: dp for dp in assignment.duty.permissions.all()}
                reg_mapping = [('leave', 'leave'), ('students', 'student'), ('attendance', 'attendance')]
                
                for duty_mod, core_mod in reg_mapping:
                    dp = duty_perms.get(duty_mod)
                    if core_mod not in user_permissions:
                        user_permissions[core_mod] = {action: False for action in ['view', 'add', 'edit', 'delete', 'approve',
                                                                                   'reject', 'export', 'print', 'import', 'hide', 'disable']}
                    if dp:
                        user_permissions[core_mod]['view'] = dp.can_view
                        user_permissions[core_mod]['add'] = dp.can_add
                        user_permissions[core_mod]['edit'] = dp.can_edit
                        user_permissions[core_mod]['delete'] = dp.can_delete
                        if not dp.can_view:
                            user_permissions[core_mod]['approve'] = False
                            user_permissions[core_mod]['reject'] = False
                        
                        # Sync visibility
                        mod_obj = next((m for m in all_modules if m.code == core_mod), None)
                        if mod_obj:
                            if dp.can_view and mod_obj.url_name:
                                if mod_obj not in visible_modules:
                                    visible_modules.append(mod_obj)
                            else:
                                if mod_obj in visible_modules:
                                    visible_modules.remove(mod_obj)
                    else:
                        for action in user_permissions[core_mod]:
                            user_permissions[core_mod][action] = False
                        mod_obj = next((m for m in all_modules if m.code == core_mod), None)
                        if mod_obj and mod_obj in visible_modules:
                            visible_modules.remove(mod_obj)

    result = {
        'user_permissions': user_permissions,
        'visible_modules': visible_modules,
        'is_superadmin': is_super,
        'user_element_permissions': user_element_permissions,
    }
    request._rbac_cache = result
    return result


def hostel_context(request):
    """
    Injects the active hostel and a list of all available hostels into the template context.
    Cached on the request to avoid repetitive queries.
    """
    if hasattr(request, '_hostel_context_cache'):
        return request._hostel_context_cache

    if not request.user.is_authenticated:
        res = {
            'active_hostel': None,
            'available_hostels': [],
        }
        request._hostel_context_cache = res
        return res

    from .models import Hostel
    hostels = list(Hostel.objects.all())
    active_hostel_id = request.session.get('active_hostel_id')
    active_hostel = None
    
    if active_hostel_id:
        active_hostel = next((h for h in hostels if h.id == int(active_hostel_id)), None)
        
    if not active_hostel and hostels:
        active_hostel = hostels[0]
        request.session['active_hostel_id'] = active_hostel.id

    res = {
        'active_hostel': active_hostel,
        'available_hostels': hostels,
    }
    request._hostel_context_cache = res
    return res


def system_settings_context(request):
    """
    Injects global SystemSettings into the template context.
    Cached on the request to avoid repetitive lookups.
    """
    if hasattr(request, '_sys_settings_context_cache'):
        return request._sys_settings_context_cache
    from .models import SystemSettings
    res = {
        'system_settings': SystemSettings.get_settings(),
    }
    request._sys_settings_context_cache = res
    return res


def leave_context(request):
    """
    Injects pending_leave_count into the template context for side navigation badges.
    Cached on the request to avoid multiple count queries during template rendering.
    """
    if hasattr(request, '_leave_context_cache'):
        return request._leave_context_cache

    if not request.user.is_authenticated:
        res = {'pending_leave_count': 0}
        request._leave_context_cache = res
        return res
    try:
        from leave.models import HostelLeave
        if hasattr(request.user, 'profile') and request.user.profile.role and request.user.profile.role.name == 'Student':
            count = HostelLeave.objects.filter(student__user=request.user, status='pending').count()
        else:
            count = HostelLeave.objects.filter(status='pending').count()
        res = {'pending_leave_count': count}
    except Exception:
        res = {'pending_leave_count': 0}
    request._leave_context_cache = res
    return res


