# Grace House School System

A multi-tenant school management system built with Django. Foundation module (core + accounts) is complete.

## Current Phase
Foundation module complete. Ready for `students` module implementation.

## Architecture
- Multi-tenant via School model in `core`
- Custom User model in `accounts` with role-based access (ADMIN, TEACHER, STUDENT, PARENT)
- Tenant-scoped models via `TenantScopedModel` abstract base class
- School-scoping middleware and mixins for view-level isolation
- Auth via `AUTH_USER_MODEL = 'accounts.User'`
- Database: SQLite (dev), PostgreSQL-ready
