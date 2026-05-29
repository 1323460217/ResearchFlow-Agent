import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        start = time.monotonic()
        response: Response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.0f}ms"
        logger.info(
            "%s %s %s %.0fms",
            request.method, request.url.path, response.status_code, elapsed_ms,
            extra={"method": request.method, "path": request.url.path,
                   "status": response.status_code, "duration_ms": elapsed_ms,
                   "request_id": request_id},
        )
        return response
