"""PDF generation for result booklets."""
import logging
import os
from pathlib import Path

from django.http import HttpResponse
from django.template.loader import render_to_string

from .booklet import build_booklet_context

logger = logging.getLogger(__name__)


def render_result_booklet_pdf(student, term):
    """Render a result booklet PDF for a student in a given term.

    The school logo is resolved from its local filesystem path (base_url)
    so WeasyPrint never depends on a web-visible /media/ URL — this keeps
    downloads working behind ngrok, proxies, and offline setups alike.

    When the WeasyPrint runtime is unavailable (e.g. missing GTK/Pango
    libraries on Windows), falls back to serving the booklet as a printable
    HTML page so the download never errors out.

    Returns an HttpResponse, or None if no enrollment found.
    """
    context, enrollment = build_booklet_context(student, term, student.school)
    if not enrollment:
        return None

    logo = student.school.logo

    try:
        from weasyprint import HTML
    except Exception as exc:  # import-time failure (missing native libs)
        logger.warning("WeasyPrint unavailable (%s); serving printable HTML booklet", exc)
        return _printable_html_response(student, term, context, logo)

    if logo:
        pdf_context = dict(context, logo_url=os.path.basename(logo.path))
        base_url = Path(logo.path).parent.as_uri()
    else:
        pdf_context = dict(context, logo_url='')
        base_url = None

    html_string = render_to_string('academics/result_booklet.html', pdf_context)

    try:
        pdf_bytes = HTML(string=html_string, base_url=base_url).write_pdf()
    except Exception as exc:  # render-time failure (missing native libs)
        logger.warning("WeasyPrint render failed (%s); serving printable HTML booklet", exc)
        return _printable_html_response(student, term, context, logo)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"result_{student.admission_number}_{term.name}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _printable_html_response(student, term, context, logo):
    """Serve the booklet as a downloadable page identical to the preview.

    Uses the same portal template the user was just viewing (sidebar and
    all), so the downloaded file looks exactly like what they saw — never
    a bare print layout that appears out of nowhere.
    """
    browser_context = dict(
        context,
        logo_url=logo.url if logo else '',
        booklet_back_url='',
        booklet_download_url='',
    )
    html = render_to_string('students/result_booklet.html', browser_context)
    response = HttpResponse(html, content_type='text/html')
    filename = f"result_{student.admission_number}_{term.name}"
    response['Content-Disposition'] = f'attachment; filename="{filename}.html"'
    return response