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
