from django.urls import path

from . import views

urlpatterns = [
    path('', views.StudentOverviewView.as_view(), name='student-overview'),
]
