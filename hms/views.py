import shutil
import csv
import os
import datetime
import ipaddress
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.contrib import messages

logger = logging.getLogger(__name__)

def _safe_int(val, default=None):
    if val is None:
        return default
    val_str = str(val).strip()
    if val_str.isdigit():
        return int(val_str)
    if val_str.startswith('-') and val_str[1:].isdigit():
        return int(val_str)
    return default

def _safe_date(val, default=None):
    if not val:
        return default
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val if isinstance(val, datetime.date) else val.date()
    try:
        return datetime.date.fromisoformat(str(val).strip())
    except Exception:
        return default

def _safe_time(val, default=None):
    if not val:
        return default
    if isinstance(val, datetime.time):
        return val
    try:
        return datetime.time.fromisoformat(str(val).strip())
    except Exception:
        return default

def _get_safe_disk_usage():
    try:
        target_path = os.getcwd()
        disk = shutil.disk_usage(target_path)
        total_gb = round(disk.total / (1024 ** 3), 1)
        used_gb = round(disk.used / (1024 ** 3), 1)
        pct = round(disk.used / disk.total * 100, 1) if disk.total > 0 else 0.0
        return total_gb, used_gb, pct
    except Exception:
        return 100.0, 10.0, 10.0

from .models import (
    StaffProfile, ComplaintTicket,
    DutyAssignment, Duty, DutyPermission, DutyApprovalLog,
    UserDashboardPreference, RoleDashboardConfig
)
from .dashboard_services import DynamicDashboardService, UserDashboardContext
from student.models import Student
from room.models import HostelBuilding, Room, Bed
from leave.models import HostelLeave
from django.contrib.auth.models import Group
from authentication.models import Role, UserProfile, AuditLog
from .utils import file_to_base64


# ──────────────────────────────────────────────────────
# Role-based access helper
# ──────────────────────────────────────────────────────
def _is_admin(user):
    if user.is_superuser:
        return True
    try:
        role = user.profile.role
        return role.is_superadmin or role.name in ('Admin', 'Staff')
    except Exception:
        return False


# ──────────────────────────────────────────────────────
# Root router
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def dashboard(request):
    user = request.user
    role = getattr(getattr(user, 'profile', None), 'role', None)

    # Super Admin preservation: always route superadmin to existing superadmin_dashboard
    if user.is_superuser or (role and role.is_superadmin) or (role and role.name == 'Admin'):
        return redirect('superadmin_dashboard')

    # Student routing
    role_name = role.name if (role and role.is_active) else None
    if role_name == 'Student' or hasattr(user, 'student'):
        return redirect('student_app:student_dashboard')

    # All other roles (Warden, Security Guard, Accountant, Cleaner, etc.) route to dynamic dashboard
    return redirect('dynamic_dashboard')


# ──────────────────────────────────────────────────────
# SUPER ADMIN DASHBOARD (PRESERVED WITHOUT MODIFICATION)
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def superadmin_dashboard(request):
    if not _is_admin(request.user):
        try:
            r_name = request.user.profile.role.name
        except Exception:
            r_name = None
        if r_name == 'Student' or hasattr(request.user, 'student'):
            return redirect('student_app:student_dashboard')
        return redirect('dynamic_dashboard')

    today = timezone.now().date()
    now = timezone.now()

    # ── Students ──
    total_students = Student.objects.count()
    active_students = Student.objects.filter(status='Active').count()
    inactive_students = total_students - active_students
    gender_male = Student.objects.filter(gender='Male').count()
    gender_female = Student.objects.filter(gender='Female').count()

    # ── Rooms & Beds ──
    total_blocks = HostelBuilding.objects.filter(is_archived=False).count()
    total_floors = HostelBuilding.objects.filter(is_archived=False).aggregate(s=Sum('total_floors'))['s'] or 0
    total_rooms = Room.objects.count()
    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(student__isnull=False).count()
    vacant_beds = Bed.objects.filter(student__isnull=True).count()
    occupancy_pct = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0

    # ── Financials ──
    today_revenue = 0
    monthly_revenue = 0
    total_revenue = 0
    pending_payments = 0
    total_expected = 0
    total_paid = 0
    total_outstanding = 0

    # ── Leaves ──
    pending_leaves = HostelLeave.objects.filter(status='pending').count()
    approved_leaves_today = HostelLeave.objects.filter(status='approved', leave_from=today).count()

    # ── HMS Models ──
    total_staff = StaffProfile.objects.count()
    active_staff = StaffProfile.objects.filter(status='active').count()
    open_complaints = ComplaintTicket.objects.filter(status__in=['pending', 'assigned', 'in_progress']).count()
    resolved_complaints = ComplaintTicket.objects.filter(status='resolved').count()

    # ── Users & Roles ──
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    # ── System Health ──
    disk_total_gb, disk_used_gb, disk_pct = _get_safe_disk_usage()

    # ── Chart Data ──
    # Monthly revenue last 6 months
    from datetime import timedelta
    import json
    monthly_labels = []
    monthly_data = []
    for i in range(5, -1, -1):
        d = (today.replace(day=1) - timedelta(days=1) * (i * 30)).replace(day=1)
        label = d.strftime('%b %Y')
        monthly_labels.append(label)
        monthly_data.append(0.0)

    monthly_labels_json = json.dumps(monthly_labels)
    monthly_data_json = json.dumps(monthly_data)

    # Recent payments
    recent_payments = []

    # Recent complaints
    recent_complaints = ComplaintTicket.objects.order_by('-created_at')[:6]

    # ── Audit Logs ──
    from django.core.paginator import Paginator
    log_qs = AuditLog.objects.select_related('actor', 'target_user', 'hostel').order_by('-timestamp')
    log_action = request.GET.get('log_action', '')
    log_search = request.GET.get('log_q', '').strip()
    log_start_date = request.GET.get('log_start_date', '').strip()
    log_end_date = request.GET.get('log_end_date', '').strip()

    if log_action:
        log_qs = log_qs.filter(action=log_action)
    if log_search:
        log_qs = log_qs.filter(
            Q(details__icontains=log_search) |
            Q(actor__username__icontains=log_search) |
            Q(target_user__username__icontains=log_search) |
            Q(ip_address__icontains=log_search)
        )
    if log_start_date:
        log_qs = log_qs.filter(timestamp__date__gte=log_start_date)
    if log_end_date:
        log_qs = log_qs.filter(timestamp__date__lte=log_end_date)

    if request.GET.get('log_export') == 'csv':
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="audit_logs_export.csv"'
        writer = csv.writer(response)
        writer.writerow(['Timestamp', 'Actor/Username', 'Action', 'Target User', 'Hostel', 'IP Address', 'Details'])
        for log in log_qs:
            writer.writerow([
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.actor.username if log.actor else 'System',
                log.get_action_display(),
                log.target_user.username if log.target_user else 'None',
                log.hostel.name if log.hostel else 'N/A',
                log.ip_address or '',
                log.details or ''
            ])
        return response

    log_paginator = Paginator(log_qs, 10)
    log_page = request.GET.get('log_page', 1)
    recent_logs = log_paginator.get_page(log_page)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
        from django.template.loader import render_to_string
        from django.http import JsonResponse
        html = render_to_string('hms/audit_logs_rows.html', {'recent_logs': recent_logs}, request=request)
        return JsonResponse({
            'html': html,
            'has_next': recent_logs.has_next(),
        })

    context = {
        'page_title': 'Super Admin Dashboard',
        # Students
        'total_students': total_students,
        'active_students': active_students,
        'inactive_students': inactive_students,
        'gender_male': gender_male,
        'gender_female': gender_female,
        # Rooms
        'total_blocks': total_blocks,
        'total_floors': total_floors,
        'total_rooms': total_rooms,
        'total_beds': total_beds,
        'occupied_beds': occupied_beds,
        'vacant_beds': vacant_beds,
        'occupancy_pct': occupancy_pct,
        # Financials
        'today_revenue': today_revenue,
        'monthly_revenue': monthly_revenue,
        'total_revenue': total_revenue,
        'pending_payments': pending_payments,
        'total_outstanding': total_outstanding,
        # Leaves
        'pending_leaves': pending_leaves,
        'approved_leaves_today': approved_leaves_today,
        # HMS
        'total_staff': total_staff,
        'active_staff': active_staff,
        'open_complaints': open_complaints,
        'resolved_complaints': resolved_complaints,
        # Users
        'total_users': total_users,
        'active_users': active_users,
        # System
        'disk_total_gb': disk_total_gb,
        'disk_used_gb': disk_used_gb,
        'disk_pct': disk_pct,
        # Charts
        'monthly_labels': monthly_labels_json,
        'monthly_data': monthly_data_json,
        # Recent data
        'recent_payments': recent_payments,
        'recent_complaints': recent_complaints,
        # Audit Logs
        'recent_logs': recent_logs,
        'log_actions': AuditLog.ACTION_CHOICES,
        'log_action_selected': log_action,
        'log_search_query': log_search,
        'log_start_date': log_start_date,
        'log_end_date': log_end_date,
    }
    return render(request, 'hms/superadmin_dashboard.html', context)


@login_required(login_url='/authentication/login')
def live_dashboard_stats(request):
    if not _is_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    today = timezone.now().date()
    
    # Students
    total_students = Student.objects.count()
    active_students = Student.objects.filter(status='Active').count()
    inactive_students = total_students - active_students
    
    # Rooms & Beds
    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(student__isnull=False).count()
    vacant_beds = Bed.objects.filter(student__isnull=True).count()
    occupancy_pct = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0

    # Financials
    monthly_revenue = 0
    today_revenue = 0

    # Complaints
    open_complaints = ComplaintTicket.objects.filter(status__in=['pending', 'assigned', 'in_progress']).count()
    resolved_complaints = ComplaintTicket.objects.filter(status='resolved').count()

    # HMS Staff
    total_staff = StaffProfile.objects.count()
    active_staff = StaffProfile.objects.filter(status='active').count()

    # Users
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    # Leaves
    pending_leaves = HostelLeave.objects.filter(status='pending').count()

    # System Health
    disk_total_gb, disk_used_gb, disk_pct = _get_safe_disk_usage()

    return JsonResponse({
        'total_students': total_students,
        'active_students': active_students,
        'inactive_students': inactive_students,
        'total_beds': total_beds,
        'occupied_beds': occupied_beds,
        'vacant_beds': vacant_beds,
        'occupancy_pct': occupancy_pct,
        'monthly_revenue': float(monthly_revenue),
        'today_revenue': float(today_revenue),
        'open_complaints': open_complaints,
        'resolved_complaints': resolved_complaints,
        'total_staff': total_staff,
        'active_staff': active_staff,
        'total_users': total_users,
        'active_users': active_users,
        'pending_leaves': pending_leaves,
        'disk_pct': disk_pct,
        'disk_used_gb': disk_used_gb,
        'disk_total_gb': disk_total_gb,
    })


# ──────────────────────────────────────────────────────
# STAFF MANAGEMENT
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def staff_list(request):
    if not _is_admin(request.user):
        return redirect('dashboard')

    from django.core.paginator import Paginator
    from hms.utils import sync_user_to_staff

    # Purge any Super Admin from StaffProfile
    StaffProfile.objects.filter(
        Q(user__is_superuser=True) |
        Q(user__profile__role__is_superadmin=True) |
        Q(user__profile__role__name__iexact='Super Admin')
    ).delete()

    # Auto-sync active non-superadmin, non-student users with roles
    try:
        staff_users = User.objects.filter(
            profile__role__isnull=False
        ).exclude(
            is_superuser=True
        ).exclude(
            profile__role__is_superadmin=True
        ).exclude(
            profile__role__name__iexact='Super Admin'
        ).exclude(
            profile__role__name__iexact='Student'
        ).select_related('profile', 'profile__role')
        for u in staff_users:
            sync_user_to_staff(u)
    except Exception as sync_err:
        import logging
        logging.getLogger(__name__).warning("Staff auto-sync exception: %s", sync_err)

    # Base QuerySet: Exclude Super Admins
    qs = StaffProfile.objects.select_related('user', 'user__profile', 'user__profile__role').exclude(
        user__is_superuser=True
    ).exclude(
        user__profile__role__is_superadmin=True
    ).exclude(
        user__profile__role__name__iexact='Super Admin'
    ).order_by('-id')

    # Available System Roles dynamically from Role Management (excluding Super Admin & Student)
    available_roles = Role.objects.filter(
        is_active=True
    ).exclude(
        is_superadmin=True
    ).exclude(
        name__iexact='Student'
    ).exclude(
        name__iexact='Super Admin'
    ).order_by('name')

    # Count staff accounts requiring role reassignment (missing, inactive, or unassigned)
    all_staff_list = list(qs)
    missing_role_count = sum(1 for s in all_staff_list if not s.has_valid_role)

    # ── Filters ──
    search = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()
    shift_filter = request.GET.get('shift', '').strip()
    performance_filter = request.GET.get('performance', '').strip()

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(designation__icontains=search) |
            Q(user__profile__role__name__icontains=search)
        )
    if role_filter:
        if role_filter == 'missing':
            # Filter accounts needing role reassignment
            qs = qs.filter(Q(user__profile__role__isnull=True) | Q(user__profile__role__is_active=False))
        elif role_filter.isdigit():
            qs = qs.filter(user__profile__role__id=int(role_filter))
        else:
            qs = qs.filter(user__profile__role__name__iexact=role_filter)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if shift_filter:
        qs = qs.filter(shift=shift_filter)
    if performance_filter:
        qs = qs.filter(performance=performance_filter)

    # ── Bulk Actions ──
    if request.method == 'POST':
        action = request.POST.get('bulk_action')
        selected_ids = request.POST.getlist('selected_staff')
        if selected_ids and action:
            selected = StaffProfile.objects.filter(id__in=selected_ids)
            if action == 'activate':
                selected.update(status='active')
                if hasattr(selected.first(), 'user') and selected.first().user:
                    for s in selected:
                        if s.user:
                            s.user.is_active = True
                            s.user.save()
                messages.success(request, f'Activated {len(selected_ids)} staff member(s).')
            elif action == 'deactivate':
                selected.update(status='inactive')
                for s in selected:
                    if s.user:
                        s.user.is_active = False
                        s.user.save()
                messages.success(request, f'Deactivated {len(selected_ids)} staff member(s).')
            elif action == 'delete':
                for s in selected:
                    if s.user:
                        s.user.delete()
                    s.delete()
                messages.success(request, 'Selected staff members deleted.')
            elif action == 'export':
                import csv
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="staff_export.csv"'
                writer = csv.writer(response)
                writer.writerow(['Name', 'Email', 'Phone', 'Designation', 'Shift', 'Status', 'Performance', 'Salary', 'Date of Joining'])
                for s in selected:
                    writer.writerow([s.name, s.email, s.phone, s.get_designation_display(), s.get_shift_display(), s.get_status_display(), s.get_performance_display(), s.salary, s.doj])
                return response
        qs_str = request.META.get('QUERY_STRING', '')
        return redirect(request.path + ('?' + qs_str if qs_str else ''))

    # ── Pagination ──
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # ── Stats ──
    today = timezone.now().date()
    seven_days_ago = today - timezone.timedelta(days=7)
    base_staff_qs = StaffProfile.objects.exclude(
        user__is_superuser=True
    ).exclude(
        user__profile__role__is_superadmin=True
    ).exclude(
        user__profile__role__name__iexact='Super Admin'
    )
    stats = {
        'total': base_staff_qs.count(),
        'active': base_staff_qs.filter(status='active').count(),
        'inactive': base_staff_qs.filter(status='inactive').count(),
        'on_leave': base_staff_qs.filter(status='on_leave').count(),
        'new_this_week': base_staff_qs.filter(doj__gte=seven_days_ago).count(),
        'designations': base_staff_qs.values('user__profile__role__name').distinct().count(),
    }

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'shift_filter': shift_filter,
        'performance_filter': performance_filter,
        'available_roles': available_roles,
        'shifts': StaffProfile.SHIFT_CHOICES,
        'statuses': StaffProfile.STATUS_CHOICES,
        'performances': StaffProfile.PERFORMANCE_CHOICES,
        'missing_role_count': missing_role_count,
        'page_title': 'Staff Management',
    }
    return render(request, 'hms/staff_list.html', context)


@login_required(login_url='/authentication/login')
def staff_create(request):
    if not _is_admin(request.user):
        return redirect('dashboard')
    
    roles = Role.objects.filter(is_active=True).exclude(is_superadmin=True).exclude(name__iexact='Student').exclude(name__iexact='Super Admin').order_by('name')
    
    if request.method == 'POST':
        data = request.POST
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        role_id = data.get('role')
        salary = data.get('salary', 0) or 0
        shift = data.get('shift', 'morning')
        status = data.get('status', 'active')
        performance = data.get('performance', 'good')
        doj = data.get('doj') or timezone.now().date()
        documents = data.get('documents', '')

        # User credentials params
        username = data.get('username', '').strip()
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')

        role_obj = None
        if role_id:
            role_obj = Role.objects.filter(id=role_id, is_active=True).exclude(is_superadmin=True).exclude(name__iexact='Super Admin').first()

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not role_obj:
            errors.append('Please select a valid active System Role from Role Management.')
            
        if username:
            if User.objects.filter(username=username).exists():
                errors.append('Username already exists.')
            if User.objects.filter(email=email).exists():
                errors.append('Email already in use.')
            if password != confirm_password:
                errors.append('Passwords do not match.')
            if len(password) < 6:
                errors.append('Password must be at least 6 characters.')
        else:
            errors.append('Username is required for staff account creation.')
        
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'hms/staff_form.html', {
                'page_title': 'Add Staff Member',
                'shifts': StaffProfile.SHIFT_CHOICES,
                'statuses': StaffProfile.STATUS_CHOICES,
                'performances': StaffProfile.PERFORMANCE_CHOICES,
                'roles': roles,
                'form_data': data
            })
            
        try:
            parts = name.split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''
            
            user = User.objects.create_user(
                username=username, email=email,
                first_name=first_name, last_name=last_name,
                password=password
            )
            user.is_active = (status == 'active')
            user.save()
            
            # Create profile
            profile = UserProfile.objects.create(user=user, phone=phone, role=role_obj)
            if role_obj:
                group, _ = Group.objects.get_or_create(name=role_obj.name)
                group.user_set.add(user)
            if request.FILES.get('photo'):
                uploaded = request.FILES['photo']
                profile.photo = uploaded
                b64_str = file_to_base64(uploaded)
                if b64_str:
                    profile.photo_data = b64_str
            profile.save()
                
            StaffProfile.objects.create(
                user=user,
                name=name,
                email=email,
                phone=phone,
                designation=role_obj.name,
                salary=salary,
                shift=shift,
                status=status,
                performance=performance,
                doj=doj,
                documents=documents,
            )
            from authentication.views import log_action
            log_action(request.user, 'create_staff', user, f"Created staff profile '{name}' with role '{role_obj.name}'", request)
            messages.success(request, f"Staff member '{name}' created successfully with role '{role_obj.name}'.")
            return redirect('staff_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('staff_list')

    return render(request, 'hms/staff_form.html', {
        'page_title': 'Add Staff Member',
        'shifts': StaffProfile.SHIFT_CHOICES,
        'statuses': StaffProfile.STATUS_CHOICES,
        'performances': StaffProfile.PERFORMANCE_CHOICES,
        'roles': roles,
    })


@login_required(login_url='/authentication/login')
def staff_edit(request, pk):
    if not _is_admin(request.user):
        return redirect('dashboard')
    staff = get_object_or_404(StaffProfile, pk=pk)
    roles = Role.objects.filter(is_active=True).exclude(is_superadmin=True).exclude(name__iexact='Student').exclude(name__iexact='Super Admin').order_by('name')
    
    if request.method == 'POST':
        data = request.POST
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        role_id = data.get('role')
        salary = data.get('salary', 0) or 0
        shift = data.get('shift', 'morning')
        status = data.get('status', 'active')
        performance = data.get('performance', 'good')
        documents = data.get('documents', '')

        # User credentials params
        username = data.get('username', '').strip()
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')

        role_obj = None
        if role_id:
            role_obj = Role.objects.filter(id=role_id, is_active=True).exclude(is_superadmin=True).exclude(name__iexact='Super Admin').first()

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not role_obj:
            errors.append('Please select a valid active System Role from Role Management.')
        if staff.user:
            if User.objects.filter(email=email).exclude(id=staff.user.id).exists():
                errors.append('Email is already in use by another user.')
            if password:
                if password != confirm_password:
                    errors.append('Passwords do not match.')
                if len(password) < 6:
                    errors.append('Password must be at least 6 characters.')
        elif username:
            if User.objects.filter(username=username).exists():
                errors.append('Username already exists.')
            if User.objects.filter(email=email).exists():
                errors.append('Email already in use.')
            if password != confirm_password:
                errors.append('Passwords do not match.')
            if len(password) < 6:
                errors.append('Password must be at least 6 characters.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'hms/staff_form.html', {
                'page_title': 'Edit Staff Member',
                'staff': staff,
                'shifts': StaffProfile.SHIFT_CHOICES,
                'statuses': StaffProfile.STATUS_CHOICES,
                'performances': StaffProfile.PERFORMANCE_CHOICES,
                'roles': roles,
                'form_data': data
            })

        try:
            if staff.user:
                user = staff.user
                parts = name.split(' ', 1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ''
                user.email = email
                user.is_active = (status == 'active')
                if password:
                    user.set_password(password)
                user.save()
                
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.phone = phone
                if role_obj:
                    if profile.role and profile.role != role_obj:
                        old_group = Group.objects.filter(name=profile.role.name).first()
                        if old_group:
                            old_group.user_set.remove(user)
                    profile.role = role_obj
                    group, _ = Group.objects.get_or_create(name=role_obj.name)
                    group.user_set.add(user)
                if request.FILES.get('photo'):
                    uploaded = request.FILES['photo']
                    profile.photo = uploaded
                    b64_str = file_to_base64(uploaded)
                    if b64_str:
                        profile.photo_data = b64_str
                profile.save()
            elif username:
                parts = name.split(' ', 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ''
                
                user = User.objects.create_user(
                    username=username, email=email,
                    first_name=first_name, last_name=last_name,
                    password=password
                )
                user.is_active = (status == 'active')
                user.save()
                
                profile = UserProfile.objects.create(user=user, phone=phone, role=role_obj)
                if role_obj:
                    group, _ = Group.objects.get_or_create(name=role_obj.name)
                    group.user_set.add(user)
                if request.FILES.get('photo'):
                    uploaded = request.FILES['photo']
                    profile.photo = uploaded
                    b64_str = file_to_base64(uploaded)
                    if b64_str:
                        profile.photo_data = b64_str
                profile.save()
                staff.user = user

            staff.name = name
            staff.email = email
            staff.phone = phone
            staff.designation = role_obj.name if role_obj else ''
            staff.salary = salary
            staff.shift = shift
            staff.status = status
            staff.performance = performance
            staff.documents = documents
            staff.save()
            from authentication.views import log_action
            log_action(request.user, 'role_reassigned', staff.user, f"Updated staff profile '{name}' and assigned role '{role_obj.name if role_obj else 'None'}'", request)
            messages.success(request, f"Staff member '{name}' updated successfully with role '{role_obj.name if role_obj else ''}'.")
            return redirect('staff_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('staff_list')

    return render(request, 'hms/staff_form.html', {
        'page_title': 'Edit Staff Member',
        'staff': staff,
        'shifts': StaffProfile.SHIFT_CHOICES,
        'statuses': StaffProfile.STATUS_CHOICES,
        'performances': StaffProfile.PERFORMANCE_CHOICES,
        'roles': roles,
    })


@login_required(login_url='/authentication/login')
def staff_delete(request, pk):
    if not _is_admin(request.user):
        return redirect('dashboard')
    staff = get_object_or_404(StaffProfile, pk=pk)
    if request.method == 'POST':
        if staff.user:
            staff.user.delete()
        staff.delete()
        messages.success(request, 'Staff member removed.')
    return redirect('staff_list')


@login_required(login_url='/authentication/login')
def staff_toggle_status(request, pk):
    """Toggle a staff member's status between active and inactive."""
    if not _is_admin(request.user):
        return redirect('dashboard')
    if request.method == 'POST':
        staff = get_object_or_404(StaffProfile, pk=pk)
        if staff.status == 'active':
            staff.status = 'inactive'
            if staff.user:
                staff.user.is_active = False
                staff.user.save()
            messages.success(request, f'{staff.name} set to Inactive.')
        else:
            staff.status = 'active'
            if staff.user:
                staff.user.is_active = True
                staff.user.save()
            messages.success(request, f'{staff.name} set to Active.')
        staff.save()
    return redirect('staff_list')


# ──────────────────────────────────────────────────────
# COMPLAINT MANAGEMENT
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def complaint_list(request):
    if not _is_admin(request.user):
        return redirect('dashboard')
    complaints = ComplaintTicket.objects.select_related('student', 'assigned_to').order_by('-created_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        complaints = complaints.filter(status=status_filter)
    staff_members = StaffProfile.objects.filter(status='active')
    context = {
        'complaints': complaints,
        'status_filter': status_filter,
        'staff_members': staff_members,
        'page_title': 'Complaint Management',
        'statuses': ComplaintTicket.STATUS_CHOICES,
    }
    return render(request, 'hms/complaint_list.html', context)


@login_required(login_url='/authentication/login')
def complaint_assign(request, pk):
    if not _is_admin(request.user):
        return redirect('dashboard')
    complaint = get_object_or_404(ComplaintTicket, pk=pk)
    if request.method == 'POST':
        staff_id = request.POST.get('staff_id')
        if staff_id:
            complaint.assigned_to = get_object_or_404(StaffProfile, pk=staff_id)
            complaint.status = 'assigned'
            complaint.save()
            messages.success(request, 'Complaint assigned.')
    return redirect('complaint_list')


@login_required(login_url='/authentication/login')
def complaint_resolve(request, pk):
    if not _is_admin(request.user):
        return redirect('dashboard')
    complaint = get_object_or_404(ComplaintTicket, pk=pk)
    if request.method == 'POST':
        complaint.status = 'resolved'
        complaint.resolved_at = timezone.now()
        complaint.feedback = request.POST.get('feedback', '')
        complaint.save()
        messages.success(request, 'Complaint resolved.')
    return redirect('complaint_list')








# ──────────────────────────────────────────────────────
# REPORTS & EXPORT
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def reports_dashboard(request):
    if not _is_admin(request.user):
        return redirect('dashboard')
    context = {
        'page_title': 'Reports & Analytics',
        'total_students': Student.objects.count(),
        'total_complaints': ComplaintTicket.objects.count(),
        'staff_count': StaffProfile.objects.count(),
    }
    return render(request, 'hms/reports.html', context)


@login_required(login_url='/authentication/login')
def export_report(request, module):
    if not _is_admin(request.user):
        return redirect('dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{module}_report.csv"'
    writer = csv.writer(response)

    if module == 'students':
        writer.writerow(['ID', 'Name', 'Email', 'Course', 'Department', 'Status', 'Admission Date'])
        for s in Student.objects.all():
            writer.writerow([s.student_id, s.name, s.email, s.course, s.department, s.status, s.admission_date])

    elif module == 'staff':
        writer.writerow(['ID', 'Name', 'Email', 'Designation', 'Shift', 'Status', 'Salary'])
        for s in StaffProfile.objects.all():
            writer.writerow([s.id, s.name, s.email, s.get_designation_display(), s.shift, s.status, s.salary])

    elif module == 'complaints':
        writer.writerow(['ID', 'Title', 'Student', 'Category', 'Status', 'Created'])
        for c in ComplaintTicket.objects.select_related('student').all():
            writer.writerow([c.id, c.title, c.student.name, c.get_category_display(), c.status, c.created_at.date()])

    else:
        writer.writerow(['No data available for this module.'])

    return response


# ──────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────
# ENTERPRISE STAFF DUTY ACCESS & SCHEDULING MODULE
# ──────────────────────────────────────────────────────
from authentication.decorators import permission_required, api_permission_required
from hms.duty_services import DutyConflictService, DutyAuthorizationService, DutyWorkflowService
from room.models import HostelBuilding, Room

def _get_client_ip(request):
    raw_ip = None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        raw_ip = x_forwarded_for.split(',')[0].strip()
    else:
        raw_ip = request.META.get('REMOTE_ADDR')
    if not raw_ip:
        return None
    raw_ip = str(raw_ip).strip()
    if raw_ip.startswith('[') and ']' in raw_ip:
        raw_ip = raw_ip[1:raw_ip.index(']')]
    elif ':' in raw_ip and raw_ip.count(':') == 1:
        raw_ip = raw_ip.split(':')[0]
    try:
        ipaddress.ip_address(raw_ip)
        return raw_ip
    except ValueError:
        return None

def ensure_default_duty_templates():
    """Seeds standard duty templates if none currently exist in database."""
    try:
        if Duty.objects.exists():
            return
        defaults = [
            {
                'name': 'Hostel Warden Shift',
                'category': 'Hostel Administration',
                'priority': 'high',
                'data_scope': 'BUILDING',
                'start_time': datetime.time(8, 0),
                'end_time': datetime.time(18, 0),
                'description': 'Daytime hostel warden supervision across assigned building.',
                'perms': {
                    'student': ['view', 'add', 'edit', 'verify', 'print', 'export'],
                    'room': ['view', 'add', 'edit', 'verify'],
                    'leave': ['view', 'approve', 'reject', 'verify'],
                    'attendance': ['view', 'add', 'edit', 'verify'],
                    'complaint': ['view', 'add', 'edit', 'verify', 'assign'],
                    'duty_management': ['view'],
                }
            },
            {
                'name': 'Campus Security Patrol',
                'category': 'Campus Security',
                'priority': 'critical',
                'data_scope': 'ASSIGNED_LOCATION',
                'start_time': datetime.time(20, 0),
                'end_time': datetime.time(6, 0),
                'description': 'Overnight gate and security monitoring at assigned entrance post.',
                'perms': {
                    'visitor': ['view', 'add', 'verify'],
                    'student': ['view'],
                    'complaint': ['view', 'add'],
                    'duty_management': ['view'],
                }
            },
            {
                'name': 'Maintenance & Facilities Inspector',
                'category': 'Maintenance',
                'priority': 'medium',
                'data_scope': 'BUILDING',
                'start_time': datetime.time(9, 0),
                'end_time': datetime.time(17, 0),
                'description': 'Inspects room facilities, plumbing, and resolves student complaints.',
                'perms': {
                    'room': ['view', 'edit'],
                    'complaint': ['view', 'edit', 'verify'],
                    'duty_management': ['view'],
                }
            }
        ]
        for d_info in defaults:
            duty = Duty.objects.create(
                name=d_info['name'],
                category=d_info['category'],
                priority=d_info['priority'],
                data_scope=d_info['data_scope'],
                start_time=d_info['start_time'],
                end_time=d_info['end_time'],
                description=d_info['description'],
                status='active'
            )
            for mod, acts in d_info['perms'].items():
                kwargs = {f'can_{act}': True for act in acts}
                DutyPermission.objects.create(duty=duty, module_name=mod, **kwargs)
    except Exception as e:
        logger.warning("ensure_default_duty_templates note: %s", e)


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'view')
def duty_list(request):
    """Enterprise Duty Monitoring & Workforce Scheduling Dashboard."""
    ensure_default_duty_templates()
    ensure_default_duty_templates()
    # Base assignments queryset with full relationships
    assignments_qs = DutyAssignment.objects.select_related(
        'staff', 'staff__user', 'staff__user__profile', 'duty', 'building', 'room', 'hostel', 'supervisor'
    ).order_by('-assigned_date', '-id')

    # Filters
    search = request.GET.get('q', '').strip()
    building_filter = request.GET.get('building', '').strip()
    status_filter = request.GET.get('status', '').strip()
    priority_filter = request.GET.get('priority', '').strip()

    if search:
        assignments_qs = assignments_qs.filter(
            Q(staff__name__icontains=search) |
            Q(staff__email__icontains=search) |
            Q(duty_title__icontains=search) |
            Q(specific_location__icontains=search) |
            Q(building__name__icontains=search)
        )
    if building_filter and building_filter.isdigit():
        assignments_qs = assignments_qs.filter(building_id=int(building_filter))
    if status_filter:
        if status_filter == 'LIVE_ON_SHIFT':
            assignments_qs = [a for a in assignments_qs if a.is_currently_on_shift]
        else:
            assignments_qs = assignments_qs.filter(status=status_filter)
    if priority_filter:
        assignments_qs = assignments_qs.filter(duty__priority=priority_filter)

    # Convert to list if queryset filtered in memory
    assignments_list = list(assignments_qs) if not isinstance(assignments_qs, list) else assignments_qs

    # Comprehensive Stat Aggregations
    all_active = DutyAssignment.objects.filter(is_active=True)
    today = timezone.localtime(timezone.now()).date()
    two_days_later = today + timezone.timedelta(days=2)

    stats = {
        'total': DutyAssignment.objects.count(),
        'active_count': all_active.count(),
        'on_duty_now': sum(1 for a in all_active if a.is_currently_on_shift),
        'pending_approvals': DutyAssignment.objects.filter(status='PENDING_APPROVAL').count(),
        'expiring_soon': DutyAssignment.objects.filter(
            is_active=True,
            end_date__gte=today,
            end_date__lte=two_days_later
        ).count(),
    }

    # Dynamic system roles and eligible staff (excluding superusers/superadmins)
    staff_members = StaffProfile.objects.exclude(
        user__is_superuser=True
    ).exclude(
        user__profile__role__is_superadmin=True
    ).exclude(
        user__profile__role__name__iexact='Super Admin'
    ).filter(status='active').order_by('name')

    duties = Duty.objects.prefetch_related('permissions').select_related('privilege_ceiling_role').all().order_by('name')
    buildings = HostelBuilding.objects.filter(is_active=True).order_by('name')
    roles = Role.objects.filter(is_active=True).exclude(is_superadmin=True).exclude(name__iexact='Super Admin').order_by('name')

    # Eligible supervisors (admin / coordinator staff)
    supervisors = User.objects.filter(is_active=True).exclude(is_superuser=True).order_by('first_name', 'username')

    # Supported Modules and Actions Matrix for RBDAC configuration
    supported_modules = [
        ('student', 'Student Management'),
        ('room', 'Rooms & Beds'),
        ('leave', 'Leave Management'),
        ('attendance', 'Attendance Records'),
        ('complaint', 'Complaint System'),
        ('fee', 'Fee & Finance'),
        ('visitor', 'Visitor Log'),
        ('duty_management', 'Duty Access Module'),
    ]

    supported_actions = [
        ('view', 'View'),
        ('add', 'Add'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
        ('reject', 'Reject'),
        ('verify', 'Verify'),
        ('export', 'Export'),
        ('print', 'Print'),
        ('download', 'Download'),
        ('assign', 'Assign'),
    ]

    context = {
        'page_title': 'Staff Duties & Workforce Access Control',
        'assignments': assignments_list,
        'stats': stats,
        'staff_members': staff_members,
        'duties': duties,
        'buildings': buildings,
        'roles': roles,
        'supervisors': supervisors,
        'supported_modules': supported_modules,
        'supported_actions': supported_actions,
        'search': search,
        'building_filter': building_filter,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'assignment_statuses': DutyAssignment.ASSIGNMENT_STATUS,
        'data_scopes': Duty.SCOPE_CHOICES,
    }
    return render(request, 'hms/duty_list.html', context)


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'add')
def duty_assign(request):
    """Creates a new duty assignment with hierarchical location, conflict validation, and approval workflow."""
    if request.method == 'POST':
        try:
            data = request.POST
            staff_id = _safe_int(data.get('staff_id'))
            if not staff_id:
                messages.error(request, "Please select a valid staff member.")
                return redirect('duty_list')

            staff = StaffProfile.objects.filter(pk=staff_id).first()
            if not staff:
                messages.error(request, "Selected staff member not found.")
                return redirect('duty_list')

            duty_id = _safe_int(data.get('duty_id'))
            duty = None
            if duty_id:
                duty = Duty.objects.filter(pk=duty_id).first()

            duty_title = data.get('duty_title', '').strip()
            if not duty_title:
                duty_title = duty.name if duty else "General Duty"

            building_id = _safe_int(data.get('building_id'))
            block = data.get('block_id', '').strip() or None
            floor = _safe_int(data.get('floor_id'))
            room_id = _safe_int(data.get('room_id'))
            specific_location = data.get('specific_location', '').strip()

            today_date = timezone.localtime(timezone.now()).date()
            start_date = _safe_date(data.get('start_date'), default=today_date)
            end_date = _safe_date(data.get('end_date'), default=None)

            shift_start = _safe_time(data.get('shift_start'), default=(duty.start_time if duty else None))
            shift_end = _safe_time(data.get('shift_end'), default=(duty.end_time if duty else None))

            working_days_list = data.getlist('working_days')
            if working_days_list:
                working_days = ",".join(working_days_list)
            elif duty and duty.working_days:
                working_days = duty.working_days
            else:
                working_days = 'MON,TUE,WED,THU,FRI,SAT,SUN'

            supervisor_id = _safe_int(data.get('supervisor_id'))
            supervisor = User.objects.filter(pk=supervisor_id).first() if supervisor_id else None

            description = data.get('description', '').strip()
            force_override = data.get('force_override') == '1'

            # 1. Location Hierarchy Validation
            is_valid_loc, loc_err = DutyConflictService.validate_location_hierarchy(
                building_id=building_id, block=block, floor=floor, room_id=room_id
            )
            if not is_valid_loc:
                messages.error(request, f"Location Error: {loc_err}")
                return redirect('duty_list')

            # 2. Shift Conflict Detection
            has_conflict, conf_assign, conf_reason = DutyConflictService.detect_conflict(
                staff_id=staff.id,
                start_date=start_date,
                end_date=end_date,
                shift_start=shift_start,
                shift_end=shift_end,
                working_days=working_days
            )
            if has_conflict and not force_override:
                messages.error(request, f"Shift Conflict Detected: {conf_reason} Check 'Force Override' if authorized.")
                return redirect('duty_list')

            # 3. Staff Leave Status Check
            on_leave, leave_msg = DutyConflictService.check_staff_leave_conflict(staff.id, start_date, end_date)
            if on_leave:
                messages.warning(request, f"Notice: {leave_msg} Ensure substitute handover if required.")

            # Determine workflow status
            initial_status = 'ACTIVE'
            if duty and duty.requires_approval:
                initial_status = 'PENDING_APPROVAL'

            assignment = DutyAssignment.objects.create(
                duty=duty,
                staff=staff,
                duty_title=duty_title,
                building_id=building_id,
                block=block,
                floor=floor,
                room_id=room_id,
                specific_location=specific_location,
                start_date=start_date,
                end_date=end_date,
                shift_start=shift_start,
                shift_end=shift_end,
                working_days=working_days,
                status=initial_status,
                supervisor=supervisor,
                description=description,
                is_active=True
            )

            client_ip = _get_client_ip(request)
            try:
                DutyApprovalLog.objects.create(
                    assignment=assignment,
                    action='CREATED',
                    performed_by=request.user,
                    notes="Duty assignment registered in system.",
                    ip_address=client_ip
                )
            except Exception as log_ex:
                logger.warning("DutyApprovalLog note: %s", log_ex)

            if initial_status == 'PENDING_APPROVAL':
                try:
                    DutyApprovalLog.objects.create(
                        assignment=assignment,
                        action='SUBMITTED',
                        performed_by=request.user,
                        notes="Submitted for supervisor approval signoff.",
                        ip_address=client_ip
                    )
                except Exception as log_ex:
                    logger.warning("DutyApprovalLog note: %s", log_ex)
                messages.info(request, f"Duty assignment for '{staff.name}' created and submitted for supervisor approval.")
            else:
                messages.success(request, f"Duty assignment for '{staff.name}' activated successfully.")

        except Exception as e:
            logger.exception("Error assigning duty: %s", e)
            messages.error(request, f"Error assigning duty: {e}")

    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'edit')
def duty_edit(request, pk):
    """Updates an existing duty assignment."""
    assignment = get_object_or_404(DutyAssignment, pk=pk)
    if request.method == 'POST':
        try:
            data = request.POST
            staff_id = _safe_int(data.get('staff_id'))
            if staff_id:
                staff = StaffProfile.objects.filter(pk=staff_id).first()
                if staff:
                    assignment.staff = staff

            duty_id = _safe_int(data.get('duty_id'))
            if duty_id:
                duty = Duty.objects.filter(pk=duty_id).first()
                if duty:
                    assignment.duty = duty

            duty_title = data.get('duty_title', '').strip()
            if duty_title:
                assignment.duty_title = duty_title

            building_id = _safe_int(data.get('building_id'))
            block = data.get('block_id', '').strip() or None
            floor = _safe_int(data.get('floor_id'))
            room_id = _safe_int(data.get('room_id'))
            specific_location = data.get('specific_location', '').strip()

            start_date = _safe_date(data.get('start_date'), default=assignment.start_date)
            end_date = _safe_date(data.get('end_date'), default=None)
            shift_start = _safe_time(data.get('shift_start'), default=assignment.shift_start)
            shift_end = _safe_time(data.get('shift_end'), default=assignment.shift_end)

            working_days_list = data.getlist('working_days')
            working_days = ",".join(working_days_list) if working_days_list else assignment.working_days

            supervisor_id = _safe_int(data.get('supervisor_id'))
            description = data.get('description', '').strip()

            # Hierarchy validation
            is_valid_loc, loc_err = DutyConflictService.validate_location_hierarchy(
                building_id=building_id, block=block, floor=floor, room_id=room_id
            )
            if not is_valid_loc:
                messages.error(request, f"Location Error: {loc_err}")
                return redirect('duty_list')

            assignment.building_id = building_id
            assignment.block = block
            assignment.floor = floor
            assignment.room_id = room_id
            assignment.specific_location = specific_location
            assignment.start_date = start_date
            assignment.end_date = end_date
            assignment.shift_start = shift_start
            assignment.shift_end = shift_end
            assignment.working_days = working_days
            assignment.supervisor_id = supervisor_id
            assignment.description = description
            assignment.save()

            client_ip = _get_client_ip(request)
            try:
                DutyApprovalLog.objects.create(
                    assignment=assignment,
                    action='CREATED',
                    performed_by=request.user,
                    notes="Duty assignment details updated.",
                    ip_address=client_ip
                )
            except Exception as log_ex:
                logger.warning("DutyApprovalLog note: %s", log_ex)

            messages.success(request, f"Duty assignment for '{assignment.staff.name}' updated successfully.")
        except Exception as e:
            logger.exception("Error updating duty assignment: %s", e)
            messages.error(request, f"Error updating duty: {e}")

    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'delete')
def duty_delete(request, pk):
    """Deletes an assignment record."""
    assignment = get_object_or_404(DutyAssignment, pk=pk)
    if request.method == 'POST':
        staff_name = assignment.staff.name
        title = assignment.duty_title
        assignment.delete()
        messages.success(request, f"Duty assignment '{title}' for '{staff_name}' deleted.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'approve')
def duty_approve(request, pk):
    """Approves a pending duty assignment. Enforces self-approval block."""
    if request.method == 'POST':
        assignment = get_object_or_404(DutyAssignment, pk=pk)
        notes = request.POST.get('notes', '')
        try:
            DutyWorkflowService.approve_assignment(
                assignment=assignment,
                approved_by_user=request.user,
                notes=notes,
                ip_address=_get_client_ip(request)
            )
            messages.success(request, f"Duty assignment '{assignment.duty_title}' approved successfully.")
        except PermissionDenied as pe:
            messages.error(request, str(pe))
        except Exception as e:
            messages.error(request, f"Approval error: {e}")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'reject')
def duty_reject(request, pk):
    """Rejects a duty assignment with mandatory reason."""
    if request.method == 'POST':
        assignment = get_object_or_404(DutyAssignment, pk=pk)
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, "A mandatory reason is required to reject a duty assignment.")
            return redirect('duty_list')
        try:
            DutyWorkflowService.reject_assignment(
                assignment=assignment,
                rejected_by_user=request.user,
                reason=reason,
                ip_address=_get_client_ip(request)
            )
            messages.info(request, f"Duty assignment '{assignment.duty_title}' was rejected.")
        except Exception as e:
            messages.error(request, f"Rejection error: {e}")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'assign')
def duty_handover(request, pk):
    """Emergency handover of an active duty assignment to a qualified replacement staff member."""
    if request.method == 'POST':
        assignment = get_object_or_404(DutyAssignment, pk=pk)
        substitute_id = request.POST.get('substitute_staff_id')
        reason = request.POST.get('reason', '').strip()

        if not substitute_id:
            messages.error(request, "Please select a replacement staff member.")
            return redirect('duty_list')

        substitute_staff = get_object_or_404(StaffProfile, pk=substitute_id)
        try:
            DutyWorkflowService.handover_duty(
                assignment=assignment,
                substitute_staff=substitute_staff,
                performed_by_user=request.user,
                reason=reason,
                ip_address=_get_client_ip(request)
            )
            messages.success(request, f"Duty '{assignment.duty_title}' successfully handed over to '{substitute_staff.name}'.")
        except Exception as e:
            messages.error(request, f"Handover error: {e}")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'edit')
def duty_revoke(request, pk):
    """Immediate killswitch: revokes active duty assignment and cuts access."""
    if request.method == 'POST':
        assignment = get_object_or_404(DutyAssignment, pk=pk)
        reason = request.POST.get('reason', 'Immediate revocation by supervisor/admin').strip()
        try:
            DutyWorkflowService.revoke_duty(
                assignment=assignment,
                revoked_by_user=request.user,
                reason=reason,
                ip_address=_get_client_ip(request)
            )
            messages.warning(request, f"Duty '{assignment.duty_title}' was revoked immediately.")
        except Exception as e:
            messages.error(request, f"Revocation error: {e}")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'add')
def duty_create(request):
    """Creates a new RBDAC Duty Template with 10 actions and data scope."""
    if request.method == 'POST':
        data = request.POST
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        category = data.get('category', 'Custom Duty').strip()
        priority = data.get('priority', 'medium')
        data_scope = data.get('data_scope', 'BUILDING')
        requires_approval = data.get('requires_approval') == 'on'
        working_days_list = data.getlist('working_days')
        working_days = ",".join(working_days_list) if working_days_list else 'MON,TUE,WED,THU,FRI,SAT,SUN'
        ceiling_role_id = _safe_int(data.get('privilege_ceiling_role'))

        start_date = data.get('start_date') or None
        end_date = data.get('end_date') or None
        start_time = data.get('start_time') or None
        end_time = data.get('end_time') or None
        repeat_type = data.get('repeat_type', 'none')

        duty = Duty.objects.create(
            name=name,
            description=description,
            category=category,
            priority=priority,
            data_scope=data_scope,
            requires_approval=requires_approval,
            working_days=working_days,
            privilege_ceiling_role_id=ceiling_role_id,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            repeat_type=repeat_type,
            status='active',
            created_by=request.user
        )

        # 10 Actions across supported HMS modules
        modules = ['student', 'room', 'leave', 'attendance', 'complaint', 'fee', 'visitor', 'duty_management']
        actions = ['view', 'add', 'edit', 'delete', 'approve', 'reject', 'verify', 'export', 'print', 'download', 'assign']

        for mod in modules:
            kwargs = {}
            for act in actions:
                kwargs[f'can_{act}'] = (data.get(f'perm_{mod}_{act}') == 'on')
            if any(kwargs.values()):
                DutyPermission.objects.create(duty=duty, module_name=mod, **kwargs)

        messages.success(request, f"Duty Template '{name}' created with 10-action RBDAC policies.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'edit')
def duty_edit_definition(request, pk):
    """Updates an existing RBDAC Duty Template."""
    duty = get_object_or_404(Duty, pk=pk)
    if request.method == 'POST':
        data = request.POST
        duty.name = data.get('name', '').strip()
        duty.description = data.get('description', '').strip()
        duty.category = data.get('category', 'Custom Duty').strip()
        duty.priority = data.get('priority', 'medium')
        duty.data_scope = data.get('data_scope', 'BUILDING')
        duty.requires_approval = data.get('requires_approval') == 'on'
        working_days_list = data.getlist('working_days')
        if working_days_list:
            duty.working_days = ",".join(working_days_list)
        duty.privilege_ceiling_role_id = _safe_int(data.get('privilege_ceiling_role'))

        duty.start_date = data.get('start_date') or None
        duty.end_date = data.get('end_date') or None
        duty.start_time = data.get('start_time') or None
        duty.end_time = data.get('end_time') or None
        duty.repeat_type = data.get('repeat_type', 'none')
        duty.status = data.get('status', 'active')
        duty.save()

        # Reset & Re-save permissions
        duty.permissions.all().delete()
        modules = ['student', 'room', 'leave', 'attendance', 'complaint', 'fee', 'visitor', 'duty_management']
        actions = ['view', 'add', 'edit', 'delete', 'approve', 'reject', 'verify', 'export', 'print', 'download', 'assign']

        for mod in modules:
            kwargs = {}
            for act in actions:
                kwargs[f'can_{act}'] = (data.get(f'perm_{mod}_{act}') == 'on')
            if any(kwargs.values()):
                DutyPermission.objects.create(duty=duty, module_name=mod, **kwargs)

        messages.success(request, f"Duty Template '{duty.name}' updated successfully.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'delete')
def duty_delete_definition(request, pk):
    """Deletes a duty template."""
    duty = get_object_or_404(Duty, pk=pk)
    if request.method == 'POST':
        name = duty.name
        duty.delete()
        messages.success(request, f"Duty Template '{name}' deleted.")
    return redirect('duty_list')


# ──────────────────────────────────────────────────────
# AJAX HIERARCHY & CONFLICT DETECTION ENDPOINTS
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
@api_permission_required('duty_management', 'view')
def get_floors_for_building(request):
    """Returns total floors and comma-separated blocks for the selected building."""
    building_id = _safe_int(request.GET.get('building_id'))
    if not building_id:
        return JsonResponse({'floors': [], 'blocks': []})

    building = HostelBuilding.objects.filter(pk=building_id).first()
    if not building:
        return JsonResponse({'floors': [], 'blocks': []})

    floors = [{'id': i, 'floor_number': i} for i in range(1, (building.total_floors or 1) + 1)]
    blocks = [b.strip() for b in (building.blocks or '').split(',') if b.strip()]
    return JsonResponse({'floors': floors, 'blocks': blocks})


@login_required(login_url='/authentication/login')
@api_permission_required('duty_management', 'view')
def get_rooms_for_building_floor(request):
    """Returns rooms matching building, floor, and optional block."""
    building_id = _safe_int(request.GET.get('building_id'))
    floor = _safe_int(request.GET.get('floor'))
    block = request.GET.get('block', '').strip()

    if not building_id:
        return JsonResponse({'rooms': []})

    qs = Room.objects.filter(building_id=building_id)
    if floor is not None:
        qs = qs.filter(floor=floor)
    if block:
        qs = qs.filter(block__iexact=block)

    rooms = [{'id': r.id, 'room_number': r.room_number, 'category': r.get_category_display()} for r in qs.order_by('room_number')]
    return JsonResponse({'rooms': rooms})


@login_required(login_url='/authentication/login')
@api_permission_required('duty_management', 'view')
def check_duty_conflict_ajax(request):
    """Real-time conflict detection AJAX endpoint for Assign/Edit modals."""
    staff_id = _safe_int(request.GET.get('staff_id'))
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date') or None
    shift_start_str = request.GET.get('shift_start') or None
    shift_end_str = request.GET.get('shift_end') or None
    working_days = request.GET.get('working_days', 'MON,TUE,WED,THU,FRI,SAT,SUN')
    exclude_id = _safe_int(request.GET.get('exclude_id'))

    if not staff_id or not start_date:
        return JsonResponse({'conflict': False, 'reason': '', 'on_leave': False, 'leave_reason': ''})

    s_time = _safe_time(shift_start_str)
    e_time = _safe_time(shift_end_str)

    has_conflict, _, reason = DutyConflictService.detect_conflict(
        staff_id=staff_id,
        start_date=start_date,
        end_date=end_date,
        shift_start=s_time,
        shift_end=e_time,
        working_days=working_days,
        exclude_id=exclude_id
    )

    on_leave, leave_reason = DutyConflictService.check_staff_leave_conflict(staff_id, start_date, end_date)

    return JsonResponse({
        'conflict': has_conflict,
        'conflict_reason': reason,
        'on_leave': on_leave,
        'leave_reason': leave_reason,
    })


# ──────────────────────────────────────────────────────
# DYNAMIC ROLE-BASED & DUTY-BASED DASHBOARD
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def dynamic_dashboard(request):
    """
    Enterprise Dynamic Dashboard for all non-Super Admin roles.
    Dynamically renders widgets, KPIs, tasks, shift timetable, and quick actions
    based on System Role permissions, Duty Assignments, and location scoping.
    Super Admin dashboard is completely preserved without interference.
    """
    user = request.user
    profile = getattr(user, 'profile', None)
    role = profile.role if profile else None

    # Preserve Super Admin: redirect Super Admin to superadmin_dashboard
    if user.is_superuser or (role and role.is_superadmin) or (role and role.name == 'Admin'):
        return redirect('superadmin_dashboard')

    # Preserve Student: redirect to student_dashboard
    if (role and role.name == 'Student') or hasattr(user, 'student'):
        return redirect('student_app:student_dashboard')

    # Handle POST actions (e.g. Duty Handover from dashboard modal)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'duty_handover':
            assignment_id = _safe_int(request.POST.get('assignment_id'))
            substitute_id = _safe_int(request.POST.get('substitute_id'))
            reason = request.POST.get('reason', '').strip()
            if assignment_id and substitute_id:
                assignment = DutyAssignment.objects.filter(id=assignment_id).first()
                substitute = StaffProfile.objects.filter(id=substitute_id, status='active').first()
                if assignment and substitute:
                    from .duty_services import DutyWorkflowService
                    ok, msg = DutyWorkflowService.process_handover(
                        assignment=assignment,
                        substitute_staff=substitute,
                        actor_user=user,
                        reason=reason
                    )
                    if ok:
                        messages.success(request, f"Duty successfully handed over to {substitute.name}.")
                    else:
                        messages.error(request, f"Handover failed: {msg}")
                else:
                    messages.error(request, "Invalid assignment or substitute staff selected.")
            return redirect('dynamic_dashboard')

    # Build user context with effective permissions, duties, and location boundaries
    ctx = DynamicDashboardService.build_user_dashboard_context(user)
    kpis = DynamicDashboardService.get_scoped_kpis(ctx)
    tasks = DynamicDashboardService.get_actionable_tasks(ctx)
    shift_schedule = DynamicDashboardService.get_shift_schedule(ctx)
    quick_actions = DynamicDashboardService.get_quick_actions(ctx)
    location_overview = DynamicDashboardService.get_location_overview(ctx)
    operational_alerts = DynamicDashboardService.get_operational_alerts(ctx)
    recent_activities = DynamicDashboardService.get_recent_activities(ctx)
    enabled_widgets = DynamicDashboardService.get_widget_preferences(user, ctx.role)
    all_widgets = DynamicDashboardService.ALL_WIDGETS

    # Substitutes for Handover modal
    substitutes = StaffProfile.objects.filter(status='active').exclude(user=user).select_related('user')
    if ctx.scoped_hostel_id:
        substitutes = substitutes.filter(hostel_id=ctx.scoped_hostel_id)

    context = {
        'page_title': f"{ctx.role_name} Dashboard",
        'ctx': ctx,
        'kpis': kpis,
        'tasks': tasks,
        'shift_schedule': shift_schedule,
        'quick_actions': quick_actions,
        'location_overview': location_overview,
        'operational_alerts': operational_alerts,
        'recent_activities': recent_activities,
        'enabled_widgets': enabled_widgets,
        'all_widgets': all_widgets,
        'substitutes': substitutes,
        'can_approve_leave': ctx.can('leave', 'approve'),
    }
    return render(request, 'hms/dynamic_dashboard.html', context)


@login_required(login_url='/authentication/login')
def dashboard_live_kpis(request):
    """AJAX endpoint for real-time periodic KPI refresh."""
    ctx = DynamicDashboardService.build_user_dashboard_context(request.user)
    kpis = DynamicDashboardService.get_scoped_kpis(ctx)
    return JsonResponse({'status': 'success', 'kpis': kpis})


@login_required(login_url='/authentication/login')
def dashboard_save_widgets(request):
    """Saves user customization for enabled dashboard widgets."""
    if request.method == 'POST':
        widgets = request.POST.getlist('widgets')
        if not widgets:
            try:
                data = json.loads(request.body.decode('utf-8'))
                widgets = data.get('widgets', [])
            except Exception:
                pass
        DynamicDashboardService.save_widget_preferences(request.user, widgets)
        messages.success(request, "Dashboard widget preferences updated successfully.")
    return redirect('dynamic_dashboard')


@login_required(login_url='/authentication/login')
def dashboard_quick_approve_leave(request, leave_id):
    """1-click leave approval from dashboard actionable queue."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

    ctx = DynamicDashboardService.build_user_dashboard_context(request.user)
    if not ctx.can('leave', 'approve'):
        return JsonResponse({'status': 'error', 'message': 'Forbidden: missing leave approve permission'}, status=403)

    leave = get_object_or_404(HostelLeave, pk=leave_id)
    if ctx.scoped_building_ids:
        bed = Bed.objects.filter(student=leave.student).select_related('room__building').first()
        if bed and bed.room.building_id not in ctx.scoped_building_ids:
            return JsonResponse({'status': 'error', 'message': 'Unauthorized: student is outside your assigned building scope'}, status=403)

    leave.status = 'approved'
    leave.approved_by = request.user
    leave.approved_at = timezone.now()
    leave.save()

    AuditLog.objects.create(
        actor=request.user,
        target_user=getattr(leave.student, 'user', None),
        action='gate_pass',
        details=f"Quick approved leave #{leave.id} for {leave.student.name} via Dynamic Dashboard"
    )

    return JsonResponse({'status': 'success', 'message': f'Leave for {leave.student.name} approved successfully.'})


@login_required(login_url='/authentication/login')
def dashboard_quick_verify_exit(request, leave_id):
    """1-click gate exit verification from dashboard actionable queue."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

    ctx = DynamicDashboardService.build_user_dashboard_context(request.user)
    if not ctx.can('leave', 'verify'):
        return JsonResponse({'status': 'error', 'message': 'Forbidden: missing leave verify permission'}, status=403)

    leave = get_object_or_404(HostelLeave, pk=leave_id)
    leave.exit_verified = True
    leave.exit_verified_by = request.user
    leave.exit_time = timezone.now()
    leave.save()

    AuditLog.objects.create(
        actor=request.user,
        target_user=getattr(leave.student, 'user', None),
        action='gate_pass',
        details=f"Quick verified gate exit for {leave.student.name} via Dynamic Dashboard"
    )

    return JsonResponse({'status': 'success', 'message': f'Gate exit verified for {leave.student.name}.'})
