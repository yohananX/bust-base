"""Seed fee categories and fee prices from the Grace House prospectus."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import AcademicSession, Term
from students.models import SchoolClass
from fees.models import FeeCategory, FeePrice


class Command(BaseCommand):
    help = 'Seed fee categories and structures from the 2026/2027 prospectus.'

    PROSPECTUS_CATEGORIES = [
        {'name': 'Registration Form', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': True},
        {'name': 'Tuition Fee', 'cycle': 'PER_TERM', 'type': 'ALL', 'compulsory': True},
        {'name': 'Uniforms', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': False},
        {'name': 'PTA', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': True},
        {'name': 'File Jacket', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': True},
        {'name': 'Maintenance', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': True},
        {'name': 'Examination Fee', 'cycle': 'ONE_TIME', 'type': 'NEW', 'compulsory': True},
        {'name': 'Christmas/End of Term Party Fee', 'cycle': 'PER_TERM', 'type': 'ALL', 'compulsory': True},
        {'name': 'Extension Class Fee', 'cycle': 'PER_TERM', 'type': 'ALL', 'compulsory': False},
    ]

    PROSPECTUS_STRUCTURES = [
        # One-time new-intake package (school-wide)
        {'category': 'Registration Form', 'amount': 2000, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        {'category': 'Uniforms', 'amount': 40000, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        {'category': 'PTA', 'amount': 1000, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        {'category': 'File Jacket', 'amount': 500, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        {'category': 'Maintenance', 'amount': 1000, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        {'category': 'Examination Fee', 'amount': 2500, 'term': None, 'type': 'NEW', 'scope': 'SCHOOL_WIDE'},
        # Termly tuition (class-specific)
        {'category': 'Tuition Fee', 'amount': 25000, 'term': 'First', 'type': 'ALL', 'scope': 'CLASS',
         'classes': ['Reception', 'Nursery 1']},
        {'category': 'Tuition Fee', 'amount': 28000, 'term': 'First', 'type': 'ALL', 'scope': 'CLASS',
         'classes': ['Nursery 2', 'Basic 1', 'Basic 2', 'Basic 3', 'Basic 4', 'Basic 5']},
        {'category': 'Tuition Fee', 'amount': 33000, 'term': 'First', 'type': 'ALL', 'scope': 'CLASS',
         'classes': ['JSS1', 'JSS2', 'JSS3']},
        {'category': 'Tuition Fee', 'amount': 34000, 'term': 'First', 'type': 'ALL', 'scope': 'CLASS',
         'classes': ['SS1', 'SS2', 'SS3']},
        # Termly extras (school-wide)
        {'category': 'Christmas/End of Term Party Fee', 'amount': 5000, 'term': 'First', 'type': 'ALL', 'scope': 'SCHOOL_WIDE'},
        {'category': 'Extension Class Fee', 'amount': 10000, 'term': 'First', 'type': 'ALL', 'scope': 'CLASS',
         'classes': ['SS3']},
    ]

    def handle(self, *args, **options):
        from core.models import School

        school = School.objects.first()
        if not school:
            self.stdout.write(self.style.ERROR('No school found. Create a school first.'))
            return

        session = AcademicSession.objects.filter(school=school, is_current=True).first()
        term_map = {}
        if session:
            for term in Term.objects.filter(school=school, session=session):
                term_map[term.name] = term
                short = term.name.replace(' Term', '').replace(' term', '').strip()
                term_map[short] = term
        else:
            self.stdout.write(self.style.WARNING('No current academic session found. Skipping term structures.'))

        with transaction.atomic():
            for cat_data in self.PROSPECTUS_CATEGORIES:
                category, created = FeeCategory.objects.get_or_create(
                    school=school,
                    name=cat_data['name'],
                    defaults={
                        'billing_cycle': cat_data['cycle'],
                        'student_type': cat_data['type'],
                        'is_compulsory': cat_data['compulsory'],
                    },
                )
                if created:
                    self.stdout.write(f'Created category: {category.name}')
                else:
                    category.billing_cycle = cat_data['cycle']
                    category.student_type = cat_data['type']
                    category.is_compulsory = cat_data['compulsory']
                    category.save()
                    self.stdout.write(f'Updated category: {category.name}')

            for struct in self.PROSPECTUS_STRUCTURES:
                term = term_map.get(struct['term'])
                if term is None and struct['term'] is not None:
                    self.stdout.write(self.style.WARNING(f"Term '{struct['term']}' not found, skipping {struct['category']}"))
                    continue

                category = FeeCategory.objects.filter(name=struct['category']).first()
                if not category:
                    self.stdout.write(self.style.WARNING(f"Category '{struct['category']}' not found, skipping"))
                    continue

                scope = struct.get('scope', 'CLASS')
                classes = struct.get('classes', [])

                if scope == 'SCHOOL_WIDE':
                    _, created = FeePrice.objects.get_or_create(
                        school=school,
                        scope=FeePrice.SCOPE_SCHOOL_WIDE,
                        school_class=None,
                        level='',
                        term=term,
                        category=category,
                        student_type=struct['type'],
                        defaults={'amount': struct['amount']},
                    )
                    if created:
                        self.stdout.write(f'Created school-wide price: {category.name} ({term.name if term else "One-time"}) {struct["type"]}')
                else:
                    for class_name in classes:
                        school_class = SchoolClass.objects.filter(school=school, name=class_name).first()
                        if not school_class:
                            self.stdout.write(self.style.WARNING(f"Class '{class_name}' not found, skipping"))
                            continue

                        _, created = FeePrice.objects.get_or_create(
                            school=school,
                            scope=FeePrice.SCOPE_CLASS,
                            school_class=school_class,
                            level='',
                            term=term,
                            category=category,
                            student_type=struct['type'],
                            defaults={'amount': struct['amount']},
                        )
                        if created:
                            self.stdout.write(f'Created price: {category.name} — {school_class.name} ({term.name if term else "One-time"}) {struct["type"]}')

        self.stdout.write(self.style.SUCCESS('Fee structure seeding complete.'))
