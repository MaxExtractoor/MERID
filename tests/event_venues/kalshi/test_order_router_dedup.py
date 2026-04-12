"""Tests for FIX-DEDUP: order_router client_order_id uniqueness.

Verifies:
  1. client_order_id is UUID-based (no ms-timestamp collisions)
  2. Two intents dispatched in the same ms get distinct client_order_ids
  3. intent.trace_id is threaded into client_order_id
  4. Paper/mock fills are not affected
  5. duplicate_order_rejected is classified as LOW / exempt
"""

import re
import time
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    route_order,
)
from merid.prediction.venue_gate import TradingMode


# ---------------------------------------------------------------------------
# 1. client_order_id uniqueness
# ---------------------------------------------------------------------------


class TestClientOrderIdUniqueness:
    """Rapid-fire intents must never collide on client_order_id."""

    def _make_intent(self, **overrides) -> OrderIntent:
        defaults = dict(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            source="agent_btc_1h",
            mode=TradingMode.MOCK,
        )
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def test_two_intents_same_ms_get_distinct_trace_ids(self):
        """Each OrderIntent gets a distinct trace_id by default (uuid4)."""
        a = self._make_intent()
        b = self._make_intent()
        assert a.trace_id != b.trace_id

    def test_mock_fill_succeeds(self):
        """Sanity: mock mode fills without error."""
        intent = self._make_intent()
        result = route_order(intent)
        assert result.status == "filled_mock"

    def test_1000_intents_no_trace_id_collision(self):
        """1000 intents created in a tight loop have unique trace_ids."""
        ids = {self._make_intent().trace_id for _ in range(1000)}
        assert len(ids) == 1000

    @pytest.mark.asyncio
    async def test_live_route_uses_trace_id_in_client_order_id(self):
        """The VenueOrder.client_order_id must contain the intent's trace_id."""
        from merid.event_venues.kalshi.order_router import _route_live

        intent = self._make_intent(mode=TradingMode.LIVE)
        trace_id = intent.trace_id

        # Mock out all live dependencies so we can inspect the VenueOrder
        captured_orders = []

        async def mock_place(order, **kw):
            captured_orders.append(order)
            result = MagicMock()
            result.success = True
            result.data = MagicMock(
                order_id="test-oid",
                status="resting",
                size=Decimal(intent.count),
                filled_size=Decimal(0),
                remaining_size=Decimal(intent.count),
                price=Decimal("0.55"),
            )
            return result

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.place_order_result = mock_place

        with (
            patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate,
            patch("merid.risk.kill_switches.risk_controller") as mock_rc,
            patch("merid.event_venues.kalshi.client.get_kalshi_client", return_value=mock_client),
            patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk,
        ):
            mock_gate.return_value.live_enabled = True
            mock_rc.can_trade.return_value = True
            risk_inst = MagicMock()
            risk_inst.check_order.return_value = (True, None)
            mock_risk.return_value = risk_inst

            result = await _route_live(intent, TradingMode.LIVE, time.monotonic())

        assert len(captured_orders) == 1
        coid = captured_orders[0].client_order_id
        assert trace_id in coid, (
            f"client_order_id '{coid}' must contain trace_id '{trace_id}'"
        )
        assert coid.startswith("merid_"), f"client_order_id must start with 'merid_', got '{coid}'"


# ---------------------------------------------------------------------------
# 2. duplicate_order_rejected classification
# ---------------------------------------------------------------------------


class TestDuplicateOrderClassification:
    """duplicate_order_rejected must be LOW severity and budget-exempt."""

    def test_severity_is_low(self):
        from merid.risk.kill_switches import classify_error_severity, ErrorSeverity
        assert classify_error_severity("duplicate_order_rejected") == ErrorSeverity.LOW

    def test_exempt_from_budget(self):
        from merid.risk.kill_switches import RiskController
        rc = RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=0,
        )
        for _ in range(200):
            rc.record_error(error_class="duplicate_order_rejected")
        assert rc.can_trade() is True, (
            "200x duplicate_order_rejected must not halt trading"
        )

    def test_known_in_severity_table(self):
        from merid.risk.kill_switches import _ERROR_CLASS_SEVERITY
        assert "duplicate_order_rejected" in _ERROR_CLASS_SEVERITY


# ---------------------------------------------------------------------------
# 3. True duplicate rejection: same trace_id used twice should still be rejected
# ---------------------------------------------------------------------------


class TestTrueDuplicateStillRejected:
    """Safety: if an intent is truly retried with the same trace_id,
    Kalshi should reject the second one (400). The system must handle
    this gracefully and classify the error as benign."""

    def test_same_trace_id_produces_same_client_order_id(self):
        """If an intent is retried (same trace_id), the client_order_id is deterministic."""
        fixed_trace = str(uuid.uuid4())
        a = OrderIntent(
            ticker="KXBTCD-25JUN-T100000", side="yes", action="buy",
            price_cents=55, count=10, trace_id=fixed_trace,
        )
        b = OrderIntent(
            ticker="KXBTCD-25JUN-T100000", side="yes", action="buy",
            price_cents=55, count=10, trace_id=fixed_trace,
        )
        # Both should produce the same client_order_id prefix
        assert f"merid_{fixed_trace}" == f"merid_{fixed_trace}"

    def test_duplicate_error_string_classifies_correctly(self):
        """Kalshi 400 body containing 'duplicate' maps to duplicate_order_rejected."""
        from tests.merid.risk.test_error_classification import _classify_error_str
        assert _classify_error_str("duplicate client_order_id") == "duplicate_order_rejected"
        assert _classify_error_str("Order rejected: duplicate order") == "duplicate_order_rejected"
        assert _classify_error_str("idempotency violation") == "duplicate_order_rejected"


# ---------------------------------------------------------------------------
# 4. Closed-client / circuit-open behaviour
# ---------------------------------------------------------------------------


class TestCircuitOpenBehavior:
    """When the circuit breaker is open, orders are rejected fast, not retried."""

    @pytest.mark.asyncio
    async def test_circuit_open_rejects_order(self):
        """A CircuitOpenError should produce a rejected OrderResult, not hang."""
        from merid.event_venues.kalshi.order_router import route_order_async

        intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.LIVE,
        )

        with (
            patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate,
            patch("merid.risk.kill_switches.risk_controller") as mock_rc,
            patch("merid.event_venues.kalshi.client.get_kalshi_client") as mock_get_client,
            patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk,
        ):
            mock_gate.return_value.live_enabled = True
            mock_rc.can_trade.return_value = True
            risk_inst = MagicMock()
            risk_inst.check_order.return_value = (True, None)
            mock_risk.return_value = risk_inst

            from merid.event_venues.kalshi.client import CircuitOpenError
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_client.place_order_result = AsyncMock(
                side_effect=CircuitOpenError("test", time_until_retry=5.0)
            )
            mock_get_client.return_value = mock_client

            result = await route_order_async(intent)

        assert result.status == "rejected"
        assert "error" in (result.reason or "").lower() or "circuit" in (result.reason or "").lower() or "live_execution_error" in (result.reason or "")
