"""Template context processors shared across portals."""
from accounts.models import Roles
from lessons.models import LessonEnrollment
from students.models import StudentGuardianLink


def login_school(request):
    """Resolve the school for anonymous entry pages (login / logged out).

    Subdomain short_code matches first (Host header), then falls back to
    the first active school so shared/dev hosts still get correct branding.
    Authenticated requests use ``request.school`` instead.
    """
    if getattr(request, 'user', None) and request.user.is_authenticated:
        return {}

    from django.core.exceptions import DisallowedHost

    from core.models import School

    try:
        host = request.get_host().split(':')[0].lower()
    except DisallowedHost:
        host = ''
    code = host.split('.')[0] if '.' in host else ''
    school = None
    if code:
        school = School.objects.filter(short_code=code, is_active=True).first()
    if school is None:
        school = (
            School.objects.filter(is_active=True).order_by('id').first()
        )
    return {'login_school': school}


def _nav_item(path, label, url, icon, section=None, exact=False, badge=None):
    return {
        'label': label,
        'url': url,
        'icon': icon,
        'section': section,
        'exact': exact,
        'badge': badge or 0,
    }


def _mark_active(items, path):
    """Highlight the single best-matching item.

    Exact items match only on equality; others match on URL prefix.
    When several match (e.g. /school-admin/fees/ and
    /school-admin/fees/outstanding/), the longest URL wins so sibling
    subpages never light up their parent.
    """
    matches = []
    for item in items:
        if item['exact']:
            if path == item['url']:
                matches.append(item)
        elif path == item['url'] or path.startswith(item['url']):
            matches.append(item)
    winner = max(matches, key=lambda i: len(i['url'])) if matches else None
    for item in items:
        item['active'] = item is winner


def _badge_counts(request, role):
    """Small per-role live counts for sidebar badges (0 = no badge)."""
    school = getattr(request, 'school', None)
    if not school:
        return {}
    badges = {}

    from core.stats import (
        outstanding_invoices,
        pending_score_review_count,
        pending_transfer_count,
    )

    if role == Roles.ADMIN:
        badges['/school-admin/results/review/'] = pending_score_review_count(school)
        invoices = outstanding_invoices(school)
        badges['/school-admin/invoices/'] = sum(
            1 for inv in invoices if inv.balance_annotated > 0
        )
        badges['/school-admin/fees/pending/'] = pending_transfer_count(school)
    elif role == Roles.PARENT:
        from students.models import StudentGuardianLink
        from fees.models import Invoice
        from fees.selectors import invoices_with_balance
        student_ids = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).values_list('student_id', flat=True)
        invoices = invoices_with_balance(
            Invoice.objects.filter(student_id__in=student_ids)
        )
        badges['/parent/invoices/'] = sum(
            1 for inv in invoices if inv.balance_annotated > 0
        )

    return badges


SECTION_ICONS = {
    'Students': 'school',
    'Academics': 'graduation-cap',
    'Fees': 'receipt',
    'Payroll': 'coins',
    'Finance': 'bar-chart-3',
    'Inventory': 'package',
    'System': 'server',
}


def sidebar_nav(request):
    """Role-scoped sidebar items for base.html, using real portal URLs."""
    if not request.user.is_authenticated:
        return {'sidebar_items': [], 'sidebar_sections': []}

    role = getattr(request.user, 'role', Roles.ADMIN)
    path = request.path
    badges = _badge_counts(request, role)

    admin_nav = [
        _nav_item(path, 'Dashboard', '/school-admin/', 'layout-dashboard', exact=True),
        _nav_item(path, 'Students', '/school-admin/students/', 'users', section='Students'),
        _nav_item(path, 'Classes', '/school-admin/classes/', 'building-2', section='Students'),
        _nav_item(path, 'Parents', '/school-admin/parents/', 'users-round', section='Students'),
        _nav_item(path, 'Staff', '/school-admin/staff/', 'briefcase'),
        _nav_item(path, 'Subjects', '/school-admin/subjects/', 'book-open', section='Academics'),
        _nav_item(path, 'Assignments', '/school-admin/assignments/', 'clipboard-list', section='Academics'),
        _nav_item(path, 'Scores', '/school-admin/scores/', 'table', section='Academics'),
        _nav_item(path, 'Review', '/school-admin/results/review/', 'eye', section='Academics', badge=badges.get('/school-admin/results/review/')),
        _nav_item(path, 'Publish', '/school-admin/results/publish/', 'send', section='Academics'),
        _nav_item(path, 'Extra Lessons', '/school-admin/lessons/', 'sun', section='Academics'),
        _nav_item(path, 'Fees & Pricing', '/school-admin/fees/', 'tags', section='Fees'),
        _nav_item(path, 'Invoices', '/school-admin/invoices/', 'file-text', section='Fees', badge=badges.get('/school-admin/invoices/')),
_nav_item(path, 'Fees Due', '/school-admin/fees/outstanding/', 'alert-circle', section='Fees'),
        _nav_item(path, 'Awaiting Confirmation', '/school-admin/fees/pending/', 'clock', section='Fees', badge=badges.get('/school-admin/fees/pending/')),
        _nav_item(path, 'Items', '/school-admin/inventory/items/', 'package', section='Inventory'),
        _nav_item(path, 'Procurement', '/school-admin/inventory/procurement/', 'package-plus', section='Inventory'),
        _nav_item(path, 'Transactions', '/school-admin/inventory/transactions/', 'history', section='Inventory'),
        _nav_item(path, 'Low Stock', '/school-admin/inventory/low-stock/', 'alert-triangle', section='Inventory'),
        _nav_item(path, 'Pay Grades', '/school-admin/payroll/grades/', 'banknote', section='Payroll'),
        _nav_item(path, 'Runs', '/school-admin/payroll/runs/', 'wallet', section='Payroll'),
        _nav_item(path, 'Projects', '/school-admin/finance/projects/', 'folder-kanban', section='Finance'),
        _nav_item(path, 'Import', '/school-admin/import/', 'upload', section='System'),
        _nav_item(path, 'Notifications', '/school-admin/notifications/', 'bell', section='System'),
        _nav_item(path, 'Sessions & Terms', '/school-admin/sessions/', 'calendar', section='System'),
        _nav_item(path, 'School Settings', '/school-admin/settings/', 'settings', section='System'),
    ]

    teacher_nav = [
        _nav_item(path, 'Dashboard', '/teacher/', 'layout-dashboard', exact=True),
        _nav_item(path, 'My Assignments', '/teacher/assignments/', 'clipboard-list'),
        _nav_item(path, 'My Extra Classes', '/teacher/lessons/', 'sun'),
        _nav_item(path, 'My Payslips', '/payroll/payslips/', 'banknote'),
    ]

    # The Extra Lessons tab is only shown once the user (or their children)
    # actually has a summer-school registration. External/walk-in summer
    # students have no portal login at all, and an existing student shouldn't
    # see the tab until the admin registers them for a lesson — so the tab is
    # gated on a real LessonEnrollment rather than always present.
    school = getattr(request, 'school', None)
    show_student_lessons = False
    show_parent_lessons = False
    if role == Roles.STUDENT and school:
        profile = getattr(request.user, 'student_profile', None)
        if profile:
            show_student_lessons = LessonEnrollment.objects.filter(
                school=school, student=profile,
            ).exclude(status=LessonEnrollment.Status.CANCELLED).exists()
    elif role == Roles.PARENT and school:
        child_ids = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).values_list('student_id', flat=True)
        show_parent_lessons = LessonEnrollment.objects.filter(
            school=school, student_id__in=child_ids,
        ).exclude(status=LessonEnrollment.Status.CANCELLED).exists()

    student_nav = [
        _nav_item(path, 'Dashboard', '/student/', 'layout-dashboard', exact=True),
        _nav_item(path, 'Pay Fees', '/student/pay/', 'banknote'),
    ]
    if show_student_lessons:
        student_nav.append(
            _nav_item(path, 'My Extra Lessons', '/student/extra-lessons/', 'sun'),
        )
    student_nav += [
        _nav_item(path, 'My Subjects', '/student/subjects/', 'book-open'),
        _nav_item(path, 'My Results', '/student/results/', 'file-text'),
        _nav_item(path, 'Change Password', '/student/password/', 'key-round'),
    ]

    parent_nav = [
        _nav_item(path, 'Dashboard', '/parent/', 'layout-dashboard', exact=True),
        _nav_item(path, 'My Children', '/parent/children/', 'users'),
    ]
    if show_parent_lessons:
        parent_nav.append(
            _nav_item(path, 'Extra Lessons', '/parent/extra-lessons/', 'sun'),
        )
    parent_nav += [
        _nav_item(path, 'Pay Fees', '/parent/pay/', 'banknote'),
        _nav_item(path, 'Invoices', '/parent/invoices/', 'credit-card', badge=badges.get('/parent/invoices/')),
    ]

    nav_map = {
        Roles.ADMIN: admin_nav,
        Roles.TEACHER: teacher_nav,
        Roles.STUDENT: student_nav,
        Roles.PARENT: parent_nav,
    }
    items = nav_map.get(role, admin_nav)
    _mark_active(items, path)

    sections = []
    for item in items:
        if sections and sections[-1]['section'] == item['section']:
            sections[-1]['items'].append(item)
        else:
            sections.append({
                'section': item['section'],
                'icon': SECTION_ICONS.get(item['section']),
                'items': [item],
            })

    return {'sidebar_items': items, 'sidebar_sections': sections}
