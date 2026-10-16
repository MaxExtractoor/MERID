"""Regression tests for the 2026-10-16 loss audit (FIX A-D).

Losses under audit: BTC NO @78c (1.91ct, evidence-blocked provisional probe,
hard-stop rejected on a 1c-non-executable limit then filled ~4c worse) and
ETH NO @47c (3ct probe whose +23c take_profit was envelope-deferred then
hard-stopped at 11c).

  A. settlement_aligned_exit.exit_envelope_allows — locked-gain arm lets a
     profitable gated exit through below the 85c profit-lock bid level.
  B. agent_grid_15m probe caps — evidence-blocked / non-positive-LCB probes
     cap at MERID_PROBE_LANE_MAX_CONTRACTS and never cross as taker.
  C. execution_risk_firewall — forced exits reprice to the depth-aware
     marginal level instead of terminal-rejecting on a non-executable limit;
     BookDepth carries marginal_price_cents.
  D. directional_regime.trendside_entry_block — fresh-label persistence,
     extreme-extension, and fast-leg-reversal arms.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.settlement_aligned_exit import (
    exit_envelope_allows,
)
from merid.event_venues.kalshi.execution_risk_firewall import (
    ExecutionRiskFirewall,
    FirewallDecision,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent
from merid.event_venues.kalshi.stop_candidate import (
    _get_depth_marginal_exit_cents,
)
from merid.prediction import directional_regime as dr
from merid.prediction.agent_grid_15m import _probe_restricted_evidence


# ---------------------------------------------------------------- A --------
# Locked-gain envelope arm.

def test_envelope_profit_lock_allows_locked_gain() -> None:
    """ETH case: bid=70 vs entry=47 (+23c) at TTE=200 — below the 85c arm,
    outside the terminal window — must ALLOW (locked win, not bleeding)."""
    ok, detail = exit_envelope_allows(
        "take_profit", 70, 200.0, entry_price_cents=47
    )
    assert ok, detail
    assert "lock_ok=True" in detail


def test_envelope_still_defers_small_gain() -> None:
    """A marginal winner inside the gated zone stays deferred."""
    ok, detail = exit_envelope_allows(
        "take_profit", 55, 300.0, entry_price_cents=47
    )
    assert not ok
    assert "lock_gain" in detail


def test_envelope_missing_entry_price_defers() -> None:
    """No entry price -> profit-lock arm unarmed; envelope unchanged."""
    ok, _ = exit_envelope_allows(
        "take_profit", 70, 300.0, entry_price_cents=None
    )
    assert not ok


def test_envelope_loss_exit_still_gated() -> None:
    """A bleeding exit (bid < entry) must never bypass via the lock arm."""
    ok, _ = exit_envelope_allows(
        "stop_loss", 20, 300.0, entry_price_cents=80
    )
    assert not ok


def test_envelope_lock_arm_env_threshold(monkeypatch) -> None:
    monkeypatch.setenv("MERID_EXIT_ENVELOPE_PROFIT_LOCK_C", "30")
    ok, _ = exit_envelope_allows(
        "take_profit", 70, 200.0, entry_price_cents=47
    )
    assert not ok  # +23c gain < raised 30c lock floor


def test_envelope_lock_arm_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MERID_EXIT_ENVELOPE_PROFIT_LOCK_C", "0")
    ok, _ = exit_envelope_allows(
        "take_profit", 90, 200.0, entry_price_cents=47
    )
    # 90 >= 85c bid arm fires anyway; disable only removes the lock arm.
    assert ok
    ok2, _ = exit_envelope_allows(
        "take_profit", 70, 200.0, entry_price_cents=47
    )
    assert not ok2


def test_envelope_untouched_for_non_gated_reasons() -> None:
    ok, detail = exit_envelope_allows(
        "expiry_liquidation", 10, 300.0, entry_price_cents=47
    )
    assert ok and detail == "not_gated"


# ---------------------------------------------------------------- B --------
# Evidence-refused / non-positive-LCB probe sizing.


def _decision(sel: str, indicators: dict, net_edge: float, mrr: float):
    """Minimal TradeDecision stand-in for _probe_restricted_evidence."""
    d = MagicMock()
    d.selected_outcome = sel
    d.indicators = indicators
    d.edge_breakdown = None
    bd = MagicMock()
    bd.net_edge = Decimal(str(net_edge))
    bd.model_risk_reserve = Decimal(str(mrr))
    setattr(d, f"{sel}_edge_breakdown", bd)
    return d


def test_probe_restricted_on_evidence_block() -> None:
    d = _decision(
        "no",
        {"no_evidence_action": "block",
         "no_evidence_binding_gate": "CELL_EVIDENCE_INSUFFICIENT"},
        net_edge=0.022, mrr=0.005,
    )
    restricted, why = _probe_restricted_evidence(d)
    assert restricted
    assert "evidence_action=block" in why


def test_probe_restricted_on_negative_lcb() -> None:
    """ETH case: evidence_action cleared but net_edge - model_risk <= 0."""
    d = _decision(
        "no",
        {"no_evidence_action": "allow"},
        net_edge=0.0168, mrr=0.02,   # lcb = -0.32c
    )
    restricted, why = _probe_restricted_evidence(d)
    assert restricted
    assert "lcb_ev" in why


def test_probe_not_restricted_on_clean_evidence() -> None:
    d = _decision(
        "yes",
        {"yes_evidence_action": "allow"},
        net_edge=0.05, mrr=0.01,
    )
    restricted, _ = _probe_restricted_evidence(d)
    assert not restricted


def test_probe_max_contracts_default_one(monkeypatch) -> None:
    monkeypatch.delenv("MERID_PROBE_LANE_MAX_CONTRACTS", raising=False)
    from merid.prediction.agent_grid_15m import _probe_lane_max_contracts
    assert _probe_lane_max_contracts() == 1.0


# ---------------------------------------------------------------- C --------
# Depth-aware marginal level + forced-exit reprice in the firewall.


def test_depth_marginal_walks_levels_for_qty() -> None:
    state = MagicMock()
    state.book = None
    # BTC incident shape: qty needs 3 levels deep.
    state.yes_bids = [(47, 1.0), (43, 0.5), (40, 2.0)]
    assert _get_depth_marginal_exit_cents(state, "yes", 150) == 43
    assert _get_depth_marginal_exit_cents(state, "yes", 300) == 40


def test_depth_marginal_none_on_missing_book() -> None:
    state = MagicMock()
    state.book = None
    state.yes_bids = []
    assert _get_depth_marginal_exit_cents(state, "yes", 100) is None
    assert _get_depth_marginal_exit_cents(None, "yes", 100) is None


def test_depth_marginal_none_when_depth_insufficient() -> None:
    state = MagicMock()
    state.book = None
    state.yes_bids = [(47, 0.5)]
    assert _get_depth_marginal_exit_cents(state, "yes", 200) is None


@pytest.fixture(autouse=True)
def _reset_firewall():
    ExecutionRiskFirewall.reset_for_test()
    yield
    ExecutionRiskFirewall.reset_for_test()


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
        "intent_id": "intent_btc_stop",
        "client_order_id": "stopcand_test_001",
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
    state.last_book_update_ts = time.monotonic()
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
async def test_forced_stop_repriced_to_marginal_not_rejected():
    """BTC incident: sell limit=44 while qty-VWAP=42.5/marginal=40 — forced
    exits must reprice to the executable depth, not bounce the order."""
    # Book sizes are contracts: 1.0ct@43 then 0.91ct@40 -> vwap=ceil(41.57)=42,
    # marginal=40.  limit=44 is non-executable at full qty.
    _mock_position_and_book(no_bids=[(43, 1), (40, 100)])
    canonical = _canonical()
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status == "approved", decision.reason
    # Repriced to the deepest needed level (marginal=40), then clamped vs
    # vwap=42 -> min(40, 42) = 40.
    assert decision.approved_limit_cents == 40


@pytest.mark.asyncio
async def test_discretionary_exit_still_rejected_when_non_executable():
    """Only forced/safety exits get the reprice; a profit exit defers."""
    _mock_position_and_book(no_bids=[(43, 1), (40, 100)])
    canonical = _canonical(reason="take_profit")
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status in ("rejected", "observe_only")
    assert "limit_not_executable" in decision.reason


@pytest.mark.asyncio
async def test_forced_exit_reprice_kill_switch(monkeypatch):
    monkeypatch.setenv("MERID_FIREWALL_FORCED_EXIT_REPRICE", "0")
    _mock_position_and_book(no_bids=[(43, 1), (40, 100)])
    canonical = _canonical()
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status in ("rejected", "observe_only")
    assert "limit_not_executable" in decision.reason


@pytest.mark.asyncio
async def test_forced_exit_still_approves_when_limit_executable():
    """No reprice needed — marginal is above the limit (deep book)."""
    _mock_position_and_book(no_bids=[(45, 1000), (44, 1000)])
    canonical = _canonical(limit_cents=43)
    decision = await ExecutionRiskFirewall.get_instance().validate_exit(
        canonical
    )
    assert decision.status == "approved"
    # clamp: min(limit=43, vwap=44) = 43 — original limit honored.
    assert decision.approved_limit_cents == 43


@pytest.fixture(autouse=True)
def _clean_patches():
    yield
    patch.stopall()


# ---------------------------------------------------------------- D --------
# Trend-side whipsaw guard.


def _regime(label: str, age_s: Optional[float] = None) -> dr.DirectionalRegime:
    return dr.DirectionalRegime(
        label=label,
        breadth60_pos=1,
        breadth60_total=5,
        btc_r60=-0.001,
        asset_r60={},
        ts=1_000_000.0,
        label_age_s=age_s,
    )


def test_trendside_fresh_regime_blocks_no_entry():
    """SELL_OFF confirmed 12s ago — buying the trend side inside the
    persistence window is the whipsaw-top case (ETH 2026-10-16)."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=12.0)
    reason = dr.trendside_entry_block(reg, "no", zscore=-1.5, price_cents=47)
    assert reason is not None and reason.startswith("trend_regime_fresh")


def test_trendside_persistent_regime_allows_entry():
    reg = _regime("SELL_OFF_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(reg, "no", zscore=-1.5, price_cents=47)
    assert reason is None


def test_trendside_extreme_extension_blocks_premium_buy():
    """BTC incident: NO @78c at |z|=5.9 — paying the extreme trend premium."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(reg, "no", zscore=-5.9, price_cents=78)
    assert reason is not None and reason.startswith("trend_extreme_extension")


def test_trendside_extreme_extension_needs_price_premium():
    """Extreme z alone at a cheap price is not exhaustion-buying."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(reg, "no", zscore=-5.9, price_cents=55)
    assert reason is None


def test_trendside_bounce_blocks_selloff_chase():
    """Fast leg reversing against the regime = V-bottom signature."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(
        reg, "no", zscore=-1.0, price_cents=40, rti_fast=+0.0015
    )
    assert reason is not None and reason.startswith("trend_bounce_detected")


def test_trendside_bounce_blocks_rally_chase_symmetric():
    reg = _regime("RALLY_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(
        reg, "yes", zscore=+1.0, price_cents=40, rti_fast=-0.0015
    )
    assert reason is not None and reason.startswith("trend_bounce_detected")


def test_trendside_aligned_fast_leg_allows():
    reg = _regime("SELL_OFF_CONFIRMED", age_s=300.0)
    reason = dr.trendside_entry_block(
        reg, "no", zscore=-1.0, price_cents=55, rti_fast=-0.002
    )
    assert reason is None


def test_trendside_countertrend_side_untouched():
    """Countertrend entries are regime_entry_block's domain — no double-gate."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=10.0)
    assert dr.trendside_entry_block(reg, "yes", zscore=-1.0, price_cents=30) is None


def test_trendside_neutral_label_no_block():
    reg = _regime("NEUTRAL", age_s=5.0)
    assert dr.trendside_entry_block(reg, "no", zscore=-9.0, price_cents=95) is None


def test_trendside_unknown_age_does_not_block():
    """label_age_s=None (hysteresis off / cold start) unarms arm 1 only."""
    reg = _regime("SELL_OFF_CONFIRMED", age_s=None)
    assert dr.trendside_entry_block(reg, "no", zscore=-1.0, price_cents=50) is None


def test_label_age_tracked_through_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MERID_DIRECTIONAL_REGIME_STATE_PATH", str(tmp_path / "r.json")
    )
    monkeypatch.setenv("MERID_REGIME_MIN_TICK_S", "1.0")
    monkeypatch.setenv("MERID_REGIME_CONFIRM_TICKS", "2")
    dr._regime_cache = (0.0, {})

    class _Sl:
        def __init__(self, r60):
            self.rti_returns = {"rti_return_60s": r60}
            self.rti_execution_eligible = True

    class _Sn:
        def __init__(self, r60):
            self.by_asset = {a: _Sl(r60) for a in dr._REGIME_ASSETS}

    down = _Sn(-0.002)
    r = None
    for i in range(3):
        r = dr.compute_directional_regime(down, now=1_000_000.0 + i * 5.0)
    assert r.label == "SELL_OFF_CONFIRMED"
    assert r.label_age_s is not None and r.label_age_s <= 10.0

    # The label keeps its age while the same regime persists.
    r2 = dr.compute_directional_regime(down, now=1_000_100.0)
    assert r2.label == "SELL_OFF_CONFIRMED"
    assert r2.label_age_s >= 95.0
    dr._regime_cache = (0.0, {})
