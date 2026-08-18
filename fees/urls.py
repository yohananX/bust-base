from django.urls import path
from . import views
from .paystack import handle_webhook

app_name = 'fees'

urlpatterns = [
    path('api/paystack-webhook/', handle_webhook, name='paystack-webhook'),
    path('api/invoice/<int:invoice_id>/', views.invoice_detail, name='invoice-detail'),
    path('api/invoice/<int:invoice_id>/pay/', views.make_payment, name='make-payment'),
    path('api/invoice/<int:invoice_id>/cash/', views.record_cash_payment, name='record-cash'),
    path('api/invoice/<int:invoice_id>/status/', views.invoice_status_partial, name='invoice-status-partial'),
    path('pay/', views.InitiatePaymentView.as_view(), name='initiate-payment'),
    path('pay/<int:invoice_id>/', views.InitiatePaymentView.as_view(), name='initiate-payment'),
    path('return/', views.PaymentReturnView.as_view(), name='payment-return'),
    path('api/payment-status/', views.PaymentStatusPartialView.as_view(), name='payment-status-partial'),
    path('api/payment-timeout-help/', views.PaymentTimeoutHelpView.as_view(), name='payment-timeout-help'),
    path('api/payment-verify/', views.VerifyPaymentView.as_view(), name='payment-verify'),
    path('api/checkout/', views.CheckoutSubmitView.as_view(), name='checkout-submit'),
    path('api/checkout/continue/', views.CheckoutContinueView.as_view(), name='checkout-continue'),
    path('receipt/<int:payment_id>/', views.PaymentReceiptView.as_view(), name='payment-receipt'),
]
