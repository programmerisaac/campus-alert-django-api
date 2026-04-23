# campusalert/core/exceptions.py

"""
Custom DRF exception handler.

Wraps all API error responses in a consistent envelope:
    { "error": true, "message": "...", "detail": {...} }

Real error details are never leaked to the client — they are logged server-side.
"""

import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('campusalert.core')


def custom_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler output in a consistent JSON envelope.

    Args:
        exc: The exception raised by the view.
        context: DRF context dict containing the view and request.

    Returns:
        A Response with a standardised error body, or None if the exception
        is unhandled (Django's 500 handler takes over).
    """
    response = exception_handler(exc, context)

    if response is not None:
        original_data = response.data

        # Build a human-readable message from the DRF error detail
        if isinstance(original_data, dict):
            # Extract the first non-null message for top-level display
            message = _extract_message(original_data)
        elif isinstance(original_data, list):
            message = original_data[0] if original_data else 'An error occurred.'
        else:
            message = str(original_data)

        response.data = {
            'error': True,
            'message': str(message),
            'detail': original_data,
        }

        # Log 5xx errors with full context for server-side debugging
        if response.status_code >= 500:
            logger.error(
                'Server error in %s.%s: %s',
                context['view'].__class__.__name__,
                context['request'].method,
                exc,
                exc_info=True,
            )

    return response


def _extract_message(data: dict) -> str:
    """
    Extracts the first error message string from a DRF error dict.
    Handles nested structures like {'field': ['error msg']} or {'detail': 'msg'}.
    """
    if 'detail' in data:
        return str(data['detail'])

    for value in data.values():
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value

    return 'An error occurred.'


