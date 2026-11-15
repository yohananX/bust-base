from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models.query import QuerySet
from django.test import TestCase

from accounts.models import Roles
from core.models import AcademicSession, School
from students.models import ClassEnrollment, ClassOffering, SchoolClass, Student
from students.services import EnrolmentConflictError, confirm_enrolment


User = get_user_model()


class ClassOfferingModelTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name='Grace House School', short_code='grace-house-offerings'
        )
        self.other_school = School.objects.create(
            name='Other School', short_code='other-offerings'
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-07-31',
            is_current=True,
        )
        self.next_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date='2026-09-01',
            end_date='2027-07-31',
        )
        self.other_session = AcademicSession.objects.create(
            school=self.other_school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-07-31',
            is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A'
        )
        self.other_class = SchoolClass.objects.create(
            school=self.school, name='JSS1B'
        )

    def test_class_offering_creation(self):
        offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.session,
        )

        self.assertEqual(offering.school, self.school)
        self.assertEqual(offering.school_class, self.school_class)
        self.assertEqual(offering.academic_session, self.session)
        self.assertIn('JSS1A', str(offering))
        self.assertIn('2025/2026', str(offering))

    def test_offering_is_unique_per_class_and_session(self):
        ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.session,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ClassOffering.objects.create(
                school=self.school,
                school_class=self.school_class,
                academic_session=self.session,
            )

    def test_same_class_can_have_offerings_in_different_sessions(self):
        first = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.session,
        )
        second = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.next_session,
        )

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ClassOffering.objects.count(), 2)

    def test_different_classes_can_have_offerings_in_same_session(self):
        first = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.session,
        )
        second = ClassOffering.objects.create(
            school=self.school,
            school_class=self.other_class,
            academic_session=self.session,
        )

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ClassOffering.objects.count(), 2)

    def test_cross_tenant_offering_is_rejected(self):
        with self.assertRaises(ValidationError):
            ClassOffering.objects.create(
                school=self.school,
                school_class=self.school_class,
                academic_session=self.other_session,
            )


class ClassEnrollmentOfferingTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name='Grace House School', short_code='grace-house-enrolments'
        )
        self.other_school = School.objects.create(
            name='Other School', short_code='other-enrolments'
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-07-31',
            is_current=True,
        )
        self.next_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date='2026-09-01',
            end_date='2027-07-31',
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A'
        )
        self.other_class = SchoolClass.objects.create(
            school=self.school, name='JSS1B'
        )
        self.offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.session,
        )
        self.other_class_offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.other_class,
            academic_session=self.session,
        )
        self.next_offering = ClassOffering.objects.create(
            school=self.school,
            school_class=self.school_class,
            academic_session=self.next_session,
        )
        self.student = self._create_student(
            school=self.school,
            username='student-one',
            admission_number='GH-001',
        )

    def _create_student(self, *, school, username, admission_number):
        user = User.objects.create_user(
            username=username,
            password='testpass123',
            school=school,
            role=Roles.STUDENT,
        )
        return Student.objects.create(
            school=school,
            user=user,
            admission_number=admission_number,
            date_of_birth='2010-01-01',
            gender=Student.MALE,
            admission_date='2025-09-01',
        )

    def test_session_and_offering_mismatch_is_rejected_on_save(self):
        enrolment = ClassEnrollment(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.next_session,
            class_offering=self.offering,
        )

        with self.assertRaises(ValidationError):
            enrolment.save()

        self.assertEqual(ClassEnrollment.objects.count(), 0)

    def test_class_and_offering_mismatch_is_rejected_on_save(self):
        enrolment = ClassEnrollment(
            school=self.school,
            student=self.student,
            school_class=self.other_class,
            session=self.session,
            class_offering=self.offering,
        )

        with self.assertRaises(ValidationError):
            enrolment.save()

        self.assertEqual(ClassEnrollment.objects.count(), 0)

    def test_student_and_enrolment_school_mismatch_is_rejected(self):
        foreign_student = self._create_student(
            school=self.other_school,
            username='foreign-student',
            admission_number='OTHER-001',
        )
        enrolment = ClassEnrollment(
            school=self.school,
            student=foreign_student,
            school_class=self.school_class,
            session=self.session,
            class_offering=self.offering,
        )

        with self.assertRaises(ValidationError):
            enrolment.save()

        self.assertEqual(ClassEnrollment.objects.count(), 0)

    def test_offering_and_student_cross_tenant_mismatch_is_rejected(self):
        foreign_session = AcademicSession.objects.create(
            school=self.other_school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-07-31',
            is_current=True,
        )
        foreign_class = SchoolClass.objects.create(
            school=self.other_school, name='JSS1A'
        )
        foreign_offering = ClassOffering.objects.create(
            school=self.other_school,
            school_class=foreign_class,
            academic_session=foreign_session,
        )
        enrolment = ClassEnrollment(
            school=self.school,
            student=self.student,
            school_class=foreign_class,
            session=foreign_session,
            class_offering=foreign_offering,
        )

        with self.assertRaises(ValidationError):
            enrolment.save()

        self.assertEqual(ClassEnrollment.objects.count(), 0)

    def test_one_enrolment_per_student_and_session_at_database_level(self):
        ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.session,
            class_offering=self.offering,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ClassEnrollment.objects.create(
                school=self.school,
                student=self.student,
                school_class=self.other_class,
                session=self.session,
                class_offering=self.other_class_offering,
            )

    def test_service_creates_valid_enrolment(self):
        enrolment = confirm_enrolment(
            self.student, self.school_class, self.session
        )

        self.assertEqual(enrolment.school, self.school)
        self.assertEqual(enrolment.student, self.student)
        self.assertEqual(enrolment.school_class, self.school_class)
        self.assertEqual(enrolment.session, self.session)
        self.assertEqual(enrolment.class_offering, self.offering)
        self.assertTrue(enrolment.is_current)

    def test_service_is_idempotent_for_same_student_class_and_session(self):
        first = confirm_enrolment(self.student, self.school_class, self.session)
        second = confirm_enrolment(self.student, self.school_class, self.session)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ClassEnrollment.objects.count(), 1)

    def test_service_rejects_conflicting_existing_enrolment(self):
        existing = confirm_enrolment(
            self.student, self.school_class, self.session
        )

        with self.assertRaises(EnrolmentConflictError):
            confirm_enrolment(self.student, self.other_class, self.session)

        existing.refresh_from_db()
        self.assertEqual(existing.school_class, self.school_class)
        self.assertEqual(existing.class_offering, self.offering)
        self.assertEqual(ClassEnrollment.objects.count(), 1)

    def test_service_rejects_cross_tenant_records(self):
        foreign_class = SchoolClass.objects.create(
            school=self.other_school, name='JSS1A'
        )

        with self.assertRaises(ValidationError):
            confirm_enrolment(self.student, foreign_class, self.session)

        self.assertFalse(ClassEnrollment.objects.exists())

    def test_service_requires_an_existing_offering(self):
        class_without_offering = SchoolClass.objects.create(
            school=self.school, name='JSS2A'
        )

        with self.assertRaises(ValidationError):
            confirm_enrolment(
                self.student, class_without_offering, self.next_session
            )

        self.assertFalse(ClassEnrollment.objects.exists())

    def test_previous_current_enrolment_deactivates_after_successful_creation(self):
        previous = confirm_enrolment(
            self.student, self.school_class, self.session
        )

        current = confirm_enrolment(
            self.student, self.school_class, self.next_session
        )

        previous.refresh_from_db()
        self.assertFalse(previous.is_current)
        self.assertTrue(current.is_current)

    def test_failed_creation_does_not_deactivate_previous_current_enrolment(self):
        previous = confirm_enrolment(
            self.student, self.school_class, self.session
        )
        class_without_offering = SchoolClass.objects.create(
            school=self.school, name='JSS2A'
        )

        with self.assertRaises(ValidationError):
            confirm_enrolment(
                self.student, class_without_offering, self.next_session
            )

        previous.refresh_from_db()
        self.assertTrue(previous.is_current)
        self.assertFalse(
            ClassEnrollment.objects.filter(session=self.next_session).exists()
        )

    def test_transaction_rolls_back_new_row_if_deactivation_fails(self):
        previous = confirm_enrolment(
            self.student, self.school_class, self.session
        )

        with patch.object(
            QuerySet,
            'update',
            side_effect=DatabaseError('simulated deactivation failure'),
        ):
            with self.assertRaises(DatabaseError):
                confirm_enrolment(
                    self.student, self.school_class, self.next_session
                )

        previous.refresh_from_db()
        self.assertTrue(previous.is_current)
        self.assertFalse(
            ClassEnrollment.objects.filter(session=self.next_session).exists()
        )
