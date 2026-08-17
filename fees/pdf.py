"""PDF generation for official fee payment receipts."""
import logging

from django.http import HttpResponse
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def render_receipt_pdf(payment, request=None):
    """Render an official fee receipt PDF for a payment.

    WeasyPrint is imported lazily so a missing native runtime (e.g. GTK/Pango
    libraries on Windows) never crashes the download. When WeasyPrint is
    unavailable, the receipt is served as the same receipt page the user
    already previewed, so the look stays constant (browser Print → PDF).

    Returns an HttpResponse, or None if the payment has no invoice to render
    against (the calling view is expected to handle None gracefully).
    """
    if payment.invoice is None:
        return None

    school = payment.invoice.school

    try:
        from weasyprint import HTML
    except Exception as exc:  # import-time failure (missing native libs)
        logger.warning("WeasyPrint unavailable (%s); serving printable HTML receipt", exc)
        return _printable_html_response(payment, school, request)

    html_string = render_to_string('fees/receipt_pdf.html', {
        'payment': payment,
        'invoice': payment.invoice,
        'school': school,
    })

    try:
        pdf_bytes = HTML(string=html_string).write_pdf()
    except Exception as exc:  # render-time failure (missing native libs)
        logger.warning("WeasyPrint render failed (%s); serving printable HTML receipt", exc)
        return _printable_html_response(payment, school, request)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"receipt-{payment.reference}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _printable_html_response(payment, school, request=None):
    """Serve the receipt preview page itself (browser Print → PDF).

    The request is passed through so context processors run — the page must
    render exactly like the preview, sidebar and all.
    """
    invoice = payment.invoice
    student = payment.student
    if student is None and invoice is not None:
        student = invoice.student

    html = render_to_string(
        'fees/receipt_view.html',
        {
            'payment': payment,
            'invoice': invoice,
            'receipt': getattr(payment, 'receipt', None),
            'student': student,
            'term': invoice.term if invoice is not None else None,
            'school': school,
        },
        request=request,
    )
    response = HttpResponse(html, content_type='text/html')
    filename = f"receipt-{payment.reference}"
    response['Content-Disposition'] = f'inline; filename="{filename}.html"'
    return response