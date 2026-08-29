import re
from django.db import transaction
from django.utils import timezone

from .models import Student


CLASS_HEADER_MAP = {
    'RECEPTION': 'R',
    'NURSERY': 'N',
    'NURSERY 1': 'N1',
    'NURSERY 2': 'N2',
    'NURSERY 3': 'N3',
    'PRE-K': 'PK',
    'KINDERGARTEN': 'KG',
    'BASIC 1': 'B1',
    'BASIC 2': 'B2',
    'BASIC 3': 'B3',
    'BASIC 4': 'B4',
    'BASIC 5': 'B5',
    'BASIC 6': 'B6',
    'PRIMARY 1': 'P1',
    'PRIMARY 2': 'P2',
    'PRIMARY 3': 'P3',
    'PRIMARY 4': 'P4',
    'PRIMARY 5': 'P5',
    'PRIMARY 6': 'P6',
    'JSS 1': 'J1',
    'JSS 2': 'J2',
    'JSS 3': 'J3',
    'SS 1': 'S1',
    'SS 2': 'S2',
    'SS 3': 'S3',
}


def _map_class_to_header(school_class):
    """Map a SchoolClass to a compact class header for admission numbers."""
    if school_class is None:
        return 'XX'
    level = (school_class.level or '').strip().upper()
    name = (school_class.name or '').strip().upper()

    # Direct level match
    if level in CLASS_HEADER_MAP:
        return CLASS_HEADER_MAP[level]

    # Name-based match
    for key, header in CLASS_HEADER_MAP.items():
        if key in name:
            return header

    # Fallback: first letter(s) + first digit from name
    letters = ''.join(w[0] for w in name.split() if w).upper()
    digits = ''.join(c for c in name if c.isdigit())
    return f"{letters[:2]}{digits[:1]}" if letters or digits else 'XX'


def _next_admission_sequence(school, class_header, year_2d):
    """Return the next sequence number for the given school/class/year scope."""
    prefix = f"{school.short_code.upper()[:3]}{year_2d}{class_header}"
    matches = Student.objects.filter(
        school=school, admission_number__startswith=prefix,
    ).values_list('admission_number', flat=True)

    max_seq = 0
    for adm in matches:
        m = re.search(r'(\d{3})$', adm)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def generate_admission_number(school, school_class, year=None):
    """Generate a unique sequential admission number.

    Format: [SchoolCode][Year][ClassHeader][SequenceNumber]
    Example: GHS26B1001
    """
    if year is None:
        year = timezone.now().year

    school_code = school.short_code.upper()[:3]
    year_2d = str(year)[-2:]
    class_header = _map_class_to_header(school_class)
    prefix = f"{school_code}{year_2d}{class_header}"

    with transaction.atomic():
        Student.objects.select_for_update().filter(
            school=school, admission_number__startswith=prefix,
        )
        seq = _next_admission_sequence(school, class_header, year_2d)
        return f"{prefix}{seq:03d}"


def find_or_create_parent(school, name, email='', phone='', relationship='GUARDIAN'):
    """Find an existing parent by fingerprint or create a new one.

    Deduplication priority:
    1. email (case-insensitive)
    2. phone (exact)
    3. first_name + last_name (case-insensitive)
    """
    from accounts.models import User, Roles
    from students.models import StudentGuardianLink

    from accounts.utils import parse_full_name, strip_honorific
    first, middle, last = parse_full_name(strip_honorific(name))

    parent = None

    if email:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT, email__iexact=email.strip()
        ).first()

    if parent is None and phone:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT, phone_number__iexact=phone.strip()
        ).first()

    if parent is None and first:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT,
            first_name__iexact=first, last_name__iexact=last,
        ).first()

    if parent is None:
        from accounts.utils import unique_username
        username = unique_username(first, last)
        parent = User.objects.create_user(
            username=username,
            first_name=first,
            middle_name=middle,
            last_name=last,
            school=school,
            role=Roles.PARENT,
            email=email.strip(),
            phone_number=phone.strip(),
            must_change_password=True,
        )

    return parent
