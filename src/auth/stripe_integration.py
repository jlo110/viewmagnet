"""
Stripe integration for subscription payments.

Handles:
- Customer creation
- Checkout + Customer Portal sessions
- Webhook processing (subscription lifecycle + invoices)
- Payment history

This service operates on the canonical :class:`src.database.models.User`
model. Plans are plain strings (``free`` / ``starter`` / ``pro`` /
``agency``) matching ``users.plan`` and ``src.config.PLAN_LIMITS`` — there
is no separate subscription-tier enum in the persistence layer.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import structlog

from src.auth.models import PaymentHistory
from src.database.models import User

logger = structlog.get_logger()


# Paid plans we can check out (free has no Stripe price).
PAID_PLANS = ("starter", "pro", "agency")

# Price IDs — configured in the Stripe dashboard and supplied via env.
# Defaults are obvious placeholders so a missing config fails loudly at
# checkout time rather than silently charging the wrong amount.
STRIPE_PRICES = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", "price_starter"),  # $9/mo
    "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro"),  # $29/mo
    "agency": os.getenv("STRIPE_PRICE_AGENCY", "price_agency"),  # $99/mo
}

# Display price in cents (used for receipts / UI fallbacks).
PLAN_PRICE_CENTS = {
    "free": 0,
    "starter": 900,
    "pro": 2900,
    "agency": 9900,
}


def _price_id_for_plan(plan: str) -> Optional[str]:
    """Resolve the Stripe price id for a plan, re-reading env each call so
    a late-bound key (the user said they'd add keys later) is picked up
    without a process restart."""
    env_key = {
        "starter": "STRIPE_PRICE_STARTER",
        "pro": "STRIPE_PRICE_PRO",
        "agency": "STRIPE_PRICE_AGENCY",
    }.get(plan)
    if not env_key:
        return None
    return os.getenv(env_key) or STRIPE_PRICES.get(plan)


class StripeService:
    """Stripe payment integration service (subscription lifecycle)."""

    def __init__(self, db_session):
        """Initialize with a SQLAlchemy session."""
        self.db = db_session
        self.stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        frontend = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.success_url = os.getenv(
            "STRIPE_SUCCESS_URL",
            f"{frontend}/dashboard/settings?tab=billing&checkout=success",
        )
        self.cancel_url = os.getenv(
            "STRIPE_CANCEL_URL",
            f"{frontend}/dashboard/settings?tab=billing&checkout=cancelled",
        )

        self._stripe = None

    @property
    def is_configured(self) -> bool:
        """True when a Stripe secret key is present. Routes use this to
        return a clean 503 instead of a 500 when billing isn't wired yet."""
        return bool(self.stripe_secret_key)

    @property
    def stripe(self):
        """Lazy-load the stripe module + set the API key."""
        if self._stripe is None:
            try:
                import stripe
            except ImportError as exc:  # pragma: no cover
                raise ImportError("stripe package required: pip install stripe") from exc
            stripe.api_key = self.stripe_secret_key
            self._stripe = stripe
        return self._stripe

    # ------------------------------------------------------------------
    # Customer
    # ------------------------------------------------------------------

    def create_customer(self, user: User) -> Optional[str]:
        """Create (or reuse) a Stripe customer for the user."""
        if user.stripe_customer_id:
            return user.stripe_customer_id
        try:
            customer = self.stripe.Customer.create(
                email=user.email,
                name=user.name,
                metadata={"user_id": str(user.id)},
            )
            user.stripe_customer_id = customer.id
            self.db.commit()
            logger.info("stripe.customer_created", user_id=user.id, customer_id=customer.id)
            return customer.id
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.customer_create_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Checkout / Portal
    # ------------------------------------------------------------------

    def create_checkout_session(
        self, user: User, plan: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Create a Stripe Checkout session for a paid plan.

        Returns ``(checkout_url, None)`` on success or ``(None, error)``.
        """
        plan = (plan or "").lower()
        if plan == "free":
            return None, "Cannot checkout for the free plan"
        if plan not in PAID_PLANS:
            return None, f"Unknown plan: {plan}"

        price_id = _price_id_for_plan(plan)
        if not price_id:
            return None, f"No Stripe price configured for {plan}"

        customer_id = self.create_customer(user)
        if not customer_id:
            return None, "Failed to create payment customer"

        try:
            session = self.stripe.checkout.Session.create(
                customer=customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=self.success_url,
                cancel_url=self.cancel_url,
                allow_promotion_codes=True,
                # 30-day free trial — matches the marketing "30-day free trial".
                subscription_data={
                    "trial_period_days": 30,
                    "metadata": {"user_id": str(user.id), "plan": plan},
                },
                metadata={"user_id": str(user.id), "plan": plan},
            )
            logger.info(
                "stripe.checkout_created",
                user_id=user.id,
                plan=plan,
                session_id=session.id,
            )
            return session.url, None
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.checkout_failed", error=str(exc))
            return None, f"Payment system error: {exc}"

    def create_portal_session(self, user: User) -> Tuple[Optional[str], Optional[str]]:
        """Create a Stripe Customer Portal session for managing billing."""
        if not user.stripe_customer_id:
            return None, "No payment account found"
        try:
            session = self.stripe.billing_portal.Session.create(
                customer=user.stripe_customer_id,
                return_url=self.success_url,
            )
            return session.url, None
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.portal_failed", error=str(exc))
            return None, f"Portal error: {exc}"

    def cancel_subscription(self, user: User) -> Tuple[bool, Optional[str]]:
        """Cancel the user's subscription at period end."""
        if not user.stripe_subscription_id:
            return False, "No active subscription found"
        try:
            self.stripe.Subscription.modify(
                user.stripe_subscription_id, cancel_at_period_end=True
            )
            logger.info("stripe.subscription_cancel_scheduled", user_id=user.id)
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.cancel_failed", error=str(exc))
            return False, f"Cancellation failed: {exc}"

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def handle_webhook(self, payload: bytes, signature: str) -> Tuple[bool, Optional[str]]:
        """Verify + dispatch a Stripe webhook event."""
        try:
            event = self.stripe.Webhook.construct_event(
                payload, signature, self.stripe_webhook_secret
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.webhook_bad_signature", error=str(exc))
            return False, "Invalid signature"

        event_type = event["type"]
        data = event["data"]["object"]
        logger.info("stripe.webhook", event_type=event_type)

        try:
            if event_type == "customer.subscription.created":
                self._handle_subscription_created(data)
            elif event_type == "customer.subscription.updated":
                self._handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                self._handle_subscription_deleted(data)
            elif event_type == "invoice.paid":
                self._handle_invoice_paid(data)
            elif event_type == "invoice.payment_failed":
                self._handle_payment_failed(data)
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe.webhook_failed", error=str(exc), event_type=event_type)
            return False, str(exc)

    def _handle_subscription_created(self, subscription: Dict) -> None:
        user_id = subscription.get("metadata", {}).get("user_id")
        plan = subscription.get("metadata", {}).get("plan")
        if not user_id or not plan:
            return
        user = self.db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return
        user.plan = plan
        user.stripe_subscription_id = subscription["id"]
        user.subscription_status = subscription.get("status")
        if subscription.get("current_period_end"):
            user.subscription_expires = datetime.utcfromtimestamp(
                subscription["current_period_end"]
            )
        self.db.commit()
        logger.info("stripe.subscription_created", user_id=user.id, plan=plan)

    def _handle_subscription_updated(self, subscription: Dict) -> None:
        user = (
            self.db.query(User)
            .filter(User.stripe_subscription_id == subscription["id"])
            .first()
        )
        if not user:
            return
        user.subscription_status = subscription.get("status")
        if subscription.get("current_period_end"):
            user.subscription_expires = datetime.utcfromtimestamp(
                subscription["current_period_end"]
            )
        # A plan change made through the Customer Portal shows up here.
        plan = subscription.get("metadata", {}).get("plan")
        if plan:
            user.plan = plan
        self.db.commit()
        logger.info(
            "stripe.subscription_updated",
            user_id=user.id,
            status=subscription.get("status"),
        )

    def _handle_subscription_deleted(self, subscription: Dict) -> None:
        user = (
            self.db.query(User)
            .filter(User.stripe_subscription_id == subscription["id"])
            .first()
        )
        if not user:
            return
        user.plan = "free"
        user.stripe_subscription_id = None
        user.subscription_status = "canceled"
        user.subscription_expires = None
        self.db.commit()
        logger.info("stripe.subscription_deleted", user_id=user.id)

    def _handle_invoice_paid(self, invoice: Dict) -> None:
        user = (
            self.db.query(User)
            .filter(User.stripe_customer_id == invoice.get("customer"))
            .first()
        )
        if not user:
            return
        payment = PaymentHistory(
            user_id=user.id,
            stripe_payment_id=invoice.get("payment_intent"),
            stripe_invoice_id=invoice.get("id"),
            amount=invoice.get("amount_paid", 0),
            currency=invoice.get("currency", "usd"),
            status="succeeded",
            description=invoice.get("description"),
            plan=user.plan,
            period_start=datetime.utcfromtimestamp(invoice["period_start"])
            if invoice.get("period_start")
            else None,
            period_end=datetime.utcfromtimestamp(invoice["period_end"])
            if invoice.get("period_end")
            else None,
        )
        self.db.add(payment)
        self.db.commit()
        logger.info("stripe.invoice_paid", user_id=user.id, amount=invoice.get("amount_paid"))

    def _handle_payment_failed(self, invoice: Dict) -> None:
        user = (
            self.db.query(User)
            .filter(User.stripe_customer_id == invoice.get("customer"))
            .first()
        )
        if not user:
            return
        payment = PaymentHistory(
            user_id=user.id,
            stripe_invoice_id=invoice.get("id"),
            amount=invoice.get("amount_due", 0),
            currency=invoice.get("currency", "usd"),
            status="failed",
            description="Payment failed",
            plan=user.plan,
        )
        self.db.add(payment)
        user.subscription_status = "past_due"
        self.db.commit()
        logger.warning("stripe.payment_failed", user_id=user.id)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_subscription_info(self, user: User) -> Dict[str, Any]:
        """Return a UI-friendly summary of the user's subscription."""
        info: Dict[str, Any] = {
            "plan": user.plan,
            "plan_display": (user.plan or "free").title(),
            "status": user.subscription_status,
            "expires_at": user.subscription_expires.isoformat()
            if user.subscription_expires
            else None,
            "price_cents": PLAN_PRICE_CENTS.get(user.plan, 0),
            "has_stripe_customer": bool(user.stripe_customer_id),
        }
        if user.stripe_subscription_id and self.is_configured:
            try:
                sub = self.stripe.Subscription.retrieve(user.stripe_subscription_id)
                info["cancel_at_period_end"] = sub.get("cancel_at_period_end", False)
                info["status"] = sub.get("status", info["status"])
            except Exception:  # noqa: BLE001
                pass
        return info


# ---------------------------------------------------------------------------
# Pricing display (back-compat for the legacy Streamlit UI)
# ---------------------------------------------------------------------------


def get_pricing_tiers() -> list:
    """Return pricing tiers for display.

    Kept for the legacy Streamlit ``auth_ui`` module. The canonical
    public pricing surface is the React Pricing component + ``/pricing.md``.
    """
    from src.auth.models import SubscriptionTier

    return [
        {
            "tier": SubscriptionTier.FREE,
            "name": "Free",
            "price": 0,
            "price_display": "$0",
            "popular": False,
        },
        {
            "tier": SubscriptionTier.STARTER,
            "name": "Starter",
            "price": 9,
            "price_display": "$9/mo",
            "popular": False,
        },
        {
            "tier": SubscriptionTier.PRO,
            "name": "Pro",
            "price": 29,
            "price_display": "$29/mo",
            "popular": True,
        },
        {
            "tier": SubscriptionTier.AGENCY,
            "name": "Agency",
            "price": 99,
            "price_display": "$99/mo",
            "popular": False,
        },
    ]
