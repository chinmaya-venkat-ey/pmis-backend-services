import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.utilities.logger import get_logger

logger = get_logger("pims.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds an X-Request-ID header and logs request/response timing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        logger.info(
            "--> %s %s | rid=%s | client=%s",
            request.method,
            request.url.path,
            request_id,
            request.client.host if request.client else "-",
        )

        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"

        logger.info(
            "<-- %s %s | rid=%s | status=%s | %.2fms",
            request.method,
            request.url.path,
            request_id,
            response.status_code,
            elapsed_ms,
        )
        return response
