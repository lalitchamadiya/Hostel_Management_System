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
from django.core.cache import cache
from django.contrib.auth import update_session_auth_hash

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

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(password)
        except ValidationError as e:
            for err in e.messages:
                messages.error(request, err)
            return render(request, 'authentication/register.html', context)

        user = User.objects.create_user(username=username, email=email)
        user.set_password(password)
        user.save()

        # Public self-registration strictly assigns Student role to prevent privilege escalation
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
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Rate limiting check: max N failed attempts per minute per IP
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        client_ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR', '127.0.0.1')

        try:
            settings_obj = SystemSettings.get_settings()
        except Exception:
            settings_obj = None

        rate_limit = getattr(settings_obj, 'login_attempt_limit', 5) or 5
        rate_key = f"login_rate_{client_ip}"
        attempt_data = cache.get(rate_key)
        now_ts = int(time.time())

        if attempt_data and isinstance(attempt_data, dict):
            elapsed = now_ts - attempt_data.get('start_ts', now_ts)
            if elapsed < 60:
                if attempt_data.get('count', 0) >= rate_limit:
                    remaining = max(1, 60 - elapsed)
                    messages.error(request, f"Too many failed login attempts. Limit is {rate_limit} attempt(s) per minute. Please wait {remaining} seconds before trying again.")
                    return render(request, 'authentication/login.html', {'fieldValues': {'username': username}})
            else:
                attempt_data = {'count': 0, 'start_ts': now_ts}
                cache.set(rate_key, attempt_data, timeout=60)
        else:
            attempt_data = {'count': 0, 'start_ts': now_ts}
            cache.set(rate_key, attempt_data, timeout=60)

        if username and password:
            user = auth.authenticate(username=username, password=password)
            if user:
                # Login succeeded: clear failed attempts
                cache.delete(rate_key)

                profile = None
                try:
                    profile = user.profile
                except Exception:
                    pass

                # Check if account is locked
                if profile and profile.is_locked:
                    messages.error(request, 'Your account has been locked. Contact an administrator.')
                    return render(request, 'authentication/login.html', {'fieldValues': {'username': username}})

                if user.is_active:
                    auth.login(request, user)
                    
                    # Dynamically set session timeout from SystemSettings
                    session_timeout = getattr(settings_obj, 'session_timeout', 1800) or 1800
                    request.session.set_expiry(session_timeout)
                    request.session['_last_activity'] = int(time.time())

                    log_action(user, 'login', user, request=request)

                    # Check password expiry cycle
                    expiry_days = getattr(settings_obj, 'password_expiry_days', 0) or 0
                    if expiry_days > 0:
                        last_changed = None
                        if profile and profile.password_changed_at:
                            last_changed = profile.password_changed_at
                        elif user.date_joined:
                            last_changed = user.date_joined

                        if last_changed and (timezone.now() - last_changed).days >= expiry_days:
                            return redirect('password_expired')

                    if profile and profile.role and profile.role.is_active:
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
                        else:
                            return redirect('superadmin_dashboard')
                    elif user.is_superuser:
                        return redirect('superadmin_dashboard')
                    else:
                        log_action(user, 'missing_role_access_blocked', user, details="User attempted login with missing or inactive role - redirected to no_role under Fail-Closed Security", request=request)
                        return redirect('no_role')

                messages.error(request, 'Account is not active')
                return render(request, 'authentication/login.html', {'fieldValues': {'username': username}})

            # Failed credentials: increment rate counter
            attempt_data['count'] = attempt_data.get('count', 0) + 1
            cache.set(rate_key, attempt_data, timeout=60)
            remaining_attempts = max(0, rate_limit - attempt_data['count'])
            if remaining_attempts > 0:
                messages.error(request, f'Invalid credentials. {remaining_attempts} attempt(s) remaining this minute.')
            else:
                messages.error(request, f'Too many failed login attempts. Limit of {rate_limit} attempt(s) per minute reached. Please wait 1 minute.')
            return render(request, 'authentication/login.html', {'fieldValues': {'username': username}})

        messages.error(request, 'Please fill all fields')
        return render(request, 'authentication/login.html')

class LogoutView(View):

    def post(self, request):

        if request.user.is_authenticated:

            log_action(request.user, 'logout', request.user, request=request)

        auth.logout(request)

        return redirect('login')

    def get(self, request):

        return self.post(request)





# ---------------------------------------------------------------------------

# Role Management

# ---------------------------------------------------------------------------



@login_required

@role_required('Super Admin')

def role_list(request):

    roles = Role.objects.exclude(is_superadmin=True).annotate(assigned_count=Count('userprofile')).order_by('-created_at')

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

        messages.error(request, 'Super Admin role is a protected system role and cannot be deleted.')

        return redirect('role_list')

    assigned_users_count = UserProfile.objects.filter(role=role).count()
    from hms.models import StaffProfile
    assigned_staff_count = StaffProfile.objects.filter(user__profile__role=role).count()
    total_assigned = max(assigned_users_count, assigned_staff_count)

    if total_assigned > 0:
        log_action(request.user, 'role_delete_blocked', None,
                   f"Blocked deletion of role '{role.name}': currently assigned to {total_assigned} user(s)/staff member(s).", request)
        messages.error(
            request,
            f"Role Protection: Cannot delete role '{role.name}' because {total_assigned} user(s) or staff member(s) are currently assigned to it. "
            f"Please reassign all users to another role before deleting. Consider deactivating the role instead."
        )
        return redirect('role_list')

    role_name = role.name
    role.delete()
    log_action(request.user, 'role_delete', None, f"Deleted role '{role_name}'", request)
    messages.success(request, f"Role '{role_name}' deleted successfully.")

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

                deletable = selected_users.exclude(id=request.user.id).exclude(is_superuser=True).exclude(profile__role__is_superadmin=True)

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



    missing_role_count = User.objects.filter(is_active=True, is_superuser=False).filter(
        Q(profile__role__isnull=True) | Q(profile__role__is_active=False)
    ).count()

    context = {

        'page_obj': page_obj,

        'stats': stats,

        'roles': roles,

        'search': search,

        'role_filter': role_filter,

        'status_filter': status_filter,

        'missing_role_count': missing_role_count,

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
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(password)
        except ValidationError as e:
            for err in e.messages:
                errors.append(err)



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
        try:
            from hms.utils import sync_user_to_staff
            sync_user_to_staff(user)
        except Exception:
            pass

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

        try:
            from hms.utils import sync_user_to_staff
            sync_user_to_staff(target)
        except Exception:
            pass

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
    ('Asia/Kolkata', 'Asia/Kolkata (IST +05:30)'),
    ('America/New_York', 'America/New_York (EST/EDT)'),
    ('America/Chicago', 'America/Chicago (CST/CDT)'),
    ('America/Denver', 'America/Denver (MST/MDT)'),
    ('America/Los_Angeles', 'America/Los_Angeles (PST/PDT)'),
    ('Europe/London', 'Europe/London (GMT/BST)'),
    ('Europe/Paris', 'Europe/Paris (CET/CEST)'),
    ('Europe/Berlin', 'Europe/Berlin (CET/CEST)'),
    ('Asia/Dubai', 'Asia/Dubai (GST +04:00)'),
    ('Asia/Singapore', 'Asia/Singapore (SGT +08:00)'),
    ('Asia/Tokyo', 'Asia/Tokyo (JST +09:00)'),
    ('Australia/Sydney', 'Australia/Sydney (AEST/AEDT)'),
    ('Asia/Karachi', 'Asia/Karachi (PKT +05:00)'),
    ('Asia/Dhaka', 'Asia/Dhaka (BST +06:00)'),
    ('Africa/Cairo', 'Africa/Cairo (EEST +03:00)'),
    ('Africa/Johannesburg', 'Africa/Johannesburg (SAST +02:00)'),
]

class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'system_name', 'organization_name', 'logo', 'favicon', 
            'theme_color', 'dark_mode_default', 'show_theme_toggle', 'timezone', 
            'date_format', 'time_format', 'currency', 'language', 
            'maintenance_mode', 'auto_recovery_enabled', 'maintenance_type', 'maintenance_status',
            'maintenance_title', 'maintenance_reason', 'maintenance_message',
            'maintenance_stage', 'maintenance_progress', 'estimated_restoration_time',
            'health_check_interval', 'consecutive_success_required',
            'support_email', 'support_phone', 'helpdesk_url',
            'system_version', 'license_key', 'license_expiry',
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
            'show_theme_toggle': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'timezone': forms.Select(choices=TIMEZONE_CHOICES, attrs={'class': 'form-select', 'id': 'id_timezone'}),
            'date_format': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_date_format'}),
            'time_format': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_time_format'}),
            'currency': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.TextInput(attrs={'class': 'form-control'}),
            'maintenance_mode': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_maintenance_mode'}),
            'auto_recovery_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_auto_recovery_enabled'}),
            'maintenance_type': forms.Select(attrs={'class': 'form-select'}),
            'maintenance_status': forms.Select(attrs={'class': 'form-select'}),
            'maintenance_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., System Under Maintenance'}),
            'maintenance_reason': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Scheduled Database Migration'}),
            'maintenance_message': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter public maintenance announcement message...'}),
            'maintenance_stage': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Diagnostics & Integrity Checks'}),
            'maintenance_progress': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '100'}),
            'estimated_restoration_time': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 2026-11-03 14:00 UTC'}),
            'health_check_interval': forms.NumberInput(attrs={'class': 'form-control', 'min': '5'}),
            'consecutive_success_required': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'support_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'support@hostel.com'}),
            'support_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 (800) 555-0199'}),
            'helpdesk_url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'https://support.hostel.com'}),
            'system_version': forms.TextInput(attrs={'class': 'form-control'}),
            'license_key': forms.TextInput(attrs={'class': 'form-control'}),
            'license_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'session_timeout': forms.NumberInput(attrs={'class': 'form-control', 'min': '60'}),
            'login_attempt_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'allowed_ips': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'enable_audit_logs': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'password_expiry_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'backup_frequency': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                if field_name in self.data:
                    val = self.data.get(field_name)
                    cleaned_data[field_name] = str(val).strip().lower() in ['on', 'true', '1', 'yes'] or val is True
                elif self.instance and self.instance.pk:
                    cleaned_data[field_name] = getattr(self.instance, field_name)
            else:
                if field_name not in self.data and self.instance and self.instance.pk:
                    cleaned_data[field_name] = getattr(self.instance, field_name)
        return cleaned_data



def _try_migrate_branding_to_base64(settings_obj):

    """
    If SystemSettings has file-based logo/favicon paths but no base64 data,
    read the files from disk and convert them to base64 data URIs for persistence.
    Handles uploads that occurred BEFORE the base64 code was deployed (e.g. on Vercel
    where /tmp/media is ephemeral). Safe to call on every GET — it no-ops when
    logo_data / favicon_data already exist or when the files are not on disk.
    """

    import os as _os, base64 as _b64, mimetypes as _mime

    from django.conf import settings as _djsettings

    migrated = False

    for field_name, data_attr in [('logo', 'logo_data'), ('favicon', 'favicon_data')]:

        field = getattr(settings_obj, field_name, None)

        existing_data = getattr(settings_obj, data_attr, None)

        if field and getattr(field, 'name', None) and not existing_data:

            try:

                file_path = _os.path.join(str(_djsettings.MEDIA_ROOT), str(field.name))

                if _os.path.exists(file_path):

                    with open(file_path, 'rb') as fp:

                        raw_bytes = fp.read()

                    mime_type, _ = _mime.guess_type(field.name)

                    if not mime_type or not mime_type.startswith('image/'):

                        mime_type = 'image/jpeg'

                    b64_str = _b64.b64encode(raw_bytes).decode('utf-8')

                    setattr(settings_obj, data_attr, f"data:{mime_type};base64,{b64_str}")

                    migrated = True

            except Exception:

                pass

    if migrated:

        from authentication.models import SystemSettings as _SS

        _SS.objects.filter(pk=settings_obj.pk).update(

            logo_data=settings_obj.logo_data,

            favicon_data=settings_obj.favicon_data,

        )

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



            prev_maintenance = settings.maintenance_mode
            if obj.maintenance_mode and not prev_maintenance:
                obj.maintenance_activated_at = timezone.now()
                obj.consecutive_success_count = 0
                if obj.maintenance_status == 'restored':
                    obj.maintenance_status = 'active'
            elif not obj.maintenance_mode and prev_maintenance:
                obj.maintenance_restored_at = timezone.now()
                obj.maintenance_status = 'restored'
            obj.save()

            # Audit log activation or deactivation of maintenance mode
            if prev_maintenance != obj.maintenance_mode:
                action_status = "ENABLED" if obj.maintenance_mode else "DISABLED"
                log_action(
                    actor=request.user,
                    action='edit',
                    target_user=request.user,
                    details=f"System Maintenance Mode was {action_status} by {request.user.username}. Restoration: {obj.estimated_restoration_time}. Notice: {obj.maintenance_message}",
                    request=request
                )

            messages.success(request, "Global system settings updated successfully!")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'message': 'Global system settings updated successfully!',
                    'theme_color': obj.theme_color,
                    'dark_mode_default': obj.dark_mode_default,
                    'show_theme_toggle': obj.show_theme_toggle,
                    'maintenance_mode': obj.maintenance_mode,
                })

            return redirect('system_settings_view')

    else:

        # Convert any file-based logo/favicon to base64 for persistent serverless storage.

        # Safe no-op when already converted or files missing.

        _try_migrate_branding_to_base64(settings)

        form = SystemSettingsForm(instance=settings)



    from authentication.health import SystemHealthService
    health_summary = SystemHealthService.perform_full_health_check()
    maintenance_history = AuditLog.objects.filter(
        action__in=['maintenance_enabled', 'maintenance_disabled', 'maintenance_auto_recovered', 'health_check_failed']
    ).order_by('-timestamp')[:8]

    return render(request, 'authentication/system_settings.html', {
        'form': form,
        'settings': settings,
        'health_summary': health_summary,
        'maintenance_history': maintenance_history,
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













@login_required
def password_expired_view(request):
    """
    Enforces mandatory password reset when the configured password expiry cycle is exceeded.
    Without a successful password change, this view blocks all application navigation.
    """
    try:
        from authentication.models import SystemSettings
        settings_obj = SystemSettings.get_settings()
        expiry_days = getattr(settings_obj, 'password_expiry_days', 90) or 90
    except Exception:
        settings_obj = None
        expiry_days = 90

    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return render(request, 'authentication/password_expired.html', {'expiry_days': expiry_days, 'system_settings': settings_obj})

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return render(request, 'authentication/password_expired.html', {'expiry_days': expiry_days, 'system_settings': settings_obj})

        if len(new_password) < 6:
            messages.error(request, 'New password must be at least 6 characters long.')
            return render(request, 'authentication/password_expired.html', {'expiry_days': expiry_days, 'system_settings': settings_obj})

        if current_password == new_password:
            messages.error(request, 'New password cannot be the same as your current password.')
            return render(request, 'authentication/password_expired.html', {'expiry_days': expiry_days, 'system_settings': settings_obj})

        # Apply password update
        request.user.set_password(new_password)
        request.user.save()

        profile = getattr(request.user, 'profile', None)
        if profile:
            profile.password_changed_at = timezone.now()
            profile.save()

        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, request.user)

        log_action(request.user, 'password_reset', request.user, details="Password changed due to password expiry cycle policy", request=request)
        messages.success(request, 'Password changed successfully! You may now access your account.')

        # Redirect to designated portal
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
        elif request.user.is_superuser:
            return redirect('superadmin_dashboard')
        return redirect('no_role')

    return render(request, 'authentication/password_expired.html', {
        'expiry_days': expiry_days,
        'system_settings': settings_obj,
    })


def secure_admin_access_view(request):
    """
    Unlinked, hidden Super Admin access route (/system-control/secure-access/).
    - Accessible while maintenance mode is active.
    - Requires secure authentication and server-side Super Admin role verification.
    - Rate-limited, CSRF-protected, audit-logged.
    - Rejects unauthorized users (ordinary staff, students, wardens) with 403 or redirect.
    - Provides a dedicated Super Admin Maintenance Command Center to monitor live health,
      toggle maintenance mode, toggle auto-recovery, and review maintenance history.
    """
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    client_ip = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR', '127.0.0.1')
    settings_obj = SystemSettings.get_settings()

    if request.user.is_authenticated:
        # Verify Super Admin role
        is_super = request.user.is_superuser
        if not is_super:
            profile = getattr(request.user, 'profile', None)
            if profile and profile.role and profile.role.name == 'Super Admin':
                is_super = True

        if not is_super:
            # Unauthorized user attempting to access hidden superadmin route
            AuditLog.objects.create(
                actor=request.user,
                action='security_violation',
                details=f"Unauthorized non-superadmin user '{request.user.username}' attempted to access hidden Super Admin route /system-control/secure-access/.",
                ip_address=client_ip
            )
            return render(request, 'maintenance.html', {
                'system_settings': settings_obj,
                'maintenance_title': 'Access Denied (403)',
                'maintenance_message': 'You do not have permission to access the Super Admin control route.',
                'maintenance_status': 'active',
            }, status=403)

        # Authenticated Super Admin
        if request.method == 'POST':
            action = request.POST.get('action')

            if action == 'toggle_maintenance':
                settings_obj.maintenance_mode = not settings_obj.maintenance_mode
                if settings_obj.maintenance_mode:
                    settings_obj.maintenance_activated_at = timezone.now()
                    settings_obj.consecutive_success_count = 0
                    if settings_obj.maintenance_status == 'restored':
                        settings_obj.maintenance_status = 'active'
                    AuditLog.objects.create(
                        actor=request.user,
                        action='maintenance_enabled',
                        details=f"Maintenance mode manually enabled by {request.user.username} via Secure Access Control.",
                        ip_address=client_ip
                    )
                    messages.success(request, "Global System Maintenance Mode has been ENABLED (HTTP 503 active).")
                else:
                    settings_obj.maintenance_restored_at = timezone.now()
                    settings_obj.maintenance_status = 'restored'
                    AuditLog.objects.create(
                        actor=request.user,
                        action='maintenance_disabled',
                        details=f"Maintenance mode manually disabled by {request.user.username} via Secure Access Control.",
                        ip_address=client_ip
                    )
                    messages.success(request, "Global System Maintenance Mode has been DISABLED (Normal operations restored).")
                settings_obj.save()

            elif action == 'toggle_auto_recovery':
                settings_obj.auto_recovery_enabled = not settings_obj.auto_recovery_enabled
                settings_obj.save()
                AuditLog.objects.create(
                    actor=request.user,
                    action='edit',
                    details=f"Automatic Maintenance Recovery policy set to {settings_obj.auto_recovery_enabled} by {request.user.username}.",
                    ip_address=client_ip
                )
                messages.success(request, f"Automatic Maintenance Recovery is now {'ENABLED' if settings_obj.auto_recovery_enabled else 'DISABLED'}.")

            elif action == 'run_health_check':
                from authentication.health import SystemHealthService
                result = SystemHealthService.evaluate_and_recover(
                    trigger='manual',
                    actor=request.user,
                    ip_address=client_ip
                )
                if result.get('recovered'):
                    messages.success(request, "System health verification passed! Maintenance mode automatically lifted and service restored.")
                elif result['health']['healthy']:
                    messages.info(request, f"Health check passed ({result.get('consecutive_count')}/{settings_obj.consecutive_success_required} consecutive passes). All critical subsystems are operational.")
                else:
                    failed = [c['name'] for c in result['health']['checks'] if not c['passed']]
                    messages.error(request, f"Health check failed: {', '.join(failed)}. Maintenance mode retained.")

            elif action == 'update_details':
                settings_obj.maintenance_status = request.POST.get('maintenance_status', settings_obj.maintenance_status)
                settings_obj.maintenance_type = request.POST.get('maintenance_type', settings_obj.maintenance_type)
                settings_obj.maintenance_title = request.POST.get('maintenance_title', settings_obj.maintenance_title)
                settings_obj.maintenance_reason = request.POST.get('maintenance_reason', settings_obj.maintenance_reason)
                settings_obj.maintenance_message = request.POST.get('maintenance_message', settings_obj.maintenance_message)
                settings_obj.maintenance_stage = request.POST.get('maintenance_stage', settings_obj.maintenance_stage)
                try:
                    settings_obj.maintenance_progress = int(request.POST.get('maintenance_progress', 50))
                except Exception:
                    pass
                settings_obj.estimated_restoration_time = request.POST.get('estimated_restoration_time', settings_obj.estimated_restoration_time)
                settings_obj.save()
                messages.success(request, "Maintenance parameters updated successfully.")

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'maintenance_mode': settings_obj.maintenance_mode})
            return redirect('/system-control/secure-access/')

        # GET request: Render Super Admin Command Center
        from authentication.health import SystemHealthService
        health_summary = SystemHealthService.perform_full_health_check()
        recent_logs = AuditLog.objects.filter(
            action__in=[
                'maintenance_enabled', 'maintenance_disabled', 'maintenance_auto_recovered',
                'health_check_failed', 'secure_access_login', 'security_violation', 'login'
            ]
        ).order_by('-timestamp')[:10]

        return render(request, 'authentication/secure_admin_command.html', {
            'system_settings': settings_obj,
            'health_summary': health_summary,
            'recent_logs': recent_logs,
        })

    # Unauthenticated visitor attempting to access hidden route
    if request.method == 'POST':
        # 1-minute rate limiting
        rate_key = f"secure_admin_login_rate_{client_ip}"
        attempt_data = cache.get(rate_key)
        now_ts = int(time.time())
        limit = getattr(settings_obj, 'login_attempt_limit', 5) or 5

        if attempt_data and isinstance(attempt_data, dict):
            elapsed = now_ts - attempt_data.get('start_ts', now_ts)
            if elapsed < 60:
                if attempt_data.get('count', 0) >= limit:
                    remaining = max(1, 60 - elapsed)
                    messages.error(request, f"Rate limit reached. Please wait {remaining} seconds before re-attempting secure access.")
                    return render(request, 'authentication/secure_admin_login.html', {'system_settings': settings_obj})
            else:
                attempt_data = {'count': 0, 'start_ts': now_ts}
        else:
            attempt_data = {'count': 0, 'start_ts': now_ts}

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = auth.authenticate(username=username, password=password)
        if user:
            is_super = user.is_superuser
            if not is_super:
                profile = getattr(user, 'profile', None)
                if profile and profile.role and profile.role.name == 'Super Admin':
                    is_super = True

            if is_super and user.is_active:
                cache.delete(rate_key)
                auth.login(request, user)
                AuditLog.objects.create(
                    actor=user,
                    action='secure_access_login',
                    details=f"Super Admin '{user.username}' successfully authenticated via Secure Access Route.",
                    ip_address=client_ip
                )
                return redirect('/system-control/secure-access/')
            else:
                attempt_data['count'] = attempt_data.get('count', 0) + 1
                cache.set(rate_key, attempt_data, timeout=60)
                AuditLog.objects.create(
                    actor=user,
                    action='security_violation',
                    details=f"Non-superadmin '{user.username}' attempted authentication at Secure Access route.",
                    ip_address=client_ip
                )
                messages.error(request, "Access restricted. Only verified Super Administrators are authorized.")
        else:
            attempt_data['count'] = attempt_data.get('count', 0) + 1
            cache.set(rate_key, attempt_data, timeout=60)
            messages.error(request, "Invalid username or password.")

    return render(request, 'authentication/secure_admin_login.html', {
        'system_settings': settings_obj
    })


def system_health_endpoint(request):
    """
    Restricted internal health-check endpoint (/system-control/health/).
    Accessible to authenticated Super Admins or via internal health key.
    Never exposes database credentials, passwords, or raw stack traces.
    """
    is_super = False
    if request.user.is_authenticated:
        is_super = request.user.is_superuser
        if not is_super:
            profile = getattr(request.user, 'profile', None)
            if profile and profile.role and profile.role.name == 'Super Admin':
                is_super = True

    import hashlib
    import secrets
    # Use dedicated health check key or SHA256 digest so raw SECRET_KEY is never exposed
    raw_secret = getattr(settings, 'SECRET_KEY', 'default-key')
    expected_key = os.getenv('HEALTH_CHECK_KEY') or hashlib.sha256(f"health:{raw_secret}".encode('utf-8')).hexdigest()[:32]
    provided_key = request.headers.get('X-Health-Check-Key') or request.GET.get('key') or ''
    has_key = secrets.compare_digest(provided_key, expected_key) if expected_key and provided_key else False

    if not is_super and not has_key:
        return JsonResponse({
            'status': 'error',
            'message': 'Access denied. Internal health verification requires Super Admin authentication or valid authorization key.'
        }, status=403)

    from authentication.health import SystemHealthService
    health_result = SystemHealthService.perform_full_health_check()
    settings_obj = SystemSettings.get_settings()

    status_code = 200 if health_result['healthy'] else 503
    return JsonResponse({
        'status': health_result['status'],
        'healthy': health_result['healthy'],
        'timestamp': health_result['timestamp'],
        'summary': health_result['summary'],
        'maintenance_mode': settings_obj.maintenance_mode,
        'maintenance_status': settings_obj.maintenance_status,
        'auto_recovery_enabled': settings_obj.auto_recovery_enabled,
        'consecutive_success_count': settings_obj.consecutive_success_count,
        'consecutive_success_required': settings_obj.consecutive_success_required,
        'checks': health_result['checks']
    }, status=status_code)
