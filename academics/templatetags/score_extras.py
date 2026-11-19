from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] or attribute or extra_tests[key] or empty string."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    value = getattr(dictionary, key, None)
    if value is not None:
        return value
    extra = getattr(dictionary, "extra_tests", None)
    if isinstance(extra, dict):
        return extra.get(key, "")
    return ""


@register.filter(name="replace")
def replace_filter(value, arg):
    """Replace occurrences of a substring with another string.

    Usage: {{ value|replace:"old,new" }}
    For two-arg syntax like {{ value|replace:'old','new' }}, Django doesn't
    support that — use the comma-separated form instead.
    """
    if value is None:
        return ""
    value = str(value)
    try:
        old, new = arg.split(",", 1)
    except ValueError:
        return value
    return value.replace(old, new)
