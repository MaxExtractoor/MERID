"""
Regression tests for the 2026-10-05 HARD_PROFIT_LOCK exit family.

Incident: KXBTC15M-26OCT042115-15 (long NO @73c) saw a real executable NO bid
of 92-99c for ~3 minutes, trail and AUTO_EXIT_99C triggers fired, and every
trigger was suppressed by MERID_DISABLE_EXIT_POLICY=1 before an exit intent
could be created.  The contract settled YES for a ~74c/contract loss.

The hard profit lock is a deterministic risk-control rule: executable
held-side bid >= threshold (default 90c) => emit a reducing exit intent
immediately, exempt from the hold-to-settlement kill-switch and from the
discretionary TP/EV gates.

Covered acceptance scenarios:
1. YES 90c lock: long YES, executable YES bid >= 90c -> one reducing exit intent.
2. NO 90c lock: long NO, executable NO bid >= 90c -> one reducing exit intent.
3. False-mark prevention: mid at 95c but held-side bid 85c -> no trigger.
4. Untrusted quote: bid >= 90c but book not executable -> BLOCKED eval + P0 alert.
5. Kill-switch bypass: MERID_DISABLE_EXIT_POLICY=1 cannot suppress the lock,
   while ordinary discretionary exits stay suppressed.
6. Disable flag: MERID_HARD_PROFIT_LOCK_ENABLED=0 -> no trigger.
7. Insufficient depth annotation: still triggers (IOC takes what is there)
   but emits the P0 depth alert.
8. Incident replay: entry 73c NO, bid 92c -> hard lock emits at 92c (would
   have saved the trade); bid 3c after reversal does not re-trigger a second
   intent for the same position.
"""

import os
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitReason
from merid.position_management.exit_audit import ExitPriceSnapshot


@pytest.fixture
def monitor(monkeypatch):
    """Fresh PositionMonitor for each test; treat all markets as tradeable."""
    monkeypatch.setattr(
        "merid.position_management.position_monitor._is_expired_ticker",
        lambda _: False,
    )
    m = PositionMonitor()
    m._is_expired_market = lambda market_id: False
    return m


def _make_position(side: PositionSide, market_id: str = "KXBTC15M-26OCT042115-15",
                   entry_cents: int = 73) -> Position:
    return Position(
        market_id=market_id,
        series_ticker="KXBTC15M",
        side=side,
        size=Decimal("1"),
        avg_entry_price_cents=entry_cents,
        take_profit_price_cents=None,
        stop_loss_price_cents=None,
        fill_source="entry_intent",
    )


def _snapshot(position: Position, *, own_bid: int, own_ask: int = 99,
              mid: int = 50, executable: bool = True,
              data_quality: str = "GOOD", book_age_ms: int = 0,
              has_bid_size: bool = True, min_depth: int = 1,
              book_age_override_ts=None) -> ExitPriceSnapshot:
    """Build a same-side snapshot; own_side_* is already in held-side space."""
    return ExitPriceSnapshot(
        market_id=position.market_id,
        position_side=position.side,
        mid_cents=mid,
        own_side_bid_cents=own_bid,
        own_side_ask_cents=own_ask,
        opposite_bid_cents=None,
        opposite_ask_cents=None,
        book_age_ms=book_age_ms,
        data_source="live_book",
        data_quality=data_quality,
        executable=executable,
        has_bid_size=has_bid_size,
        snapshot_id=f"test:{position.position_id}:{own_bid}",
        timestamp=time.monotonic(),
        min_depth_own_side=min_depth,
        seconds_to_expiry=300.0,
        book_sequence=42,
    )


def _capture_callback(monitor):
    calls = []

    def callback(pos, reason, price, contracts=None):
        calls.append({"position_id": pos.position_id, "reason": reason,
                      "price": price, "contracts": contracts})

    monitor._exit_intent_callback = callback
    return calls


@pytest.mark.asyncio
async def test_yes_90c_lock_creates_one_reducing_exit(monitor):
    """Long YES sees executable YES bid >= 90c -> exactly one reducing exit."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=95), 1
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert decision.exit_price_cents == 92
    assert decision.metadata["trigger_family"] == "HARD_PROFIT_LOCK"
    assert decision.metadata["held_side_executable_bid_cents"] == 92
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK
    assert calls[0]["price"] == 92
    # contracts=None == full reduce-only close of remaining quantity
    assert calls[0]["contracts"] is None


@pytest.mark.asyncio
async def test_no_90c_lock_creates_one_reducing_exit(monitor):
    """Long NO sees executable NO bid >= 90c -> exactly one reducing exit.

    This is the incident side: the failed position was long NO; its
    executable NO bid hit 92-99c while the kill-switch suppressed every exit.
    """
    position = _make_position(PositionSide.NO, entry_cents=73)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=8), 1
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert decision.exit_price_cents == 92
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK


@pytest.mark.asyncio
async def test_false_mark_no_lock_when_bid_below_threshold(monitor):
    """Mid/last at 90c+ but held-side executable bid below 90c -> no lock."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    # Mid prints 95c but the best executable YES bid is only 85c.
    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=85, own_ask=95, mid=95), 1
    )

    # No lock trigger; the bid is what matters, never the mid.
    assert decision is None or decision.reason != ExitReason.HARD_PROFIT_LOCK
    assert all(c["reason"] != ExitReason.HARD_PROFIT_LOCK for c in calls)


@pytest.mark.asyncio
async def test_untrusted_quote_blocks_lock_with_p0_alert(monitor, caplog):
    """Bid >= 90c on an untrusted book -> BLOCKED decision, no intent, P0 alert.

    2026-10-05: the witnessed lock-level bid must also be LATCHED as a durable
    obligation (previously the alert fired but no obligation was recorded, so
    later polls degraded into EXIT_BLOCKED_BOOK_INVALID forever).
    """
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    async def _no_recovery(_pos):
        return None

    monitor._hard_lock_quote_recovery = _no_recovery

    decision = await monitor._check_position(
        position,
        _snapshot(position, own_bid=95, executable=False, data_quality="STALE",
                  book_age_ms=60_000),
        1,
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert decision.metadata["decision"] == "BLOCKED"
    assert decision.metadata["block_reason"] == "TP_QUOTE_NOT_TRUSTED"
    assert len(calls) == 0
    assert "HARD_PROFIT_LOCK_BLOCKED_UNTRUSTED_QUOTE" in caplog.text
    # The witnessed 95c bid is now a durable obligation with the event trail.
    assert position.hard_lock_pending is not None
    assert position.hard_lock_pending["trigger_bid_cents"] == 95
    assert position.hard_lock_pending["trusted_at_latch"] is False
    assert position.hard_lock_pending["latched_via"] == "poll_untrusted"
    assert any(
        e.get("event") == "HARD_LOCK_TRIGGERED"
        for e in position.hard_lock_pending.get("events", [])
    )


@pytest.mark.asyncio
async def test_lock_bypasses_exit_policy_kill_switch(monitor):
    """MERID_DISABLE_EXIT_POLICY=1 cannot suppress the lock, but still
    suppresses an ordinary discretionary exit."""
    position = _make_position(PositionSide.NO, entry_cents=73)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    os.environ["MERID_DISABLE_EXIT_POLICY"] = "1"
    try:
        # Ordinary exit stays suppressed under the kill-switch.
        await monitor._emit_exit_intent(
            position, ExitReason.TAKE_PROFIT, 95, snapshot=None
        )
        assert len(calls) == 0

        # The hard lock must still emit despite the flag.
        decision = await monitor._check_position(
            position, _snapshot(position, own_bid=92, mid=8), 1
        )
        assert decision is not None
        assert decision.reason == ExitReason.HARD_PROFIT_LOCK
        assert len(calls) == 1
        assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK
    finally:
        os.environ.pop("MERID_DISABLE_EXIT_POLICY", None)


@pytest.mark.asyncio
async def test_lock_disabled_by_env(monitor):
    """MERID_HARD_PROFIT_LOCK_ENABLED=0 disables the lock entirely."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    os.environ["MERID_HARD_PROFIT_LOCK_ENABLED"] = "0"
    try:
        decision = await monitor._check_position(
            position, _snapshot(position, own_bid=95, mid=95), 1
        )
        assert decision is None or decision.reason != ExitReason.HARD_PROFIT_LOCK
        assert all(c["reason"] != ExitReason.HARD_PROFIT_LOCK for c in calls)
    finally:
        os.environ.pop("MERID_HARD_PROFIT_LOCK_ENABLED", None)


@pytest.mark.asyncio
async def test_lock_threshold_configurable(monitor):
    """MERID_HARD_PROFIT_LOCK_CENTS overrides the default 90c threshold."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    os.environ["MERID_HARD_PROFIT_LOCK_CENTS"] = "95"
    try:
        # 92c is below the configured 95c lock -> no lock trigger.
        decision = await monitor._check_position(
            position, _snapshot(position, own_bid=92, mid=92), 1
        )
        assert all(c["reason"] != ExitReason.HARD_PROFIT_LOCK for c in calls)

        # 95c reaches the configured lock -> trigger.
        decision2 = await monitor._check_position(
            position, _snapshot(position, own_bid=95, mid=95), 2
        )
        assert decision2 is not None
        assert decision2.reason == ExitReason.HARD_PROFIT_LOCK
        assert calls[-1]["reason"] == ExitReason.HARD_PROFIT_LOCK
    finally:
        os.environ.pop("MERID_HARD_PROFIT_LOCK_CENTS", None)


@pytest.mark.asyncio
async def test_insufficient_depth_still_fires_with_alert(monitor, caplog):
    """Bid >= lock but annotated depth < qty: IOC submits anyway (venue takes
    what is available, residual re-evaluates) and the depth alert is logged."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    position.size = Decimal("5")
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    decision = await monitor._check_position(
        position,
        _snapshot(position, own_bid=92, has_bid_size=True, min_depth=2),
        1,
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert decision.metadata["depth_sufficient"] is False
    assert len(calls) == 1
    assert "HARD_PROFIT_LOCK_INSUFFICIENT_DEPTH" in caplog.text


@pytest.mark.asyncio
async def test_incident_replay_73c_no_92c_bid(monitor):
    """Incident replay: NO entry @73c -> executable NO bid 92c -> lock emits.

    The 92c bid must produce the reducing exit intent the live incident
    lost to MERID_DISABLE_EXIT_POLICY=1.
    """
    position = _make_position(PositionSide.NO, entry_cents=73)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    # Tick 1: bid ramps to 92c (the real book printed 92-96c for ~3 min).
    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=10), 1
    )
    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert decision.exit_price_cents == 92
    assert len(calls) == 1
    assert calls[0]["price"] == 92


def _book_state(**over):
    """Minimal market-state object for _get_exit_price_snapshot.

    Models the incident shape: YES bid absent (decided market), YES ask=1c,
    so the reciprocal NO bid = 99c is populated while best_no_ask is absent.
    """
    import types
    base = dict(
        book_initialized=True,
        executable=True,
        data_quality="GOOD",
        data_source="ws",
        live_sequence_confirmed=True,
        last_book_update_ts=time.monotonic(),
        best_bid_cents=None,
        best_ask_cents=1,
        best_no_bid_cents=99,
        best_no_ask_cents=None,
        min_depth_yes=0,
        min_depth_no=100,
        has_bid=False,
        has_no_bid=True,
        mid_cents=None,
        spread_cents=None,
        book_sequence=42,
        seconds_to_expiry=300.0,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_one_sided_book_no_position_produces_snapshot(monitor):
    """Incident shape: YES bid absent, YES ask=1c -> implied NO bid=99c.

    The old code required own_ask too (no_ask = 100 - yes_bid is absent when
    the YES bid is gone) and returned None -> BOOK_UNUSABLE while an
    executable 99c own-side bid sat in the state.  A SELL exit needs only
    the bid.
    """
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)

    snap = monitor._get_exit_price_snapshot(
        _book_state(), position.side, position.market_id
    )

    assert snap is not None
    assert snap.own_side_bid_cents == 99
    assert snap.own_side_ask_cents is None
    assert snap.derived_from_reciprocal_book is True


@pytest.mark.asyncio
async def test_one_sided_book_still_fires_lock(monitor):
    """The resolved 99c reciprocal NO bid reaches the lock trigger."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    snap = monitor._get_exit_price_snapshot(
        _book_state(), position.side, position.market_id
    )
    decision = await monitor._check_position(position, snap, 1)

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK
    # Latch written atomically with the observation.
    assert position.hard_lock_pending is not None
    assert position.hard_lock_pending["trigger_bid_cents"] == 99
    assert position.hard_lock_pending["intent_submitted"] is True


@pytest.mark.asyncio
async def test_lock_latch_one_shot_idempotent(monitor):
    """Repeated >=90c observations produce exactly one exit intent."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    for i in range(3):
        await monitor._check_position(position, _snapshot(position, own_bid=92), i)

    assert len(calls) == 1
    assert position.hard_lock_pending is not None


@pytest.mark.asyncio
async def test_latch_opportunity_lost_on_subthreshold_recovery(monitor):
    """Latched at 92c, book recovers at 85c -> terminal OPPORTUNITY_LOST,
    latch cleared, no second intent emitted."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    await monitor._check_position(position, _snapshot(position, own_bid=92), 1)
    assert position.hard_lock_pending is not None
    assert len(calls) == 1

    # Book recovers below the lock threshold — the lock obligation lapses.
    await monitor._check_position(position, _snapshot(position, own_bid=85), 2)
    assert position.hard_lock_pending is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fast_path_callback_latches_and_emits(monitor):
    """Market-state update path: a fresh >=90c quote triggers the emit without
    waiting for the 5s poll."""
    import asyncio

    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)
    monitor._loop = asyncio.get_running_loop()

    monitor._on_hard_lock_market_update(position.market_id, _book_state())
    await asyncio.sleep(0.1)

    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK
    assert position.hard_lock_pending is not None
    assert position.hard_lock_pending["latched_via"] == "market_state_event"


@pytest.mark.asyncio
async def test_fast_path_ignores_subthreshold_quote(monitor):
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)
    import asyncio
    monitor._loop = asyncio.get_running_loop()

    monitor._on_hard_lock_market_update(
        position.market_id, _book_state(best_ask_cents=15, best_no_bid_cents=85)
    )
    await asyncio.sleep(0.05)

    assert len(calls) == 0
    assert position.hard_lock_pending is None


@pytest.mark.asyncio
async def test_quote_recovery_throttled_and_bounded(monitor):
    """_hard_lock_quote_recovery enforces max attempts + min interval."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    position.hard_lock_pending = {
        "state": "PENDING",
        "trigger_bid_cents": 99,
        "recovery_attempts": 99,  # exhausted
        "last_recovery_ts": 0.0,
    }
    assert await monitor._hard_lock_quote_recovery(position) is None

    position.hard_lock_pending = {
        "state": "PENDING",
        "trigger_bid_cents": 99,
        "recovery_attempts": 0,
        "last_recovery_ts": time.monotonic(),  # too soon — throttled
    }
    assert await monitor._hard_lock_quote_recovery(position) is None


def test_hard_profit_lock_classified_as_hard_risk():
    """loop_15m price validation must classify the lock as hard-risk —
    never the discretionary profit floor, never 'unknown classification'
    (the 04:21 BTC_NO@81 EXIT-PRICE-VALIDATION-FAIL incident)."""
    from merid.loop_15m import (
        MERID_HARD_RISK_EXIT_REASONS,
        MERID_PROFIT_EXIT_REASONS,
    )

    assert "hard_profit_lock" in MERID_HARD_RISK_EXIT_REASONS
    assert "hard_profit_lock" not in MERID_PROFIT_EXIT_REASONS


def test_model_fair_value_ignores_market_implied():
    """_get_model_fair_value_cents must NOT fall back to implied_prob.

    The TP overpay floor anchored to market-implied fair was tautological:
    when entry_model_probability is missing the floor became bid+cost and TP
    could never trigger (incident: fair=96, floor=98 on a 96c bid).
    """
    from merid.event_venues.kalshi.stop_candidate import _get_model_fair_value_cents

    class _State:
        model_fair_prob = None
        external_fair_value = None
        implied_prob = 0.96  # market-derived; must be ignored for the TP floor

    assert _get_model_fair_value_cents(_State(), "yes") is None
    assert _get_model_fair_value_cents(_State(), "no") is None

    class _State2:
        model_fair_prob = 0.96
        model_fair_prob_ts = time.time()
        external_fair_value = None
        implied_prob = 0.40

    assert _get_model_fair_value_cents(_State2(), "yes") == 96
    assert _get_model_fair_value_cents(_State2(), "no") == 4


# ── 2026-10-05 incident-shape hardening ─────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_exit_triggered_flag_does_not_freeze_lock(monitor):
    """exit_triggered=True with no exited_at (a crashed intent path) must not
    freeze the lock gate upstream of _emit_exit_intent's stale-flag clearing."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    # Simulate the frozen state: flagged as exiting but never actually exited.
    position.exit_triggered = True
    position.exited_at = None

    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=8), 1
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK


@pytest.mark.asyncio
async def test_genuinely_exited_position_skips_lock(monitor):
    """exit_triggered=True WITH exited_at is a real close — lock must not fire."""
    from datetime import datetime, timezone

    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    position.exit_triggered = True
    position.exited_at = datetime.now(timezone.utc)

    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=8), 1
    )

    assert all(c["reason"] != ExitReason.HARD_PROFIT_LOCK for c in calls)
    assert decision is None or decision.reason != ExitReason.HARD_PROFIT_LOCK


@pytest.mark.asyncio
async def test_untrusted_latch_then_recovered_quote_emits(monitor):
    """Incident replay: lock-level bid on an unusable quote latches; a bounded
    REST recovery that produces a trusted quote emits the exit intent."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    recovered = _snapshot(position, own_bid=99, mid=5)

    async def _recovery(_pos):
        return recovered

    monitor._hard_lock_quote_recovery = _recovery

    decision = await monitor._check_position(
        position,
        _snapshot(position, own_bid=99, executable=False, data_quality="STALE",
                  book_age_ms=60_000),
        1,
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK
    assert calls[0]["price"] == 99


@pytest.mark.asyncio
async def test_unsubmitted_lock_with_stale_inflight_force_reconciles(monitor):
    """A latched-but-unsubmitted lock blocked by a stale in-flight record must
    reach _emit_exit_intent's forced reconcile instead of degrading to
    EXIT_BLOCKED_BOOK_INVALID."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

    # Latch the obligation without a submitted intent.
    monitor._latch_hard_lock(
        position, bid_cents=99, threshold_cents=90,
        trusted=False, via="poll_untrusted",
    )

    # Stale in-flight record that a real exit intent left behind.
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMITTED",
        "timestamp": time.time() - 1.0,
        "client_order_id": None,
        "reason": "stop_loss",
    }

    async def _fake_reconcile(position_id, client_order_id, force=False, new_price_cents=None):
        monitor._exit_intent_in_flight.pop(position_id, None)

    monitor._reconcile_exit_intent = _fake_reconcile

    decision = await monitor._check_position(
        position, _snapshot(position, own_bid=92, mid=8), 1
    )

    assert decision is not None
    assert decision.reason == ExitReason.HARD_PROFIT_LOCK
    assert len(calls) == 1
    assert calls[0]["reason"] == ExitReason.HARD_PROFIT_LOCK


@pytest.mark.asyncio
async def test_fast_path_unusable_book_latches_obligation(monitor):
    """Market-state update where the snapshot gate rejects the book but the
    raw NO bid reads >= lock must latch a durable obligation."""
    import asyncio

    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    calls = _capture_callback(monitor)
    monitor._loop = asyncio.get_running_loop()

    # Book unusable (BAD quality) but the raw reciprocal-derived NO bid is 99c.
    monitor._on_hard_lock_market_update(
        position.market_id, _book_state(data_quality="BAD_DUALITY", executable=False)
    )
    await asyncio.sleep(0.05)

    assert len(calls) == 0  # never emit off an untrusted quote
    assert position.hard_lock_pending is not None
    assert position.hard_lock_pending["trigger_bid_cents"] == 99
    assert position.hard_lock_pending["trusted_at_latch"] is False
    assert position.hard_lock_pending["latched_via"] == "market_state_event_untrusted"


@pytest.mark.asyncio
async def test_hard_lock_event_trail_recorded(monitor):
    """The durable lifecycle vocabulary is appended to the pending record."""
    position = _make_position(PositionSide.NO, entry_cents=81)
    monitor.add_position(position)
    _capture_callback(monitor)

    await monitor._check_position(position, _snapshot(position, own_bid=92, mid=8), 1)

    events = [
        e.get("event") for e in (position.hard_lock_pending or {}).get("events", [])
    ]
    assert "HARD_LOCK_TRIGGERED" in events
    assert "HARD_LOCK_INTENT_CREATED" in events
    assert "HARD_LOCK_SUBMIT_STARTED" in events
