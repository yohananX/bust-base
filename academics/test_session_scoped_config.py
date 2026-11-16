from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Roles, User
from academics.models import ClassSubject, Score, Subject, TeacherAssignment
from academics.services import copy_subject_configurations
from core.models import AcademicSession, School, Term
from students.models import ClassEnrollment, ClassOffering, SchoolClass, Student


class SessionScopedAcademicConfigurationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name='Session School', short_code='session-school'
        )
        self.previous_session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
        )
        self.current_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 7, 31),
            is_current=True,
        )
        self.previous_term = Term.objects.create(
            school=self.school,
            session=self.previous_session,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
        )
        self.current_term = Term.objects.create(
            school=self.school,
            session=self.current_session,
            name='First Term',
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 15),
            is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A'
        )
        self.previous_offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.previous_session,
        )
        self.current_offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.current_session,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name='Mathematics',
            code='MTH',
            pass_mark=40,
        )
        self.previous_config = ClassSubject.objects.create(
            school=self.school,
            class_offering=self.previous_offering,
            subject=self.subject,
            pass_mark=40,
        )
        self.current_config = ClassSubject.objects.create(
            school=self.school,
            class_offering=self.current_offering,
            subject=self.subject,
            pass_mark=60,
        )
        self.teacher_previous = User.objects.create_user(
            username='teacher.previous',
            password='pass',
            school=self.school,
            role=Roles.TEACHER,
        )
        self.teacher_current = User.objects.create_user(
            username='teacher.current',
            password='pass',
            school=self.school,
            role=Roles.TEACHER,
        )
        student_user = User.objects.create_user(
            username='session.student',
            password='pass',
            school=self.school,
            role=Roles.STUDENT,
        )
        self.student = Student.objects.create(
            school=self.school,
            user=student_user,
            admission_number='SESSION-001',
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.previous_session,
            class_offering=self.previous_offering,
            is_current=False,
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.current_session,
            class_offering=self.current_offering,
            is_current=True,
        )

    def _complete_score(self, *, config, term, total_exam=25):
        return Score.objects.create(
            school=self.school,
            student=self.student,
            class_subject=config,
            term=term,
            test_1=10,
            test_2=10,
            test_3=10,
            exam_score=total_exam,
            entered_by=self.teacher_current,
        )

    def test_same_class_and_subject_have_different_session_pass_marks(self):
        self.assertNotEqual(self.previous_config.pk, self.current_config.pk)
        self.assertEqual(self.previous_config.pass_mark, 40)
        self.assertEqual(self.current_config.pass_mark, 60)

        historical = self._complete_score(
            config=self.previous_config,
            term=self.previous_term,
        )
        current = self._complete_score(
            config=self.current_config,
            term=self.current_term,
        )
        self.assertEqual(historical.total_score, 55)
        self.assertTrue(historical.passed)
        self.assertFalse(current.passed)

        self.current_config.pass_mark = 50
        self.current_config.save(update_fields=['pass_mark'])
        historical.refresh_from_db()
        self.assertTrue(historical.passed)
        self.assertEqual(historical.class_subject, self.previous_config)

    def test_different_teachers_can_be_assigned_across_sessions(self):
        previous = TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_previous,
            class_subject=self.previous_config,
        )
        current = TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_current,
            class_subject=self.current_config,
        )
        self.assertEqual(previous.session, self.previous_session)
        self.assertEqual(current.session, self.current_session)
        self.assertNotEqual(previous.teacher, current.teacher)

    def test_multiple_teachers_remain_valid_for_one_configuration(self):
        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_previous,
            class_subject=self.current_config,
        )
        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_current,
            class_subject=self.current_config,
        )
        self.assertEqual(
            TeacherAssignment.objects.filter(
                class_subject=self.current_config
            ).count(),
            2,
        )

    def test_cross_school_assignment_is_rejected(self):
        other_school = School.objects.create(
            name='Other School', short_code='session-other'
        )
        foreign_teacher = User.objects.create_user(
            username='foreign.teacher',
            password='pass',
            school=other_school,
            role=Roles.TEACHER,
        )
        with self.assertRaises(ValidationError):
            TeacherAssignment.objects.create(
                school=self.school,
                teacher=foreign_teacher,
                class_subject=self.current_config,
            )

    def test_subject_and_offering_school_mismatch_is_rejected(self):
        other_school = School.objects.create(
            name='Config Other', short_code='config-other'
        )
        foreign_subject = Subject.objects.create(
            school=other_school, name='Foreign Maths', code='FMTH'
        )
        with self.assertRaises(ValidationError):
            ClassSubject.objects.create(
                school=self.school,
                class_offering=self.current_offering,
                subject=foreign_subject,
                pass_mark=40,
            )

    def test_duplicate_configuration_and_assignment_are_prevented(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClassSubject.objects.create(
                school=self.school,
                class_offering=self.current_offering,
                subject=self.subject,
                pass_mark=60,
            )

        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_current,
            class_subject=self.current_config,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherAssignment.objects.create(
                school=self.school,
                teacher=self.teacher_current,
                class_subject=self.current_config,
            )

    def test_score_rejects_configuration_from_another_session(self):
        with self.assertRaises(ValidationError):
            self._complete_score(
                config=self.previous_config,
                term=self.current_term,
            )


class CopySubjectConfigurationsTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name='Copy School', short_code='copy-school'
        )
        self.old_session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
        )
        self.new_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 7, 31),
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='Primary 1'
        )
        self.source = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.old_session,
        )
        self.target = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.new_session,
        )
        self.maths = Subject.objects.create(
            school=self.school, name='Mathematics', code='MTH'
        )
        self.english = Subject.objects.create(
            school=self.school, name='English', code='ENG'
        )
        self.source_maths = ClassSubject.objects.create(
            school=self.school,
            class_offering=self.source,
            subject=self.maths,
            pass_mark=45,
        )
        self.source_english = ClassSubject.objects.create(
            school=self.school,
            class_offering=self.source,
            subject=self.english,
            pass_mark=50,
        )

    def test_copy_is_independent_editable_and_idempotent(self):
        created, skipped = copy_subject_configurations(self.source, self.target)
        self.assertEqual((created, skipped), (2, 0))

        copied_maths = ClassSubject.objects.get(
            class_offering=self.target, subject=self.maths
        )
        copied_maths.pass_mark = 60
        copied_maths.save(update_fields=['pass_mark'])
        self.source_maths.refresh_from_db()
        self.assertEqual(self.source_maths.pass_mark, 45)
        self.assertEqual(copied_maths.pass_mark, 60)

        created, skipped = copy_subject_configurations(self.source, self.target)
        self.assertEqual((created, skipped), (0, 2))
        copied_maths.refresh_from_db()
        self.assertEqual(copied_maths.pass_mark, 60)
        self.assertEqual(
            ClassSubject.objects.filter(class_offering=self.target).count(), 2
        )
