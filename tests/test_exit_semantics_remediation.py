"""Regression tests for the exit/close-semantics remediation.

Covers the producer-side and router-side fixes made during the exit audit:

- ``_resolve_kalshi_side`` canonical mapping (YES/NO x buy/sell -> wire forms).
- ``_check_exit_delta_invariant`` fail-closed on unknown/error position state.
- ``market_order_fallback`` preserves exit/reduce-only semantics + stable coid.
- ``resting_order_monitor._retry_exit_order`` stable identity + no blind retry
  after ambiguous submission outcomes.
- ``execution_queue_handler`` direction mapping (``entry.direction``, not
  ``entry.side``) — ``"short"`` -> BUY_NO, never a sell.
- ``agent_mode_router`` canonical side mapping — ``"no"`` -> BUY_NO.
- Hedge ``to_order_intents`` exit marking for sell-side hedge orders.
- ``StopCandidateExecutionReducer`` deterministic per-candidate identity and
  reconcile-before-retry after ``submission_unknown``.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


TICKER = "KXBTC15M-ZZTEST"


# ── _resolve_kalshi_side ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "side, action, expected",
    [
        ("yes", "sell", "SELL_YES"),   # long-YES exit
        ("no", "sell", "SELL_NO"),     # long-NO exit
        ("yes", "buy", "BUY_YES"),     # YES entry
        ("no", "buy", "BUY_NO"),       # NO entry (Kalshi "short")
        ("SELL_YES", "sell", "SELL_YES"),  # already canonical
        ("sell_no", "sell", "SELL_NO"),    # lowercase Kalshi form
    ],
)
def test_resolve_kalshi_side_mapping_table(side, action, expected):
    from merid.event_venues.kalshi.order_router import OrderIntent, _resolve_kalshi_side

    intent = OrderIntent(ticker=TICKER, side=side, action=action, price_cents=50, count=1)
    assert _resolve_kalshi_side(intent) == expected


def test_resolve_kalshi_side_resolves_kalshi_side_only_intent():
    """A kalshi_side-only intent resolves: __post_init__ derives the
    side/action pair from kalshi_side, which the wire builder then
    serializes — so validation and serialization stay in lockstep."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _resolve_kalshi_side

    intent = OrderIntent(
        ticker=TICKER, side="", action="", price_cents=50, count=1, kalshi_side="SELL_NO"
    )
    assert (intent.side, intent.action) == ("no", "sell")
    assert _resolve_kalshi_side(intent) == "SELL_NO"


def test_resolve_kalshi_side_prefers_wire_side_over_kalshi_side_field():
    """intent.side wins over kalshi_side to match _build_create_order_request."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _resolve_kalshi_side

    intent = OrderIntent(
        ticker=TICKER, side="yes", action="sell", price_cents=50, count=1,
        kalshi_side="SELL_NO",  # conflicting field — wire builder ignores it
    )
    assert _resolve_kalshi_side(intent) == "SELL_YES"


def test_resolve_kalshi_side_rejects_unmappable():
    from merid.event_venues.kalshi.order_router import OrderIntent, _resolve_kalshi_side

    intent = OrderIntent(ticker=TICKER, side="long", action="buy", price_cents=50, count=1)
    assert _resolve_kalshi_side(intent) is None


# ── _check_exit_delta_invariant: fail closed ────────────────────────────────


def _exit_intent(**over):
    from merid.event_venues.kalshi.order_router import OrderIntent

    kw = dict(
        ticker=TICKER,
        side="yes",
        action="sell",
        price_cents=50,
        count=1,
        entry_or_exit="exit",
        exit_reason="exit_tp",
        reduce_only=True,
    )
    kw.update(over)
    return OrderIntent(**kw)


def test_exit_delta_fails_closed_when_position_unknown(monkeypatch):
    """No pre_position_fp, no canonical snapshot, no cache position -> reject."""
    import merid.event_venues.kalshi.position_cache as pc_mod

    cache = MagicMock()
    cache.get_position.return_value = None
    monkeypatch.setattr(pc_mod, "get_position_cache", lambda: cache)

    from merid.event_venues.kalshi.order_router import _check_exit_delta_invariant, TradingMode

    result = _check_exit_delta_invariant(_exit_intent(), TradingMode.PAPER)
    assert result is not None and result.status == "rejected"
    assert "unknown_position" in (result.reason or "")


def test_exit_delta_fails_closed_on_check_exception(monkeypatch):
    """An exception while resolving position state must not fail open."""
    import merid.event_venues.kalshi.position_cache as pc_mod

    cache = MagicMock()
    cache.get_position.side_effect = RuntimeError("cache unavailable")
    monkeypatch.setattr(pc_mod, "get_position_cache", lambda: cache)

    from merid.event_venues.kalshi.order_router import _check_exit_delta_invariant, TradingMode

    result = _check_exit_delta_invariant(_exit_intent(), TradingMode.PAPER)
    assert result is not None and result.status == "rejected"


def test_exit_delta_uses_canonical_fresh_position_exact(monkeypatch):
    """A fractional exit validated against the exact canonical snapshot passes.

    Regression: a whole-contract legacy fallback (floor) would false-reject a
    1.25-contract exit of a real 1.5-contract position.
    """
    import merid.event_venues.kalshi.position_cache as pc_mod

    cache = MagicMock()
    cache.get_position.return_value = None
    monkeypatch.setattr(pc_mod, "get_position_cache", lambda: cache)

    from merid.event_venues.kalshi.order_router import _check_exit_delta_invariant, TradingMode

    intent = _exit_intent(count=1, count_fp=Decimal("1.25"))
    intent._canonical_order_intent = SimpleNamespace(expected_position_before=150)

    result = _check_exit_delta_invariant(intent, TradingMode.PAPER)
    assert result is None, f"valid 1.50 -> 0.25 exit was rejected: {result}"


# ── market_order_fallback: exit semantics + stable identity ─────────────────


def _resting_record(**over):
    from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord

    kw = dict(
        kalshi_order_id="kord-1",
        ticker=TICKER,
        side="yes",
        action="sell",
        original_size=1,
        remaining_size=1,
        price_cents=45,
        intent_id="orig_intent_1",
        client_order_id="take_profit_abc123",
        exit_policy_id="exit_policy_1",
    )
    kw.update(over)
    return RestingOrderRecord(**kw)


@pytest.mark.asyncio
async def test_fallback_preserves_exit_semantics_and_stable_coid():
    from merid.event_venues.kalshi.market_order_fallback import (
        FallbackDecision,
        MarketOrderFallbackEngine,
    )

    captured = {}

    async def fake_route(intent):
        captured["intent"] = intent
        return SimpleNamespace(status="filled_live", order_id="fb-1", has_execution=True)

    client = MagicMock()
    client.cancel_order = AsyncMock(return_value={"status": "canceled"})

    engine = MarketOrderFallbackEngine()
    decision = FallbackDecision(
        should_fallback=True, reason="test", original_order=_resting_record()
    )

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: client
    ), patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ), patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        lambda ticker: (None, None),
    ):
        result = await engine.execute_fallback(decision)

    assert result["status"] == "executed"
    intent = captured["intent"]
    # Exit semantics preserved: the fallback of a resting exit must remain a
    # bounded reduce-only close.
    assert intent.entry_or_exit == "exit"
    assert intent.reduce_only is True
    assert intent.is_exit_order is True
    assert intent.exit_reason
    assert intent.exit_policy_id == "exit_policy_1"
    # Stable, deterministic identity derived from the original order.
    assert intent.client_order_id
    assert intent.client_order_id.startswith("take_profit_abc123"[:40])
    assert "_fb_" in intent.client_order_id
    assert len(intent.client_order_id) <= 64
    assert intent.intent_id == "fallback_orig_intent_1"
    # Real price, not the old price_cents=0 market-order stub.
    assert 1 <= intent.price_cents <= 99


@pytest.mark.asyncio
async def test_fallback_coid_deterministic_across_retries():
    """Two fallbacks of the same original order produce the same coid."""
    from merid.event_venues.kalshi.market_order_fallback import (
        FallbackDecision,
        MarketOrderFallbackEngine,
    )

    coids = []

    async def fake_route(intent):
        coids.append(intent.client_order_id)
        return SimpleNamespace(status="filled_live", order_id="fb-x")

    client = MagicMock()
    client.cancel_order = AsyncMock(return_value={"status": "canceled"})
    engine = MarketOrderFallbackEngine()

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: client
    ), patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ), patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        lambda ticker: (None, None),
    ):
        for _ in range(2):
            await engine.execute_fallback(
                FallbackDecision(
                    should_fallback=True, reason="t", original_order=_resting_record()
                )
            )

    assert len(coids) == 2 and coids[0] == coids[1]


@pytest.mark.asyncio
async def test_fallback_entry_order_not_marked_exit():
    """A resting ENTRY order's fallback must not be marked reduce-only exit."""
    from merid.event_venues.kalshi.market_order_fallback import (
        FallbackDecision,
        MarketOrderFallbackEngine,
    )

    captured = {}

    async def fake_route(intent):
        captured["intent"] = intent
        return SimpleNamespace(status="filled_live", order_id="fb-2")

    client = MagicMock()
    client.cancel_order = AsyncMock(return_value={"status": "canceled"})

    cache = MagicMock()
    cache.get_position.return_value = None
    engine = MarketOrderFallbackEngine()

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: client
    ), patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ), patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        lambda ticker: (None, None),
    ), patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache", lambda: cache
    ):
        await engine.execute_fallback(
            FallbackDecision(
                should_fallback=True,
                reason="t",
                original_order=_resting_record(
                    side="yes", action="buy", client_order_id="entry_abc",
                    exit_policy_id="",
                ),
            )
        )

    intent = captured["intent"]
    assert intent.entry_or_exit != "exit"
    assert intent.reduce_only is not True


# ── resting_order_monitor retry: stable identity + no blind retry ───────────


@pytest.mark.asyncio
async def test_exit_retry_carries_stable_identity_and_reduce_only():
    from merid.event_venues.kalshi.resting_order_monitor import (
        ExitOrderState,
        RestingOrderMonitor,
    )

    captured = {}

    async def fake_route(intent):
        captured["intent"] = intent
        return SimpleNamespace(
            status="filled_live", order_id="new-ord-1", has_execution=True,
            reason=None,
        )

    state = ExitOrderState(
        order_id="ord-1", asset="BTC", side="SELL_YES", action="sell",
        base_price_cents=45, current_aggressiveness=0.5, retries_left=5,
        last_action_ts=0.0, status="pending",
        intent_id="exit_intent_1", client_order_id="exit_coid_1",
        ticker=TICKER, count=1, exit_reason="exit_tp", exit_policy_id="pol_1",
    )
    state.total_retries = 1

    monitor = RestingOrderMonitor()
    with patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ):
        await monitor._retry_exit_order(state, new_price_cents=40, delay_ms=0)

    intent = captured["intent"]
    assert intent.entry_or_exit == "exit"
    assert intent.reduce_only is True
    assert intent.intent_id == "exit_intent_1"
    # Deterministic per-attempt identity derived from the original coid.
    assert intent.client_order_id == "exit_coid_1_r01"
    assert intent.exit_reason == "exit_tp"
    assert intent.exit_policy_id == "pol_1"


@pytest.mark.asyncio
async def test_exit_retry_halts_on_submission_unknown():
    """A submission_unknown result must not stack another live order."""
    from merid.event_venues.kalshi.resting_order_monitor import (
        ExitOrderState,
        RestingOrderMonitor,
    )

    async def fake_route(intent):
        return SimpleNamespace(
            status="submission_unknown", order_id=None, has_execution=False,
            reason="timeout",
        )

    state = ExitOrderState(
        order_id="ord-2", asset="BTC", side="SELL_YES", action="sell",
        base_price_cents=45, current_aggressiveness=0.5, retries_left=3,
        last_action_ts=0.0, status="pending",
        intent_id="exit_intent_2", client_order_id="exit_coid_2",
        ticker=TICKER, count=1, exit_reason="exit_tp", exit_policy_id="pol_2",
    )
    state.total_retries = 1
    retries_before = state.retries_left

    monitor = RestingOrderMonitor()
    with patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ):
        await monitor._retry_exit_order(state, new_price_cents=40, delay_ms=0)

    assert state.status == "pending_reconciliation"
    # No further retry was scheduled.
    assert state.retries_left == retries_before


# ── execution_queue_handler: canonical direction mapping ────────────────────


def _queue_entry(direction: str):
    from merid.execution.execution_queue import ExecutionQueueEntry

    entry = ExecutionQueueEntry.from_signal(
        ticker=TICKER,
        direction=direction,
        size_contracts=1,
        edge=0.02,
        confidence=0.7,
        bankroll_snapshot_usd=Decimal("100"),
        risk_ok=True,
        recon_ok=True,
        agent_id="test_agent",
        metadata={"limit_price_cents": 50},
    )
    entry.entry_id = "eq-1"
    return entry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction, exp_side, exp_action",
    [
        ("long", "yes", "buy"),
        ("yes", "yes", "buy"),
        ("short", "no", "buy"),   # Kalshi short = long NO, never a sell
        ("no", "no", "buy"),
    ],
)
async def test_queue_handler_maps_direction_to_canonical_entry(
    direction, exp_side, exp_action
):
    from merid.execution.execution_queue_handler import ExecutionQueueHandler

    captured = {}

    async def fake_route(intent):
        captured["intent"] = intent
        return SimpleNamespace(
            status="filled_paper", has_execution=True, request_completed=True,
            is_terminal=True,
        )

    queue = MagicMock()
    handler = ExecutionQueueHandler(queue=queue)

    with patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ):
        await handler._execute_entry(_queue_entry(direction))

    intent = captured["intent"]
    assert intent.side == exp_side
    assert intent.action == exp_action
    assert intent.entry_or_exit == "entry"
    queue.mark_executed.assert_called_once_with("eq-1", TICKER, success=True)


@pytest.mark.asyncio
async def test_queue_handler_rejects_unmappable_direction():
    from merid.execution.execution_queue_handler import ExecutionQueueHandler

    async def fake_route(intent):  # pragma: no cover - must never be called
        raise AssertionError("route_order_async called for unmappable direction")

    queue = MagicMock()
    handler = ExecutionQueueHandler(queue=queue)

    with patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ):
        await handler._execute_entry(_queue_entry("sideways"))

    queue.mark_executed.assert_called_once_with("eq-1", TICKER, success=False)


# ── agent_mode_router: canonical side mapping ───────────────────────────────


def test_agent_mode_router_maps_no_to_buy_no():
    """Regression: side='no' must produce BUY_NO, not a sell (SELL_NO = long YES)."""
    import merid.kalshi.agent_mode_router as amr

    captured = {}

    async def fake_route(intent):
        captured["intent"] = intent
        return SimpleNamespace(has_execution=True)

    router = amr.AgentModeRouter.__new__(amr.AgentModeRouter)
    router.paper_portfolio = MagicMock()

    cfg = SimpleNamespace(mode="live", size_multiplier=1.0)
    with patch.object(amr, "is_agent_enabled", return_value=True), patch.object(
        amr, "get_agent_mode_config", return_value=cfg
    ), patch.object(amr, "get_agent_size_multiplier", return_value=1.0), patch(
        "merid.event_venues.kalshi.order_router.route_order_async", fake_route
    ):
        ok = router.route_opinion("agent_x", TICKER, "no", 1, 0.7)

    assert ok is True
    intent = captured["intent"]
    assert intent.side == "no"
    assert intent.action == "buy"
    assert intent.entry_or_exit == "entry"


def test_agent_mode_router_rejects_unknown_side():
    import merid.kalshi.agent_mode_router as amr

    router = amr.AgentModeRouter.__new__(amr.AgentModeRouter)
    router.paper_portfolio = MagicMock()

    cfg = SimpleNamespace(mode="live", size_multiplier=1.0)
    with patch.object(amr, "is_agent_enabled", return_value=True), patch.object(
        amr, "get_agent_mode_config", return_value=cfg
    ), patch.object(amr, "get_agent_size_multiplier", return_value=1.0):
        ok = router.route_opinion("agent_x", TICKER, "sideways", 1, 0.7)

    assert ok is False


# ── hedge engine: exit intent marking ────────────────────────────────────────


def test_hedge_exit_intent_marked_reduce_only():
    from merid.hedging.engine import CryptoHedgeEngine, HedgeOrder, HedgeResult

    result = HedgeResult(
        orders=[
            HedgeOrder(
                asset="BTC",
                timeframe="exit",
                hedge_reason="tp_exit:profit",
                side="yes",
                action="sell",
                count=1,
                price_cents=80,
                target_ticker=TICKER,
                client_tag="tp_exit:profit:rec1",
            )
        ]
    )

    intents = CryptoHedgeEngine().to_order_intents(result)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.entry_or_exit == "exit"
    assert intent.reduce_only is True
    assert intent.is_exit_order is True
    assert intent.exit_reason == "tp_exit:profit"
    # client_tag doubles as stable per-record client_order_id for idempotency.
    assert intent.client_order_id == "tp_exit:profit:rec1"


def test_hedge_entry_intent_marked_entry():
    from merid.hedging.engine import CryptoHedgeEngine, HedgeOrder, HedgeResult

    result = HedgeResult(
        orders=[
            HedgeOrder(
                asset="BTC",
                timeframe="15m",
                hedge_reason="same_asset_same_horizon",
                side="no",
                action="buy",
                count=1,
                price_cents=30,
                target_ticker=TICKER,
                client_tag="hedge_entry:rec2",
            )
        ]
    )

    intents = CryptoHedgeEngine().to_order_intents(result)
    intent = intents[0]
    assert intent.entry_or_exit == "entry"
    assert intent.reduce_only is not True
    assert intent.is_exit_order is False


# ── stop-candidate reducer: deterministic identity + reconcile-before-retry ──


def _stop_candidate(**over):
    from merid.event_venues.kalshi.stop_candidate import StopCandidate

    kw = dict(
        market_ticker=TICKER,
        trigger_reason="STOP_LOSS",
        position_from_exchange_cc=100,  # 1.00 long-YES contract
        executable_exit_cents=40,
        seconds_to_expiry=None,
    )
    kw.update(over)
    return StopCandidate(**kw)


def _make_reducer(submit, fetch=None):
    from merid.event_venues.kalshi.stop_candidate_reducer import (
        StopCandidateExecutionReducer,
    )

    async def _no_open_orders(ticker=None):
        return []

    async def _no_cancel(order_id):
        return None

    if fetch is None:

        async def fetch(ticker, timeout=1.0, fallback_to_cache=True):
            return (100, 45, "yes")

    return StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=_no_open_orders,
        cancel_order=_no_cancel,
        submit_order=submit,
        retry_backoff_seconds=0.0,
    )


@pytest.mark.asyncio
async def test_reducer_deterministic_identity_across_retry():
    """Retries of one candidate reuse the same intent_id/client_order_id."""
    seen = []

    async def submit(intent):
        seen.append((intent.intent_id, intent.client_order_id))
        status = "submission_unknown" if len(seen) == 1 else "filled_live"
        return SimpleNamespace(status=status)

    reducer = _make_reducer(submit)
    result = await reducer.reduce(_stop_candidate(), force=True)

    assert result.status == "submitted"
    assert len(seen) == 2
    # Same logical intent -> identical venue idempotency key on retry.
    assert seen[0] == seen[1]
    assert seen[0][1].startswith("stopcand_sc-")


@pytest.mark.asyncio
async def test_reducer_reconciles_position_before_retry_after_unknown():
    """After submission_unknown, a now-flat position must stop the retry."""
    submit_calls = []
    fetch_calls = []

    async def submit(intent):
        submit_calls.append(intent)
        return SimpleNamespace(status="submission_unknown")

    async def fetch(ticker, timeout=1.0, fallback_to_cache=True):
        fetch_calls.append(ticker)
        # First fetch = pre-submit snapshot; refresh sees the position filled.
        return (100, 45, "yes") if len(fetch_calls) == 1 else (0, 45, "yes")

    reducer = _make_reducer(submit, fetch=fetch)
    result = await reducer.reduce(_stop_candidate(), force=True)

    # Position went flat -> the exit already happened venue-side; no resubmit.
    assert result.status == "no_position"
    assert len(submit_calls) == 1
    assert len(fetch_calls) == 2  # initial fetch + pre-retry reconciliation


@pytest.mark.asyncio
async def test_reducer_no_double_submit_on_persistent_unknown():
    """Persistent submission_unknown escalates instead of stacking orders."""
    submit_calls = []

    async def submit(intent):
        submit_calls.append(intent)
        return SimpleNamespace(status="submission_unknown")

    reducer = _make_reducer(submit)
    result = await reducer.reduce(_stop_candidate(), force=True)

    assert result.status == "escalated"
    assert len(submit_calls) <= reducer.max_retry_attempts
