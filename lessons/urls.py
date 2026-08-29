from django.urls import path

from . import views

app_name = 'lessons'

urlpatterns = [
    path('', views.PeriodListView.as_view(), name='period_list'),
    path('periods/new/', views.PeriodFormView.as_view(), name='period_new'),
    path('periods/<int:pk>/edit/', views.PeriodFormView.as_view(), name='period_form'),
    path('periods/<int:pk>/close/', views.PeriodCloseView.as_view(), name='period_close'),
    path('classes/', views.ClassListView.as_view(), name='class_list'),
    path('classes/new/', views.ClassFormView.as_view(), name='class_new'),
    path('classes/<int:pk>/edit/', views.ClassFormView.as_view(), name='class_form'),
    path('classes/<int:pk>/delete/', views.ClassDeleteView.as_view(), name='class_delete'),
    path('classes/<int:pk>/teachers/', views.ClassTeachersView.as_view(), name='class_teachers'),
    path('enrollments/', views.EnrollmentListView.as_view(), name='enrollment_list'),
    path('enrollments/new/', views.EnrollmentFormView.as_view(), name='enrollment_new'),
    path('enrollments/<int:pk>/', views.EnrollmentDetailView.as_view(), name='enrollment_detail'),
    path('enrollments/<int:pk>/edit/', views.EnrollmentFormView.as_view(), name='enrollment_form'),
    path('enrollments/<int:pk>/print/', views.EnrollmentPrintView.as_view(), name='enrollment_print'),
    path('enrollments/<int:pk>/cancel/', views.EnrollmentCancelView.as_view(), name='enrollment_cancel'),
    path('enrollments/<int:pk>/pay/', views.EnrollmentPaymentView.as_view(), name='enrollment_pay'),
    path('enrollments/<int:pk>/register/', views.EnrollmentRegisterStudentView.as_view(), name='enrollment_register_student'),
    path('enrollments/export/', views.EnrollmentExportView.as_view(), name='enrollment_export'),
]