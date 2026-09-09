"""Setup status checks for the admin dashboard.

Each check function takes a ``School`` (tenant) and returns an alert dict
or ``None``.  Alerts are collected, sorted by priority (lower = shown first),
and truncated to ``MAX_DASHBOARD_ALERTS``.

The checks cover the ten most critical pieces of school configuration —
they appear on the dashboard when the value is genuinely empty/missing and
disappear automatically once the admin fills in the missing data.
"""
from core.models import AcademicSession, Term
from academics.models import Subject, TeacherAssignment
from students.models import SchoolClass, Student
from fees.models import FeeCategory, FeePrice
from payroll.models import StaffProfile


MAX_DASHBOARD_ALERTS = 5

# Priority constants — lower numbers float to the top.
PRIORITY_SCHOOL_PROFILE = 1
PRIORITY_SESSION = 10
PRIORITY_TERM = 20
PRIORITY_CLASSES = 30
PRIORITY_SUBJECTS = 40
PRIORITY_FEE_CATEGORIES = 50
PRIORITY_FEE_PRICES = 60
PRIORITY_TEACHER_ASSIGNMENTS = 70
PRIORITY_STUDENTS = 80
PRIORITY_STAFF = 90


def _alert(key, title, description, icon, color, action_url, action_label, priority):
    """Build a standardised alert dict consumed by the dashboard template."""
    return {
        'key': key,
        'title': title,
        'description': description,
        'icon': icon,
        'color': color,
        'action_url': action_url,
        'action_label': action_label,
        'priority': priority,
    }


# ── Individual checks ──────────────────────────────────────────────────────


def check_school_profile(school):
    """Alert when contact or bank details needed for receipts are missing."""
    missing = []
    if not school.phone:
        missing.append('phone number')
    if not school.email:
        missing.append('email')
    if not school.bank_name:
        missing.append('bank name')
    if not school.account_name:
        missing.append('account name')
    if not school.account_number:
        missing.append('account number')
    if missing:
        return _alert(
            key='school_profile',
            title='School profile is incomplete',
            description='Missing ' + ', '.join(missing) + '. These are needed on receipts and invoices.',
            icon='settings',
            color='danger',
            action_url='school_admin:school_settings',
            action_label='Complete profile',
            priority=PRIORITY_SCHOOL_PROFILE,
        )
    return None


def check_current_session(school):
    """Alert when no academic session is marked as current."""
    if not AcademicSession.objects.filter(school=school, is_current=True).exists():
        return _alert(
            key='no_session',
            title='No active academic session',
            description='Create and activate an academic session to organise terms and enrollments.',
            icon='calendar',
            color='danger',
            action_url='school_admin:session_list',
            action_label='Set up sessions',
            priority=PRIORITY_SESSION,
        )
    return None


def check_current_term(school):
    """Alert when no term is marked as current."""
    if not Term.objects.filter(school=school, is_current=True).exists():
        return _alert(
            key='no_term',
            title='No current term set',
            description='Mark a term as current to enable enrollment, scoring, and results.',
            icon='calendar-days',
            color='danger',
            action_url='school_admin:session_list',
            action_label='Set current term',
            priority=PRIORITY_TERM,
        )
    return None


def check_active_classes(school):
    """Alert when no active classes exist."""
    if not SchoolClass.objects.filter(school=school, is_active=True).exists():
        return _alert(
            key='no_classes',
            title='No classes configured',
            description='Classes are required to enrol students and assign subjects.',
            icon='layers',
            color='warning',
            action_url='school_admin:class_list',
            action_label='Add classes',
            priority=PRIORITY_CLASSES,
        )
    return None


def check_subjects(school):
    """Alert when no subjects are defined."""
    if not Subject.objects.filter(school=school).exists():
        return _alert(
            key='no_subjects',
            title='No subjects defined',
            description='Subjects are needed to create teacher assignments and record scores.',
            icon='book-open',
            color='warning',
            action_url='school_admin:subject_list',
            action_label='Add subjects',
            priority=PRIORITY_SUBJECTS,
        )
    return None


def check_fee_categories(school):
    """Alert when no fee categories are defined."""
    if not FeeCategory.objects.filter(school=school).exists():
        return _alert(
            key='no_fee_categories',
            title='No fee categories',
            description='Define fee categories before setting prices or generating invoices.',
            icon='tag',
            color='warning',
            action_url='school_admin:fee_category_list',
            action_label='Add fee categories',
            priority=PRIORITY_FEE_CATEGORIES,
        )
    return None


def check_fee_prices(school):
    """Alert when no fee prices exist for the current term."""
    current_term = Term.objects.filter(school=school, is_current=True).first()
    if current_term is None:
        # The session/term check already covers this situation.
        return None
    if not FeePrice.objects.filter(school=school, term=current_term, is_active=True).exists():
        return _alert(
            key='no_fee_prices',
            title='No fee prices for current term',
            description=f'Set up fee prices for {current_term.name} to generate invoices.',
            icon='tag',
            color='warning',
            action_url='school_admin:fee_pricing_list',
            action_label='Set up pricing',
            priority=PRIORITY_FEE_PRICES,
        )
    return None


def check_teacher_assignments(school):
    """Alert when no teacher assignments exist for the current session."""
    current_session = AcademicSession.objects.filter(school=school, is_current=True).first()
    if current_session is None:
        # The session check already covers this situation.
        return None
    if not TeacherAssignment.objects.filter(school=school, session=current_session).exists():
        return _alert(
            key='no_teacher_assignments',
            title='No teacher assignments',
            description=f'Assign teachers to subjects and classes for {current_session.name}.',
            icon='user-check',
            color='warning',
            action_url='school_admin:assignment_list',
            action_label='Assign teachers',
            priority=PRIORITY_TEACHER_ASSIGNMENTS,
        )
    return None


def check_students(school):
    """Alert when no active students are enrolled."""
    if not Student.objects.filter(school=school, status=Student.ACTIVE).exists():
        return _alert(
            key='no_students',
            title='No student records',
            description='Add students to start enrolment, fees, and academic tracking.',
            icon='users',
            color='info',
            action_url='school_admin:student_list',
            action_label='Add students',
            priority=PRIORITY_STUDENTS,
        )
    return None


def check_staff_profiles(school):
    """Alert when no staff profiles exist."""
    if not StaffProfile.objects.filter(school=school).exists():
        return _alert(
            key='no_staff',
            title='No staff profiles',
            description='Create staff profiles to enable payroll processing.',
            icon='graduation-cap',
            color='info',
            action_url='school_admin:staff_list',
            action_label='Add staff',
            priority=PRIORITY_STAFF,
        )
    return None


# ── Registry & runner ──────────────────────────────────────────────────────

CHECKS = [
    check_school_profile,
    check_current_session,
    check_current_term,
    check_active_classes,
    check_subjects,
    check_fee_categories,
    check_fee_prices,
    check_teacher_assignments,
    check_students,
    check_staff_profiles,
]


def run_setup_checks(school, max_alerts=MAX_DASHBOARD_ALERTS):
    """Run all setup checks for *school* and return the highest-priority alerts.

    Returns a list of alert dicts sorted by priority (ascending) and truncated
    to *max_alerts* entries.  Returns an empty list when everything is configured.
    """
    alerts = []
    for check_fn in CHECKS:
        alert = check_fn(school)
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda a: a['priority'])
    return alerts[:max_alerts]
