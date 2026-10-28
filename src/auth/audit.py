"""Append-only audit log helper.

All write paths go through :func:`record_audit_event`. It is best-effort: a
failure to write an audit row is logged but never raises (so it can't break
the request that triggered it).
"""
from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from fastapi import Request

from src.database.connection import get_session
from src.database.models import AuditEvent

logger = structlog.get_logger(__name__)


def record_audit_event(
    event_type: str,
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Persist one audit event. Silent on DB errors."""
    try:
        ip_address = None
        user_agent = None
        if request is not None:
            ip_address = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
        
        event = AuditEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent[:255] if user_agent else None,
            details=json.dumps(details, default=str) if details else None,
        )
        with get_session() as session:
            session.add(event)
            session.commit()
    except Exception as e:
        logger.warning("audit.record_failed", event_type=event_type, user_id=user_id, error=str(e))
