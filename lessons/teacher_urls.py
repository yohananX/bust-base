from django.urls import path

from . import teacher_views

app_name = 'lessons_teacher'

urlpatterns = [
    path('', teacher_views.TeacherClassListView.as_view(), name='class_list'),
    path('class/<int:pk>/', teacher_views.TeacherClassDetailView.as_view(), name='class_detail'),
]