import csv
import os
import tempfile
from decimal import Decimal

from django.test import TestCase
from django.core.management import call_command

from core.models import School, AcademicSession
from accounts.models import User, Roles
from students.models import SchoolClass, Student, StudentGuardianLink
from academics.models import Subject
from data_import.importers import (
    ClassImporter, SubjectImporter, StudentImporter, StaffImporter,
    _generate_code,
)
from accounts.utils import generate_username
from data_import.models import ImportLog


def _write_csv(headers, rows):
    """Write rows to a temp CSV file and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode='w', newline='', suffix='.csv', delete=False, encoding='utf-8',
    )
    writer = csv.DictWriter(tmp, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    tmp.close()
    return tmp.name


class BaseImportTestCase(TestCase):
    """Shared setup for all import tests."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test-school')
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-07-31',
            is_current=True,
        )


# ─── Helper unit tests ───────────────────────────────────────────────────

class GenerateCodeTest(TestCase):
    def test_single_word(self):
        self.assertEqual(_generate_code('Mathematics'), 'MATH')

    def test_two_words(self):
        self.assertEqual(_generate_code('English Studies'), 'ES')

    def test_three_words(self):
        self.assertEqual(_generate_code('Basic Science And Tech'), 'BSAT')

    def test_empty(self):
        self.assertEqual(_generate_code(''), '')


class GenerateUsernameTest(TestCase):
    def test_basic(self):
        self.assertEqual(generate_username('John', 'Doe'), 'john.doe')

    def test_with_spaces(self):
        self.assertEqual(generate_username('Mary', 'Jane Smith'), 'mary.jane.smith')

    def test_special_chars(self):
        self.assertEqual(generate_username("O'Brien", 'Mac'), 'obrien.mac')


# ─── ClassImporter tests ─────────────────────────────────────────────────

class ClassImporterCreatesClassesTest(BaseImportTestCase):
    def test_creates_classes(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [
                {'name': 'Primary 1', 'section': 'Primary'},
                {'name': 'JSS 1', 'section': 'Junior'},
            ],
        )
        try:
            importer = ClassImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['total'], 2)
            self.assertEqual(result['created'], 2)
            self.assertEqual(result['skipped'], 0)
            self.assertEqual(result['errors'], [])

            self.assertTrue(SchoolClass.objects.filter(school=self.school, name='Primary 1').exists())
            self.assertTrue(SchoolClass.objects.filter(school=self.school, name='JSS 1').exists())
        finally:
            os.unlink(csv_path)


class ClassImporterSkipsDuplicatesTest(BaseImportTestCase):
    def test_skips_duplicates(self):
        SchoolClass.objects.create(school=self.school, name='Primary 1', level='Primary')

        csv_path = _write_csv(
            ['name', 'section'],
            [{'name': 'Primary 1', 'section': 'Primary'}],
        )
        try:
            importer = ClassImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['total'], 1)
            self.assertEqual(result['created'], 0)
            self.assertEqual(result['skipped'], 1)
        finally:
            os.unlink(csv_path)


class ClassImporterWithSectionTest(BaseImportTestCase):
    def test_section_maps_to_level(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [{'name': 'JSS 2', 'section': 'Junior'}],
        )
        try:
            importer = ClassImporter(school=self.school)
            result = importer.import_csv(csv_path)

            cls = SchoolClass.objects.get(school=self.school, name='JSS 2')
            self.assertEqual(cls.level, 'Junior')
        finally:
            os.unlink(csv_path)

    def test_empty_section_uses_name(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [{'name': 'Reception', 'section': ''}],
        )
        try:
            importer = ClassImporter(school=self.school)
            result = importer.import_csv(csv_path)

            cls = SchoolClass.objects.get(school=self.school, name='Reception')
            self.assertEqual(cls.level, 'Reception')
        finally:
            os.unlink(csv_path)


# ─── SubjectImporter tests ───────────────────────────────────────────────

class SubjectImporterCreatesSubjectsTest(BaseImportTestCase):
    def test_creates_subjects(self):
        SchoolClass.objects.create(school=self.school, name='Primary 1', level='Primary')

        csv_path = _write_csv(
            ['class_name', 'subject_name'],
            [
                {'class_name': 'Primary 1', 'subject_name': 'English Studies'},
                {'class_name': 'Primary 1', 'subject_name': 'Mathematics'},
            ],
        )
        try:
            importer = SubjectImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['total'], 2)
            self.assertEqual(result['created'], 2)
            self.assertTrue(Subject.objects.filter(school=self.school, name='English Studies').exists())
            self.assertTrue(Subject.objects.filter(school=self.school, name='Mathematics').exists())
        finally:
            os.unlink(csv_path)


class SubjectImporterRequiresExistingClassTest(BaseImportTestCase):
    def test_errors_on_missing_class(self):
        csv_path = _write_csv(
            ['class_name', 'subject_name'],
            [{'class_name': 'Nonexistent', 'subject_name': 'History'}],
        )
        try:
            importer = SubjectImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 0)
            self.assertEqual(len(result['errors']), 1)
            self.assertIn('not found', result['errors'][0]['message'])
        finally:
            os.unlink(csv_path)


class SubjectImporterSkipsDuplicatesTest(BaseImportTestCase):
    def test_skips_duplicates(self):
        school_class = SchoolClass.objects.create(school=self.school, name='Primary 1', level='Primary')
        subject = Subject.objects.create(school=self.school, name='English Studies', code='ES')
        ClassSubject.objects.create(school=self.school, subject=subject, school_class=school_class)

        csv_path = _write_csv(
            ['class_name', 'subject_name'],
            [{'class_name': 'Primary 1', 'subject_name': 'English Studies'}],
        )
        try:
            importer = SubjectImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['skipped'], 1)
            self.assertEqual(result['created'], 0)
        finally:
            os.unlink(csv_path)


# ─── StudentImporter tests ───────────────────────────────────────────────

class StudentImporterCreatesStudentTest(BaseImportTestCase):
    def test_creates_student(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            user = User.objects.get(username='johndoe')
            self.assertEqual(user.role, Roles.STUDENT)
            self.assertTrue(Student.objects.filter(school=self.school, user=user).exists())
        finally:
            os.unlink(csv_path)


class StudentImporterAutoInvoiceTest(BaseImportTestCase):
    """Imported students with a class get a current-term invoice automatically."""

    def setUp(self):
        super().setUp()
        from core.models import Term
        from fees.models import FeeCategory, FeeStructure

        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date='2025-09-01', end_date='2025-12-15', is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS 1', level='Junior',
        )
        category = FeeCategory.objects.create(school=self.school, name='Tuition')
        FeeStructure.objects.create(
            school=self.school, school_class=self.school_class, term=self.term,
            category=category, amount=Decimal('54000.00'),
        )

    def test_import_enrolls_and_generates_invoice(self):
        from fees.models import Invoice

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)
            self.assertEqual(result['created'], 1)

            student = Student.objects.get(user__username='johndoe')
            invoice = Invoice.objects.filter(
                school=self.school, student=student, term=self.term,
            ).first()
            self.assertIsNotNone(invoice, 'expected an auto-generated invoice on import')
            self.assertEqual(invoice.total_amount, Decimal('54000.00'))
        finally:
            os.unlink(csv_path)

    def test_import_without_class_has_no_invoice(self):
        from fees.models import Invoice

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'Jane', 'last_name': 'Roe', 'username': 'janeroe',
              'date_of_birth': '2010-01-15', 'gender': 'F',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)
            self.assertEqual(result['created'], 1)

            student = Student.objects.get(user__username='janeroe')
            self.assertFalse(
                Invoice.objects.filter(school=self.school, student=student).exists()
            )
        finally:
            os.unlink(csv_path)


class StudentImporterWithParentTest(BaseImportTestCase):
    def test_creates_parent_with_full_info(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': 'Jane Doe', 'parent_email': 'jane@example.com', 'parent_phone': '08012345678',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            parent = User.objects.get(role=Roles.PARENT, school=self.school)
            self.assertEqual(parent.first_name, 'Jane')
            self.assertEqual(parent.last_name, 'Doe')
            self.assertEqual(parent.email, 'jane@example.com')
            self.assertEqual(parent.phone_number, '08012345678')
        finally:
            os.unlink(csv_path)


class StudentImporterParentWithoutEmailTest(BaseImportTestCase):
    def test_parent_without_email(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': 'Jane Doe', 'parent_email': '', 'parent_phone': '08012345678',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            parent = User.objects.get(role=Roles.PARENT, school=self.school)
            self.assertEqual(parent.email, '')
            self.assertEqual(parent.phone_number, '08012345678')
        finally:
            os.unlink(csv_path)


class StudentImporterParentWithoutPhoneTest(BaseImportTestCase):
    def test_parent_without_phone(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': 'Jane Doe', 'parent_email': 'jane@example.com', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            parent = User.objects.get(role=Roles.PARENT, school=self.school)
            self.assertEqual(parent.email, 'jane@example.com')
            self.assertEqual(parent.phone_number, '')
        finally:
            os.unlink(csv_path)


class StudentImporterParentWithoutEmailOrPhoneTest(BaseImportTestCase):
    def test_parent_without_email_or_phone(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': 'Jane Doe', 'parent_email': '', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            parent = User.objects.get(role=Roles.PARENT, school=self.school)
            self.assertEqual(parent.first_name, 'Jane')
            self.assertEqual(parent.email, '')
            self.assertEqual(parent.phone_number, '')
        finally:
            os.unlink(csv_path)


class StudentImporterWithoutParentNameTest(BaseImportTestCase):
    def test_no_parent_created(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            self.assertFalse(User.objects.filter(role=Roles.PARENT, school=self.school).exists())
        finally:
            os.unlink(csv_path)


class StudentImporterSkipsDuplicateUsernameTest(BaseImportTestCase):
    def test_skips_duplicate_username(self):
        User.objects.create_user(username='johndoe', password='test123', school=self.school, role=Roles.STUDENT)

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['skipped'], 1)
            self.assertEqual(result['created'], 0)
        finally:
            os.unlink(csv_path)


class StudentImporterAutoGeneratesUsernameTest(BaseImportTestCase):
    def test_auto_generates_username(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': '',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            self.assertTrue(User.objects.filter(username='john.doe').exists())
        finally:
            os.unlink(csv_path)


class StudentImporterAutoGeneratesAdmissionNumberTest(BaseImportTestCase):
    def test_auto_generates_admission_number(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            student = Student.objects.get(school=self.school)
            self.assertTrue(student.admission_number.startswith('TES'))
            self.assertRegex(student.admission_number, r'^[A-Z]{3}\d{2}[A-Z0-9]{2}\d{3}$')
        finally:
            os.unlink(csv_path)


class StudentImporterMultiGuardianTest(BaseImportTestCase):
    def test_creates_multiple_guardians(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'date_of_birth', 'gender',
             'guardian_1_name', 'guardian_1_email', 'guardian_1_phone', 'guardian_1_relationship',
             'guardian_2_name', 'guardian_2_email', 'guardian_2_phone', 'guardian_2_relationship',
             'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'date_of_birth': '2010-01-15', 'gender': 'M',
              'guardian_1_name': 'Jane Doe', 'guardian_1_email': 'jane@example.com', 'guardian_1_phone': '08011111111', 'guardian_1_relationship': 'MOTHER',
              'guardian_2_name': 'John Doe Sr', 'guardian_2_email': 'john.sr@example.com', 'guardian_2_phone': '08022222222', 'guardian_2_relationship': 'FATHER',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            student = Student.objects.get(school=self.school)
            links = StudentGuardianLink.objects.filter(student=student)
            self.assertEqual(links.count(), 2)
            self.assertTrue(links.filter(guardian__email='jane@example.com').exists())
            self.assertTrue(links.filter(guardian__email='john.sr@example.com').exists())
        finally:
            os.unlink(csv_path)

    def test_deduplicates_parents_by_email_across_rows(self):
        parent_email = 'shared@example.com'
        csv_path = _write_csv(
            ['first_name', 'last_name', 'date_of_birth', 'gender',
             'guardian_1_name', 'guardian_1_email', 'guardian_1_phone', 'guardian_1_relationship',
             'class_name'],
            [
                {'first_name': 'Child1', 'last_name': 'Doe', 'date_of_birth': '2010-01-15', 'gender': 'M',
                 'guardian_1_name': 'Jane Doe', 'guardian_1_email': parent_email, 'guardian_1_phone': '08011111111', 'guardian_1_relationship': 'MOTHER',
                 'class_name': ''},
                {'first_name': 'Child2', 'last_name': 'Doe', 'date_of_birth': '2011-02-15', 'gender': 'F',
                 'guardian_1_name': 'Jane Doe', 'guardian_1_email': parent_email, 'guardian_1_phone': '08011111111', 'guardian_1_relationship': 'MOTHER',
                 'class_name': ''},
            ],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 2)
            parent_count = User.objects.filter(school=self.school, role=Roles.PARENT, email=parent_email).count()
            self.assertEqual(parent_count, 1)
            children = Student.objects.filter(school=self.school)
            self.assertEqual(children.count(), 2)
            for child in children:
                self.assertEqual(child.guardian_links.count(), 1)
                self.assertEqual(child.guardian_links.first().guardian.email, parent_email)
        finally:
            os.unlink(csv_path)

    def test_parses_delimited_guardians_column(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'date_of_birth', 'gender', 'guardians', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'date_of_birth': '2010-01-15', 'gender': 'M',
              'guardians': 'Jane Doe|jane@example.com|08011111111|MOTHER;John Doe Sr|john.sr@example.com|08022222222|FATHER',
              'class_name': ''}],
        )
        try:
            importer = StudentImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            student = Student.objects.get(school=self.school)
            links = StudentGuardianLink.objects.filter(student=student)
            self.assertEqual(links.count(), 2)
        finally:
            os.unlink(csv_path)


# ─── StaffImporter tests ─────────────────────────────────────────────────

class StaffImporterCreatesStaffTest(BaseImportTestCase):
    def test_creates_staff(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'email', 'phone_number', 'role'],
            [{'first_name': 'Emeka', 'last_name': 'Teacher', 'username': 'emekat',
              'email': 'emeka@school.com', 'phone_number': '08011112222', 'role': 'TEACHER'}],
        )
        try:
            importer = StaffImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['created'], 1)
            user = User.objects.get(username='emekat')
            self.assertEqual(user.role, Roles.TEACHER)
            self.assertEqual(user.email, 'emeka@school.com')
        finally:
            os.unlink(csv_path)


class StaffImporterSkipsDuplicateUsernameTest(BaseImportTestCase):
    def test_skips_duplicate_username(self):
        User.objects.create_user(username='emekat', password='test123', school=self.school, role=Roles.TEACHER)

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'email', 'phone_number', 'role'],
            [{'first_name': 'Emeka', 'last_name': 'Teacher', 'username': 'emekat',
              'email': '', 'phone_number': '', 'role': 'TEACHER'}],
        )
        try:
            importer = StaffImporter(school=self.school)
            result = importer.import_csv(csv_path)

            self.assertEqual(result['skipped'], 1)
            self.assertEqual(result['created'], 0)
        finally:
            os.unlink(csv_path)


class StaffImporterDefaultsRoleToTeacherTest(BaseImportTestCase):
    def test_defaults_role_to_teacher(self):
        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'email', 'phone_number', 'role'],
            [{'first_name': 'Emeka', 'last_name': 'Teacher', 'username': 'emekat',
              'email': '', 'phone_number': '', 'role': ''}],
        )
        try:
            importer = StaffImporter(school=self.school)
            result = importer.import_csv(csv_path)

            user = User.objects.get(username='emekat')
            self.assertEqual(user.role, Roles.TEACHER)
        finally:
            os.unlink(csv_path)


# ─── Management command tests ────────────────────────────────────────────

class ImportDataCommandDryRunTest(BaseImportTestCase):
    def test_dry_run(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [{'name': 'Primary 1', 'section': 'Primary'}],
        )
        try:
            call_command('import_data', file=csv_path, type='classes', school='test-school', dry_run=True)

            # Nothing should be created during dry run
            self.assertFalse(SchoolClass.objects.filter(school=self.school, name='Primary 1').exists())
            # No import log should be created
            self.assertFalse(ImportLog.objects.filter(school=self.school).exists())
        finally:
            os.unlink(csv_path)


class ImportDataCommandClassesTest(BaseImportTestCase):
    def test_import_classes(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [
                {'name': 'Primary 1', 'section': 'Primary'},
                {'name': 'JSS 1', 'section': 'Junior'},
            ],
        )
        try:
            call_command('import_data', file=csv_path, type='classes', school='test-school')

            self.assertEqual(SchoolClass.objects.filter(school=self.school).count(), 2)
        finally:
            os.unlink(csv_path)


class ImportDataCommandStudentsTest(BaseImportTestCase):
    def test_import_students(self):
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

        csv_path = _write_csv(
            ['first_name', 'last_name', 'username', 'date_of_birth', 'gender', 'parent_name', 'parent_email', 'parent_phone', 'class_name'],
            [{'first_name': 'John', 'last_name': 'Doe', 'username': 'johndoe',
              'date_of_birth': '2010-01-15', 'gender': 'M',
              'parent_name': '', 'parent_email': '', 'parent_phone': '',
              'class_name': 'JSS 1'}],
        )
        try:
            call_command('import_data', file=csv_path, type='students', school='test-school')

            self.assertTrue(User.objects.filter(username='johndoe').exists())
            self.assertTrue(Student.objects.filter(school=self.school).exists())
        finally:
            os.unlink(csv_path)


class ImportLogCreatedTest(BaseImportTestCase):
    def test_import_log_created(self):
        csv_path = _write_csv(
            ['name', 'section'],
            [{'name': 'Primary 1', 'section': 'Primary'}],
        )
        try:
            call_command('import_data', file=csv_path, type='classes', school='test-school')

            log = ImportLog.objects.get(school=self.school)
            self.assertEqual(log.import_type, 'classes')
            self.assertEqual(log.total_rows, 1)
            self.assertEqual(log.created_count, 1)
            self.assertFalse(log.dry_run)
        finally:
            os.unlink(csv_path)


class ImportConfirmNotifiesAdminsTest(TestCase):
    """Confirming an import notifies all admins with a summary alert."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test-school')
        self.admin = User.objects.create_user(
            username='import-admin', email='ia@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        SchoolClass.objects.create(school=self.school, name='JSS 1', level='Junior')

    def test_confirm_notifies_admins(self):
        from notifications.models import NotificationLog
        from django.urls import reverse

        self.client.force_login(self.admin)
        session = self.client.session
        session['import_data'] = {
            'type': 'students',
            'filename': 'students.csv',
            'rows': [{
                'first_name': 'Ada', 'last_name': 'Obi', 'username': 'adaobi',
                'date_of_birth': '2012-01-01', 'gender': 'F',
                'parent_name': '', 'parent_email': '', 'parent_phone': '',
                'class_name': 'JSS 1',
            }],
        }
        session.save()

        response = self.client.post(reverse('data_import:import_confirm'), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)

        row = NotificationLog.objects.filter(
            recipient=self.admin, reference__startswith='import:',
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.channel, NotificationLog.Channel.IN_APP)
        self.assertTrue(row.subject.startswith('Import complete: 1'))
        self.assertEqual(row.url, reverse('data_import:import'))
