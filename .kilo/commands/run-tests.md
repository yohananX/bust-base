# Command: Run Tests

Use this when the user asks to run tests or verify changes.

## Commands

```bash
# Run all tests
python manage.py test

# Run specific app
python manage.py test notifications

# Run specific test class
python manage.py test notifications.tests.NotifyHelperTest

# Run with verbose output
python manage.py test -v 2

# Run specific test method
python manage.py test notifications.tests.NotifyHelperTest.test_notify_creates_log
```

## Test Conventions
- Tests live in `<app>/tests.py` or `<app>/test_*.py`
- Use `TestCase` from `django.test`
- Use `override_settings` for email backend: `@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')`
- Create test data in `setUp()` using factory patterns or direct creation
- Test both happy path and failure cases
- Test cross-school isolation for tenant-scoped models
- Current total: ~183 tests
