# Known Risks & Technical Debt

## Current
- SQLite used for development (change `DATABASES` in settings.py to switch to PostgreSQL)
- SECRET_KEY is auto-generated and checked into git — must be made environment-based before production
- DEBUG = True — must be False in production
- ALLOWED_HOSTS is empty — needs configuration for production
- No custom UI yet — everything goes through Django admin
- Role-mixing: RoleRequiredMixin doesn't yet check subject/class assignment scoping (will be added in academics module)

## Mitigated
- ✅ AUTH_USER_MODEL set before first migration (cannot be changed easily later)
- ✅ Multi-tenant isolation enforced at model, queryset, and middleware levels
- ✅ Tests for data leakage across schools exist and pass
