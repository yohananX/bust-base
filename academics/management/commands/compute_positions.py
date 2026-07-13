from django.core.management.base import BaseCommand, CommandError
from academics.models import Subject, Score
from academics.ranking import compute_positions as compute_rankings
from students.models import SchoolClass
from core.models import Term


class Command(BaseCommand):
    help = 'Compute Olympic/dense ranking positions for a given class, subject, and term.'

    def add_arguments(self, parser):
        parser.add_argument('--class-id', type=int, required=True, help='ID of the SchoolClass')
        parser.add_argument('--subject-id', type=int, required=True, help='ID of the Subject')
        parser.add_argument('--term-id', type=int, required=True, help='ID of the Term')

    def handle(self, *args, **options):
        try:
            school_class = SchoolClass.objects.get(pk=options['class_id'])
        except SchoolClass.DoesNotExist:
            raise CommandError(f'SchoolClass with id {options["class_id"]} does not exist.')
        
        try:
            subject = Subject.objects.get(pk=options['subject_id'])
        except Subject.DoesNotExist:
            raise CommandError(f'Subject with id {options["subject_id"]} does not exist.')
        
        try:
            term = Term.objects.get(pk=options['term_id'])
        except Term.DoesNotExist:
            raise CommandError(f'Term with id {options["term_id"]} does not exist.')

        count = compute_rankings(school_class, subject, term)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Positions computed for {count} score(s) in {school_class} - {subject} ({term}).'
            )
        )
