import csv
import os
import tempfile

from django.test import TestCase, TransactionTestCase
from django.core.management import call_command
from django.utils import timezone

from core.models import School, AcademicSession
from accounts.models import User, Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from academics.models import Subject
from data_import.importers import (
    ClassImporter, SubjectImporter, StudentImporter, StaffImporter,
    _generate_code, _generate_username,
)
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
        self.assertEqual(_generate_username('John', 'Doe'), 'johndoe')

    def test_with_spaces(self):
        self.assertEqual(_generate_username('Mary', 'Jane Smith'), 'maryjanesmith')

    def test_special_chars(self):
        self.assertEqual(_generate_username("O'Brien", 'Mac'), 'obrienmac')


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
        SchoolClass.objects.create(school=self.school, name='Primary 1', level='Primary')
        Subject.objects.create(school=self.school, name='English Studies', code='ES')

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
            self.assertTrue(User.objects.filter(username='johndoe').exists())
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
            self.assertTrue(student.admission_number.startswith('STU-'))
            self.assertTrue(len(student.admission_number) > 4)
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
