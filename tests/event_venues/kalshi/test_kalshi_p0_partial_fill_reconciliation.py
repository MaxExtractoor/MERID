"""P0 partial-fill and exposure-reconciliation tests.

These tests drive ``_route_live`` and ``reconcile_unified_risk_with_venue``
against ``DeterministicKalshiClient`` and verify:

1. Partial IOC fills record only ``executed_count`` and release the remainder.
2. IOC zero-fills record zero filled and zero pending exposure.
3. Stale GTC orders are cancelled through the port before exposure release.
4. Cancel-after-partial-fill records the filled portion and drops the rest.
5. Restart reconciliation reconstructs open-order + position exposure.
6. Terminal orders are not reintroduced as pending by stale polls.
"""

from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    TradingMode,
    _route_live,
)
from merid.event_venues.kalshi.order_gate import (
    get_pre_trade_gate,
    reset_pre_trade_gate_for_testing,
    OrderStatus,
)
from merid.event_venues.kalshi.contract_lease import (
    reset_contract_lease_registry_for_testing,
)
from merid.event_venues.kalshi.port import (
    get_kalshi_execution_port,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from merid.risk.unified_risk_manager import (
    get_unified_risk_manager,
    UnifiedRiskManager,
)
import merid.risk.profiles.global_allocator as _global_allocator_module
from merid.event_venues.kalshi.kalshi_risk import (
    reconcile_unified_risk_with_venue,
)
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

TICKER = "KXBTC15M-TEST-50000"


# ---------------------------------------------------------------------------
# Stubs for non-port helpers
# ---------------------------------------------------------------------------

class _VenueGateStub:
    mode = TradingMode.LIVE
    live_enabled = True

    def log_order_decision(self, **kwargs) -> None:
        pass


class _RiskControllerStub:
    def can_trade(self) -> bool:
        return True

    def get_kill_reason(self) -> Optional[str]:
        return None

    def halt_strategy(self, *args, **kwargs) -> None:
        pass


class _DynamicRiskStub:
    def can_trade_now(self):
        return True, "ok"

    def update_execution_metrics(self, **kwargs) -> None:
        pass


class _GlobalAllocatorStub:
    """Record the pending/filled lifecycle so tests can inspect it."""

    def __init__(self):
        self._pending_orders: dict = {}
        self._asset_positions: dict = {}

    def record_order_submitted(self, asset: str, order_id: str, notional_usd: float) -> None:
        self._pending_orders[asset] = (order_id, notional_usd)

    def record_order_filled(self, asset: str, order_id: str, fill_notional_usd: float) -> None:
        self._pending_orders.pop(asset, None)
        self._asset_positions[asset] = (order_id, fill_notional_usd)

    def record_order_rejected(self, asset: str, order_id: str) -> None:
        self._pending_orders.pop(asset, None)


class _DedupCacheStub:
    def __init__(self, coid: str) -> None:
        self._coid = coid

    def get_or_create(self, **kwargs):
        return self._coid, False

    def mark_completed(self, *args, **kwargs) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_gate_and_lease():
    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()
    UnifiedRiskManager.reset_for_tests()
    yield
    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()
    reset_kalshi_execution_port_for_testing()


@pytest.fixture
def client(monkeypatch) -> DeterministicKalshiClient:
    """Fresh deterministic simulator with real UnifiedRiskManager and a
    stubbed GlobalAllocator so tests can inspect the lifecycle."""
    c = DeterministicKalshiClient()
    c.set_time(1_700_000_000)
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    set_kalshi_execution_port(c)

    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: c
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router.get_venue_gate",
        lambda: _VenueGateStub(),
    )
    monkeypatch.setattr(
        "merid.risk.kill_switches.risk_controller", _RiskControllerStub()
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.dynamic_risk.get_dynamic_risk_engine",
        lambda: _DynamicRiskStub(),
    )

    # Single shared allocator instance across the test.
    _ga = _GlobalAllocatorStub()
    monkeypatch.setattr(
        "merid.risk.profiles.global_allocator.get_global_allocator",
        lambda: _ga,
    )
    monkeypatch.setattr(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile",
        lambda: None,
    )
    import merid.settings as _settings
    monkeypatch.setattr(_settings.settings, "MERID_EXECUTION_MODE", "normal")

    # Real UnifiedRiskManager with a $1000 cap and 10-contract limit so
    # small test orders pass.
    risk = get_unified_risk_manager()
    risk._limits.fixed_exposure_cap_usd = 1000.0
    risk._limits.per_trade_max_contracts = 10
    risk._limits.per_asset_enabled = False
    risk.calibrate_from_balance(100_000_000)

    yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_intent(
    *,
    price_cents: int,
    count: int = 1,
    tif: str = "ioc",
    aggressiveness: float = 1.0,
    liquidity_role: str = "taker",
    post_only: bool = False,
) -> OrderIntent:
    return OrderIntent(
        ticker=TICKER,
        side="BUY_YES",
        action="buy",
        price_cents=price_cents,
        count=count,
        time_in_force=tif,
        post_only=post_only,
        aggressiveness=aggressiveness,
        liquidity_role=liquidity_role,
        order_type="limit",
        source="agent_grid",
        snapshot_ts=time.time(),
        edge_pct=5.0,
        confidence=0.7,
        exit_policy_id="test",
        window_resolution_id="test_window",
        risk_tier="A",
        max_hold_seconds=600,
    )


def _exit_intent(
    *,
    price_cents: int,
    count: int,
    tif: str = "ioc",
    pre_position: int,
) -> OrderIntent:
    return OrderIntent(
        ticker=TICKER,
        side="SELL_YES",
        action="sell",
        price_cents=price_cents,
        count=count,
        time_in_force=tif,
        post_only=False,
        aggressiveness=1.0,
        liquidity_role="taker",
        order_type="limit",
        source="position_monitor_exit",
        snapshot_ts=time.time(),
        entry_or_exit="exit",
        reduce_only=True,
        exit_policy_id="test",
        exit_reason="exit_manual",
        pre_position_size=pre_position,
        expected_post_position_size=0,
        max_hold_seconds=600,
    )


def _fresh_state() -> SimpleNamespace:
    return SimpleNamespace(
        last_book_update_ts=time.monotonic(),
        last_rest_update_ts=time.monotonic(),
        book_initialized=True,
        depth_10c=100,
        mid_cents=50,
        best_bid_cents=45,
        best_ask_cents=55,
        best_no_bid_cents=None,
        best_no_ask_cents=None,
        yes_depth=100,
        no_depth=100,
    )


def _reserve_gate(intent: OrderIntent, monkeypatch, strategy: str = "test_partial_fill") -> str:
    gate = get_pre_trade_gate()
    verdict = gate.check(
        agent_id=intent.agent_id or ("position_monitor_exit" if intent.entry_or_exit == "exit" else "agent_grid"),
        strategy_group=strategy,
        contract_id=intent.ticker,
        side=intent.side,
        action=intent.action,
        target_count=intent.count,
        price_cents=intent.price_cents,
        decision_ts=intent.snapshot_ts,
        intent_id=intent.intent_id,
        exit_policy_id=intent.exit_policy_id,
        window_resolution_id=intent.window_resolution_id,
        risk_tier=intent.risk_tier,
        max_hold_seconds=intent.max_hold_seconds,
        entry_or_exit=intent.entry_or_exit or "entry",
        reduce_only=intent.reduce_only,
    )
    assert verdict.allowed, f"gate unexpectedly blocked: {verdict.reason}"
    intent.client_tag = verdict.client_order_id
    intent.client_order_id = verdict.client_order_id
    stub = _DedupCacheStub(verdict.client_order_id)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache", lambda: stub
    )
    return verdict.client_order_id


async def _route_entry(intent: OrderIntent):
    return await _route_live(
        intent, TradingMode.LIVE, time.monotonic(),
        prepared_state=_fresh_state(), plan_done=True,
    )


async def _route_exit(intent: OrderIntent):
    return await _route_live(
        intent, TradingMode.LIVE, time.monotonic()
    )


def _unified_exposure() -> float:
    return get_unified_risk_manager()._category_exposure.get("crypto", 0.0)


def _global_allocator() -> _GlobalAllocatorStub:
    return _global_allocator_module.get_global_allocator()


def _build_open_gtc_order(*, client_order_id: str, size: int, price: Decimal) -> None:
    """Helper to build a GTC order directly through the simulator for
    reconciliation tests."""
    from merid.event_venues.base import VenueOrder
    return VenueOrder(
        market_id=TICKER,
        side="buy",
        size=Decimal(str(size)),
        price=price,
        order_type="limit",
        outcome_id="yes",
        client_order_id=client_order_id,
        time_in_force="gtc",
    )


# ---------------------------------------------------------------------------
# Partial / zero-fill scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_ioc_exit_fill_records_executed_count(
    client: DeterministicKalshiClient, monkeypatch
) -> None:
    """A 2-contract exit IOC with only 1 contract on the bid fills 1,
    records a release for 1, and does not rest the remainder."""
    client.set_initial_position(TICKER, "yes", 2, avg_price_cents=50)
    client.set_orderbook(
        TICKER, best_bid_cents=50, best_ask_cents=60,
        bid_size=Decimal("1"), ask_size=Decimal("10"),
    )

    # Seed local exposure from the venue-side position.
    await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)
    assert _unified_exposure() == pytest.approx(1.0)

    intent = _exit_intent(price_cents=50, count=2, pre_position=2)
    _reserve_gate(intent, monkeypatch, "test_exit")

    result = await _route_exit(intent)

    assert result.status == "filled_live", (result.status, result.reason)
    assert result.executed_count == 1
    assert result.remaining_count == 0
    assert result.has_execution

    # Only the filled notional is released from UnifiedRiskManager.
    assert _unified_exposure() == pytest.approx(0.5)

    # No resting monitor registration for IOC.
    assert (await client.get_open_orders_result()).data == []
    assert client._position_yes[TICKER] == Decimal("1")

    # GlobalAllocator should see the fill, not the requested count.
    allocator = _global_allocator()
    assert allocator._asset_positions.get("BTC")[1] == pytest.approx(0.5)
    assert "BTC" not in allocator._pending_orders


@pytest.mark.asyncio
async def test_ioc_zero_fill_records_zero_exposure(
    client: DeterministicKalshiClient, monkeypatch
) -> None:
    """An IOC far from the market should return ``unfilled_ioc`` with zero
    filled notional and zero pending exposure."""
    client.set_market(
        TICKER,
        SimpleNamespace(best_bid=45, best_ask=55, volume=1000, open_interest=1000,
                        active=True, resolved=False),
    )
    client.set_orderbook(
        TICKER, best_bid_cents=45, best_ask_cents=55,
        bid_size=Decimal("10"), ask_size=Decimal("0"),
    )

    # Use a taker IOC priced at the displayed ask.  The displayed ask has zero
    # size, so the order does not fill and is cancelled by the venue, exercising
    # the zero-fill path.  post_only=True combined with an IOC is invalid and is
    # coerced to GTC by the execution-mode resolver, so we keep post_only=False.
    intent = _entry_intent(
        price_cents=55,
        count=1,
        tif="ioc",
        aggressiveness=1.0,
        liquidity_role="taker",
        post_only=False,
    )
    _reserve_gate(intent, monkeypatch)

    result = await _route_entry(intent)

    assert result.status == "unfilled_ioc", (result.status, result.reason)
    assert result.executed_count == 0
    assert result.remaining_count == 0
    assert not result.has_execution

    assert _unified_exposure() == 0.0

    allocator = _global_allocator()
    assert "BTC" not in allocator._pending_orders
    assert "BTC" not in allocator._asset_positions


# ---------------------------------------------------------------------------
# Stale / cancel / restart reconciliation scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_gtc_cancel_confirms_before_exposure_release(client) -> None:
    """A GTC order older than the threshold is cancelled and the re-fetch
    must not reintroduce its notional into UnifiedRiskManager."""
    t0 = 1_700_000_000
    client.set_time(t0)

    order = _build_open_gtc_order(client_order_id="stale-gtc-1", size=1, price=Decimal("0.50"))
    res = await client.place_order_result(order)
    assert res.success and res.data
    placed = res.data

    # Move time forward so the order is stale.
    client.set_time(t0 + 500)

    result = await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)

    assert placed.order_id in result["canceled_order_ids"]
    assert result["confirmed_open_notional_usd"] == 0.0
    assert _unified_exposure() == 0.0


@pytest.mark.asyncio
async def test_cancel_after_partial_fill_records_filled_only(client) -> None:
    """A GTC order partially fills (1 of 2), then the remainder is cancelled.
    Reconciliation must keep the filled position and drop the unfilled rest."""
    client.set_orderbook(
        TICKER, best_bid_cents=45, best_ask_cents=55,
        bid_size=Decimal("10"), ask_size=Decimal("1"),
    )

    order = _build_open_gtc_order(client_order_id="partial-then-cancel-1", size=2, price=Decimal("0.55"))
    res = await client.place_order_result(order)
    assert res.success and res.data
    placed = res.data
    assert placed.status == "partially_filled"
    assert placed.filled_size == Decimal("1")

    # Cancel the remaining 1 contract.
    cancel = await client.cancel_order(placed.order_id)
    assert cancel.success

    result = await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)

    # Only the filled position remains (1 contract @ 55c).
    assert result["confirmed_open_notional_usd"] == pytest.approx(0.55)
    assert _unified_exposure() == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_restart_reconstructs_exposure_from_port_state(client) -> None:
    """After a restart, reconcile_unified_risk_with_venue rebuilds local
    exposure from the port's open orders and positions."""
    client.set_time(time.time())
    client.set_orderbook(
        TICKER, best_bid_cents=45, best_ask_cents=55,
        bid_size=Decimal("10"), ask_size=Decimal("1"),
    )

    # Place a 2-contract GTC order that fills 1 and rests 1.
    order = _build_open_gtc_order(client_order_id="restart-1", size=2, price=Decimal("0.55"))
    res = await client.place_order_result(order)
    assert res.success and res.data

    # Simulate a clean restart: zero local exposure.
    UnifiedRiskManager.reset_for_tests()
    get_unified_risk_manager()._limits.fixed_exposure_cap_usd = 1000.0
    get_unified_risk_manager()._limits.per_trade_max_contracts = 10
    get_unified_risk_manager()._limits.per_asset_enabled = False

    result = await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)

    # Open order (1 remaining @ 55c) + position (1 filled @ 55c) = 2 * 0.55
    assert result["confirmed_open_notional_usd"] == pytest.approx(1.10)
    assert _unified_exposure() == pytest.approx(1.10)


@pytest.mark.asyncio
async def test_terminal_order_not_reintroduced_by_stale_poll(client) -> None:
    """A terminal (canceled) order with a stale timestamp must not be counted
    as open exposure even if a later poll returns it."""
    t0 = 1_700_000_000
    client.set_time(t0)

    order = _build_open_gtc_order(client_order_id="terminal-1", size=1, price=Decimal("0.50"))
    res = await client.place_order_result(order)
    placed = res.data

    # Cancel it before the poll.
    cancel = await client.cancel_order(placed.order_id)
    assert cancel.success

    # Simulate a stale poll that still returns a terminal record.
    client.set_time(t0 + 500)

    result = await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)

    assert result["confirmed_open_notional_usd"] == 0.0
    assert _unified_exposure() == 0.0
