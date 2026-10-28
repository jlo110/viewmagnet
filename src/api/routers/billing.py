"""Stripe subscription billing endpoints.

Wires the :class:`src.auth.stripe_integration.StripeService` to HTTP so the
React app can start a checkout, open the Customer Portal, and read live
subscription status. A public webhook ingests Stripe events to keep
``users.plan`` / ``subscription_status`` in sync.

Routes
------
``POST /billing/checkout``      — create a Checkout session for a paid plan
``POST /billing/portal``        — create a Customer Portal session
``GET  /billing/subscription``  — current plan + status + usage limits
``POST /billing/webhook``       — Stripe event ingestion (no auth; signature-verified)

Auth uses :func:`get_current_user` (JWT or PAT). The webhook is unauthenticated
by design — it is verified with the Stripe signing secret instead, and is
excluded from the OpenAPI schema since it's machine-to-machine.

When Stripe isn't configured yet (no ``STRIPE_SECRET_KEY``), the user-facing
endpoints return a clean 503 so the frontend can show "billing coming soon"
rather than a 500.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.auth.dependencies import get_current_user
from src.auth.stripe_integration import PAID_PLANS, StripeService
from src.config import PLAN_LIMITS
from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: str = Field(description="Paid plan to subscribe to: starter, pro, or agency")


class CheckoutResponse(BaseModel):
    checkout_url: str = Field(description="Stripe-hosted Checkout URL to redirect the user to")


class PortalResponse(BaseModel):
    portal_url: str = Field(description="Stripe Customer Portal URL")


class SubscriptionResponse(BaseModel):
    plan: str
    plan_display: str
    status: str | None = None
    expires_at: str | None = None
    price_cents: int = 0
    cancel_at_period_end: bool = False
    has_stripe_customer: bool = False
    # Usage limits for the active plan (so the UI can render quota bars).
    analyses_per_month: int = 0
    analyses_used_this_month: int = 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
):
    """Start a Stripe Checkout session for a paid plan.

    Returns the hosted Checkout URL; the frontend redirects the browser to it.
    On success, the ``customer.subscription.created`` webhook upgrades the
    user's plan.
    """
    plan = (body.plan or "").lower()
    if plan not in PAID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan '{body.plan}'. Choose one of: {', '.join(PAID_PLANS)}.",
        )

    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        svc = StripeService(session)
        if not svc.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Billing is not configured yet. Please try again later.",
            )
        url, error = svc.create_checkout_session(user, plan)
        if error or not url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error or "Failed to create checkout session",
            )
        return CheckoutResponse(checkout_url=url)


@router.post("/portal", response_model=PortalResponse)
async def create_portal(current_user: User = Depends(get_current_user)):
    """Open the Stripe Customer Portal so the user can change card, switch
    plans, or cancel. Requires an existing Stripe customer (i.e. they've
    checked out at least once)."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        svc = StripeService(session)
        if not svc.is_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Billing is not configured yet.",
            )
        url, error = svc.create_portal_session(user)
        if error or not url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error or "No billing account found. Subscribe to a plan first.",
            )
        return PortalResponse(portal_url=url)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(current_user: User = Depends(get_current_user)):
    """Return the user's current plan, Stripe status, and usage limits.

    Always succeeds even when Stripe isn't configured — falls back to the
    locally-stored ``users.plan`` so the dashboard billing tab renders.
    """
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        svc = StripeService(session)
        info = svc.get_subscription_info(user)
        plan_cfg = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
        return SubscriptionResponse(
            plan=info["plan"],
            plan_display=info["plan_display"],
            status=info.get("status"),
            expires_at=info.get("expires_at"),
            price_cents=info.get("price_cents", 0),
            cancel_at_period_end=info.get("cancel_at_period_end", False),
            has_stripe_customer=info.get("has_stripe_customer", False),
            analyses_per_month=plan_cfg.get("analyses_per_month", 0),
            analyses_used_this_month=getattr(user, "analyses_this_month", 0) or 0,
        )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Ingest Stripe webhook events (signature-verified, no auth).

    Stripe POSTs subscription + invoice lifecycle events here. We verify the
    signature with ``STRIPE_WEBHOOK_SECRET`` before processing.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    with get_session() as session:
        svc = StripeService(session)
        if not svc.is_configured:
            # Acknowledge so Stripe doesn't retry forever against an
            # unconfigured environment.
            return {"received": True, "processed": False}
        ok, error = svc.handle_webhook(payload, signature)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error or "Webhook processing failed",
            )
        return {"received": True, "processed": True}
