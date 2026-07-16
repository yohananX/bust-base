from django.urls import path

from . import views

urlpatterns = [
    path('', views.ParentChildrenListView.as_view(), name='parent-children'),
    path('child/<int:pk>/', views.ParentChildDetailView.as_view(), name='parent-child-detail'),
    path('child/<int:child_pk>/results/<int:term_id>/', views.ParentChildResultBookletView.as_view(), name='parent-child-result-booklet'),
    path('child/<int:child_pk>/results/<int:term_id>/download/', views.ParentChildResultDownloadView.as_view(), name='parent-child-result-download'),
]
