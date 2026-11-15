from contextlib import redirect_stdout
from datetime import date
from io import StringIO

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ClassOfferingMigrationTests(TransactionTestCase):
    migrate_from = ('students', '0010_remove_schoolclass_level')
    migrate_to = ('students', '0011_classoffering_and_enrollment_offering')
    accounts_leaf = ('accounts', '0007_plan_updates')

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state(
            [self.migrate_from, self.accounts_leaf]
        ).apps

    def tearDown(self):
        # Always return the shared test database schema to the latest migration,
        # including after the intentional migration-failure test.
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        super().tearDown()

    def _create_school(self, *, name, short_code):
        School = self.old_apps.get_model('core', 'School')
        return School.objects.create(name=name, short_code=short_code)

    def _create_student(self, *, school, username, admission_number):
        User = self.old_apps.get_model('accounts', 'User')
        Student = self.old_apps.get_model('students', 'Student')
        user = User.objects.create(
            school=school,
            username=username,
            password='!',
            role='STUDENT',
        )
        return Student.objects.create(
            school=school,
            user=user,
            admission_number=admission_number,
            date_of_birth=date(2010, 1, 1),
            gender='MALE',
            admission_date=date(2024, 9, 1),
        )

    def test_backfills_existing_enrolments_and_preserves_history(self):
        AcademicSession = self.old_apps.get_model('core', 'AcademicSession')
        SchoolClass = self.old_apps.get_model('students', 'SchoolClass')
        ClassEnrollment = self.old_apps.get_model(
            'students', 'ClassEnrollment'
        )

        school = self._create_school(
            name='Migration School', short_code='migration-school'
        )
        historical_session = AcademicSession.objects.create(
            school=school,
            name='2024/2025',
            start_date=date(2024, 9, 1),
            end_date=date(2025, 7, 31),
            is_current=False,
        )
        current_session = AcademicSession.objects.create(
            school=school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        historical_class = SchoolClass.objects.create(
            school=school, name='JSS1A', is_active=True
        )
        active_class_without_enrolment = SchoolClass.objects.create(
            school=school, name='JSS1B', is_active=True
        )
        inactive_class = SchoolClass.objects.create(
            school=school, name='JSS1C', is_active=False
        )
        student = self._create_student(
            school=school,
            username='migration-student',
            admission_number='MIG-001',
        )
        enrolment = ClassEnrollment.objects.create(
            school=school,
            student=student,
            school_class=historical_class,
            session=historical_session,
            is_current=False,
        )
        original = {
            'student_id': enrolment.student_id,
            'school_class_id': enrolment.school_class_id,
            'session_id': enrolment.session_id,
            'school_id': enrolment.school_id,
            'is_current': enrolment.is_current,
            'enrolled_on': enrolment.enrolled_on,
        }

        output = StringIO()
        self.executor = MigrationExecutor(connection)
        with redirect_stdout(output):
            self.executor.migrate([self.migrate_to])
        new_apps = self.executor.loader.project_state([self.migrate_to]).apps
        NewEnrollment = new_apps.get_model('students', 'ClassEnrollment')
        ClassOffering = new_apps.get_model('students', 'ClassOffering')

        migrated = NewEnrollment.objects.get(pk=enrolment.pk)
        offering = ClassOffering.objects.get(pk=migrated.class_offering_id)

        self.assertEqual(offering.school_class_id, historical_class.pk)
        self.assertEqual(
            offering.academic_session_id, historical_session.pk
        )
        self.assertEqual(migrated.student_id, original['student_id'])
        self.assertEqual(
            migrated.school_class_id, original['school_class_id']
        )
        self.assertEqual(migrated.session_id, original['session_id'])
        self.assertEqual(migrated.school_id, original['school_id'])
        self.assertEqual(migrated.is_current, original['is_current'])
        self.assertEqual(migrated.enrolled_on, original['enrolled_on'])

        # Historical pair + both active classes in the current session.
        self.assertEqual(ClassOffering.objects.count(), 3)
        self.assertTrue(
            ClassOffering.objects.filter(
                school_class_id=active_class_without_enrolment.pk,
                academic_session_id=current_session.pk,
            ).exists()
        )
        self.assertFalse(
            ClassOffering.objects.filter(
                school_class_id=inactive_class.pk,
                academic_session_id=current_session.pk,
            ).exists()
        )
        self.assertIn('created 3 offering(s), mapped 1 enrolment(s)', output.getvalue())

        # Reverse and verify that only the new pointer/table disappear. All
        # pre-existing enrolment fields and data remain unchanged.
        reverse_executor = MigrationExecutor(connection)
        reverse_executor.migrate([self.migrate_from])
        reversed_apps = reverse_executor.loader.project_state(
            [self.migrate_from]
        ).apps
        ReversedEnrollment = reversed_apps.get_model(
            'students', 'ClassEnrollment'
        )
        reversed_enrolment = ReversedEnrollment.objects.get(pk=enrolment.pk)
        self.assertEqual(reversed_enrolment.student_id, original['student_id'])
        self.assertEqual(
            reversed_enrolment.school_class_id, original['school_class_id']
        )
        self.assertEqual(reversed_enrolment.session_id, original['session_id'])
        self.assertEqual(reversed_enrolment.school_id, original['school_id'])
        self.assertEqual(reversed_enrolment.is_current, original['is_current'])
        self.assertEqual(
            reversed_enrolment.enrolled_on, original['enrolled_on']
        )

    def test_migration_fails_loudly_for_unmappable_enrolment(self):
        AcademicSession = self.old_apps.get_model('core', 'AcademicSession')
        SchoolClass = self.old_apps.get_model('students', 'SchoolClass')
        ClassEnrollment = self.old_apps.get_model(
            'students', 'ClassEnrollment'
        )

        school = self._create_school(
            name='Source School', short_code='migration-source'
        )
        other_school = self._create_school(
            name='Other School', short_code='migration-other'
        )
        foreign_session = AcademicSession.objects.create(
            school=other_school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        school_class = SchoolClass.objects.create(
            school=school, name='JSS1A', is_active=True
        )
        student = self._create_student(
            school=school,
            username='invalid-migration-student',
            admission_number='MIG-INVALID',
        )
        invalid = ClassEnrollment.objects.create(
            school=school,
            student=student,
            school_class=school_class,
            session=foreign_session,
            is_current=True,
        )

        executor = MigrationExecutor(connection)
        with self.assertRaisesMessage(
            RuntimeError, f'Cannot map ClassEnrollment {invalid.pk}'
        ):
            executor.migrate([self.migrate_to])

        # Remove only the deliberately corrupt fixture so tearDown can restore
        # the latest schema successfully.
        ClassEnrollment.objects.filter(pk=invalid.pk).delete()
