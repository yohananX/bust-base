"""PDF generation for official fee payment receipts."""
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML


def render_receipt_pdf(payment):
    """Render an official fee receipt PDF for a payment.

    Returns an HttpResponse with PDF content, or None if PDF generation fails
    (the calling view is expected to handle None gracefully).
    """
    try:
        school = payment.invoice.school

        html_string = render_to_string('fees/receipt_pdf.html', {
            'payment': payment,
            'invoice': payment.invoice,
            'school': school,
        })
        pdf_bytes = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"receipt-{payment.reference}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception:
        return None