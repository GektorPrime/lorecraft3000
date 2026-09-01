"""Request safeguards for the local-only application."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _hostname(value: str, *, origin: bool = False) -> str | None:
    try:
        parsed = urlsplit(value if origin else f"//{value}")
    except ValueError:
        return None
    if origin and parsed.scheme not in {"http", "https"}:
        return None
    return parsed.hostname


def _is_loopback_client(host: str | None) -> bool:
    if host == "testclient":  # Starlette's in-process TestClient transport.
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


class LocalRequestGuardMiddleware(BaseHTTPMiddleware):
    """Reject network hosts and browser writes originating outside this machine."""

    async def dispatch(self, request: Request, call_next):
        if not _is_loopback_client(request.client.host if request.client else None):
            return JSONResponse(
                {"detail": "LoreCraft3000 only accepts local connections."},
                status_code=403,
            )
        host = _hostname(request.headers.get("host", ""))
        if host not in _LOOPBACK_HOSTS:
            return JSONResponse(
                {"detail": "LoreCraft3000 only accepts requests from this computer."},
                status_code=400,
            )

        origin = request.headers.get("origin")
        if request.method in _UNSAFE_METHODS and origin is not None:
            if _hostname(origin, origin=True) not in _LOOPBACK_HOSTS:
                return JSONResponse(
                    {"detail": "Request came from an unrelated website."},
                    status_code=403,
                )
        return await call_next(request)
