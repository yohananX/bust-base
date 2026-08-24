"""
URL configuration for school project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic.base import RedirectView

from core.views import health

urlpatterns = [
    path('health/', health, name='health'),
    path('admin/', RedirectView.as_view(url='/secure-control-panel/', permanent=False), name='admin_redirect'),
    path('secure-control-panel/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('teacher/', include('academics.urls')),
    path('teacher/lessons/', include('lessons.teacher_urls')),
    path('parent/', include('students.urls')),
    path('student/', include('students.student_urls')),
    path('fees/', include('fees.urls')),
    path('payroll/', include('payroll.urls')),
    path('notifications/', include('notifications.urls')),
    path('school-admin/lessons/', include('lessons.urls')),
    path('school-admin/import/', include('data_import.urls')),
    path('school-admin/', include('school_admin.urls')),
    path('school-admin/', include('finance.urls')),
    path('', RedirectView.as_view(url='/accounts/redirect/', permanent=False), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Serve uploaded media (passports, logos) from the shared volume in production.
    # Adequate at school-system scale; swap for S3/CDN if traffic grows.
    from django.views.static import serve

    urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT})]
