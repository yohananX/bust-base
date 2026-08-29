"""Tests for the Extra Lessons / Summer School module (lessons app)."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.models import School
from fees.models import Payment
from students.models import SchoolClass, Student

from .models import (
    LessonClass,
    LessonEnrollment,
    LessonPeriod,
    LessonTeacherAssignment,
)


class LessonsBase(TestCase):
    def setUp(self):
        User = self._user_model()
        self.school = School.objects.create(
            name="Grace House School", short_code="grace-house",
        )
        self.admin = User.objects.create_user(
            username="admin", password="testpass123", school=self.school,
            role=Roles.ADMIN, first_name="Ada", last_name="Nwosu",
        )
        self.teacher = User.objects.create_user(
            username="teacher", password="testpass123", school=self.school,
            role=Roles.TEACHER, first_name="Bola", last_name="Tunde",
        )
        self.student_user = User.objects.create_user(
            username="student", password="testpass123", school=self.school,
            role=Roles.STUDENT, first_name="Kelechi", last_name="Okafor",
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user,
            admission_number="GH-001", gender=Student.MALE,
            date_of_birth="2012-05-15", admission_date="2025-09-01",
        )
        self.period = LessonPeriod.objects.create(
            school=self.school, name="Summer School 2026",
            start_date="2026-08-01", end_date="2026-08-28",
            status=LessonPeriod.Status.OPEN,
        )
        self.lesson_class = LessonClass.objects.create(
            school=self.school, period=self.period,
            name="Mathematics Booster", level_hint="JSS1",
            fee_amount=Decimal("15000.00"),
        )
        self.client.force_login(self.admin)

    @staticmethod
    def _user_model():
        from django.contrib.auth import get_user_model
        return get_user_model()


class ModelTests(LessonsBase):
    def test_period_str(self):
        self.assertEqual(str(self.period), "Summer School 2026")

    def test_lesson_class_str(self):
        self.assertEqual(str(self.lesson_class), "Mathematics Booster (Summer School 2026)")

    def test_unique_period_name(self):
        with self.assertRaises(Exception):
            LessonPeriod.objects.create(
                school=self.school, name="Summer School 2026",
                start_date="2026-08-01", end_date="2026-08-28",
            )

    def test_teacher_assignment(self):
        assignment = LessonTeacherAssignment.objects.create(
            school=self.school, lesson_class=self.lesson_class, teacher=self.teacher,
        )
        self.assertIn(assignment.teacher, self.lesson_class.teachers)

    def test_period_default_fee_amount(self):
        self.period.default_fee_amount = Decimal("10000.00")
        self.period.save()
        self.assertEqual(self.period.default_fee_amount, Decimal("10000.00"))

    def test_resolved_fee_amount_uses_class_fee_when_set(self):
        self.lesson_class.fee_amount = Decimal("20000.00")
        self.lesson_class.save()
        self.assertEqual(self.lesson_class.resolved_fee_amount, Decimal("20000.00"))

    def test_resolved_fee_amount_falls_back_to_period_default(self):
        self.lesson_class.fee_amount = None
        self.lesson_class.save()
        self.period.default_fee_amount = Decimal("12000.00")
        self.period.save()
        self.assertEqual(self.lesson_class.resolved_fee_amount, Decimal("12000.00"))

    def test_lesson_class_can_link_school_class(self):
        from students.models import SchoolClass
        school_class = SchoolClass.objects.create(
            school=self.school, name="JSS 1", level="JSS",
        )
        self.lesson_class.school_class = school_class
        self.lesson_class.save()
        self.assertEqual(self.lesson_class.school_class.name, "JSS 1")


class EnrollmentTests(LessonsBase):
    def setUp(self):
        super().setUp()
        self.enrollment = LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            student=self.student, parent_name="Obi Okafor",
            parent_phones=["08012345678"],
        )

    def test_child_name_uses_student(self):
        self.assertEqual(self.enrollment.child_name, "Kelechi Okafor")

    def test_child_name_external(self):
        external = LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            external_name="Zainab Musa", parent_name="Amin Musa",
            parent_phones=["08022222222"],
        )
        self.assertEqual(external.child_name, "Zainab Musa")

    def test_payment_status_unpaid(self):
        self.assertEqual(self.enrollment.payment_status, "UNPAID")

    def test_payment_status_paid(self):
        Payment.objects.create(
            school=self.school, lesson_enrollment=self.enrollment,
            student=self.student, amount=Decimal("15000.00"),
            method=Payment.Method.CASH, status=Payment.Status.CONFIRMED,
            paid_on=self._now(),
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.amount_paid, Decimal("15000.00"))
        self.assertEqual(self.enrollment.payment_status, "PAID")

    def _now(self):
        from django.utils import timezone
        return timezone.now()


class PeriodViewTests(LessonsBase):
    def test_period_list_requires_admin(self):
        self.client.logout()
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse("lessons:period_list"))
        self.assertEqual(resp.status_code, 403)

    def test_period_list_shows_period(self):
        resp = self.client.get(reverse("lessons:period_list"))
        self.assertContains(resp, "Summer School 2026")

    def test_period_create(self):
        resp = self.client.post(reverse("lessons:period_new"), {
            "name": "Easter Boost 2027",
            "start_date": "2027-04-01",
            "end_date": "2027-04-15",
            "status": LessonPeriod.Status.DRAFT,
        })
        self.assertRedirects(resp, reverse("lessons:period_list"))
        self.assertTrue(
            LessonPeriod.objects.filter(
                school=self.school, name="Easter Boost 2027",
            ).exists(),
        )

    def test_period_close(self):
        resp = self.client.post(
            reverse("lessons:period_close", args=[self.period.pk]),
        )
        self.assertRedirects(resp, reverse("lessons:period_list"))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, LessonPeriod.Status.CLOSED)


class ClassViewTests(LessonsBase):
    def test_class_create(self):
        resp = self.client.post(reverse("lessons:class_new"), {
            "period": self.period.pk,
            "name": "English Booster",
            "level_hint": "JSS2",
            "capacity": "20",
            "fee_amount": "20000.00",
        })
        self.assertRedirects(resp, reverse("lessons:class_list"))
        self.assertTrue(
            LessonClass.objects.filter(
                school=self.school, name="English Booster",
            ).exists(),
        )

    def test_class_duplicate_in_period_rejected(self):
        resp = self.client.post(reverse("lessons:class_new"), {
            "period": self.period.pk,
            "name": "Mathematics Booster",
            "fee_amount": "15000.00",
        })
        self.assertEqual(resp.status_code, 302)


class EnrollmentViewTests(LessonsBase):
    def test_enrollment_create_external(self):
        resp = self.client.post(reverse("lessons:enrollment_new"), {
            "lesson_class": self.lesson_class.pk,
            "external_name": "Zainab Musa",
            "age": "10",
            "parent_name": "Amin Musa",
            "parent_phones": ["08022222222"],
            "relationship": "MOTHER",
            "source": "REFERRAL",
            "consent_given": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            LessonEnrollment.objects.filter(
                school=self.school, external_name="Zainab Musa",
            ).exists(),
        )

    def test_enrollment_requires_parent_phone(self):
        resp = self.client.post(reverse("lessons:enrollment_new"), {
            "lesson_class": self.lesson_class.pk,
            "external_name": "Zainab Musa",
            "parent_name": "Amin Musa",
            "parent_phones": [],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            LessonEnrollment.objects.filter(
                school=self.school, external_name="Zainab Musa",
            ).exists(),
        )

    def test_enrollment_requires_child(self):
        resp = self.client.post(reverse("lessons:enrollment_new"), {
            "lesson_class": self.lesson_class.pk,
            "parent_name": "Amin Musa",
            "parent_phones": ["08022222222"],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(LessonEnrollment.objects.count(), 0)

    def test_enrollment_payment_marks_paid(self):
        enrollment = LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            student=self.student, parent_name="Obi Okafor",
            parent_phones=["08012345678"],
        )
        resp = self.client.post(
            reverse("lessons:enrollment_pay", args=[enrollment.pk]),
            {"amount": "15000.00", "method": "CASH"},
        )
        self.assertEqual(resp.status_code, 302)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, LessonEnrollment.Status.PAID)
        self.assertTrue(Payment.objects.filter(
            lesson_enrollment=enrollment, status=Payment.Status.CONFIRMED,
        ).exists())

    def test_csv_export(self):
        LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            student=self.student, parent_name="Obi Okafor",
            parent_phones=["08012345678"],
        )
        resp = self.client.get(reverse("lessons:enrollment_export"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("Kelechi Okafor", resp.content.decode())


class TeacherPortalTests(LessonsBase):
    def setUp(self):
        super().setUp()
        LessonTeacherAssignment.objects.create(
            school=self.school, lesson_class=self.lesson_class, teacher=self.teacher,
        )
        self.client.logout()
        self.client.force_login(self.teacher)

    def test_teacher_sees_assigned_class(self):
        resp = self.client.get(reverse("lessons_teacher:class_list"))
        self.assertContains(resp, "Mathematics Booster")

    def test_teacher_sees_enrolled_students(self):
        LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            student=self.student, parent_name="Obi Okafor",
            parent_phones=["08012345678"],
        )
        resp = self.client.get(
            reverse("lessons_teacher:class_detail", args=[self.lesson_class.pk]),
        )
        self.assertContains(resp, "Kelechi Okafor")

    def test_teacher_blocked_from_unassigned_class(self):
        other = LessonClass.objects.create(
            school=self.school, period=self.period, name="Physics",
            fee_amount=Decimal("12000.00"),
        )
        resp = self.client.get(
            reverse("lessons_teacher:class_detail", args=[other.pk]),
        )
        self.assertEqual(resp.status_code, 404)


class EnrollmentRegisterStudentViewTests(LessonsBase):
    def test_get_prepopulates_middle_name(self):
        enrollment = LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            external_name="Enoima Ini Jackson",
            parent_name="Amin Musa",
            parent_phones=["08022222222"],
        )
        resp = self.client.get(
            reverse("lessons:enrollment_register_student", args=[enrollment.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="Enoima"')
        self.assertContains(resp, 'value="Ini"')
        self.assertContains(resp, 'value="Jackson"')

    def test_post_saves_middle_name(self):
        enrollment = LessonEnrollment.objects.create(
            school=self.school, lesson_class=self.lesson_class,
            external_name="Enoima Ini Jackson",
            parent_name="Amin Musa",
            parent_phones=["08022222222"],
        )
        resp = self.client.post(
            reverse("lessons:enrollment_register_student", args=[enrollment.pk]),
            {
                "first_name": "Enoima",
                "middle_name": "Ini",
                "last_name": "Jackson",
                "new_email": "enoima@example.com",
                "new_phone_number": "08011111111",
                "date_of_birth": "2015-06-01",
                "gender": "FEMALE",
                "admission_date": "2026-08-28",
                "status": "ACTIVE",
                "class_id": "",
                "session_id": "",
                "guardian_0_name": "Amin Musa",
                "guardian_0_phone": "08022222222",
                "guardian_0_relationship": "FATHER",
            },
        )
        self.assertEqual(resp.status_code, 302)
        enrollment.refresh_from_db()
        self.assertIsNotNone(enrollment.student)
        self.assertEqual(enrollment.student.user.middle_name, "Ini")
        self.assertEqual(enrollment.student.user.first_name, "Enoima")
        self.assertEqual(enrollment.student.user.last_name, "Jackson")