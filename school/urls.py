"""
URL configuration for school project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView

urlpatterns = [
    path('admin/', RedirectView.as_view(url='/secure-control-panel/', permanent=False), name='admin_redirect'),
    path('secure-control-panel/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('teacher/', include('academics.urls')),
    path('parent/', include('students.urls')),
    path('student/', include('students.student_urls')),
    path('fees/', include('fees.urls')),
    path('payroll/', include('payroll.urls')),
    path('finance/', include('finance.urls')),
    path('notifications/', include('notifications.urls')),
    path('school-admin/', include('school_admin.urls')),
    path('', RedirectView.as_view(url='/accounts/redirect/', permanent=False), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
