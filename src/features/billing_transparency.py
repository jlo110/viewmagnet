"""
Billing Transparency for ViewMagnet.

Provides clear billing communication including:
- Renewal reminders (7d, 3d, 1d before)
- Usage history tracking
- Invoice emails
- Credit usage visibility
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import structlog

logger = structlog.get_logger()


class NotificationType(Enum):
    """Types of billing notifications."""
    RENEWAL_REMINDER_7D = "renewal_reminder_7d"
    RENEWAL_REMINDER_3D = "renewal_reminder_3d"
    RENEWAL_REMINDER_1D = "renewal_reminder_1d"
    USAGE_WARNING_75 = "usage_warning_75"
    USAGE_WARNING_90 = "usage_warning_90"
    CREDIT_LOW = "credit_low"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_UPGRADED = "subscription_upgraded"
    SUBSCRIPTION_DOWNGRADED = "subscription_downgraded"


@dataclass
class UsageRecord:
    """A single usage record."""
    id: str
    user_id: int
    action: str  # "analysis", "title_generation", "thumbnail_creation", etc.
    credits_used: int
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None


@dataclass
class InvoiceItem:
    """An item on an invoice."""
    description: str
    quantity: int
    unit_price: float
    total: float


@dataclass
class Invoice:
    """A billing invoice."""
    invoice_id: str
    user_id: int
    user_email: str
    user_name: str
    items: List[InvoiceItem]
    subtotal: float
    tax: float
    total: float
    currency: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    status: str = "pending"  # pending, paid, failed, refunded
    stripe_invoice_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "user_id": self.user_id,
            "items": [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total": item.total,
                }
                for item in self.items
            ],
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }


@dataclass
class BillingNotification:
    """A billing notification to send to user."""
    notification_type: NotificationType
    user_id: int
    user_email: str
    subject: str
    body: str
    scheduled_for: datetime
    sent_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class UsageTracker:
    """
    Tracks user credit usage for billing transparency.
    """
    
    # Credit costs per action
    CREDIT_COSTS = {
        "video_analysis": 1,
        "title_generation": 1,
        "thumbnail_creation": 2,
        "script_generation": 3,
        "voiceover_generation": 5,
        "faceless_video": 10,
        "winning_formula": 2,
        "competitor_analysis": 2,
    }
    
    def __init__(self, session):
        self.session = session
    
    def record_usage(
        self,
        user_id: int,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> UsageRecord:
        """
        Record a credit usage event.
        
        Args:
            user_id: User ID.
            action: Action performed.
            details: Additional details about the action.
        
        Returns:
            UsageRecord object.
        """
        import uuid
        
        credits_used = self.CREDIT_COSTS.get(action, 1)
        
        record = UsageRecord(
            id=str(uuid.uuid4())[:8],
            user_id=user_id,
            action=action,
            credits_used=credits_used,
            timestamp=datetime.utcnow(),
            details=details,
        )
        
        # Store in database (would use actual model)
        logger.info(f"Usage recorded: user={user_id}, action={action}, credits={credits_used}")
        
        return record
    
    def get_usage_history(
        self,
        user_id: int,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get usage history for a user.
        
        Args:
            user_id: User ID.
            days: Number of days of history.
        
        Returns:
            List of usage records.
        """
        # Would query database
        return []
    
    def get_usage_summary(
        self,
        user_id: int,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get usage summary for a user.
        
        Args:
            user_id: User ID.
            days: Number of days to summarize.
        
        Returns:
            Usage summary dict.
        """
        history = self.get_usage_history(user_id, days)
        
        by_action = {}
        total_credits = 0
        
        for record in history:
            action = record.get("action", "unknown")
            credits = record.get("credits_used", 0)
            
            by_action[action] = by_action.get(action, 0) + credits
            total_credits += credits
        
        return {
            "user_id": user_id,
            "period_days": days,
            "total_credits_used": total_credits,
            "by_action": by_action,
            "daily_average": round(total_credits / days, 1) if days > 0 else 0,
        }


class RenewalReminderService:
    """
    Sends renewal reminders before subscription renewal.
    """
    
    REMINDER_DAYS = [7, 3, 1]  # Days before renewal to send reminders
    
    def __init__(self, email_service=None):
        self.email_service = email_service
    
    def get_users_needing_reminder(
        self,
        days_before: int,
    ) -> List[Dict[str, Any]]:
        """
        Get users who need a renewal reminder.
        
        Args:
            days_before: Days before renewal.
        
        Returns:
            List of users needing reminders.
        """
        # Would query database for users with renewal date = now + days_before
        return []
    
    def create_reminder(
        self,
        user: Dict[str, Any],
        days_before: int,
    ) -> BillingNotification:
        """
        Create a renewal reminder notification.
        
        Args:
            user: User data dict.
            days_before: Days until renewal.
        
        Returns:
            BillingNotification object.
        """
        notification_type = {
            7: NotificationType.RENEWAL_REMINDER_7D,
            3: NotificationType.RENEWAL_REMINDER_3D,
            1: NotificationType.RENEWAL_REMINDER_1D,
        }.get(days_before, NotificationType.RENEWAL_REMINDER_7D)
        
        subject = f"Your ViewMagnet subscription renews in {days_before} day{'s' if days_before > 1 else ''}"
        
        body = f"""
Hi {user.get('name', 'there')},

Your ViewMagnet {user.get('plan', 'subscription')} subscription will automatically renew in {days_before} day{'s' if days_before > 1 else ''}.

Subscription Details:
- Plan: {user.get('plan', 'Unknown').title()}
- Amount: ${user.get('amount', 0):.2f}/{user.get('interval', 'month')}
- Renewal Date: {user.get('renewal_date', 'N/A')}

What you've accomplished this billing period:
- Videos analyzed: {user.get('videos_analyzed', 0)}
- Titles generated: {user.get('titles_generated', 0)}
- Credits remaining: {user.get('credits_remaining', 0)}

No action needed - your subscription will renew automatically.
To manage your subscription, visit: https://app.viewmagnet.com/settings/billing

Thanks for being a ViewMagnet member!
The ViewMagnet Team
        """.strip()
        
        return BillingNotification(
            notification_type=notification_type,
            user_id=user.get("id", 0),
            user_email=user.get("email", ""),
            subject=subject,
            body=body,
            scheduled_for=datetime.utcnow(),
            metadata={
                "days_before": days_before,
                "plan": user.get("plan"),
                "amount": user.get("amount"),
            },
        )
    
    def send_reminder(self, notification: BillingNotification) -> bool:
        """
        Send a renewal reminder.
        
        Args:
            notification: The notification to send.
        
        Returns:
            True if sent successfully.
        """
        if not self.email_service:
            logger.warning("Email service not configured, cannot send reminder")
            return False
        
        try:
            self.email_service.send(
                to=notification.user_email,
                subject=notification.subject,
                body=notification.body,
            )
            notification.sent_at = datetime.utcnow()
            logger.info(f"Sent renewal reminder to {notification.user_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")
            return False
    
    def process_reminders(self):
        """Process all pending renewal reminders."""
        for days in self.REMINDER_DAYS:
            users = self.get_users_needing_reminder(days)
            
            for user in users:
                notification = self.create_reminder(user, days)
                self.send_reminder(notification)


class InvoiceService:
    """
    Generates and sends invoice emails.
    """
    
    def __init__(self, email_service=None):
        self.email_service = email_service
    
    def create_invoice(
        self,
        user_id: int,
        user_email: str,
        user_name: str,
        plan: str,
        amount: float,
        stripe_invoice_id: Optional[str] = None,
    ) -> Invoice:
        """
        Create an invoice for a subscription payment.
        
        Args:
            user_id: User ID.
            user_email: User email.
            user_name: User name.
            plan: Plan name.
            amount: Payment amount.
            stripe_invoice_id: Stripe invoice ID if applicable.
        
        Returns:
            Invoice object.
        """
        import uuid
        
        items = [
            InvoiceItem(
                description=f"ViewMagnet {plan.title()} Plan - Monthly Subscription",
                quantity=1,
                unit_price=amount,
                total=amount,
            )
        ]
        
        # Calculate tax (simplified - would use actual tax calculation)
        tax_rate = 0.0  # No tax for digital services in many jurisdictions
        tax = round(amount * tax_rate, 2)
        total = amount + tax
        
        return Invoice(
            invoice_id=f"INV-{datetime.now().strftime('%Y%m')}-{str(uuid.uuid4())[:8].upper()}",
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            items=items,
            subtotal=amount,
            tax=tax,
            total=total,
            currency="USD",
            created_at=datetime.utcnow(),
            paid_at=datetime.utcnow(),
            status="paid",
            stripe_invoice_id=stripe_invoice_id,
        )
    
    def generate_invoice_email(self, invoice: Invoice) -> str:
        """
        Generate invoice email body.
        
        Args:
            invoice: Invoice object.
        
        Returns:
            Email body as string.
        """
        items_text = "\n".join([
            f"  - {item.description}: ${item.total:.2f}"
            for item in invoice.items
        ])
        
        return f"""
Hi {invoice.user_name},

Thank you for your payment! Here's your invoice:

Invoice ID: {invoice.invoice_id}
Date: {invoice.created_at.strftime('%B %d, %Y')}

Items:
{items_text}

Subtotal: ${invoice.subtotal:.2f}
Tax: ${invoice.tax:.2f}
Total: ${invoice.total:.2f} {invoice.currency}

Status: {invoice.status.upper()}

You can view your billing history and download invoices at:
https://app.viewmagnet.com/settings/billing

Questions? Reply to this email or contact support@viewmagnet.com.

Thanks for using ViewMagnet!
The ViewMagnet Team
        """.strip()
    
    def send_invoice(self, invoice: Invoice) -> bool:
        """
        Send invoice email to user.
        
        Args:
            invoice: Invoice to send.
        
        Returns:
            True if sent successfully.
        """
        if not self.email_service:
            logger.warning("Email service not configured")
            return False
        
        try:
            body = self.generate_invoice_email(invoice)
            self.email_service.send(
                to=invoice.user_email,
                subject=f"ViewMagnet Invoice {invoice.invoice_id}",
                body=body,
            )
            logger.info(f"Sent invoice {invoice.invoice_id} to {invoice.user_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send invoice: {e}")
            return False


class BillingTransparencyService:
    """
    Main service for billing transparency features.
    """
    
    def __init__(self, session=None, email_service=None):
        self.session = session
        self.usage_tracker = UsageTracker(session) if session else None
        self.reminder_service = RenewalReminderService(email_service)
        self.invoice_service = InvoiceService(email_service)
    
    def get_billing_overview(self, user_id: int) -> Dict[str, Any]:
        """
        Get billing overview for a user.
        
        Args:
            user_id: User ID.
        
        Returns:
            Billing overview dict.
        """
        # Would fetch from database
        return {
            "user_id": user_id,
            "current_plan": "starter",
            "plan_price": 19.00,
            "billing_interval": "monthly",
            "credits_included": 500,
            "credits_used": 127,
            "credits_remaining": 373,
            "next_renewal": (datetime.utcnow() + timedelta(days=15)).isoformat(),
            "payment_method": "Visa ending in 4242",
            "billing_history": [],
        }
    
    def get_credit_usage_chart_data(
        self,
        user_id: int,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get data for credit usage chart.
        
        Args:
            user_id: User ID.
            days: Number of days.
        
        Returns:
            Chart data dict.
        """
        # Would query actual usage from database
        # Return sample data structure
        return {
            "user_id": user_id,
            "period_days": days,
            "data_points": [
                {"date": (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d"), "credits": 5}
                for i in range(days, 0, -1)
            ],
            "by_category": {
                "video_analysis": 45,
                "title_generation": 30,
                "thumbnail_creation": 20,
                "other": 5,
            },
        }
    
    def process_payment_webhook(
        self,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a payment webhook from Stripe.
        
        Args:
            event_type: Stripe event type.
            event_data: Event data.
        
        Returns:
            Processing result.
        """
        if event_type == "invoice.payment_succeeded":
            # Create and send invoice
            invoice_data = event_data.get("invoice", {})
            user_id = invoice_data.get("metadata", {}).get("user_id")
            
            if user_id:
                # Create invoice record
                invoice = self.invoice_service.create_invoice(
                    user_id=int(user_id),
                    user_email=invoice_data.get("customer_email", ""),
                    user_name=invoice_data.get("customer_name", ""),
                    plan=invoice_data.get("lines", {}).get("data", [{}])[0].get("description", ""),
                    amount=invoice_data.get("amount_paid", 0) / 100,  # Convert from cents
                    stripe_invoice_id=invoice_data.get("id"),
                )
                
                # Send invoice email
                self.invoice_service.send_invoice(invoice)
                
                return {"status": "success", "invoice_id": invoice.invoice_id}
        
        elif event_type == "invoice.payment_failed":
            # Would send payment failed notification
            return {"status": "payment_failed_notification_sent"}
        
        elif event_type == "customer.subscription.deleted":
            # Would handle subscription cancellation
            return {"status": "subscription_cancelled"}
        
        return {"status": "unhandled_event", "event_type": event_type}


# API models and routes would be added to main.py
API_ROUTES = """
# Add these routes to src/api/main.py:

@app.get("/billing/overview")
async def get_billing_overview(user_id: int = Query(...)):
    service = BillingTransparencyService()
    return service.get_billing_overview(user_id)

@app.get("/billing/usage")
async def get_usage_history(user_id: int = Query(...), days: int = Query(30)):
    service = BillingTransparencyService()
    return service.get_credit_usage_chart_data(user_id, days)

@app.post("/billing/webhook")
async def handle_billing_webhook(request: Request):
    import stripe
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    
    service = BillingTransparencyService()
    return service.process_payment_webhook(event["type"], event["data"]["object"])
"""
