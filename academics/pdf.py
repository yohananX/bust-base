"""PDF generation for result booklets."""
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML

from .booklet import build_booklet_context


def render_result_booklet_pdf(student, term):
    """Render a result booklet PDF for a student in a given term.

    Returns an HttpResponse with PDF content, or None if no enrollment found.
    """
    context, enrollment = build_booklet_context(student, term, student.school)
    if not enrollment:
        return None

    logo_url = student.school.logo.url if student.school.logo else ''
    context['logo_url'] = logo_url

    html_string = render_to_string('academics/result_booklet.html', context)
    pdf_bytes = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"result_{student.admission_number}_{term.name}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response