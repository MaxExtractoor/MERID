"""Unit tests for the cheap-tail canary lane."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import merid.prediction.trade_decision as _trade_decision_module
from merid.prediction.trade_decision import compute_trade_decision


_fd, _tmp_daily = tempfile.mkstemp(suffix=".json")
os.close(_fd)


def _reset_canary_daily_file() -> None:
    """Write a fresh daily counter and clear any in-memory cached state."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh = {"date": today, "count": 0, "assets": {}}
    with open(_tmp_daily, "w", encoding="utf-8") as f:
        json.dump(fresh, f)
    _trade_decision_module._cheap_tail_canary_daily_state = {}


_reset_canary_daily_file()


@pytest.fixture(autouse=True)
def _configure_canary(monkeypatch):
    """Set the canary lane constants via monkeypatch so these tests work
    regardless of which test file imports *merid.prediction.trade_decision* first.
    """
    _reset_canary_daily_file()
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_ENABLED", True)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_ALLOWED_SIDES", ["yes"])
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_ALLOWED_ASSETS", ["ETH"])
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS", 20)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS", 34)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT", 8.0)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MIN_PROB_GAP_PCT", 9.0)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MIN_EV_TO_TAIL_RATIO", 0.10)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MIN_TTE_S", 120.0)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MAX_TTE_S", 900.0)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_MAX_DAILY", 3)
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_DAILY_FILE", _tmp_daily)
    monkeypatch.setattr(_trade_decision_module, "MERID_TAIL_CALIBRATION_ENABLED", False)
    monkeypatch.setattr(_trade_decision_module, "MERID_ORDER_DECISION_LEDGER_ENABLED", False)
    monkeypatch.setattr(_trade_decision_module, "MERID_MIN_HELD_PRICE_CENTS", 35)


def _make_canary_decision(decision_id: str = "test-dec", **kwargs):
    defaults = {
        "run_id": "test-run",
        "decision_id": decision_id,
        "ticker": "KXETH15M-26SEP101830-30",
        "asset": "ETH",
        "spot_price": 99.9655,
        "strike_price": 100.0,
        "seconds_to_expiry": 300.0,
        "yes_bid_cents": 29.0,
        "yes_ask_cents": 30.0,
        "no_bid_cents": 70.0,
        "no_ask_cents": 71.0,
        "yes_depth_cc": 200.0,
        "no_depth_cc": 200.0,
        "fee_per_contract_cents": 2.0,
        "annualized_vol": 0.80,
        "model_uncertainty": 0.02,
        "data_quality": "live",
        "data_state": "healthy",
        "regime": "normal",
        "regime_label": "normal",
        "regime_probability": 1.0,
        "min_required_edge": 0.03,
        "settlement_reference": "cfb_rti_live",
    }
    defaults.update(kwargs)
    return compute_trade_decision(**defaults)


def test_canary_selects_cheap_yes_eth():
    """A 30c ETH YES with Bachelier p ~0.44 and positive net edge should be selected by the canary."""
    decision = _make_canary_decision(decision_id="test-canary-select")
    assert decision.selected_outcome == "yes", f"expected canary YES, got {decision.selected_outcome}"
    assert decision.indicators.get("decision_lane") == "cheap_tail_canary"
    assert float(decision.approved_size_cc) == 100.0
    price_cents = int(round(float(decision.selected_outcome_price or Decimal("0")) * 100))
    assert 20 <= price_cents <= 34, f"price {price_cents}c is outside canary band"
    assert float(decision.net_edge or 0) > 0.08


def test_main_lane_rejects_cheap_yes():
    """The same 30c candidate must be rejected by the main lane; canary is the only path."""
    decision = _make_canary_decision(decision_id="test-main-vs-canary")
    assert decision.no_trade_reason is None or "cheap_tail_canary" in (decision.no_trade_reason or "")
    assert decision.indicators.get("decision_lane") == "cheap_tail_canary"


def test_canary_blocks_non_allowed_asset():
    """A cheap YES for a non-allowed asset must not be selected by the canary."""
    decision = _make_canary_decision(decision_id="test-asset-guard", asset="SOL")
    assert decision.indicators.get("decision_lane") != "cheap_tail_canary"
    assert decision.selected_outcome is None or decision.selected_outcome != "yes"


def test_canary_blocks_non_allowed_side():
    """A cheap NO (even if in range) must not be selected because allowed_sides=yes."""
    # Mirror the scenario: 30c NO with p_no=0.44 (spot just above strike).
    decision = _make_canary_decision(
        decision_id="test-side-guard",
        spot_price=100.0345,
        yes_bid_cents=70.0,
        yes_ask_cents=71.0,
        no_bid_cents=29.0,
        no_ask_cents=30.0,
    )
    assert decision.indicators.get("decision_lane") != "cheap_tail_canary"


def test_main_lane_does_not_select_cheap_tail(monkeypatch):
    """Without the canary overlay the 30c candidate should be a no_trade."""
    with open(_tmp_daily, "w", encoding="utf-8") as _:
        pass  # reset daily count
    monkeypatch.setattr(_trade_decision_module, "MERID_CHEAP_TAIL_CANARY_ENABLED", False)
    decision = _make_canary_decision(decision_id="test-main-lane-only")
    assert decision.selected_outcome is None
    assert decision.indicators.get("decision_lane") != "cheap_tail_canary"
