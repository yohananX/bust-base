from django.core.management.base import BaseCommand

from academics.models import Score, Subject
from academics.ranking import compute_positions
from core.models import Term
from students.models import SchoolClass


class Command(BaseCommand):
    help = "Compute Olympic/dense ranking positions for scores"

    def add_arguments(self, parser):
        parser.add_argument("--school-class", type=int, help="SchoolClass ID")
        parser.add_argument("--subject", type=int, help="Subject ID")
        parser.add_argument("--term", type=int, help="Term ID")

    def handle(self, *args, **options):
        school_class_id = options.get("school_class")
        subject_id = options.get("subject")
        term_id = options.get("term")

        total = 0

        if school_class_id and subject_id and term_id:
            school_class = SchoolClass.objects.get(pk=school_class_id)
            subject = Subject.objects.get(pk=subject_id)
            term = Term.objects.get(pk=term_id)
            updated = compute_positions(school_class, subject, term)
            total += updated
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {updated} scores for {subject.name} / {school_class.name} / {term.name}"
                )
            )
        else:
            # Get all unique (school_class, subject, term) combos from scores
            scores = Score.objects.select_related("subject", "term", "student").all()
            combos = set()
            for score in scores:
                enrollment = score.student.enrollments.filter(is_current=True).first()
                if enrollment:
                    combos.add((enrollment.school_class_id, score.subject_id, score.term_id))

            for sc_id, sub_id, t_id in combos:
                school_class = SchoolClass.objects.get(pk=sc_id)
                subject = Subject.objects.get(pk=sub_id)
                term = Term.objects.get(pk=t_id)
                updated = compute_positions(school_class, subject, term)
                total += updated
                self.stdout.write(f"  {subject.name} / {school_class.name} / {term.name}: {updated}")

            self.stdout.write(self.style.SUCCESS(f"Total: {total} scores updated"))
