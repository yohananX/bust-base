# Business Rules

## Multi-tenancy
- Every model inherits from TenantScopedModel to enforce school isolation
- School-scoping middleware sets request.school for all views
- SchoolScopedQuerySetMixin auto-filters all list/detail views by school
- User also inherits TenantScopedModel (via TenantScopedUserManager)

## User Model
- Single User model with role field (not separate tables per role)
- Role-specific data lives in domain modules with FK to User
- Every user belongs to exactly one school
- Current roles: ADMIN, TEACHER, STUDENT, PARENT

## Payroll (design decision)
- Payroll is independent of the coarse role field entirely
- Any User can optionally have a StaffProfile if they draw a salary, regardless of role
- A STAFF role may be added later for permission/reporting clarity, not for payroll logic
- This sidesteps touching the Roles enum right now

## Academic Calendar
- One AcademicSession per school year
- Only one session per school can be current at a time
- Only one Term per school can be current at a time (across all sessions)
- Term names are unique within a (school, session)

## Access Control
- RoleRequiredMixin on all views with allowed_roles list
- 403 for unauthorized roles, 302 redirect for unauthenticated
- TeacherAssignmentRequiredMixin for subject/class-scoped access
- GuardianScopedQuerySetMixin for parent-scoped data access

## Financial (fees)
- FeeStructure = policy (what a class owes for a category in a term)
- Invoice = bill (snapshot at generation, NOT live-linked to FeeStructure)
- Balance/status always computed from Payment rows, never stored
- PENDING payments never count toward amount_paid
- All money in Decimal, never float
- Invoice generation is idempotent (running twice doesn't double-bill)
