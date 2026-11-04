from django.db import models
from django.contrib.auth.models import User
from student.models import Student
from django.utils import timezone
from hms.utils import normalize_phone_number

class StaffProfile(models.Model):
    DESIGNATION_CHOICES = [
        ('warden', 'Hostel Warden'),
        ('cleaner', 'Cleaning Staff'),
        ('chef', 'Kitchen Chef'),
        ('helpers', 'Kitchen Helper'),
        ('guard', 'Security Guard'),
        ('maintenance', 'Maintenance Technician'),
        ('admin', 'Admin Coordinator'),
    ]
    SHIFT_CHOICES = [
        ('morning', 'Morning Shift (6 AM - 2 PM)'),
        ('evening', 'Evening Shift (2 PM - 10 PM)'),
        ('night', 'Night Shift (10 PM - 6 AM)'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('on_leave', 'On Leave'),
    ]
    PERFORMANCE_CHOICES = [
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('average', 'Average'),
        ('needs_improvement', 'Needs Improvement'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_profile')
    hostel = models.ForeignKey('authentication.Hostel', on_delete=models.CASCADE, related_name='staff', null=True, blank=True)
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    designation = models.CharField(max_length=50, choices=DESIGNATION_CHOICES)
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    shift = models.CharField(max_length=20, choices=SHIFT_CHOICES, default='morning')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    performance = models.CharField(max_length=30, choices=PERFORMANCE_CHOICES, default='good')
    doj = models.DateField(default=timezone.now)
    documents = models.CharField(max_length=255, blank=True, help_text="List of submitted docs, e.g. Aadhar, Police verification")

    @property
    def assigned_role(self):
        """Returns the assigned System Role from linked user's profile."""
        if self.user and hasattr(self.user, 'profile') and self.user.profile and self.user.profile.role:
            return self.user.profile.role
        return None

    @property
    def has_valid_role(self):
        r = self.assigned_role
        return bool(r and r.is_active)

    @property
    def role_display_name(self):
        r = self.assigned_role
        if r:
            if not r.is_active:
                return "Role Missing – Reassignment Required"
            return r.name
        return "Role Missing – Reassignment Required"

    def get_designation_display(self):
        return self.role_display_name

    def __str__(self):
        return f"{self.name} - {self.role_display_name}"

    def save(self, *args, **kwargs):
        if self.phone:
            try:
                self.phone = normalize_phone_number(self.phone)
            except Exception:
                pass
        r = self.assigned_role
        if r:
            self.designation = r.name[:50]
        elif not self.designation:
            self.designation = "Role Missing – Reassignment Required"[:50]
        super().save(*args, **kwargs)



class ComplaintTicket(models.Model):
    CATEGORY_CHOICES = [
        ('room', 'Room Maintenance'),
        ('mess', 'Mess & Food'),
        ('electricity', 'Electricity & Power'),
        ('internet', 'Internet & Wi-Fi'),
        ('cleaning', 'Cleaning & Hygiene'),
        ('other', 'Other Issues'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Ticket'),
        ('assigned', 'Ticket Assigned'),
        ('in_progress', 'Resolution in Progress'),
        ('resolved', 'Resolved'),
    ]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='complaints')
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    assigned_to = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_complaints')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    feedback = models.TextField(blank=True, help_text="Feedback from the student after resolution")

    def __str__(self):
        return f"#{self.id or 'New'} - {self.title} ({self.get_status_display()})"


class Duty(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High/Critical'),
    ]
    REPEAT_CHOICES = [
        ('none', 'None'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, default='Custom Duty')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    repeat_type = models.CharField(max_length=20, choices=REPEAT_CHOICES, default='none')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name


class DutyPermission(models.Model):
    duty = models.ForeignKey(Duty, on_delete=models.CASCADE, related_name='permissions')
    module_name = models.CharField(max_length=50) # e.g. leave, students, fees, attendance
    can_view = models.BooleanField(default=False)
    can_add = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        db_table = 'duty_permissions'
        unique_together = ('duty', 'module_name')

    def __str__(self):
        return f"{self.duty.name} - {self.module_name}"


class DutyAssignment(models.Model):
    duty = models.ForeignKey(Duty, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments')
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='duties')
    duty_title = models.CharField(max_length=100, help_text="e.g. Floor Supervisor, Guard, Kitchen Help")
    specific_location = models.CharField(max_length=150, blank=True, help_text="e.g. Main Gate 1, Kitchen, Mess hall")
    shift_start = models.TimeField(null=True, blank=True)
    shift_end = models.TimeField(null=True, blank=True)
    description = models.TextField(blank=True, help_text="Specific instructions or notes")
    assigned_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'duty_assignment'
        ordering = ['-assigned_date', 'staff__name']

    def __str__(self):
        dest = f" ({self.specific_location})" if self.specific_location else ""
        return f"{self.staff.name} - {self.duty_title}{dest or ' General'}"


