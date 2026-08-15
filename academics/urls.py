from django.urls import path

from academics.views import (
    TeacherAssignmentListView,
    TeacherAssignmentsView,
    TeacherScoreGridView,
    TeacherScoreUpdateView,
)

urlpatterns = [
    path('', TeacherAssignmentListView.as_view(), name='assignment_list'),
    path('assignments/', TeacherAssignmentsView.as_view(), name='teacher_assignments'),
    path('assignment/<int:pk>/scores/', TeacherScoreGridView.as_view(), name='score_grid'),
    path('assignment/<int:pk>/score/<int:score_pk>/', TeacherScoreUpdateView.as_view(), name='score_update'),
]
