from decimal import Decimal
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Add Pre-Nursery School Fees price for current term.'

    def handle(self, *args, **options):
        from fees.models import FeeCategory, FeePrice
        from students.models import SchoolClass
        from core.models import School, Term

        school = School.objects.first()
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if not current_term:
            self.stdout.write(self.style.ERROR('No current term found.'))
            return

        cat = FeeCategory.objects.filter(school=school, name='Pre-Nursery School Fees').first()
        if not cat:
            self.stdout.write(self.style.ERROR('Pre-Nursery School Fees category not found.'))
            return

        pre_nursery = SchoolClass.objects.filter(school=school, name='Pre-Nursery').first()
        if not pre_nursery:
            self.stdout.write(self.style.WARNING('Pre-Nursery class not found, skipping.'))
            return

        _, created = FeePrice.objects.get_or_create(
            school=school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=pre_nursery,
            term=current_term,
            category=cat,
            student_type='ALL',
            defaults={'amount': Decimal('20000.00')},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Pre-Nursery School Fees price: NGN 20,000.00 for {current_term.name}'))
        else:
            self.stdout.write('Pre-Nursery School Fees price already exists.')
