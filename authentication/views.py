import csv
import json
import time
from functools import wraps

from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST

from .decorators import role_required, permission_required
from .models import AuditLog, Module, Role, RolePermission, UserProfile, Hostel, PermissionElement, RoleElementPermission, get_or_create_student_role
from hms.utils import file_to_base64

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@login_required
def no_role_view(request):
    """
    Renders a dedicated page informing users who have no role assigned
    that they must contact an administrator.
    """
    return render(request, 'authentication/no_role.html')


def log_action(actor, action, target_user=None, details='', request=None):
    """Utility to record an audit log entry."""
    ip = None
    if request:
        x_forward = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forward.split(',')[0] if x_forward else request.META.get('REMOTE_ADDR')
    AuditLog.objects.create(
        actor=actor,
        target_user=target_user,
        action=action,
        details=details,
        ip_address=ip,
    )


def get_client_ip(request):
    x_forward = request.META.get('HTTP_X_FORWARDED_FOR')
    return x_forward.split(',')[0] if x_forward else request.META.get('REMOTE_ADDR')


# ---------------------------------------------------------------------------
# Auth — Validation, Registration, Login, Logout
# ---------------------------------------------------------------------------

from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class EmailValidationView(View):
    def post(self, request):
        data = json.loads(request.body)
        email = data.get('email', '')
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({'email_error': 'Email is invalid'}, status=400)
        if User.objects.filter(email=email).exists():
            return JsonResponse({'email_error': 'Email already in use'}, status=409)
        return JsonResponse({'email_valid': True})


class UserNameValidationView(View):
    def post(self, request):
        data = json.loads(request.body)
        username = data['username']
        if not str(username).isalnum():
            return JsonResponse({'username_error': 'Username must be alphanumeric'}, status=400)
        if User.objects.filter(username=username).exists():
            return JsonResponse({'username_error': 'Username already taken'}, status=409)
        return JsonResponse({'username_valid': True})


class RegistrationView(View):
    def get(self, request):
        roles = Role.objects.filter(is_active=True).exclude(is_superadmin=True)
        return render(request, 'authentication/register.html', {'roles': roles})

    def post(self, request):
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        role_id = request.POST.get('role')

        context = {
            'fieldValues': request.POST,
            'roles': Role.objects.filter(is_active=True).exclude(is_superadmin=True),
        }

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists')
            return render(request, 'authentication/register.html', context)
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists')
            return render(request, 'authentication/register.html', context)
        if len(password) < 6:
            messages.error(request, 'Password too short')
            return render(request, 'authentication/register.html', context)

        user = User.objects.create_user(username=username, email=email)
        user.set_password(password)
        user.save()

        # Check role or fallback to Student role automatically
        role_obj = None
        if role_id:
            try:
                role_obj = Role.objects.get(id=role_id)
            except (Role.DoesNotExist, ValueError):
                pass

        if not role_obj:
            role_obj = get_or_create_student_role()

        UserProfile.objects.create(user=user, role=role_obj)
        group, _ = Group.objects.get_or_create(name=role_obj.name)
        group.user_set.add(user)

        messages.success(request, 'Account Successfully Created')
        return redirect('login')


class LoginView(View):
    def get(self, request):
        return render(request, 'authentication/login.html')

    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']

        if username and password:
            user = auth.authenticate(username=username, password=password)
            if user:
                profile = None
                try:
                    profile = user.profile
                except Exception:
                    pass

                # Check if account is locked
                if profile and profile.is_locked:
                    messages.error(request, 'Your account has been locked. Contact an administrator.')
                    return render(request, 'authentication/login.html')

                if user.is_active:
                    auth.login(request, user)
                    request.session.set_expiry(900)
                    log_action(user, 'login', user, request=request)

                    if profile and profile.role:
                        role_name = profile.role.name
                        if role_name in ('Super Admin', 'Admin'):
                            return redirect('superadmin_dashboard')
                        elif role_name == 'Student':
                            return redirect('student_app:student_dashboard')
                        elif role_name == 'Warden':
                            return redirect('warden_dashboard')
                        elif role_name == 'Staff':
                            return redirect('superadmin_dashboard')
                        elif role_name in ('Security Guard', 'Security'):
                            return redirect('security_dashboard')
                    elif user.is_superuser:
                        return redirect('superadmin_dashboard')
                    else:
                        return redirect('no_role')

                    return redirect('superadmin_dashboard')

                messages.error(request, 'Account is not active')
                return render(request, 'authentication/login.html')

            messages.error(request, 'Invalid credentials, try again')
            return render(request, 'authentication/login.html')

        messages.error(request, 'Please fill all fields')
        return render(request, 'authentication/login.html')


class LogoutView(View):
    def post(self, request):
        if request.user.is_authenticated:
            log_action(request.user, 'logout', request.user, request=request)
        auth.logout(request)
        return redirect('login')


# ---------------------------------------------------------------------------
# Role Management
# ---------------------------------------------------------------------------

@login_required
@role_required('Super Admin')
def role_list(request):
    roles = Role.objects.exclude(is_superadmin=True).order_by('-created_at')
    return render(request, 'authentication/rbac/role_list.html', {'roles': roles})


@login_required
@role_required('Super Admin')
def role_create(request):
    modules = Module.objects.all()
    elements = PermissionElement.objects.select_related('module').all()
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        is_active = request.POST.get('is_active') == 'on'

        role = Role.objects.create(name=name, description=description, is_active=is_active)

        for module in modules:
            RolePermission.objects.create(
                role=role, module=module,
                can_view=request.POST.get(f'view_{module.id}') == 'on',
                can_add=request.POST.get(f'add_{module.id}') == 'on',
                can_edit=request.POST.get(f'edit_{module.id}') == 'on',
                can_delete=request.POST.get(f'delete_{module.id}') == 'on',
                can_approve=request.POST.get(f'approve_{module.id}') == 'on',
                can_reject=request.POST.get(f'reject_{module.id}') == 'on',
                can_export=request.POST.get(f'export_{module.id}') == 'on',
                can_print=request.POST.get(f'print_{module.id}') == 'on',
                can_import=request.POST.get(f'import_{module.id}') == 'on',
                can_hide=request.POST.get(f'hide_{module.id}') == 'on',
                can_disable=request.POST.get(f'disable_{module.id}') == 'on',
            )

        for element in elements:
            RoleElementPermission.objects.create(
                role=role,
                element=element,
                is_enabled=request.POST.get(f'element_{element.id}') == 'on'
            )

        messages.success(request, f"Role '{name}' created successfully.")
        return redirect('role_list')

    return render(request, 'authentication/rbac/role_form.html', {
        'modules': modules,
        'role_perms': {},
        'elements': elements,
        'role_element_perms': set()
    })


@login_required
@role_required('Super Admin')
def role_edit(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if role.is_superadmin:
        messages.error(request, 'Super Admin role cannot be modified.')
        return redirect('role_list')
        
    modules = Module.objects.all()
    elements = PermissionElement.objects.select_related('module').all()

    if request.method == 'POST':
        role.name = request.POST.get('name')
        role.description = request.POST.get('description')
        role.is_active = request.POST.get('is_active') == 'on'
        role.save()

        for module in modules:
            perm, _ = RolePermission.objects.get_or_create(role=role, module=module)
            perm.can_view = request.POST.get(f'view_{module.id}') == 'on'
            perm.can_add = request.POST.get(f'add_{module.id}') == 'on'
            perm.can_edit = request.POST.get(f'edit_{module.id}') == 'on'
            perm.can_delete = request.POST.get(f'delete_{module.id}') == 'on'
            perm.can_approve = request.POST.get(f'approve_{module.id}') == 'on'
            perm.can_reject = request.POST.get(f'reject_{module.id}') == 'on'
            perm.can_export = request.POST.get(f'export_{module.id}') == 'on'
            perm.can_print = request.POST.get(f'print_{module.id}') == 'on'
            perm.can_import = request.POST.get(f'import_{module.id}') == 'on'
            perm.can_hide = request.POST.get(f'hide_{module.id}') == 'on'
            perm.can_disable = request.POST.get(f'disable_{module.id}') == 'on'
            perm.save()

        for element in elements:
            el_perm, _ = RoleElementPermission.objects.get_or_create(role=role, element=element)
            el_perm.is_enabled = request.POST.get(f'element_{element.id}') == 'on'
            el_perm.save()

        messages.success(request, f"Role '{role.name}' updated successfully.")
        return redirect('role_list')

    role_perms = {p.module_id: p for p in role.permissions.all()}
    role_element_perms = set(RoleElementPermission.objects.filter(role=role, is_enabled=True).values_list('element_id', flat=True))
    return render(request, 'authentication/rbac/role_form.html', {
        'role': role,
        'modules': modules,
        'role_perms': role_perms,
        'elements': elements,
        'role_element_perms': role_element_perms
    })


@login_required
@role_required('Super Admin')
def role_clone(request, pk):
    """Deep copy of a role's permissions to a new role."""
    if request.method == 'POST':
        source_role = get_object_or_404(Role, pk=pk)
        if source_role.is_superadmin:
            messages.error(request, 'Super Admin role cannot be cloned.')
            return redirect('role_list')
            
        new_name = request.POST.get('name', f"{source_role.name} (Copy)").strip()
        
        if Role.objects.filter(name=new_name).exists():
            messages.error(request, f"A role named '{new_name}' already exists.")
            return redirect('role_list')
            
        new_role = Role.objects.create(
            name=new_name,
            description=f"Cloned from '{source_role.name}'. {source_role.description}",
            is_active=source_role.is_active
        )
        
        # Copy permissions
        for perm in source_role.permissions.all():
            RolePermission.objects.create(
                role=new_role,
                module=perm.module,
                can_view=perm.can_view,
                can_add=perm.can_add,
                can_edit=perm.can_edit,
                can_delete=perm.can_delete,
                can_approve=perm.can_approve,
                can_reject=perm.can_reject,
                can_export=perm.can_export,
                can_print=perm.can_print,
                can_import=perm.can_import,
                can_hide=perm.can_hide,
                can_disable=perm.can_disable,
            )
            
        log_action(request.user, 'create', None, f"Cloned role '{source_role.name}' to '{new_role.name}'", request)
        messages.success(request, f"Role '{source_role.name}' cloned to '{new_role.name}' successfully.")
    return redirect('role_list')


@login_required
def permission_overview(request, pk):
    """Returns JSON of a user's permissions."""
    target_user = get_object_or_404(User, pk=pk)
    if request.user.id != target_user.id and not (
        request.user.is_superuser or (
            hasattr(request.user, 'profile') and
            request.user.profile.role and
            request.user.profile.role.is_superadmin
        )
    ):
        return JsonResponse({'error': 'Forbidden'}, status=403)
        
    from .context_processors import rbac_context
    class FakeRequest:
        def __init__(self, user):
            self.user = user
            self.session = {}
    fake_req = FakeRequest(target_user)
    ctx = rbac_context(fake_req)
    return JsonResponse(ctx)


@login_required
@role_required('Super Admin')
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if role.is_superadmin:
        messages.error(request, 'Super Admin role cannot be deleted.')
    else:
        role.delete()
        messages.success(request, 'Role deleted successfully.')
    return redirect('role_list')


@login_required
@role_required('Super Admin')
def add_custom_permission_element(request):
    """Allows Super Admins to dynamically add new permission elements from Role forms."""
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().replace(' ', '_').lower()
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', 'button')
        description = request.POST.get('description', '').strip()
        module_id = request.POST.get('module')

        if not code or not name:
            messages.error(request, "Code and Name are required fields.")
        elif PermissionElement.objects.filter(code=code).exists():
            messages.error(request, f"Permission element with code '{code}' already exists.")
        else:
            module_obj = None
            if module_id:
                try:
                    module_obj = Module.objects.get(id=module_id)
                except Module.DoesNotExist:
                    pass
            
            PermissionElement.objects.create(
                code=code,
                name=name,
                category=category,
                description=description,
                module=module_obj
            )
            messages.success(request, f"Custom permission element '{name}' created successfully.")
            
    referrer = request.META.get('HTTP_REFERER')
    if referrer:
        return redirect(referrer)
    return redirect('role_list')


# ---------------------------------------------------------------------------
# User Management — Full CRUD + Actions
# ---------------------------------------------------------------------------

@login_required
@role_required('Super Admin')
def user_list(request):
    """View, search, filter and perform bulk actions on all system users."""
    qs = User.objects.select_related('profile', 'profile__role').order_by('-id')

    # ── Filters ──
    search = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '')
    status_filter = request.GET.get('status', '')

    if search:
        qs = qs.filter(
            Q(username__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search)
        )
    if role_filter:
        qs = qs.filter(profile__role_id=role_filter)
    if status_filter:
        if status_filter == 'active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'inactive':
            qs = qs.filter(is_active=False)
        elif status_filter == 'locked':
            qs = qs.filter(profile__is_locked=True)

    # ── Bulk Actions ──
    if request.method == 'POST':
        action = request.POST.get('bulk_action')
        selected_ids = request.POST.getlist('selected_users')
        if selected_ids and action:
            selected_users = User.objects.filter(id__in=selected_ids)
            
            if action == 'activate':
                selected_users.update(is_active=True)
                for u in selected_users:
                    log_action(request.user, 'activate', u, 'Bulk activated', request)
                messages.success(request, f'Activated {selected_users.count()} user(s).')
                
            elif action == 'deactivate':
                deactivatable = selected_users.exclude(id=request.user.id)
                deactivatable.update(is_active=False)
                for u in deactivatable:
                    log_action(request.user, 'deactivate', u, 'Bulk deactivated', request)
                messages.success(request, f'Deactivated {deactivatable.count()} user(s).')
                if deactivatable.count() < selected_users.count():
                    messages.warning(request, 'You cannot deactivate your own account.')
                    
            elif action == 'delete':
                deletable = selected_users.exclude(id=request.user.id)
                u_count = deletable.count()
                for u in deletable:
                    log_action(request.user, 'delete', None, f'Bulk deleted user {u.username}', request)
                    u.delete()
                messages.success(request, f'Deleted {u_count} user(s).')
                if u_count < selected_users.count():
                    messages.warning(request, 'You cannot delete your own account.')
                    
            elif action == 'export':
                return _export_users_csv(selected_users)
        
        qs_str = request.META.get('QUERY_STRING', '')
        return redirect(request.path + ('?' + qs_str if qs_str else ''))

    # ── Stats ──
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    stats = {
        'total': User.objects.count(),
        'active': User.objects.filter(is_active=True).count(),
        'inactive': User.objects.filter(is_active=False).count(),
        'roles': Role.objects.filter(is_active=True).count(),
        'logged_in_today': User.objects.filter(last_login__gte=today_start).count(),
        'new_this_week': User.objects.filter(date_joined__gte=seven_days_ago).count(),
    }

    # ── Pagination ──
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    roles = Role.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'roles': roles,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'page_title': 'User Management',
    }
    return render(request, 'authentication/rbac/user_list.html', context)


@login_required
@role_required('Super Admin')
def user_create(request):
    """Create a new user account with full profile details."""
    roles = Role.objects.filter(is_active=True)
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        role_id = request.POST.get('role')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        is_active = request.POST.get('is_active', 'on') == 'on'

        errors = []
        if not username:
            errors.append('Username is required.')
        elif User.objects.filter(username=username).exists():
            errors.append('Username already exists.')
        if email and User.objects.filter(email=email).exists():
            errors.append('Email already in use.')
        if password != confirm_password:
            errors.append('Passwords do not match.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'authentication/rbac/user_form.html', {
                'roles': roles, 'form_data': request.POST
            })

        user = User.objects.create_user(
            username=username, email=email,
            first_name=first_name, last_name=last_name,
        )
        user.set_password(password)
        user.is_active = is_active
        user.save()

        # Build profile
        profile = UserProfile.objects.create(user=user, phone=phone)
        if role_id:
            try:
                role_obj = Role.objects.get(id=role_id)
                profile.role = role_obj
                group, _ = Group.objects.get_or_create(name=role_obj.name)
                group.user_set.add(user)
            except Role.DoesNotExist:
                pass
        if request.FILES.get('photo'):
            try:
                uploaded = request.FILES['photo']
                profile.photo = uploaded
                b64_str = file_to_base64(uploaded)
                if b64_str:
                    profile.photo_data = b64_str
                profile.save()
            except Exception as e:
                messages.warning(request, f"User created, but photo upload failed: {str(e)}")
        else:
            profile.save()

        log_action(request.user, 'create', user, f'Created user {username}', request)
        messages.success(request, f"User '{username}' created successfully.")
        return redirect('user_management')

    return render(request, 'authentication/rbac/user_form.html', {'roles': roles})


@login_required
@role_required('Super Admin')
def user_detail(request, pk):
    """View full user profile and audit history."""
    target = get_object_or_404(User, pk=pk)
    profile, _ = UserProfile.objects.get_or_create(user=target)
    audit_logs = AuditLog.objects.filter(target_user=target).select_related('actor')[:50]
    return render(request, 'authentication/rbac/user_detail.html', {
        'target': target,
        'profile': profile,
        'audit_logs': audit_logs,
    })


@login_required
@role_required('Super Admin')
def user_edit(request, pk):
    """Edit an existing user's information."""
    target = get_object_or_404(User, pk=pk)
    profile, _ = UserProfile.objects.get_or_create(user=target)
    roles = Role.objects.filter(is_active=True)

    if request.method == 'POST':
        target.first_name = request.POST.get('first_name', '').strip()
        target.last_name = request.POST.get('last_name', '').strip()
        target.email = request.POST.get('email', '').strip()
        # Prevent a user from deactivating their own account
        if target.id == request.user.id:
            target.is_active = True
        else:
            target.is_active = request.POST.get('is_active') == 'on'
        target.save()

        profile.phone = request.POST.get('phone', '').strip()
        if request.FILES.get('photo'):
            try:
                uploaded = request.FILES['photo']
                profile.photo = uploaded
                b64_str = file_to_base64(uploaded)
                if b64_str:
                    profile.photo_data = b64_str
                profile.save()
            except Exception as e:
                messages.warning(request, f"Profile updated, but photo save failed: {str(e)}")

        role_id = request.POST.get('role')
        if role_id:
            try:
                new_role = Role.objects.get(id=role_id)
                old_role = profile.role.name if profile.role else 'None'
                profile.role = new_role
                target.groups.clear()
                group, _ = Group.objects.get_or_create(name=new_role.name)
                target.groups.add(group)
                if old_role != new_role.name:
                    log_action(request.user, 'role_change', target,
                               f'Role changed from {old_role} to {new_role.name}', request)
            except Role.DoesNotExist:
                pass
        profile.save()

        log_action(request.user, 'edit', target, f'Edited user {target.username}', request)
        messages.success(request, f"User '{target.username}' updated successfully.")
        return redirect('user_detail', pk=pk)

    return render(request, 'authentication/rbac/user_form.html', {
        'roles': roles,
        'target': target,
        'profile': profile,
        'edit_mode': True,
    })


@login_required
@role_required('Super Admin')
def user_delete(request, pk):
    """Confirm and delete a user account."""
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        if target.id == request.user.id:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('user_management')
        username = target.username
        log_action(request.user, 'delete', None, f'Deleted user {username}', request)
        target.delete()
        messages.success(request, f"User '{username}' has been deleted.")
        return redirect('user_management')

    return render(request, 'authentication/rbac/user_confirm_delete.html', {'target': target})


@login_required
@role_required('Super Admin')
def user_toggle_status(request, pk):
    """Activate or deactivate a user account."""
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        if target.id == request.user.id:
            messages.error(request, 'You cannot deactivate your own account.')
            return redirect('user_management')
        target.is_active = not target.is_active
        target.save()
        action = 'activate' if target.is_active else 'deactivate'
        log_action(request.user, action, target, f'Account {"activated" if target.is_active else "deactivated"}', request)
        messages.success(request, f"User '{target.username}' has been {'activated' if target.is_active else 'deactivated'}.")
    return redirect('user_management')


@login_required
@role_required('Super Admin')
def user_lock(request, pk):
    """Lock or unlock a user account."""
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        if target.id == request.user.id:
            messages.error(request, 'You cannot lock your own account.')
            return redirect('user_management')
        profile, _ = UserProfile.objects.get_or_create(user=target)
        profile.is_locked = not profile.is_locked
        profile.save()
        action = 'lock' if profile.is_locked else 'unlock'
        log_action(request.user, action, target, f'Account {"locked" if profile.is_locked else "unlocked"}', request)
        messages.success(request, f"User '{target.username}' has been {'locked' if profile.is_locked else 'unlocked'}.")
    return redirect('user_management')


@login_required
@role_required('Super Admin')
def user_reset_password(request, pk):
    """Reset a user's password to a new value provided by the Super Admin."""
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not new_password or len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            target.set_password(new_password)
            target.save()
            log_action(request.user, 'password_reset', target, f'Password reset for {target.username}', request)
            messages.success(request, f"Password for '{target.username}' has been reset successfully.")
            return redirect('user_management')

    return render(request, 'authentication/rbac/user_reset_password.html', {'target': target})


@login_required
@role_required('Super Admin')
def user_change_role(request, pk):
    """Change a user's role via modal POST."""
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        role_id = request.POST.get('role_id')
        if role_id:
            role = get_object_or_404(Role, id=role_id)
            profile, _ = UserProfile.objects.get_or_create(user=target)
            old_role = profile.role.name if profile.role else 'None'
            profile.role = role
            profile.save()
            target.groups.clear()
            group, _ = Group.objects.get_or_create(name=role.name)
            target.groups.add(group)
            log_action(request.user, 'role_change', target,
                       f'Role changed from {old_role} to {role.name}', request)
            messages.success(request, f"Role updated for '{target.username}'.")
    return redirect('user_management')


@login_required
@role_required('Super Admin')
def user_export(request):
    """Export filtered user list as CSV."""
    qs = User.objects.select_related('profile', 'profile__role').order_by('username')
    selected_ids = request.GET.getlist('ids')
    if selected_ids:
        qs = qs.filter(id__in=selected_ids)

    log_action(request.user, 'export', None, f'Exported {qs.count()} user records', request)
    return _export_users_csv(qs)


def _export_users_csv(queryset):
    """Internal helper — stream a CSV response for a User queryset."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['ID', 'Username', 'Full Name', 'Email', 'Phone', 'Role', 'Status', 'Locked', 'Date Joined', 'Last Login'])
    for u in queryset:
        profile = getattr(u, 'profile', None)
        writer.writerow([
            u.id,
            u.username,
            u.get_full_name(),
            u.email,
            profile.phone if profile else '',
            profile.role.name if profile and profile.role else 'No Role',
            'Active' if u.is_active else 'Inactive',
            'Yes' if profile and profile.is_locked else 'No',
            u.date_joined.strftime('%Y-%m-%d %H:%M'),
            u.last_login.strftime('%Y-%m-%d %H:%M') if u.last_login else 'Never',
        ])
    return response


@login_required
@role_required('Super Admin')
def user_audit(request, pk):
    """View the full audit log for a specific user."""
    target = get_object_or_404(User, pk=pk)
    logs = AuditLog.objects.filter(
        Q(target_user=target) | Q(actor=target)
    ).select_related('actor', 'target_user').order_by('-timestamp')
    return render(request, 'authentication/rbac/user_audit.html', {
        'target': target,
        'logs': logs,
    })


# Old alias kept for backward-compat from existing sidebar link
@login_required
@role_required('Super Admin')
def user_update_role(request, user_id):
    """Legacy endpoint — delegates to user_change_role."""
    return user_change_role(request, pk=user_id)



from django import forms
from .models import SystemSettings

TIMEZONE_CHOICES = [
    ('UTC', 'UTC'),
    ('Asia/Kolkata', 'Asia/Kolkata (IST)'),
    ('America/New_York', 'America/New_York (EST/EDT)'),
    ('Europe/London', 'Europe/London (GMT/BST)'),
    ('Asia/Dubai', 'Asia/Dubai'),
    ('Asia/Singapore', 'Asia/Singapore'),
]

class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'system_name', 'organization_name', 'logo', 'favicon', 
            'theme_color', 'dark_mode_default', 'timezone', 
            'date_format', 'time_format', 'currency', 'language', 
            'maintenance_mode', 'system_version', 'license_key', 'license_expiry',
            'session_timeout', 'login_attempt_limit', 'allowed_ips',
            'enable_audit_logs', 'password_expiry_days', 'backup_frequency'
        ]
        widgets = {
            'system_name': forms.TextInput(attrs={'class': 'form-control'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'favicon': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'theme_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'dark_mode_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'timezone': forms.Select(choices=TIMEZONE_CHOICES, attrs={'class': 'form-select'}),
            'date_format': forms.TextInput(attrs={'class': 'form-control'}),
            'time_format': forms.TextInput(attrs={'class': 'form-control'}),
            'currency': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.TextInput(attrs={'class': 'form-control'}),
            'maintenance_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'system_version': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'license_key': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'license_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'session_timeout': forms.NumberInput(attrs={'class': 'form-control', 'min': 60, 'placeholder': 'e.g. 1800 (seconds)'}),
            'login_attempt_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 20, 'placeholder': 'e.g. 5 attempts'}),
            'allowed_ips': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'e.g. 192.168.1.1, 10.0.0.0/24 (blank for all)'}),
            'enable_audit_logs': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'password_expiry_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'e.g. 90 (0 to disable)'}),
            'backup_frequency': forms.Select(choices=[
                ('daily', 'Daily Auto-Backup'),
                ('weekly', 'Weekly Auto-Backup'),
                ('monthly', 'Monthly Auto-Backup'),
                ('manual', 'Manual Backups Only')
            ], attrs={'class': 'form-select'}),
        }


@login_required
@role_required('Super Admin')
def system_settings_view(request):
    settings = SystemSettings.get_settings()
    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, request.FILES, instance=settings)
        if form.is_valid():
            obj = form.save(commit=False)

            # Process logo upload or clear
            if 'logo' in request.FILES:
                b64_logo = file_to_base64(request.FILES['logo'])
                if b64_logo:
                    obj.logo_data = b64_logo
            elif request.POST.get('logo-clear') == 'on':
                obj.logo_data = None
                obj.logo = None

            # Process favicon upload or clear
            if 'favicon' in request.FILES:
                b64_fav = file_to_base64(request.FILES['favicon'])
                if b64_fav:
                    obj.favicon_data = b64_fav
            elif request.POST.get('favicon-clear') == 'on':
                obj.favicon_data = None
                obj.favicon = None

            obj.save()
            messages.success(request, "Global system settings updated successfully!")
            return redirect('system_settings_view')
    else:
        form = SystemSettingsForm(instance=settings)

    return render(request, 'authentication/system_settings.html', {
        'form': form,
        'settings': settings,
    })


@require_POST
def keep_alive_view(request):
    """Refreshes the user's session timestamp without reloading the page."""
    if request.user.is_authenticated:
        now_ts = int(time.time())
        request.session['_last_activity'] = now_ts
        timeout = getattr(settings, 'SESSION_COOKIE_AGE', 900)
        return JsonResponse({'status': 'success', 'last_activity': now_ts, 'timeout': timeout})
    return JsonResponse({'status': 'unauthorized'}, status=401)





