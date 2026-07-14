"""
Custom admin configuration — app ordering and model visibility.

Called from school_admin/apps.py ready() hook,
after all apps including admin are loaded.
"""
import logging
logger = logging.getLogger(__name__)

APPS_TO_HIDE = {'django_q'}
MODELS_TO_HIDE = {'auth.Group'}
TARGET_ORDER = [
    'students',   # Daily: rosters, enrollments
    'fees',        # Daily/Weekly: invoices, payments
    'academics',   # Weekly: subjects, scores
    'payroll',     # Weekly/Monthly: payslips
    'finance',     # Monthly: projects, reports
    'notifications',  # As-needed: notification log
    'core',        # Rarely: sessions, terms
    'accounts',    # Rarely: users
]

# Sentinel to prevent double-patching
_PATCHED = False


def setup_admin():
    """Reorder admin apps and hide internal models. Idempotent."""
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    from django.contrib.admin.sites import AdminSite

    original = AdminSite.get_app_list

    def ordered_get_app_list(site_instance, request):
        """Order apps by workflow, filtering out noise models."""
        app_list = original(site_instance, request)

        # Filter out hidden apps entirely
        app_list = [a for a in app_list if a['app_label'] not in APPS_TO_HIDE]

        # Filter hidden models from remaining apps
        for app in app_list:
            app['models'] = [
                m for m in app.get('models', [])
                if f"{app['app_label']}.{m['object_name']}" not in MODELS_TO_HIDE
            ]

        # Reorder
        app_dict = {app['app_label']: app for app in app_list}
        ordered = []
        seen = set()
        for label in TARGET_ORDER:
            if label in app_dict:
                ordered.append(app_dict[label])
                seen.add(label)

        for app in app_list:
            if app['app_label'] not in seen:
                ordered.append(app)

        return ordered

    AdminSite.get_app_list = ordered_get_app_list
    logger.info("Admin setup: reordered %d apps, hidden %d apps + %d models",
                len(TARGET_ORDER), len(APPS_TO_HIDE), len(MODELS_TO_HIDE))
