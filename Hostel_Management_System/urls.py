from django.contrib import admin
from django.urls import path , include, re_path
from django.views.generic import TemplateView
from authentication.views import secure_admin_access_view, system_health_endpoint
from authentication.media_serve import serve_media

urlpatterns = [
    path('system-control/secure-access/', secure_admin_access_view, name='secure_admin_access'),
    path('system-control/health/', system_health_endpoint, name='system_health_endpoint'),
    path('' , include('hms.urls')),
    path('student/',include('student.urls')),
    path('room/', include('room.urls')),
    path('authentication/',include('authentication.urls')),
    path('leave/', include('leave.urls')),
    path('student_app/', include('student_app.urls')),
    path('warden/', include('warden.urls')),
    
    path('admin/', admin.site.urls),

    path('manifest.json', TemplateView.as_view(template_name='manifest.json', content_type='application/json'), name='manifest_json'),
    path('service-worker.js', TemplateView.as_view(template_name='service-worker.js', content_type='application/javascript'), name='service_worker_js'),
    
    # Persistent media routing (serves from disk or PostgreSQL Base64 fallback)
    re_path(r'^media/(?P<path>.*)$', serve_media, name='serve_media'),
]
