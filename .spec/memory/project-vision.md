# Grace House School System — School Management Platform

## Architecture
**Modular monolith** — one Django project, internally split into Django apps.
Not microservices. Solo dev, no ops overhead until evidence requires splitting.

**Multi-tenancy from day one** — `school_id` on every core table. Currently one school,
designed for resale later. Every model inherits `TenantScopedModel` for enforced isolation.

**Frontend (MVP)**: Django templates + htmx + Tailwind. No separate SPA in v1.

## Current Phase
**Phase 1 — MVP** (core loop for one school).
✅ core + accounts — School tenant, user roles, auth, school-scoping
✅ students — registration, enrollment history, guardian linking, promotion
🔜 fees — FeeStructure, Invoice, Payment, Paystack integration
⏳ academics (minimal) — subjects, teacher assignment, score entry, results
⏳ Deploy to Railway/Render + Postgres + R2/B2

## Tech Stack
- Backend: Django 6.0, PostgreSQL
- Frontend: Django templates + htmx + Tailwind
- Payments: Paystack (primary), Flutterwave (alternative)
- File storage: Cloudflare R2 / Backblaze B2 (S3-compatible)
- Background jobs: Django-Q2
- Documents: WeasyPrint / python-docx / reportlab
- Hosting: Railway or Render

## Modules
| Module | Responsibility |
|--------|---------------|
| core | School tenant, tenant-scoped base, shared models (session, term), middleware |
| accounts | User, roles, auth, RoleRequiredMixin, SchoolScopedQuerySetMixin |
| students | Student profiles, class enrollment, guardian links, promotion |
| fees | Fee structures, invoices, payments, receipts |
| academics | Subjects, teacher assignments, scores, results |
| examscribe | Exam photo upload → formatted document → gradable test |
| payroll | Staff salary, payment runs, payslips |
| finance | Budget, expenditure, financial reporting |
| notifications | Email/SMS for fee reminders, result availability, payroll |

## Key Architectural Decisions
| Decision | Reasoning |
|----------|-----------|
| Modular monolith, not microservices | Solo dev; avoids ops overhead disproportionate to actual scaling needs |
| Django | Free admin panel + built-in auth = large speed win for admin-heavy MVP |
| Server-rendered templates + htmx | Avoids building/maintaining a separate frontend + API for v1 |
| `school_id` on every core table | Cheap now, expensive to retrofit; is the entire cost of "resale-ready" |
| Paystack/Flutterwave over Stripe | Standard for Nigerian schools; supports bank transfer/USSD parents actually use |
| Fold ExamScribe in as a module | Its output connects directly to the results pipeline |
