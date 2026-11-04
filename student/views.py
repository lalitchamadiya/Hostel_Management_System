from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.db import transaction, IntegrityError
import secrets

from .forms import StudentForm
from .models import Student


from django.db.models import Q, Count
from django.db.models.functions import ExtractMonth
from .models import DEPARTMENT_CHOICES, COURSE_CHOICES, STATUS_CHOICES

from django.utils import timezone
import json
from authentication.decorators import role_required, permission_required
from django.core.exceptions import PermissionDenied



@login_required
@permission_required('student', 'view')
def student_list(request):
    # Student role isolation: Redirect to their own profile if they try to access list
    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        try:
            student_obj = Student.objects.get(user=request.user)
            return redirect('view_student', pk=student_obj.pk)
        except Student.DoesNotExist:
            raise PermissionDenied("Student record not found for this user.")

    query = request.GET.get('q')
    dept = request.GET.get('department')
    course = request.GET.get('course')
    status = request.GET.get('status')
    
    # Attempt migrating any file-based student photos on disk to persistent Base64 in PostgreSQL
    try:
        import os, base64, mimetypes
        from django.conf import settings as _settings
        pending_students = Student.objects.filter(photo_data__isnull=True).exclude(photo='')
        for s in pending_students[:10]:
            if s.photo and hasattr(s.photo, 'name') and s.photo.name:
                p = os.path.join(str(_settings.MEDIA_ROOT), str(s.photo.name))
                if os.path.exists(p):
                    with open(p, 'rb') as f:
                        raw = f.read()
                    if raw:
                        mime, _ = mimetypes.guess_type(s.photo.name)
                        mime = mime or 'image/jpeg'
                        b64 = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                        Student.objects.filter(pk=s.pk).update(photo_data=b64)
    except Exception:
        pass

    students = Student.objects.select_related('user').all()
    
    if query:
        students = students.filter(
            Q(name__icontains=query) |
            Q(roll__icontains=query) |
            Q(email__icontains=query) |
            Q(phone_number__icontains=query)
        )
    
    if dept:
        students = students.filter(department=dept)
    
    if course:
        students = students.filter(course=course)
        
    if status:
        students = students.filter(status=status)
        
    context = {
        'students': students,
        'departments': [choice[0] for choice in DEPARTMENT_CHOICES],
        'courses': [choice[0] for choice in COURSE_CHOICES],
        'statuses': [choice[0] for choice in STATUS_CHOICES],
        'current_filters': {
            'q': query,
            'department': dept,
            'course': course,
            'status': status,
        }
    }
    return render(request, 'student/student_list.html', context)


@transaction.atomic
@login_required
@permission_required('student', 'add')
def create_student(request):
    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES)
        if form.is_valid():
            student = form.save(commit=False)
            if 'photo' in request.FILES:
                from hms.utils import file_to_base64
                b64_str = file_to_base64(request.FILES['photo'])
                if b64_str:
                    student.photo_data = b64_str

            roll = form.cleaned_data['roll']
            email = form.cleaned_data['email']
            initial_password = secrets.token_urlsafe(8)
            try:
                user = User.objects.create_user(
                    username=roll,
                    email=email,
                    password=initial_password,
                )
            except IntegrityError:
                if User.objects.filter(username=roll).exists():
                    form.add_error('roll', 'A user with this enrollment number already exists.')
                else:
                    form.add_error('email', 'A user with this email already exists.')
            else:
                group, _ = Group.objects.get_or_create(name='Students')
                user.groups.add(group)
                student.user = user
                student.save()
                messages.success(request, f'Student created successfully. Initial temporary password: {initial_password}')
                return redirect('student_list')
    else:
        form = StudentForm()
    return render(request, 'student/create_student.html', {'form': form})


@transaction.atomic
@login_required
@permission_required('student', 'edit')
def update_student(request, pk):
    student = get_object_or_404(Student, pk=pk)

    if request.method == 'POST':
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            try:
                has_new_photo = 'photo' in request.FILES and request.FILES['photo']
                student = form.save(commit=False)
                if has_new_photo:
                    from hms.utils import file_to_base64
                    b64_str = file_to_base64(request.FILES['photo'])
                    if b64_str:
                        student.photo_data = b64_str
                else:
                    old_s = Student.objects.filter(pk=student.pk).first()
                    if old_s and old_s.photo_data:
                        student.photo_data = old_s.photo_data
                new_roll = form.cleaned_data['roll']
                new_email = form.cleaned_data['email']
                
                s_user = None
                try:
                    s_user = student.user
                except Exception:
                    s_user = None

                if s_user:
                    user_updated = False
                    if new_roll != s_user.username:
                        if User.objects.filter(username=new_roll).exclude(pk=s_user.pk).exists():
                            form.add_error('roll', 'Another user with this enrollment number already exists.')
                            return render(request, 'student/update_student.html', {'form': form, 'student': student})
                        s_user.username = new_roll
                        user_updated = True
                    if new_email != s_user.email:
                        if User.objects.filter(email=new_email).exclude(pk=s_user.pk).exists():
                            form.add_error('email', 'Another user with this email already exists.')
                            return render(request, 'student/update_student.html', {'form': form, 'student': student})
                        s_user.email = new_email
                        user_updated = True
                    if user_updated:
                        s_user.save()
                student.save()
                messages.success(request, 'Student updated successfully.')
                return redirect('student_list')
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Error saving student profile: %s", e)
                messages.error(request, f'Failed to update student profile: {str(e)}')
                return render(request, 'student/update_student.html', {'form': form, 'student': student})
    else:
        form = StudentForm(instance=student)
    return render(request, 'student/update_student.html', {'form': form, 'student': student})



from django.http import JsonResponse

@login_required
def check_roll_number(request):
    roll = request.GET.get('roll', '').strip()
    student_id = request.GET.get('student_id', '').strip()
    
    if not roll:
        return JsonResponse({'available': True})
        
    qs = Student.objects.filter(roll=roll)
    if student_id:
        qs = qs.exclude(pk=student_id)
        
    user_qs = User.objects.filter(username=roll)
    if student_id:
        try:
            s_obj = Student.objects.get(pk=student_id)
            if s_obj.user:
                user_qs = user_qs.exclude(pk=s_obj.user.pk)
        except Student.DoesNotExist:
            pass
            
    is_available = not qs.exists() and not user_qs.exists()
    return JsonResponse({'available': is_available})


@login_required
@permission_required('student', 'view')
def view_student(request, pk):
    student = get_object_or_404(Student, pk=pk)

    
    # Student role isolation: Can only view their own record
    if hasattr(request.user, 'profile') and request.user.profile.role.name == 'Student':
        if student.user != request.user:
            raise PermissionDenied("You are not authorized to view this record.")

    return render(request, 'student/view_student.html', {'student': student})


@login_required
@permission_required('student', 'delete')
def delete_student(request, pk):
    student = get_object_or_404(Student, pk=pk)

    # Prevent deleting student if currently allocated to a bed
    from room.models import Bed
    allocated_bed = Bed.objects.filter(student=student).select_related('room').first()
    if allocated_bed:
        messages.error(
            request,
            f"Cannot delete student '{student.name}': Currently allocated to Room {allocated_bed.room.room_number}, Bed #{allocated_bed.bed_number}. Please vacate the bed first."
        )
        return redirect('student_list')

    if request.method == 'POST':
        # deleting the user cascades to the Student record
        if student.user:
            student.user.delete()
        else:
            student.delete()
        messages.success(request, 'Student deleted successfully.')
        return redirect('student_list')
    return render(request, 'student/confirm_delete.html', {'student': student})


from decimal import Decimal
from room.models import HostelBuilding, Bed
from .models import StudentFeePayment

@login_required
@permission_required('fee_manager', 'view')
def fee_manager(request):
    """
    Fee Manager View: Shows calculated fees (Total Fee, Paid Fee, Remaining Fee) for all allocated students.
    Automatically resolves fees based on building fee structure matching student admission year.
    Carries forward paid fees on bed transfers.
    """
    building_filter = request.GET.get('building', '')
    status_filter = request.GET.get('status', '')
    search_q = request.GET.get('q', '').strip()

    beds_qs = Bed.objects.filter(student__isnull=False).select_related('student', 'room', 'room__building')

    if building_filter:
        beds_qs = beds_qs.filter(room__building_id=building_filter)

    if search_q:
        beds_qs = beds_qs.filter(
            Q(student__name__icontains=search_q) |
            Q(student__roll__icontains=search_q) |
            Q(student__email__icontains=search_q)
        )

    from django.utils import timezone
    current_year = str(timezone.now().year)

    records = []
    total_expected = Decimal('0.00')
    total_collected = Decimal('0.00')
    total_due = Decimal('0.00')

    for bed in beds_qs:
        student = bed.student
        summary = student.get_calculated_fee_summary()

        # Business Rule: Show all current year students, but for past years, show ONLY students with remaining fees due
        student_year = str(summary.get('academic_year') or (student.admission_date.year if student.admission_date else current_year))
        if student_year != current_year and summary['remaining_fee'] <= Decimal('0.00'):
            continue

        if status_filter and summary['status'] != status_filter:
            continue

        total_expected += summary['total_fee']
        total_collected += summary['paid_fee']
        total_due += summary['remaining_fee']

        records.append({
            'student': student,
            'bed': bed,
            'building': bed.room.building,
            'room_number': bed.room.room_number,
            'summary': summary,
        })

    buildings = HostelBuilding.objects.filter(is_active=True)

    context = {
        'page_title': 'Fee Manager',
        'records': records,
        'total_expected': total_expected,
        'total_collected': total_collected,
        'total_due': total_due,
        'buildings': buildings,
        'current_building': building_filter,
        'current_status': status_filter,
        'search_q': search_q,
    }
    return render(request, 'student/fee_manager.html', context)


@login_required
@permission_required('fee_manager', 'add')
def record_fee_payment(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount_paid', '0.00'))
            payment_method = request.POST.get('payment_method', 'ONLINE')
            transaction_id = request.POST.get('transaction_id', '').strip()
            remarks = request.POST.get('remarks', '').strip()

            if amount <= Decimal('0.00'):
                messages.error(request, 'Please enter a valid payment amount.')
                return redirect('fee_manager')

            receipt_no = f"REC-{timezone.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

            StudentFeePayment.objects.create(
                student=student,
                academic_year=student.academic_year or str(student.admission_date.year if student.admission_date else 2026),
                amount_paid=amount,
                payment_date=timezone.now().date(),
                payment_method=payment_method,
                transaction_id=transaction_id,
                receipt_number=receipt_no,
                remarks=remarks,
                recorded_by=request.user
            )
            messages.success(request, f'Payment of ₹{amount} recorded successfully for {student.name}. Receipt #{receipt_no}.')
        except Exception as e:
            messages.error(request, f'Error recording payment: {e}')

    return redirect('fee_manager')


from .models import FeeInstallment, FeePenalty

@login_required
@permission_required('fee_manager', 'add')
def fee_installments(request):
    """
    Manage Fee Installment Due Dates
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            name = request.POST.get('installment_name', '').strip()
            due_date = request.POST.get('due_date')
            percentage = request.POST.get('percentage', '50.00')
            academic_year = request.POST.get('academic_year', '2026').strip()
            desc = request.POST.get('description', '').strip()

            if name and due_date:
                FeeInstallment.objects.create(
                    installment_name=name,
                    due_date=due_date,
                    percentage=percentage,
                    academic_year=academic_year,
                    description=desc
                )
                messages.success(request, f'Installment "{name}" created successfully.')
            else:
                messages.error(request, 'Please provide both installment name and due date.')

        elif action == 'toggle':
            inst_id = request.POST.get('installment_id')
            inst = get_object_or_404(FeeInstallment, pk=inst_id)
            inst.is_active = not inst.is_active
            inst.save()
            messages.info(request, f'Installment "{inst.installment_name}" status updated.')

        elif action == 'delete':
            inst_id = request.POST.get('installment_id')
            inst = get_object_or_404(FeeInstallment, pk=inst_id)
            inst.delete()
            messages.success(request, 'Installment deleted successfully.')

        return redirect('fee_installments')

    installments = FeeInstallment.objects.all().order_by('due_date')
    context = {
        'page_title': 'Fee Installment Dates',
        'installments': installments,
    }
    return render(request, 'student/fee_installments.html', context)


@login_required
@permission_required('fee_manager', 'add')
def fee_penalties(request):
    """
    Manage Late Fee Penalty Rules & Grace Periods
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            title = request.POST.get('title', '').strip()
            penalty_type = request.POST.get('penalty_type', 'PER_DAY')
            amount = request.POST.get('amount', '50.00')
            grace_period = request.POST.get('grace_period_days', '5')

            if title:
                FeePenalty.objects.create(
                    title=title,
                    penalty_type=penalty_type,
                    amount=amount,
                    grace_period_days=grace_period
                )
                messages.success(request, f'Penalty rule "{title}" created successfully.')
            else:
                messages.error(request, 'Please provide a penalty title.')

        elif action == 'toggle':
            penalty_id = request.POST.get('penalty_id')
            pen = get_object_or_404(FeePenalty, pk=penalty_id)
            pen.is_active = not pen.is_active
            pen.save()
            messages.info(request, f'Penalty rule "{pen.title}" status updated.')

        elif action == 'delete':
            penalty_id = request.POST.get('penalty_id')
            pen = get_object_or_404(FeePenalty, pk=penalty_id)
            pen.delete()
            messages.success(request, 'Penalty rule deleted successfully.')

        return redirect('fee_penalties')

    penalties = FeePenalty.objects.all().order_by('-created_at')
    context = {
        'page_title': 'Fee Penalty Rules',
        'penalties': penalties,
    }
    return render(request, 'student/fee_penalties.html', context)


@login_required
@permission_required('fee_manager', 'view')
def fee_transactions(request):
    """
    View complete record of all student fee payments & transaction receipts
    """
    search_q = request.GET.get('q', '').strip()
    payment_method = request.GET.get('method', '').strip()
    building_id = request.GET.get('building', '').strip()

    payments = StudentFeePayment.objects.select_related('student', 'recorded_by').all().order_by('-payment_date', '-created_at')

    if search_q:
        payments = payments.filter(
            Q(student__name__icontains=search_q) |
            Q(student__roll__icontains=search_q) |
            Q(receipt_number__icontains=search_q) |
            Q(transaction_id__icontains=search_q)
        )

    if payment_method:
        payments = payments.filter(payment_method=payment_method)

    if building_id:
        payments = payments.filter(student__allocated_beds__room__building_id=building_id).distinct()

    total_amount = sum(p.amount_paid for p in payments)
    cash_total = sum(p.amount_paid for p in payments if p.payment_method == 'CASH')
    online_total = sum(p.amount_paid for p in payments if p.payment_method in ['ONLINE', 'BANK_TRANSFER', 'CHEQUE'])

    from room.models import HostelBuilding
    buildings = HostelBuilding.objects.filter(is_active=True)

    context = {
        'page_title': 'Fee Transactions History',
        'payments': payments,
        'search_q': search_q,
        'current_method': payment_method,
        'current_building': building_id,
        'buildings': buildings,
        'total_amount': total_amount,
        'cash_total': cash_total,
        'online_total': online_total,
    }
    return render(request, 'student/fee_transactions.html', context)