"""Server-side validation for uploaded bank-transfer proofs.

The checkout form's ``accept`` attribute is client-side only; these checks
reject junk uploads (renamed files, executables, oversized blobs) before
anything is written to disk.
"""
from django.core.exceptions import ValidationError

MAX_PROOF_SIZE = 5 * 1024 * 1024  # 5 MB

_IMAGE_SIGNATURES = (
    (b'\xff\xd8\xff', 'JPEG'),
    (b'\x89PNG\r\n\x1a\n', 'PNG'),
    (b'WEBP', 'WebP'),  # RIFF container — checked at offset 8
)

PDF_SIGNATURE = b'%PDF'


def validate_proof_file(file):
    """Reject anything that is not a small image or PDF.

    Reads a few leading bytes (magic number) rather than trusting the
    declared extension, so renaming an arbitrary file won't pass.
    """
    if file is None:
        return

    if file.size > MAX_PROOF_SIZE:
        raise ValidationError(
            'The proof file is too large (max 5 MB). Please upload a smaller screenshot or PDF.'
        )

    head = file.read(16)
    file.seek(0)

    if head.startswith(PDF_SIGNATURE):
        return
    for signature, label in _IMAGE_SIGNATURES:
        if signature == b'WEBP':
            if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                return
        elif head.startswith(signature):
            return

    raise ValidationError(
        'That file does not look like a proof of payment. '
        'Upload a screenshot or PDF (JPG, PNG, WebP, PDF).'
    )