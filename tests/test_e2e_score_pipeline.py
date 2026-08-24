"""End-to-end score moderation -> ranking -> published booklet pipeline.

Chains: teacher enters scores -> admin moderates -> ranking verified ->
term summary verified -> admin publishes -> student accesses booklet ->
parent accesses booklet -> notifications verified.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.models import School, AcademicSession, Term
from academics.models import (
    Subject, TeacherAssignment, Score, TermResult, GradeScale,
)
from students.models import (
    SchoolClass, Student, ClassEnrollment, StudentGuardianLink,
)
from notifications.models import NotificationLog
from accounts.models import User


User = User


class ScorePipelineEndToEndTest(TestCase):
    """One chained test method covering the full score moderation + booklet pipeline."""

    def setUp(self):
        self.school = School.objects.create(name='E2E Score School', short_code='e2escore')
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-08-31',
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='First Term',
            start_date='2025-09-01',
            end_date='2025-12-15',
            is_current=True,
        )

        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.subject = Subject.objects.create(
            school=self.school, name='Mathematics', code='MTH', pass_mark=40,
        )

        # Teacher
        self.teacher_user = User.objects.create_user(
            username='e2escore_teacher', email='teacher@e2escore.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        self.assignment = TeacherAssignment.objects.create(
            school=self.school, teacher=self.teacher_user,
            subject=self.subject, school_class=self.school_class,
            session=self.session,
        )

        # Admin
        self.admin_user = User.objects.create_user(
            username='e2escore_admin', email='admin@e2escore.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )

        # Student A
        self.student_a_user = User.objects.create_user(
            username='stu_a', email='stu_a@e2escore.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        self.student_a = Student.objects.create(
            school=self.school, user=self.student_a_user,
            admission_number='E2ES-A',
            date_of_birth='2010-01-01', gender=Student.MALE,
            admission_date='2025-09-01', status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student_a,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        self.guardian_a = User.objects.create_user(
            username='guard_a', email='guard_a@e2escore.com', password='testpass123',
            school=self.school, role=Roles.PARENT,
        )
        StudentGuardianLink.objects.create(
            school=self.school, student=self.student_a, guardian=self.guardian_a,
            relationship=StudentGuardianLink.FATHER, is_primary_contact=True,
        )

        # Student B
        self.student_b_user = User.objects.create_user(
            username='stu_b', email='stu_b@e2escore.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        self.student_b = Student.objects.create(
            school=self.school, user=self.student_b_user,
            admission_number='E2ES-B',
            date_of_birth='2010-02-02', gender=Student.FEMALE,
            admission_date='2025-09-01', status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student_b,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        self.guardian_b = User.objects.create_user(
            username='guard_b', email='guard_b@e2escore.com', password='testpass123',
            school=self.school, role=Roles.PARENT,
        )
        StudentGuardianLink.objects.create(
            school=self.school, student=self.student_b, guardian=self.guardian_b,
            relationship=StudentGuardianLink.MOTHER, is_primary_contact=True,
        )

        # Grade scale
        GradeScale.objects.create(
            school=self.school, min_score=70, max_score=100, label='A', remark='Excellent',
        )
        GradeScale.objects.create(
            school=self.school, min_score=60, max_score=69, label='B', remark='Very Good',
        )
        GradeScale.objects.create(
            school=self.school, min_score=50, max_score=59, label='C', remark='Good',
        )
        GradeScale.objects.create(
            school=self.school, min_score=40, max_score=49, label='D', remark='Pass',
        )
        GradeScale.objects.create(
            school=self.school, min_score=0, max_score=39, label='F', remark='Fail',
        )

    def test_full_score_pipeline(self):
        """Chain: teacher enters scores -> admin moderates -> ranking -> term summary -> publish -> booklet -> notifications."""

        # ------------------------------------------------------------------
        # Step 1 -- Teacher enters scores (PENDING)
        # ------------------------------------------------------------------
        # Student A: total = 8+7+9+60 = 84
        Score.objects.create(
            school=self.school, student=self.student_a, subject=self.subject,
            term=self.term,
            test_1=8, test_2=7, test_3=9, exam_score=60,
            entered_by=self.teacher_user,
        )

        # Student B: total = 10+9+8+65 = 92
        Score.objects.create(
            school=self.school, student=self.student_b, subject=self.subject,
            term=self.term,
            test_1=10, test_2=9, test_3=8, exam_score=65,
            entered_by=self.teacher_user,
        )

        score_a = Score.objects.get(student=self.student_a)
        score_b = Score.objects.get(student=self.student_b)
        self.assertEqual(score_a.moderation_status, Score.MODERATION_PENDING)
        self.assertEqual(score_b.moderation_status, Score.MODERATION_PENDING)
        self.assertIsNone(score_a.position)
        self.assertIsNone(score_b.position)
        self.assertEqual(TermResult.objects.count(), 0)

        # ------------------------------------------------------------------
        # Step 2 -- Admin moderates: approve both scores
        # ------------------------------------------------------------------
        self.client.force_login(self.admin_user)

        resp_a = self.client.post(reverse('school_admin:review_results'), {
            'score_id': score_a.pk, 'action': 'approve',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp_a.status_code, 302)

        resp_b = self.client.post(reverse('school_admin:review_results'), {
            'score_id': score_b.pk, 'action': 'approve',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp_b.status_code, 302)

        score_a.refresh_from_db()
        score_b.refresh_from_db()
        self.assertEqual(score_a.moderation_status, Score.MODERATION_APPROVED)
        self.assertEqual(score_b.moderation_status, Score.MODERATION_APPROVED)

        # ------------------------------------------------------------------
        # Step 3 -- Verify ranking
        # ------------------------------------------------------------------
        # B (92) should be position 1, A (84) should be position 2
        score_a.refresh_from_db()
        score_b.refresh_from_db()
        self.assertEqual(score_b.position, 1)
        self.assertEqual(score_a.position, 2)

        # ------------------------------------------------------------------
        # Step 4 -- Verify term summary
        # ------------------------------------------------------------------
        tr_a = TermResult.objects.get(student=self.student_a, term=self.term)
        tr_b = TermResult.objects.get(student=self.student_b, term=self.term)
        self.assertEqual(tr_a.grand_total, 84)
        self.assertEqual(tr_a.total_subjects, 1)
        self.assertEqual(tr_a.overall_position, 2)
        self.assertEqual(tr_b.grand_total, 92)
        self.assertEqual(tr_b.total_subjects, 1)
        self.assertEqual(tr_b.overall_position, 1)

        # ------------------------------------------------------------------
        # Step 5 -- Admin publishes results
        # ------------------------------------------------------------------
        publish_resp = self.client.post(
            reverse('school_admin:publish_results'),
            {'term_id': self.term.pk, 'action': 'publish'},
        )
        self.assertEqual(publish_resp.status_code, 302)

        self.term.refresh_from_db()
        self.assertTrue(self.term.results_published)

        # ------------------------------------------------------------------
        # Step 6 -- Student accesses booklet
        # ------------------------------------------------------------------
        self.client.force_login(self.student_a_user)
        booklet_resp = self.client.get(
            reverse('student-result-booklet', kwargs={'term_id': self.term.pk})
        )
        self.assertEqual(booklet_resp.status_code, 200)
        self.assertContains(booklet_resp, 'Mathematics')
        self.assertContains(booklet_resp, '84')

        # ------------------------------------------------------------------
        # Step 7 -- Parent accesses booklet
        # ------------------------------------------------------------------
        self.client.force_login(self.guardian_a)
        parent_booklet_resp = self.client.get(
            reverse(
                'parent-child-result-booklet',
                kwargs={'child_pk': self.student_a.pk, 'term_id': self.term.pk},
            )
        )
        self.assertEqual(parent_booklet_resp.status_code, 200)
        self.assertContains(parent_booklet_resp, 'Mathematics')
        self.assertContains(parent_booklet_resp, '84')

        # ------------------------------------------------------------------
        # Step 8 -- Verify notifications
        # ------------------------------------------------------------------
        # Student notification
        student_notif = NotificationLog.objects.filter(
            reference=f'term-results:{self.term.pk}:s:{self.student_a.pk}'
        ).first()
        self.assertIsNotNone(student_notif)
        self.assertEqual(student_notif.recipient, self.student_a_user)
        self.assertEqual(student_notif.channel, NotificationLog.Channel.IN_APP)
        self.assertIn('Results available', student_notif.subject)

        # Guardian notification
        guardian_notif = NotificationLog.objects.filter(
            reference=f'term-results:{self.term.pk}:g:{self.student_a.pk}'
        ).first()
        self.assertIsNotNone(guardian_notif)
        self.assertEqual(guardian_notif.recipient, self.guardian_a)
        self.assertEqual(guardian_notif.channel, NotificationLog.Channel.IN_APP)
        self.assertIn('Results available', guardian_notif.subject)
