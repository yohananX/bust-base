from django.core.management.base import BaseCommand, CommandError

from academics.models import ClassSubject, Score, Subject
from academics.ranking import compute_positions, compute_term_summary
from core.models import School, Term
from students.models import ClassOffering, SchoolClass


class Command(BaseCommand):
    help = (
        "Recompute ranking positions (per subject) and term summaries for scores. "
        "Safe to re-run at any time: positions and TermResult aggregates are reset "
        "and rebuilt from the moderated (APPROVED) scores of each class/term. "
        "Moderation actions already trigger recomputation automatically; this "
        "command is for a full backfill."
    )

    def add_arguments(self, parser):
        parser.add_argument("--school-class", type=int, help="SchoolClass ID")
        parser.add_argument("--subject", type=int, help="Subject ID")
        parser.add_argument("--term", type=int, help="Term ID")
        parser.add_argument("--school", type=int, help="School ID (full recompute only)")

    def handle(self, *args, **options):
        school_class_id = options.get("school_class")
        subject_id = options.get("subject")
        term_id = options.get("term")
        school_id = options.get("school")

        if school_id and (school_class_id or subject_id or term_id):
            raise CommandError("--school cannot be combined with --school-class/--subject/--term")

        total_positions = 0
        total_summaries = 0

        if school_class_id and subject_id and term_id:
            school_class = SchoolClass.objects.get(pk=school_class_id)
            subject = Subject.objects.get(pk=subject_id)
            term = Term.objects.get(pk=term_id)
            offering = ClassOffering.objects.get(
                school=school_class.school,
                school_class=school_class,
                academic_session=term.session,
            )
            class_subject = ClassSubject.objects.get(
                school=school_class.school,
                class_offering=offering,
                subject=subject,
            )
            updated = compute_positions(class_subject, term)
            total_positions += updated
            self.stdout.write(
                self.style.SUCCESS(
                    f"Positions for {subject.name} / {school_class.name} / {term.name}: {updated}"
                )
            )
            summaries = compute_term_summary(offering, term)
            total_summaries += summaries
            self.stdout.write(
                self.style.SUCCESS(
                    f"Term summaries for {school_class.name} / {term.name}: {summaries}"
                )
            )
        else:
            # Get all unique (school_class, subject, term) combos from scores.
            # The class is taken from the enrollment for the score's own session,
            # so historical terms are ranked against their original class roster.
            scores = Score.objects.select_related(
                "class_subject__subject",
                "class_subject__class_offering__school_class",
                "term",
            ).all()
            if school_id:
                school = School.objects.filter(pk=school_id).first()
                if not school:
                    raise CommandError(f"School {school_id} not found")
                scores = scores.filter(school=school)
            combos = set()
            for score in scores:
                combos.add((score.class_subject_id, score.term_id))

            for class_subject_id, t_id in combos:
                class_subject = ClassSubject.objects.select_related(
                    'subject', 'class_offering__school_class'
                ).get(pk=class_subject_id)
                term = Term.objects.get(pk=t_id)
                updated = compute_positions(class_subject, term)
                total_positions += updated
                self.stdout.write(
                    f"  Positions {class_subject.subject.name} / "
                    f"{class_subject.school_class.name} / {term.name}: {updated}"
                )

            # Term summaries: one pass per (offering, term)
            summary_pairs = {
                (
                    ClassSubject.objects.values_list(
                        'class_offering_id', flat=True
                    ).get(pk=class_subject_id),
                    t_id,
                )
                for class_subject_id, t_id in combos
            }
            for offering_id, t_id in summary_pairs:
                offering = ClassOffering.objects.select_related('school_class').get(
                    pk=offering_id
                )
                term = Term.objects.get(pk=t_id)
                summaries = compute_term_summary(offering, term)
                total_summaries += summaries
                self.stdout.write(
                    f"  Summaries {offering.school_class.name} / "
                    f"{term.name}: {summaries}"
                )

            self.stdout.write(self.style.SUCCESS(
                f"Total: {total_positions} positions, {total_summaries} term summaries updated"
            ))
