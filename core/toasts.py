"""Helpers for showing toast notifications, including via HTMX responses."""
import json


def toast_trigger(message, level='success'):
    """Build an ``HX-Trigger`` response-header value that raises a toast.

    Views returning partials for HTMX swaps call this and set the result on
    the response header; the front-end ``app-toast`` event listener renders
    the toast (see templates/base.html).
    """
    return json.dumps({'app-toast': {'message': str(message), 'type': level}})


def attach_toast(response, message, level='success'):
    """Set the HX-Trigger header on an existing HttpResponse."""
    response['HX-Trigger'] = toast_trigger(message, level)
    return response
