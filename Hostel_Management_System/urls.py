from django.contrib import admin
from django.urls import path , include
from django.views.generic import TemplateView
from authentication.views import secure_admin_access_view, system_health_endpoint

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
]

from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
