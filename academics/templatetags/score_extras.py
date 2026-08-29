from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] or attribute or extra_tests[key] or empty string."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    value = getattr(dictionary, key, None)
    if value is not None:
        return value
    extra = getattr(dictionary, 'extra_tests', None)
    if isinstance(extra, dict):
        return extra.get(key, '')
    return ''
