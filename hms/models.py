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
    SCOPE_CHOICES = [
        ('OWN', 'Own Records Only'),
        ('LOCATION', 'Assigned Location (Block / Floor / Room / Post)'),
        ('BUILDING', 'Assigned Building'),
        ('ORGANIZATION', 'Entire Organization'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, default='Custom Duty')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    data_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='BUILDING', help_text="Data access boundary")
    requires_approval = models.BooleanField(default=False, help_text="Require supervisor signoff before duty activation")
    working_days = models.CharField(max_length=50, default='MON,TUE,WED,THU,FRI,SAT,SUN', help_text="Comma-separated active days")
    privilege_ceiling_role = models.ForeignKey('authentication.Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='duty_ceilings', help_text="Privilege ceiling boundary")
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

    @property
    def working_days_list(self):
        if not self.working_days:
            return []
        return [d.strip().upper() for d in self.working_days.split(',') if d.strip()]


class DutyPermission(models.Model):
    duty = models.ForeignKey(Duty, on_delete=models.CASCADE, related_name='permissions')
    module_name = models.CharField(max_length=50) # e.g. leave, student, attendance, room, complaint, fee, visitor, duty_management
    can_view = models.BooleanField(default=False)
    can_add = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    can_reject = models.BooleanField(default=False)
    can_verify = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    can_print = models.BooleanField(default=False)
    can_download = models.BooleanField(default=False)
    can_assign = models.BooleanField(default=False)

    class Meta:
        db_table = 'duty_permissions'
        unique_together = ('duty', 'module_name')

    def __str__(self):
        return f"{self.duty.name} - {self.module_name}"


class DutyAssignment(models.Model):
    ASSIGNMENT_STATUS = [
        ('DRAFT', 'Draft'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('ACTIVE', 'Active / Ongoing'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed'),
        ('EXPIRED', 'Expired'),
        ('REVOKED', 'Emergency Revoked'),
    ]

    duty = models.ForeignKey(Duty, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments')
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='duties')
    duty_title = models.CharField(max_length=100, help_text="e.g. Floor Supervisor, Guard, Kitchen Help")
    
    # Hierarchical Location Scoping
    hostel = models.ForeignKey('authentication.Hostel', on_delete=models.SET_NULL, null=True, blank=True, related_name='duty_assignments')
    building = models.ForeignKey('room.HostelBuilding', on_delete=models.SET_NULL, null=True, blank=True, related_name='duty_assignments')
    block = models.CharField(max_length=50, blank=True, null=True)
    floor = models.IntegerField(null=True, blank=True)
    room = models.ForeignKey('room.Room', on_delete=models.SET_NULL, null=True, blank=True, related_name='duty_assignments')
    specific_location = models.CharField(max_length=150, blank=True, help_text="e.g. Main Gate 1, Kitchen, Mess hall")
    
    # Temporal Scheduling
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    shift_start = models.TimeField(null=True, blank=True)
    shift_end = models.TimeField(null=True, blank=True)
    working_days = models.CharField(max_length=50, default='MON,TUE,WED,THU,FRI,SAT,SUN')
    
    # Workflow & Approvals
    status = models.CharField(max_length=20, choices=ASSIGNMENT_STATUS, default='ACTIVE')
    supervisor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='supervised_duties')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_duties')
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True)
    
    # Emergency Handover
    handover_from = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='handed_over_duties')
    handover_to = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_handover_duties')
    handover_at = models.DateTimeField(null=True, blank=True)
    handover_reason = models.TextField(blank=True)
    
    # Emergency Killswitch / Revocation
    revoked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='revoked_duties')
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(blank=True)

    description = models.TextField(blank=True, help_text="Specific instructions or notes")
    assigned_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'duty_assignment'
        ordering = ['-assigned_date', 'staff__name']

    def __str__(self):
        dest = f" ({self.specific_location})" if self.specific_location else ""
        return f"{self.staff.name} - {self.duty_title}{dest or ' General'}"

    @property
    def working_days_list(self):
        if not self.working_days:
            return []
        return [d.strip().upper() for d in self.working_days.split(',') if d.strip()]

    @property
    def location_display(self):
        parts = []
        if self.building:
            parts.append(self.building.name)
        if self.block:
            parts.append(f"Block {self.block}")
        if self.floor is not None:
            parts.append(f"Floor {self.floor}")
        if self.room:
            parts.append(f"Room {self.room.room_number}")
        if self.specific_location:
            parts.append(f"({self.specific_location})")
        return " · ".join(parts) if parts else "Organization Campus"

    @property
    def is_currently_on_shift(self):
        """Returns True if the assignment is approved/active and current time is within shift window."""
        if not self.is_active or self.status not in ('ACTIVE', 'APPROVED'):
            return False
        now_dt = timezone.localtime(timezone.now())
        today = now_dt.date()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        
        # Check active day of week
        weekday_map = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
        current_day = weekday_map.get(today.weekday())
        if self.working_days_list and current_day not in self.working_days_list:
            return False

        # If shift timings are defined, check within slot (with 15 min grace period)
        if self.shift_start and self.shift_end:
            now_time = now_dt.time()
            if self.shift_start <= self.shift_end:
                return self.shift_start <= now_time <= self.shift_end
            else:
                return now_time >= self.shift_start or now_time <= self.shift_end
        return True


class DutyApprovalLog(models.Model):
    ACTION_CHOICES = [
        ('CREATED', 'Assignment Created'),
        ('SUBMITTED', 'Submitted for Approval'),
        ('APPROVED', 'Assignment Approved'),
        ('REJECTED', 'Assignment Rejected'),
        ('HANDOVER', 'Duty Handed Over'),
        ('REVOKED', 'Duty Revoked'),
        ('EXPIRED', 'Duty Expired'),
    ]
    assignment = models.ForeignKey(DutyAssignment, on_delete=models.CASCADE, related_name='approval_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    performed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-performed_at']

    def __str__(self):
        return f"{self.assignment.duty_title} - {self.action} by {self.performed_by or 'System'}"
