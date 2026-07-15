import os

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import School
from data_import.importers import ClassImporter, SubjectImporter, StudentImporter, StaffImporter
from data_import.models import ImportLog


IMPORTERS = {
    'classes': ClassImporter,
    'subjects': SubjectImporter,
    'students': StudentImporter,
    'staff': StaffImporter,
}


class Command(BaseCommand):
    help = 'Import data from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='Path to CSV file')
        parser.add_argument('--type', required=True, choices=IMPORTERS.keys(), help='Import type')
        parser.add_argument('--school', required=True, help='School name or short_code')
        parser.add_argument('--dry-run', action='store_true', help='Preview without committing')
        parser.add_argument('--verbose', action='store_true', help='Show each row')

    def handle(self, *args, **opts):
        # Resolve school by name or short_code
        school = School.objects.filter(short_code=opts['school']).first()
        if not school:
            school = School.objects.filter(name__iexact=opts['school']).first()
        if not school:
            self.stderr.write(self.style.ERROR(f"School '{opts['school']}' not found"))
            return

        file_path = opts['file']
        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR(f"File '{file_path}' does not exist"))
            return

        import_type = opts['type']
        dry_run = opts['dry_run']
        verbose = opts['verbose']

        importer_class = IMPORTERS[import_type]
        importer = importer_class(school=school, dry_run=dry_run, verbose=verbose)

        self.stdout.write(f"Importing {import_type} from {file_path} for school '{school.name}'...")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved"))

        result = importer.import_csv(file_path)

        # Print summary
        self.stdout.write("")
        self.stdout.write(f"Total rows:   {result['total']}")
        self.stdout.write(self.style.SUCCESS(f"Created:      {result['created']}"))
        self.stdout.write(self.style.WARNING(f"Skipped:      {result['skipped']}"))
        self.stdout.write(self.style.ERROR(f"Errors:       {len(result['errors'])}"))

        if result['errors']:
            self.stdout.write("")
            self.stdout.write("Errors:")
            for err in result['errors']:
                self.stdout.write(f"  Row {err['row']}: {err['message']}")

        # Create import log (not during dry runs)
        if not dry_run:
            ImportLog.objects.create(
                school=school,
                import_type=import_type,
                filename=os.path.basename(file_path),
                total_rows=result['total'],
                created_count=result['created'],
                skipped_count=result['skipped'],
                error_count=len(result['errors']),
                errors=result['errors'],
                dry_run=dry_run,
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete — no changes made"))
        else:
            self.stdout.write(self.style.SUCCESS("Import complete"))
