from decimal import Decimal
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Debug fee pricing calculation for a student.'

    def add_arguments(self, parser):
        parser.add_argument('--student_id', type=int, default=None)
        parser.add_argument('--class_name', type=str, default='JSS1')

    def handle(self, *args, **options):
        from fees.models import FeePrice
        from students.models import Student, ClassEnrollment, SchoolClass
        from core.models import School, Term
        from fees.pricing import resolve_prices
        from fees.utils import resolve_student_type

        school = School.objects.first()
        current_term = Term.objects.filter(school=school, is_current=True).first()
        self.stdout.write(f'Current term: {current_term.name}')

        class_name = options['class_name']
        school_class = SchoolClass.objects.filter(school=school, name=class_name).first()
        if not school_class:
            self.stdout.write(self.style.ERROR(f'Class {class_name} not found'))
            return
        self.stdout.write(f'Class: {school_class.name} (level={school_class.level})')

        enrollments = ClassEnrollment.objects.filter(
            school=school, school_class=school_class, is_current=True
        )
        self.stdout.write(f'Students in {class_name}: {enrollments.count()}')

        # Show all prices that apply
        class_prices = FeePrice.objects.filter(
            school=school, scope='CLASS', school_class=school_class, term=current_term, is_active=True
        )
        self.stdout.write(f'\n{class_name} class-specific prices: {class_prices.count()}')
        for p in class_prices:
            self.stdout.write(f'  {p.category.name}: {p.amount}')

        sw_prices = FeePrice.objects.filter(school=school, scope='SCHOOL_WIDE', is_active=True)
        self.stdout.write(f'\nSchool-wide prices: {sw_prices.count()}')
        for p in sw_prices:
            self.stdout.write(f'  {p.category.name}: {p.amount} (term={p.term})')

        level_prices = FeePrice.objects.filter(
            school=school, scope='LEVEL', level=school_class.level, is_active=True
        )
        self.stdout.write(f'\n{school_class.level} level prices: {level_prices.count()}')
        for p in level_prices:
            self.stdout.write(f'  {p.category.name}: {p.amount}')

        # Resolve for a specific student
        if options['student_id']:
            stu = Student.objects.filter(school=school, pk=options['student_id']).first()
        else:
            stu = Student.objects.filter(
                school=school, enrollments__school_class=school_class, enrollments__is_current=True
            ).first()

        if stu:
            self.stdout.write(f'\n--- Resolving for: {stu} ---')
            student_type = resolve_student_type(stu, current_term.session)
            self.stdout.write(f'Student type: {student_type}')
            prices = resolve_prices(
                school, school_class, current_term,
                student_type=student_type, student=stu, session=current_term.session
            )
            total = Decimal('0.00')
            for p in prices:
                self.stdout.write(f'  {p.category.name}: {p.amount} (scope={p.scope})')
                total += p.amount
            self.stdout.write(self.style.SUCCESS(f'\nTOTAL: {total}'))
