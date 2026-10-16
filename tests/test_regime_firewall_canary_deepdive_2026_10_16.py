"""Regression tests for the 2026-10-16 regime/firewall/canary deep-dive audit.

Live evidence behind each fix:

* Regime: 507 label flips in 24h (~57/hr); *_CONFIRMED median dwell 22s, 73%
  died <60s; direct RALLY->SELL_OFF flips observed.  Fixes: confirm_ticks
  2->4, CONFIRMED never flips directly to the opposite CONFIRMED, and a young
  CONFIRMED demotes to same-side WEAKENING instead of collapsing to NEUTRAL.

* Firewall: book ts<=0 read as book_age_ms=0 (fresh) — a fail-open staleness
  hole; VWAP always ROUND_CEILING overstated sell-side executability;
  forced exits hard-rejected on insufficient depth instead of partial-closing;
  consume_decision never consumed (unbounded map).

* Monitor: DOGE take_profit wedged durable SUBMITTING >15min — the sweeper
  only covered INTENT_PERSISTED, and a failed dispatch callback cleared the
  in-memory flight while leaving the durable SUBMITTING record orphaned.

* Canary: canary_taker/canary_maker documented as 1-contract probes but
  inherited MERID_BOUNDED_LANE_MAX_CONTRACTS=3.

* Envelope: 163 trailing_stop exits deferred at mean +3.0c locked gain —
  below the 10c profit arm but a ratcheted win nonetheless.

* Telemetry: EDGE_BELOW_DYNAMIC_THRESHOLD compared best_ev against the
  cross-side minimum bound -> false-positive violations.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.settlement_aligned_exit import (
    exit_envelope_allows,
)
from merid.event_venues.kalshi.execution_risk_firewall import (
    ExecutionRiskFirewall,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent
from merid.prediction import directional_regime as dr


# ---------------------------------------------------------------- regime ---
# Label churn hysteresis.


class _Slice:
    def __init__(self, r60: Optional[float], eligible: bool = True):
        self.rti_returns = {"rti_return_60s": r60}
        self.rti_execution_eligible = eligible


class _Snap:
    def __init__(self, r60_map):
        self.by_asset = {a: _Slice(v) for a, v in r60_map.items()}


_RALLY_SNAP = _Snap(
    {a: v for a, v in zip(dr._REGIME_ASSETS, [0.001, 0.002, 0.001, 0.0005, -0.001])}
    if len(dr._REGIME_ASSETS) == 5
    else {a: 0.001 for a in dr._REGIME_ASSETS}
)
_DUMP_SNAP = _Snap(
    {a: v for a, v in zip(dr._REGIME_ASSETS, [-0.001, -0.002, -0.001, -0.0005, 0.001])}
    if len(dr._REGIME_ASSETS) == 5
    else {a: -0.001 for a in dr._REGIME_ASSETS}
)
_MIXED_SNAP = _Snap({a: 0.0 for a in dr._REGIME_ASSETS})


@pytest.fixture
def regime_state(tmp_path, monkeypatch):
    p = tmp_path / "regime_state.json"
    monkeypatch.setenv("MERID_DIRECTIONAL_REGIME_STATE_PATH", str(p))
    monkeypatch.setenv("MERID_REGIME_MIN_TICK_S", "1.0")
    dr._regime_cache = (0.0, {})
    yield str(p)
    dr._regime_cache = (0.0, {})


def _seed_regime(path: str, **over: Any) -> None:
    st = {
        "epoch": dr.POLICY_EPOCH,
        "score": 0.0,
        "up_ticks": 0,
        "down_ticks": 0,
        "label": "NEUTRAL",
        "last_ts": 0.0,
        "label_since_ts": 0.0,
    }
    st.update(over)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    dr._regime_cache = (0.0, {})


def test_confirm_ticks_default_is_four(monkeypatch):
    """2026-10-16 churn audit: 2 aligned ticks (~3s) confirmed mostly noise —
    median CONFIRMED dwell was 22s.  The bar is ~6s of unbroken alignment."""
    monkeypatch.delenv("MERID_REGIME_CONFIRM_TICKS", raising=False)
    assert dr._regime_confirm_ticks() == 4


def test_no_direct_opposite_confirmed_flip(regime_state):
    """SELL_OFF_CONFIRMED -> RALLY_CONFIRMED in one tick is forbidden: a hard
    reversal must decay through the same-side WEAKENING first."""
    t = 1_000_100.0
    _seed_regime(
        regime_state,
        label="SELL_OFF_CONFIRMED",
        score=0.24,          # EMA next tick: 0.6*0.24 + 0.4*1 = 0.544 >= confirm
        up_ticks=3,          # +1 aligned tick reaches the confirm chain
        down_ticks=0,
        label_since_ts=t - 100.0,
        last_ts=t - 5.0,
    )
    reg = dr.compute_directional_regime(_RALLY_SNAP, now=t)
    assert reg.label == "SELL_OFF_WEAKENING", reg.label


def test_young_confirmed_demotes_to_weakening_not_neutral(regime_state):
    """A CONFIRMED younger than MERID_REGIME_MIN_DWELL_S cannot collapse
    straight to NEUTRAL — it demotes to same-side WEAKENING (blocks release
    immediately, trend memory survives)."""
    t = 1_000_200.0
    _seed_regime(
        regime_state,
        label="SELL_OFF_CONFIRMED",
        score=-0.10,         # neutral tick -> score -0.06 > -weaken -> NEUTRAL candidate
        up_ticks=0,
        down_ticks=0,
        label_since_ts=t - 10.0,   # 10s < 30s dwell
        last_ts=t - 5.0,
    )
    reg = dr.compute_directional_regime(_MIXED_SNAP, now=t)
    assert reg.label == "SELL_OFF_WEAKENING", reg.label


def test_old_confirmed_may_decay_to_neutral(regime_state):
    """Past the dwell window the decay path is unchanged."""
    t = 1_000_200.0
    _seed_regime(
        regime_state,
        label="SELL_OFF_CONFIRMED",
        score=-0.10,
        up_ticks=0,
        down_ticks=0,
        label_since_ts=t - 90.0,   # 90s > 30s dwell
        last_ts=t - 5.0,
    )
    reg = dr.compute_directional_regime(_MIXED_SNAP, now=t)
    assert reg.label == "NEUTRAL", reg.label


def test_same_side_weakening_always_allowed(regime_state):
    """CONFIRMED -> own WEAKENING is the decay path itself — dwell must not
    trap a weakening label inside CONFIRMED (blocks would stick)."""
    t = 1_000_300.0
    _seed_regime(
        regime_state,
        label="SELL_OFF_CONFIRMED",
        score=-0.30,
        up_ticks=0,
        down_ticks=2,        # 3 < confirm(4) -> not re-confirmed; score <= -weaken
        label_since_ts=t - 5.0,
        last_ts=t - 5.0,
    )
    reg = dr.compute_directional_regime(_DUMP_SNAP, now=t)
    assert reg.label == "SELL_OFF_WEAKENING", reg.label


def test_dwell_env_override(monkeypatch):
    monkeypatch.setenv("MERID_REGIME_MIN_DWELL_S", "120")
    assert dr._regime_min_dwell_s() == 120.0


# -------------------------------------------------------------- firewall ---


@pytest.fixture(autouse=True)
def _reset_firewall():
    ExecutionRiskFirewall.reset_for_test()
    yield
    ExecutionRiskFirewall.reset_for_test()


@pytest.fixture(autouse=True)
def _clean_patches():
    yield
    patch.stopall()


def _canonical(**over: Any) -> CanonicalOrderIntent:
    defaults = {
        "market_ticker": "KXBTC15M-26OCT152115-15",
        "contract": "no",
        "action": "sell",
        "purpose": "close",
        "qty_cc": 191,
        "limit_cents": 44,
        "strategy_signal": "exit",
        "expected_position_before": -191,
        "expected_position_after": 0,
        "expected_realized_pnl_cents": 0,
        "reason": "hard_stop",
        "allow_short": False,
        "intent_id": "intent_fw_deepdive",
        "client_order_id": "stopcand_fw_001",
        "kalshi_side": "SELL_NO",
        "fee_cents": 1,
        "reduce_only": True,
        "time_in_force": "ioc",
    }
    defaults.update(over)
    return CanonicalOrderIntent(**defaults)


def _mock_position_and_book(
    no_bids: List[Tuple[int, int]],
    yes_exposure_cc: int = -191,
    avg_price_cents: int = 78,
    side: str = "no",
    book_ts: Optional[float] = None,
) -> None:
    cache = MagicMock()
    pos = MagicMock()
    pos.quantity_cc = abs(yes_exposure_cc)
    pos.avg_price_cents = avg_price_cents
    pos.entry_fill_id = "fill_entry_1"
    pos.entry_signal_id = None
    pos.last_update_ts = time.time()
    pos._yes_exposure.return_value = yes_exposure_cc
    cache.get_position.return_value = pos
    cache._last_exchange_sync_time = {}

    async def _fetch(ticker, timeout=None, fallback_to_cache=None):
        return (yes_exposure_cc, avg_price_cents, side)

    state = MagicMock()
    state.book = None
    state.yes_bids = [(55, 1000)]
    state.no_bids = no_bids
    state.best_bid_cents = 55
    state.best_ask_cents = 57
    state.best_no_bid_cents = no_bids[0][0]
    state.best_no_ask_cents = 100 - 55
    state.last_book_update_ts = (
        time.monotonic() if book_ts is None else book_ts
    )
    state.book_sequence = 7
    state.status = "open"
    state.seconds_to_expiry = 500.0

    store = MagicMock()
    store.get.return_value = state
    store.get_unified.return_value = None

    patch(
        "merid.event_venues.kalshi.order_intent_contract"
        ".fetch_fresh_signed_yes_exposure",
        _fetch,
    ).start()
    patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        return_value=cache,
    ).start()
    patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ).start()


@pytest.mark.asyncio
async def test_book_ts_zero_fails_closed_as_stale():
    """A book with ts<=0 is UNKNOWN-stale, not fresh — the old code stamped
    book_age_ms=0 and passed the staleness gate on an uninitialized book."""
    _mock_position_and_book(
        no_bids=[(45, 1000)], book_ts=0.0
    )
    canonical = _canonical(limit_cents=40)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status in ("rejected", "observe_only")
    assert "stale_book" in decision.reason


@pytest.mark.asyncio
async def test_sell_vwap_floor_rounding():
    """Sell-side VWAP must round DOWN (conservative proceeds).  Book
    1ct@43 + 0.91ct@40 -> true vwap 41.57; CEIL reported 42 and a sell
    limit=42 read executable when the real average was not."""
    _mock_position_and_book(no_bids=[(43, 1), (40, 100)])
    canonical = _canonical(reason="take_profit", limit_cents=42)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status in ("rejected", "observe_only")
    assert "limit_not_executable" in decision.reason
    assert "vwap=41" in decision.reason


@pytest.mark.asyncio
async def test_forced_exit_resizes_to_available_depth():
    """A forced/safety exit wider than the book must partial-close at the
    visible depth, not reject outright — the residual re-triggers next tick."""
    _mock_position_and_book(
        no_bids=[(45, 1), (44, 1)], yes_exposure_cc=-500
    )  # 2 contracts depth vs 5 requested
    canonical = _canonical(qty_cc=500, expected_position_before=-500)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status == "approved", decision.reason
    assert decision.qty_cc == 200


@pytest.mark.asyncio
async def test_discretionary_exit_still_rejects_on_thin_depth():
    """Non-forced exits keep the hard insufficient_depth reject."""
    _mock_position_and_book(
        no_bids=[(45, 1), (44, 1)], yes_exposure_cc=-500
    )
    canonical = _canonical(reason="take_profit", qty_cc=500,
                           expected_position_before=-500)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status in ("rejected", "observe_only")
    assert "insufficient_depth" in decision.reason


@pytest.mark.asyncio
async def test_consume_decision_actually_consumes():
    """consume_decision must pop — the token map is not a lookup table."""
    _mock_position_and_book(no_bids=[(45, 1000)])
    canonical = _canonical(limit_cents=43)
    fw = ExecutionRiskFirewall.get_instance()
    decision = await fw.validate_exit(canonical)
    assert decision.status == "approved"
    coid = decision.client_order_id
    assert fw.consume_decision(coid) is not None
    assert fw.consume_decision(coid) is None


# --------------------------------------------------------------- monitor ---


def test_sweep_schedules_reconcile_for_stale_submitting(tmp_path):
    """The DOGE wedge: durable SUBMITTING with the callback/task dead must be
    pushed through _reconcile_exit_intent, not left nonterminal forever."""
    from merid.position_management.position_monitor import PositionMonitor
    from merid.event_venues.kalshi.order_attempt_store import (
        ExitOrderAttemptState,
    )

    mon = object.__new__(PositionMonitor)
    mon._lock = __import__("threading").Lock()
    mon._open_positions = {}
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._loop = None

    record = MagicMock()
    record.state = ExitOrderAttemptState.SUBMITTING.value
    record.created_at = time.time() - 400.0
    record.position_key = "pos_doge_1"
    record.client_order_id = "exit_5b5c07cede14496c57f4"
    record.attempt_id = "att_doge_1"
    record.payload_json = "{}"

    store = MagicMock()
    store.list_nonterminal_exit_attempts.return_value = [record]

    scheduled = []
    mon._schedule_exit_reconcile = (
        lambda pid, coid: scheduled.append((pid, coid))
    )

    with patch(
        "merid.position_management.position_monitor.OrderAttemptStore",
        return_value=store,
    ):
        swept = mon._sweep_stale_exit_obligations()

    assert swept == 1
    assert scheduled == [("pos_doge_1", "exit_5b5c07cede14496c57f4")]
    # The wedge is reconciled, not blindly terminalized — venue truth is
    # unproven for a SUBMITTING record.
    store.transition_exit_attempt.assert_not_called()


def test_sweep_leaves_fresh_submitting_alone(tmp_path):
    from merid.position_management.position_monitor import PositionMonitor
    from merid.event_venues.kalshi.order_attempt_store import (
        ExitOrderAttemptState,
    )

    mon = object.__new__(PositionMonitor)
    mon._lock = __import__("threading").Lock()
    mon._open_positions = {}
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._loop = None
    mon._swept_reconcile_at = {}

    record = MagicMock()
    record.state = ExitOrderAttemptState.SUBMITTING.value
    record.created_at = time.time() - 10.0   # inside the reconcile horizon
    record.position_key = "pos_fresh"
    record.client_order_id = "exit_fresh"
    record.attempt_id = "att_fresh"
    record.payload_json = "{}"

    store = MagicMock()
    store.list_nonterminal_exit_attempts.return_value = [record]

    scheduled = []
    mon._schedule_exit_reconcile = lambda pid, coid: scheduled.append((pid, coid))

    with patch(
        "merid.position_management.position_monitor.OrderAttemptStore",
        return_value=store,
    ):
        swept = mon._sweep_stale_exit_obligations()

    assert swept == 0
    assert scheduled == []


def test_mark_reconciled_uses_caller_coid_when_maps_empty(tmp_path):
    """Observed live 2026-10-16: durable attempts older than the 30d rehydrate
    lookback are swept into _reconcile_exit_intent, which terminalizes the
    intent — but _mark_exit_intent_reconciled derived the coid only from the
    in-memory maps.  With no rehydrated entry the coid was None and the
    durable attempt stayed RESOLVING_ON_EXCHANGE forever, re-swept every
    throttle interval."""
    from merid.position_management.position_monitor import PositionMonitor
    from merid.event_venues.kalshi.order_attempt_store import (
        ExitOrderAttemptState,
    )

    mon = object.__new__(PositionMonitor)
    mon._lock = __import__("threading").Lock()
    mon._open_positions = {}
    # No rehydrated in-flight entry — maps are empty.
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._save_exit_intent_in_flight = lambda: None

    record = MagicMock()
    record.attempt_id = "att_old_1"
    store = MagicMock()
    store.get_exit_attempt_by_client_order_id.return_value = record

    with patch(
        "merid.position_management.position_monitor.OrderAttemptStore",
        return_value=store,
    ):
        mon._mark_exit_intent_reconciled(
            "pos_gone_1", "position_closed", "exit_deadbeef"
        )

    store.get_exit_attempt_by_client_order_id.assert_called_once_with(
        "exit_deadbeef"
    )
    store.transition_exit_attempt.assert_called_once()
    _args, kwargs = store.transition_exit_attempt.call_args
    assert kwargs["attempt_id"] == "att_old_1"
    assert kwargs["new_state"] == ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value


def test_mark_reconciled_without_coid_and_empty_maps_is_noop(tmp_path):
    """With no caller coid and no in-memory entry there is nothing to
    terminalize — must not touch the store."""
    from merid.position_management.position_monitor import PositionMonitor

    mon = object.__new__(PositionMonitor)
    mon._lock = __import__("threading").Lock()
    mon._open_positions = {}
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._save_exit_intent_in_flight = lambda: None

    store = MagicMock()
    with patch(
        "merid.position_management.position_monitor.OrderAttemptStore",
        return_value=store,
    ):
        mon._mark_exit_intent_reconciled("pos_x", "position_closed")

    store.transition_exit_attempt.assert_not_called()


# ---------------------------------------------------------------- canary ---


def test_canary_lane_cap_default_one(monkeypatch):
    monkeypatch.delenv("MERID_CANARY_LANE_MAX_CONTRACTS", raising=False)
    from merid.prediction.agent_grid_15m import _canary_lane_max_contracts
    assert _canary_lane_max_contracts() == 1.0


def test_canary_lane_cap_ignores_raised_bounded_cap(monkeypatch):
    """MERID_BOUNDED_LANE_MAX_CONTRACTS=3 must not lift the canary probe."""
    monkeypatch.setenv("MERID_BOUNDED_LANE_MAX_CONTRACTS", "3")
    from merid.prediction.agent_grid_15m import (
        _bounded_lane_max_contracts,
        _canary_lane_max_contracts,
    )
    assert _bounded_lane_max_contracts() == 3.0
    assert min(
        _bounded_lane_max_contracts(), _canary_lane_max_contracts()
    ) == 1.0


def test_canary_lane_cap_hard_ceiling(monkeypatch):
    """Even an explicit override is clamped — canary accounting prices a
    probe, not a sized position."""
    monkeypatch.setenv("MERID_CANARY_LANE_MAX_CONTRACTS", "50")
    from merid.prediction.agent_grid_15m import _canary_lane_max_contracts
    assert _canary_lane_max_contracts() == 3.0


# -------------------------------------------------------------- envelope ---


def test_trailing_stop_locks_small_gain():
    """163 live deferrals averaged +3.0c — a ratcheted win must not be held
    hostage below the 10c take-profit arm."""
    ok, detail = exit_envelope_allows(
        "trailing_stop", 55, 300.0, entry_price_cents=52
    )
    assert ok, detail
    assert "lock_ok=True" in detail


def test_trailing_stop_loser_still_gated():
    """A trail that retraced through cost stays gated — settlement reversion
    evidence genuinely applies to losing exits."""
    ok, _ = exit_envelope_allows(
        "trailing_stop", 45, 300.0, entry_price_cents=52
    )
    assert not ok


def test_trailing_stop_arm_env_override(monkeypatch):
    monkeypatch.setenv("MERID_EXIT_ENVELOPE_TRAIL_LOCK_C", "5")
    ok, _ = exit_envelope_allows(
        "trailing_stop", 55, 300.0, entry_price_cents=52
    )
    assert not ok   # +3c < raised 5c trail floor


def test_take_profit_keeps_full_lock_threshold():
    """The trail override must not leak onto take_profit (+3c still defers)."""
    ok, _ = exit_envelope_allows(
        "take_profit", 55, 300.0, entry_price_cents=52
    )
    assert not ok


# ------------------------------------------------------------- telemetry ---


def test_edge_below_threshold_uses_best_side_bound():
    """False-positive: best_ev cleared the cross-side MINIMUM bound while
    staying under the best side's OWN bound — not a violation."""
    from merid.prediction.decision_telemetry import _validate_record_invariants

    rec = {
        "type": "decision_record",
        "terminal_code": "EDGE_BELOW_DYNAMIC_THRESHOLD",
        "best_executable_ev_cents": 4.7,
        "yes_ev_net_cents": 4.7,
        "no_ev_net_cents": -1.0,
        "best_required_edge_cents": 2.0,          # min across sides
        "required_edge_yes_cents": 8.0,           # best side's own bound
        "edge_shortfall_cents": 3.3,
    }
    assert _validate_record_invariants(rec) == []


def test_edge_below_threshold_still_flags_real_violation():
    """best_ev clearing ITS OWN bound under the code is a real violation."""
    from merid.prediction.decision_telemetry import _validate_record_invariants

    rec = {
        "type": "decision_record",
        "terminal_code": "EDGE_BELOW_DYNAMIC_THRESHOLD",
        "best_executable_ev_cents": 9.0,
        "yes_ev_net_cents": 9.0,
        "no_ev_net_cents": -1.0,
        "best_required_edge_cents": 2.0,
        "required_edge_yes_cents": 5.0,
        "edge_shortfall_cents": 0.0,
    }
    violations = _validate_record_invariants(rec)
    assert any("EDGE_BELOW_DYNAMIC_THRESHOLD" in v for v in violations)
