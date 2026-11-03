from django.test import TestCase
from .forms import StudentForm
from .models import Student
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
import base64


class StudentFormTests(TestCase):
    def test_dob_cannot_be_future(self):
        form = StudentForm(data={'email': 'a@b.com', 'dob': '2999-01-01'})
        self.assertFalse(form.is_valid())
        self.assertIn('dob', form.errors)

    def test_phone_format_invalid(self):
        form = StudentForm(data={'email': 'a@b.com', 'phone_number': '12345'})
        self.assertFalse(form.is_valid())
        self.assertIn('phone_number', form.errors)

    def test_phone_auto_prefix_91(self):
        form = StudentForm(data={'phone_number': '9327431562'})
        form.is_valid()
        self.assertEqual(form.cleaned_data.get('phone_number'), '+919327431562')

    def test_student_model_phone_save_normalization(self):
        student = Student.objects.create(
            name='Test Student',
            email='testphone@example.com',
            phone_number='9876543210',
            guardian_phone='09876543210'
        )
        self.assertEqual(student.phone_number, '+919876543210')
        self.assertEqual(student.guardian_phone, '+919876543210')

    def test_email_uniqueness(self):
        user = User.objects.create_user(username='x@x.com', password='pwd')
        Student.objects.create(user=user, email='x@x.com', name='X')
        form = StudentForm(data={'email': 'x@x.com'})
        self.assertFalse(form.is_valid())


class StudentPhotoStorageTests(TestCase):
    def setUp(self):
        # 1x1 transparent GIF bytes
        self.tiny_gif = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
            b'\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
            b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
        )

    def test_photo_upload_converts_to_base64_photo_data(self):
        uploaded = SimpleUploadedFile(
            name='avatar.gif',
            content=self.tiny_gif,
            content_type='image/gif'
        )
        student = Student.objects.create(
            name='Photo Student',
            email='photostudent@example.com',
            photo=uploaded
        )
        # photo_data must be populated automatically
        self.assertIsNotNone(student.photo_data)
        self.assertTrue(student.photo_data.startswith('data:image/'))
        self.assertIn('base64,', student.photo_data)
        # photo_url property returns the base64 data uri
        self.assertEqual(student.photo_url, student.photo_data)

    def test_serve_media_fallback_from_database(self):
        b64_str = f"data:image/gif;base64,{base64.b64encode(self.tiny_gif).decode('utf-8')}"
        student = Student.objects.create(
            name='Remote Serverless Student',
            email='remote@example.com',
            photo='student_photos/fake_missing_on_disk.gif',
            photo_data=b64_str
        )
        # Request /media/student_photos/fake_missing_on_disk.gif
        res = self.client.get('/media/student_photos/fake_missing_on_disk.gif')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'image/gif')
        self.assertEqual(res.content, self.tiny_gif)

    def test_serve_media_missing_fallback_redirects_to_default_avatar(self):
        # Non-existent photo should redirect to /static/image/User.jpg rather than 404
        res = self.client.get('/media/student_photos/completely_nonexistent.jpg')
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, '/static/image/User.jpg')
