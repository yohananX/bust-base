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


def parse_full_name(full_name):
    """Split a full name into (first, middle, last) parts.

    Heuristic:
    - 1 word  -> first=word, middle='', last=''
    - 2 words -> first=word1, middle='', last=word2
    - 3+ words -> first=word1, middle=word2...word(n-1), last=word(n)
    """
    parts = full_name.strip().split()
    if not parts:
        return ('', '', '')
    if len(parts) == 1:
        return (parts[0], '', '')
    if len(parts) == 2:
        return (parts[0], '', parts[1])
    return (parts[0], ' '.join(parts[1:-1]), parts[-1])


HONORIFICS = {'mr', 'mrs', 'miss', 'dr', 'prof', 'chief', 'engr', 'barr', 'rev', 'pastor'}


def strip_honorific(name):
    """Remove leading honorifics like Mrs., Mr., Dr., etc. from a name."""
    parts = name.strip().split(None, 1)
    if parts and parts[0].lower().rstrip('.').rstrip() in HONORIFICS:
        return parts[1] if len(parts) > 1 else ''
    return name