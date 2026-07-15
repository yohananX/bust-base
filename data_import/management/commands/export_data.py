import csv
import sys

from django.core.management.base import BaseCommand

from core.models import School
from accounts.models import User, Roles
from students.models import SchoolClass, Student, ClassEnrollment
from academics.models import Subject


EXPORTERS = {
    'classes': '_export_classes',
    'subjects': '_export_subjects',
    'students': '_export_students',
    'staff': '_export_staff',
}


class Command(BaseCommand):
    help = 'Export data to CSV'

    def add_arguments(self, parser):
        parser.add_argument('--type', required=True, choices=EXPORTERS.keys(), help='Export type')
        parser.add_argument('--school', required=True, help='School name or short_code')
        parser.add_argument('--output', default=None, help='Output file path (default: stdout)')

    def handle(self, *args, **opts):
        school = School.objects.filter(short_code=opts['school']).first()
        if not school:
            school = School.objects.filter(name__iexact=opts['school']).first()
        if not school:
            self.stderr.write(self.style.ERROR(f"School '{opts['school']}' not found"))
            return

        exporter_name = EXPORTERS[opts['type']]
        exporter = getattr(self, exporter_name)
        rows = exporter(school)

        output_path = opts.get('output')
        if output_path:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} rows to {output_path}"))
        else:
            if rows:
                writer = csv.DictWriter(sys.stdout, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            else:
                self.stdout.write("No data to export")

    def _export_classes(self, school):
        classes = SchoolClass.objects.filter(school=school).order_by('level', 'name')
        return [
            {'name': c.name, 'section': c.level}
            for c in classes
        ]

    def _export_subjects(self, school):
        subjects = Subject.objects.filter(school=school).order_by('name')
        return [
            {'class_name': '', 'subject_name': s.name, 'code': s.code}
            for s in subjects
        ]

    def _export_students(self, school):
        students = Student.objects.filter(school=school).select_related('user').order_by('admission_number')
        rows = []
        for s in students:
            rows.append({
                'first_name': s.user.first_name,
                'last_name': s.user.last_name,
                'username': s.user.username,
                'date_of_birth': str(s.date_of_birth) if s.date_of_birth else '',
                'gender': s.gender,
                'parent_name': '',
                'parent_email': '',
                'parent_phone': '',
                'class_name': '',
            })
        return rows

    def _export_staff(self, school):
        staff = User.objects.filter(
            school=school,
            role__in=[Roles.ADMIN, Roles.TEACHER],
        ).order_by('username')
        return [
            {
                'first_name': u.first_name,
                'last_name': u.last_name,
                'username': u.username,
                'email': u.email,
                'phone_number': u.phone_number,
                'role': u.role,
            }
            for u in staff
        ]
