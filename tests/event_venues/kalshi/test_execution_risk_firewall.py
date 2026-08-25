"""Unit tests for ``merid.event_venues.kalshi.execution_risk_firewall``."""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.execution_risk_firewall import (
    ExecutionRiskFirewall,
    FirewallDecision,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent


@pytest.fixture(autouse=True)
def reset_firewall():
    ExecutionRiskFirewall.reset_for_test()
    yield
    ExecutionRiskFirewall.reset_for_test()


def _make_canonical(**overrides: Any) -> CanonicalOrderIntent:
    defaults = {
        "market_ticker": "KXBTC15M-26AUG100000-00",
        "contract": "yes",
        "action": "sell",
        "purpose": "close",
        "qty_cc": 100,
        "limit_cents": 55,
        "strategy_signal": "exit",
        "expected_position_before": 100,
        "expected_position_after": 0,
        "expected_realized_pnl_cents": 0,
        "reason": "test_exit",
        "allow_short": False,
        "intent_id": "intent_123",
        "client_order_id": "merid_test_coid_001",
        "kalshi_side": "SELL_YES",
        "fee_cents": 2,
        "reduce_only": True,
        "time_in_force": "ioc",
    }
    defaults.update(overrides)
    return CanonicalOrderIntent(**defaults)


def _mock_position_store(yes_exposure_cc: int, avg_price_cents: int = 50, side: str = "yes", parent: Optional[str] = None):
    """Patch fetch_fresh_signed_yes_exposure and the position cache."""
    cache = MagicMock()
    pos = MagicMock()
    pos.quantity_cc = abs(yes_exposure_cc)
    pos.avg_price_cents = avg_price_cents
    pos.entry_fill_id = parent
    pos.entry_signal_id = None
    pos.last_update_ts = time.time()
    pos._yes_exposure.return_value = yes_exposure_cc
    cache.get_position.return_value = pos
    cache._last_exchange_sync_time = {}

    async def _fake_fetch(ticker, timeout=None, fallback_to_cache=None):
        return (yes_exposure_cc, avg_price_cents, side)

    patcher_fetch = patch(
        "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
        _fake_fetch,
    )
    patcher_cache = patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        return_value=cache,
    )
    patcher_fetch.start()
    patcher_cache.start()

    return cache


def _mock_market_state(
    yes_bids: List[Tuple[int, int]] = None,
    no_bids: List[Tuple[int, int]] = None,
    ts: float = None,
    status: str = "open",
    seconds_to_expiry: float = 1000.0,
):
    """Patch KalshiMarketStateStore to return a state with the given ladders."""
    yes_bids = yes_bids or [(55, 1000)]
    no_bids = no_bids or [(45, 1000)]
    ts = ts or time.monotonic()

    state = MagicMock()
    state.yes_bids = yes_bids
    state.no_bids = no_bids
    state.best_bid_cents = yes_bids[0][0]
    state.best_ask_cents = 100 - no_bids[0][0]
    state.best_no_bid_cents = no_bids[0][0]
    state.best_no_ask_cents = 100 - yes_bids[-1][0]
    state.last_book_update_ts = ts
    state.book_sequence = 42
    state.book = None
    state.status = status
    state.seconds_to_expiry = seconds_to_expiry

    store = MagicMock()
    store.get.return_value = state
    store.get_unified.return_value = None

    patcher = patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    )
    patcher.start()
    return store


def _mock_fills_ledger(signed_yes_exposure: int, avg_price_cents: int = 50, side: str = "yes"):
    """Patch fills ledger to return a position computed from local fills."""
    ledger = MagicMock()
    ledger.compute_position_from_fills.return_value = {
        "market_ticker": "KXBTC15M-26AUG100000-00",
        "side": side,
        "contracts": Decimal(abs(signed_yes_exposure)) / Decimal("100"),
        "quantity_cc": abs(signed_yes_exposure),
        "avg_price_dollars": float(avg_price_cents) / 100.0,
        "avg_price_cents": avg_price_cents,
        "total_fees_usd": 0.0,
        "computed_from_fills": 1,
        "excluded_from_live_replay": 0,
        "signed_yes_exposure": signed_yes_exposure,
    }

    patcher = patch(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
        return_value=ledger,
    )
    patcher.start()
    return ledger


def _mock_stale_position_store(yes_exposure_cc: int, avg_price_cents: int = 50, side: str = "yes"):
    """Like _mock_position_store, but the cached snapshot is well beyond the 10s max age."""
    cache = MagicMock()
    pos = MagicMock()
    pos.quantity_cc = abs(yes_exposure_cc)
    pos.avg_price_cents = avg_price_cents
    pos.entry_fill_id = "fill_001"
    pos.entry_signal_id = None
    # Make the cached snapshot stale so the firewall must fall back to the ledger.
    pos.last_update_ts = time.time() - 120.0
    pos._yes_exposure.return_value = yes_exposure_cc
    cache.get_position.return_value = pos
    cache._last_exchange_sync_time = {}

    async def _fake_fetch(ticker, timeout=None, fallback_to_cache=None):
        return (yes_exposure_cc, avg_price_cents, side)

    patcher_fetch = patch(
        "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
        _fake_fetch,
    )
    patcher_cache = patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        return_value=cache,
    )
    patcher_fetch.start()
    patcher_cache.start()

    return cache


def _clear_patches():
    patch.stopall()


@pytest.fixture(autouse=True)
def clean_patches():
    yield
    _clear_patches()


@pytest.mark.asyncio
async def test_approve_exit_with_position_and_depth():
    _mock_position_store(yes_exposure_cc=100, avg_price_cents=50, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)])

    canonical = _make_canonical()
    firewall = ExecutionRiskFirewall.get_instance()
    decision = await firewall.validate_exit(canonical)

    assert isinstance(decision, FirewallDecision)
    assert decision.status == "approved"
    assert decision.qty_cc == 100
    assert decision.client_order_id == canonical.client_order_id
    assert decision.exchange_position_cc == 100
    assert decision.vwap_cents == 55
    assert decision.available_depth_cc == 100
    assert decision.approved_limit_cents == 55


@pytest.mark.asyncio
async def test_reject_over_close():
    _mock_position_store(yes_exposure_cc=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)])

    canonical = _make_canonical(qty_cc=200)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "over_close" in decision.reason


@pytest.mark.asyncio
async def test_reject_insufficient_depth():
    _mock_position_store(yes_exposure_cc=1000, side="yes")
    # Only 1 contract available at the best bid.
    _mock_market_state(yes_bids=[(55, 1)])

    canonical = _make_canonical(qty_cc=1000)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "insufficient_depth" in decision.reason


@pytest.mark.asyncio
async def test_reject_missing_parent_when_required():
    _mock_position_store(yes_exposure_cc=100, side="yes", parent=None)
    _mock_market_state(yes_bids=[(55, 1000)])

    canonical = _make_canonical(parent_entry_fill_id=None)

    with patch.dict(os.environ, {"MERID_REQUIRE_EXIT_PARENTAGE": "1"}):
        decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "parent" in decision.reason


@pytest.mark.asyncio
async def test_observe_mode_defaults_in_tests():
    _mock_position_store(yes_exposure_cc=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)])

    canonical = _make_canonical()
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    # In the test environment production is False, so observe-only does not
    # reject. It should still approve because the order passes all checks.
    assert decision.status == "approved"


@pytest.mark.asyncio
async def test_port_approves_exit_with_valid_firewall_token(monkeypatch):
    """Router-mediated exit with a valid firewall approval reaches the venue adapter."""
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    _mock_position_store(yes_exposure_cc=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)])

    canonical = _make_canonical()
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)
    assert decision.status == "approved"

    from merid.event_venues.kalshi.port import CreateOrderRequest
    from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort
    from merid.resilience import OperationResult
    from merid.event_venues.base import PlacedOrder

    placed = PlacedOrder(
        order_id="venue_oid_123",
        market_id=canonical.market_ticker,
        side="sell",
        size=Decimal("1"),
        price=Decimal("0.55"),
        filled_size=Decimal("0"),
        remaining_size=Decimal("1"),
        status="resting",
        venue="kalshi",
    )
    client = MagicMock()
    client.place_order_result = AsyncMock(return_value=OperationResult.ok(placed))
    port = KalshiVenueClientExecutionPort(client=client)

    request = CreateOrderRequest(
        ticker=canonical.market_ticker,
        side="sell",
        outcome="yes",
        size=Decimal("1"),
        price_cents=55,
        order_type="limit",
        reduce_only=True,
        client_order_id=decision.client_order_id,
        metadata={"firewall_decision_id": decision.decision_id, "entry_or_exit": "exit"},
    )

    response = await port.create_order(request)
    assert response.success
    assert client.place_order_result.called
    placed_order_arg = client.place_order_result.call_args[0][0]
    assert placed_order_arg.firewall_approval_id == decision.decision_id


@pytest.mark.asyncio
async def test_port_rejects_direct_exit_without_approval(monkeypatch):
    """Direct production exit without approval never reaches the Kalshi client."""
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    _mock_position_store(yes_exposure_cc=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)])

    from merid.event_venues.kalshi.port import CreateOrderRequest
    from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort

    client = MagicMock()
    port = KalshiVenueClientExecutionPort(client=client)

    request = CreateOrderRequest(
        ticker="KXBTC15M-26AUG100000-00",
        side="sell",
        outcome="yes",
        size=Decimal("1"),
        price_cents=55,
        order_type="limit",
        reduce_only=True,
        client_order_id="unapproved_coid_001",
        metadata={"entry_or_exit": "exit"},
    )

    response = await port.create_order(request)
    assert not response.success
    assert "firewall" in (response.error or "")
    assert not client.place_order_result.called


@pytest.mark.asyncio
async def test_enforcement_rejects_stale_book(monkeypatch):
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    _mock_position_store(yes_exposure_cc=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)], ts=1.0)

    # Make the book stale beyond the 2s default.
    with patch(
        "merid.event_venues.kalshi.execution_risk_firewall.time.monotonic",
        return_value=10_000.0,
    ):
        canonical = _make_canonical()
        decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status == "rejected"
    assert "stale_book" in decision.reason


@pytest.mark.asyncio
async def test_reduce_only_fallback_approves_stale_snapshot():
    """A stale exchange position snapshot does not block a reduce-only exit when
    the local fills ledger has a matching position and the market is active."""
    _mock_stale_position_store(yes_exposure_cc=100, side="yes")
    _mock_fills_ledger(signed_yes_exposure=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)], status="open", seconds_to_expiry=120.0)

    canonical = _make_canonical(qty_cc=100, reduce_only=True, purpose="close")
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status == "approved"
    assert decision.exchange_position_cc == 100
    assert decision.position_version.startswith("fills_ledger:")


@pytest.mark.asyncio
async def test_reduce_only_fallback_rejects_closed_market():
    """A reduce-only fallback must not proceed when the market is closed or the
    reserve-to-close window has already passed."""
    _mock_stale_position_store(yes_exposure_cc=100, side="yes")
    _mock_fills_ledger(signed_yes_exposure=100, side="yes")
    _mock_market_state(
        yes_bids=[(55, 1000)],
        ts=time.monotonic(),
        status="closed",
        seconds_to_expiry=0.0,
    )

    canonical = _make_canonical(qty_cc=100, reduce_only=True, purpose="close")
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "market_not_active" in decision.reason


@pytest.mark.asyncio
async def test_reduce_only_fallback_rejects_no_local_position():
    """If the exchange snapshot is stale and the local ledger has no position,
    the fallback must fail closed."""
    _mock_stale_position_store(yes_exposure_cc=0, side="yes")
    ledger = _mock_fills_ledger(signed_yes_exposure=0, side="yes")
    ledger.compute_position_from_fills.return_value = None
    _mock_market_state(yes_bids=[(55, 1000)], status="open", seconds_to_expiry=120.0)

    canonical = _make_canonical(qty_cc=100, reduce_only=True, purpose="close")
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "no_local_position" in decision.reason


@pytest.mark.asyncio
async def test_reduce_only_fallback_rejects_wrong_direction():
    """A fallback is only allowed when the order actually reduces the local position."""
    _mock_stale_position_store(yes_exposure_cc=100, side="yes")
    _mock_fills_ledger(signed_yes_exposure=100, side="yes")
    _mock_market_state(yes_bids=[(55, 1000)], status="open", seconds_to_expiry=120.0)

    # Asking to buy more YES would increase the position, not reduce it.
    canonical = _make_canonical(
        action="buy", contract="yes", qty_cc=100, reduce_only=True, purpose="close"
    )
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(canonical)

    assert decision.status in ("rejected", "observe_only")
    assert "no_local_position" in decision.reason
