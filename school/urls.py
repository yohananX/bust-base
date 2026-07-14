import school.admin_setup  # noqa: applies admin ordering and model hiding

"""
URL configuration for school project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
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
