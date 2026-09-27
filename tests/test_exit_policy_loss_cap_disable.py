"""Regression tests for the operator kill switches added 2026-09-27.

MERID_DISABLE_EXIT_POLICY=1  -> position_monitor emits no automatic exit
                                intents (TP/SL/trailing/time/edge/policy) —
                                positions hold to settlement; reduce-only
                                router capability is unaffected.

MERID_DISABLE_LOSS_CAP=1     -> unified_sizing bypasses the UnifiedRiskManager
                                daily/weekly loss throttle so surviving
                                candidates size on cash/exposure/Kelly only.
"""

import asyncio
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _flag_on(monkeypatch, name):
    monkeypatch.setenv(name, "1")


def _flag_off(monkeypatch, name):
    monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Exit policy kill switch
# ---------------------------------------------------------------------------

def _make_monitor(tmp_path=None):
    """Bare PositionMonitor instance (bypasses heavy __init__).

    Wires only the attributes the flag-off emit path reaches before invoking
    the callback: in-flight registry, dedup maps, a lock, and a writable
    persistence path.
    """
    import threading
    from pathlib import Path

    from merid.position_management.position_monitor import PositionMonitor

    mon = PositionMonitor.__new__(PositionMonitor)
    mon._exit_intent_callback = MagicMock(name="exit_intent_callback")
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._recent_exit_submissions = {}
    mon._lock = threading.Lock()
    mon._exit_intent_persistence_path = (
        (tmp_path or Path.cwd()) / "test_exit_intents.json"
    )
    return mon


def _make_position():
    pos = MagicMock(name="position")
    pos.position_id = "KXBTC15M-test-abcdef01"
    pos.market_id = "KXBTC15M-26SEP270100-00"
    # Telemetry fields formatted by _emit_exit_intent (None -> "n/a" paths).
    pos.entry_model_probability = None
    pos.entry_market_probability = None
    pos.take_profit_price_cents = None
    pos.dynamic_tp_target_cents = None
    pos._last_current_edge_pct = None
    pos.unrealized_pnl_cents = 0
    pos.size = 1.0
    pos.edge_decay_confirmations = 0
    pos.avg_entry_price_cents = 37
    pos.entry_fill_price_cents = 37
    pos.time_since_entry_seconds = 12.0
    pos.exit_triggered = False
    pos.exited_at = None
    # Trusted provenance so the quarantine gate doesn't intercept.
    from merid.position_management.position import RiskParamsState

    pos.fill_source = "alpha"
    pos.risk_params_state = RiskParamsState.ORIGINAL_PERSISTED
    pos.risk_params_schema_version = 2
    return pos


def test_exit_intent_suppressed_when_disabled(monkeypatch):
    from merid.position_management.position_monitor import (
        _exit_policy_disabled,
    )
    from merid.position_management.exit_policy import ExitReason

    _flag_on(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    assert _exit_policy_disabled() is True

    mon = _make_monitor()
    asyncio.run(
        mon._emit_exit_intent(_make_position(), ExitReason.TAKE_PROFIT, 70)
    )
    mon._exit_intent_callback.assert_not_called()


def test_exit_intent_suppresses_scale_out_when_disabled(monkeypatch):
    _flag_on(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    mon = _make_monitor()
    mon._emit_scale_out_intent(_make_position(), 1, 70)
    mon._exit_intent_callback.assert_not_called()


def test_exit_intent_emits_when_flag_absent(monkeypatch, tmp_path):
    """With the flag unset the emit path must still reach the callback."""
    from merid.position_management.exit_policy import ExitReason

    _flag_off(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    mon = _make_monitor(tmp_path)
    # The emit path formats a large decision record from the position; stub the
    # builder — this test only proves the flag does NOT block the callback.
    rec = MagicMock()
    rec.to_log_line = lambda: "[EXIT-DECISION] stub"
    mon._build_exit_decision_record = lambda **kw: rec
    pos = _make_position()
    pos.r_multiple = 0.0
    asyncio.run(
        mon._emit_exit_intent(pos, ExitReason.TAKE_PROFIT, 70)
    )
    mon._exit_intent_callback.assert_called_once()


def test_exit_policy_flag_semantics(monkeypatch):
    from merid.position_management.position_monitor import _exit_policy_disabled

    _flag_off(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    assert _exit_policy_disabled() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("MERID_DISABLE_EXIT_POLICY", v)
        assert _exit_policy_disabled() is True, v
    for v in ("0", "false", "off", ""):
        monkeypatch.setenv("MERID_DISABLE_EXIT_POLICY", v)
        assert _exit_policy_disabled() is False, v


# ---------------------------------------------------------------------------
# Loss-cap kill switch
# ---------------------------------------------------------------------------

def _size_kwargs():
    return dict(
        bankroll_usd=Decimal("2.31"),
        price_cents=45,
        asset="BTC",
        model_prob=0.57,
        side="yes",
    )


def test_loss_cap_disabled_bypasses_rm_zero_scale(monkeypatch):
    """With the flag on, a risk manager reporting scale=0 must not zero size."""
    from merid.prediction import unified_sizing

    _flag_on(monkeypatch, "MERID_DISABLE_LOSS_CAP")

    class _CappedRM:
        def get_loss_adjusted_size_scale(self):
            return 0.0

    import merid.risk.unified_risk_manager as urm_mod

    monkeypatch.setattr(
        urm_mod, "get_unified_risk_manager", lambda: _CappedRM(), raising=False
    )

    count, notional, meta = unified_sizing.compute_order_size(**_size_kwargs())
    assert meta.get("reason") != "daily_weekly_loss_cap"
    assert meta.get("reason") != "risk_manager_unavailable"
    assert count > 0, f"expected positive size, got count={count} meta={meta}"


def test_loss_cap_still_blocks_when_flag_absent(monkeypatch):
    """Without the flag the daily/weekly cap still fails closed."""
    from merid.prediction import unified_sizing

    _flag_off(monkeypatch, "MERID_DISABLE_LOSS_CAP")

    class _CappedRM:
        def get_loss_adjusted_size_scale(self):
            return 0.0

    import merid.risk.unified_risk_manager as urm_mod

    monkeypatch.setattr(
        urm_mod, "get_unified_risk_manager", lambda: _CappedRM(), raising=False
    )

    count, notional, meta = unified_sizing.compute_order_size(**_size_kwargs())
    assert count == 0.0
    assert meta.get("reason") == "daily_weekly_loss_cap"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Hold-to-settlement economics: no exit leg exists while the exit policy is
# disabled, so entry EV must be single-leg (entry fee only) in both the
# decision-layer edge math and the router's round-trip cost gate.
# ---------------------------------------------------------------------------

def _make_net_cost_intent(price_cents: int, gross_edge_cents: float, count: float = 1.0):
    """Entry intent whose modeled edge is exactly ``gross_edge_cents`` total."""
    intent = MagicMock(name="intent")
    intent.ticker = "KXTEST-1"
    intent.price_cents = price_cents
    intent.count = count
    intent.count_fp = None
    intent.edge_pct = 1.0  # truthy; superseded by p_selected path below
    intent.p_selected = price_cents / 100.0 + gross_edge_cents / (100.0 * count)
    intent.aggressiveness = 0.0
    intent.reduce_only = False
    intent.side = "buy"
    intent.intent_id = "test-intent"
    intent.client_order_id = "test-coid"
    return intent


def _patch_market_state(monkeypatch, bid_cents: int, ask_cents: int):
    """Feed the gate a fresh, initialized book."""
    import merid.event_venues.kalshi.market_state as ms

    state = MagicMock(name="state")
    state.best_bid_cents = bid_cents
    state.best_ask_cents = ask_cents
    state.book_initialized = True
    state.seconds_to_expiry = 600.0
    from merid.data.ingress_replay import replay_time
    state.last_book_update_wall_ts = replay_time()

    store = MagicMock(name="store")
    store.get = lambda ticker: state
    monkeypatch.setattr(ms, "get_kalshi_market_state_store", lambda: store)


def _is_exit_order_passthrough(monkeypatch):
    import merid.event_venues.kalshi.order_router as orouter
    monkeypatch.setattr(orouter, "_is_exit_order", lambda intent: False)


def test_round_trip_gate_single_leg_when_exits_disabled(monkeypatch):
    """With exits disabled the gate must charge entry-side costs only."""
    import merid.event_venues.kalshi.order_router as orouter
    from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact

    _flag_on(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    _is_exit_order_passthrough(monkeypatch)
    _patch_market_state(monkeypatch, bid_cents=29, ask_cents=31)

    # Pick a gross edge in the gap band: positive under single-leg maker
    # economics, negative under the old 2*maker round-trip assumption.
    maker_fee = float(kalshi_fee_cents_exact(0.30, 1.0, "maker"))
    gross_edge = maker_fee * 1.5  # single-leg net +0.5*fee, round-trip net -0.5*fee
    intent = _make_net_cost_intent(30, gross_edge)

    result = orouter._round_trip_net_of_cost_gate(intent)
    assert result is None, f"single-leg economics must pass; got {result}"
    assert intent.policy_mode == "NEUTRAL_MM"


def test_round_trip_gate_still_charges_exit_leg_when_flag_off(monkeypatch):
    """Flag absent -> old round-trip economics unchanged."""
    import merid.event_venues.kalshi.order_router as orouter
    from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact

    _flag_off(monkeypatch, "MERID_DISABLE_EXIT_POLICY")
    _is_exit_order_passthrough(monkeypatch)
    _patch_market_state(monkeypatch, bid_cents=29, ask_cents=31)

    maker_fee = float(kalshi_fee_cents_exact(0.30, 1.0, "maker"))
    gross_edge = maker_fee * 1.5
    intent = _make_net_cost_intent(30, gross_edge)

    result = orouter._round_trip_net_of_cost_gate(intent)
    assert result is not None and result.startswith("net_of_cost:"), (
        f"round-trip economics must still reject; got {result}"
    )


def _td_calibrator():
    from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator
    return TailProbabilityCalibrator(
        yes_held_prices=[0.10, 0.30, 0.40, 0.50, 0.55, 0.60, 0.75, 0.90],
        yes_actual_probs=[0.10, 0.28, 0.40, 0.53, 0.59, 0.63, 0.77, 0.90],
        no_held_prices=[0.10, 0.30, 0.40, 0.50, 0.55, 0.60, 0.75, 0.90],
        no_actual_probs=[0.12, 0.32, 0.43, 0.52, 0.61, 0.67, 0.83, 0.92],
        buffer=0.05,
    )


def _td_decision(monkeypatch, exits_disabled: bool):
    import merid.prediction.trade_decision as td

    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(td, "load_tail_calibrator", lambda *a, **k: _td_calibrator())
    monkeypatch.setattr(td, "MERID_CALIBRATION_CAP_FULL_RANGE", True)
    monkeypatch.setattr(td, "MERID_DISABLE_EXIT_POLICY", exits_disabled)

    return td.compute_trade_decision(
        run_id="exit_reserve_test",
        decision_id="exit_reserve_test",
        ticker="KXBTC15M-26SEP271200-00",
        asset="BTC",
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=900.0,
        yes_bid_cents=58.0,
        yes_ask_cents=60.0,
        no_bid_cents=38.0,
        no_ask_cents=40.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.0,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
    )


def test_exit_cost_reserve_zeroed_when_exits_disabled(monkeypatch):
    """Hold-to-settlement EV carries entry fee only — no phantom exit leg."""
    d = _td_decision(monkeypatch, exits_disabled=True)
    assert float(d.exit_cost_reserve_yes) == 0.0, (
        f"exit reserve must be 0 with exits disabled, got {d.exit_cost_reserve_yes}"
    )
    assert float(d.exit_cost_reserve_no) == 0.0


def test_exit_cost_reserve_charged_when_exits_enabled(monkeypatch):
    """Flag absent -> exit reserve still charged (behavior unchanged)."""
    d = _td_decision(monkeypatch, exits_disabled=False)
    # fee_per_contract_cents=1.0 -> fee=0.01 charged as the exit reserve.
    assert float(d.exit_cost_reserve_yes) == pytest.approx(0.01)
    assert float(d.exit_cost_reserve_no) == pytest.approx(0.01)
