# School Management Platform — Phased Roadmap

**Architecture**: Modular monolith (one Django project, separate apps), not microservices.
**Multi-tenancy**: school_id on every core table from day one, use later.
**Frontend MVP**: Django templates + htmx + Tailwind (not a separate SPA).
**Hosting**: Railway/Render + managed Postgres + R2/B2 for file storage.
**Payments**: Paystack (primary) + Flutterwave (alternative).
**Background jobs**: Django-Q2 (simpler than Celery for solo dev).

---

## Phase 1 — MVP (get something usable fast)

| Order | Module | Status |
|-------|--------|--------|
| 1 | `core` + `accounts` — School/tenant, user roles, school-scoping | ✅ **Done** |
| 2 | `students` — registration, enrollment, guardian links, promotion | ✅ **Done** |
| 3 | `academics` — subjects, teacher assignments, scores, ranking | ✅ **Done** |
| 4 | ~~`fees`~~ *(reordered)* | — |
| **5** | **`fees` — fee structures, invoices, payments, Paystack** | **🔜 Current** |
| 6 | `payroll` — staff salary, payment runs, payslips | ⏳ |
| 7 | Deploy on Railway/Render + Postgres + R2/B2 | ⏳ |

**Out of scope for Phase 1**: finance/ budgeting, notifications, full ExamScribe, cross-subject report cards.

---

## Phase 2 — Round out operations
- `payroll`: staff salary structure and payment runs
- `finance`: projects/expansion/budget tracking, rolled-up financial reporting
- `notifications`: email/SMS for fee reminders and result availability
- `examscribe`: photo upload → formatted document → linked to a gradable test

## Phase 3 — Polish, scale, resale-readiness
- Parent portal refinement
- Harden multi-tenancy: second-school onboarding, tenant-level settings
- Split modules only if/when evidence requires it
