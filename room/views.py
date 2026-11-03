import json
from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from student.models import Student
from .models import HostelBuilding, BuildingFeeStructure, Room, Bed


class RoomForm(forms.Form):
    building = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_building'})
    )
    block = forms.ChoiceField(
        choices=[('A', 'Block A'), ('B', 'Block B')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_block'})
    )
    floor = forms.ChoiceField(
        choices=[(1, '1st Floor'), (2, '2nd Floor'), (3, '3rd Floor')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_floor'})
    )
    room_number = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_room_number', 'placeholder': 'e.g. 101'})
    )
    room_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_room_name', 'placeholder': 'e.g. Deluxe Suite'})
    )
    room_type = forms.ChoiceField(
        choices=[
            ('2_BED', '2 BED (Double Sharing)'),
            ('4_BED', '4 BED (Quad Sharing)'),
            ('CUSTOM', 'CUSTOM (Specify Capacity)'),
        ],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_room_type'})
    )
    category = forms.ChoiceField(
        choices=[('GENERAL', 'General Student'), ('DELUXE', 'Deluxe Premium'), ('STAFF', 'Staff / Warden')],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_category'})
    )
    status = forms.ChoiceField(
        choices=[('AVAILABLE', 'Available / Active'), ('MAINTENANCE', 'Under Maintenance')],
        widget=forms.Select(attrs={'class': 'form-select', 'name': 'status', 'id': 'id_status'})
    )
    is_ac = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_ac'})
    )
    capacity = forms.IntegerField(
        initial=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_capacity', 'min': 1, 'max': 20})
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'id': 'id_description', 'rows': 2})
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop('buildings_data', None)
        super().__init__(*args, **kwargs)
        buildings = HostelBuilding.objects.filter(is_active=True)
        if buildings.exists():
            self.fields['building'].choices = [(str(b.pk), b.name) for b in buildings]
        else:
            self.fields['building'].choices = []


class BuildingForm(forms.Form):
    name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Boys Hostel Block A'})
    )
    gender = forms.ChoiceField(
        choices=[('Boys', 'Boys Wing / Male'), ('Girls', 'Girls Wing / Female')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    total_floors = forms.IntegerField(
        initial=3,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 20})
    )
    blocks = forms.CharField(
        initial='Block A, Block B',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Block A, Block B'})
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    # Student Fee Configuration
    fee_type = forms.ChoiceField(
        choices=[
            ('MONTHLY_PER_STUDENT', 'Monthly – Per Student'),
            ('YEARLY_PER_STUDENT', 'Yearly – Per Student'),
        ],
        initial='MONTHLY_PER_STUDENT',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_fee_type', 'onchange': 'toggleFeeLabels()'})
    )
    academic_year = forms.CharField(
        initial='2026',
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_academic_year', 'placeholder': 'e.g. 2026 or 2027'})
    )
    monthly_fee_per_student = forms.DecimalField(
        initial=6000.00,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_monthly_fee_per_student', 'step': '100', 'min': 0})
    )
    yearly_fee_per_student = forms.DecimalField(
        initial=60000.00,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_yearly_fee_per_student', 'step': '500', 'min': 0})
    )


# ── Main Room Dashboard ──
@login_required(login_url='/authentication/login')
def room_base(request):
    active_buildings = HostelBuilding.objects.filter(is_active=True)
    active_b_ids = set(active_buildings.values_list('id', flat=True))

    total_rooms = Room.objects.filter(building_id__in=active_b_ids).count()
    boys_rooms = Room.objects.filter(building_id__in=active_b_ids, gender='Boys').count()
    girls_rooms = Room.objects.filter(building_id__in=active_b_ids, gender='Girls').count()

    total_beds = Bed.objects.filter(room__building_id__in=active_b_ids).count()
    allocated_beds = Bed.objects.filter(room__building_id__in=active_b_ids, student__isnull=False).count()
    vacant_beds = max(0, total_beds - allocated_beds)

    boys_allocated = Bed.objects.filter(room__building_id__in=active_b_ids, student__isnull=False, room__gender='Boys').count()
    girls_allocated = Bed.objects.filter(room__building_id__in=active_b_ids, student__isnull=False, room__gender='Girls').count()

    context = {
        'page_title': 'Room Management Dashboard',
        'total_buildings': len(active_b_ids),
        'total_availabel_room': total_rooms,
        'total_boys_rooms': boys_rooms,
        'total_girls_rooms': girls_rooms,
        'total_allocated_beds': allocated_beds,
        'total_unallocated_beds': vacant_beds,
        'total_maintenance_rooms': Room.objects.filter(building_id__in=active_b_ids, status='MAINTENANCE').count(),
        'total_reserved_beds': 0,
        'total_boys_allocated': boys_allocated,
        'total_girls_allocated': girls_allocated,
        'upcoming_vacancies': 0,
    }
    return render(request, 'room/room_base.html', context)


# ── Room Management (Overview) ──
@login_required(login_url='/authentication/login')
def room_manage(request):
    search_query = request.GET.get('q', '').strip()
    selected_building_id = request.GET.get('building', '')

    active_buildings = HostelBuilding.objects.filter(is_active=True)
    active_b_ids = set(active_buildings.values_list('id', flat=True))

    qs = Room.objects.prefetch_related('beds__student', 'building').all()
    if selected_building_id:
        qs = qs.filter(building_id=selected_building_id)
    else:
        qs = qs.filter(building_id__in=active_b_ids)

    if search_query:
        qs = qs.filter(room_number__icontains=search_query) | qs.filter(room_name__icontains=search_query)

    rooms_list = []
    for r in qs:
        beds_list = []
        occupied_count = 0
        for b in r.beds.all():
            if b.student:
                occupied_count += 1
            beds_list.append({
                'id': b.id,
                'bed_number': b.bed_number,
                'student': b.student
            })

        room_obj = {
            'id': r.id,
            'pk': r.id,
            'room_number': r.room_number,
            'room_name': r.room_name or f"Unit #{r.room_number}",
            'building': {'id': r.building.id, 'name': r.building.name},
            'block': r.block,
            'get_block_display': f"Block {r.block}",
            'room_type': r.capacity,
            'gender': r.gender,
            'beds': {'all': beds_list},
            'occupied_count': occupied_count,
        }
        rooms_list.append(room_obj)

    b_list = [{'pk': b.pk, 'name': b.name} for b in active_buildings]

    context = {
        'page_title': 'Room Overview',
        'rooms': rooms_list,
        'buildings': b_list,
        'selected_building_id': selected_building_id,
        'search_query': search_query,
    }
    return render(request, 'room/manage.html', context)


# ── Room Allocation ──
@login_required(login_url='/authentication/login')
def room_allocate(request):
    if request.method == 'POST':
        room_id = request.POST.get('room-select')
        bed_num = request.POST.get('bed-select')
        student_id = request.POST.get('student-select')

        if room_id and bed_num and student_id:
            room_obj = Room.objects.filter(pk=room_id).first()
            if room_obj:
                bed_obj = Bed.objects.filter(room=room_obj, bed_number=str(bed_num)).first()
                if bed_obj:
                    st_obj = Student.objects.filter(student_id=student_id).first()
                    if st_obj:
                        existing_bed = Bed.objects.filter(student=st_obj).exclude(room=room_obj, bed_number=str(bed_num)).first()
                        if existing_bed:
                            messages.error(request, f'{st_obj.name} is already allocated to Room {existing_bed.room.room_number} Bed {existing_bed.bed_number}. Each student can only be allocated to one bed.')
                            return redirect('room_allocate')
                        bed_obj.student = st_obj
                        bed_obj.save()
                        messages.success(request, f'{st_obj.name} successfully allocated to Room {room_obj.room_number} Bed {bed_num}.')
                        return redirect('student_allocated_view', room_id=room_obj.id)

        messages.error(request, 'Invalid room, bed, or student selection.')
        return redirect('room_allocate')

    b_list = [
        {'id': b.id, 'name': b.name, 'get_gender_display': b.gender}
        for b in HostelBuilding.objects.filter(is_active=True)
    ]
    blocks = [('A', 'Block A'), ('B', 'Block B')]

    context = {
        'page_title': 'Allocate Bed',
        'buildings': b_list,
        'blocks': blocks,
    }
    return render(request, 'room/allocate.html', context)


# ── Auto Allocate ──
@login_required(login_url='/authentication/login')
def room_auto_allocate(request):
    assigned_student_ids = Bed.objects.filter(student__isnull=False).values_list('student_id', flat=True)
    unallocated_students = Student.objects.filter(status='Active').exclude(student_id__in=assigned_student_ids)

    context = {
        'page_title': 'Auto Allocate Rooms',
        'unallocated_students': unallocated_students,
    }
    return render(request, 'room/auto_allocate.html', context)


@login_required(login_url='/authentication/login')
def room_auto_allocate_execute(request):
    if request.method == 'POST':
        active_b_ids = set(HostelBuilding.objects.filter(is_active=True).values_list('id', flat=True))
        assigned_student_ids = set(Bed.objects.filter(student__isnull=False).values_list('student_id', flat=True))

        unallocated_students = list(Student.objects.filter(status='Active').exclude(student_id__in=assigned_student_ids))

        allocated_count = 0
        for student in unallocated_students:
            st_gender = 'Boys' if student.gender == 'Male' else 'Girls'
            vacant_bed = Bed.objects.filter(
                student__isnull=True,
                room__building_id__in=active_b_ids,
                room__gender=st_gender
            ).first()
            if vacant_bed:
                vacant_bed.student = student
                vacant_bed.save()
                allocated_count += 1

        if allocated_count > 0:
            messages.success(request, f'Successfully auto-allocated {allocated_count} residents to vacant hostel beds.')
        else:
            messages.info(request, 'No unallocated students or vacant beds in active buildings available for auto-allocation.')

    return redirect('room_manage')


# ── Create Room ──
@login_required(login_url='/authentication/login')
def create_room(request):
    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            building_id = int(cleaned.get('building', 1))
            b_info = HostelBuilding.objects.filter(pk=building_id).first()
            if not b_info:
                b_info = HostelBuilding.objects.filter(is_active=True).first()

            if not b_info:
                messages.error(request, 'Please create a hostel building before adding rooms.')
                return redirect('building_create')

            gender = b_info.gender
            r_type = cleaned.get('room_type', '2_BED')

            if r_type == '2_BED':
                capacity = 2
            elif r_type == '4_BED':
                capacity = 4
            else:
                capacity = int(cleaned.get('capacity', 2))

            room_obj = Room.objects.create(
                building=b_info,
                room_number=cleaned.get('room_number'),
                room_name=cleaned.get('room_name') or f"Unit #{cleaned.get('room_number')}",
                block=cleaned.get('block', 'A'),
                floor=cleaned.get('floor', 1),
                room_type=r_type,
                category=cleaned.get('category', 'GENERAL'),
                gender=gender,
                capacity=capacity,
                status=cleaned.get('status', 'AVAILABLE'),
                is_ac=bool(cleaned.get('is_ac')),
                description=cleaned.get('description', '')
            )

            for b_idx in range(1, capacity + 1):
                Bed.objects.create(room=room_obj, bed_number=str(b_idx), student=None)

            messages.success(request, f"New Room #{cleaned.get('room_number')} created successfully.")
            return redirect('room_manage')
    else:
        form = RoomForm()

    context = {
        'page_title': 'Create New Room',
        'action': 'Create',
        'form': form,
    }
    return render(request, 'room/create_room.html', context)


# ── Edit / Delete / Change Room ──
@login_required(login_url='/authentication/login')
def edit_room(request, pk):
    room_obj = get_object_or_404(Room, pk=pk)

    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            building_id = int(cleaned.get('building', 1))
            b_info = HostelBuilding.objects.filter(pk=building_id).first() or room_obj.building

            r_type = cleaned.get('room_type', '2_BED')
            if r_type == '2_BED':
                capacity = 2
            elif r_type == '4_BED':
                capacity = 4
            else:
                capacity = int(cleaned.get('capacity', 2))

            room_obj.building = b_info
            room_obj.room_number = cleaned.get('room_number')
            room_obj.room_name = cleaned.get('room_name') or f"Unit #{cleaned.get('room_number')}"
            room_obj.block = cleaned.get('block', 'A')
            room_obj.floor = cleaned.get('floor', 1)
            room_obj.room_type = r_type
            room_obj.category = cleaned.get('category', 'GENERAL')
            room_obj.gender = b_info.gender
            room_obj.capacity = capacity
            room_obj.status = cleaned.get('status', 'AVAILABLE')
            room_obj.is_ac = bool(cleaned.get('is_ac'))
            room_obj.description = cleaned.get('description', '')
            room_obj.save()

            current_beds = list(room_obj.beds.all())
            if len(current_beds) < capacity:
                for b_idx in range(len(current_beds) + 1, capacity + 1):
                    Bed.objects.create(room=room_obj, bed_number=str(b_idx), student=None)
            elif len(current_beds) > capacity:
                for b in current_beds[capacity:]:
                    b.delete()

            messages.success(request, f"Room Unit #{cleaned.get('room_number')} updated successfully.")
            return redirect('room_manage')
    else:
        initial_data = {
            'building': str(room_obj.building.pk),
            'block': room_obj.block,
            'floor': room_obj.floor,
            'room_number': room_obj.room_number,
            'room_name': room_obj.room_name,
            'room_type': room_obj.room_type,
            'category': room_obj.category,
            'status': room_obj.status,
            'is_ac': room_obj.is_ac,
            'capacity': room_obj.capacity,
            'description': room_obj.description,
        }
        form = RoomForm(initial=initial_data)

    room_dict = {
        'pk': room_obj.pk,
        'id': room_obj.id,
        'room_number': room_obj.room_number,
        'room_name': room_obj.room_name,
    }

    context = {
        'page_title': f"Edit Room #{room_obj.room_number}",
        'action': 'Edit',
        'room': room_dict,
        'form': form,
    }
    return render(request, 'room/create_room.html', context)


@login_required(login_url='/authentication/login')
def delete_room(request, pk):
    room_obj = Room.objects.filter(pk=pk).first()
    if room_obj:
        if room_obj.beds.filter(student__isnull=False).exists():
            messages.error(request, f"Cannot delete Room #{room_obj.room_number} because it has allocated resident(s). Please deallocate residents first.")
            return redirect('room_manage')
        r_num = room_obj.room_number
        room_obj.delete()
        messages.success(request, f'Room #{r_num} deleted successfully.')
    else:
        messages.success(request, f'Room #{pk} deleted successfully.')
    return redirect('room_manage')


@login_required(login_url='/authentication/login')
def delete_allocation(request, bed_id):
    bed_obj = Bed.objects.filter(pk=bed_id).first()
    found_room_id = None
    if bed_obj:
        found_room_id = bed_obj.room.id
        bed_num = bed_obj.bed_number
        bed_obj.student = None
        bed_obj.save()
        messages.success(request, f'Allocation for Bed #{bed_num} removed successfully.')
    else:
        messages.success(request, f'Allocation for bed {bed_id} removed.')

    next_url = request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url and 'http' not in next_url:
        return redirect(next_url)
    elif found_room_id:
        return redirect('student_allocated_view', room_id=found_room_id)
    return redirect('room_manage')


@login_required(login_url='/authentication/login')
def change_room(request, current_bed_id):
    curr_bed_obj = Bed.objects.filter(pk=current_bed_id).first()
    if not curr_bed_obj:
        messages.error(request, 'Bed allocation not found.')
        return redirect('room_manage')

    curr_room_obj = curr_bed_obj.room
    assigned_student = curr_bed_obj.student

    fee_summary = assigned_student.get_calculated_fee_summary() if assigned_student else {
        'total_fee': 0, 'paid_fee': 0, 'remaining_fee': 0, 'building_name': ''
    }

    if request.method == 'POST':
        target_room_id = request.POST.get('room-select')
        target_bed_num = request.POST.get('bed-select')

        target_room_obj = Room.objects.filter(pk=target_room_id).first()
        if target_room_obj:
            curr_bed_obj.student = None
            curr_bed_obj.save()

            target_bed_obj = Bed.objects.filter(room=target_room_obj, bed_number=str(target_bed_num)).first()
            if target_bed_obj:
                target_bed_obj.student = assigned_student
                target_bed_obj.save()

            st_name = assigned_student.name if assigned_student else 'Resident'
            new_summary = assigned_student.get_calculated_fee_summary() if assigned_student else fee_summary

            messages.success(
                request,
                f"{st_name} transferred to {target_room_obj.building.name} (Room #{target_room_obj.room_number}, Bed #{target_bed_num}). "
                f"Fee recalculated: Total: ₹{new_summary['total_fee']}, Paid: ₹{new_summary['paid_fee']}, Remaining Due: ₹{new_summary['remaining_fee']}."
            )
            return redirect('student_allocated_view', room_id=target_room_obj.id)
        else:
            messages.error(request, 'Target room not found.')
            return redirect('room_manage')

    b_list = [
        {'id': b.id, 'name': b.name, 'get_gender_display': b.gender}
        for b in HostelBuilding.objects.filter(is_active=True)
    ]
    blocks = [('A', 'Block A'), ('B', 'Block B')]

    current_bed_context = {
        'id': curr_bed_obj.id,
        'bed_number': curr_bed_obj.bed_number,
        'paid_amount': str(fee_summary['paid_fee']),
        'total_amount': str(fee_summary['total_fee']),
        'remaining_amount': str(fee_summary['remaining_fee']),
        'room': {
            'id': curr_room_obj.id,
            'room_number': curr_room_obj.room_number,
            'building': {'name': curr_room_obj.building.name},
            'floor': {'floor_number': curr_room_obj.floor},
        }
    }

    context = {
        'page_title': 'Change Room',
        'current_bed': current_bed_context,
        'student': assigned_student,
        'fee_summary': fee_summary,
        'buildings': b_list,
        'blocks': blocks,
    }
    return render(request, 'room/change_room.html', context)


# ── Building Management ──
@login_required(login_url='/authentication/login')
def building_list(request):
    qs = HostelBuilding.objects.all()

    b_list = []
    for b in qs:
        room_count = b.rooms.count()
        current_fee = b.get_current_fee()
        fee_history = list(b.fee_structures.all().order_by('-academic_year'))
        b_list.append({
            'id': b.id,
            'pk': b.pk,
            'name': b.name,
            'code': b.code or f"B-{b.id}",
            'gender': b.gender,
            'get_gender_display': b.gender,
            'total_floors': b.total_floors,
            'room_count': room_count,
            'capacity': room_count * 2,
            'description': b.description or '',
            'is_active': b.is_active,
            'is_archived': b.is_archived,
            'current_fee': current_fee,
            'fee_history': fee_history,
        })

    context = {
        'page_title': 'Hostel Buildings',
        'buildings': b_list,
    }
    return render(request, 'room/building_list.html', context)


@login_required(login_url='/authentication/login')
def building_create(request):
    if request.method == 'POST':
        form = BuildingForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            b_obj = HostelBuilding.objects.create(
                name=cleaned.get('name'),
                code=f"B-{HostelBuilding.objects.count() + 1}",
                gender=cleaned.get('gender', 'Boys'),
                total_floors=cleaned.get('total_floors', 3),
                blocks=cleaned.get('blocks', 'Block A, Block B') or 'Block A',
                description=cleaned.get('description', ''),
                is_active=bool(cleaned.get('is_active', True)),
                is_archived=False,
            )
            acad_year = cleaned.get('academic_year', '2026–2027').strip() or '2026–2027'
            fee_type = cleaned.get('fee_type', 'MONTHLY_PER_STUDENT')
            monthly_fee = cleaned.get('monthly_fee_per_student') or 0.00
            yearly_fee = cleaned.get('yearly_fee_per_student') or 0.00

            BuildingFeeStructure.objects.create(
                building=b_obj,
                academic_year=acad_year,
                fee_type=fee_type,
                monthly_fee_per_student=monthly_fee,
                yearly_fee_per_student=yearly_fee,
                is_active=True,
                created_by=request.user if request.user.is_authenticated else None
            )
            fee_label = f"₹{yearly_fee}/year" if fee_type == 'YEARLY_PER_STUDENT' else f"₹{monthly_fee}/month"
            messages.success(request, f"New building '{b_obj.name}' added with fee {fee_label} ({acad_year}).")
            return redirect('building_list')
    else:
        form = BuildingForm()

    return render(request, 'room/building_form.html', {'page_title': 'Add Building', 'action': 'Add', 'form': form})


@login_required(login_url='/authentication/login')
def building_edit(request, pk):
    b_info = get_object_or_404(HostelBuilding, pk=pk)
    current_fee = b_info.get_current_fee()

    if request.method == 'POST':
        form = BuildingForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            b_info.name = cleaned.get('name')
            b_info.gender = cleaned.get('gender', 'Boys')
            b_info.total_floors = cleaned.get('total_floors', 3)
            b_info.blocks = cleaned.get('blocks', 'Block A') or 'Block A'
            b_info.description = cleaned.get('description', '')
            b_info.is_active = bool(cleaned.get('is_active', True))
            b_info.save()

            acad_year = cleaned.get('academic_year', '2026–2027').strip() or '2026–2027'
            fee_type = cleaned.get('fee_type', 'MONTHLY_PER_STUDENT')
            monthly_fee = cleaned.get('monthly_fee_per_student') or 0.00
            yearly_fee = cleaned.get('yearly_fee_per_student') or 0.00

            fee_obj, created = BuildingFeeStructure.objects.get_or_create(
                building=b_info,
                academic_year=acad_year,
                defaults={
                    'fee_type': fee_type,
                    'monthly_fee_per_student': monthly_fee,
                    'yearly_fee_per_student': yearly_fee,
                    'is_active': True,
                    'created_by': request.user if request.user.is_authenticated else None
                }
            )
            if not created:
                fee_obj.fee_type = fee_type
                fee_obj.monthly_fee_per_student = monthly_fee
                fee_obj.yearly_fee_per_student = yearly_fee
                fee_obj.save()

            messages.success(request, f"Building '{b_info.name}' updated successfully.")
            return redirect('building_list')
    else:
        initial_data = {
            'name': b_info.name,
            'gender': b_info.gender,
            'total_floors': b_info.total_floors,
            'blocks': b_info.blocks or 'Block A, Block B',
            'description': b_info.description,
            'is_active': b_info.is_active,
            'academic_year': current_fee.academic_year if current_fee else '2026–2027',
            'monthly_fee_per_student': current_fee.monthly_fee_per_student if current_fee else 6000.00,
            'yearly_fee_per_student': current_fee.yearly_fee_per_student if current_fee else 60000.00,
            'fee_type': current_fee.fee_type if current_fee else 'MONTHLY_PER_STUDENT',
        }
        form = BuildingForm(initial=initial_data)

    fee_history = b_info.fee_structures.all().order_by('-academic_year')
    return render(request, 'room/building_form.html', {
        'page_title': f"Edit Building: {b_info.name}",
        'action': 'Edit',
        'form': form,
        'building': b_info,
        'fee_history': fee_history
    })


@login_required(login_url='/authentication/login')
def add_building_fee_structure(request, building_id):
    building = get_object_or_404(HostelBuilding, pk=building_id)
    if request.method == 'POST':
        academic_year = request.POST.get('academic_year', '').strip()
        fee_type = request.POST.get('fee_type', 'MONTHLY_PER_STUDENT')
        monthly_fee = request.POST.get('monthly_fee_per_student') or 0.00
        yearly_fee = request.POST.get('yearly_fee_per_student') or 0.00
        if academic_year:
            fee_obj, created = BuildingFeeStructure.objects.update_or_create(
                building=building,
                academic_year=academic_year,
                defaults={
                    'monthly_fee_per_student': monthly_fee,
                    'yearly_fee_per_student': yearly_fee,
                    'fee_type': fee_type,
                    'is_active': True,
                    'created_by': request.user if request.user.is_authenticated else None
                }
            )
            fee_label = f"₹{yearly_fee}/year" if fee_type == 'YEARLY_PER_STUDENT' else f"₹{monthly_fee}/month"
            if created:
                messages.success(request, f"Added fee structure for {academic_year}: {fee_label}.")
            else:
                messages.success(request, f"Updated fee structure for {academic_year}: {fee_label}.")
        else:
            messages.error(request, "Please enter a valid academic year.")
    return redirect('building_edit', pk=building.pk)


@login_required(login_url='/authentication/login')
def building_delete(request, pk):
    b_obj = HostelBuilding.objects.filter(pk=pk).first()
    if b_obj:
        if Bed.objects.filter(room__building=b_obj, student__isnull=False).exists():
            messages.error(request, f"Cannot delete Building '{b_obj.name}' because it contains rooms with allocated resident(s). Please deallocate residents first.")
            return redirect('building_list')
        b_name = b_obj.name
        b_obj.delete()
        messages.success(request, f"Building '{b_name}' removed successfully.")
    else:
        messages.success(request, f"Building {pk} removed.")
    return redirect('building_list')


@login_required(login_url='/authentication/login')
def building_toggle(request, pk):
    b_info = HostelBuilding.objects.filter(pk=pk).first()
    if b_info:
        b_info.is_active = not b_info.is_active
        b_info.save()
        status_txt = 'activated' if b_info.is_active else 'deactivated'
        messages.success(request, f"Building '{b_info.name}' {status_txt}.")
    else:
        messages.success(request, f'Building {pk} status toggled.')
    return redirect('building_list')


# ── Residents & Student Views ──
@login_required(login_url='/authentication/login')
def student_details_list(request):
    beds = Bed.objects.filter(student__isnull=False).select_related('student', 'room', 'room__building')
    students = Student.objects.filter(status='Active').order_by('-student_id')
    context = {
        'page_title': 'Hostel Residents',
        'beds': beds,
        'students': students,
    }
    return render(request, 'room/student_details_list.html', context)



@login_required(login_url='/authentication/login')
def student_allocated_view(request, room_id):
    room_obj_db = Room.objects.filter(pk=room_id).first()

    if not room_obj_db:
        messages.error(request, "Room not found.")
        return redirect('room_manage')

    hydrated_beds = []
    occupied_count = 0
    for b in room_obj_db.beds.all():
        if b.student:
            occupied_count += 1
        hydrated_beds.append({
            'id': b.id,
            'bed_number': b.bed_number,
            'student': b.student,
            'remaining_amount': 0
        })

    total_beds = room_obj_db.capacity
    vacant_count = max(0, total_beds - occupied_count)

    room_obj = {
        'id': room_obj_db.id,
        'room_number': room_obj_db.room_number,
        'room_name': room_obj_db.room_name or f"Unit #{room_obj_db.room_number}",
        'building': {'name': room_obj_db.building.name},
        'floor': {'floor_number': room_obj_db.floor},
        'get_room_type_display': f"{total_beds} BED",
        'get_gender_display': f"{room_obj_db.gender} Wing",
    }

    context = {
        'page_title': f"Room #{room_obj_db.room_number} Details",
        'room_number': room_obj_db.room_number,
        'room': room_obj,
        'total_beds': total_beds,
        'occupied_beds': occupied_count,
        'vacant_beds': vacant_count,
        'beds': hydrated_beds,
    }
    return render(request, 'room/student_allocated_view.html', context)


# ── AJAX Endpoints ──
@login_required(login_url='/authentication/login')
def check_room_number(request):
    number = request.GET.get('number', '').strip()
    building_id = request.GET.get('building_id')
    room_id = request.GET.get('room_id')

    if not number:
        return JsonResponse({'available': True, 'message': 'Room number available'})

    qs = Room.objects.filter(room_number=number)
    if building_id:
        qs = qs.filter(building_id=building_id)
    if room_id and room_id.isdigit():
        qs = qs.exclude(pk=int(room_id))

    if qs.exists():
        return JsonResponse({'available': False, 'message': f'Room #{number} already exists.'})

    return JsonResponse({'available': True, 'message': f'Room #{number} is available.'})


@login_required(login_url='/authentication/login')
def get_floors(request):
    building_id = request.GET.get('building_id')
    if not building_id or not str(building_id).isdigit():
        return JsonResponse({
            'floors': [],
            'blocks': [],
            'gender': '',
            'total_floors': 0
        })

    b_info = HostelBuilding.objects.filter(pk=int(building_id)).first()
    if not b_info:
        return JsonResponse({
            'floors': [],
            'blocks': [],
            'gender': '',
            'total_floors': 0
        })

    total_floors = b_info.total_floors
    gender = b_info.gender

    floors = []
    for fl in range(1, total_floors + 1):
        if fl == 1:
            lbl = "1st Floor (Ground)"
        elif fl == 2:
            lbl = "2nd Floor"
        elif fl == 3:
            lbl = "3rd Floor"
        else:
            lbl = f"{fl}th Floor"
        floors.append({'id': fl, 'label': lbl})

    raw_blocks = [b.strip() for b in b_info.blocks.split(',') if b.strip()] if b_info.blocks else ['Block A']
    blocks = []
    for b in raw_blocks:
        b_code = b.replace('Block ', '').strip() if b.startswith('Block ') else b
        blocks.append({
            'id': b_code,
            'label': f"{b} ({gender} Wing)"
        })

    return JsonResponse({
        'floors': floors,
        'blocks': blocks,
        'gender': gender,
        'total_floors': total_floors
    })


@login_required(login_url='/authentication/login')
def rooms_by_building(request):
    return JsonResponse({'rooms': []})


@login_required(login_url='/authentication/login')
def get_rooms_for_allocation(request):
    building_id = request.GET.get('building_id')
    active_b_ids = set(HostelBuilding.objects.filter(is_active=True).values_list('id', flat=True))

    qs = Room.objects.filter(building_id__in=active_b_ids).prefetch_related('beds')
    if building_id:
        qs = qs.filter(building_id=building_id)

    res_rooms = []
    for r in qs:
        total_b = r.capacity
        occ_b = sum(1 for b in r.beds.all() if b.student)
        vacant_b = max(0, total_b - occ_b)
        res_rooms.append({
            'room_id': r.id,
            'room_number': r.room_number,
            'gender': r.gender,
            'gender_display': f"{r.gender} Wing",
            'vacant_beds': vacant_b,
            'capacity': total_b
        })

    return JsonResponse({'rooms': res_rooms})


@login_required(login_url='/authentication/login')
def get_beds_for_room(request):
    room_id = request.GET.get('room_id', '1')
    room_info = Room.objects.filter(pk=room_id).prefetch_related('beds', 'beds__student').first()

    beds_data = []
    if room_info:
        for b in room_info.beds.all():
            st_data = None
            if b.student:
                st_data = {
                    'id': b.student.student_id,
                    'name': b.student.name,
                    'roll': b.student.roll or f'{b.student.student_id}',
                    'photo': b.student.photo_url,
                }
            beds_data.append({
                'bed_number': b.bed_number,
                'student': st_data
            })
    else:
        beds_data = [
            {'bed_number': '1', 'student': None},
            {'bed_number': '2', 'student': None},
        ]

    return JsonResponse({
        'room_number': room_info.room_number if room_info else str(room_id),
        'gender_display': room_info.gender if room_info else 'Boys',
        'beds': beds_data
    })


@login_required(login_url='/authentication/login')
def get_students_by_gender(request):
    room_gender = request.GET.get('room_gender', '')
    gender = 'Male' if 'boy' in room_gender.lower() else 'Female'
    assigned_student_ids = Bed.objects.filter(student__isnull=False).values_list('student_id', flat=True)
    qs = Student.objects.filter(status='Active', gender=gender).exclude(student_id__in=assigned_student_ids)
    students_data = [
        {
            'id': s.student_id,
            'name': s.name,
            'roll': s.roll or f'STU{s.student_id}',
            'phone': s.phone_number or '',
            'photo': s.photo_url,
        }
        for s in qs
    ]
    return JsonResponse({'students': students_data})


@login_required(login_url='/authentication/login')
def search_unallocated_students(request):
    q = request.GET.get('q', '').strip()
    assigned_st_ids = Bed.objects.filter(student__isnull=False).values_list('student_id', flat=True)
    qs = Student.objects.filter(status='Active').exclude(student_id__in=assigned_st_ids)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(student_id__icontains=q) | Q(roll__icontains=q))

    students_data = [
        {
            'id': s.student_id,
            'name': s.name,
            'roll': s.roll or f'STU{s.student_id}',
            'phone': s.phone_number or '',
            'photo': s.photo_url,
        }
        for s in qs[:30]
    ]
    return JsonResponse({'students': students_data})


@login_required(login_url='/authentication/login')
def allocate_bed_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            bed_id = data.get('bed_id')
            student_id = data.get('student_id')

            bed_obj = Bed.objects.filter(pk=bed_id).first()
            st_obj = Student.objects.filter(student_id=student_id).first()

            if bed_obj and st_obj:
                existing_bed = Bed.objects.filter(student=st_obj).exclude(pk=bed_obj.pk).first()
                if existing_bed:
                    return JsonResponse({'status': 'error', 'message': f'{st_obj.name} is already allocated to Room {existing_bed.room.room_number} Bed {existing_bed.bed_number}. Each student can only be allocated to one bed.'}, status=400)
                bed_obj.student = st_obj
                bed_obj.save()
                messages.success(request, f"{st_obj.name} successfully allocated to Room {bed_obj.room.room_number} Bed {bed_obj.bed_number}.")
                return JsonResponse({'status': 'success', 'message': f'Allocated {st_obj.name} to Bed {bed_obj.bed_number}'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid bed or student specified.'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)
