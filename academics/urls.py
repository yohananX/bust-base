from django.urls import path
from django.views.generic.base import RedirectView

from academics.views import (
    TeacherAssignmentListView,
    TeacherScoreGridView,
    TeacherScoreUpdateView,
)

urlpatterns = [
    path('', TeacherAssignmentListView.as_view(), name='assignment_list'),
    path('assignments/', RedirectView.as_view(url='/teacher/', permanent=False), name='assignments_redirect'),
    path('assignment/<int:pk>/scores/', TeacherScoreGridView.as_view(), name='score_grid'),
    path('assignment/<int:pk>/score/<int:score_pk>/', TeacherScoreUpdateView.as_view(), name='score_update'),
]
