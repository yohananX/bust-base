from django.urls import path

from . import views

urlpatterns = [
    path('', views.StudentOverviewView.as_view(), name='student-overview'),
    path('pay/', views.MakePaymentView.as_view(), name='student-pay'),
    path('results/', views.StudentResultsHistoryView.as_view(), name='student-results-history'),
    path('results/<int:term_id>/', views.StudentResultBookletView.as_view(), name='student-result-booklet'),
    path('subjects/', views.StudentSubjectsView.as_view(), name='student-subjects'),
    path('extra-lessons/', views.StudentExtraLessonsView.as_view(), name='student-extra-lessons'),
    path('password/', views.StudentSelfPasswordChangeView.as_view(), name='student-password-change'),
]
