"""Custom admin configuration — app ordering, model hiding."""
import types
from django.contrib import admin

# ── App reordering ──────────────────────────────────────────────────────

_original_get_app_list = admin.site.get_app_list

def _ordered_get_app_list(site, request):
    """Return apps in workflow order instead of alphabetical."""
    app_list = _original_get_app_list(site, request)
    app_dict = {app['app_label']: app for app in app_list}

    # Workflow order: daily-use first, technical internals last
    ordered_labels = [
        'students',      # Daily: rosters, enrollments
        'fees',           # Daily/Weekly: invoices, payments
        'academics',      # Weekly: subjects, scores
        'payroll',        # Weekly/Monthly: payslips
        'finance',        # Monthly: projects, reports
        'notifications',  # As-needed: notification log
        'core',           # Rarely: sessions, terms
        'accounts',       # Rarely: users
    ]

    ordered = []
    seen = set()
    for label in ordered_labels:
        if label in app_dict:
            ordered.append(app_dict[label])
            seen.add(label)

    # Append remaining apps (django_q, auth, contenttypes, sessions, etc.)
    for app in app_list:
        if app['app_label'] not in seen:
            ordered.append(app)
            seen.add(app['app_label'])

    return ordered

admin.site.get_app_list = types.MethodType(_ordered_get_app_list, admin.site)

# ── Hide Django Q models from admin nav ────────────────────────────────
# Django Q internal task models are noise for school admins

from django_q.models import Task, OrmQ, Schedule, Success, Failure
for model in [Task, OrmQ, Schedule, Success, Failure]:
    try:
        admin.site.unregister(model)
    except admin.sites.NotRegistered:
        pass

# ── Hide Auth Groups (unused — permission system is role-field-based) ──

from django.contrib.auth.models import Group
try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass
