"""Contract-shaped error responses.

The frontend contract specifies `{code, message}` with a fixed code enum, not FastAPI's
default `{"detail": ...}`. The distinction the frontend actually acts on is 404 (never
existed -> "잘못된 링크") versus 410 (expired -> "지난 알림입니다"), so both must survive
all the way to the wire.
"""

from typing import NoReturn

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from backend_core.models import ErrorBody, ErrorCode


class ApiError(HTTPException):
    """HTTPException carrying a contract error code."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code: ErrorCode = code


def session_not_found() -> NoReturn:
    raise ApiError(404, "SESSION_NOT_FOUND", "토큰을 찾을 수 없습니다.")


def session_expired() -> NoReturn:
    raise ApiError(410, "SESSION_EXPIRED", "만료된 링크입니다.")


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render ApiError (and any other HTTPException) in the contract's error shape."""
    if isinstance(exc, ApiError):
        status, code, message = exc.status_code, exc.code, str(exc.detail)
    elif isinstance(exc, HTTPException):
        status, code, message = exc.status_code, _code_for(exc.status_code), str(exc.detail)
    else:  # pragma: no cover - defensive; FastAPI routes non-HTTP errors elsewhere
        status, code, message = 500, "INTERNAL", "내부 오류가 발생했습니다."
    return JSONResponse(
        status_code=status,
        content=ErrorBody(code=code, message=message).model_dump(by_alias=True),
        # Error bodies can echo request context; keep them out of shared caches too.
        headers={"Cache-Control": "no-store"},
    )


def _code_for(status_code: int) -> ErrorCode:
    if status_code == 404:
        return "SESSION_NOT_FOUND"
    if status_code == 410:
        return "SESSION_EXPIRED"
    if status_code == 429:
        return "RATE_LIMITED"
    if 400 <= status_code < 500:
        return "INVALID_REQUEST"
    return "INTERNAL"
