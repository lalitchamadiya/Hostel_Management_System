import shutil
import csv
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.contrib import messages

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
    DutyAssignment, Duty, DutyPermission
)
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
    role_name = None
    try:
        role_name = user.profile.role.name
    except Exception:
        pass

    if role_name == 'Student':
        return redirect('student_app:student_dashboard')
    if role_name == 'Warden':
        return redirect('warden_dashboard')
    if role_name == 'Admin':
        return redirect('superadmin_dashboard')
    if role_name in ('Security Guard', 'Security'):
        return redirect('security_dashboard')
    return redirect('superadmin_dashboard')


# ──────────────────────────────────────────────────────
# SUPER ADMIN DASHBOARD
# ──────────────────────────────────────────────────────
@login_required(login_url='/authentication/login')
def superadmin_dashboard(request):
    if not _is_admin(request.user):
        try:
            r_name = request.user.profile.role.name
        except Exception:
            r_name = None
        if r_name == 'Warden':
            return redirect('warden_dashboard')
        elif r_name in ('Security Guard', 'Security'):
            return redirect('security_dashboard')
        elif r_name == 'Student' or hasattr(request.user, 'student'):
            return redirect('student_app:student_dashboard')
        return redirect('student_app:student_dashboard')

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

    # Auto-sync users with staff-related roles into StaffProfile
    try:
        staff_users = User.objects.filter(
            profile__role__isnull=False
        ).exclude(
            profile__role__name__iexact='Student'
        ).select_related('profile', 'profile__role')
        for u in staff_users:
            sync_user_to_staff(u)
    except Exception as sync_err:
        import logging
        logging.getLogger(__name__).warning("Staff auto-sync exception: %s", sync_err)

    qs = StaffProfile.objects.select_related('user', 'user__profile').order_by('-id')

    # ── Filters ──
    search = request.GET.get('q', '').strip()
    designation_filter = request.GET.get('designation', '')
    status_filter = request.GET.get('status', '')
    shift_filter = request.GET.get('shift', '')
    performance_filter = request.GET.get('performance', '')

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(designation__icontains=search)
        )
    if designation_filter:
        qs = qs.filter(designation=designation_filter)
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
    stats = {
        'total': StaffProfile.objects.count(),
        'active': StaffProfile.objects.filter(status='active').count(),
        'inactive': StaffProfile.objects.filter(status='inactive').count(),
        'on_leave': StaffProfile.objects.filter(status='on_leave').count(),
        'new_this_week': StaffProfile.objects.filter(doj__gte=seven_days_ago).count(),
        'designations': StaffProfile.objects.values('designation').distinct().count(),
    }

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'search': search,
        'designation_filter': designation_filter,
        'status_filter': status_filter,
        'shift_filter': shift_filter,
        'performance_filter': performance_filter,
        'designations': StaffProfile.DESIGNATION_CHOICES,
        'shifts': StaffProfile.SHIFT_CHOICES,
        'statuses': StaffProfile.STATUS_CHOICES,
        'performances': StaffProfile.PERFORMANCE_CHOICES,
        'page_title': 'Staff Management',
    }
    return render(request, 'hms/staff_list.html', context)


@login_required(login_url='/authentication/login')
def staff_create(request):
    if not _is_admin(request.user):
        return redirect('dashboard')
    
    roles = Role.objects.filter(is_active=True)
    
    if request.method == 'POST':
        data = request.POST
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        designation = data.get('designation', '')
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
        role_id = data.get('role')

        # Check if Admin designation or Admin system role
        is_admin_role = False
        if role_id:
            role_obj = Role.objects.filter(id=role_id).first()
            if role_obj and 'admin' in role_obj.name.lower():
                is_admin_role = True

        errors = []
        if designation == 'admin' or is_admin_role:
            salary = 0.00
            shift = 'morning'
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
            
        if username:
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
                'page_title': 'Add Staff Member',
                'designations': StaffProfile.DESIGNATION_CHOICES,
                'shifts': StaffProfile.SHIFT_CHOICES,
                'statuses': StaffProfile.STATUS_CHOICES,
                'performances': StaffProfile.PERFORMANCE_CHOICES,
                'roles': roles,
                'form_data': data
            })
            
        try:
            user = None
            if username:
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
                designation=designation,
                salary=salary,
                shift=shift,
                status=status,
                performance=performance,
                doj=doj,
                documents=documents,
            )
            messages.success(request, 'Staff member added successfully.')
            return redirect('staff_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('staff_list')

    return render(request, 'hms/staff_form.html', {
        'page_title': 'Add Staff Member',
        'designations': StaffProfile.DESIGNATION_CHOICES,
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
    roles = Role.objects.filter(is_active=True)
    
    if request.method == 'POST':
        data = request.POST
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        designation = data.get('designation', staff.designation)
        salary = data.get('salary', 0) or 0
        shift = data.get('shift', 'morning')
        status = data.get('status', 'active')
        performance = data.get('performance', 'good')
        documents = data.get('documents', '')

        # User credentials params
        username = data.get('username', '').strip()
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')
        role_id = data.get('role')

        # Check if Admin designation or Admin system role
        is_admin_role = False
        if role_id:
            role_obj = Role.objects.filter(id=role_id).first()
            if role_obj and 'admin' in role_obj.name.lower():
                is_admin_role = True

        errors = []
        if designation == 'admin' or is_admin_role:
            salary = 0.00
            shift = 'morning'
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
                'designations': StaffProfile.DESIGNATION_CHOICES,
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
                if role_id:
                    try:
                        role_obj = Role.objects.get(id=role_id)
                        if profile.role and profile.role != role_obj:
                            old_group = Group.objects.filter(name=profile.role.name).first()
                            if old_group:
                                old_group.user_set.remove(user)
                        profile.role = role_obj
                        group, _ = Group.objects.get_or_create(name=role_obj.name)
                        group.user_set.add(user)
                    except Role.DoesNotExist:
                        pass
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
            staff.designation = designation
            staff.salary = salary
            staff.shift = shift
            staff.status = status
            staff.performance = performance
            staff.documents = documents
            staff.save()
            messages.success(request, 'Staff member updated.')
            return redirect('staff_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('staff_list')

    return render(request, 'hms/staff_form.html', {
        'page_title': 'Edit Staff Member',
        'staff': staff,
        'designations': StaffProfile.DESIGNATION_CHOICES,
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
# STAFF DUTY ASSIGNMENT MODULE
# ──────────────────────────────────────────────────────
from authentication.decorators import permission_required, api_permission_required

@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'view')
def duty_list(request):
    assignments = DutyAssignment.objects.select_related('staff', 'duty').filter(is_active=True).order_by('-assigned_date')
    staff_members = StaffProfile.objects.filter(status='active').order_by('name')
    duties = Duty.objects.prefetch_related('permissions').all().order_by('name')
    
    context = {
        'page_title': 'Staff Duty Assignments',
        'assignments': assignments,
        'staff_members': staff_members,
        'duties': duties,
    }
    return render(request, 'hms/duty_list.html', context)


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'add')
def duty_assign(request):
    if request.method == 'POST':
        data = request.POST
        staff_id = data.get('staff_id')
        duty_id = data.get('duty_id')
        duty_title = data.get('duty_title', '').strip()
        specific_location = data.get('specific_location', '').strip()
        shift_start = data.get('shift_start') or None
        shift_end = data.get('shift_end') or None
        description = data.get('description', '').strip()
        
        staff = get_object_or_404(StaffProfile, pk=staff_id)
        
        duty = None
        if duty_id:
            duty = Duty.objects.filter(pk=duty_id).first()
            if duty and not duty_title:
                duty_title = duty.name
            if duty:
                if not shift_start and duty.start_time:
                    shift_start = duty.start_time
                if not shift_end and duty.end_time:
                    shift_end = duty.end_time
        
        DutyAssignment.objects.create(
            duty=duty,
            staff=staff,
            duty_title=duty_title,
            specific_location=specific_location,
            shift_start=shift_start,
            shift_end=shift_end,
            description=description
        )
        messages.success(request, f'Duty assigned to {staff.name} successfully.')
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'edit')
def duty_edit(request, pk):
    assignment = get_object_or_404(DutyAssignment, pk=pk)
    if request.method == 'POST':
        data = request.POST
        staff_id = data.get('staff_id')
        duty_id = data.get('duty_id')
        duty_title = data.get('duty_title', '').strip()
        specific_location = data.get('specific_location', '').strip()
        shift_start = data.get('shift_start') or None
        shift_end = data.get('shift_end') or None
        description = data.get('description', '').strip()
        
        staff = get_object_or_404(StaffProfile, pk=staff_id)
        
        duty = None
        if duty_id:
            duty = Duty.objects.filter(pk=duty_id).first()
            if duty and not duty_title:
                duty_title = duty.name
        
        assignment.duty = duty
        assignment.staff = staff
        assignment.duty_title = duty_title
        assignment.specific_location = specific_location
        assignment.shift_start = shift_start
        assignment.shift_end = shift_end
        assignment.description = description
        assignment.save()
        messages.success(request, f"Duty assignment for {staff.name} updated.")
    return redirect('duty_list')



@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'delete')
def duty_delete(request, pk):
    assignment = get_object_or_404(DutyAssignment, pk=pk)
    if request.method == 'POST':
        assignment.delete()
        messages.success(request, 'Duty assignment deleted.')
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'add')
def duty_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', 'Custom Duty').strip()
        priority = request.POST.get('priority', 'medium')
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        start_time = request.POST.get('start_time') or None
        end_time = request.POST.get('end_time') or None
        repeat_type = request.POST.get('repeat_type', 'none')
        
        duty = Duty.objects.create(
            name=name,
            description=description,
            category=category,
            priority=priority,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            repeat_type=repeat_type,
            status='active',
            created_by=request.user
        )
        
        # Save permissions for each module
        modules = ['leave', 'students', 'attendance']
        for mod in modules:
            can_view = request.POST.get(f'perm_{mod}_view') == 'on'
            can_add = request.POST.get(f'perm_{mod}_add') == 'on'
            can_edit = request.POST.get(f'perm_{mod}_edit') == 'on'
            can_delete = request.POST.get(f'perm_{mod}_delete') == 'on'
            
            # If any permission is granted, save it
            if can_view or can_add or can_edit or can_delete:
                DutyPermission.objects.create(
                    duty=duty,
                    module_name=mod,
                    can_view=can_view,
                    can_add=can_add,
                    can_edit=can_edit,
                    can_delete=can_delete
                )
        
        messages.success(request, f"Duty '{name}' created successfully.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'edit')
def duty_edit_definition(request, pk):
    duty = get_object_or_404(Duty, pk=pk)
    if request.method == 'POST':
        duty.name = request.POST.get('name', '').strip()
        duty.description = request.POST.get('description', '').strip()
        duty.category = request.POST.get('category', 'Custom Duty').strip()
        duty.priority = request.POST.get('priority', 'medium')
        duty.start_date = request.POST.get('start_date') or None
        duty.end_date = request.POST.get('end_date') or None
        duty.start_time = request.POST.get('start_time') or None
        duty.end_time = request.POST.get('end_time') or None
        duty.repeat_type = request.POST.get('repeat_type', 'none')
        duty.status = request.POST.get('status', 'active')
        duty.save()
        
        # Reset permissions
        duty.permissions.all().delete()
        modules = ['leave', 'students', 'attendance']
        for mod in modules:
            can_view = request.POST.get(f'perm_{mod}_view') == 'on'
            can_add = request.POST.get(f'perm_{mod}_add') == 'on'
            can_edit = request.POST.get(f'perm_{mod}_edit') == 'on'
            can_delete = request.POST.get(f'perm_{mod}_delete') == 'on'
            
            if can_view or can_add or can_edit or can_delete:
                DutyPermission.objects.create(
                    duty=duty,
                    module_name=mod,
                    can_view=can_view,
                    can_add=can_add,
                    can_edit=can_edit,
                    can_delete=can_delete
                )
        messages.success(request, f"Duty definition '{duty.name}' updated.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@permission_required('duty_management', 'delete')
def duty_delete_definition(request, pk):
    duty = get_object_or_404(Duty, pk=pk)
    if request.method == 'POST':
        duty.delete()
        messages.success(request, "Duty definition deleted.")
    return redirect('duty_list')


@login_required(login_url='/authentication/login')
@api_permission_required('duty_management', 'view')
def get_floors_for_building(request):
    return JsonResponse({'floors': []})





