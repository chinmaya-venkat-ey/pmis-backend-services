"""
Logging middleware for request/response tracking.
"""
import time
import uuid
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging requests and responses.

    This middleware:
    1. Generates unique request ID
    2. Logs incoming requests
    3. Logs outgoing responses with duration
    4. Attaches request ID to request state
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable
    ) -> Response:
        """
        Process request with logging.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response from next handler
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"[{request_id}] "
            f"User: {getattr(request.state, 'user_login', 'anonymous')}"
        )

        # Track request duration
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        logger.info(
            f"Response: {request.method} {request.url.path} "
            f"[{request_id}] "
            f"Status: {response.status_code} "
            f"Duration: {duration:.3f}s"
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response
