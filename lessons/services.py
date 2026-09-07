"""Service helpers for lesson enrollments."""

from decimal import Decimal

from django.utils import timezone
from django.urls import reverse

from fees.paystack import issue_receipt
from notifications.utils import notify
from accounts.models import User
from .models import LessonEnrollment


def record_enrollment_payment(enrollment, amount, method, reference, description, recorded_by):
    """Record a confirmed payment for a lesson enrollment.

    Creates the ``Payment`` row, issues a receipt, notifies the student,
    and flips the enrollment status to ``PAID`` when fully settled.
    """
    payment = enrollment.payments.create(
        school=enrollment.school,
        student=enrollment.student,
        amount=amount,
        method=method,
        reference=reference,
        status='CONFIRMED',
        paid_on=timezone.now(),
        recorded_by=recorded_by,
        description=description,
    )

    issue_receipt(payment)

    student_user = User.objects.filter(pk=enrollment.student_id).first()
    if student_user and student_user.email:
        notify(
            recipient=student_user,
            channel='IN_APP',
            subject=f'Payment recorded: ₦{amount:,.2f}',
            message=f'Payment of ₦{amount:,.2f} recorded for {enrollment.child_name} ({enrollment.lesson_class}).',
            reference=f'lesson-payment:{payment.id}',
            url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
        )

    if enrollment.status == LessonEnrollment.Status.REGISTERED and enrollment.amount_paid >= enrollment.fee_amount:
        enrollment.status = LessonEnrollment.Status.PAID
        enrollment.save()

    return payment
