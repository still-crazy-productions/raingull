from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Template filter to get a dictionary item by key."""
    if dictionary is None:
        return None
    return dictionary.get(key) 