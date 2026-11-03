import datetime
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from hms.utils import normalize_phone_number
GENDER_CHOICES = [
    ('Male', 'Male'),
    ('Female', 'Female'),
    ('Other', 'Other'),
]

STATE_CHOICES = [
    ('Andhra Pradesh', 'Andhra Pradesh'),
    ('Arunachal Pradesh', 'Arunachal Pradesh'),
    ('Assam', 'Assam'),
    ('Bihar', 'Bihar'),
    ('Chhattisgarh', 'Chhattisgarh'),
    ('Goa', 'Goa'),
    ('Gujarat', 'Gujarat'),
    ('Haryana', 'Haryana'),
    ('Himachal Pradesh', 'Himachal Pradesh'),
    ('Jammu and Kashmir', 'Jammu and Kashmir'),
    ('Jharkhand', 'Jharkhand'),
    ('Karnataka', 'Karnataka'),
    ('Kerala', 'Kerala'),
    ('Madhya Pradesh', 'Madhya Pradesh'),
    ('Maharashtra', 'Maharashtra'),
    ('Manipur', 'Manipur'),
    ('Meghalaya', 'Meghalaya'),
    ('Mizoram', 'Mizoram'),
    ('Nagaland', 'Nagaland'),
    ('Odisha', 'Odisha'),
    ('Punjab', 'Punjab'),
    ('Rajasthan', 'Rajasthan'),
    ('Sikkim', 'Sikkim'),
    ('Tamil Nadu', 'Tamil Nadu'),
    ('Telangana', 'Telangana'),
    ('Tripura', 'Tripura'),
    ('Uttar Pradesh', 'Uttar Pradesh'),
    ('Uttarakhand', 'Uttarakhand'),
    ('West Bengal', 'West Bengal'),
    ('Andaman and Nicobar Islands', 'Andaman and Nicobar Islands'),
    ('Chandigarh', 'Chandigarh'),
    ('Dadra and Nagar Haveli', 'Dadra and Nagar Haveli'),
    ('Daman and Diu', 'Daman and Diu'),
    ('Delhi', 'Delhi'),
    ('Lakshadweep', 'Lakshadweep'),
    ('Puducherry', 'Puducherry'),
    ('California', 'California'),
    ('Texas', 'Texas'),
    ('New York', 'New York'),
]

CITY_CHOICES = [
    ('Hyderabad', 'Hyderabad'),
    ('Ahmedabad', 'Ahmedabad'),
    ('Surat', 'Surat'),
    ('Vadodara', 'Vadodara'),
    ('Rajkot', 'Rajkot'),
    ('Bhavnagar', 'Bhavnagar'),
    ('Junagadh', 'Junagadh'),
    ('Jamnagar', 'Jamnagar'),
    ('Gandhinagar', 'Gandhinagar'),
    ('Navsari', 'Navsari'),
    ('Anand', 'Anand'),
    ('Bhuj', 'Bhuj'),
    ('Valsad', 'Valsad'),
    ('Bharuch', 'Bharuch'),
    ('Palanpur', 'Palanpur'),
    ('Porbandar', 'Porbandar'),
    ('Nadiad', 'Nadiad'),
    ('Mehsana', 'Mehsana'),
    ('Surendranagar', 'Surendranagar'),
    ('Virpur', 'Virpur'),
    ('Vapi', 'Vapi'),
    ('Los Angeles', 'Los Angeles'),
    ('New York City', 'New York City'),
]

DEPARTMENT_CHOICES = [
    ('CSE', 'Computer Science and Engineering'),
    ('ECE', 'Electronics and Communication Engineering'),
    ('EEE', 'Electrical and Electronics Engineering'),
    ('ME', 'Mechanical Engineering'),
    ('CE', 'Civil Engineering'),
    ('CHE', 'Chemical Engineering'),
    ('BIO', 'Biotechnology'),
    ('AE', 'Aerospace Engineering'),
    ('IT', 'Information Technology'),
    ('EE', 'Electrical Engineering'),
    ('ARCH', 'Architecture'),
    ('BBA', 'Business Administration'),
    ('MBA', 'Master of Business Administration'),
    ('BSC', 'Bachelor of Science'),
    ('MSC', 'Master of Science'),
    ('PHYS', 'Physics'),
    ('CHEM', 'Chemistry'),
    ('MATH', 'Mathematics'),
    ('BIO', 'Biology'),
    ('ENV', 'Environmental Science'),
    ('LAW', 'Law'),
    ('MED', 'Medicine'),
    ('PHARMA', 'Pharmacy'),
    ('DENT', 'Dentistry'),
    ('NURS', 'Nursing'),
    ('PSY', 'Psychology'),
    ('SOC', 'Sociology'),
    ('ECON', 'Economics'),
    ('ENG', 'English Literature'),
    ('HIST', 'History'),
    ('GEO', 'Geography'),
    ('POLSCI', 'Political Science'),
    ('EDU', 'Education'),
    ('ART', 'Fine Arts'),
    ('MUS', 'Music'),
    ('DANCE', 'Dance'),
    ('THEA', 'Theatre Arts'),
    ('PHIL', 'Philosophy'),
    ('LING', 'Linguistics'),
    ('STAT', 'Statistics'),
    ('ANTH', 'Anthropology'),
    ('JMC', 'Journalism and Mass Communication'),
    ('FASH', 'Fashion Design'),
    ('TOUR', 'Tourism Management'),
    ('HM', 'Hotel Management'),
    ('AGRI', 'Agriculture'),
    ('VET', 'Veterinary Science'),
    ('FORE', 'Forestry'),
    ('HORT', 'Horticulture'),
    ('FISH', 'Fisheries Science'),
    ('ANIM', 'Animal Husbandry'),
    ('RURDEV', 'Rural Development'),
    ('CS', 'Computer Science'),
    ('ENG', 'Engineering'),
]

COURSE_CHOICES = [
    ('B.Tech', 'B.Tech'),
    ('M.Tech', 'M.Tech'),
    ('BA', 'Bachelor of Arts'),
    ('MA', 'Master of Arts'),
    ('BSc', 'Bachelor of Science'),
    ('MSC', 'Master of Science'),
    ('BCA', 'Bachelor of Computer Applications'),
    ('MCA', 'Master of Computer Applications'),
    ('BBA', 'Bachelor of Business Administration'),
    ('MBA', 'Master of Business Administration'),
    ('PhD', 'Doctor of Philosophy'),
    ('BCom', 'Bachelor of Commerce'),
    ('MCom', 'Master of Commerce'),
    ('BBA LLB', 'Bachelor of Business Administration and Bachelor of Laws'),
    ('BSc Nursing', 'Bachelor of Science in Nursing'),
    ('GNM', 'General Nursing and Midwifery'),
    ('BHMS', 'Bachelor of Homeopathic Medicine and Surgery'),
    ('BAMS', 'Bachelor of Ayurvedic Medicine and Surgery'),
    ('CS101', 'Intro to Computer Science'),
    ('ENG101', 'Intro to Engineering'),
]

SEM_CHOICES = [
    ('1', '1st'), ('2', '2nd'), ('3', '3rd'), ('4', '4th'), ('5', '5th'), ('6', '6th'),
]

BLOOD_GROUP_CHOICES = [
    ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
    ('O+', 'O+'), ('O-', 'O-'), ('AB+', 'AB+'), ('AB-', 'AB-'),
]

CATEGORY_CHOICES = [
    ('General', 'General'), ('OBC', 'OBC'), ('SC', 'SC'), ('ST', 'ST'), ('EWS', 'EWS'),
]

NATIONALITY_CHOICES = [
    ('Indian', 'Indian'), ('Other', 'Other'),
]

DIVISION_CHOICES = [
    ('A', 'Division A'), ('B', 'Division B'), ('C', 'Division C'), ('D', 'Division D'),
]

STATUS_CHOICES = [
    ('Active', 'Active'), ('Pending', 'Pending'), ('Inactive', 'Inactive'), ('On Leave', 'On Leave'),
]

class Student(models.Model):
    GENDER_CHOICES = GENDER_CHOICES
    STATE_CHOICES = STATE_CHOICES
    CITY_CHOICES = CITY_CHOICES
    DEPARTMENT_CHOICES = DEPARTMENT_CHOICES
    COURSE_CHOICES = COURSE_CHOICES
    SEM_CHOICES = SEM_CHOICES
    BLOOD_GROUP_CHOICES = BLOOD_GROUP_CHOICES
    CATEGORY_CHOICES = CATEGORY_CHOICES
    NATIONALITY_CHOICES = NATIONALITY_CHOICES
    DIVISION_CHOICES = DIVISION_CHOICES
    STATUS_CHOICES = STATUS_CHOICES

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    hostel = models.ForeignKey('authentication.Hostel', on_delete=models.CASCADE, related_name='students', null=True, blank=True)

    student_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    roll = models.CharField(max_length=50, blank=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    dob = models.DateField(blank=True, null=True)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    nationality = models.CharField(max_length=50, choices=NATIONALITY_CHOICES, default='Indian')
    photo = models.ImageField(upload_to='student_photos/', blank=True, null=True)
    photo_data = models.TextField(blank=True, null=True, help_text="Base64 Data URI for persistent serverless photo storage")

    @property
    def photo_url(self):
        try:
            val = getattr(self, 'photo_data', None)
            if val and len(val) > 20:
                return val
        except Exception:
            pass
        try:
            if self.photo and hasattr(self.photo, 'name') and self.photo.name:
                import os, base64, mimetypes
                from django.conf import settings
                full_path = os.path.join(str(settings.MEDIA_ROOT), str(self.photo.name))
                if os.path.exists(full_path):
                    try:
                        with open(full_path, 'rb') as f:
                            raw = f.read()
                        if raw:
                            mime, _ = mimetypes.guess_type(self.photo.name)
                            mime = mime or 'image/jpeg'
                            b64 = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                            self.photo_data = b64
                            Student.objects.filter(pk=self.pk).update(photo_data=b64)
                            return b64
                    except Exception:
                        pass
                if hasattr(self.photo, 'url'):
                    return self.photo.url
        except Exception:
            pass
        return '/static/image/User.jpg'

    # Parents Information
    father_name = models.CharField(max_length=100, blank=True, null=True)
    mother_name = models.CharField(max_length=100, blank=True, null=True)
    guardian_name = models.CharField(max_length=100, blank=True, null=True)
    guardian_phone = models.CharField(max_length=20, blank=True, null=True)
    guardian_occupation = models.CharField(max_length=100, blank=True, null=True)
    parent_email = models.EmailField(blank=True, null=True)

    # Academic Information
    course = models.CharField(max_length=50, choices=COURSE_CHOICES, blank=True)
    department = models.CharField(max_length=100, choices=DEPARTMENT_CHOICES, blank=True)
    semester = models.CharField(max_length=2, choices=SEM_CHOICES, blank=True)
    division = models.CharField(max_length=5, choices=DIVISION_CHOICES, blank=True)
    admission_date = models.DateField(blank=True, null=True)
    admission_number = models.CharField(max_length=50, blank=True)
    academic_year = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')

    # Address
    address = models.TextField(blank=True) # Address Line 1
    address_line_2 = models.TextField(blank=True)
    state = models.CharField(max_length=50, choices=STATE_CHOICES, blank=True)
    city = models.CharField(max_length=50, choices=CITY_CHOICES, blank=True)
    country = models.CharField(max_length=50, default='India', blank=True)
    pincode = models.CharField(max_length=10, blank=True)

    # Emergency Contact
    emergency_name = models.CharField(max_length=100, blank=True)
    emergency_relation = models.CharField(max_length=50, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    emergency_alt_phone = models.CharField(max_length=20, blank=True)

    create_at = models.DateTimeField(auto_now_add=True)
    update_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'student'

    def __str__(self):
        return f'{self.name} ({self.email})'

    def save(self, *args, **kwargs):
        if self.phone_number:
            try:
                self.phone_number = normalize_phone_number(self.phone_number)
            except Exception:
                pass
        if self.guardian_phone:
            try:
                self.guardian_phone = normalize_phone_number(self.guardian_phone)
            except Exception:
                pass
        if self.emergency_phone:
            try:
                self.emergency_phone = normalize_phone_number(self.emergency_phone)
            except Exception:
                pass
        if self.emergency_alt_phone:
            try:
                self.emergency_alt_phone = normalize_phone_number(self.emergency_alt_phone)
            except Exception:
                pass

        # Convert uploaded photo into persistent Base64 photo_data for PostgreSQL
        if self.photo:
            try:
                if hasattr(self.photo, 'file'):
                    import base64, mimetypes
                    file_obj = self.photo.file
                    file_obj.seek(0)
                    raw_bytes = file_obj.read()
                    file_obj.seek(0)
                    if raw_bytes:
                        mime_type, _ = mimetypes.guess_type(self.photo.name or '')
                        if not mime_type or not mime_type.startswith('image/'):
                            mime_type = 'image/jpeg'
                        b64_str = base64.b64encode(raw_bytes).decode('utf-8')
                        self.photo_data = f"data:{mime_type};base64,{b64_str}"
                elif not self.photo_data and hasattr(self.photo, 'name') and self.photo.name:
                    import os, base64, mimetypes
                    from django.conf import settings
                    full_path = os.path.join(str(settings.MEDIA_ROOT), str(self.photo.name))
                    if os.path.exists(full_path):
                        with open(full_path, 'rb') as f:
                            raw_bytes = f.read()
                        if raw_bytes:
                            mime, _ = mimetypes.guess_type(self.photo.name)
                            mime = mime or 'image/jpeg'
                            b64_str = base64.b64encode(raw_bytes).decode('utf-8')
                            self.photo_data = f"data:{mime};base64,{b64_str}"
            except Exception:
                pass

        try:
            super().save(*args, **kwargs)
        except (OSError, IOError):
            self.photo = None
            super().save(*args, **kwargs)

        # Sync photo_data to UserProfile if student is linked to a User
        if self.user and self.photo_data:
            try:
                from authentication.models import UserProfile
                profile, _ = UserProfile.objects.get_or_create(user=self.user)
                if profile.photo_data != self.photo_data:
                    profile.photo_data = self.photo_data
                    profile.save(update_fields=['photo_data'])
            except Exception:
                pass

    @property
    def enrollmentNumber(self):
        return self.roll

    @property
    def firstname(self):
        return (self.name or '').split(' ', 1)[0]

    @property
    def lastname(self):
        parts = (self.name or '').split(' ', 1)
        return parts[1] if len(parts) > 1 else ''

    @property
    def is_active(self):
        return self.status == 'Active'

    @property
    def bed_set(self):
        return self.allocated_beds

    def get_fee_info(self, academic_year=None):
        """
        Determines the applicable fee structure for the student based on:
        1. Explicit academic_year passed
        2. Student's academic_year field (e.g. '2026', '2027')
        3. Student's admission_date year (e.g. '2026', '2027')
        Returns dict with fee details or default zeroes.
        """
        target_year = academic_year or self.academic_year
        if not target_year and self.admission_date:
            target_year = str(self.admission_date.year)

        bed = self.allocated_beds.first()
        if bed and bed.room and bed.room.building:
            fee_obj = bed.room.building.get_current_fee(academic_year=target_year)
            if fee_obj:
                is_yearly = (fee_obj.fee_type == 'YEARLY_PER_STUDENT')
                amount = fee_obj.yearly_fee_per_student if is_yearly else fee_obj.monthly_fee_per_student
                if is_yearly:
                    monthly_val = (fee_obj.yearly_fee_per_student / Decimal('12.00')).quantize(Decimal('0.01')) if fee_obj.yearly_fee_per_student else Decimal('0.00')
                    yearly_val = fee_obj.yearly_fee_per_student
                else:
                    monthly_val = fee_obj.monthly_fee_per_student
                    yearly_val = fee_obj.monthly_fee_per_student * Decimal('12.00')
                return {
                    'fee_type': fee_obj.fee_type,
                    'fee_type_display': fee_obj.get_fee_type_display(),
                    'academic_year': fee_obj.academic_year,
                    'amount': amount,
                    'monthly_fee': monthly_val,
                    'yearly_fee': yearly_val,
                    'building_name': bed.room.building.name
                }

        return {
            'fee_type': 'MONTHLY_PER_STUDENT',
            'fee_type_display': 'Monthly – Per Student',
            'academic_year': target_year or '',
            'amount': Decimal('0.00'),
            'monthly_fee': Decimal('0.00'),
            'yearly_fee': Decimal('0.00'),
            'building_name': ''
        }

    def get_monthly_fee(self, academic_year=None):
        return self.get_fee_info(academic_year=academic_year)['monthly_fee']

    def get_yearly_fee(self, academic_year=None):
        return self.get_fee_info(academic_year=academic_year)['yearly_fee']

    def get_total_paid_fee(self):
        from django.db.models import Sum
        res = self.fee_payments.aggregate(total=Sum('amount_paid'))['total']
        return res if res is not None else Decimal('0.00')

    def get_calculated_fee_summary(self, target_building=None, academic_year=None):
        """
        Calculates Total Fee, Total Paid Fee, and Remaining Fee.
        If target_building is provided (e.g. during bed transfer), calculates the new building fee
        while carrying forward the student's previously paid fee balance.
        """
        target_year = academic_year or self.academic_year
        if not target_year and self.admission_date:
            target_year = str(self.admission_date.year)

        bed = self.allocated_beds.first()
        building_obj = target_building or (bed.room.building if (bed and bed.room and bed.room.building) else None)

        total_fee = Decimal('0.00')
        fee_type = 'MONTHLY_PER_STUDENT'
        fee_type_display = 'Monthly – Per Student'
        building_name = ''

        if building_obj:
            building_name = building_obj.name
            fee_obj = building_obj.get_current_fee(academic_year=target_year)
            if fee_obj:
                fee_type = fee_obj.fee_type
                fee_type_display = fee_obj.get_fee_type_display()
                total_fee = fee_obj.yearly_fee_per_student if fee_obj.fee_type == 'YEARLY_PER_STUDENT' else fee_obj.monthly_fee_per_student

        paid_fee = self.get_total_paid_fee()
        remaining_fee = max(Decimal('0.00'), total_fee - paid_fee)

        # Check for overdue installments & late fee penalties
        late_fee = Decimal('0.00')
        is_overdue = False
        today = timezone.now().date()

        if remaining_fee > Decimal('0.00'):
            # Fetch active installments
            active_installments = FeeInstallment.objects.filter(is_active=True).order_by('due_date')
            overdue_installments = [inst for inst in active_installments if today > inst.due_date]

            if overdue_installments:
                is_overdue = True
                # Query active penalty rules
                active_penalties = FeePenalty.objects.filter(is_active=True)
                for inst in overdue_installments:
                    for pen in active_penalties:
                        grace_date = inst.due_date + datetime.timedelta(days=pen.grace_period_days)
                        if today > grace_date:
                            days_late = (today - grace_date).days
                            if pen.penalty_type == 'PER_DAY':
                                late_fee += Decimal(str(pen.amount)) * Decimal(days_late)
                            elif pen.penalty_type == 'FIXED':
                                late_fee += Decimal(str(pen.amount))
                            elif pen.penalty_type == 'PERCENTAGE':
                                late_fee += (remaining_fee * Decimal(str(pen.amount))) / Decimal('100.00')

        total_fee += late_fee
        remaining_fee += late_fee

        if remaining_fee <= Decimal('0.00') and total_fee > Decimal('0.00'):
            status = 'PAID'
        elif is_overdue:
            status = 'OVERDUE'
        elif paid_fee > Decimal('0.00'):
            status = 'PARTIAL'
        else:
            status = 'DUE'

        return {
            'building_name': building_name,
            'academic_year': target_year or '',
            'fee_type': fee_type,
            'fee_type_display': fee_type_display,
            'total_fee': total_fee,
            'paid_fee': paid_fee,
            'remaining_fee': remaining_fee,
            'late_fee': late_fee,
            'status': status,
        }


class StudentFeePayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('CASH', 'Cash'),
        ('ONLINE', 'Online / UPI / NetBanking'),
        ('CHEQUE', 'Cheque / DD'),
        ('BANK_TRANSFER', 'Bank Transfer'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_payments')
    academic_year = models.CharField(max_length=20, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='ONLINE')
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'student_fee_payment'
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"{self.student.name} - ₹{self.amount_paid} ({self.payment_date})"


class Attendance(models.Model):
    ATTENDANCE_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Late', 'Late'),
        ('On Leave', 'On Leave'),
    ]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=ATTENDANCE_CHOICES, default='Present')
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.student.name} - {self.date} - {self.status}"


# Django Signals for lifecycle events
from django.db.models.signals import pre_delete, post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group

class FeeInstallment(models.Model):
    academic_year = models.CharField(max_length=20, default='2026')
    installment_name = models.CharField(max_length=100, help_text="e.g. Installment 1 / Semester 1 Fee")
    due_date = models.DateField()
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=50.00, help_text="Percentage of total fee due")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fee_installment'
        ordering = ['due_date']

    def __str__(self):
        return f"{self.installment_name} ({self.academic_year}) - Due: {self.due_date}"


class FeePenalty(models.Model):
    PENALTY_TYPE_CHOICES = [
        ('FIXED', 'Fixed One-Time Fee (₹)'),
        ('PER_DAY', 'Daily Recurring Late Fee (₹/day)'),
        ('PERCENTAGE', 'Percentage of Due Amount (%)'),
    ]

    title = models.CharField(max_length=100, help_text="e.g. Standard Late Payment Fine")
    penalty_type = models.CharField(max_length=20, choices=PENALTY_TYPE_CHOICES, default='PER_DAY')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    grace_period_days = models.IntegerField(default=5, help_text="Days after due date before penalty starts applying")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fee_penalty'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_penalty_type_display()} - ₹{self.amount})"


@receiver(pre_delete, sender=Student)
def deallocate_student_before_delete(sender, instance, **kwargs):
    from django.apps import apps
    try:
        Bed = apps.get_model('room', 'Bed')
        # Reset any beds assigned to this student
        Bed.objects.filter(student=instance).update(
            student=None
        )
    except LookupError:
        pass

@receiver(post_save, sender=Student)
def create_student_user_account(sender, instance, created, **kwargs):
    from authentication.models import Role, UserProfile

    if created:
        user = instance.user
        if not user:
            username = instance.roll.strip() if (instance.roll and instance.roll.strip()) else f"std_{instance.student_id}"
            email = instance.email
            
            # Ensure we don't crash on existing username or email
            if not User.objects.filter(username=username).exists():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password='User1234'
                )
                # Add to Students group
                group, _ = Group.objects.get_or_create(name='Students')
                user.groups.add(group)
                
                # Link back using update (to avoid post_save recursion)
                Student.objects.filter(pk=instance.pk).update(user=user)
                
        # Ensure the UserProfile with Student role exists for this user
        if user:
            from authentication.models import get_or_create_student_role
            student_role = get_or_create_student_role()
            profile, _ = UserProfile.objects.get_or_create(
                user=user,
                defaults={'role': student_role}
            )
            if not profile.role:
                profile.role = student_role
                profile.save()
