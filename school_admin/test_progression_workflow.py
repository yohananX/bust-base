from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.models import AcademicSession, School, Term
from students.models import (
    AcademicStage,
    ClassEnrollment,
    ClassOffering,
    SchoolClass,
    SessionPreparation,
    Student,
    StudentSessionMovement,
)
from students.services import confirm_enrolment


User = get_user_model()


class SessionPreparationViewTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Workflow School', short_code='workflow')
        self.other_school = School.objects.create(name='Other School', short_code='workflow-other')
        self.admin = User.objects.create_user(
            username='workflow-admin',
            password='testpass123',
            school=self.school,
            role=Roles.ADMIN,
        )
        self.client.force_login(self.admin)
        self.source = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        self.target = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 7, 31),
        )
        for name, start, end in (
            ('First Term', date(2026, 9, 1), date(2026, 12, 15)),
            ('Second Term', date(2027, 1, 5), date(2027, 4, 10)),
            ('Third Term', date(2027, 4, 20), date(2027, 7, 31)),
        ):
            Term.objects.create(
                school=self.school,
                session=self.target,
                name=name,
                start_date=start,
                end_date=end,
            )
        self.stage = AcademicStage.objects.create(
            school=self.school, name='Primary', display_order=1
        )
        self.grade1 = SchoolClass.objects.create(
            school=self.school, name='Grade 1', academic_stage=self.stage
        )
        self.grade2 = SchoolClass.objects.create(
            school=self.school, name='Grade 2', academic_stage=self.stage
        )
        ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade1,
            academic_session=self.source,
        )
        student_user = User.objects.create_user(
            username='workflow-student',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name='Amina',
            last_name='Student',
        )
        self.student = Student.objects.create(
            school=self.school,
            user=student_user,
            admission_number='WF-001',
            date_of_birth=date(2014, 1, 1),
            gender=Student.FEMALE,
            admission_date=date(2025, 9, 1),
        )
        self.historical = confirm_enrolment(
            self.student, self.grade1, self.source
        )
        self.preparation = SessionPreparation.objects.create(
            school=self.school,
            source_session=self.source,
            target_session=self.target,
            created_by=self.admin,
        )

    def test_guided_page_shows_six_steps_and_counts(self):
        response = self.client.get(reverse(
            'school_admin:session_preparation_detail',
            args=[self.preparation.pk],
        ))
        self.assertEqual(response.status_code, 200)
        for label in (
            'Session setup', 'Class offerings', 'Progression configuration',
            'Proposed student movements', 'Exceptions and overrides',
            'Final review and confirmation',
        ):
            self.assertContains(response, label)
        self.assertContains(response, 'Without offering')

    def test_progression_post_persists_permanent_relationship(self):
        response = self.client.post(
            reverse('school_admin:session_preparation_progression', args=[self.preparation.pk]),
            {
                f'stage_next_{self.stage.pk}': '',
                f'class_next_{self.grade1.pk}': str(self.grade2.pk),
                f'class_next_{self.grade2.pk}': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.grade1.refresh_from_db()
        self.assertEqual(self.grade1.next_class, self.grade2)

    def test_complete_view_workflow_confirms_without_duplicates(self):
        self.grade1.next_class = self.grade2
        self.grade1.save()
        offering_response = self.client.post(
            reverse('school_admin:session_preparation_offerings', args=[self.preparation.pk]),
            {'class_ids': [str(self.grade2.pk)]},
        )
        self.assertEqual(offering_response.status_code, 302)
        self.client.post(
            reverse('school_admin:session_preparation_generate', args=[self.preparation.pk])
        )
        movement = StudentSessionMovement.objects.get(
            preparation=self.preparation, student=self.student
        )
        self.assertEqual(movement.destination_class, self.grade2)

        confirm_url = reverse(
            'school_admin:session_preparation_confirm', args=[self.preparation.pk]
        )
        first = self.client.post(confirm_url)
        second = self.client.post(confirm_url)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            ClassEnrollment.objects.filter(
                student=self.student, session=self.target
            ).count(),
            1,
        )
        self.assertFalse(
            ClassEnrollment.objects.get(pk=self.historical.pk).is_current
        )

    def test_individual_exclusion_override_through_view(self):
        self.grade1.next_class = self.grade2
        self.grade1.save()
        ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade2,
            academic_session=self.target,
        )
        self.client.post(
            reverse('school_admin:session_preparation_generate', args=[self.preparation.pk])
        )
        movement = StudentSessionMovement.objects.get(student=self.student)
        response = self.client.post(
            reverse(
                'school_admin:session_preparation_movement',
                args=[self.preparation.pk, movement.pk],
            ),
            {'action': 'EXCLUDE', 'destination_class_id': '', 'note': 'Approved leave'},
        )
        self.assertEqual(response.status_code, 302)
        movement.refresh_from_db()
        self.assertEqual(movement.action, StudentSessionMovement.Action.EXCLUDE)
        self.assertTrue(movement.is_override)
        self.assertEqual(movement.note, 'Approved leave')

    def test_draft_preparation_blocks_premature_session_activation(self):
        response = self.client.post(reverse(
            'school_admin:session_set_current', args=[self.target.pk]
        ))
        self.assertRedirects(
            response,
            reverse(
                'school_admin:session_preparation_detail',
                args=[self.preparation.pk],
            ),
        )
        self.target.refresh_from_db()
        self.source.refresh_from_db()
        self.assertFalse(self.target.is_current)
        self.assertTrue(self.source.is_current)

        target_term = self.target.terms.first()
        term_response = self.client.post(reverse(
            'school_admin:term_set_current', args=[target_term.pk]
        ))
        self.assertRedirects(
            term_response,
            reverse(
                'school_admin:session_preparation_detail',
                args=[self.preparation.pk],
            ),
        )
        target_term.refresh_from_db()
        self.assertFalse(target_term.is_current)

    def test_foreign_school_cannot_view_or_mutate_preparation(self):
        other_admin = User.objects.create_user(
            username='other-admin',
            password='testpass123',
            school=self.other_school,
            role=Roles.ADMIN,
        )
        self.client.force_login(other_admin)
        detail = self.client.get(reverse(
            'school_admin:session_preparation_detail', args=[self.preparation.pk]
        ))
        confirm = self.client.post(reverse(
            'school_admin:session_preparation_confirm', args=[self.preparation.pk]
        ))
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(confirm.status_code, 404)
        self.preparation.refresh_from_db()
        self.assertEqual(self.preparation.status, SessionPreparation.Status.DRAFT)


class SessionPreparationCreateViewTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Create Workflow', short_code='create-workflow')
        self.admin = User.objects.create_user(
            username='create-admin',
            password='testpass123',
            school=self.school,
            role=Roles.ADMIN,
        )
        self.client.force_login(self.admin)
        self.source = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        self.current_term = Term.objects.create(
            school=self.school,
            session=self.source,
            name='Third Term',
            start_date=date(2026, 4, 20),
            end_date=date(2026, 7, 31),
            is_current=True,
        )

    def test_create_page_builds_session_terms_and_draft(self):
        response = self.client.post(
            reverse('school_admin:session_preparation_create'),
            {
                'source_session_id': str(self.source.pk),
                'name': '2026/2027',
                'start_date': '2026-09-01',
                'end_date': '2027-07-31',
                'first_term_start': '2026-09-01',
                'first_term_end': '2026-12-15',
                'second_term_start': '2027-01-05',
                'second_term_end': '2027-04-10',
                'third_term_start': '2027-04-20',
                'third_term_end': '2027-07-31',
            },
        )
        preparation = SessionPreparation.objects.get(school=self.school)
        self.assertRedirects(
            response,
            reverse('school_admin:session_preparation_detail', args=[preparation.pk]),
        )
        self.assertEqual(preparation.target_session.terms.count(), 3)
        self.assertFalse(preparation.target_session.is_current)
        self.current_term.refresh_from_db()
        self.assertTrue(self.current_term.is_current)

    def test_invalid_schedule_does_not_leave_partial_session(self):
        response = self.client.post(
            reverse('school_admin:session_preparation_create'),
            {
                'source_session_id': str(self.source.pk),
                'name': '2026/2027',
                'start_date': '2026-09-01',
                'end_date': '2027-07-31',
                'first_term_start': '2026-09-01',
                'first_term_end': '2026-12-15',
                'second_term_start': '2026-12-01',
                'second_term_end': '2027-04-10',
                'third_term_start': '2027-04-20',
                'third_term_end': '2027-07-31',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AcademicSession.objects.filter(
                school=self.school, name='2026/2027'
            ).exists()
        )

    def test_legacy_session_create_does_not_activate_a_future_term(self):
        response = self.client.post(
            reverse('school_admin:session_create'),
            {
                'name': '2026/2027',
                'start_date': '2026-09-01',
                'end_date': '2027-07-31',
            },
        )
        self.assertRedirects(response, reverse('school_admin:session_list'))
        target = AcademicSession.objects.get(
            school=self.school, name='2026/2027'
        )
        self.assertFalse(target.terms.filter(is_current=True).exists())
        self.current_term.refresh_from_db()
        self.assertTrue(self.current_term.is_current)
