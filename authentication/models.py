from django.db import models

from django.contrib.auth.models import User, Group

from django.utils import timezone

from hms.utils import normalize_phone_number





class Module(models.Model):

    name = models.CharField(max_length=100, unique=True)

    code = models.SlugField(max_length=100, unique=True)  # e.g. 'student', 'room', 'leave'



    # Sidebar / navigation metadata

    menu_label = models.CharField(max_length=100, blank=True, help_text="Label shown in sidebar menu")

    icon = models.CharField(max_length=60, blank=True, help_text="Bootstrap icon class e.g. bi-people")

    url_name = models.CharField(max_length=100, blank=True, help_text="Django URL name for the module index page")

    order = models.PositiveSmallIntegerField(default=0, help_text="Sidebar display order (lower = higher)")

    parent_code = models.SlugField(max_length=100, blank=True, help_text="Parent module code for sub-menus")



    class Meta:

        ordering = ['order', 'name']



    def __str__(self):

        return self.name





class Role(models.Model):

    name = models.CharField(max_length=100, unique=True)

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    is_superadmin = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    def __str__(self):

        return self.name





class RolePermission(models.Model):

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')

    module = models.ForeignKey(Module, on_delete=models.CASCADE)



    can_view = models.BooleanField(default=False)

    can_add = models.BooleanField(default=False)

    can_edit = models.BooleanField(default=False)

    can_delete = models.BooleanField(default=False)

    can_approve = models.BooleanField(default=False)

    can_reject = models.BooleanField(default=False)

    can_export = models.BooleanField(default=False)

    can_print = models.BooleanField(default=False)

    can_import = models.BooleanField(default=False)

    can_hide = models.BooleanField(default=False)

    can_disable = models.BooleanField(default=False)



    class Meta:

        unique_together = ('role', 'module')



    def __str__(self):

        return f"{self.role.name} - {self.module.name}"





class UserProfile(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)



    hostel = models.ForeignKey(

        'authentication.Hostel', on_delete=models.SET_NULL,

        null=True, blank=True, related_name='user_profiles',

        help_text='Hostel scope for non-super-admin users'

    )



    # Extended fields for User Management

    phone = models.CharField(max_length=20, blank=True)

    photo = models.ImageField(upload_to='user_photos/', blank=True, null=True)

    photo_data = models.TextField(blank=True, null=True, help_text="Base64 Data URI for persistent serverless photo storage")

    is_locked = models.BooleanField(default=False)  # Locked accounts cannot log in



    @property

    def photo_url(self):

        try:

            val = getattr(self, 'photo_data', None)

            if val:

                return val

        except Exception:

            pass

        try:

            if self.photo and hasattr(self.photo, 'url'):

                return self.photo.url

        except Exception:

            pass

        return '/static/image/User.jpg'



    def __str__(self):

        return f"{self.user.username} - {self.role.name if self.role else 'No Role'}"



    def save(self, *args, **kwargs):

        if self.phone:

            try:

                self.phone = normalize_phone_number(self.phone)

            except Exception:

                pass

        super().save(*args, **kwargs)



    @property

    def display_name(self):

        full = self.user.get_full_name()

        return full if full else self.user.username





class WardenProfile(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='warden_profile')



    def __str__(self):

        return f"Warden: {self.user.username}"





class AuditLog(models.Model):

    """Records every significant administrative action for accountability."""



    ACTION_CHOICES = [

        ('create', 'User Created'),

        ('edit', 'User Edited'),

        ('delete', 'User Deleted'),

        ('activate', 'User Activated'),

        ('deactivate', 'User Deactivated'),

        ('lock', 'User Locked'),

        ('unlock', 'User Unlocked'),

        ('role_change', 'Role Changed'),

        ('password_reset', 'Password Reset'),

        ('export', 'Data Exported'),

        ('login', 'User Logged In'),

        ('logout', 'User Logged Out'),

        ('gate_pass', 'Gate Pass Action'),

    ]



    actor = models.ForeignKey(

        User, on_delete=models.SET_NULL, null=True,

        related_name='audit_actions', verbose_name='Performed By'

    )

    target_user = models.ForeignKey(

        User, on_delete=models.SET_NULL, null=True, blank=True,

        related_name='audit_records', verbose_name='Affected User'

    )



    hostel = models.ForeignKey(

        'authentication.Hostel', on_delete=models.SET_NULL,

        null=True, blank=True, related_name='audit_logs'

    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)

    details = models.TextField(blank=True)

    timestamp = models.DateTimeField(default=timezone.now)

    ip_address = models.GenericIPAddressField(null=True, blank=True)



    class Meta:

        ordering = ['-timestamp']



    def __str__(self):

        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.actor} → {self.action} on {self.target_user}"



class Notification(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')

    message = models.TextField()

    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ['-created_at']



    def __str__(self):

        return f"Notification for {self.user.username}: {self.message[:20]}"





class Hostel(models.Model):

    HOSTEL_TYPES = [

        ('Boys', 'Boys'),

        ('Girls', 'Girls'),

        ('Mixed', 'Mixed'),

    ]







    name = models.CharField(max_length=100, unique=True)

    code = models.CharField(max_length=20, unique=True, default='H01')

    hostel_type = models.CharField(max_length=10, choices=HOSTEL_TYPES, default='Mixed')

    address = models.TextField(blank=True)

    phone_number = models.CharField(max_length=20, blank=True)

    email = models.EmailField(blank=True)

    branding_logo = models.ImageField(upload_to='hostel_logos/', blank=True, null=True)

    hostel_image = models.ImageField(upload_to='hostel_images/', blank=True, null=True)

    description = models.TextField(blank=True)

    theme_color = models.CharField(max_length=7, default='#0d6efd', help_text="Hex color code")

    capacity = models.IntegerField(default=100)

    is_active = models.BooleanField(default=True)

    

    # Configurations

    separate_academic_year = models.BooleanField(default=False)

    separate_fee_structure = models.BooleanField(default=False)

    separate_staff_assignment = models.BooleanField(default=False)

    separate_inventory = models.BooleanField(default=False)

    separate_notifications = models.BooleanField(default=False)

    separate_visitor_policy = models.BooleanField(default=False)

    separate_leave_policy = models.BooleanField(default=False)

    separate_attendance_rules = models.BooleanField(default=False)



    created_at = models.DateTimeField(auto_now_add=True)



    def __str__(self):

        return f"{self.name} ({self.code})"



    def save(self, *args, **kwargs):

        if self.phone_number:

            try:

                self.phone_number = normalize_phone_number(self.phone_number)

            except Exception:

                pass

        super().save(*args, **kwargs)





class SystemSettings(models.Model):

    system_name = models.CharField(max_length=100, default='Apex Hostel')

    organization_name = models.CharField(max_length=150, default='Management System')

    logo = models.ImageField(upload_to='system_logos/', blank=True, null=True)

    favicon = models.ImageField(upload_to='system_favicons/', blank=True, null=True)

    logo_data = models.TextField(blank=True, null=True, help_text="Base64 Data URI for persistent serverless logo storage")

    favicon_data = models.TextField(blank=True, null=True, help_text="Base64 Data URI for persistent serverless favicon storage")

    theme_color = models.CharField(max_length=7, default='#6366f1', help_text="Hex color code")

    dark_mode_default = models.BooleanField(default=True)

    timezone = models.CharField(max_length=100, default='Asia/Kolkata')

    date_format = models.CharField(max_length=50, default='Y-m-d')

    time_format = models.CharField(max_length=50, default='H:i:s')

    currency = models.CharField(max_length=10, default='USD')

    language = models.CharField(max_length=10, default='en')

    maintenance_mode = models.BooleanField(default=False)

    system_version = models.CharField(max_length=20, default='1.0.0')

    license_key = models.TextField(blank=True)

    license_expiry = models.DateField(null=True, blank=True)



    # Security Settings

    session_timeout = models.IntegerField(default=1800, help_text="Session timeout in seconds")

    login_attempt_limit = models.IntegerField(default=5, help_text="Max login attempts before lockout")

    allowed_ips = models.TextField(blank=True, help_text="Allowed IP ranges/CSV list (blank to disable check)")

    enable_audit_logs = models.BooleanField(default=True, help_text="Toggle logging system events")

    password_expiry_days = models.IntegerField(default=90, help_text="Force password reset after X days (0 to disable)")

    backup_frequency = models.CharField(max_length=20, default='daily', help_text="Frequency of database backups")



    class Meta:

        verbose_name = "Global System Settings"

        verbose_name_plural = "Global System Settings"



    def save(self, *args, **kwargs):

        self.pk = 1

        super().save(*args, **kwargs)



    @classmethod

    def get_settings(cls):

        settings, created = cls.objects.get_or_create(pk=1)

        return settings



    @property

    def logo_url(self):

        """Return base64 data URI if stored, or a valid media URL only when the file
        physically exists on disk. Guards against broken URLs on serverless/ephemeral
        storage (e.g. Vercel) where /tmp/media is wiped on cold start."""

        import os as _os

        try:

            val = getattr(self, 'logo_data', None)

            if val:

                return val

        except Exception:

            pass

        try:

            if self.logo and hasattr(self.logo, 'url') and self.logo.name:

                from django.conf import settings as _djsettings

                file_path = _os.path.join(str(_djsettings.MEDIA_ROOT), str(self.logo.name))

                if _os.path.exists(file_path):

                    return self.logo.url

        except Exception:

            pass

        return None



    @property

    def favicon_url(self):

        """Return base64 data URI if stored, or a valid media URL only when the file
        physically exists on disk. Guards against broken URLs on serverless/ephemeral
        storage (e.g. Vercel) where /tmp/media is wiped on cold start."""

        import os as _os

        try:

            val = getattr(self, 'favicon_data', None)

            if val:

                return val

        except Exception:

            pass

        try:

            if self.favicon and hasattr(self.favicon, 'url') and self.favicon.name:

                from django.conf import settings as _djsettings

                file_path = _os.path.join(str(_djsettings.MEDIA_ROOT), str(self.favicon.name))

                if _os.path.exists(file_path):

                    return self.favicon.url

        except Exception:

            pass

        return None





class PermissionElement(models.Model):

    CATEGORY_CHOICES = [

        ('page', 'Page / View'),

        ('button', 'Button / CTA'),

        ('item', 'Minor UI Item / Section'),

        ('api', 'API Endpoint / Action'),

    ]

    code = models.SlugField(max_length=100, unique=True, help_text="Unique permission code e.g. btn_create_room")

    name = models.CharField(max_length=150, help_text="Human readable name e.g. New Room Button")

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='button')

    description = models.TextField(blank=True, help_text="What this permission controls")

    module = models.ForeignKey('Module', on_delete=models.SET_NULL, null=True, blank=True, related_name='elements')



    def __str__(self):

        return f"{self.get_category_display()} - {self.name} ({self.code})"





class RoleElementPermission(models.Model):

    role = models.ForeignKey('Role', on_delete=models.CASCADE, related_name='element_permissions')

    element = models.ForeignKey(PermissionElement, on_delete=models.CASCADE, related_name='role_permissions')

    is_enabled = models.BooleanField(default=False)



    class Meta:

        unique_together = ('role', 'element')



    def __str__(self):

        return f"{self.role.name} -> {self.element.code}: {self.is_enabled}"





def get_or_create_student_role():

    """

    Checks if a Role with name 'Student' exists.

    If not found, creates it automatically with active status and default module permissions.

    Returns the Student Role instance.

    """

    role = Role.objects.filter(name='Student').first()

    if not role:

        role = Role.objects.create(

            name='Student',

            description='Default Student Role with access to personal dashboard and leave requests.',

            is_active=True,

            is_superadmin=False

        )

        student_module = Module.objects.filter(code='student').first()

        leave_module = Module.objects.filter(code='leave').first()

        

        if student_module:

            RolePermission.objects.get_or_create(

                role=role,

                module=student_module,

                defaults={'can_view': True}

            )

        if leave_module:

            RolePermission.objects.get_or_create(

                role=role,

                module=leave_module,

                defaults={'can_view': True, 'can_add': True, 'can_edit': True}

            )

    return role





