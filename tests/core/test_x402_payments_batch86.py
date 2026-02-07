"""Tests for core/x402_payments.py - Batch 86."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.x402_payments import (
    PaymentRail, PaymentStatus, PaymentRequest, PaymentReceipt,
    X402Resource, X402Client
)


class TestPaymentRail:
    """Tests for PaymentRail enum."""

    def test_lightning_value(self):
        assert PaymentRail.LIGHTNING.value == "lightning"

    def test_usdc_base_value(self):
        assert PaymentRail.USDC_BASE.value == "usdc_base"

    def test_stablecoin_generic_value(self):
        assert PaymentRail.STABLECOIN_GENERIC.value == "stablecoin"


class TestPaymentStatus:
    """Tests for PaymentStatus enum."""

    def test_pending_value(self):
        assert PaymentStatus.PENDING.value == "pending"

    def test_completed_value(self):
        assert PaymentStatus.COMPLETED.value == "completed"

    def test_failed_value(self):
        assert PaymentStatus.FAILED.value == "failed"


class TestPaymentRequest:
    """Tests for PaymentRequest dataclass."""

    def test_payment_request_creation(self):
        request = PaymentRequest(
            request_id="req123",
            resource_url="https://example.com/resource",
            amount_sats=1000,
            amount_usd=0.50,
            rail=PaymentRail.LIGHTNING,
            invoice="lnbc...",
            expires_at=1234567890.0
        )
        assert request.request_id == "req123"
        assert request.amount_sats == 1000
        assert request.rail == PaymentRail.LIGHTNING


class TestPaymentReceipt:
    """Tests for PaymentReceipt dataclass."""

    def test_payment_receipt_creation(self):
        receipt = PaymentReceipt(
            receipt_id="rec456",
            request_id="req123",
            amount_paid=0.50,
            rail=PaymentRail.LIGHTNING,
            tx_hash="abc123",
            preimage="pre123",
            access_token="token789",
            expires_at=1234567900.0
        )
        assert receipt.receipt_id == "rec456"
        assert receipt.amount_paid == 0.50
        assert receipt.access_token == "token789"


class TestX402Resource:
    """Tests for X402Resource dataclass."""

    def test_resource_creation(self):
        resource = X402Resource(
            resource_id="res789",
            url="https://example.com/api",
            description="API access",
            price_sats=500,
            price_usd=0.25,
            supported_rails=[PaymentRail.LIGHTNING, PaymentRail.USDC_BASE],
            ttl_seconds=3600,
            provider="Example Provider"
        )
        assert resource.resource_id == "res789"
        assert resource.price_sats == 500
        assert len(resource.supported_rails) == 2
