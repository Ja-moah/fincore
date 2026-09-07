import uuid

from .request_context import request_id_context


class RequestCorrelationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied_request_id = request.headers.get("X-Request-ID")
        try:
            request_id = uuid.UUID(supplied_request_id) if supplied_request_id else uuid.uuid4()
        except (ValueError, TypeError, AttributeError):
            request_id = uuid.uuid4()

        request.request_id = request_id
        token = request_id_context.set(str(request_id))
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = str(request_id)
            return response
        finally:
            request_id_context.reset(token)
