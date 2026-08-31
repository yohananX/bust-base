import csv
import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.models import User, Roles
from accounts.utils import generate_username
from academics.models import Subject
from core.models import AcademicSession
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from students.utils import generate_admission_number, find_or_create_parent


def _generate_code(name):
    """Generate a subject code from a name.

    'English Studies' -> 'ENG', 'Basic Science' -> 'BSCI', 'Mathematics' -> 'MATH'
    """
    words = name.strip().split()
    if len(words) == 1:
        code = words[0][:4].upper()
    else:
        code = ''.join(w[0] for w in words)[:6].upper()
    return code


def _map_gender(raw):
    """Map short gender codes to model values."""
    if not raw:
        return 'MALE'
    raw = raw.strip().upper()
    if raw in ('M', 'MALE'):
        return 'MALE'
    if raw in ('F', 'FEMALE'):
        return 'FEMALE'
    return 'MALE'


class BaseImporter:
    """Base class for CSV importers."""

    def __init__(self, school, dry_run=False, verbose=False):
        self.school = school
        self.dry_run = dry_run
        self.verbose = verbose
        self._counter = 0

    def import_csv(self, file_path):
        """Override in subclasses."""
        raise NotImplementedError

    def _read_csv(self, file_path):
        """Read CSV and return list of dicts."""
        rows = []
        with open(file_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({k: v.strip() if v else '' for k, v in row.items()})
        return rows


class ClassImporter(BaseImporter):
    """Import classes from CSV.

    CSV columns: name, section
    Maps section -> level.
    """

    def import_csv(self, file_path):
        rows = self._read_csv(file_path)
        total = len(rows)
        created = 0
        skipped = 0
        errors = []

        for i, row in enumerate(rows, start=1):
            name = row.get('name', '').strip()
            section = row.get('section', '').strip()

            if not name:
                errors.append({'row': i, 'message': 'Missing class name'})
                continue

            # Use section as level; fall back to class name
            level = section if section else name

            if SchoolClass.objects.filter(school=self.school, name=name).exists():
                skipped += 1
                if self.verbose:
                    self._log(f"Row {i}: SKIP — class '{name}' already exists")
                continue

            if not self.dry_run:
                SchoolClass.objects.create(
                    school=self.school,
                    name=name,
                    level=level,
                )
            created += 1
            if self.verbose:
                self._log(f"Row {i}: CREATED — '{name}' (level: {level})")

        return {
            'total': total,
            'created': created,
            'skipped': skipped,
            'errors': errors,
        }

    def _log(self, msg):
        print(msg)


class SubjectImporter(BaseImporter):
    """Import subjects from CSV.

    CSV columns: class_name, subject_name
    Looks up SchoolClass by name (case-insensitive), auto-generates code.
    """

    def import_csv(self, file_path):
        rows = self._read_csv(file_path)
        total = len(rows)
        created = 0
        skipped = 0
        errors = []

        for i, row in enumerate(rows, start=1):
            class_name = row.get('class_name', '').strip()
            subject_name = row.get('subject_name', '').strip()

            if not class_name:
                errors.append({'row': i, 'message': 'Missing class_name'})
                continue
            if not subject_name:
                errors.append({'row': i, 'message': 'Missing subject_name'})
                continue

            # Case-insensitive lookup for class
            school_class = SchoolClass.objects.filter(
                school=self.school,
                name__iexact=class_name,
            ).first()

            if not school_class:
                errors.append({'row': i, 'message': f"Class '{class_name}' not found"})
                continue

            code = _generate_code(subject_name)

            if Subject.objects.filter(school=self.school, name__iexact=subject_name).exists():
                skipped += 1
                if self.verbose:
                    self._log(f"Row {i}: SKIP — subject '{subject_name}' already exists")
                continue

            base_code = code
            suffix = 1
            while Subject.objects.filter(school=self.school, code=code).exists():
                code = f'{base_code}{suffix}'
                suffix += 1

            if not self.dry_run:
                subject = Subject.objects.create(
                    school=self.school,
                    name=subject_name,
                    code=code,
                )
                ClassSubject.objects.create(
                    school=self.school,
                    subject=subject,
                    school_class=school_class,
                )
            created += 1
            if self.verbose:
                self._log(f"Row {i}: CREATED — '{subject_name}' (code: {code})")

        return {
            'total': total,
            'created': created,
            'skipped': skipped,
            'errors': errors,
        }

    def _log(self, msg):
        print(msg)


class StudentImporter(BaseImporter):
    """Import students from CSV.

    CSV columns: first_name, last_name, username, date_of_birth, gender,
                 parent_name, parent_email, parent_phone, class_name
    """

    def import_csv(self, file_path):
        rows = self._read_csv(file_path)
        total = len(rows)
        created = 0
        skipped = 0
        errors = []

        # Get current academic session for enrollment
        current_session = AcademicSession.objects.filter(
            school=self.school, is_current=True,
        ).first()

        today = timezone.now().date()

        for i, row in enumerate(rows, start=1):
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            username = row.get('username', '').strip()
            dob_raw = row.get('date_of_birth', '').strip()
            gender_raw = row.get('gender', '').strip()
            parent_name = row.get('parent_name', '').strip()
            parent_email = row.get('parent_email', '').strip()
            parent_phone = row.get('parent_phone', '').strip()
            class_name = row.get('class_name', '').strip()

            # Validate required fields
            if not first_name:
                errors.append({'row': i, 'message': 'Missing first_name'})
                continue
            if not last_name:
                errors.append({'row': i, 'message': 'Missing last_name'})
                continue

            # Auto-generate username if missing
            if not username:
                username = generate_username(first_name, last_name)

            # Skip if username already exists
            if User.objects.filter(username=username).exists():
                skipped += 1
                if self.verbose:
                    self._log(f"Row {i}: SKIP — username '{username}' already exists")
                continue

            # Parse date of birth — optional, defaults to 2010-01-01
            dob = None
            if dob_raw:
                try:
                    dob = date.fromisoformat(dob_raw)
                except ValueError:
                    errors.append({'row': i, 'message': f"Invalid date_of_birth: '{dob_raw}'"})
                    continue
            else:
                dob = date(2010, 1, 1)

            # Look up class
            school_class = None
            if class_name:
                school_class = SchoolClass.objects.filter(
                    school=self.school, name__iexact=class_name,
                ).first()
                if not school_class:
                    errors.append({'row': i, 'message': f"Class '{class_name}' not found"})
                    continue

            # Generate admission number
            admission_number = generate_admission_number(self.school, school_class)

            if not self.dry_run:
                with transaction.atomic():
                    # Create user
                    user = User.objects.create_user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        school=self.school,
                        role=Roles.STUDENT,
                    )

                    # Create student profile
                    student = Student.objects.create(
                        school=self.school,
                        user=user,
                        admission_number=admission_number,
                        date_of_birth=dob,
                        gender=_map_gender(gender_raw),
                        admission_date=today,
                    )

                    # Enroll in class if class found and session exists
                    if school_class and current_session:
                        ClassEnrollment.objects.create(
                            school=self.school,
                            student=student,
                            school_class=school_class,
                            session=current_session,
                        )
                        from fees.generation import generate_invoice_for_current_term
                        generate_invoice_for_current_term(student)

                    # Create parent/guardian(s). Supports two formats:
                    # 1. Repeated columns: guardian_1_name, guardian_1_email, ...
                    # 2. Single delimited column: guardians="Jane Doe|jane@test.com|08011111111|MOTHER;John Doe|..."
                    guardian_entries = []

                    # Collect from repeated columns first
                    idx = 1
                    while True:
                        g_name = row.get(f'guardian_{idx}_name', '').strip()
                        g_email = row.get(f'guardian_{idx}_email', '').strip()
                        g_phone = row.get(f'guardian_{idx}_phone', '').strip()
                        g_rel = row.get(f'guardian_{idx}_relationship', 'GUARDIAN').strip().upper()
                        if not g_name and not g_email and not g_phone:
                            break
                        guardian_entries.append({
                            'name': g_name,
                            'email': g_email,
                            'phone': g_phone,
                            'relationship': g_rel or 'GUARDIAN',
                        })
                        idx += 1

                    # Fallback: parse delimited guardians column
                    if not guardian_entries:
                        raw = row.get('guardians', '').strip()
                        if raw:
                            for chunk in raw.split(';'):
                                chunk = chunk.strip()
                                if not chunk:
                                    continue
                                parts = [p.strip() for p in chunk.split('|')]
                                guardian_entries.append({
                                    'name': parts[0] if len(parts) > 0 else '',
                                    'email': parts[1] if len(parts) > 1 else '',
                                    'phone': parts[2] if len(parts) > 2 else '',
                                    'relationship': parts[3].upper() if len(parts) > 3 else 'GUARDIAN',
                                })

                    # Legacy single-column fallback
                    if not guardian_entries and (parent_name or parent_email or parent_phone):
                        guardian_entries.append({
                            'name': parent_name,
                            'email': parent_email,
                            'phone': parent_phone,
                            'relationship': 'OTHER',
                        })

                    for g_idx, entry in enumerate(guardian_entries):
                        name = entry['name']
                        email = entry['email']
                        phone = entry['phone']
                        relationship = entry['relationship']

                        if not name and not email and not phone:
                            continue

                        parent_user = find_or_create_parent(
                            self.school, name, email=email, phone=phone,
                            relationship=relationship,
                        )

                        StudentGuardianLink.objects.create(
                            school=self.school,
                            student=student,
                            guardian=parent_user,
                            relationship=relationship,
                            is_primary_contact=(g_idx == 0),
                        )

            created += 1
            if self.verbose:
                self._log(f"Row {i}: CREATED — {first_name} {last_name} ({username})")

        return {
            'total': total,
            'created': created,
            'skipped': skipped,
            'errors': errors,
        }

    def _log(self, msg):
        print(msg)


class StaffImporter(BaseImporter):
    """Import staff from CSV.

    CSV columns: first_name, last_name, username, email, phone_number, role
    """

    def import_csv(self, file_path):
        rows = self._read_csv(file_path)
        total = len(rows)
        created = 0
        skipped = 0
        errors = []

        for i, row in enumerate(rows, start=1):
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            username = row.get('username', '').strip()
            email = row.get('email', '').strip()
            phone_number = row.get('phone_number', '').strip()
            role = row.get('role', '').strip().upper()

            if not first_name:
                errors.append({'row': i, 'message': 'Missing first_name'})
                continue
            if not last_name:
                errors.append({'row': i, 'message': 'Missing last_name'})
                continue

            # Auto-generate username if missing
            if not username:
                username = generate_username(first_name, last_name)

            # Skip if username already exists
            if User.objects.filter(username=username).exists():
                skipped += 1
                if self.verbose:
                    self._log(f"Row {i}: SKIP — username '{username}' already exists")
                continue

            # Default role to TEACHER
            if role not in dict(Roles.CHOICES):
                role = Roles.TEACHER

            if not self.dry_run:
                User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone_number=phone_number,
                    school=self.school,
                    role=role,
                )

            created += 1
            if self.verbose:
                self._log(f"Row {i}: CREATED — {first_name} {last_name} ({username})")

        return {
            'total': total,
            'created': created,
            'skipped': skipped,
            'errors': errors,
        }

    def _log(self, msg):
        print(msg)
