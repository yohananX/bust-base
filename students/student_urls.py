from django.urls import path

from . import views

urlpatterns = [
    path('', views.StudentOverviewView.as_view(), name='student-overview'),
    path('results/<int:term_id>/', views.StudentResultBookletView.as_view(), name='student-result-booklet'),
    path('results/<int:term_id>/download/', views.StudentResultDownloadView.as_view(), name='student-result-download'),
]
