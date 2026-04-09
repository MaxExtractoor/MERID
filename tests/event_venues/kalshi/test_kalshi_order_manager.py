"""Tests for Kalshi Order Manager — Partial fills and order lifecycle."""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.order_manager import (
    TERMINAL_STATUSES,
    FillCallback,
    FillEvent,
    FlattenResult,
    OrderManager,
    TrackedOrder,
    WaitResult,
)


# ── Module-level fixtures — bypass safety gates in unit tests ───────────────

@pytest.fixture(autouse=True)
def _bypass_safety_gates():
    """Ensure kill switch and VenueGate do not block orders in unit tests.

    Unit tests here exercise order-manager logic in isolation; integration
    tests must cover the real gate behavior separately.
    """
    mock_gate = MagicMock()
    mock_gate.should_simulate_fill.return_value = False
    mock_gate.mode.value = "live"

    mock_rc = MagicMock()
    mock_rc.can_trade.return_value = True
    mock_rc.get_kill_reason.return_value = None

    with patch("merid.risk.kill_switches.risk_controller", mock_rc), \
         patch("merid.prediction.venue_gate.get_venue_gate", return_value=mock_gate):
        yield


# ── Helpers ────────────────────────────────────────────────────────────

def _mock_placed(
    order_id="ord-1",
    market_id="KXBTC-H1",
    side="buy",
    size=10,
    price=Decimal("0.55"),
    filled=0,
    remaining=None,
    status="open",
):
    m = MagicMock()
    m.order_id = order_id
    m.market_id = market_id
    m.side = side
    m.size = Decimal(str(size))
    m.price = price
    m.filled_size = Decimal(str(filled))
    m.remaining_size = Decimal(str(remaining)) if remaining is not None else Decimal(str(size - filled))
    m.status = status
    return m


def _mock_client(placed=None, get_order_returns=None, cancel_returns=True):
    client = AsyncMock()
    client.place_order = AsyncMock(return_value=placed)
    if get_order_returns is not None:
        client.get_order = AsyncMock(side_effect=get_order_returns if isinstance(get_order_returns, list) else [get_order_returns])
    else:
        client.get_order = AsyncMock(return_value=None)
    client.cancel_order = AsyncMock(return_value=cancel_returns)
    return client


def _mock_order():
    m = MagicMock()
    m.market_id = "KXBTC-H1"
    m.side = "buy"
    m.outcome_id = "yes"
    m.client_order_id = "test-123"
    m.size = 10
    m.price = Decimal("0.55")
    m.order_type = "limit"
    return m


# ── TrackedOrder ─────────────────────────────────────────────────────

class TestTrackedOrder:
    def test_defaults(self):
        t = TrackedOrder(
            order_id="o1", client_order_id="c1", ticker="T",
            side="buy", outcome="yes", requested_size=10, price_cents=55,
        )
        assert t.remaining_size == 10
        assert t.filled_size == 0
        assert t.fill_pct == 0.0
        assert t.is_partial is False
        assert t.terminal is False

    def test_fill_pct(self):
        t = TrackedOrder(
            order_id="o1", client_order_id="c1", ticker="T",
            side="buy", outcome="yes", requested_size=10, price_cents=55,
            filled_size=5, remaining_size=5,
        )
        assert t.fill_pct == 50.0
        assert t.is_partial is True

    def test_to_dict(self):
        t = TrackedOrder(
            order_id="o1", client_order_id="c1", ticker="T",
            side="buy", outcome="yes", requested_size=10, price_cents=55,
        )
        d = t.to_dict()
        assert d["order_id"] == "o1"
        assert "fill_events" in d
        assert "fill_pct" in d


# ── FillEvent ────────────────────────────────────────────────────────

class TestFillEvent:
    def test_to_dict(self):
        e = FillEvent(
            order_id="o1", ts=1000.0, fill_size=5,
            cumulative_filled=5, remaining=5,
        )
        d = e.to_dict()
        assert d["fill_size"] == 5
        assert d["cumulative_filled"] == 5


# ── WaitResult ───────────────────────────────────────────────────────

class TestWaitResult:
    def test_to_dict(self):
        r = WaitResult(
            order_id="o1", final_status="filled",
            filled_size=10, remaining_size=0,
        )
        d = r.to_dict()
        assert d["final_status"] == "filled"
        assert d["timed_out"] is False


# ── Submit order ─────────────────────────────────────────────────────

class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_submit_success(self):
        placed = _mock_placed()
        client = _mock_client(placed=placed)
        mgr = OrderManager(client=client)
        order = _mock_order()
        tracked = await mgr.submit_order(order)
        assert tracked is not None
        assert tracked.order_id == "ord-1"
        assert tracked.requested_size == 10

    @pytest.mark.asyncio
    async def test_submit_failure(self):
        client = _mock_client(placed=None)
        mgr = OrderManager(client=client)
        tracked = await mgr.submit_order(_mock_order())
        assert tracked is None

    @pytest.mark.asyncio
    async def test_submit_no_client(self):
        mgr = OrderManager(client=None)
        tracked = await mgr.submit_order(_mock_order())
        assert tracked is None


# ── Manual tracking ──────────────────────────────────────────────────

class TestManualTracking:
    def test_track_order(self):
        mgr = OrderManager()
        tracked = mgr.track_order("o1", ticker="T", side="buy", requested_size=10, price_cents=55)
        assert mgr.get_tracked("o1") is tracked
        assert len(mgr.all_orders) == 1
        assert len(mgr.open_orders) == 1

    def test_get_tracked_missing(self):
        mgr = OrderManager()
        assert mgr.get_tracked("missing") is None


# ── Update from status (manual / WS) ────────────────────────────────

class TestUpdateFromStatus:
    def test_incremental_fill_detected(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        tracked = mgr.update_from_status("o1", "partially_filled", filled_size=5, remaining_size=5)
        assert tracked.filled_size == 5
        assert len(tracked.fill_events) == 1
        assert tracked.fill_events[0].fill_size == 5

    def test_multiple_incremental_fills(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "partially_filled", filled_size=3, remaining_size=7)
        mgr.update_from_status("o1", "partially_filled", filled_size=7, remaining_size=3)
        mgr.update_from_status("o1", "filled", filled_size=10, remaining_size=0)
        tracked = mgr.get_tracked("o1")
        assert len(tracked.fill_events) == 3
        assert tracked.fill_events[0].fill_size == 3
        assert tracked.fill_events[1].fill_size == 4
        assert tracked.fill_events[2].fill_size == 3

    def test_no_fill_on_same_count(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "partially_filled", filled_size=5, remaining_size=5)
        mgr.update_from_status("o1", "partially_filled", filled_size=5, remaining_size=5)
        tracked = mgr.get_tracked("o1")
        assert len(tracked.fill_events) == 1  # No duplicate

    def test_terminal_status(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "filled", filled_size=10, remaining_size=0)
        tracked = mgr.get_tracked("o1")
        assert tracked.terminal is True
        assert len(mgr.open_orders) == 0

    def test_update_missing_order(self):
        mgr = OrderManager()
        result = mgr.update_from_status("missing", "filled", 10, 0)
        assert result is None


# ── Fill callback ────────────────────────────────────────────────────

class TestFillCallback:
    def test_callback_invoked(self):
        events = []
        def on_fill(order_id, event):
            events.append((order_id, event))

        mgr = OrderManager(on_fill=on_fill)
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "partially_filled", filled_size=5, remaining_size=5)
        assert len(events) == 1
        assert events[0][0] == "o1"
        assert events[0][1].fill_size == 5

    def test_callback_error_handled(self):
        def bad_callback(order_id, event):
            raise ValueError("boom")

        mgr = OrderManager(on_fill=bad_callback)
        mgr.track_order("o1", requested_size=10)
        # Should not raise
        mgr.update_from_status("o1", "filled", filled_size=10, remaining_size=0)
        assert mgr.get_tracked("o1").terminal is True


# ── Poll order ───────────────────────────────────────────────────────

class TestPollOrder:
    @pytest.mark.asyncio
    async def test_poll_detects_fill(self):
        placed_partial = _mock_placed(filled=5, remaining=5, status="partially_filled")
        client = _mock_client(get_order_returns=placed_partial)
        mgr = OrderManager(client=client)
        mgr.track_order("ord-1", requested_size=10)
        tracked = await mgr.poll_order("ord-1")
        assert tracked.filled_size == 5
        assert len(tracked.fill_events) == 1

    @pytest.mark.asyncio
    async def test_poll_terminal_skipped(self):
        mgr = OrderManager(client=AsyncMock())
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "filled", 10, 0)
        tracked = await mgr.poll_order("o1")
        assert tracked.terminal is True
        # get_order should not have been called
        mgr._client.get_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_missing_order(self):
        mgr = OrderManager(client=AsyncMock())
        result = await mgr.poll_order("missing")
        assert result is None


# ── Wait for fill ────────────────────────────────────────────────────

class TestWaitForFill:
    @pytest.mark.asyncio
    async def test_immediate_fill(self):
        filled = _mock_placed(filled=10, remaining=0, status="filled")
        client = _mock_client(get_order_returns=filled)
        mgr = OrderManager(client=client, poll_interval=0.01)
        mgr.track_order("ord-1", requested_size=10)
        # Pre-set to terminal so wait exits immediately
        mgr.update_from_status("ord-1", "filled", 10, 0)
        result = await mgr.wait_for_fill("ord-1", timeout_s=1.0)
        assert result.final_status == "filled"
        assert result.timed_out is False
        assert result.filled_size == 10

    @pytest.mark.asyncio
    async def test_timeout_and_cancel(self):
        # get_order always returns open
        open_order = _mock_placed(filled=0, remaining=10, status="open")
        client = _mock_client(get_order_returns=[open_order] * 20, cancel_returns=True)
        mgr = OrderManager(client=client, poll_interval=0.02)
        mgr.track_order("ord-1", requested_size=10)
        result = await mgr.wait_for_fill("ord-1", timeout_s=0.1, cancel_on_timeout=True)
        assert result.timed_out is True
        assert result.canceled_on_timeout is True

    @pytest.mark.asyncio
    async def test_timeout_no_cancel(self):
        open_order = _mock_placed(filled=0, remaining=10, status="open")
        client = _mock_client(get_order_returns=[open_order] * 20)
        mgr = OrderManager(client=client, poll_interval=0.02)
        mgr.track_order("ord-1", requested_size=10)
        result = await mgr.wait_for_fill("ord-1", timeout_s=0.1, cancel_on_timeout=False)
        assert result.timed_out is True
        assert result.canceled_on_timeout is False

    @pytest.mark.asyncio
    async def test_wait_missing_order(self):
        mgr = OrderManager()
        result = await mgr.wait_for_fill("missing", timeout_s=0.1)
        assert result.timed_out is True
        assert result.final_status == "unknown"


# ── Cancel order ─────────────────────────────────────────────────────

class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_open_order(self):
        client = _mock_client(cancel_returns=True)
        mgr = OrderManager(client=client)
        mgr.track_order("o1", requested_size=10)
        success = await mgr.cancel_order("o1")
        assert success is True
        assert mgr.get_tracked("o1").terminal is True

    @pytest.mark.asyncio
    async def test_cancel_terminal_order(self):
        mgr = OrderManager(client=AsyncMock())
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "filled", 10, 0)
        success = await mgr.cancel_order("o1")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_missing_order(self):
        mgr = OrderManager(client=AsyncMock())
        success = await mgr.cancel_order("missing")
        assert success is False


# ── Summary ──────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        mgr.track_order("o2", requested_size=5)
        mgr.update_from_status("o1", "filled", 10, 0)
        s = mgr.summary()
        assert s["total_orders"] == 2
        assert s["open_orders"] == 1
        assert s["filled_orders"] == 1
        assert "orders" in s

    def test_partial_fill_count(self):
        mgr = OrderManager()
        mgr.track_order("o1", requested_size=10)
        mgr.update_from_status("o1", "partially_filled", 5, 5)
        s = mgr.summary()
        assert s["partial_fills"] == 1
        assert s["total_fill_events"] == 1


# ── FlattenResult ─────────────────────────────────────────────────────

class TestFlattenResult:
    def test_to_dict(self):
        r = FlattenResult(order_id="o1", success=True, cancel_success=True, filled_size=5)
        d = r.to_dict()
        assert d["order_id"] == "o1"
        assert d["success"] is True
        assert d["filled_size"] == 5


# ── Cancel and flatten ─────────────────────────────────────────────

class TestCancelAndFlatten:
    @pytest.mark.asyncio
    async def test_cancel_and_flatten_no_fills(self):
        """Cancel order with no fills → no flatten order needed."""
        client = _mock_client(cancel_returns=True)
        # get_order returns canceled with 0 fills
        canceled = _mock_placed(filled=0, remaining=10, status="canceled")
        client.get_order = AsyncMock(return_value=canceled)
        mgr = OrderManager(client=client)
        mgr.track_order("ord-1", ticker="KXBTC-H1", side="buy", requested_size=10)
        result = await mgr.cancel_and_flatten("ord-1")
        assert result.success
        assert result.cancel_success
        assert result.filled_size == 0
        assert result.flatten_placed is False

    @pytest.mark.asyncio
    async def test_cancel_and_flatten_with_partial(self):
        """Cancel partially filled order → flatten opposite side for filled qty."""
        client = _mock_client(cancel_returns=True)
        # After cancel, get_order shows 5 filled
        partial = _mock_placed(filled=5, remaining=5, status="canceled")
        client.get_order = AsyncMock(return_value=partial)
        # Flatten order placement succeeds
        flatten_placed = _mock_placed(order_id="flatten-1", filled=5, remaining=0, status="filled", side="sell")
        client.place_order = AsyncMock(return_value=flatten_placed)
        mgr = OrderManager(client=client)
        mgr.track_order("ord-1", ticker="KXBTC-H1", side="buy", outcome="yes", requested_size=10)
        result = await mgr.cancel_and_flatten("ord-1")
        assert result.success
        assert result.filled_size == 5
        assert result.flatten_placed
        assert result.flatten_order_id == "flatten-1"
        # Flatten order should be tracked
        assert mgr.get_tracked("flatten-1") is not None

    @pytest.mark.asyncio
    async def test_cancel_and_flatten_no_flatten_requested(self):
        """Cancel with fills but place_flatten_order=False."""
        client = _mock_client(cancel_returns=True)
        partial = _mock_placed(filled=5, remaining=5, status="canceled")
        client.get_order = AsyncMock(return_value=partial)
        mgr = OrderManager(client=client)
        mgr.track_order("ord-1", ticker="KXBTC-H1", side="buy", requested_size=10)
        result = await mgr.cancel_and_flatten("ord-1", place_flatten_order=False)
        assert result.success
        assert result.filled_size == 5
        assert result.flatten_placed is False

    @pytest.mark.asyncio
    async def test_cancel_and_flatten_missing_order(self):
        mgr = OrderManager()
        result = await mgr.cancel_and_flatten("missing")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_cancel_and_flatten_no_client(self):
        """With no client, cancel succeeds locally but no flatten order."""
        mgr = OrderManager(client=None)
        mgr.track_order("ord-1", ticker="KXBTC-H1", side="buy", requested_size=10)
        result = await mgr.cancel_and_flatten("ord-1")
        assert result.success
        assert result.flatten_placed is False
