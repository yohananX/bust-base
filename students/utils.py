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

    Returns tuple of ``(parent_user, was_created)``.
    """
    from accounts.models import User, Roles
    from students.models import StudentGuardianLink

    from accounts.utils import parse_full_name, strip_honorific
    first, middle, last = parse_full_name(strip_honorific(name))

    parent = None
    matched_by = None

    if email:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT, email__iexact=email.strip()
        ).first()
        if parent:
            matched_by = 'email'

    if parent is None and phone:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT, phone_number__iexact=phone.strip()
        ).first()
        if parent:
            matched_by = 'phone'

    if parent is None and first:
        parent = User.objects.filter(
            school=school, role=Roles.PARENT,
            first_name__iexact=first, last_name__iexact=last,
        ).first()
        if parent:
            matched_by = 'name'

    if parent is None:
        from accounts.utils import generate_username
        username = generate_username(first, last)
        base = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
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
        matched_by = 'created'

    return parent, matched_by == 'created'


def validate_guardian_form(post_data):
    """Check for duplicate guardian entries in form POST data.

    Returns a list of error messages. An empty list means no duplicates.
    """
    guardian_rows = []
    guardian_index = 0
    while True:
        name = post_data.get(f'guardian_{guardian_index}_name', '').strip()
        email = post_data.get(f'guardian_{guardian_index}_email', '').strip()
        phone = post_data.get(f'guardian_{guardian_index}_phone', '').strip()
        if not name and not email and not phone:
            break
        guardian_rows.append({
            'name': name,
            'email': email,
            'phone': phone,
            'index': guardian_index,
        })
        guardian_index += 1

    form_errors = []
    for i, row in enumerate(guardian_rows):
        for j, other in enumerate(guardian_rows[:i]):
            if (
                (row['email'] and other['email'] and row['email'] == other['email']) or
                (row['phone'] and other['phone'] and row['phone'] == other['phone']) or
                (row['name'] and other['name'] and row['name'].lower() == other['name'].lower())
            ):
                form_errors.append(
                    f"Guardian {row['index'] + 1} appears to duplicate guardian {other['index'] + 1}."
                )

    return form_errors


def create_guardians_from_form(student, school, post_data):
    """Create guardian links from form POST data.

    Reads guardian_0_name/email/phone/relationship/occupation/address/
    authorized_pickup_person, guardian_1_*, etc. until a row with all three
    core fields empty is encountered. The first guardian is marked as
    primary contact.

    Returns tuple of ``(created_links, warnings)`` where ``warnings`` is a
    list of human-readable strings describing when an existing guardian was
    reused instead of creating a new one.
    """
    from students.models import StudentGuardianLink

    created = []
    warnings = []
    guardian_index = 0
    while True:
        name = post_data.get(f'guardian_{guardian_index}_name', '').strip()
        email = post_data.get(f'guardian_{guardian_index}_email', '').strip()
        phone = post_data.get(f'guardian_{guardian_index}_phone', '').strip()
        relationship = post_data.get(f'guardian_{guardian_index}_relationship', 'GUARDIAN')
        occupation = post_data.get(f'guardian_{guardian_index}_occupation', '').strip()
        address = post_data.get(f'guardian_{guardian_index}_address', '').strip()
        authorized_pickup_person = post_data.get(f'guardian_{guardian_index}_authorized_pickup_person', '').strip()

        if not name and not email and not phone:
            break

        if name:
            parent_user, was_created = find_or_create_parent(
                school, name, email=email, phone=phone, relationship=relationship
            )
            if was_created:
                warnings.append(
                    f"New guardian account created for {parent_user.get_full_name() or parent_user.username}."
                )
            else:
                warnings.append(
                    f"Reused existing guardian: {parent_user.get_full_name() or parent_user.username} ({email or phone or 'name match'})."
                )
            created.append(StudentGuardianLink.objects.create(
                school=school,
                student=student,
                guardian=parent_user,
                relationship=relationship,
                is_primary_contact=(guardian_index == 0),
                occupation=occupation,
                address=address,
                authorized_pickup_person=authorized_pickup_person,
            ))

        guardian_index += 1

    return created, warnings
