# Grace House School System

A modular monolith school management system with tenant (multi-school) isolation.

## Phase 1 — MVP (Completed Modules)
- core: School, AcademicSession, Term, SchoolMiddleware
- accounts: Custom User model with Roles (ADMIN, TEACHER, STUDENT, PARENT), RoleRequiredMixin
- students: SchoolClass, Student, ClassEnrollment, StudentGuardianLink, GuardianScopedQuerySetMixin
- academics: Subject, TeacherAssignment, Score with Olympic/dense ranking
- **fees**: FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment with Paystack integration

## Architecture
- TenantScopedModel base class with `school` FK on all tenant models
- SchoolMiddleware sets `request.school` from authenticated user
- All unique_together constraints include `school` for cross-tenant isolation
- Invoice status computed via properties (not stored): UNPAID/PARTIAL/PAID
- Webhook handler is idempotent — duplicate calls don't duplicate payments