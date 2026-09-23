# Grace House School Management Platform

Multi-tenant school management platform for Grace House International School —
admin, teacher, parent, and student portals covering academics, fees (Paystack),
payroll, finance, inventory, extra lessons, and CSV data import.

Django 6 · Python 3.12 · SQLite (dev) / Postgres (prod) · HTMX + Tailwind ·
Django-Q2 (async tasks) · Paystack (payments) · Chart.js (parent dashboard).

## Quickstart (local dev)

```powershell
python -m venv venv; .\venv\Scripts\Activate
pip install -r requirements.txt
Copy-Item .env.example .env   # then set SECRET_KEY, DEBUG=True
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Optional demo data: `seed_data/populate.py`, `seed_data/curriculum.py`
(see `FEE_REDESIGN_PLAN.md` for the fee-pricing seed).

Docker (prod-like): `docker compose up --build` — Postgres + Redis + web
(gunicorn/waitress) + Django-Q2 worker. Copy `.env.production.example` to
`.env` first.

## Architecture in 60 seconds

**Multi-tenancy.** Every business model inherits `core.TenantScopedModel`
(a `school` FK). Views scope by `school=request.school` (set by
`SchoolMiddleware`); superusers have `school=None` and are rejected from
tenant portals. Rule of thumb: no `school=` on a queryset is a bug —
see `tests/test_tenancy.py`.

| App | Owns |
|---|---|
| `accounts` | `User` (ADMIN/TEACHER/STUDENT/PARENT), login, `RoleRequiredMixin` |
| `core` | `TenantScopedModel`, `School`, `AcademicSession`, `Term` |
| `students` / `academics` | Enrollments, guardian links, scores, moderation, publishing |
| `fees` | Invoices, payments, Paystack webhook/verify, receipts |
| `notifications` | `notify()` / `notify_admins()` → `NotificationLog` (IN_APP bell) |
| `school_admin` | Admin portal (students, fees, results, settings) |
| `payroll` / `finance` / `inventory` / `lessons` / `data_import` | Payslips, expenditures, stock, extra lessons, CSV import |

**Fee pricing.** `FeePrice` is canonical (legacy `FeeStructure` is a
deprecated read-only shim). Scopes nest `SCHOOL_WIDE` → `LEVEL` → `CLASS`,
most-specific wins; `fees.pricing.resolve_prices(school, class, term)` is the
only resolver, with `FeePriceOverride` handling scholarships/discounts.

**Payments.** Webhook-first: `charge.success` → `_handle_charge_success`
(HMAC + amount tamper-check + idempotency), with a verify-endpoint fallback
(`confirm_payment_from_verify`). Both paths share one field mapper
(`_payment_kwargs_from_webhook`). Receipts are lazy + idempotent
(`issue_receipt`). Transfer payments stay PENDING until an admin confirms.

**Notifications.** `notify(recipient, channel, subject, message, reference)` —
one durable row per recipient; `IN_APP` rows power the bell (toast if online).
EMAIL/SMS are synchronous audit records. `notify_admins` is for action
items/exceptions only, never routine confirmations. References
(`payment-confirm:{id}`, `term-results:{id}`…) dedup retried webhooks.

**Results.** Scores enter PENDING → admin approves in moderation;
`Term.results_published` gates student/parent visibility.

## Testing

```powershell
python manage.py test            # full suite (~190 tests)
python manage.py test fees       # one app
```

Mock Paystack with `unittest.mock.patch` (see `fees/tests.py`:
`WebhookSecurityTest`, `VerifyTransactionFallbackTest`). Portal-leakage
tests live in `tests/test_tenancy.py` — keep them green.

## Docs

| File | What |
|---|---|
| `CONTEXT.md` | Domain glossary, notification rules, fee-redesign decisions |
| `AGENTS.md` | Contributor patterns (scoping, roles, money, templates) |
| `CODEBASE_AUDIT.md` | Audit findings + phased cleanup plan |
| `DEPLOYMENT.md` | CI/CD, backups, production runbook |
| `INVENTORY_USER_GUIDE.md` | Inventory workflows |

## Security notes

- `docker-compose.yml` binds Redis to localhost only — do not expose 6379.
- Dependabot + `pip-audit` track vulns on `requests`/`boto3`/`Pillow`
  (see `.github/`).
- Never commit `.env` or `backups/`; both are gitignored.
