from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.views import exception_handler


def _message_from_data(data):
    if isinstance(data, dict):
        for value in data.values():
            return _message_from_data(value)
    if isinstance(data, list) and data:
        return _message_from_data(data[0])
    return str(data)


def financial_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    original_data = response.data
    if isinstance(exc, NotAuthenticated):
        code = "AUTHENTICATION_REQUIRED"
    elif isinstance(exc, AuthenticationFailed):
        code = "INVALID_AUTHENTICATION"
    elif isinstance(exc, PermissionDenied):
        code = "PERMISSION_DENIED"
    elif isinstance(exc, NotFound):
        code = "NOT_FOUND"
    elif isinstance(exc, ValidationError):
        code = "INVALID_AMOUNT" if "amount" in original_data else "INVALID_REQUEST"
    else:
        code = "REQUEST_ERROR"

    response.data = {
        "error": {
            "code": code,
            "message": _message_from_data(original_data),
            "details": original_data,
        }
    }
    return response
