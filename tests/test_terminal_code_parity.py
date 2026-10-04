"""5-asset x 2-side parity suite for the canonical 15m decision pipeline.

Invariant under test: when normalized inputs are identical, BTC, ETH, SOL,
XRP and DOGE must produce the same terminal outcome.  Different labels are
legitimate only when they arise from different *inputs* (price band, TTE,
depth, quotes) flowing through one shared policy — never from asset-specific
control flow.

Covers:
  * classify_market_regime has no asset parameter at all (structural proof
    that the price-band / per-band-TTE policy cannot fork by asset).
  * resolve_terminal_code precedence (DecisionSignals -> TerminalCode).
  * canonical_terminal_code mapping for the production reason vocabulary.
  * compute_trade_decision: identical normalized inputs across all five
    assets produce identical selection / no_trade_reason.
  * Soft evidence states are never the terminal semantics: SOFT_PENALTY /
    SPARSE insufficiency surface as EDGE_BELOW_DYNAMIC_THRESHOLD, and a
    soft-pass admits the candidate.
"""
from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from merid.prediction.terminal_codes import (
    DecisionSignals,
    TerminalCode,
    canonical_terminal_code,
    resolve_terminal_code,
)


ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SIDES = ("yes", "no")


# --------------------------------------------------------------------------
# Structural parity: the band/TTE classifier cannot fork on asset
# --------------------------------------------------------------------------

def test_regime_classifier_has_no_asset_parameter():
    from merid.event_venues.kalshi.market_regime import classify_market_regime

    params = list(inspect.signature(classify_market_regime).parameters)
    assert "asset" not in params
    assert params == ["price_cents", "time_to_expiry_seconds"]


@pytest.mark.parametrize("asset", ASSETS)
def test_tte_floor_is_identical_across_assets(asset):
    """One shared regime table: below the band floor no asset may enter."""
    from merid.event_venues.kalshi.market_regime import (
        REGIME_CONFIGS,
        classify_market_regime,
    )

    # balanced band (25-75c) requires >=120s; every asset sees the same rule.
    assert classify_market_regime(50, 119) is None
    r = classify_market_regime(50, 120)
    assert r is not None and r.name == "balanced"
    assert r.min_time_to_expiry_seconds == 120
    # The config table itself is asset-free.
    for name, regime in REGIME_CONFIGS.items():
        assert not hasattr(regime, "asset"), name


@pytest.mark.parametrize("asset", ASSETS)
def test_price_band_is_identical_across_assets(asset):
    from merid.event_venues.kalshi.market_regime import classify_market_regime

    # 5c is below every enabled band (tails are disabled): no regime.
    assert classify_market_regime(5, 600) is None
    # 96c likewise above the enabled bands.
    assert classify_market_regime(96, 600) is None
    # 50c -> balanced for every asset.
    assert classify_market_regime(50, 600).name == "balanced"


# --------------------------------------------------------------------------
# Resolver precedence (DecisionSignals -> TerminalCode)
# --------------------------------------------------------------------------

def test_resolve_terminal_code_precedence_order():
    base = dict(
        market_available=True,
        tte_seconds=600.0,
        min_entry_tte_seconds=30.0,
        book_trusted=True,
        spot_trusted=True,
        any_side_has_real_liquidity=True,
        any_side_in_price_band=True,
        any_eligible_side_has_positive_net_ev=True,
        selected_side_evidence_hard_block=False,
        selected_side_clears_dynamic_threshold=True,
        selected_side_clears_conviction=True,
        allocator_selected=True,
    )
    assert resolve_terminal_code(DecisionSignals(**base)) == TerminalCode.CANDIDATE_EMITTED

    # Each earlier gate must pre-empt every later one.
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "market_available": False})
    ) == TerminalCode.MARKET_UNAVAILABLE
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "tte_seconds": 20.0})
    ) == TerminalCode.TTE_ENTRY_CUTOFF
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "book_trusted": False})
    ) == TerminalCode.BOOK_NOT_TRUSTED
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "spot_trusted": False})
    ) == TerminalCode.SPOT_NOT_TRUSTED
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "any_side_has_real_liquidity": False})
    ) == TerminalCode.SIDE_NOT_LIQUID
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "any_side_in_price_band": False})
    ) == TerminalCode.NO_ELIGIBLE_PRICE_BAND
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "any_eligible_side_has_positive_net_ev": False})
    ) == TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "selected_side_evidence_hard_block": True})
    ) == TerminalCode.EVIDENCE_HARD_BLOCK
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "selected_side_clears_dynamic_threshold": False})
    ) == TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "selected_side_clears_conviction": False})
    ) == TerminalCode.LOW_CONVICTION
    assert resolve_terminal_code(
        DecisionSignals(**{**base, "allocator_selected": False})
    ) == TerminalCode.ALLOCATION_NOT_SELECTED


def test_edge_gate_preempts_evidence_labels():
    """A domain-eligible asset with no positive EV must report
    NO_POSITIVE_EXECUTABLE_EDGE even when a producer only supplied an
    evidence-flavoured reason string."""
    st = DecisionSignals(
        any_eligible_side_has_positive_net_ev=False,
        selected_side_evidence_hard_block=True,
        selected_side_clears_dynamic_threshold=False,
        allocator_selected=False,
    )
    assert resolve_terminal_code(st) == TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE


def test_soft_evidence_reason_maps_to_edge_threshold():
    for raw in (
        "evidence_soft_penalty_insufficient_yes",
        "evidence_soft_penalty_insufficient_no",
        "evidence_challenge_insufficient_yes",
        "evidence_sparse_matched_no",
        "evidence_empty_insufficient_yes",
    ):
        assert canonical_terminal_code(raw, 5.0) == (
            TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
        ), raw


def test_hard_evidence_reason_maps_to_hard_block():
    for raw in (
        "evidence_toxic_cell_no",
        "evidence_cell_insufficient_yes",
        "calibration_evidence_yes",
        "market_fade_blocked_no",
    ):
        assert canonical_terminal_code(raw, 5.0) == (
            TerminalCode.EVIDENCE_HARD_BLOCK.value
        ), raw


def test_conviction_and_lane_floor_reasons_map_canonical():
    # Structural conviction veto must not collapse into an EV label — the
    # candidate cleared its economics and failed directional certainty.
    assert canonical_terminal_code("low_conviction_yes", -1.4) == (
        TerminalCode.LOW_CONVICTION.value
    )
    assert canonical_terminal_code("low_conviction_no", 2.0) == (
        TerminalCode.LOW_CONVICTION.value
    )
    # A bounded-lane floor miss is a threshold failure on the lane's own
    # (possibly negative) required edge, not a positive-EV failure.
    assert canonical_terminal_code("yes_edge_below_lane_floor", -4.6) == (
        TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
    )
    assert canonical_terminal_code("no_edge_below_lane_floor", -5.1) == (
        TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
    )


# --------------------------------------------------------------------------
# compute_trade_decision: identical inputs -> identical outcome across assets
# --------------------------------------------------------------------------

import merid.prediction.trade_decision as _td  # noqa: E402
from merid.prediction.trade_decision import compute_trade_decision  # noqa: E402


@pytest.fixture(autouse=True)
def _neutral_overlays(monkeypatch, tmp_path):
    """Isolate market-anchor shrinkage and any on-disk evidence state."""
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )


def _decision(asset: str, **over):
    args = dict(
        run_id="parity",
        decision_id=f"parity_{asset}",
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=58.0,
        no_ask_cents=60.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.03,
        settlement_reference="cfb_rti_live",
    )
    args.update(over)
    return compute_trade_decision(**args)


@pytest.mark.parametrize("asset", ASSETS)
def test_no_positive_edge_is_uniform(asset):
    """Both asks above the calibrated fair value: neither side has positive
    executable EV, identically for every asset."""
    d = _decision(
        asset,
        yes_bid_cents=59.0, yes_ask_cents=60.0,
        no_bid_cents=44.0, no_ask_cents=45.0,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "no_positive_executable_edge"


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_positive_edge_path_is_asset_symmetric(asset, side):
    """Identical books + identical calibrated belief select the same side and
    emit a candidate for every asset."""
    if side == "yes":
        d = _decision(asset, spot_price=100.5)
        want = "yes"
    else:
        d = _decision(asset, spot_price=99.5)
        want = "no"
    assert d.selected_outcome == want, (asset, d.no_trade_reason)
    assert d.no_trade_reason is None


@pytest.mark.parametrize("asset", ASSETS)
def test_soft_penalty_is_not_terminal(asset, monkeypatch):
    """SOFT_PENALTY state with positive net EV admits via the elevated-reserve
    lane (allowed=True); it must never be the semantic terminal state."""
    from merid.prediction import evidence_policy as ep

    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", True)
    monkeypatch.setattr(
        _td, "_load_live_evidence", lambda: {"cells": {"k": {}}}
    )

    def _soft_pass(*a, **kw):
        return ep.EvidenceDecision(
            allowed=True,
            code="SOFT_PENALTY_PASS",
            cell_key=f"{a[1] if len(a) > 1 else 'SOL'}|yes|50-74|mid",
            evidence_level_used="asset_side_price",
            parent_level=None,
            effective_independent_n=10.0,
            cell_n_eff=10.0,
            wins_weighted=6.0,
            losses_weighted=4.0,
            n_raw=10,
            posterior_mean=0.6,
            posterior_lcb=0.5,
            posterior_std=0.05,
            lcb_net_ev_cents=1.0,
            required_margin_cents=8.0,
            sparse_uplift_cents=3.0,
            matching_hard_block=False,
            escape_required=True,
            evidence_stale=False,
            evidence_age_s=60.0,
            fallback_reason=None,
        )

    monkeypatch.setattr(ep, "evaluate", _soft_pass)
    monkeypatch.setattr(ep, "enabled", lambda: True)

    d = _decision(asset, spot_price=100.5)
    assert d.selected_outcome == "yes", (asset, d.no_trade_reason)
