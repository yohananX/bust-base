# Command: Create a New Django App

Use this when the user asks to add a new module/system to the project.

## Steps

1. Run: `python manage.py startapp <app_name>`
2. Add `<app_name>` to `INSTALLED_APPS` in `school/settings.py`
3. Create the following files in the app:
   - `models.py` — models inheriting `TenantScopedModel`
   - `views.py` — views using `RoleRequiredMixin`
   - `urls.py` — URL patterns with `app_name`
   - `admin.py` — admin registrations
   - `tests.py` — tests
4. Create `templates/<app_name>/` directory for HTML templates
5. Create `migrations/` directory (auto-created by startapp)
6. Include URLs in `school/urls.py`:
   ```python
   path('<app_prefix>/', include('<app_name>.urls')),
   ```
7. Run migrations: `python manage.py makemigrations && python manage.py migrate`
8. Add tests and verify: `python manage.py test <app_name>`

## Conventions
- Use single quotes for strings
- Use f-strings for formatting
- Use `gettext_lazy` for all user-facing strings
- All models must have `school = models.ForeignKey('core.School', ...)` via TenantScopedModel
- Views requiring auth must use `RoleRequiredMixin` with `allowed_roles`
- URL names should use snake_case and include the app namespace
