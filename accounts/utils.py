"""Shared account utilities."""
import re
import secrets
import string


def generate_username(first_name, last_name):
    """Build a lowercase 'first.last' username from names.

    Spaces become dots; anything outside [a-z0-9.] is stripped.
    """
    base = f"{first_name.strip()}.{last_name.strip()}"
    base = base.lower().replace(' ', '.')
    return re.sub(r'[^a-z0-9.]', '', base)


def unique_username(first_name, last_name):
    """Generate a username from names, appending a counter on collision.

    e.g. john.doe, then john.doe1, john.doe2, ...
    """
    from accounts.models import User

    base = generate_username(first_name, last_name) or 'user'
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}{counter}"
        counter += 1
    return username


def generate_password(length=10):
    """Cryptographically random alphanumeric one-time password.

    Single source of truth for auto-generated credentials across the
    admin portal (staff, students, guardians, credential slips).
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))