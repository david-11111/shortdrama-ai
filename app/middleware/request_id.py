"""Request-ID middleware: generate and propagate X-Request-ID header."""

import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger("app.request_id")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure every request has an X-Request-ID, inject it into request.state for logging."""

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = req_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
