from contextlib import redirect_stdout
from datetime import date
from io import StringIO

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SessionScopedAcademicMigrationTests(TransactionTestCase):
    migrate_from = ('academics', '0011_subject_pass_mark')
    migrate_to = ('academics', '0013_finalize_session_scoped_academics')
    students_leaf = ('students', '0011_classoffering_and_enrollment_offering')
    students_latest = ('students', '0012_student_progression_phase3')
    accounts_leaf = ('accounts', '0007_plan_updates')

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from, self.students_leaf])
        self.old_apps = self.executor.loader.project_state(
            [self.migrate_from, self.students_leaf, self.accounts_leaf]
        ).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to, self.students_latest])
        super().tearDown()

    def _school(self, suffix='main'):
        School = self.old_apps.get_model('core', 'School')
        return School.objects.create(
            name=f'Migration School {suffix}',
            short_code=f'academic-migration-{suffix}',
        )

    def _user(self, school, username, role):
        User = self.old_apps.get_model('accounts', 'User')
        return User.objects.create(
            school=school,
            username=username,
            password='!',
            role=role,
        )

    def _student(self, school, username='migration-student'):
        Student = self.old_apps.get_model('students', 'Student')
        user = self._user(school, username, 'STUDENT')
        return Student.objects.create(
            school=school,
            user=user,
            admission_number=f'{username}-001',
            date_of_birth=date(2010, 1, 1),
            gender='MALE',
            admission_date=date(2024, 9, 1),
        )

    def test_splits_multi_session_configuration_and_remaps_history(self):
        AcademicSession = self.old_apps.get_model('core', 'AcademicSession')
        Term = self.old_apps.get_model('core', 'Term')
        SchoolClass = self.old_apps.get_model('students', 'SchoolClass')
        ClassOffering = self.old_apps.get_model('students', 'ClassOffering')
        ClassEnrollment = self.old_apps.get_model('students', 'ClassEnrollment')
        Subject = self.old_apps.get_model('academics', 'Subject')
        ClassSubject = self.old_apps.get_model('academics', 'ClassSubject')
        TeacherAssignment = self.old_apps.get_model(
            'academics', 'TeacherAssignment'
        )
        Score = self.old_apps.get_model('academics', 'Score')

        school = self._school()
        first_session = AcademicSession.objects.create(
            school=school,
            name='2024/2025',
            start_date=date(2024, 9, 1),
            end_date=date(2025, 7, 31),
        )
        second_session = AcademicSession.objects.create(
            school=school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        first_term = Term.objects.create(
            school=school,
            session=first_session,
            name='First Term',
            start_date=date(2024, 9, 1),
            end_date=date(2024, 12, 15),
        )
        second_term = Term.objects.create(
            school=school,
            session=second_session,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
        )
        school_class = SchoolClass.objects.create(
            school=school, name='JSS1A'
        )
        first_offering = ClassOffering.objects.create(
            school=school,
            school_class=school_class,
            academic_session=first_session,
        )
        second_offering = ClassOffering.objects.create(
            school=school,
            school_class=school_class,
            academic_session=second_session,
        )
        subject = Subject.objects.create(
            school=school,
            name='Mathematics',
            code='MTH',
            pass_mark=35,
        )
        legacy_config = ClassSubject.objects.create(
            school=school,
            school_class=school_class,
            subject=subject,
            pass_mark=45,
        )
        teacher_one = self._user(school, 'migration-teacher-one', 'TEACHER')
        teacher_two = self._user(school, 'migration-teacher-two', 'TEACHER')
        TeacherAssignment.objects.create(
            school=school,
            teacher=teacher_one,
            subject=subject,
            school_class=school_class,
            session=first_session,
        )
        TeacherAssignment.objects.create(
            school=school,
            teacher=teacher_two,
            subject=subject,
            school_class=school_class,
            session=second_session,
        )
        student = self._student(school)
        ClassEnrollment.objects.create(
            school=school,
            student=student,
            school_class=school_class,
            session=first_session,
            class_offering=first_offering,
            is_current=False,
        )
        ClassEnrollment.objects.create(
            school=school,
            student=student,
            school_class=school_class,
            session=second_session,
            class_offering=second_offering,
            is_current=True,
        )
        # Insert legacy Score rows via raw SQL to bypass post_save audit
        # signals (which import AuditLog from the current apps registry and
        # would reject old_apps.School instances during migration setUp).
        table = connection.ops.quote_name('academics_score')
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {table} '
                '(school_id, student_id, subject_id, term_id, test_1, test_2, test_3, '
                'exam_score, extra_tests, moderation_status, entered_by_id, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                [school.pk, student.pk, subject.pk, first_term.pk,
                 None, None, None, 50, '{}', 'PENDING', teacher_one.pk,
                 date(2024, 9, 15)],
            )
            cursor.execute(
                f'INSERT INTO {table} '
                '(school_id, student_id, subject_id, term_id, test_1, test_2, test_3, '
                'exam_score, extra_tests, moderation_status, entered_by_id, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                [school.pk, student.pk, subject.pk, second_term.pk,
                 None, None, None, 60, '{}', 'PENDING', teacher_two.pk,
                 date(2025, 9, 15)],
            )
        first_score = Score.objects.filter(
            school=school, student=student, term=first_term,
        ).order_by('-pk').first()
        second_score = Score.objects.filter(
            school=school, student=student, term=second_term,
        ).order_by('-pk').first()

        output = StringIO()
        self.executor = MigrationExecutor(connection)
        with redirect_stdout(output):
            self.executor.migrate([self.migrate_to])
        new_apps = self.executor.loader.project_state([self.migrate_to]).apps
        NewClassSubject = new_apps.get_model('academics', 'ClassSubject')
        NewTeacherAssignment = new_apps.get_model(
            'academics', 'TeacherAssignment'
        )
        NewScore = new_apps.get_model('academics', 'Score')

        configs = NewClassSubject.objects.filter(
            subject_id=subject.pk
        ).order_by('class_offering__academic_session__start_date')
        self.assertEqual(configs.count(), 2)
        self.assertEqual(
            list(configs.values_list('pass_mark', flat=True)), [45, 45]
        )
        config_by_offering = {
            config.class_offering_id: config for config in configs
        }
        self.assertEqual(
            NewScore.objects.get(pk=first_score.pk).class_subject_id,
            config_by_offering[first_offering.pk].pk,
        )
        self.assertEqual(
            NewScore.objects.get(pk=second_score.pk).class_subject_id,
            config_by_offering[second_offering.pk].pk,
        )
        self.assertEqual(
            set(
                NewTeacherAssignment.objects.values_list(
                    'class_subject__class_offering_id', flat=True
                )
            ),
            {first_offering.pk, second_offering.pk},
        )
        self.assertIn('created 1 session clone(s)', output.getvalue())

        # Identical session values can be reversed without data loss.
        reverse_executor = MigrationExecutor(connection)
        reverse_executor.migrate([self.migrate_from])
        reversed_apps = reverse_executor.loader.project_state(
            [self.migrate_from]
        ).apps
        ReversedClassSubject = reversed_apps.get_model(
            'academics', 'ClassSubject'
        )
        ReversedScore = reversed_apps.get_model('academics', 'Score')
        self.assertEqual(ReversedClassSubject.objects.count(), 1)
        self.assertEqual(
            ReversedClassSubject.objects.get().pk,
            legacy_config.pk,
        )
        self.assertEqual(
            set(ReversedScore.objects.values_list('subject_id', flat=True)),
            {subject.pk},
        )

    def test_fails_loudly_when_legacy_configuration_has_no_offering(self):
        SchoolClass = self.old_apps.get_model('students', 'SchoolClass')
        Subject = self.old_apps.get_model('academics', 'Subject')
        ClassSubject = self.old_apps.get_model('academics', 'ClassSubject')

        school = self._school('ambiguous')
        school_class = SchoolClass.objects.create(
            school=school, name='Unmapped Class'
        )
        subject = Subject.objects.create(
            school=school, name='History', code='HIS'
        )
        config = ClassSubject.objects.create(
            school=school,
            school_class=school_class,
            subject=subject,
        )

        executor = MigrationExecutor(connection)
        with self.assertRaisesMessage(
            RuntimeError,
            f'ClassSubject {config.pk}',
        ):
            executor.migrate([self.migrate_to])

        # Remove only the deliberately unmappable source fixture so tearDown
        # can restore the latest schema.
        ClassSubject.objects.filter(pk=config.pk).delete()
