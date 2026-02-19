# backend/app/middleware/auth_trace.py
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.utils.logger import setup_logger

log = setup_logger("middleware")


class AuthTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only log auth-sensitive paths or errors, otherwise it's too noisy
        # For development, we log everything as DEBUG/INFO

        path = request.url.path
        method = request.method

        log.info(f"➡️  REQ: {method} {path}")

        response = await call_next(request)

        # Log response status
        if response.status_code >= 400:
            log.warning(f"⬅️  RES: {method} {path} - Status {response.status_code}")
        else:
            log.info(f"⬅️  RES: {method} {path} - Status {response.status_code}")

        return response
