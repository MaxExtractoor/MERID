"""Replay harness for the StopCandidateExecutionReducer.

Each scenario replays a sequence of market/position snapshots through the
reducer with deterministic mocked fetch/cancel/submit callables.  The acceptance
bar is: exactly one exit, correct quantity, correct side, no orphaned orders,
and a clear terminal state.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure
from merid.event_venues.kalshi.stop_candidate import StopCandidate, build_stop_candidate
from merid.event_venues.kalshi.stop_candidate_reducer import (
    ReducerResult,
    StopCandidateExecutionReducer,
)


class _FakeOrderResult:
    def __init__(self, status, order_id=None, fill=None, reason=None):
        self.status = status
        self.order_id = order_id
        self.fill = fill
        self.reason = reason
        self.mode = SimpleNamespace(value="paper")

    def to_dict(self):
        return {
            "status": self.status,
            "order_id": self.order_id,
            "fill": self.fill,
            "reason": self.reason,
        }


def _kalshi_state(yes_bid=48, yes_ask=51, no_bid=49, no_ask=52, seconds_to_expiry=600.0):
    return SimpleNamespace(
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        no_bid_cents=no_bid,
        no_ask_cents=no_ask,
        book=SimpleNamespace(
            best_yes_bid=yes_bid,
            best_yes_ask=yes_ask,
            yes_bids=[SimpleNamespace(price_cents=yes_bid)],
            no_bids=[SimpleNamespace(price_cents=no_bid)],
        ),
        book_sequence=123,
        book_updated_ts=0.0,
        seconds_to_expiry=seconds_to_expiry,
    )


def _unified_state(fair_yes=0.45):
    return SimpleNamespace(
        external_fair_value=fair_yes,
        book=SimpleNamespace(
            best_yes_bid=50,
            best_yes_ask=51,
            yes_bids=[SimpleNamespace(price_cents=50)],
            no_bids=[SimpleNamespace(price_cents=49)],
        ),
    )


def _actor(position=1000, open_orders=None, submit_result=None, cancel_ok=True):
    """Return deterministic dependency callables for a replay scenario."""
    if open_orders is None:
        open_orders = []
    if submit_result is None:
        submit_result = _FakeOrderResult("filled_live", order_id="order-1")

    pos_state = {"position": position}
    cancel_log: list = []
    submit_log: list = []

    async def fetch_position(ticker, timeout=1.0, fallback_to_cache=True):
        return pos_state["position"], 50, "yes" if pos_state["position"] > 0 else "no"

    async def get_open_orders(ticker=None):
        return open_orders

    async def cancel_order(order_id):
        cancel_log.append(order_id)
        if cancel_ok:
            return SimpleNamespace(success=True)
        raise RuntimeError("cancel failed")

    async def submit_order(intent):
        submit_log.append(intent)
        return submit_result

    return (
        fetch_position,
        get_open_orders,
        cancel_order,
        submit_order,
        pos_state,
        cancel_log,
        submit_log,
    )


def _yes_candidate(qty_cc=1000, held="yes", executable=48, fair=45, trigger="HARD_STOP", quote_age_ms=0, position_snapshot_age_ms=0):
    return build_stop_candidate(
        market_ticker="KXBTC15M-TEST",
        exchange_position_cc=to_signed_yes_exposure(held, qty_cc),
        trigger_reason=trigger,
        entry_price_cents=50,
        executable_exit_cents=executable,
        fair_value_cents=fair,
        kalshi_state=_kalshi_state(yes_bid=executable),
        unified_state=_unified_state(fair_yes=fair / 100.0),
        quote_age_ms=quote_age_ms,
        position_snapshot_age_ms=position_snapshot_age_ms,
        seconds_to_expiry=600.0,
    )


@pytest.mark.asyncio
async def test_single_stop_submits_one_exit():
    """One stop trigger -> one reduce-only IOC exit for the full position."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)

    assert result.status == "submitted"
    assert result.order_result is not None
    assert result.order_result.status == "filled_live"
    assert result.order_result.order_id == "order-1"
    assert len(submit_log) == 1
    intent = submit_log[0]
    assert intent.reduce_only is True
    assert intent.time_in_force == "ioc"
    assert intent.action == "sell"
    assert intent.side == "yes"
    assert intent.count == 10


@pytest.mark.asyncio
async def test_repeated_stop_trigger_is_suppressed():
    """Two concurrent triggers for the same position version produce one exit."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()

    async def run():
        return await reducer.reduce(candidate, force=True)

    results = await asyncio.gather(run(), run())
    statuses = [r.status for r in results]
    assert "submitted" in statuses
    assert "duplicate" in statuses
    assert len([s for s in statuses if s == "submitted"]) == 1
    assert len(submit_log) == 1


@pytest.mark.asyncio
async def test_partial_fill_then_stop_exits_remaining():
    """After a partial fill leaves 5 contracts, a new stop trigger exits 5."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("partial_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate(qty_cc=1000)
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "submitted"
    assert submit_log[-1].count == 10

    # Simulate the exchange now reports only 5 contracts (partial fill applied).
    pos_state["position"] = 500
    candidate2 = _yes_candidate(qty_cc=500)
    result2 = await reducer.reduce(candidate2, force=True)
    assert result2.status == "submitted"
    assert submit_log[-1].count == 5
    assert len([i for i in submit_log if i.count == 10]) == 1
    assert len([i for i in submit_log if i.count == 5]) == 1


@pytest.mark.asyncio
async def test_position_sign_mismatch_rejects_stale_stop():
    """If the position has flipped since the candidate, do not submit."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=-1000, submit_result=_FakeOrderResult("filled_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate(qty_cc=1000, held="yes")
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "stale_position"
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_position_flat_rejects_stop():
    """A stop trigger when the position is already flat is a no-op."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=0, submit_result=_FakeOrderResult("filled_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "no_position"
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_conflicting_open_order_cancelled_before_submission():
    """A stale sell order on the held side is cancelled before the new exit."""
    stale_order = SimpleNamespace(
        order_id="stale-1",
        market_id="KXBTC15M-TEST",
        side="yes",
        action="sell",
    )
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000,
        open_orders=[stale_order],
        submit_result=_FakeOrderResult("filled_live", order_id="order-1"),
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "submitted"
    assert "stale-1" in cancel_log
    assert len(submit_log) == 1


@pytest.mark.asyncio
async def test_cancel_failure_escalates():
    """If cancelling a conflicting order fails, escalate rather than submit."""
    stale_order = SimpleNamespace(
        order_id="stale-1",
        market_id="KXBTC15M-TEST",
        side="yes",
        action="sell",
    )
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000,
        open_orders=[stale_order],
        cancel_ok=False,
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "escalated"
    assert "cancel" in result.reason
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_venue_rejected_exit_escalates_after_retries():
    """A venue rejection consumes the retry budget and then escalates."""
    attempts = {"count": 0}

    async def reject_submit(intent):
        attempts["count"] += 1
        return _FakeOrderResult("rejected", reason="venue_rejected")

    fetch, open, cancel, _, pos_state, cancel_log, submit_log = _actor(position=1000)
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=reject_submit,
        max_retry_attempts=2,
        retry_backoff_seconds=0.0,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "escalated"
    assert attempts["count"] == 2
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_stale_quote_rejects():
    """A stop with a stale quote is rejected, not submitted."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    # Quote age beyond the 10_000 ms limit.
    candidate = _yes_candidate(quote_age_ms=60_000)
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "rejected"
    assert "stale_quote" in result.reason
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_settlement_approach_blocks_stop():
    """A stop inside the close cutoff window is rejected."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = build_stop_candidate(
        market_ticker="KXBTC15M-TEST",
        exchange_position_cc=1000,
        trigger_reason="HARD_STOP",
        entry_price_cents=50,
        executable_exit_cents=48,
        fair_value_cents=45,
        kalshi_state=_kalshi_state(yes_bid=48),
        unified_state=_unified_state(fair_yes=0.45),
        quote_age_ms=0,
        position_snapshot_age_ms=0,
        seconds_to_expiry=30.0,
    )
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "rejected"
    assert "close_window" in result.reason
    assert len(submit_log) == 0


@pytest.mark.asyncio
async def test_feed_disconnect_then_retry_succeeds():
    """A timeout/disconnect on the first submit is retried; exactly one exit fills."""
    calls = {"count": 0}

    async def flaky_submit(intent):
        calls["count"] += 1
        if calls["count"] == 1:
            raise asyncio.TimeoutError("feed disconnect")
        return _FakeOrderResult("filled_live", order_id="order-2")

    fetch, open, cancel, _, pos_state, cancel_log, submit_log = _actor(position=1000)
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=flaky_submit,
        retry_backoff_seconds=0.0,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "submitted"
    assert result.order_result.order_id == "order-2"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_position_discrepancy_uses_authoritative_exchange_size():
    """Local candidate says 10 contracts but exchange reports 5; close only 5."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=500, submit_result=_FakeOrderResult("filled_live", order_id="order-1")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    # Candidate built when the position was 10 contracts; exchange now has 5.
    candidate = _yes_candidate(qty_cc=1000)
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "submitted"
    assert submit_log[-1].count == 5
    assert submit_log[-1].reduce_only is True
    assert submit_log[-1].side == "yes"


@pytest.mark.asyncio
async def test_process_restart_cancels_in_flight_exit():
    """After restart, an open in-flight stop order is cancelled before a new exit."""
    in_flight = SimpleNamespace(
        order_id="inflight-1",
        market_id="KXBTC15M-TEST",
        side="yes",
        action="sell",
    )
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000,
        open_orders=[in_flight],
        submit_result=_FakeOrderResult("filled_live", order_id="order-1"),
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True)
    assert result.status == "submitted"
    assert "inflight-1" in cancel_log
    assert len([i for i in submit_log if i.count == 10]) == 1


@pytest.mark.asyncio
async def test_shadow_mode_logs_intent_without_submission():
    """Shadow run produces the same intent but never calls submit_order."""
    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    # Shadow mode short-circuits before submit: build and validate only.
    result = await reducer.reduce(candidate, force=True, shadow_mode=True)
    assert result.status == "shadow"
    assert result.intent is not None
    assert result.intent.count == 10
    assert result.intent.reduce_only is True
    assert len(submit_log) == 0
    assert len(cancel_log) == 0


@pytest.mark.asyncio
async def test_stop_candidate_inherits_entry_parentage(monkeypatch):
    """Exit intent carries the originating entry's fill, order, intent and decision IDs."""
    from merid.event_venues.kalshi.position_cache import CachedPosition

    cached = CachedPosition(
        market_id="KXBTC15M-TEST",
        agent_id="test",
        contracts=10,
        side="yes",
        thesis_side="yes",
        avg_price_cents=50,
        entry_fill_id="fill-123",
        entry_order_id="order-123",
        entry_intent_id="intent-123",
        decision_id="dec-123",
        entry_signal_id="sig-123",
    )

    class FakeCache:
        def get_position(self, ticker):
            return cached

    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        lambda: FakeCache(),
    )

    fetch, open, cancel, submit, pos_state, cancel_log, submit_log = _actor(
        position=1000, submit_result=_FakeOrderResult("filled_live")
    )
    reducer = StopCandidateExecutionReducer(
        fetch_position=fetch,
        get_open_orders=open,
        cancel_order=cancel,
        submit_order=submit,
    )
    candidate = _yes_candidate()
    result = await reducer.reduce(candidate, force=True, shadow_mode=True)
    assert result.status == "shadow"
    intent = result.intent
    assert intent.parentage_status == "CANONICAL_FILL"
    assert intent.parent_entry_fill_id == "fill-123"
    assert intent.parent_entry_order_id == "order-123"
    assert intent.parent_entry_intent_id == "intent-123"
    assert intent.parent_decision_id == "dec-123"
    assert intent.parent_entry_signal_id == "sig-123"
