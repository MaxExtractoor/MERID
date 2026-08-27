"""P0 exit-order tests: ``_route_live`` through the ``KalshiExecutionPort``.

These tests drive the production live-routing path (``_route_live``) against
``DeterministicKalshiClient`` injected via ``set_kalshi_execution_port`` and
verify exit-order lifecycle behaviour:

- full-fill / partial-fill / zero-fill IOC exit orders
- timeout-after-submit recovery (gate record -> SUBMISSION_UNKNOWN)
- sub-10c reduce-only exit acceptance (entry floor must not trap exits)
- cancel-versus-fill race: cancel after a partial fill, final position check

Risk/gate helpers unrelated to the port (kill switches, venue gate, dynamic
risk) are stubbed; the exchange side is the real deterministic simulator.
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
    OrderStatus,
    get_pre_trade_gate,
    reset_pre_trade_gate_for_testing,
)
from merid.event_venues.kalshi.contract_lease import (
    reset_contract_lease_registry_for_testing,
)
from merid.event_venues.kalshi.port import (
    get_kalshi_execution_port,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

TICKER = "KXBTC15M-TEST-50000"


# ---------------------------------------------------------------------------
# Stubs for non-port risk/gate helpers
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
    # The raw client is retained in _route_live only for the public WS/REST
    # orderbook divergence check and the post-fill balance probe.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: c
    )
    # Stub risk/gate helpers that are unrelated to the port boundary.
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
    import merid.settings as _settings

    monkeypatch.setattr(_settings.settings, "MERID_EXECUTION_MODE", "normal")
    yield c
    reset_kalshi_execution_port_for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_intent(
    *,
    ticker: str = TICKER,
    side: str = "SELL_YES",
    action: str = "sell",
    price_cents: int = 50,
    count: int = 2,
    tif: str = "ioc",
    reduce_only: bool = True,
    pre_position: int = 5,
) -> OrderIntent:
    # NOTE: intents reaching _route_live carry Kalshi-formatted sides
    # (BUY_YES/SELL_YES/BUY_NO/SELL_NO) â€” the [SEV-0-SIDE-INVARIANT] check in
    # _route_live rejects bare "yes"/"no".  Upstream (loop_15m) stamps the
    # Kalshi format; "SELL_YES" here is the semantic "side=yes, action=sell".
    return OrderIntent(
        ticker=ticker,
        side=side,
        action=action,
        price_cents=price_cents,
        count=count,
        time_in_force=tif,
        entry_or_exit="exit",
        reduce_only=reduce_only,
        exit_policy_id="test",
        exit_reason="exit_manual",
        source="position_monitor_exit",
        aggressiveness=1.0 if tif == "ioc" else 0.0,
        snapshot_ts=time.time(),
        pre_position_size=pre_position,
        expected_post_position_size=0,
    )


class _DedupCacheStub:
    """Pin the router's dedup cache to the gate-reserved client_order_id.

    ``_route_live`` calls ``cache.get_or_create(...)`` and overwrites
    ``intent.client_tag`` with the returned coid; in production the gate
    reservation and dedup cache are populated together upstream.  In these
    tests we reserve the gate slot first, so the dedup cache must hand back
    the same coid (and report "not a duplicate").
    """

    def __init__(self, coid: str) -> None:
        self._coid = coid

    def get_or_create(self, **kwargs):
        return self._coid, False

    def mark_completed(self, *args, **kwargs) -> None:
        pass


def _reserve_gate(intent: OrderIntent, monkeypatch) -> str:
    """Create the PENDING pre-trade gate record the router would own."""
    gate = get_pre_trade_gate()
    verdict = gate.check(
        agent_id=intent.agent_id or "position_monitor_exit",
        strategy_group="test_exit",
        contract_id=intent.ticker,
        side=intent.side,
        action=intent.action,
        target_count=intent.count,
        price_cents=intent.price_cents,
        decision_ts=intent.snapshot_ts,
        intent_id=intent.intent_id,
        exit_policy_id=intent.exit_policy_id,
        entry_or_exit=intent.entry_or_exit,
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


def _gate_record(client_order_id: str):
    for rec in get_pre_trade_gate().store.snapshot():
        if rec.client_order_id == client_order_id:
            return rec
    return None


async def _route(intent: OrderIntent):
    return await _route_live(intent, TradingMode.LIVE, time.monotonic())


# ---------------------------------------------------------------------------
# Exit order scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exit_order_full_fill(client: DeterministicKalshiClient, monkeypatch) -> None:
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    client.set_orderbook(TICKER, best_bid_cents=50, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    intent = _exit_intent(price_cents=50, count=2)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "filled_live", result.reason
    assert result.fill["count"] == 2
    assert result.fill["price_cents"] == 50
    assert result.fill["client_tag"] == coid
    assert result.fill["order_id"]

    # Exchange state: position reduced, no resting residue.
    assert client._position_yes[TICKER] == Decimal("3")
    assert (await client.get_open_orders_result()).data == []
    assert len(client._fills) == 1

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_exit_order_partial_fill(client: DeterministicKalshiClient, monkeypatch) -> None:
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    # Only 1 contract available at the bid.
    client.set_orderbook(TICKER, best_bid_cents=50, best_ask_cents=60,
                         bid_size=Decimal("1"), ask_size=Decimal("10"))

    intent = _exit_intent(price_cents=50, count=2)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    # Partial fill is still exposure-affecting: filled_live with partial detail.
    assert result.status == "filled_live", result.reason
    assert result.fill["count"] == 1
    assert result.fill["requested_count"] == 2
    assert result.fill["partial"] is True

    # IOC remainder is killed: nothing rests on the book.
    assert client._position_yes[TICKER] == Decimal("4")
    assert (await client.get_open_orders_result()).data == []

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.PARTIAL


@pytest.mark.asyncio
async def test_exit_order_zero_fill_ioc(client: DeterministicKalshiClient, monkeypatch) -> None:
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    # Bid below our limit: a sell at 50 does not cross a 40c bid.
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    intent = _exit_intent(price_cents=50, count=2)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "unfilled_ioc", (result.status, result.reason)
    assert client._position_yes[TICKER] == Decimal("5")
    assert (await client.get_open_orders_result()).data == []
    assert client._fills == []

    # The gate slot is freed for a retry on the next cycle.
    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_exit_order_timeout_after_submit_recovery(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    client.set_orderbook(TICKER, best_bid_cents=50, best_ask_cents=60,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))
    client.set_timeout_after_submit("once")

    intent = _exit_intent(price_cents=50, count=2)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    # The create-order ack was lost, but the broker query resolves the order
    # to filled without resubmitting.  Exposure is applied by the fills poller,
    # not the router, so no double-counting occurs.
    assert result.status == "filled_live", (result.status, result.reason)
    assert result.has_execution
    assert result.order_id is not None

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.FILLED

    # The broker lookup is idempotent: the same order is still reachable.
    recovered = await client.get_order(client_order_id=coid)
    assert recovered is not None
    assert recovered.status == "filled"
    assert recovered.filled_size == Decimal("2")

    # Exchange truth: position was reduced even though the ack timed out.
    assert client._position_yes[TICKER] == Decimal("3")


@pytest.mark.asyncio
async def test_exit_order_sub_10c_reduce_only_accepted(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    """Sub-10c reduce-only exits must be accepted: the 10c floor is an entry
    guard and must never trap a position that needs to close."""
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    client.set_orderbook(TICKER, best_bid_cents=8, best_ask_cents=20,
                         bid_size=Decimal("10"), ask_size=Decimal("10"))

    intent = _exit_intent(price_cents=8, count=2)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "filled_live", result.reason
    assert result.fill["count"] == 2
    assert result.fill["price_cents"] == 8
    assert client._position_yes[TICKER] == Decimal("3")

    rec = _gate_record(coid)
    assert rec is not None
    assert rec.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_exit_order_cancel_after_partial_fill(
    client: DeterministicKalshiClient, monkeypatch,
) -> None:
    """Cancel-versus-fill race: a resting exit that partially filled is then
    canceled; the final position must reflect only the executed contracts."""
    client.set_initial_position(TICKER, "yes", 5, avg_price_cents=50)
    # Only 3 contracts bid at 40c; the remaining 2 rest on the book.
    client.set_orderbook(TICKER, best_bid_cents=40, best_ask_cents=60,
                         bid_size=Decimal("3"), ask_size=Decimal("10"))

    # Non-reduce-only exit so the GTC remainder is allowed to rest.
    intent = _exit_intent(price_cents=40, count=5, tif="gtc", reduce_only=False)
    coid = _reserve_gate(intent, monkeypatch)

    result = await _route(intent)

    assert result.status == "filled_live", result.reason
    assert result.fill["count"] == 3
    assert result.fill["remaining_count"] == 2
    assert result.fill["partial"] is True

    # The remainder is resting on the exchange.
    open_orders = await client.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].remaining_size == Decimal("2")

    # Cancel the resting remainder (cancel-after-partial race).
    port = get_kalshi_execution_port()
    cancel = await port.cancel_order(result.order_id)
    assert cancel.success, cancel.error

    # Final exchange state: only the 3 executed contracts left the position.
    assert client._position_yes[TICKER] == Decimal("2")
    assert (await client.get_open_orders_result()).data == []

    final = await client.get_order(order_id=result.order_id)
    assert final is not None
    assert final.status == "canceled"
    assert final.filled_size == Decimal("3")
