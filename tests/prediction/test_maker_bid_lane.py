"""Unit tests for the queue-priced maker (bid-basis) evaluation lane.

Regression coverage for 2026-10-02: the taker and maker-fee decision passes
both price entry at the ASK, so in a market-rich-vs-model regime every eval
shows negative edge and nothing trades.  The maker-bid pass prices entry at
the own-side BID (the price a resting post-only order actually pays) and
charges an explicit adverse-selection reserve inside net edge.
"""
from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import compute_trade_decision


_fd, _tmp_daily = tempfile.mkstemp(suffix=".json")
os.close(_fd)


@pytest.fixture(autouse=True)
def _configure_lane(monkeypatch):
    monkeypatch.setattr(_td, "MERID_TAIL_CALIBRATION_ENABLED", False)
    monkeypatch.setattr(_td, "MERID_ORDER_DECISION_LEDGER_ENABLED", False)
    monkeypatch.setattr(_td, "MERID_MIN_HELD_PRICE_CENTS", 35)
    monkeypatch.setattr(_td, "MERID_CHEAP_TAIL_CANARY_ENABLED", False)
    monkeypatch.setattr(
        _td, "MERID_CHEAP_TAIL_CANARY_DAILY_FILE", _tmp_daily
    )


def _make_decision(decision_id: str = "test-mb", **kwargs):
    defaults = {
        "run_id": "test-run",
        "decision_id": decision_id,
        "ticker": "KXETH15M-26OCT101830-30",
        "asset": "ETH",
        "spot_price": 99.9655,
        "strike_price": 100.0,
        # 300s: inside the bounded live domain (<= MERID_LIVE_ENTRY_MAX_TTE_S
        # = 600s) and clear of the near-expiry confidence penalty.
        "seconds_to_expiry": 300.0,
        # YES book 46/54 (8c spread), dual NO book 46/54 — models the wide
        # queue observed on 15m binaries near convergence.  Mid is neutral
        # (50c) so the market-fade and anchor priors do not fight the side.
        "yes_bid_cents": 46.0,
        "yes_ask_cents": 54.0,
        "no_bid_cents": 46.0,
        "no_ask_cents": 54.0,
        "yes_depth_cc": 500.0,
        "no_depth_cc": 500.0,
        "annualized_vol": 0.80,
        "model_uncertainty": 0.02,
        "data_quality": "live",
        "data_state": "healthy",
        "regime": "normal",
        "regime_label": "normal",
        "regime_probability": 1.0,
        "min_required_edge": 0.03,
        "settlement_reference": "cfb_rti_live",
        # p_yes = 0.59: inside the tail-deviation guard (raw Bachelier
        # ~0.44-0.47, guard 0.15) and clear of the ~0.51 cost-basis floor at
        # a 46c bid entry — isolates the price-basis effect.
        "p_yes_model": 0.59,
    }
    defaults.update(kwargs)
    return compute_trade_decision(**defaults)


def test_ask_basis_taker_fails_edge():
    """At taker economics (ask + taker fee) the same candidate is below floor."""
    decision = _make_decision(fee_per_contract_cents=2.0)
    # net at ask: 0.59 - 0.54 - 0.02(taker fee) - 0.005(exit) - risk < floor
    assert decision.selected_outcome is None, (
        f"unexpected selection: {decision.selected_outcome} "
        f"reason={decision.no_trade_reason}"
    )


def test_bid_basis_selects_and_stamps_lane():
    """The bid-priced pass must evaluate edge at the own-side bid."""
    decision = _make_decision(
        decision_id="test-mb-select",
        fee_per_contract_cents=0.5,
        entry_price_basis="bid",
        adverse_selection_reserve=0.02,
    )
    assert decision.selected_outcome == "yes", (
        f"expected YES selection, got {decision.selected_outcome} "
        f"reason={decision.no_trade_reason}"
    )
    # Entry price must be the YES BID (46c), not the ask.
    price = float(decision.selected_outcome_price or Decimal("0"))
    assert abs(price - 0.46) < 1e-9, f"expected bid-priced entry 0.46, got {price}"
    assert decision.indicators.get("decision_lane") == "maker_bid"
    assert decision.indicators.get("entry_price_basis") == "bid"


def test_bid_basis_reserve_is_charged():
    """Zero reserve must produce strictly more net edge than 2c reserve."""
    base = _make_decision(
        decision_id="test-mb-r0",
        fee_per_contract_cents=0.5,
        entry_price_basis="bid",
        adverse_selection_reserve=0.0,
    )
    hair = _make_decision(
        decision_id="test-mb-r2",
        fee_per_contract_cents=0.5,
        entry_price_basis="bid",
        adverse_selection_reserve=0.02,
    )
    assert float(hair.net_edge) == pytest.approx(
        float(base.net_edge) - 0.02, abs=1e-6
    )


def test_bid_basis_dead_side_is_not_priced():
    """A side with no bid cannot host a resting order — it must not be
    selected as a phantom edge at entry=0."""
    decision = _make_decision(
        decision_id="test-mb-deadside",
        fee_per_contract_cents=0.5,
        entry_price_basis="bid",
        adverse_selection_reserve=0.02,
        p_yes_model=0.05,  # strongly NO-favouring model
        no_bid_cents=0.0,  # ...but the NO book is empty
        no_ask_cents=10.0,
        yes_bid_cents=90.0,  # keep the YES side out of reach too
        yes_ask_cents=92.0,
    )
    assert decision.selected_outcome != "no", (
        "selected empty-bid side — phantom edge"
    )


def test_ask_basis_default_unchanged():
    """Default basis keeps ask pricing — regression guard for all lanes."""
    decision = _make_decision(
        decision_id="test-ask-default",
        fee_per_contract_cents=0.5,
        p_yes_model=0.78,  # clears the 3c floor even at the ask
    )
    assert decision.indicators.get("entry_price_basis") in (None, "ask")
    # Up-front stamp must still record the ask as the evaluated entry.
    assert decision.indicators.get("yes_entry_price_cents") == 54
    assert decision.indicators.get("no_entry_price_cents") == 54
    if decision.selected_outcome == "yes":
        price = float(decision.selected_outcome_price or Decimal("0"))
        assert abs(price - 0.54) < 1e-9
