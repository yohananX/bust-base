from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('bell/count/', views.notification_bell_count, name='bell_count'),
    path('bell/dropdown/', views.notification_bell_dropdown, name='bell_dropdown'),
]
