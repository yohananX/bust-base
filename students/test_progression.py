from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase

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
from students.progression import (
    confirm_session_preparation,
    create_session_preparation,
    generate_progression_proposals,
    get_or_create_session_preparation,
    preparation_summary,
    set_preparation_offerings,
    update_progression_configuration,
    update_student_movement,
)
from students.services import confirm_enrolment


User = get_user_model()


class ProgressionModelValidationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='School A', short_code='progress-a')
        self.other_school = School.objects.create(name='School B', short_code='progress-b')
        self.nursery = AcademicStage.objects.create(
            school=self.school, name='Nursery', display_order=1
        )
        self.primary = AcademicStage.objects.create(
            school=self.school, name='Primary', display_order=2
        )
        self.secondary = AcademicStage.objects.create(
            school=self.school, name='Secondary', display_order=3
        )
        self.foreign_stage = AcademicStage.objects.create(
            school=self.other_school, name='Primary', display_order=1
        )
        self.grade1 = SchoolClass.objects.create(
            school=self.school, name='Grade 1', academic_stage=self.primary
        )
        self.grade2 = SchoolClass.objects.create(
            school=self.school, name='Grade 2', academic_stage=self.primary
        )
        self.jss1 = SchoolClass.objects.create(
            school=self.school, name='JSS 1', academic_stage=self.secondary
        )

    def test_valid_same_stage_progression(self):
        self.grade1.next_class = self.grade2
        self.grade1.save()
        self.grade1.refresh_from_db()
        self.assertEqual(self.grade1.next_class, self.grade2)

    def test_valid_cross_stage_progression(self):
        self.primary.next_stage = self.secondary
        self.primary.save()
        self.grade2.next_class = self.jss1
        self.grade2.save()
        self.assertEqual(self.grade2.next_class, self.jss1)

    def test_cross_stage_progression_requires_source_next_stage(self):
        self.grade2.next_class = self.jss1
        with self.assertRaises(ValidationError):
            self.grade2.save()

    def test_cross_stage_progression_must_agree_with_stage_progression(self):
        self.primary.next_stage = self.nursery
        self.primary.save()
        self.grade2.next_class = self.jss1
        with self.assertRaises(ValidationError):
            self.grade2.save()

    def test_stage_progression_rejects_cross_school_relationship(self):
        self.primary.next_stage = self.foreign_stage
        with self.assertRaises(ValidationError):
            self.primary.save()

    def test_class_progression_rejects_cross_school_relationship(self):
        foreign_class = SchoolClass.objects.create(
            school=self.other_school,
            name='Grade 2',
            academic_stage=self.foreign_stage,
        )
        self.grade1.next_class = foreign_class
        with self.assertRaises(ValidationError):
            self.grade1.save()

    def test_stage_self_reference_and_cycle_are_rejected(self):
        self.nursery.next_stage_id = self.nursery.pk
        with self.assertRaises(ValidationError):
            self.nursery.save()

        self.nursery.next_stage = self.primary
        self.nursery.save()
        self.primary.next_stage = self.nursery
        with self.assertRaises(ValidationError):
            self.primary.save()

    def test_class_self_reference_and_cycle_are_rejected(self):
        self.grade1.next_class_id = self.grade1.pk
        with self.assertRaises(ValidationError):
            self.grade1.save()

        self.grade1.next_class = self.grade2
        self.grade1.save()
        self.grade2.next_class = self.grade1
        with self.assertRaises(ValidationError):
            self.grade2.save()

    def test_database_constraints_reject_direct_self_references(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcademicStage.objects.filter(pk=self.primary.pk).update(
                next_stage_id=self.primary.pk
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchoolClass.objects.filter(pk=self.grade1.pk).update(
                next_class_id=self.grade1.pk
            )

    def test_changing_stage_progression_cannot_invalidate_class_progression(self):
        self.primary.next_stage = self.secondary
        self.primary.save()
        self.grade2.next_class = self.jss1
        self.grade2.save()
        self.primary.next_stage = self.nursery
        with self.assertRaises(ValidationError):
            self.primary.save()

    def test_progression_configuration_persists(self):
        self.primary.next_stage = self.secondary
        self.primary.save()
        self.grade2.next_class = self.jss1
        self.grade2.save()
        self.primary.refresh_from_db()
        self.grade2.refresh_from_db()
        self.assertEqual(self.primary.next_stage, self.secondary)
        self.assertEqual(self.grade2.next_class, self.jss1)

    def test_programmatic_class_without_stage_gets_explicit_unclassified_stage(self):
        school_class = SchoolClass.objects.create(
            school=self.school, name='Legacy Unclassified'
        )
        self.assertIsNotNone(school_class.academic_stage_id)
        self.assertEqual(school_class.academic_stage.name, 'Unclassified')
        self.assertFalse(school_class.academic_stage.is_active)


class ProgressionConfigurationServiceTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Config School', short_code='config-school')
        self.other_school = School.objects.create(name='Other', short_code='config-other')
        self.primary = AcademicStage.objects.create(
            school=self.school, name='Primary', display_order=1
        )
        self.secondary = AcademicStage.objects.create(
            school=self.school, name='Secondary', display_order=2
        )
        self.grade6 = SchoolClass.objects.create(
            school=self.school, name='Grade 6', academic_stage=self.primary
        )
        self.jss1 = SchoolClass.objects.create(
            school=self.school, name='JSS 1', academic_stage=self.secondary
        )

    def test_whole_graph_update_allows_coordinated_cross_stage_change(self):
        changed_stages, changed_classes = update_progression_configuration(
            self.school,
            {self.primary.pk: self.secondary.pk, self.secondary.pk: None},
            {self.grade6.pk: self.jss1.pk, self.jss1.pk: None},
        )
        self.assertEqual((changed_stages, changed_classes), (1, 1))
        self.primary.refresh_from_db()
        self.grade6.refresh_from_db()
        self.assertEqual(self.primary.next_stage, self.secondary)
        self.assertEqual(self.grade6.next_class, self.jss1)

    def test_invalid_configuration_rolls_back_all_relationships(self):
        with self.assertRaises(ValidationError):
            update_progression_configuration(
                self.school,
                {self.primary.pk: self.secondary.pk, self.secondary.pk: self.primary.pk},
                {self.grade6.pk: self.jss1.pk},
            )
        self.primary.refresh_from_db()
        self.grade6.refresh_from_db()
        self.assertIsNone(self.primary.next_stage)
        self.assertIsNone(self.grade6.next_class)

    def test_configuration_rejects_foreign_ids(self):
        foreign_stage = AcademicStage.objects.create(
            school=self.other_school, name='Foreign', display_order=1
        )
        with self.assertRaises(ValidationError):
            update_progression_configuration(
                self.school, {self.primary.pk: foreign_stage.pk}, {}
            )


class SessionPreparationServiceTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Preparation School', short_code='prep-school')
        self.other_school = School.objects.create(name='Other School', short_code='prep-other')
        self.source_session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
            is_current=True,
        )
        self.target_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 7, 31),
        )
        self.primary = AcademicStage.objects.create(
            school=self.school, name='Primary', display_order=1
        )
        self.secondary = AcademicStage.objects.create(
            school=self.school, name='Secondary', display_order=2
        )
        self.grade1 = SchoolClass.objects.create(
            school=self.school, name='Grade 1', academic_stage=self.primary
        )
        self.grade2 = SchoolClass.objects.create(
            school=self.school, name='Grade 2', academic_stage=self.primary
        )
        self.grade3 = SchoolClass.objects.create(
            school=self.school, name='Grade 3', academic_stage=self.primary
        )
        self.grade1.next_class = self.grade2
        self.grade1.save()
        self.source_grade1 = ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade1,
            academic_session=self.source_session,
        )
        self.source_grade2 = ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade2,
            academic_session=self.source_session,
        )
        self.target_grade2 = ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade2,
            academic_session=self.target_session,
        )
        self.preparation = SessionPreparation.objects.create(
            school=self.school,
            source_session=self.source_session,
            target_session=self.target_session,
        )

    def create_student(self, suffix, school_class=None, status=Student.ACTIVE):
        school_class = school_class or self.grade1
        user = User.objects.create_user(
            username=f'student-{suffix}',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name='Student',
            last_name=str(suffix),
        )
        student = Student.objects.create(
            school=self.school,
            user=user,
            admission_number=f'P-{suffix}',
            date_of_birth=date(2014, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=status,
        )
        enrollment = confirm_enrolment(
            student=student,
            school_class=school_class,
            session=self.source_session,
        )
        return student, enrollment

    def test_proposal_uses_configured_next_class(self):
        student, _ = self.create_student('next')
        created, refreshed = generate_progression_proposals(self.preparation)
        movement = StudentSessionMovement.objects.get(student=student)
        self.assertEqual((created, refreshed), (1, 0))
        self.assertEqual(movement.proposed_class, self.grade2)
        self.assertEqual(movement.destination_class, self.grade2)
        self.assertEqual(
            movement.proposal_basis,
            StudentSessionMovement.ProposalBasis.NEXT_CLASS,
        )

    def test_no_next_class_proposes_same_class_without_guessing(self):
        student, _ = self.create_student('same', school_class=self.grade2)
        generate_progression_proposals(self.preparation)
        movement = StudentSessionMovement.objects.get(student=student)
        self.assertEqual(movement.proposed_class, self.grade2)
        self.assertEqual(
            movement.proposal_basis,
            StudentSessionMovement.ProposalBasis.SAME_CLASS,
        )

    def test_destination_without_offering_requires_manual_attention(self):
        self.grade1.next_class = self.grade3
        self.grade1.save()
        self.create_student('missing')
        generate_progression_proposals(self.preparation)
        counts, movements = preparation_summary(self.preparation)
        self.assertEqual(counts['manual_attention'], 1)
        self.assertEqual(counts['without_offering'], 1)
        self.assertEqual(movements[0].review_issue[0], 'MISSING_OFFERING')

    def test_individual_override_requires_and_uses_exact_offering(self):
        student, _ = self.create_student('override')
        target_grade3 = ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade3,
            academic_session=self.target_session,
        )
        generate_progression_proposals(self.preparation)
        movement = StudentSessionMovement.objects.get(student=student)
        movement = update_student_movement(
            movement=movement,
            action=StudentSessionMovement.Action.PROGRESS,
            destination_class=self.grade3,
            note='Administrative placement',
        )
        self.assertTrue(movement.is_override)
        self.assertEqual(movement.destination_class, target_grade3.school_class)

        target_grade3.delete()
        with self.assertRaises(ValidationError):
            update_student_movement(
                movement=movement,
                action=StudentSessionMovement.Action.PROGRESS,
                destination_class=self.grade3,
            )

    def test_repeater_uses_source_class_offering(self):
        student, _ = self.create_student('repeat')
        ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade1,
            academic_session=self.target_session,
        )
        generate_progression_proposals(self.preparation)
        movement = update_student_movement(
            movement=StudentSessionMovement.objects.get(student=student),
            action=StudentSessionMovement.Action.REPEAT,
        )
        self.assertEqual(movement.destination_class, self.grade1)
        self.assertTrue(movement.is_override)
        counts, _ = preparation_summary(self.preparation)
        self.assertEqual(counts['repeaters'], 1)
        self.assertEqual(counts['remaining'], 1)

    def test_lifecycle_exclusions_and_manual_exclusion(self):
        active, _ = self.create_student('active')
        withdrawn, _ = self.create_student('withdrawn', status=Student.WITHDRAWN)
        suspended, _ = self.create_student('suspended', status=Student.SUSPENDED)
        generate_progression_proposals(self.preparation)
        active_movement = StudentSessionMovement.objects.get(student=active)
        update_student_movement(
            movement=active_movement,
            action=StudentSessionMovement.Action.EXCLUDE,
            note='Leave of absence',
        )
        self.assertEqual(
            StudentSessionMovement.objects.get(student=withdrawn).action,
            StudentSessionMovement.Action.WITHDRAW,
        )
        self.assertEqual(
            StudentSessionMovement.objects.get(student=suspended).action,
            StudentSessionMovement.Action.EXCLUDE,
        )
        counts, _ = preparation_summary(self.preparation)
        self.assertEqual(counts['excluded'], 2)
        self.assertEqual(counts['withdrawn'], 1)

    def test_repeated_generation_is_idempotent_and_preserves_override(self):
        student, _ = self.create_student('repeat-request')
        ClassOffering.objects.create(
            school=self.school,
            school_class=self.grade1,
            academic_session=self.target_session,
        )
        generate_progression_proposals(self.preparation)
        movement = update_student_movement(
            movement=StudentSessionMovement.objects.get(student=student),
            action=StudentSessionMovement.Action.REPEAT,
            note='Approved repeater',
        )
        created, refreshed = generate_progression_proposals(self.preparation)
        movement.refresh_from_db()
        self.assertEqual((created, refreshed), (0, 1))
        self.assertEqual(StudentSessionMovement.objects.count(), 1)
        self.assertEqual(movement.action, StudentSessionMovement.Action.REPEAT)
        self.assertEqual(movement.note, 'Approved repeater')

    def test_confirmation_is_idempotent_and_preserves_history(self):
        student, historical = self.create_student('confirm')
        generate_progression_proposals(self.preparation)
        first = confirm_session_preparation(preparation=self.preparation)
        second = confirm_session_preparation(preparation=self.preparation)
        self.assertFalse(first.already_confirmed)
        self.assertTrue(second.already_confirmed)
        self.assertEqual(
            ClassEnrollment.objects.filter(
                student=student, session=self.target_session
            ).count(),
            1,
        )
        historical.refresh_from_db()
        self.assertTrue(ClassEnrollment.objects.filter(pk=historical.pk).exists())
        self.assertFalse(historical.is_current)

    def test_failed_confirmation_preserves_previous_enrolment(self):
        student, historical = self.create_student('failed')
        self.target_grade2.delete()
        generate_progression_proposals(self.preparation)
        with self.assertRaises(ValidationError):
            confirm_session_preparation(preparation=self.preparation)
        historical.refresh_from_db()
        self.assertTrue(historical.is_current)
        self.assertFalse(
            ClassEnrollment.objects.filter(
                student=student, session=self.target_session
            ).exists()
        )

    def test_batch_confirmation_rolls_back_every_student_on_failure(self):
        first_student, first_historical = self.create_student('batch-a')
        second_student, second_historical = self.create_student('batch-b')
        generate_progression_proposals(self.preparation)
        real_confirm = confirm_enrolment
        call_count = 0

        def fail_second(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise DatabaseError('simulated batch failure')
            return real_confirm(**kwargs)

        with patch('students.progression.confirm_enrolment', side_effect=fail_second):
            with self.assertRaises(DatabaseError):
                confirm_session_preparation(preparation=self.preparation)

        self.assertFalse(
            ClassEnrollment.objects.filter(session=self.target_session).exists()
        )
        first_historical.refresh_from_db()
        second_historical.refresh_from_db()
        self.assertTrue(first_historical.is_current)
        self.assertTrue(second_historical.is_current)
        self.preparation.refresh_from_db()
        self.assertEqual(self.preparation.status, SessionPreparation.Status.DRAFT)

    def test_withdrawal_is_applied_only_during_confirmation(self):
        student, historical = self.create_student('mark-withdrawn')
        generate_progression_proposals(self.preparation)
        movement = StudentSessionMovement.objects.get(student=student)
        update_student_movement(
            movement=movement,
            action=StudentSessionMovement.Action.WITHDRAW,
        )
        student.refresh_from_db()
        self.assertEqual(student.status, Student.ACTIVE)
        confirm_session_preparation(preparation=self.preparation)
        student.refresh_from_db()
        historical.refresh_from_db()
        self.assertEqual(student.status, Student.WITHDRAWN)
        self.assertFalse(historical.is_current)
        self.assertFalse(
            ClassEnrollment.objects.filter(
                student=student, session=self.target_session
            ).exists()
        )

    def test_tenant_isolation_for_proposals_and_overrides(self):
        local_student, _ = self.create_student('tenant')
        foreign_stage = AcademicStage.objects.create(
            school=self.other_school, name='Primary', display_order=1
        )
        foreign_class = SchoolClass.objects.create(
            school=self.other_school,
            name='Grade 2',
            academic_stage=foreign_stage,
        )
        generate_progression_proposals(self.preparation)
        movement = StudentSessionMovement.objects.get(student=local_student)
        with self.assertRaises(ValidationError):
            update_student_movement(
                movement=movement,
                action=StudentSessionMovement.Action.PROGRESS,
                destination_class=foreign_class,
            )
        self.assertEqual(
            StudentSessionMovement.objects.filter(
                preparation=self.preparation
            ).count(),
            1,
        )

    def test_repeated_preparation_request_returns_same_record(self):
        preparation, created = get_or_create_session_preparation(
            school=self.school,
            source_session=self.source_session,
            target_session=self.target_session,
        )
        self.assertFalse(created)
        self.assertEqual(preparation.pk, self.preparation.pk)
        self.assertEqual(SessionPreparation.objects.count(), 1)

    def test_offering_selection_is_idempotent(self):
        created, selected = set_preparation_offerings(
            preparation=self.preparation,
            class_ids=[self.grade2.pk, self.grade3.pk],
        )
        again_created, again_selected = set_preparation_offerings(
            preparation=self.preparation,
            class_ids=[self.grade2.pk, self.grade3.pk],
        )
        self.assertEqual((created, selected), (1, 2))
        self.assertEqual((again_created, again_selected), (0, 2))
        self.assertEqual(
            ClassOffering.objects.filter(
                academic_session=self.target_session
            ).count(),
            2,
        )


class SessionPreparationCreationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Creation School', short_code='creation')
        self.admin = User.objects.create_user(
            username='creation-admin',
            password='testpass123',
            school=self.school,
            role=Roles.ADMIN,
        )
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
        self.term_specs = [
            {'name': 'First Term', 'start_date': date(2026, 9, 1), 'end_date': date(2026, 12, 15)},
            {'name': 'Second Term', 'start_date': date(2027, 1, 5), 'end_date': date(2027, 4, 10)},
            {'name': 'Third Term', 'start_date': date(2027, 4, 20), 'end_date': date(2027, 7, 31)},
        ]

    def test_creates_future_session_and_configured_terms_without_activation(self):
        preparation = create_session_preparation(
            school=self.school,
            source_session=self.source,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 7, 31),
            term_specs=self.term_specs,
            created_by=self.admin,
        )
        self.assertFalse(preparation.target_session.is_current)
        self.assertEqual(
            list(preparation.target_session.terms.values_list('name', flat=True)),
            ['First Term', 'Second Term', 'Third Term'],
        )
        self.assertFalse(preparation.target_session.terms.filter(is_current=True).exists())
        self.current_term.refresh_from_db()
        self.assertTrue(self.current_term.is_current)

    def test_invalid_term_schedule_rolls_back_session_creation(self):
        invalid = [dict(spec) for spec in self.term_specs]
        invalid[1]['start_date'] = date(2026, 12, 1)
        with self.assertRaises(ValidationError):
            create_session_preparation(
                school=self.school,
                source_session=self.source,
                name='2026/2027',
                start_date=date(2026, 9, 1),
                end_date=date(2027, 7, 31),
                term_specs=invalid,
                created_by=self.admin,
            )
        self.assertFalse(
            AcademicSession.objects.filter(
                school=self.school, name='2026/2027'
            ).exists()
        )
