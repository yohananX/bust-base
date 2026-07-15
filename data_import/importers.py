import csv
import re
import time
from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.models import User, Roles
from academics.models import Subject
from core.models import AcademicSession
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink


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


def _generate_username(first_name, last_name):
    """Generate a lowercase username with no spaces from first and last name."""
    base = f"{first_name}{last_name}".lower().replace(' ', '').replace('-', '').replace('.', '')
    return re.sub(r'[^a-z0-9]', '', base)


def _generate_admission_number():
    """Generate a unique admission number using timestamp."""
    ts = int(time.time() * 1000) % 10_000_000
    return f"STU-{ts:07d}"


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

            # Check if subject with this code already exists for this school
            if Subject.objects.filter(school=self.school, code=code).exists():
                skipped += 1
                if self.verbose:
                    self._log(f"Row {i}: SKIP — subject code '{code}' already exists")
                continue

            if not self.dry_run:
                Subject.objects.create(
                    school=self.school,
                    name=subject_name,
                    code=code,
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
                username = _generate_username(first_name, last_name)

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
            admission_number = _generate_admission_number()

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

                    # Create parent/guardian if parent_name is provided
                    if parent_name:
                        parent_parts = parent_name.split(None, 1)
                        parent_first = parent_parts[0]
                        parent_last = parent_parts[1] if len(parent_parts) > 1 else ''
                        parent_username = _generate_username(parent_first, parent_last)

                        # Ensure parent_username is unique
                        base_parent_username = parent_username
                        counter = 1
                        while User.objects.filter(username=parent_username).exists():
                            parent_username = f"{base_parent_username}{counter}"
                            counter += 1

                        parent_user = User.objects.create_user(
                            username=parent_username,
                            first_name=parent_first,
                            last_name=parent_last,
                            school=self.school,
                            role=Roles.PARENT,
                        )

                        if parent_email:
                            parent_user.email = parent_email
                        if parent_phone:
                            parent_user.phone_number = parent_phone
                        if parent_email or parent_phone:
                            parent_user.save()

                        # Determine relationship (guess from name or default)
                        relationship = 'OTHER'
                        if parent_first.lower().startswith(('mr', 'man', 'dad', 'pa')):
                            relationship = 'FATHER'
                        elif parent_first.lower().startswith(('mrs', 'miss', 'mum', 'mom', 'ma')):
                            relationship = 'MOTHER'

                        StudentGuardianLink.objects.create(
                            school=self.school,
                            student=student,
                            guardian=parent_user,
                            relationship=relationship,
                            is_primary_contact=True,
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
                username = _generate_username(first_name, last_name)

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
