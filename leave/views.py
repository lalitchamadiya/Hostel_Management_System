from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from authentication.decorators import role_required, permission_required
from django.core.exceptions import PermissionDenied
from datetime import datetime, date, timedelta, time
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import transaction, models
from .models import HostelLeave, GatePass, QRPass
from student.models import Student, Attendance
from authentication.models import Notification, AuditLog
import uuid

def generate_gate_pass_no():
    return f"GP-{uuid.uuid4().hex[:8].upper()}"

@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def leave_base(request):
    return redirect('pending_leave')

@login_required(login_url='/authentication/login')
@permission_required('leave', 'edit')
def edit_leave(request, leave_id):
    leave = get_object_or_404(HostelLeave, id=leave_id)
    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        if leave.student.user != request.user:
            raise PermissionDenied
            
    student = leave.student
    if request.method == 'POST':
        leave.reason = request.POST.get('reason')
        from_str = request.POST.get('leave_date')
        to_str = request.POST.get('return_date')
        parsed_from = parse_date(from_str) if from_str else None
        parsed_to = parse_date(to_str) if to_str else None
        if parsed_from:
            leave.leave_from = parsed_from
        if parsed_to:
            leave.leave_to = parsed_to
        leave.start_time = request.POST.get('start_time')
        leave.end_time = request.POST.get('end_time')
        leave.destination = request.POST.get('destination')
        leave.transport_mode = request.POST.get('transport_mode')
        leave.remarks = request.POST.get('remarks')
        try:
            leave.save()
            messages.success(request, 'Leave request updated successfully.')
            return redirect('leave_record')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    context = {'leave': leave, 'student_details': student}
    return render(request, 'leave/edit_leave.html', context)

def process_leave_action(request, leave, action):
    if action == 'approve':
        with transaction.atomic():
            leave.status = 'approved'
            leave.approved_by = request.user
            leave.approval_date = timezone.now()
            
            # Ensure date objects
            l_from = leave.leave_from
            if isinstance(l_from, str):
                l_from = parse_date(l_from)
                leave.leave_from = l_from
            l_to = leave.leave_to
            if isinstance(l_to, str):
                l_to = parse_date(l_to)
                leave.leave_to = l_to

            # Calculate total days
            if l_to and l_from:
                leave.total_days = max((l_to - l_from).days, 1)
            leave.save()

            # Generate Gate Pass
            gp_no = generate_gate_pass_no()
            GatePass.objects.create(gate_pass_no=gp_no, leave_request=leave)

            # Generate EXIT QRPass (Expires at the end of leave_from date)
            valid_from_date = l_from or timezone.now().date()
            expires_at = timezone.make_aware(datetime.combine(valid_from_date, time(23, 59, 59)))
            QRPass.objects.create(
                leave=leave,
                pass_type='EXIT',
                expires_at=expires_at
            )

            student = leave.student

            # Mark Attendance as 'On Leave' for the dates
            current_date = l_from or timezone.now().date()
            end_date = l_to or current_date
            while current_date <= end_date:
                Attendance.objects.update_or_create(
                    student=student,
                    date=current_date,
                    defaults={'status': 'On Leave', 'marked_by': request.user}
                )
                current_date += timedelta(days=1)

            # Create Notification
            Notification.objects.create(
                user=student.user,
                message=f"Your leave request for {leave.leave_from} has been approved. Gate Pass {gp_no} and Exit QR Code generated."
            )

            # Log to AuditLog
            AuditLog.objects.create(
                actor=request.user,
                target_user=student.user,
                action='gate_pass',
                details=f"Approved leave and generated Gate Pass {gp_no} and EXIT QR for student {student.name}",
                ip_address=request.META.get('REMOTE_ADDR')
            )

    elif action == 'reject':
        leave.status = 'rejected'
        leave.save()
        Notification.objects.create(
            user=leave.student.user,
            message=f"Your leave request for {leave.leave_from} has been rejected."
        )

    elif action == 'entered':
        # Legacy/direct entry mark support (also handles completed state)
        with transaction.atomic():
            leave.status = 'completed'
            leave.entry_time = timezone.now()
            leave.entry_verified = True
            leave.save()
            
            # Restore Student Status
            student = leave.student
            student.status = 'Active'
            student.save()
            
            # Log return
            AuditLog.objects.create(
                actor=request.user,
                target_user=student.user,
                action='edit',
                details=f"Student {student.name} marked as returned from leave.",
                ip_address=request.META.get('REMOTE_ADDR')
            )


@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def leave_record(request):
    if request.method == 'POST':
        # Action requires approve/reject permission
        action = request.POST.get('action')
        # Check permissions safely (Superusers and active super-admins always bypass)
        is_authorized = False
        if request.user.is_superuser:
            is_authorized = True
        elif hasattr(request.user, 'profile') and request.user.profile.role:
            role = request.user.profile.role
            if role.is_superadmin:
                is_authorized = True
            else:
                perm = role.permissions.filter(module__code='leave').first()
                if perm:
                    if action == 'approve' and getattr(perm, 'can_approve', False):
                        is_authorized = True
                    elif action == 'reject' and getattr(perm, 'can_reject', False):
                        is_authorized = True

        if not is_authorized:
            raise PermissionDenied

        leave_id = request.POST.get('leave_id')
        try:
            leave = HostelLeave.objects.get(id=leave_id)
            process_leave_action(request, leave, action)
            messages.success(request, f"Status updated to {leave.status}.")
        except HostelLeave.DoesNotExist:
            messages.error(request, "Leave request not found.")

    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        leave_requests = HostelLeave.objects.filter(student__user=request.user, status__in=['rejected', 'entered', 'completed'])
    else:
        leave_requests = HostelLeave.objects.filter(status__in=['rejected', 'entered', 'completed'])
    return render(request, 'leave/leave_record.html', {'leave_requests': leave_requests})

@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def pending_leave(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        # Check permissions safely (Superusers and active super-admins always bypass)
        is_authorized = False
        if request.user.is_superuser:
            is_authorized = True
        elif hasattr(request.user, 'profile') and request.user.profile.role:
            role = request.user.profile.role
            if role.is_superadmin:
                is_authorized = True
            else:
                perm = role.permissions.filter(module__code='leave').first()
                if perm:
                    if action == 'approve' and getattr(perm, 'can_approve', False):
                        is_authorized = True
                    elif action == 'reject' and getattr(perm, 'can_reject', False):
                        is_authorized = True

        if not is_authorized:
            raise PermissionDenied

        leave_id = request.POST.get('leave_id')
        try:
            leave = HostelLeave.objects.get(id=leave_id)
            process_leave_action(request, leave, action)
            messages.success(request, "Status updated.")
        except HostelLeave.DoesNotExist:
            messages.error(request, "Not found.")
        return redirect('pending_leave')

    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        pending_leave_requests = HostelLeave.objects.filter(student__user=request.user, status__in=['pending', 'approved'])
    else:
        pending_leave_requests = HostelLeave.objects.filter(status__in=['pending', 'approved'])
    return render(request, 'leave/pending_leave.html', {'pending_leave_requests': pending_leave_requests})

@login_required(login_url='/authentication/login')
@permission_required('leave', 'add')
def add_leave(request):
    if request.method == 'POST':
        enrollment_number = request.POST.get('enrollment_number')
        reason = request.POST.get('reason')
        leave_date_str = request.POST.get('leave_date')
        return_date_str = request.POST.get('return_date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        destination = request.POST.get('destination')
        transport_mode = request.POST.get('transport_mode')
        remarks = request.POST.get('remarks')

        try:
            student = Student.objects.get(roll=enrollment_number)
            # Isolation check for Student role
            if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
                if student.user != request.user:
                    raise PermissionDenied("You can only add leave for yourself.")

            if HostelLeave.objects.filter(student=student).exclude(status__in=['entered', 'completed', 'rejected']).exists():
                messages.error(request, 'Active or pending request already exists.')
                return redirect('add_leave') 

            leave_from = datetime.strptime(leave_date_str, '%Y-%m-%d').date()
            leave_to = datetime.strptime(return_date_str, '%Y-%m-%d').date() if return_date_str else None
            
            HostelLeave.objects.create(
                student=student, 
                leave_from=leave_from, 
                leave_to=leave_to,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                destination=destination,
                transport_mode=transport_mode,
                remarks=remarks
            )
            messages.success(request, 'Submitted successfully.')
            return redirect('pending_leave') 
        except Student.DoesNotExist:
            messages.error(request, 'Enrollment number does not exist.')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'leave/add_leave.html')

@login_required(login_url='/authentication/login')
@permission_required('leave', 'add')
def check_enrollment(request):
    student_details = None
    error_message = None
    if request.method == 'POST':
        enrollment_number = request.POST.get('enrollment_number')
        try:
            student_details = Student.objects.get(roll=enrollment_number)
            if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
                if student_details.user != request.user:
                     raise PermissionDenied
        except Student.DoesNotExist:
            error_message = "Student Record not found."

    return render(request, 'leave/add_leave.html', {
        'student_details': student_details,
        'error_message': error_message,
    })

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.loader import render_to_string
try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def gate_pass_management(request):
    query = request.GET.get('q')
    status = request.GET.get('status')
    date = request.GET.get('date')
    
    gate_passes = GatePass.objects.select_related('leave_request__student').all()
    
    if query:
        gate_passes = gate_passes.filter(
            models.Q(gate_pass_no__icontains=query) |
            models.Q(leave_request__student__name__icontains=query) |
            models.Q(leave_request__student__roll__icontains=query)
        )
    
    if status:
        gate_passes = gate_passes.filter(status=status)
        
    if date:
        gate_passes = gate_passes.filter(leave_request__leave_from=date)
        
    return render(request, 'leave/gate_pass_management.html', {'gate_passes': gate_passes})

@login_required(login_url='/authentication/login')
def download_gate_pass_pdf(request, gp_id):
    if pisa is None:
        return HttpResponse('PDF generation dependency is not installed.', status=500)

    gp = get_object_or_404(GatePass, id=gp_id)
    
    # Security: Students can only download their own
    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        if gp.leave_request.student.user != request.user:
            raise PermissionDenied

    html = render_to_string('leave/gate_pass_pdf.html', {'gp': gp, 'student': gp.leave_request.student})
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="GatePass_{gp.gate_pass_no}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generating PDF', status=500)
    return response

@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def leave_reports(request):
    # Today's students on leave
    today = date.today()
    on_leave_today = Student.objects.filter(status='On Leave')
    returned_today = HostelLeave.objects.filter(leave_to=today, status__in=['entered', 'completed'])
    expected_return = HostelLeave.objects.filter(leave_to=today, status='approved')
    
    context = {
        'on_leave_today': on_leave_today,
        'returned_today': returned_today,
        'expected_return': expected_return,
        'today': today,
    }
    return render(request, 'leave/leave_reports.html', context)

@login_required(login_url='/authentication/login')    
@permission_required('leave', 'delete')
def delete_leave(request, leave_id):
    leave = get_object_or_404(HostelLeave, id=leave_id)
    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        if leave.student.user != request.user:
            raise PermissionDenied
    leave.delete()
    messages.success(request, 'Deleted successfully.')
    return redirect('leave_record')

@login_required(login_url='/authentication/login')    
@permission_required('leave', 'delete')
def cancel_gate_pass(request, gp_id):
    if request.method == 'POST':
        gp = get_object_or_404(GatePass, id=gp_id)
        
        with transaction.atomic():
            gp.status = 'Cancelled'
            gp.save()
            
            # Revert corresponding leave status to rejected
            leave = gp.leave_request
            leave.status = 'rejected'
            leave.save()
            
            # Deactivate all active QR passes for this leave
            leave.qr_passes.filter(is_used=False).update(is_used=True)
            
            # Notify the student
            Notification.objects.create(
                user=leave.student.user,
                message=f"Your Gate Pass {gp.gate_pass_no} has been cancelled by the administration."
            )
            
            # Audit logging
            AuditLog.objects.create(
                actor=request.user,
                target_user=leave.student.user,
                action='delete',
                details=f"Cancelled Gate Pass {gp.gate_pass_no} for student {leave.student.name}",
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
        messages.success(request, f"Gate Pass {gp.gate_pass_no} cancelled successfully.")
    return redirect('gate_pass_management')

# ==================== NEW QR CODE SERVICE & SCAN WORKFLOW ====================

import qrcode
from io import BytesIO

@login_required(login_url='/authentication/login')
def qr_code_image(request, qr_token):
    qr_pass = get_object_or_404(QRPass, qr_token=qr_token)
    
    # JSON payload structure as specified in requirements
    data = {
       "leave_id": qr_pass.leave.id,
       "student_id": qr_pass.leave.student.student_id,
       "type": qr_pass.pass_type,
       "token": str(qr_pass.qr_token)
    }
    
    import json
    from qrcode.image.pil import PilImage
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(json.dumps(data))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white", image_factory=PilImage)
    
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")

@login_required(login_url='/authentication/login')
def security_dashboard(request):
    return redirect('dynamic_dashboard')

@login_required(login_url='/authentication/login')
@permission_required('leave', 'view')
def scan_gate_pass(request, qr_token):
    clean_token = qr_token.strip()
    qr = None
    leave = None

    # 1. Search by GatePass gate_pass_no (e.g. "GP-ABC5616A")
    gate_pass = GatePass.objects.filter(gate_pass_no__iexact=clean_token).first()
    if gate_pass:
        leave = gate_pass.leave_request
        qr = leave.qr_passes.order_by('-generated_at').first()

    # 2. Search by QRPass qr_token (UUID)
    if not qr:
        try:
            val_uuid = uuid.UUID(clean_token)
            qr = QRPass.objects.filter(qr_token=val_uuid).first()
            if qr:
                leave = qr.leave
        except (ValueError, TypeError, AttributeError):
            pass

    # 3. Search by HostelLeave ID (numeric)
    if not qr and clean_token.isdigit():
        leave = HostelLeave.objects.filter(id=int(clean_token)).first()
        if leave:
            qr = leave.qr_passes.order_by('-generated_at').first()

    # 4. If leave found but no active QRPass exists yet, auto-create initial pass
    if leave and not qr:
        expires_at = timezone.make_aware(datetime.combine(leave.leave_from, time(23, 59, 59)))
        pass_type = 'ENTRY' if leave.exit_verified else 'EXIT'
        qr = QRPass.objects.create(
            leave=leave,
            pass_type=pass_type,
            expires_at=expires_at
        )

    if not qr or not leave:
        context = {
            'qr': None,
            'leave': None,
            'student': None,
            'bed': None,
            'error_msg': f"No valid gate pass found for token '{clean_token}'. Please verify the pass number.",
            'success_msg': None,
        }
        return render(request, 'leave/scan_confirmation.html', context)

    student = leave.student
    error_msg = None
    success_msg = None
    
    # Condition 1: check if used
    if qr.is_used:
        error_msg = "Pass Already Used"
    # Check if expired
    elif timezone.now() > qr.expires_at:
        error_msg = "Pass Expired"
    
    if request.method == 'POST' and not error_msg:
        with transaction.atomic():
            # Condition 2: type == EXIT
            if qr.pass_type == 'EXIT':
                leave.exit_time = timezone.now()
                leave.exit_verified = True
                leave.save()
                
                qr.is_used = True
                qr.used_at = timezone.now()
                qr.save()
                
                # Generate ENTRY QR Pass (Expires end of return date + 1)
                expires_at = timezone.make_aware(datetime.combine(leave.leave_to or leave.leave_from, time(23, 59, 59)))
                QRPass.objects.create(
                    leave=leave,
                    pass_type='ENTRY',
                    expires_at=expires_at
                )
                success_msg = f"EXIT APPROVED for {student.name}. Entry QR pass generated."
                
                # Update Student Status
                student.status = 'On Leave'
                student.save()
                
            # Condition 3: type == ENTRY
            elif qr.pass_type == 'ENTRY':
                leave.entry_time = timezone.now()
                leave.entry_verified = True
                leave.status = 'completed'
                leave.save()
                
                qr.is_used = True
                qr.used_at = timezone.now()
                qr.save()
                
                # Restore Student Status
                student.status = 'Active'
                student.save()

                # Remove/Delete GatePass record so pass is deleted upon entry approval
                if hasattr(leave, 'gate_pass'):
                    leave.gate_pass.delete()

                success_msg = f"ENTRY APPROVED for {student.name}. Gating workflow complete."
    
    context = {
        'qr': qr,
        'leave': leave,
        'student': student,
        'bed': student.allocated_beds.first(),
        'error_msg': error_msg,
        'success_msg': success_msg,
    }
    return render(request, 'leave/scan_confirmation.html', context)



