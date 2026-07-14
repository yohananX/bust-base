from django.apps import AppConfig


class SchoolAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'school_admin'
    verbose_name = 'School Admin Portal'

    def ready(self):
        """Apply admin customizations after all apps are loaded."""
        from school.admin_setup import setup_admin
        setup_admin()
