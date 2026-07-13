from django.urls import path
from . import views
from .paystack import handle_webhook

app_name = 'fees'

urlpatterns = [
    path('api/paystack-webhook/', handle_webhook, name='paystack-webhook'),
    path('api/invoice/<int:invoice_id>/', views.invoice_detail, name='invoice-detail'),
    path('api/invoice/<int:invoice_id>/pay/', views.make_payment, name='make-payment'),
    path('api/invoice/<int:invoice_id>/cash/', views.record_cash_payment, name='record-cash'),
]
