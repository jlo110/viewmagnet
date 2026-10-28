"""Unified error schema + exception handlers.

All HTTP errors emit a consistent shape:

    {
        "error": {
            "code": "validation_error",
            "message": "...",
            "request_id": "...",
            "details": { ... }
        }
    }

so the frontend can render errors uniformly.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

from src.config import get_settings
from src.features.llm_client import LLMBudgetExceeded

logger = structlog.get_logger(__name__)


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    request_id: str
    details: Optional[dict[str, Any]] = None


class ApiError(BaseModel):
    """Top-level error envelope returned by every error handler."""
    error: ApiErrorPayload


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _make_response(
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
                "details": details,
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the given FastAPI app."""
    settings = get_settings()
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code_map = {
            400: "bad_request",
            401: "unauthorized",
            402: "payment_required",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "rate_limited",
        }
        # Routers may raise ``HTTPException(detail={"error": "...", "message":
        # "...", ...extra})`` to surface structured payloads (e.g. the
        # render-budget 402 carries ``minutes_used``/``minutes_limit``).
        # When that's the case, lift the human-readable ``message`` to the
        # envelope's ``message`` field and pass the rest through as
        # ``details`` so the frontend can read the structured fields.
        detail = exc.detail
        if isinstance(detail, dict):
            human = str(detail.get("message") or detail.get("error") or "An error occurred")
            return _make_response(
                status_code=exc.status_code,
                code=code_map.get(exc.status_code, "http_error"),
                message=human,
                request=request,
                details=detail,
            )
        return _make_response(
            status_code=exc.status_code,
            code=code_map.get(exc.status_code, "http_error"),
            message=str(detail) if detail else "An error occurred",
            request=request,
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return _make_response(
            status_code=422,
            code="validation_error",
            message="Invalid request payload",
            request=request,
            details={"errors": exc.errors()},
        )
    
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
        return _make_response(
            status_code=429,
            code="rate_limited",
            message=str(exc.detail) if hasattr(exc, "detail") else "Rate limit exceeded",
            request=request,
        )
    
    @app.exception_handler(LLMBudgetExceeded)
    async def llm_budget_exception_handler(request: Request, exc: LLMBudgetExceeded):
        return _make_response(
            status_code=402,
            code="llm_budget_exceeded",
            message=str(exc),
            request=request,
            details={"spent_usd": exc.spent_usd, "limit_usd": exc.limit_usd},
        )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            exc_message=str(exc),
            path=request.url.path,
            method=request.method,
        )
        message = (
            "An internal error occurred. Please try again later."
            if settings.is_production
            else f"{type(exc).__name__}: {exc}"
        )
        return _make_response(
            status_code=500,
            code="internal_error",
            message=message,
            request=request,
        )


async def request_id_middleware(request: Request, call_next):
    """Attach a UUID to every request so it appears in error responses + logs."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
