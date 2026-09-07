import csv
import io
import os
import tempfile
from contextlib import contextmanager

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from data_import.importers import ClassImporter, SubjectImporter, StudentImporter, StaffImporter, IMPORTERS, TEMPLATES
from data_import.models import ImportLog


@contextmanager
def _temp_csv_path(rows):
    """Write rows to a temporary CSV file and yield its path.

    The file is automatically deleted when the context exits.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode='w', newline='', suffix='.csv', delete=False, encoding='utf-8',
    )
    try:
        if rows:
            writer = csv.DictWriter(tmp, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        tmp.close()
        yield tmp.name
    finally:
        os.unlink(tmp.name)


class DataImportView(RoleRequiredMixin, View):
    """Show upload form with import history."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        logs = ImportLog.objects.filter(school=request.school).order_by('-imported_at')[:20]
        return render(request, 'data_import/import.html', {
            'logs': logs,
            'import_types': ImportLog.IMPORT_TYPES,
        })

    def post(self, request):
        csv_file = request.FILES.get('csv_file')
        import_type = request.POST.get('import_type', '').strip()

        if not csv_file:
            messages.error(request, 'Please select a CSV file to upload.')
            return redirect('data_import:import')

        if import_type not in IMPORTERS:
            messages.error(request, 'Invalid import type.')
            return redirect('data_import:import')

        # Read and parse the CSV
        try:
            decoded = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded))
            all_rows = list(reader)
        except Exception as e:
            messages.error(request, f'Error reading CSV file: {e}')
            return redirect('data_import:import')

        if not all_rows:
            messages.error(request, 'The CSV file is empty or has no data rows.')
            return redirect('data_import:import')

        # Run dry_run to get created/skipped/error counts
        with _temp_csv_path(all_rows) as tmp_path:
            importer_class = IMPORTERS[import_type]
            importer = importer_class(school=request.school, dry_run=True, verbose=False)
            dry_result = importer.import_csv(tmp_path)

        # Store data in session for confirmation
        request.session['import_data'] = {
            'type': import_type,
            'filename': csv_file.name,
            'rows': [dict(r) for r in all_rows],
        }

        headers = reader.fieldnames or []
        # Convert to list of lists for template rendering (dict key access is tricky in Django templates)
        preview_rows = []
        for row in all_rows[:10]:
            preview_rows.append([row.get(h, '') for h in headers])

        error_rows = [e['row'] for e in dry_result.get('errors', [])]

        context = {
            'import_type': import_type,
            'filename': csv_file.name,
            'total_rows': len(all_rows),
            'preview_rows': preview_rows,
            'headers': headers,
            'dry_result': dry_result,
            'error_rows': error_rows,
        }

        return render(request, 'data_import/partials/_preview.html', context)


class DataImportConfirmView(RoleRequiredMixin, View):
    """Execute the actual import after user confirms."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        import_data = request.session.get('import_data')
        if not import_data:
            messages.error(request, 'No import data found. Please upload a file again.')
            return redirect('data_import:import')

        import_type = import_data['type']
        filename = import_data['filename']
        rows = import_data['rows']

        # Write rows to a temporary CSV file for the importer
        with _temp_csv_path(rows) as tmp_path:
            importer_class = IMPORTERS[import_type]
            importer = importer_class(school=request.school, dry_run=False, verbose=False)
            result = importer.import_csv(tmp_path)

            # Create import log
            log = ImportLog.objects.create(
                school=request.school,
                import_type=import_type,
                filename=filename,
                total_rows=result['total'],
                created_count=result['created'],
                skipped_count=result['skipped'],
                error_count=len(result['errors']),
                errors=result['errors'],
                dry_run=False,
                imported_by=request.user,
            )

            # One summary notification for all admins
            from notifications.utils import notify_admins
            notify_admins(
                school=request.school,
                subject=f'Import complete: {result["created"]} {import_type} records',
                message=(
                    f'Import of {filename}: {result["created"]} created, '
                    f'{result["skipped"]} skipped, {len(result["errors"])} errors.'
                ),
                reference=f'import:{log.id}',
                url=reverse('data_import:import'),
            )

            # Clear session data
            del request.session['import_data']

            context = {
                'log': log,
                'result': result,
            }
            return render(request, 'data_import/partials/_results.html', context)


class DataImportTemplateDownloadView(RoleRequiredMixin, View):
    """Serve downloadable CSV template files."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, type):
        if type not in TEMPLATES:
            messages.error(request, 'Invalid template type.')
            return redirect('data_import:import')

        content = TEMPLATES[type]
        from core.utils import csv_response

        response = csv_response(f'{type}_template.csv')
        response.write(content)
        return response
