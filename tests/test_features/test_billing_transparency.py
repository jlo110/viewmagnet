"""Tests for billing_transparency.py - Billing features."""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from src.features.billing_transparency import (
    NotificationType,
    UsageRecord,
    InvoiceItem,
    Invoice,
    BillingNotification,
    UsageTracker,
    RenewalReminderService,
    InvoiceService,
    BillingTransparencyService,
)


class TestNotificationType:
    """Tests for NotificationType enum."""
    
    def test_notification_types_exist(self):
        """Test all expected notification types exist."""
        assert NotificationType.RENEWAL_REMINDER_7D.value == "renewal_reminder_7d"
        assert NotificationType.RENEWAL_REMINDER_3D.value == "renewal_reminder_3d"
        assert NotificationType.RENEWAL_REMINDER_1D.value == "renewal_reminder_1d"
        assert NotificationType.PAYMENT_SUCCESS.value == "payment_success"
        assert NotificationType.PAYMENT_FAILED.value == "payment_failed"


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""
    
    def test_usage_record_creation(self):
        """Test creating a UsageRecord instance."""
        record = UsageRecord(
            id="rec123",
            user_id=1,
            action="video_analysis",
            credits_used=1,
            timestamp=datetime.utcnow(),
        )
        assert record.id == "rec123"
        assert record.user_id == 1
        assert record.credits_used == 1
        assert record.details is None


class TestInvoiceItem:
    """Tests for InvoiceItem dataclass."""
    
    def test_invoice_item_creation(self):
        """Test creating an InvoiceItem instance."""
        item = InvoiceItem(
            description="ViewMagnet Pro Plan - Monthly",
            quantity=1,
            unit_price=29.00,
            total=29.00,
        )
        assert item.description == "ViewMagnet Pro Plan - Monthly"
        assert item.total == 29.00


class TestInvoice:
    """Tests for Invoice dataclass."""
    
    def test_invoice_creation(self):
        """Test creating an Invoice instance."""
        items = [
            InvoiceItem("Monthly Plan", 1, 19.00, 19.00),
        ]
        invoice = Invoice(
            invoice_id="INV-202601-ABC123",
            user_id=1,
            user_email="user@example.com",
            user_name="Test User",
            items=items,
            subtotal=19.00,
            tax=0.0,
            total=19.00,
            currency="USD",
            created_at=datetime.utcnow(),
        )
        assert invoice.invoice_id == "INV-202601-ABC123"
        assert invoice.status == "pending"
        assert invoice.paid_at is None
    
    def test_invoice_to_dict(self):
        """Test Invoice to_dict method."""
        items = [
            InvoiceItem("Monthly Plan", 1, 19.00, 19.00),
        ]
        now = datetime.utcnow()
        invoice = Invoice(
            invoice_id="INV-TEST",
            user_id=1,
            user_email="user@example.com",
            user_name="Test User",
            items=items,
            subtotal=19.00,
            tax=0.0,
            total=19.00,
            currency="USD",
            created_at=now,
            status="paid",
        )
        
        result = invoice.to_dict()
        
        assert result["invoice_id"] == "INV-TEST"
        assert result["subtotal"] == 19.00
        assert result["status"] == "paid"
        assert len(result["items"]) == 1


class TestBillingNotification:
    """Tests for BillingNotification dataclass."""
    
    def test_notification_creation(self):
        """Test creating a BillingNotification instance."""
        notification = BillingNotification(
            notification_type=NotificationType.RENEWAL_REMINDER_7D,
            user_id=1,
            user_email="user@example.com",
            subject="Your subscription renews in 7 days",
            body="Hi, your subscription will renew soon.",
            scheduled_for=datetime.utcnow(),
        )
        assert notification.notification_type == NotificationType.RENEWAL_REMINDER_7D
        assert notification.sent_at is None


class TestUsageTracker:
    """Tests for UsageTracker."""
    
    def test_credit_costs_defined(self):
        """Test credit costs are defined for all actions."""
        assert UsageTracker.CREDIT_COSTS["video_analysis"] == 1
        assert UsageTracker.CREDIT_COSTS["thumbnail_creation"] == 2
        assert UsageTracker.CREDIT_COSTS["voiceover_generation"] == 5
        assert UsageTracker.CREDIT_COSTS["faceless_video"] == 10
    
    def test_record_usage(self):
        """Test recording usage creates a record."""
        mock_session = Mock()
        tracker = UsageTracker(mock_session)
        
        record = tracker.record_usage(
            user_id=1,
            action="video_analysis",
            details={"video_id": "test123"},
        )
        
        assert record.user_id == 1
        assert record.action == "video_analysis"
        assert record.credits_used == 1
        assert record.details == {"video_id": "test123"}
    
    def test_record_usage_unknown_action(self):
        """Test recording usage for unknown action defaults to 1 credit."""
        mock_session = Mock()
        tracker = UsageTracker(mock_session)
        
        record = tracker.record_usage(
            user_id=1,
            action="unknown_action",
        )
        
        assert record.credits_used == 1  # Default
    
    def test_get_usage_summary(self):
        """Test getting usage summary."""
        mock_session = Mock()
        tracker = UsageTracker(mock_session)
        
        # Mock returns empty history
        with patch.object(tracker, "get_usage_history", return_value=[]):
            summary = tracker.get_usage_summary(user_id=1, days=30)
        
        assert summary["user_id"] == 1
        assert summary["period_days"] == 30
        assert summary["total_credits_used"] == 0


class TestRenewalReminderService:
    """Tests for RenewalReminderService."""
    
    def test_reminder_days(self):
        """Test reminder days are set correctly."""
        assert RenewalReminderService.REMINDER_DAYS == [7, 3, 1]
    
    def test_create_reminder_7d(self):
        """Test creating 7-day reminder."""
        service = RenewalReminderService()
        
        user = {
            "id": 1,
            "name": "Test User",
            "email": "test@example.com",
            "plan": "starter",
            "amount": 19.00,
            "interval": "month",
            "renewal_date": "2026-02-01",
        }
        
        notification = service.create_reminder(user, days_before=7)
        
        assert notification.notification_type == NotificationType.RENEWAL_REMINDER_7D
        assert "7 days" in notification.subject
        assert "Test User" in notification.body
        assert "$19.00" in notification.body
    
    def test_create_reminder_1d(self):
        """Test creating 1-day reminder."""
        service = RenewalReminderService()
        
        user = {
            "id": 1,
            "name": "User",
            "email": "test@example.com",
            "plan": "pro",
            "amount": 49.00,
            "interval": "month",
        }
        
        notification = service.create_reminder(user, days_before=1)
        
        assert notification.notification_type == NotificationType.RENEWAL_REMINDER_1D
        assert "1 day" in notification.subject
        # Singular "day" not "days"
        assert "days" not in notification.subject
    
    def test_send_reminder_without_email_service(self):
        """Test send_reminder returns False without email service."""
        service = RenewalReminderService(email_service=None)
        
        notification = BillingNotification(
            notification_type=NotificationType.RENEWAL_REMINDER_7D,
            user_id=1,
            user_email="test@example.com",
            subject="Test",
            body="Test body",
            scheduled_for=datetime.utcnow(),
        )
        
        result = service.send_reminder(notification)
        
        assert result is False
    
    def test_send_reminder_with_email_service(self):
        """Test send_reminder sends email with service."""
        mock_email = Mock()
        service = RenewalReminderService(email_service=mock_email)
        
        notification = BillingNotification(
            notification_type=NotificationType.RENEWAL_REMINDER_7D,
            user_id=1,
            user_email="test@example.com",
            subject="Test Subject",
            body="Test body",
            scheduled_for=datetime.utcnow(),
        )
        
        result = service.send_reminder(notification)
        
        assert result is True
        mock_email.send.assert_called_once_with(
            to="test@example.com",
            subject="Test Subject",
            body="Test body",
        )
        assert notification.sent_at is not None


class TestInvoiceService:
    """Tests for InvoiceService."""
    
    def test_create_invoice(self):
        """Test creating an invoice."""
        service = InvoiceService()
        
        invoice = service.create_invoice(
            user_id=1,
            user_email="test@example.com",
            user_name="Test User",
            plan="starter",
            amount=19.00,
            stripe_invoice_id="in_123",
        )
        
        assert invoice.user_id == 1
        assert invoice.total == 19.00
        assert invoice.status == "paid"
        assert len(invoice.items) == 1
        assert "Starter Plan" in invoice.items[0].description
    
    def test_create_invoice_id_format(self):
        """Test invoice ID has correct format."""
        service = InvoiceService()
        
        invoice = service.create_invoice(
            user_id=1,
            user_email="test@example.com",
            user_name="Test",
            plan="pro",
            amount=49.00,
        )
        
        assert invoice.invoice_id.startswith("INV-")
        assert len(invoice.invoice_id) > 10
    
    def test_generate_invoice_email(self):
        """Test generating invoice email body."""
        service = InvoiceService()
        
        items = [InvoiceItem("Test Plan", 1, 19.00, 19.00)]
        invoice = Invoice(
            invoice_id="INV-TEST-123",
            user_id=1,
            user_email="test@example.com",
            user_name="Test User",
            items=items,
            subtotal=19.00,
            tax=0.0,
            total=19.00,
            currency="USD",
            created_at=datetime.utcnow(),
            status="paid",
        )
        
        email_body = service.generate_invoice_email(invoice)
        
        assert "Test User" in email_body
        assert "INV-TEST-123" in email_body
        assert "$19.00" in email_body
        assert "PAID" in email_body
    
    def test_send_invoice_without_email_service(self):
        """Test send_invoice returns False without email service."""
        service = InvoiceService(email_service=None)
        
        invoice = Mock()
        
        result = service.send_invoice(invoice)
        
        assert result is False


class TestBillingTransparencyService:
    """Tests for BillingTransparencyService."""
    
    def test_get_billing_overview(self):
        """Test getting billing overview."""
        service = BillingTransparencyService()
        
        overview = service.get_billing_overview(user_id=1)
        
        assert overview["user_id"] == 1
        assert "current_plan" in overview
        assert "credits_included" in overview
        assert "credits_remaining" in overview
        assert "next_renewal" in overview
    
    def test_get_credit_usage_chart_data(self):
        """Test getting credit usage chart data."""
        service = BillingTransparencyService()
        
        data = service.get_credit_usage_chart_data(user_id=1, days=30)
        
        assert data["user_id"] == 1
        assert data["period_days"] == 30
        assert "data_points" in data
        assert "by_category" in data
        assert len(data["data_points"]) == 30
    
    def test_process_payment_webhook_success(self):
        """Test processing successful payment webhook."""
        mock_email = Mock()
        service = BillingTransparencyService(email_service=mock_email)
        
        event_data = {
            "invoice": {
                "id": "in_123",
                "metadata": {"user_id": "1"},
                "customer_email": "test@example.com",
                "customer_name": "Test User",
                "amount_paid": 1900,  # cents
                "lines": {"data": [{"description": "Starter Plan"}]},
            }
        }
        
        result = service.process_payment_webhook(
            event_type="invoice.payment_succeeded",
            event_data=event_data,
        )
        
        assert result["status"] == "success"
        assert "invoice_id" in result
    
    def test_process_payment_webhook_failed(self):
        """Test processing failed payment webhook."""
        service = BillingTransparencyService()
        
        result = service.process_payment_webhook(
            event_type="invoice.payment_failed",
            event_data={},
        )
        
        assert result["status"] == "payment_failed_notification_sent"
    
    def test_process_payment_webhook_unhandled(self):
        """Test processing unhandled webhook event."""
        service = BillingTransparencyService()
        
        result = service.process_payment_webhook(
            event_type="unknown.event",
            event_data={},
        )
        
        assert result["status"] == "unhandled_event"
        assert result["event_type"] == "unknown.event"
