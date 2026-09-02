"""Audit FeeStructure rows to identify school-wide duplication.

This command quantifies how many FeeStructure rows are redundant copies of
a single school-wide price.  In Phase 0 the fee model requires every
school_class to have its own FeeStructure row, so static fees such as PTA,
registration, or file jackets are duplicated N times (once per class) even
though the amount never changes.

Usage::
    python manage.py audit_fee_structures
"""
from collections import defaultdict

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Audit FeeStructure rows to identify school-wide candidates and duplication.'

    def handle(self, *args, **options):
        from core.models import School
        from fees.models import FeeCategory, FeeStructure
        from students.models import SchoolClass

        total_rows = FeeStructure.objects.count()
        self.stdout.write(f'Total FeeStructure rows: {total_rows}')
        self.stdout.write('=' * 72)

        if total_rows == 0:
            self.stdout.write(self.style.WARNING('No FeeStructure rows found. Nothing to audit.'))
            return

        total_duplication = 0
        total_tuition_like = 0

        schools = School.objects.all()
        for school in schools:
            self._audit_school(school, SchoolClass, FeeStructure)
            dupes, tuition = self._audit_school_totals(school)
            total_duplication += dupes
            total_tuition_like += tuition

        self.stdout.write('=' * 72)
        self.stdout.write(
            f'SUMMARY: {total_duplication} redundant rows '
            f'(school-wide candidates), {total_tuition_like} tuition-like groups '
            f'(class-specific pricing).'
        )

    # -- helpers -----------------------------------------------------------

    def _audit_school(self, school, SchoolClass, FeeStructure):
        """Print the per-school breakdown."""
        self.stdout.write('')
        self.stdout.write(f'School: {school.name} (code: {school.short_code})')
        self.stdout.write('-' * 60)

        class_count = SchoolClass.objects.filter(school=school).count()
        school_structures = FeeStructure.objects.filter(school=school).select_related(
            'category', 'term', 'school_class'
        )

        if not school_structures:
            self.stdout.write('  (no FeeStructure rows)')
            return

        # Group by (category, term_name, student_type) -> {amount: [classes]}
        groups = defaultdict(lambda: defaultdict(list))
        for fs in school_structures:
            term_name = fs.term.name if fs.term else '(one-time)'
            key = (fs.category.name, term_name, fs.student_type)
            groups[key][fs.amount].append(fs.school_class.name)

        for (cat_name, term_name, student_type), amount_map in sorted(groups.items()):
            amounts = sorted(amount_map.keys())
            if len(amounts) == 1:
                amount = amounts[0]
                classes = sorted(set(amount_map[amount]))
                n = len(amount_map[amount])
                dupes = n - 1

                if n > 1:
                    label = 'SCHOOL-WIDE'
                    extra = f'  -> {dupes} redundant row(s)'
                else:
                    label = 'CLASS-SPECIFIC'
                    extra = ''

                self.stdout.write(
                    f'  [{label}] {cat_name} / {term_name} / {student_type}'
                )
                self.stdout.write(
                    f'    Amount: NGN{amount:,.2f}  |  Classes: {n} ({", ".join(classes)})'
                )
                if extra:
                    self.stdout.write(f'    {extra}')
            else:
                self.stdout.write(
                    f'  [TUITION-LIKE] {cat_name} / {term_name} / {student_type}'
                )
                for amt in amounts:
                    classes = sorted(set(amount_map[amt]))
                    self.stdout.write(
                        f'    NGN{amt:,.2f}: {", ".join(classes)}'
                    )

    def _audit_school_totals(self, school):
        """Compute duplication and tuition-like counts for a single school."""
        from fees.models import FeeStructure

        structures = FeeStructure.objects.filter(school=school)
        groups = defaultdict(lambda: defaultdict(list))

        for fs in structures:
            term_name = fs.term.name if fs.term else '(one-time)'
            key = (fs.category_id, term_name, fs.student_type)
            groups[key][fs.amount].append(fs.school_class_id)

        dupes = 0
        tuition_like = 0
        for amount_map in groups.values():
            if len(amount_map) == 1:
                classes = set()
                for cls_list in amount_map.values():
                    classes.update(cls_list)
                if len(classes) > 1:
                    # All classes share one price — redundant rows
                    dupes += len(classes) - 1
            else:
                tuition_like += 1
        return dupes, tuition_like
