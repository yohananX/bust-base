"""Shared view helpers."""
import csv

from django.http import HttpResponse


def csv_response(filename, header=None):
    """Start a CSV download response.

    Returns an ``HttpResponse`` with CSV content type and an attachment
    ``Content-Disposition`` for ``filename``. When ``header`` is given the
    header row is written and the writer is returned as ``(response,
    writer)``; otherwise just the bare response (for pre-rendered content).
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    if header is None:
        return response
    writer = csv.writer(response)
    writer.writerow(header)
    return response, writer