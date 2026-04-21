"""Global HTTP middleware for the FastAPI server.

Provides two concerns:

1. **RequestLoggingMiddleware** — logs every inbound request and its response
   (or error) as structured JSON via the standard ``logging`` module.  Each
   request is assigned a short ``request_id`` (8-char hex) that appears on
   every log line for that request, making it trivial to trace a single call
   through the logs with ``grep request_id=<id>``.

   Events emitted:
       request.received  — method, path, client IP
       request.completed — status_code, latency_ms
       request.error     — exc_info + latency_ms (HTTP 500)

2. **error_handler** — catch-all exception barrier that converts any unhandled
   exception into a ``{"error": "<str(e)>"}`` JSON response with HTTP 500.
   Registered via ``app.middleware("http")`` *after* CORSMiddleware so CORS
   headers survive error responses.

Middleware stack (outermost → innermost):
    CORSMiddleware → error_handler → RequestLoggingMiddleware → route handlers
"""

import logging
import time
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """ASGI middleware that logs request entry and exit with a shared request_id.

    Wraps each request in a try/finally so exit timing is always recorded even
    when a downstream exception propagates (error_handler will catch it outside
    this layer and convert it to a 500).

    Args:
        app: The next ASGI application in the stack.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        request_id = uuid4().hex[:8]
        start = time.perf_counter()

        logger.info(
            "request received",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else "unknown",
            },
        )

        status_code = 500
        try:
            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            await self.app(scope, receive, send_wrapper)

            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(
                "request error",
                exc_info=exc,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "latency_ms": latency_ms,
                },
            )
            raise


async def error_handler(request: Request, call_next):
    """Catch-all exception barrier for unhandled route errors.

    Converts any uncaught exception into a structured JSON error response
    (HTTP 500) so the client always receives a consistent shape.

    Args:
        request: The incoming FastAPI/Starlette request object.
        call_next: ASGI callable representing the next layer in the stack.

    Returns:
        The original response on success, or a ``JSONResponse`` with status
        500 and body ``{"error": str(e)}`` on failure.
    """
    try:
        return await call_next(request)
    except Exception as e:
        logger.error("unhandled exception", exc_info=e, extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"error": str(e)})
