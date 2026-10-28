"""Legacy auth models -- thin compatibility facade.

The canonical ORM lives in :mod:`src.database.models`. This module previously
defined a duplicate ``User`` (and ``YouTubeConnection``, ``UserSession``,
``PaymentHistory``) bound to the same tables, which caused dual mapper
conflicts at runtime.

It now re-exports the canonical types and exposes a small shim layer for the
two consumers that still import from here (Streamlit UI + Stripe integration).
"""
from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from src.database.models import (  # noqa: F401  (re-exported for backwards compat)
    Base,
    User,
    YouTubeConnection,
)


class SubscriptionTier(str, Enum):
    """Subscription tier levels (legacy enum kept for Stripe webhook code)."""
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    AGENCY = "agency"


# Per-tier limits historically defined here; live in src/config.py PLAN_LIMITS now.
LEGACY_LIMITS = {
    SubscriptionTier.FREE: {"videos_per_month": 5, "scripts_per_month": 3, "thumbnails_per_month": 5},
    SubscriptionTier.STARTER: {"videos_per_month": 50, "scripts_per_month": 20, "thumbnails_per_month": 30},
    SubscriptionTier.PRO: {"videos_per_month": 500, "scripts_per_month": 100, "thumbnails_per_month": 200},
    SubscriptionTier.AGENCY: {"videos_per_month": -1, "scripts_per_month": -1, "thumbnails_per_month": -1},
}


class UserSession(Base):
    """Optional persistent session record (used by Streamlit auth UI)."""
    __tablename__ = "user_sessions"
    __table_args__ = {"extend_existing": True}
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_activity_at = Column(DateTime, default=datetime.utcnow)
    
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    @classmethod
    def create_token(cls) -> str:
        return secrets.token_urlsafe(32)
    
    def is_valid(self) -> bool:
        return datetime.utcnow() < self.expires_at


class PaymentHistory(Base):
    """Stripe payment receipt (used by billing dashboards)."""
    __tablename__ = "payment_history"
    __table_args__ = {"extend_existing": True}
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    stripe_payment_id = Column(String(255), nullable=True)
    stripe_invoice_id = Column(String(255), nullable=True)
    
    amount = Column(Float, nullable=False)  # In cents
    currency = Column(String(3), default="usd")
    status = Column(String(50), nullable=False)  # succeeded, failed, pending
    description = Column(String(500), nullable=True)

    # Plan string at time of payment (free/starter/pro/agency). Stored as a
    # plain string rather than the legacy SubscriptionTier enum so it stays
    # aligned with the canonical ``users.plan`` column.
    plan = Column(String(50), nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


def legacy_set_password(user: User, password: str) -> None:
    """Compatibility helper: set a password using bcrypt (matches new login)."""
    from src.auth.password import hash_password
    user.password_hash = hash_password(password)


def legacy_check_password(user: User, password: str) -> bool:
    """Compatibility helper: verify a password using bcrypt."""
    from src.auth.password import verify_password
    if not user.password_hash:
        return False
    return verify_password(password, user.password_hash)


__all__ = [
    "Base",
    "User",
    "YouTubeConnection",
    "UserSession",
    "PaymentHistory",
    "SubscriptionTier",
    "LEGACY_LIMITS",
    "legacy_set_password",
    "legacy_check_password",
]
