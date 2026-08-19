from django import template

register = template.Library()


@register.filter(name="split_string")
def split_string(value, delimiter):
    if not value:
        return []
    return value.split(delimiter)


@register.filter(name="strip")
def strip(value):
    if value:
        return value.strip()
    return ""
