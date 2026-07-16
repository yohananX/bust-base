from django.urls import path

from . import views

urlpatterns = [
    path('', views.StudentOverviewView.as_view(), name='student-overview'),
    path('results/', views.StudentResultsHistoryView.as_view(), name='student-results-history'),
    path('results/<int:term_id>/', views.StudentResultBookletView.as_view(), name='student-result-booklet'),
    path('results/<int:term_id>/download/', views.StudentResultDownloadView.as_view(), name='student-result-download'),
    path('password/', views.StudentSelfPasswordChangeView.as_view(), name='student-password-change'),
]
