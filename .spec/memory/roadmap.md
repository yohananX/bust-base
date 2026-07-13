# School Management Platform — Phased Roadmap

**Architecture**: Modular monolith (one Django project, separate apps), not microservices.
**Multi-tenancy**: school_id on every core table from day one, use later.
**Frontend MVP**: Django templates + htmx + Tailwind (not a separate SPA).
**Hosting**: Railway/Render + managed Postgres + R2/B2 for file storage.
**Payments**: Paystack (primary) + Flutterwave (alternative).
**Background jobs**: Django-Q2 (simpler than Celery for solo dev).

---

## Phase 1 — MVP (get something usable fast)
Goal: a working core loop for one school, end to end.

| Order | Module | Status |
|-------|--------|--------|
| 1 | `core` + `accounts` — School/tenant model, user roles, login, school-scoping | ✅ **Done** |
| 2 | `students` — registration, class assignment, enrollment history, guardian linking | ✅ **Done** |
| 3 | `academics` — subjects, teacher assignments, score entry (30/70), per-subject ranking | 🔜 **Now** |
| 4 | `fees` — fee structure, invoice generation, Paystack payment integration, admin view | ⏳ |
| 5 | Deploy on Railway/Render + managed Postgres, R2/B2 for file storage | ⏳ |

**Deliberately out of scope for Phase 1**: payroll, projects/expansion budgeting, notifications, full ExamScribe pipeline, cross-subject report cards.

---

## Phase 2 — Round out school operations
- `payroll`: staff salary structure and payment runs
- `finance`: projects/expansion/budget tracking, rolled-up financial reporting
- `notifications`: email/SMS for fee reminders and result availability
- `examscribe`: photo upload → formatted document → linked to a gradable test
- Cross-subject report cards / term summaries

## Phase 3 — Polish, scale, and resale-readiness
- Parent portal refinement
- Harden multi-tenancy: second-school onboarding flow, tenant-level settings
- Consider splitting modules only if/when evidence requires it

---

## Open questions to resolve before/while building

1. **Fee structure complexity** — flat fees per class, or itemized (tuition + transport + feeding, etc.)? Needs answer before `fees` models are final.
2. **Grading policy** — weighted average, grading scale used. Needs answer before `academics` result computation is locked.
3. **Exact permissions matrix** — teacher (own subjects/classes only), parent (own children only), admin (everything). Write out explicitly before writing view code.
