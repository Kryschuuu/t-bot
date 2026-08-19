# trading/templatetags/my_filters.py
from django import template

register = template.Library()


# my_filters.py
@register.filter
def get_item(dictionary, key):
    if not dictionary:  # None-Check hinzufügen
        return {}
    return dictionary.get(key)


@register.filter
def sub(value, arg):
    """Subtrahiert den Wert vom Argument"""
    try:
        return value - arg
    except (TypeError, ValueError):
        return value
