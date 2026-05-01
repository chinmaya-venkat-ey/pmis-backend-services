"""Request/response logging middleware — ported from the monolith / user-service."""
import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        logger.info(
            "Request: %s %s [%s] User: %s",
            request.method, request.url.path, request_id,
            getattr(request.state, "user_login", "anonymous"),
            )

        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        logger.info(
            "Response: %s %s [%s] Status: %s Duration: %.3fs",
            request.method, request.url.path, request_id,
            response.status_code, duration,
            )
        response.headers["X-Request-ID"] = request_id
        return response
