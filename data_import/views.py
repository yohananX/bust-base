import csv
import io
import json
import os
import tempfile

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import School
from data_import.importers import ClassImporter, SubjectImporter, StudentImporter, StaffImporter
from data_import.models import ImportLog


IMPORTERS = {
    'classes': ClassImporter,
    'subjects': SubjectImporter,
    'students': StudentImporter,
    'staff': StaffImporter,
}

TEMPLATES = {
    'classes': 'name,section\nReception,\nPrimary 1,Primary\nPrimary 2,Primary\nJSS 1,Junior\nJSS 2,Junior\nSS 1,Senior',
    'subjects': 'class_name,subject_name\nReception,Literacy\nReception,Numeracy\nPrimary 1,English Studies\nPrimary 1,Mathematics\nJSS 1,Basic Science',
    'students': 'first_name,last_name,username,date_of_birth,gender,parent_name,parent_email,parent_phone,class_name\nJohn,Doe,johndoe,2010-01-15,M,Jane Doe,jane@example.com,08012345678,JSS 1',
    'staff': 'first_name,last_name,username,email,phone_number,role\nEmeka,Teacher,emekat,emeka@school.com,08011112222,TEACHER',
}


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
            return redirect('school_admin:import')

        if import_type not in IMPORTERS:
            messages.error(request, 'Invalid import type.')
            return redirect('school_admin:import')

        # Read and parse the CSV
        try:
            decoded = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded))
            all_rows = list(reader)
        except Exception as e:
            messages.error(request, f'Error reading CSV file: {e}')
            return redirect('school_admin:import')

        if not all_rows:
            messages.error(request, 'The CSV file is empty or has no data rows.')
            return redirect('school_admin:import')

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

        context = {
            'import_type': import_type,
            'filename': csv_file.name,
            'total_rows': len(all_rows),
            'preview_rows': preview_rows,
            'headers': headers,
        }

        return render(request, 'data_import/partials/_preview.html', context)


class DataImportConfirmView(RoleRequiredMixin, View):
    """Execute the actual import after user confirms."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        import_data = request.session.get('import_data')
        if not import_data:
            messages.error(request, 'No import data found. Please upload a file again.')
            return redirect('school_admin:import')

        import_type = import_data['type']
        filename = import_data['filename']
        rows = import_data['rows']

        # Write rows to a temporary CSV file for the importer
        tmp = tempfile.NamedTemporaryFile(
            mode='w', newline='', suffix='.csv', delete=False, encoding='utf-8',
        )
        try:
            if rows:
                writer = csv.DictWriter(tmp, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            tmp.close()

            importer_class = IMPORTERS[import_type]
            importer = importer_class(school=request.school, dry_run=False, verbose=False)
            result = importer.import_csv(tmp.name)

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

            # Clear session data
            del request.session['import_data']

            context = {
                'log': log,
                'result': result,
            }
            return render(request, 'data_import/partials/_results.html', context)
        finally:
            os.unlink(tmp.name)


class DataImportTemplateDownloadView(RoleRequiredMixin, View):
    """Serve downloadable CSV template files."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, type):
        if type not in TEMPLATES:
            messages.error(request, 'Invalid template type.')
            return redirect('school_admin:import')

        content = TEMPLATES[type]
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{type}_template.csv"'
        return response
