from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from core.models import School
from students.models import Student, ClassEnrollment, StudentGuardianLink
from academics.models import Score, TermResult
from fees.models import Invoice, Payment, FeeReceipt
from lessons.models import LessonEnrollment
from notifications.models import NotificationLog


class Command(BaseCommand):
    help = (
        'Selectively delete all student-related records for a school while '
        'preserving School, SchoolClass, Subject, AcademicSession, Term, '
        'FeeStructure, TeacherAssignment, and payroll/finance data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--school',
            required=True,
            help='School name or short_code to target (e.g. "Grace House" or "grace-house").',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without making changes.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        school_name = opts['school']
        dry_run = opts['dry_run']

        school = School.objects.filter(
            name__iexact=school_name
        ).first() or School.objects.filter(
            short_code__iexact=school_name.replace(' ', '-')
        ).first()

        if not school:
            self.stdout.write(self.style.ERROR(f'School not found: {school_name}'))
            return

        students_qs = Student.objects.filter(school=school)
        student_ids = list(students_qs.values_list('pk', flat=True))

        if not student_ids:
            self.stdout.write(self.style.WARNING(f'No students found for school: {school.name}'))
            return

        self.stdout.write(
            self.style.WARNING(
                f'Target school: {school.name} ({len(student_ids)} students)'
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be made.'))

        # ── 1. Notification logs for student/parent users ─────────────────
        student_users = Student.objects.filter(
            school=school
        ).values_list('user_id', flat=True)
        guardian_links = StudentGuardianLink.objects.filter(
            student__school=school
        ).values_list('guardian_id', flat=True)
        recipient_ids = list(student_users) + list(guardian_links)

        notif_count = NotificationLog.objects.filter(
            recipient_id__in=recipient_ids
        ).count()
        self.stdout.write(f'NotificationLog records to remove: {notif_count}')
        if not dry_run:
            NotificationLog.objects.filter(recipient_id__in=recipient_ids).delete()

        # ── 2. Scores (student + entered_by cascade risk) ─────────────────
        score_count = Score.objects.filter(student_id__in=student_ids).count()
        self.stdout.write(f'Score records to remove: {score_count}')
        if not dry_run:
            Score.objects.filter(student_id__in=student_ids).delete()

        # ── 3. Term results ──────────────────────────────────────────────
        term_result_count = TermResult.objects.filter(
            student_id__in=student_ids
        ).count()
        self.stdout.write(f'TermResult records to remove: {term_result_count}')
        if not dry_run:
            TermResult.objects.filter(student_id__in=student_ids).delete()

        # ── 4. Lesson enrollments (SET_NULL — explicit cleanup) ──────────
        lesson_enroll_count = LessonEnrollment.objects.filter(
            student_id__in=student_ids
        ).count()
        self.stdout.write(f'LessonEnrollment records to detach/remove: {lesson_enroll_count}')
        if not dry_run:
            LessonEnrollment.objects.filter(student_id__in=student_ids).delete()

        # ── 5. Payments (direct student FK + invoice-linked) ─────────────
        payment_count = Payment.objects.filter(
            student_id__in=student_ids
        ).count()
        self.stdout.write(f'Payment records to remove: {payment_count}')
        if not dry_run:
            Payment.objects.filter(student_id__in=student_ids).delete()

        # ── 6. Invoices (cascades to InvoiceLineItem and FeeReceipt) ─────
        invoice_count = Invoice.objects.filter(
            student_id__in=student_ids
        ).count()
        self.stdout.write(f'Invoice records to remove: {invoice_count}')
        if not dry_run:
            Invoice.objects.filter(student_id__in=student_ids).delete()

        # ── 7. Class enrollments ─────────────────────────────────────────
        enrollment_count = ClassEnrollment.objects.filter(
            student_id__in=student_ids
        ).count()
        self.stdout.write(f'ClassEnrollment records to remove: {enrollment_count}')
        if not dry_run:
            ClassEnrollment.objects.filter(student_id__in=student_ids).delete()

        # ── 8. Guardian links ────────────────────────────────────────────
        guardian_link_count = StudentGuardianLink.objects.filter(
            student__school=school
        ).count()
        self.stdout.write(f'StudentGuardianLink records to remove: {guardian_link_count}')
        if not dry_run:
            StudentGuardianLink.objects.filter(student__school=school).delete()

        # ── 9. Students (cascades to User, which cascades to any remaining
        #            NotificationLog/Payment.recorded_by/Score.entered_by) ─
        self.stdout.write(f'Student records to remove: {len(student_ids)}')
        if not dry_run:
            students_qs.delete()

        # ── 10. Completely orphaned records (test artifacts) ─────────────
        orphan_payments = Payment.objects.filter(student__isnull=True, invoice__isnull=True)
        orphan_lessons = LessonEnrollment.objects.filter(student__isnull=True)
        self.stdout.write(f'Orphan Payment records to remove: {orphan_payments.count()}')
        self.stdout.write(f'Orphan LessonEnrollment records to remove: {orphan_lessons.count()}')
        if not dry_run:
            orphan_payments.delete()
            orphan_lessons.delete()

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run complete — no data was modified.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Successfully cleared student data for school: {school.name}'
            ))
