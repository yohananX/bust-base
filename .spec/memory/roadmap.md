# Implementation Roadmap

## ✅ Phase 0: Foundation (DONE)
- [x] Django project scaffolded
- [x] `core` app: School, AcademicSession, Term, TenantScopedModel
- [x] `accounts` app: User (custom), RoleRequiredMixin, SchoolScopedQuerySetMixin
- [x] School-scoping middleware
- [x] AUTH_USER_MODEL set before first migration
- [x] Admin registrations for all models
- [x] 29 tests covering multi-tenant isolation, role-based access, "one current" enforcement

## 🔜 Phase 1: Students module
- Student profiles, class assignments, etc.
- Depends on core + accounts being solid

## Future Phases
- Academics (subjects, classes, timetables)
- Fees (invoicing, payments)
- Payroll
- ExamScribe (results, report cards)
