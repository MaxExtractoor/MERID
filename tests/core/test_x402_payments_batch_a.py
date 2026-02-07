"""Tests for core/x402_payments.py - Batch A."""
import pytest
from decimal import Decimal

from core.x402_payments import (
    PaymentRail, PaymentStatus, PaymentRequest, PaymentReceipt, X402Resource
)


class TestPaymentRailEnum:
    """Tests for PaymentRail enum."""

    def test_payment_rail_values(self):
        assert PaymentRail.LIGHTNING.value == "lightning"
        assert PaymentRail.USDC_BASE.value == "usdc_base"
        assert PaymentRail.USDC_ARBITRUM.value == "usdc_arbitrum"
        assert PaymentRail.ETH_MAINNET.value == "eth_mainnet"
        assert PaymentRail.STABLECOIN_GENERIC.value == "stablecoin"


class TestPaymentStatusEnum:
    """Tests for PaymentStatus enum."""

    def test_payment_status_values(self):
        assert PaymentStatus.PENDING.value == "pending"
        assert PaymentStatus.COMPLETED.value == "completed"
        assert PaymentStatus.FAILED.value == "failed"
        assert PaymentStatus.EXPIRED.value == "expired"
        assert PaymentStatus.REFUNDED.value == "refunded"


class TestPaymentRequestDataclass:
    """Tests for PaymentRequest dataclass."""

    def test_payment_request_creation(self):
        request = PaymentRequest(
            request_id="req_123",
            resource_url="https://api.merid.ai/data/feed",
            amount_sats=10000,
            amount_usd=5.50,
            rail=PaymentRail.LIGHTNING,
            invoice="lnbc100u1p3...",
            expires_at=1234567890.0
        )
        assert request.request_id == "req_123"
        assert request.resource_url == "https://api.merid.ai/data/feed"
        assert request.amount_sats == 10000
        assert request.amount_usd == 5.50
        assert request.rail == PaymentRail.LIGHTNING
        assert request.invoice == "lnbc100u1p3..."
        assert request.expires_at == 1234567890.0

    def test_payment_request_defaults(self):
        request = PaymentRequest(
            request_id="req_456",
            resource_url="https://api.merid.ai/signal",
            amount_sats=5000,
            amount_usd=2.75,
            rail=PaymentRail.USDC_BASE,
            invoice="0xabc...",
            expires_at=1234567890.0
        )
        assert request.metadata == {}
        assert request.created_at > 0


class TestPaymentReceiptDataclass:
    """Tests for PaymentReceipt dataclass."""

    def test_payment_receipt_creation(self):
        receipt = PaymentReceipt(
            receipt_id="rcpt_789",
            request_id="req_123",
            amount_paid=5.50,
            rail=PaymentRail.LIGHTNING,
            tx_hash="abc123...",
            preimage="preimage123...",
            access_token="token_abc",
            expires_at=1234567890.0
        )
        assert receipt.receipt_id == "rcpt_789"
        assert receipt.request_id == "req_123"
        assert receipt.amount_paid == 5.50
        assert receipt.rail == PaymentRail.LIGHTNING
        assert receipt.tx_hash == "abc123..."
        assert receipt.preimage == "preimage123..."
        assert receipt.access_token == "token_abc"

    def test_payment_receipt_optional_fields(self):
        receipt = PaymentReceipt(
            receipt_id="rcpt_abc",
            request_id="req_456",
            amount_paid=2.75,
            rail=PaymentRail.STABLECOIN_GENERIC,
            tx_hash=None,
            preimage=None,
            access_token="token_xyz",
            expires_at=1234567890.0
        )
        assert receipt.tx_hash is None
        assert receipt.preimage is None


class TestX402ResourceDataclass:
    """Tests for X402Resource dataclass."""

    def test_x402_resource_creation(self):
        resource = X402Resource(
            resource_id="res_123",
            url="https://api.merid.ai/premium/signals",
            description="Premium trading signals",
            price_sats=10000,
            price_usd=5.50,
            supported_rails=[PaymentRail.LIGHTNING, PaymentRail.USDC_BASE],
            ttl_seconds=3600,
            provider="merid"
        )
        assert resource.resource_id == "res_123"
        assert resource.url == "https://api.merid.ai/premium/signals"
        assert resource.description == "Premium trading signals"
        assert resource.price_sats == 10000
        assert resource.price_usd == 5.50
        assert len(resource.supported_rails) == 2
        assert resource.ttl_seconds == 3600
        assert resource.provider == "merid"

    def test_x402_resource_single_rail(self):
        resource = X402Resource(
            resource_id="res_456",
            url="https://api.merid.ai/data/market",
            description="Market data feed",
            price_sats=5000,
            price_usd=2.75,
            supported_rails=[PaymentRail.LIGHTNING],
            ttl_seconds=1800,
            provider="merid"
        )
        assert len(resource.supported_rails) == 1
        assert resource.supported_rails[0] == PaymentRail.LIGHTNING
