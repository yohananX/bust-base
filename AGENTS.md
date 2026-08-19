# AGENTS.md — Grace House School System

## Role
You are a senior Django engineer working on a multi-tenant school management platform.

## Tech Stack
- Django 5, Python 3.12
- SQLite (dev), Postgres (prod)
- HTMX for partial page updates
- Tailwind CSS for styling
- Django-Q2 for async tasks
- Paystack for payments
- Brevo for transactional email (optional)
- Chart.js for parent dashboard charts

## Project Structure

| App | Purpose |
|-----|---------|
| accounts | User model (ADMIN, TEACHER, STUDENT, PARENT), login/logout, RoleRequiredMixin |
| core | TenantScopedModel, School, AcademicSession, Term |
| students | Student, ClassEnrollment, StudentGuardianLink, parent/student portals |
| academics | Score, Subject, TeacherAssignment, TermResult, score moderation |
| fees | Invoice, Payment, FeeStructure, Paystack webhook/verify, receipts |
| notifications | NotificationLog, notify(), bell views, process_notification task |
| school_admin | Admin portal (students, fees, results, payroll, settings) |
| payroll | Pay grades, allowances, payroll runs, disbursements |
| finance | Projects, expenditures, financial reports |
| data_import | CSV import for students/staff with dry-run validation |

## Critical Patterns

### Multi-tenancy
- All business models inherit `TenantScopedModel` (school FK).
- Superadmins have `school=None`.
- Queries must always be scoped by `school=request.school`.
- Use `select_related('school')` and `filter(school=request.school)` consistently.

### Role-based access
- Use `RoleRequiredMixin` on all views: `allowed_roles = [Roles.ADMIN]`
- Roles: ADMIN, TEACHER, STUDENT, PARENT
- Permission checks in views: `if user.role == Roles.PARENT: ...`

### Notifications
- Use `notify(recipient=..., channel='IN_APP', subject=..., message=..., reference=...)`
- Channels: EMAIL, SMS, IN_APP
- Reference strings enable dedup: `payment-confirm:{id}`, `receipt:{id}`, etc.
- Primary-contact guardian: `student.guardian_links.filter(is_primary_contact=True).first()`
- Never send email/SMS unless explicitly asked — IN_APP is the default.

### Parents and Guardians
- `StudentGuardianLink` links User(PARENT) ? Student
- One parent can have many children; one child can have many guardians
- `is_primary_contact=True` selects the notification recipient
- Parent scope check pattern:
  ```python
  if not StudentGuardianLink.objects.filter(student=student, guardian=request.user).exists():
      messages.error(request, 'You are not authorized.')
      return redirect('parent-children')
  ```

### Payments
- Payment statuses: PENDING, CONFIRMED, FAILED
- Webhook-first confirmation: `charge.success` ? `_handle_charge_success`
- Fallback: `PaymentReturnView` polls verify endpoint after 5s
- Receipt issued lazily via `issue_receipt(payment)` — idempotent
- Bank transfers: PENDING until admin confirms/rejects

### Results
- Scores enter as PENDING, admin approves/rejects in moderation
- `Term.results_published` gates student/parent visibility
- Notification dedup: `NotificationLog.objects.filter(reference='term-results:{id}').exists()`

### Templates
- Base template: `templates/base.html`
- Parent portal: `templates/students/parent/*.html`
- Student portal: `templates/students/student/*.html`
- Admin portal: `templates/school_admin/*.html`
- Shared components: `templates/components/*.html`
- All use Tailwind CSS; icons via Lucide (`data-lucide`)

### Testing
- Tests live in `<app>/tests.py` or `<app>/test_*.py`
- Run: `python manage.py test <app>`
- Use `BaseTestCase` patterns from existing tests
- Mock external APIs (Paystack) with `unittest.mock.patch`
- Current test count: ~183

## How to Add a New Feature

1. **Model**: Add to `<app>/models.py`, inherit `TenantScopedModel`, create migration
2. **Admin**: Register in `<app>/admin.py` with list_display, filters, search_fields
3. **View**: Add to `<app>/views.py`, use `RoleRequiredMixin`, scope by school
4. **URL**: Add to `<app>/urls.py` and include in `school/urls.py`
5. **Template**: Create in `templates/<app>/<template>.html`
6. **Test**: Add to `<app>/tests.py` covering happy path, auth, and scoping
7. **Notify**: If the feature creates events, call `notify()` from the view

## How to Add a New Django App

1. `python manage.py startapp <app_name>`
2. Add `<app_name>` to `settings.INSTALLED_APPS`
3. Create `models.py`, `views.py`, `urls.py`, `admin.py`, `tests.py`
4. Create `templates/<app_name>/` directory for HTML templates
5. Create `migrations/` directory (auto-created by startapp)
6. Include URLs in `school/urls.py`:
   ```python
   path('<app_prefix>/', include('<app_name>.urls')),
   ```
7. Run `python manage.py makemigrations && python manage.py migrate`

## Important Files to Read Before Making Changes
- `CONTEXT.md` — Domain glossary and notification rules
- `core/models.py` — TenantScopedModel, School, Term
- `accounts/models.py` — User, Roles, RoleRequiredMixin
- `notifications/utils.py` — notify() helper
- `students/models.py` — StudentGuardianLink, parent scoping
- `fees/paystack.py` — Payment webhook/verify/receipt patterns

## Gotchas
- Never use `User.objects.filter(...)` without `school=...` (except superadmins)
- `StudentGuardianLink` is tenant-scoped; always filter by `school`
- `notify()` may raise if recipient has no email — guard with `if user.email:`
- `Payment.student` can be None for invoice-less payments — null-safe access
- `Term.results_published` must be True before students/parents can see results
- Use `select_related` and `prefetch_related` aggressively — N+1 is common
- HTMX requests: check `request.headers.get('HX-Request')` for partial templates
- All monetary amounts are Decimal — never float
- Use `timezone.now()` not `datetime.now()`

## Commands
- Run tests: `python manage.py test`
- Run app tests: `python manage.py test <app>`
- Make migrations: `python manage.py makemigrations`
- Migrate: `python manage.py migrate`
- Shell: `python manage.py shell`
- Create superuser: `python manage.py createsuperuser`
- Dev server: `python manage.py runserver`
