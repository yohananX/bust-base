# Business Rules

## Multi-tenancy
- Every model inherits from TenantScopedModel to enforce school isolation
- School-scoping middleware sets request.school for all views
- SchoolScopedQuerySetMixin auto-filters all list/detail views by school

## User Model
- Single User model with role field (not separate tables per role)
- Role-specific data lives in domain modules with FK to User
- Every user belongs to exactly one school

## Academic Calendar
- One AcademicSession per school year
- Only one session per school can be current at a time
- Only one Term per school can be current at a time (across all sessions)
- Term names are unique within a (school, session)

## Access Control
- RoleRequiredMixin on all views with allowed_roles list
- 403 for unauthorized roles, 302 redirect for unauthenticated
