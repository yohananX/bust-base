from django.urls import path

from . import views

urlpatterns = [
    path('', views.ParentChildrenListView.as_view(), name='parent-children'),
    path('child/<int:pk>/', views.ParentChildDetailView.as_view(), name='parent-child-detail'),
]
