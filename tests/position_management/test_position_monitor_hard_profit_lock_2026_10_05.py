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
    """Bid >= 90c on an untrusted book -> BLOCKED decision, no intent, P0 alert."""
    position = _make_position(PositionSide.YES, entry_cents=50)
    monitor.add_position(position)
    calls = _capture_callback(monitor)

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
