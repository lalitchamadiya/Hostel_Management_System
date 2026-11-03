from django.contrib import messages
from django.shortcuts import get_object_or_404, render , redirect
from leave.models import HostelLeave, GatePass
from student.forms import StudentForm, StudentSelfUpdateForm
from student.models import Student 
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.utils.timezone import now
import uuid
from django.db import models
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
try:
    from xhtml2pdf import pisa
except ImportError:  # pragma: no cover
    pisa = None



@login_required(login_url='/authentication/login/')
def student_dashboard(request):
    student = get_object_or_404(Student, user=request.user)
    
    # Bed/Room info
    bed = student.allocated_beds.first()
    
    # Leave Info
    recent_leaves = HostelLeave.objects.filter(student=student).order_by('-created_at')[:5]
    
    context = {
        'student': student,
        'bed': bed,
        'recent_leaves': recent_leaves,
    }
    return render(request, 'student_app/student_dashboard.html', context)


@login_required(login_url='/authentication/login/')
def student_gate_pass(request):
    student = get_object_or_404(Student, user=request.user)
    active_leave = HostelLeave.objects.filter(
        student=student
    ).exclude(
        status__in=['completed', 'entered', 'rejected']
    ).order_by('-created_at').first()

    if not active_leave:
        active_leave = HostelLeave.objects.filter(
            student=student,
            status='approved'
        ).order_by('-created_at').first()

    if active_leave:
        return view_active_pass(request, leave_id=active_leave.id)

    context = {
        'student': student,
        'leave': None,
        'active_pass': None,
        'bed': student.allocated_beds.first(),
    }
    return render(request, 'student_app/student_pass_view.html', context)


@login_required(login_url='/authentication/login/')
def student_gate_passes_status_json(request):
    student = get_object_or_404(Student, user=request.user)
    gate_passes = GatePass.objects.filter(leave_request__student=student).order_by('-created_at')
    passes_data = []
    for gp in gate_passes:
        leave = gp.leave_request
        active_qr = leave.qr_passes.order_by('-generated_at').first()
        passes_data.append({
            'gp_id': gp.id,
            'gate_pass_no': gp.gate_pass_no,
            'leave_id': leave.id,
            'leave_status': leave.status,
            'exit_verified': leave.exit_verified,
            'entry_verified': leave.entry_verified,
            'has_pass': bool(active_qr),
            'pass_type': active_qr.pass_type if active_qr else None,
            'is_used': active_qr.is_used if active_qr else False,
            'qr_token': str(active_qr.qr_token) if active_qr else None,
            'qr_url': request.build_absolute_uri(reverse('qr_code_image', kwargs={'qr_token': active_qr.qr_token})) if active_qr else None,
            'expires_at': active_qr.expires_at.strftime('%Y-%m-%d %H:%M:%S') if active_qr else None,
            'is_completed': leave.status in ['completed', 'entered'],
        })
    response = JsonResponse({'passes': passes_data})
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@login_required(login_url='/authentication/login/')
def student_profile(request):
    student = get_object_or_404(Student, user=request.user)
    return render(request, 'student_app/student_profile.html', {'student': student})


@login_required(login_url='/authentication/login/')
def student_profile_update(request):
    student = get_object_or_404(Student, user=request.user)
    
    if request.method == 'POST':
        form = StudentSelfUpdateForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            obj = form.save(commit=False)
            if 'photo' in request.FILES:
                from hms.utils import file_to_base64
                b64_str = file_to_base64(request.FILES['photo'])
                if b64_str:
                    obj.photo_data = b64_str
            obj.save()
            messages.success(request, 'Student updated successfully')
            return redirect('student_app:student_profile')
        else:
            # If the form is not valid, add an error message
            messages.error(request, 'Please correct the errors below.')
            if not form.is_valid():
                print(form.errors)
    else:
        form = StudentSelfUpdateForm(instance=student)
        
    return render(request, 'student_app/student_profile_update.html', {'form': form,'student': student})


@login_required(login_url='/authentication/login/')
def food_schedule(request):
    food_schedule = {
        'Monday': {
            'breakfast': 'Thepla',
            'breakfast_image': 'https://media.istockphoto.com/id/1807607799/photo/thepla-or-methi-thepla-gujarati-dish.webp?a=1&b=1&s=612x612&w=0&k=20&c=XD1obx3pjZGOEhaz-bUMl0JQzPA5HmEdLqvqKp-7apA=',
            'lunch': 'Gujarati Thali',
            'lunch_image': 'https://media.istockphoto.com/id/469160387/photo/gujarati-thali.webp?a=1&b=1&s=612x612&w=0&k=20&c=wX5kx52ZHpYsmGAasLdOBSkE3MpKVOeTiFcmkb5wgRI=',
            'dinner': 'Undhiyu',
            'dinner_image': 'https://media.istockphoto.com/id/1177420020/photo/undhiyu-is-a-gujarati-mixed-vegetable-dish-specialty-of-surat-india-served-in-a-bowl-with-or.webp?a=1&b=1&s=612x612&w=0&k=20&c=p3vdeTPkJARqNfrfrmOzcCU-OWkARcnUZbnyHYuo6vc=',
        },
        'Tuesday': {
            'breakfast': 'Dhokla',
            'breakfast_image': 'https://media.istockphoto.com/id/2154971502/photo/famous-gujrati-snack-dhokla-made-with-gram-flour-and-sugar-syrup-decorated-with-mint-and.webp?a=1&b=1&s=612x612&w=0&k=20&c=MacEDJlATPi0-ztKaDwBRJxq4k9KPKI6MhZwEoZdQeg=',
            'lunch': 'Kadhi and Khichdi',
            'lunch_image': 'https://media.istockphoto.com/id/1255780592/photo/dal-khichadi-and-kadhi-with-papad-and-raw-mango-pickle.webp?a=1&b=1&s=612x612&w=0&k=20&c=tlOmaex2c7oT0eB-XllGD88T-MXaAXWR4l7OSQhks-w=',
            'dinner': 'Handvo',
            'dinner_image': 'https://media.istockphoto.com/id/2154972036/photo/gujrati-food-handvo-decorated-with-mint-chutney-curry-leaves-lemons-and-tomato-sauce.webp?a=1&b=1&s=612x612&w=0&k=20&c=7tbcEfR-Cexekj3YhRkLCkg2_PZwvwWZYblEbk2h6pU=',
        },
        'Wednesday': {
            'breakfast': 'Fafda Jalebi',
            'breakfast_image': 'https://media.istockphoto.com/id/1413554835/photo/popular-indian-sweet-jalebi-and-fafda-served-with-sambhara-gujarati-snack-is-mostly-eaten.webp?a=1&b=1&s=612x612&w=0&k=20&c=ZrJsrIpUM7uvoXDu4oTolagi2xU7mZVcAdmrMSIecjw=',
            'lunch': 'Bharela Ringan (Stuffed Eggplant)',
            'lunch_image': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQD5CEgKCjP_71K-lKyhtCzBF0isoOFeVQdCg&s',
            'dinner': 'Sev Tameta Nu Shaak',
            'dinner_image': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRAqqFS6rucXCp4dvGL_eXyFSuQkSp3Q9wGPQ&s',
        },
        'Thursday': {
            'breakfast': 'Khaman',
            'breakfast_image': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/SPECIAL_SURATI_KHAMAN.jpg/250px-SPECIAL_SURATI_KHAMAN.jpg',
            'lunch': 'Dal Dhokli',
            'lunch_image': 'https://www.jcookingodyssey.com/wp-content/uploads/2025/02/gujarati-dal-dhokli.jpg',
            'dinner': 'Muthiya',
            'dinner_image': 'https://herbivorecucina.com/wp-content/uploads/2023/05/Kale-Muthiya-1.jpg',
        },
        'Friday': {
            'breakfast': 'Gota',
            'breakfast_image': 'https://i0.wp.com/binjalsvegkitchen.com/wp-content/uploads/2016/06/Methi-Na-Gota-H1.jpg?w=600&ssl=1',
            'lunch': 'Gujarati Shaak and Rotli',
            'lunch_image': 'https://static.wixstatic.com/media/5a630d_083f4a870ed749a9aaae18389a5aec18~mv2.jpg/v1/fill/w_740,h_1036,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/5a630d_083f4a870ed749a9aaae18389a5aec18~mv2.jpg',
            'dinner': 'Khichu',
            'dinner_image': 'https://www.theroute2roots.com/wp-content/uploads/2020/05/Khichu-12-of-4-1.jpeg',
        },
        'Saturday': {
            'breakfast': 'Puran Poli',
            'breakfast_image': 'https://shwetainthekitchen.com/wp-content/uploads/2020/03/IMG_7944-scaled.jpg',
            'lunch': 'Patra',
            'lunch_image': 'https://cookilicious.com/wp-content/uploads/2021/08/pathrode-patra-colocasia-pinwheels-4.jpg',
            'dinner': 'Dabeli',
            'dinner_image': 'https://i0.wp.com/binjalsvegkitchen.com/wp-content/uploads/2017/10/Kutchi-Dabeli-H1.jpg?w=600&ssl=1',
        },
        'Sunday': {
            'breakfast': 'Bhakhri and Chai',
            'breakfast_image': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR01FZ4Zp0BOUrGz_pSQczh4yKLXNAJ2_tjtg&s',
            'lunch': 'Surti Locho',
            'lunch_image': 'https://www.cookingcarnival.com/wp-content/uploads/2020/06/Surti-locho-recipe-2.jpg',
            'dinner': 'Khaman Dhokla',
            'dinner_image': 'https://thespicemess.com/wp-content/uploads/2022/04/Khaman-Dhokla-57-1.jpg',
        },
    }
    return render(request, 'student_app/food_schedule.html', {'food_schedule': food_schedule})


@login_required(login_url='/authentication/login/')
def student_leave_request(request):
    student_details = get_object_or_404(Student, email=request.user.email)
    latest_leave = HostelLeave.objects.filter(student=student_details).order_by('-created_at').first()

    if request.method == 'POST':
        reason = request.POST.get('reason')
        leave_date = request.POST.get('leave_date')

        leave_date = parse_date(leave_date)
        if not leave_date:
            messages.error(request, 'Invalid leave date.')
            return render(request, 'student_app/student_leave_request.html', {'student_details': student_details, 'latest_leave': latest_leave})

        try:
            # Check if the latest leave request is still active
            if latest_leave and latest_leave.status not in ['entered', 'completed', 'rejected']:
                messages.error(request, 'You cannot submit a new leave request until your previous application is completed or rejected.')
                return redirect('student_app:student_leave_request')

            hostelleave = HostelLeave(
                student=student_details,
                leave_from=leave_date,
                leave_to=parse_date(request.POST.get('return_date')),
                start_time=request.POST.get('start_time'),
                end_time=request.POST.get('end_time'),
                reason=reason,
                destination=request.POST.get('destination'),
                transport_mode=request.POST.get('transport_mode'),
                remarks=request.POST.get('remarks')
            )
            hostelleave.save()
            messages.success(request, 'Leave request submitted successfully.')
            return redirect('student_app:student_leave_details')
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")

    return render(
        request,
        'student_app/student_leave_request.html',
        {
            'student_details': student_details,
            'latest_leave': latest_leave,
            'today_date': now().date().isoformat(),
        },
    )


@login_required(login_url='/authentication/login/')
def student_leave_details(request):
    if request.user.is_authenticated:
        try:
            student = get_object_or_404(Student, email=request.user.email)
            leave_requests = HostelLeave.objects.filter(student=student).order_by('-created_at')
        except Student.DoesNotExist:
            leave_requests = []
    else:
        leave_requests = []

    return render(request, 'student_app/student_leave_details.html', {'leave_requests': leave_requests})

@login_required(login_url='/authentication/login/')
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password1 = request.POST.get('new_password1')
        new_password2 = request.POST.get('new_password2')

        if not request.user.check_password(old_password):
            messages.error(request, 'Your current password is incorrect.')
            return redirect('student_app:change_password')

        if new_password1 != new_password2:
            messages.error(request, 'The new passwords do not match.')
            return redirect('student_app:change_password')

        if len(new_password1) < 8:
            messages.error(request, 'The new password must be at least 8 characters long.')
            return redirect('student_app:change_password')

        # Change the password
        request.user.set_password(new_password1)
        request.user.save()

        # Keep the user logged in after changing the password
        update_session_auth_hash(request, request.user)

        messages.success(request, 'Your password has been successfully changed.')
        return redirect('student_app:student_profile')

    return render(request, 'student_app/student_profile_password_change.html')


@login_required(login_url='/authentication/login/')
def view_active_pass(request, leave_id):
    student = get_object_or_404(Student, user=request.user)
    leave = get_object_or_404(HostelLeave, id=leave_id, student=student)
    
    # Get active/latest pass (EXIT or ENTRY)
    active_pass = leave.qr_passes.order_by('-generated_at').first()
    
    # If no pass exists and leave is approved, auto-generate EXIT pass as fallback
    if not active_pass and leave.status == 'approved':
        from leave.models import QRPass
        from datetime import time, datetime
        from django.utils import timezone
        expires_at = timezone.make_aware(datetime.combine(leave.leave_from, time(23, 59, 59)))
        active_pass = QRPass.objects.create(
            leave=leave,
            pass_type='EXIT',
            expires_at=expires_at
        )

    context = {
        'student': student,
        'leave': leave,
        'active_pass': active_pass,
        'bed': student.allocated_beds.first(),
    }
    return render(request, 'student_app/student_pass_view.html', context)

from django.urls import reverse

@login_required(login_url='/authentication/login/')
def active_pass_status_json(request, leave_id):
    student = get_object_or_404(Student, user=request.user)
    leave = get_object_or_404(HostelLeave, id=leave_id, student=student)
    active_pass = leave.qr_passes.order_by('-generated_at').first()
    
    data = {
        'has_pass': bool(active_pass),
        'leave_id': leave.id,
        'leave_status': leave.status,
        'exit_verified': leave.exit_verified,
        'entry_verified': leave.entry_verified,
    }
    
    if active_pass:
        data.update({
            'pass_id': active_pass.id,
            'pass_type': active_pass.pass_type,
            'is_used': active_pass.is_used,
            'qr_token': str(active_pass.qr_token),
            'qr_url': request.build_absolute_uri(reverse('qr_code_image', kwargs={'qr_token': active_pass.qr_token})),
            'expires_at': active_pass.expires_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    response = JsonResponse(data)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


