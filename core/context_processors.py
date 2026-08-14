"""Template context processors shared across portals."""
from accounts.models import Roles


def _nav_item(path, label, url, icon, section=None, exact=False, badge=None):
    if exact:
        is_active = path == url
    else:
        is_active = path == url or path.startswith(url)
    return {
        'label': label,
        'url': url,
        'icon': icon,
        'section': section,
        'active': is_active,
        'badge': badge or 0,
    }


def _badge_counts(request, role):
    """Small per-role live counts for sidebar badges (0 = no badge)."""
    school = getattr(request, 'school', None)
    if not school:
        return {}
    badges = {}

    if role == Roles.ADMIN:
        from academics.models import Score
        badges['/school-admin/results/review/'] = Score.objects.filter(
            school=school, moderation_status='PENDING',
        ).count()
        from fees.models import Invoice, Payment
        from fees.selectors import invoices_with_balance
        invoices = invoices_with_balance(Invoice.objects.filter(school=school))
        badges['/school-admin/invoices/'] = sum(
            1 for inv in invoices if inv.balance_annotated > 0
        )
        badges['/school-admin/fees/pending/'] = Payment.objects.filter(
            school=school, status='PENDING', method='BANK_TRANSFER',
        ).count()
    elif role == Roles.TEACHER:
        from academics.models import TeacherAssignment
        badges['/teacher/assignments/'] = TeacherAssignment.objects.filter(
            school=school, teacher=request.user,
        ).count()
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
    'Staff & Users': 'id-card',
    'Academics': 'graduation-cap',
    'Fees': 'receipt',
    'Payroll': 'coins',
    'Finance': 'bar-chart-3',
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
        _nav_item(path, 'Staff', '/school-admin/staff/', 'briefcase', section='Staff & Users'),
        _nav_item(path, 'Users', '/school-admin/users/', 'user-cog', section='Staff & Users'),
        _nav_item(path, 'Subjects', '/school-admin/subjects/', 'book-open', section='Academics'),
        _nav_item(path, 'Assignments', '/school-admin/assignments/', 'clipboard-list', section='Academics'),
        _nav_item(path, 'Scores', '/school-admin/scores/', 'table', section='Academics'),
        _nav_item(path, 'Review', '/school-admin/results/review/', 'eye', section='Academics', badge=badges.get('/school-admin/results/review/')),
        _nav_item(path, 'Publish', '/school-admin/results/publish/', 'send', section='Academics'),
        _nav_item(path, 'Fees & Pricing', '/school-admin/fees/', 'tags', section='Fees'),
        _nav_item(path, 'Invoices', '/school-admin/invoices/', 'file-text', section='Fees', badge=badges.get('/school-admin/invoices/')),
        _nav_item(path, 'Outstanding Fees', '/school-admin/fees/outstanding/', 'alert-circle', section='Fees'),
        _nav_item(path, 'Pending Payments', '/school-admin/fees/pending/', 'clock', section='Fees', badge=badges.get('/school-admin/fees/pending/')),
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
        _nav_item(path, 'My Assignments', '/teacher/assignments/', 'clipboard-list', badge=badges.get('/teacher/assignments/')),
        _nav_item(path, 'My Payslips', '/teacher/payslips/', 'banknote'),
    ]

    student_nav = [
        _nav_item(path, 'Dashboard', '/student/', 'layout-dashboard', exact=True),
        _nav_item(path, 'Pay Fees', '/student/pay/', 'banknote'),
        _nav_item(path, 'My Results', '/student/results/', 'file-text'),
        _nav_item(path, 'Change Password', '/student/password/', 'key-round'),
    ]

    parent_nav = [
        _nav_item(path, 'Dashboard', '/parent/', 'layout-dashboard', exact=True),
        _nav_item(path, 'My Children', '/parent/children/', 'users'),
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
