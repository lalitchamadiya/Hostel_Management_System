import os
import base64
import mimetypes
from django.conf import settings
from django.http import HttpResponse, Http404
from django.shortcuts import redirect
from django.views.static import serve


def serve_media(request, path):
    """
    Robust media file server supporting both local disk and serverless PostgreSQL storage.
    If the requested file exists in MEDIA_ROOT, it is streamed from disk.
    If running on an ephemeral serverless filesystem (e.g. Vercel) where the local file
    was cleaned up, it retrieves the binary data from PostgreSQL (photo_data Base64)
    and streams it with proper MIME type and caching headers.
    """
    # 1. Try disk storage first
    try:
        full_path = os.path.join(str(settings.MEDIA_ROOT), path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return serve(request, path, document_root=settings.MEDIA_ROOT)
    except Exception:
        pass

    # 2. Try retrieving from PostgreSQL database
    filename = os.path.basename(path)
    if filename:
        # Check Student model
        try:
            from student.models import Student
            student = Student.objects.filter(photo__endswith=filename).first()
            if student and student.photo_data:
                data_uri = student.photo_data
                header, encoded = data_uri.split(',', 1) if ',' in data_uri else ('', data_uri)
                mime = 'image/jpeg'
                if 'image/' in header:
                    mime = header.split(';')[0].replace('data:', '')
                img_bytes = base64.b64decode(encoded)
                response = HttpResponse(img_bytes, content_type=mime)
                response['Cache-Control'] = 'public, max-age=86400'
                return response
        except Exception:
            pass

        # Check UserProfile model
        try:
            from authentication.models import UserProfile
            profile = UserProfile.objects.filter(photo__endswith=filename).first()
            if profile and profile.photo_data:
                data_uri = profile.photo_data
                header, encoded = data_uri.split(',', 1) if ',' in data_uri else ('', data_uri)
                mime = 'image/jpeg'
                if 'image/' in header:
                    mime = header.split(';')[0].replace('data:', '')
                img_bytes = base64.b64decode(encoded)
                response = HttpResponse(img_bytes, content_type=mime)
                response['Cache-Control'] = 'public, max-age=86400'
                return response
        except Exception:
            pass

        # Check SystemSettings model (system logo and favicon)
        try:
            from authentication.models import SystemSettings
            sys_settings = SystemSettings.objects.first()
            if sys_settings:
                data_uri = None
                if 'system_logos' in path or (sys_settings.logo and filename in str(sys_settings.logo)):
                    data_uri = sys_settings.logo_data
                elif 'system_favicons' in path or (sys_settings.favicon and filename in str(sys_settings.favicon)):
                    data_uri = sys_settings.favicon_data

                if data_uri:
                    header, encoded = data_uri.split(',', 1) if ',' in data_uri else ('', data_uri)
                    mime = 'image/png'
                    if 'image/' in header:
                        mime = header.split(';')[0].replace('data:', '')
                    img_bytes = base64.b64decode(encoded)
                    response = HttpResponse(img_bytes, content_type=mime)
                    response['Cache-Control'] = 'public, max-age=86400'
                    return response
        except Exception:
            pass

    # 3. Fallback for avatar / photos / logos: redirect to default assets rather than showing a broken image
    if 'student_photos' in path or 'user_photos' in path or 'avatar' in path:
        return redirect('/static/image/User.jpg')
    if 'system_logos' in path:
        return redirect('/static/image/logo.png')
    if 'system_favicons' in path:
        return redirect('/static/favicon.ico')

    # If it's another media file that doesn't exist, raise standard 404
    raise Http404(f"Media file '{path}' does not exist")

