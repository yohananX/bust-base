from students.models import Student, ClassEnrollment
from fees.models import Invoice, Payment
from core.models import Term

school_name = 'Grace House International School'
term = Term.objects.filter(school__name=school_name, is_current=True).first()

for s in Student.objects.filter(school__name=school_name):
    inv = Invoice.objects.filter(school__name=school_name, student=s, term=term).first()
    if inv:
        has_payments = Payment.objects.filter(invoice=inv).exists()
        enrollment = ClassEnrollment.objects.filter(student=s, is_current=True).first()
        class_name = enrollment.school_class.name if enrollment else 'N/A'
        print(f'{s.user.get_full_name()}: class={class_name}, total={inv.total_amount}, balance={inv.balance}, has_payments={has_payments}')
    else:
        print(f'{s.user.get_full_name()}: NO INVOICE')
