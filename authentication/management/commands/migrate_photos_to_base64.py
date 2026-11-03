import os
import base64
import mimetypes
from django.core.management.base import BaseCommand
from django.conf import settings
from student.models import Student
from authentication.models import UserProfile


class Command(BaseCommand):
    help = "Migrate existing disk-based Student and UserProfile photos to persistent Base64 in PostgreSQL."

    def handle(self, *args, **options):
        self.stdout.write("Starting photo migration to Base64 in PostgreSQL...")
        media_root = str(settings.MEDIA_ROOT)
        migrated_students = 0
        migrated_users = 0

        # Migrate Student photos
        for student in Student.objects.filter(photo_data__isnull=True).exclude(photo=''):
            if student.photo and hasattr(student.photo, 'name') and student.photo.name:
                disk_path = os.path.join(media_root, str(student.photo.name))
                if os.path.exists(disk_path):
                    try:
                        with open(disk_path, 'rb') as f:
                            raw = f.read()
                        if raw:
                            mime, _ = mimetypes.guess_type(student.photo.name)
                            mime = mime or 'image/jpeg'
                            b64 = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                            student.photo_data = b64
                            student.save(update_fields=['photo_data'])
                            migrated_students += 1
                            self.stdout.write(self.style.SUCCESS(f"Migrated Student photo: {student.name} ({student.roll})"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Could not convert student {student.name}: {e}"))

        # Migrate UserProfile photos
        for profile in UserProfile.objects.filter(photo_data__isnull=True).exclude(photo=''):
            if profile.photo and hasattr(profile.photo, 'name') and profile.photo.name:
                disk_path = os.path.join(media_root, str(profile.photo.name))
                if os.path.exists(disk_path):
                    try:
                        with open(disk_path, 'rb') as f:
                            raw = f.read()
                        if raw:
                            mime, _ = mimetypes.guess_type(profile.photo.name)
                            mime = mime or 'image/jpeg'
                            b64 = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                            profile.photo_data = b64
                            profile.save(update_fields=['photo_data'])
                            migrated_users += 1
                            self.stdout.write(self.style.SUCCESS(f"Migrated UserProfile photo: {profile.user.username}"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Could not convert user {profile.user.username}: {e}"))

        # Migrate SystemSettings logo & favicon
        from authentication.models import SystemSettings
        sys_settings = SystemSettings.objects.first()
        if sys_settings:
            if not sys_settings.logo_data and sys_settings.logo and hasattr(sys_settings.logo, 'name') and sys_settings.logo.name:
                disk_path = os.path.join(media_root, str(sys_settings.logo.name))
                if os.path.exists(disk_path):
                    try:
                        with open(disk_path, 'rb') as f:
                            raw = f.read()
                        if raw:
                            mime, _ = mimetypes.guess_type(sys_settings.logo.name)
                            mime = mime or 'image/png'
                            sys_settings.logo_data = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                            sys_settings.save(update_fields=['logo_data'])
                            self.stdout.write(self.style.SUCCESS("Migrated SystemSettings logo to Base64"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Could not convert system logo: {e}"))

            if not sys_settings.favicon_data and sys_settings.favicon and hasattr(sys_settings.favicon, 'name') and sys_settings.favicon.name:
                disk_path = os.path.join(media_root, str(sys_settings.favicon.name))
                if os.path.exists(disk_path):
                    try:
                        with open(disk_path, 'rb') as f:
                            raw = f.read()
                        if raw:
                            mime, _ = mimetypes.guess_type(sys_settings.favicon.name)
                            mime = mime or 'image/png'
                            sys_settings.favicon_data = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
                            sys_settings.save(update_fields=['favicon_data'])
                            self.stdout.write(self.style.SUCCESS("Migrated SystemSettings favicon to Base64"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Could not convert system favicon: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Photo migration complete! Students migrated: {migrated_students}, Users migrated: {migrated_users}."
        ))

