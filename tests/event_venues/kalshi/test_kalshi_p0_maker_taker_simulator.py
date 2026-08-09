"""P0 maker/taker tests: ``_route_live`` through the ``KalshiExecutionPort``.

Covers the maker/taker contract at the port boundary:

- maker (post_only) orders create expiring GTC/GTT resting orders
- taker IOC zero-fill leaves no resting reservation
- taker IOC full-fill executes immediately

The exchange side is the real ``DeterministicKalshiClient`` injected via
``set_kalshi_execution_port``; risk/gate helpers unrelated to the port are
stubbed (kill switches, venue gate, unified risk, slot allocator, profile).

NOTE: intents reaching ``_route_live`` carry Kalshi-formatted sides
(BUY_YES/SELL_YES/BUY_NO/SELL_NO) â€” the [SEV-0-SIDE-INVARIANT] check rejects
bare "yes"/"no".  "BUY_YES" here is the semantic "side=yes, action=buy".
"""

from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace
from typing import List, Optional

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    TradingMode,
    _route_live,
)
from merid.event_venues.kalshi.order_gate import (
    OrderStatus,
    get_pre_trade_gate,
    reset_pre_trade_gate_for_testing,
)
from merid.event_venues.kalshi.contract_lease import (
    reset_contract_lease_registry_for_testing,
)
from merid.event_venues.kalshi.port import (
    CreateOrderRequest,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

# Distinct assets per test to avoid cross-test interference from the router's
# per-asset 15-minute entry-window tracking.
TICKER_MAKER = "KXBTC15M-TEST-50000"
TICKER_TAKER_ZERO = "KXETH15M-TEST-2000"
TICKER_TAKER_FULL = "KXSOL15M-TEST-100"


# ---------------------------------------------------------------------------
# Stubs for non-port risk/gate helpers
# ---------------------------------------------------------------------------

class _VenueGateStub:
    mode = TradingMode.LIVE
    live_enabled = True

    def log_order_decision(self, **kwargs) -> None:
        pass


class _UnifiedRiskStub:
    def calibrate_from_balance(self, *args, **kwargs) -> None:
        pass

    def check_order(self, **kwargs):
        return True, "ok"

    def record_fill(self, **kwargs) -> None:
        pass

    def release(self, **kwargs) -> None:
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


class _SlotAllocatorStub:
    def request_allocation(self, request):
        return True, "ok", "slot-test"

    def release_slot(self, *args, **kwargs) -> None:
        pass


class _DedupCacheStub:
    """Hand back the gate-reserved coid; see exit-order suite for rationale."""

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
    yield
    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()


@pytest.fixture
def client(monkeypatch) -> DeterministicKalshiClient:
    """Fresh deterministic simulator injected as the global execution port."""
    c = DeterministicKalshiClient()
    c.set_time(1_700_000_000)
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    set_kalshi_execution_port(c)
    # Raw client is retained only for the public orderbook divergence check
    # and the post-fill balance probe.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: c
    )
    # Stub risk/gate helpers unrelated to the port boundary.
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
    monkeypatch.setattr(
        "merid.risk.unified_risk_manager.get_unified_risk_manager",
        lambda: _UnifiedRiskStub(),
    )
    monkeypatch.setattr(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile",
        lambda: None,
    )
    monkeypatch.setattr(
        "merid.risk.global_slot_allocator.get_global_slot_allocator",
        lambda: _SlotAllocatorStub(),
    )
    monkeypatch.setattr(
        "merid.risk.profiles.global_allocator.get_global_allocator",
        lambda: None,
    )
    import merid.settings as _settings

    monkeypatch.setattr(_settings.settings, "MERID_EXECUTION_MODE", "normal")
    yield c
    reset_kalshi_execution_port_for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_intent(
    *,
    ticker: str,
    price_cents: int,
    count: int = 2,
    tif: str = "gtc",
    post_only: bool = False,
    aggressiveness: float = 0.0,
) -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side="BUY_YES",
        action="buy",
        price_cents=price_cents,
        count=count,
        time_in_force=tif,
        post_only=post_only,
        aggressiveness=aggressiveness,
        source="agent_grid",
        snapshot_ts=time.time(),
        edge_pct=5.0,
        confidence=0.7,
        # "No trade without exit" invariant: 15m entries must carry an exit
        # policy linkage for the pre-trade gate.
        exit_policy_id="test",
        window_resolution_id="test_window",
        risk_tier="A",
        max_hold_seconds=600,
    )


def _reserve_gate(intent: OrderIntent, monkeypatch) -> str:
    gate = get_pre_trade_gate()
    verdict = gate.check(
        agent_id=intent.agent_id or "agent_grid",
        strategy_group="test_maker_taker",
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
        entry_or_exit="entry",
    )
    assert verdict.allowed, f"gate unexpectedly blocked: {verdict.reason}"
    intent.client_tag = verdict.client_order_id
    intent.client_order_id = verdict.client_order_id
    stub = _DedupCacheStub(verdict.client_order_id)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache", lambda: stub
    )
    return verdict.client_order_id


def _fresh_state() -> SimpleNamespace:
    """Minimal market state for the router's non-port freshness gates."""
    return SimpleNamespace(
        last_book_update_ts=time.monotonic(),
        last_rest_update_ts=time.monotonic(),
        depth_10c=100,
        mid_cents=None,
        best_bid_cents=None,
        best_ask_cents=None,
        best_no_bid_cents=None,
        best_no_ask_cents=None,
        yes_depth=100,
        no_depth=100,
    )


def _set_market(client: DeterministicKalshiClient, ticker: str) -> None:
    """A5 market-condition check reads best_bid/best_ask/volume/OI (cents)."""
    client.set_market(
        ticker,
        SimpleNamespace(
            best_bid=45, best_ask=55, volume=1000, open_interest=1000,
            active=True, resolved=False,
        ),
    )


def _gate_record(client_order_id: str):
    for rec in get_pre_trade_gate().store.snapshot():
        if rec.client_order_id == client_order_id:
            return rec
    return None


async def _route(intent: OrderIntent):
    return await _route_live(
        intent, TradingMode.LIVE, time.monotonic(),
        prepared_state=_fresh_state(), plan_done=True,
    )


# ---------------------------------------------------------------------------
# Maker / taker scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maker_post_only_creates_expiring_gtc_order(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    """A passive (post_only) order must rest as GTC/GTT with an explicit
    expiration timestamp â€” never IOC and never without an expiry."""
    client.set_orderbook(TICKER_MAKER, best_bid_cents=45, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    _set_market(client, TICKER_MAKER)

    # Spy on the port boundary to capture the exact CreateOrderRequest.
    sent: List[CreateOrderRequest] = []
    orig_create = client.create_order

    async def _spy_create(request: CreateOrderRequest):
        sent.append(request)
        return await orig_create(request)

    client.create_order = _spy_create  # type: ignore[method-assign]

    intent = _entry_intent(
        ticker=TICKER_MAKER, price_cents=50, count=1,
        tif="gtc", post_only=True, aggressiveness=0.0,
    )
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "resting", (result.status, result.reason)
    assert result.order_id

    # Wire-level invariants at the port boundary.
    assert len(sent) == 1
    request = sent[0]
    assert request.post_only is True
    assert request.side == "buy"
    assert request.outcome == "yes"
    assert request.price_cents == 50
    assert request.time_in_force == "GTC"
    assert request.expiration_ts is not None
    assert request.expiration_ts > int(time.time())
    assert request.client_order_id == coid
    assert request.metadata["intent_id"] == intent.intent_id

    # Exchange state: one resting order, no fills.
    open_orders = await client.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].status == "resting"
    assert open_orders[0].client_order_id == coid
    assert client._fills == []
    assert client._balance_usd == Decimal("10000")

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.SUBMITTED


@pytest.mark.asyncio
async def test_taker_ioc_zero_fill_leaves_no_resting_reservation(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    """A taker IOC that does not cross must leave nothing on the book and
    free the gate slot for the next cycle."""
    client.set_orderbook(TICKER_TAKER_ZERO, best_bid_cents=45, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    _set_market(client, TICKER_TAKER_ZERO)

    # Buy at 50c does not cross the 55c ask.
    intent = _entry_intent(
        ticker=TICKER_TAKER_ZERO, price_cents=50, count=1,
        tif="ioc", post_only=False, aggressiveness=1.0,
    )
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "unfilled_ioc", (result.status, result.reason)

    # No resting reservation remains on the venue.
    assert (await client.get_open_orders_result()).data == []
    assert client._fills == []
    assert client._balance_usd == Decimal("10000")
    assert client._position_yes.get(TICKER_TAKER_ZERO, Decimal("0")) == Decimal("0")

    # The gate slot is freed so a fresh signal can retry next cycle.
    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_taker_ioc_full_fill_executes_immediately(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    """A taker IOC that crosses the spread fills immediately."""
    client.set_orderbook(TICKER_TAKER_FULL, best_bid_cents=45, best_ask_cents=55,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    _set_market(client, TICKER_TAKER_FULL)

    # Buy at 55c crosses the 55c ask.
    intent = _entry_intent(
        ticker=TICKER_TAKER_FULL, price_cents=55, count=1,
        tif="ioc", post_only=False, aggressiveness=1.0,
    )
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "filled_live", (result.status, result.reason)
    assert result.fill["count"] == 1
    assert result.fill["price_cents"] == 55
    assert result.fill["client_tag"] == coid
    assert result.fill["order_id"]

    # Exchange state: position established at the ask, nothing resting.
    assert client._position_yes[TICKER_TAKER_FULL] == Decimal("1")
    assert (await client.get_open_orders_result()).data == []
    assert len(client._fills) == 1
    assert client._balance_usd == Decimal("10000") - (Decimal("1") * Decimal("0.55"))

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.FILLED
