"""Candidate-funnel telemetry: per-asset terminal codes and candidate-surface
fields must be populated on every evaluation, including no-trade rejections,
so the funnel answers "where did each asset die" from the record alone.
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import decision_telemetry as dt


def _wf(**stages):
    return {"stages": stages, "selected": False}


def test_terminal_code_allocator_selected():
    assert dt._terminal_code({}, {"x": 1}, True, "", None) == "CANDIDATE_EMITTED"


def test_terminal_code_waterfall_stages():
    assert dt._terminal_code(
        _wf(market_discovered={"status": False, "reason": "no contract in entry window"}),
        None, False, "", None,
    ) == "MARKET_UNAVAILABLE"
    assert dt._terminal_code(
        _wf(
            market_discovered={"status": True},
            spot_price={"status": False, "reason": "no spot"},
        ),
        None, False, "", None,
    ) == "SPOT_NOT_TRUSTED"
    assert dt._terminal_code(
        _wf(
            market_discovered={"status": True},
            spot_price={"status": True},
            market_open={"status": False, "reason": "market validation failed (stale/missing/illiquid)"},
        ),
        None, False, "", None,
    ) == "BOOK_NOT_TRUSTED"
    assert dt._terminal_code(
        _wf(
            market_discovered={"status": True},
            spot_price={"status": True},
            market_open={"status": False, "reason": "price_history=0 < 1 (warmup)"},
        ),
        None, False, "", None,
    ) == "SPOT_NOT_TRUSTED"
    assert dt._terminal_code(
        _wf(
            market_discovered={"status": True},
            spot_price={"status": True},
            market_open={"status": False, "reason": "time_to_expiry=18.4s < min=30.0s"},
        ),
        None, False, "", None,
    ) == "TTE_ENTRY_CUTOFF"


def test_terminal_code_reason_mapping():
    cases = [
        ("both_sides_disabled_regime", "NO_ELIGIBLE_PRICE_BAND"),
        ("price_band_both_sides_disabled", "NO_ELIGIBLE_PRICE_BAND"),
        ("tte_entry_cutoff", "TTE_ENTRY_CUTOFF"),
        ("min_tte_entry_disabled", "TTE_ENTRY_CUTOFF"),
        ("final_minute_entry_disabled", "TTE_ENTRY_CUTOFF"),
        ("evidence_toxic_cell_no", "EVIDENCE_HARD_BLOCK"),
        ("evidence_cell_insufficient_no", "EVIDENCE_HARD_BLOCK"),
        ("calibration_evidence_yes", "EVIDENCE_HARD_BLOCK"),
        ("calibration_evidence_no", "EVIDENCE_HARD_BLOCK"),
        ("live_evidence_asset_no", "EVIDENCE_HARD_BLOCK"),
        ("live_evidence_cell_no", "EVIDENCE_HARD_BLOCK"),
        ("market_fade_blocked_no", "EVIDENCE_HARD_BLOCK"),
        # Soft/sparse/challenge insufficiency = model edge could not clear the
        # elevated evidence reserve — an edge-threshold failure, not a veto.
        ("evidence_soft_penalty_insufficient_yes", "EDGE_BELOW_DYNAMIC_THRESHOLD"),
        ("evidence_challenge_insufficient_no", "EDGE_BELOW_DYNAMIC_THRESHOLD"),
        ("evidence_sparse_matched_yes", "EDGE_BELOW_DYNAMIC_THRESHOLD"),
        ("insufficient_depth", "SIDE_NOT_LIQUID"),
        ("insufficient_depth_no", "SIDE_NOT_LIQUID"),
        ("SKIP_MARKET_NOT_READY", "BOOK_NOT_TRUSTED"),
        ("invalid_confidence", "BOOK_NOT_TRUSTED"),
        ("cost_basis_override_no", "NO_POSITIVE_EXECUTABLE_EDGE"),
        ("directional_tie", "NO_POSITIVE_EXECUTABLE_EDGE"),
        ("no_positive_executable_edge", "NO_POSITIVE_EXECUTABLE_EDGE"),
        ("no_trade_without_exit", "ENTRY_LIFECYCLE_INVALID"),
        ("allocator_not_selected", "ALLOCATION_NOT_SELECTED"),
        ("allocator_loss", "ALLOCATION_NOT_SELECTED"),
        ("cooldown: x", "RISK_OR_ALLOCATION_REJECT"),
        ("KNAPSACK_CAP", "RISK_OR_ALLOCATION_REJECT"),
        ("exception: boom", "MODEL_UNAVAILABLE"),
        ("stale_decision_hard_cap", "EXECUTION_REJECT"),
        ("post_only_passivity_no_cross", "EXECUTION_REJECT"),
        ("something_never_seen", "UNCLASSIFIED"),
    ]
    for reason, expected in cases:
        assert dt._terminal_code({}, None, False, reason, None) == expected, reason


def test_terminal_code_regime_tte_floor_is_market_unavailable():
    """Both-sides regime disablement inside the TTE floor is an expired entry
    window, not a toxic price band — distinguishable on the record."""
    assert dt._terminal_code(
        {}, None, False, "both_sides_disabled_regime", None,
        decision={"regime_reject_cause": "tte_floor"},
    ) == "TTE_ENTRY_CUTOFF"
    assert dt._terminal_code(
        {}, None, False, "both_sides_disabled_regime", None,
        decision={"regime_reject_cause": "price_band"},
    ) == "NO_ELIGIBLE_PRICE_BAND"
    # Missing discriminator keeps the conservative price-band mapping.
    assert dt._terminal_code({}, None, False, "both_sides_disabled_regime", None) == "NO_ELIGIBLE_PRICE_BAND"


def test_terminal_code_edge_sign_disambiguation():
    # Positive-but-insufficient edge -> EDGE_BELOW_DYNAMIC_THRESHOLD.
    assert dt._terminal_code({}, None, False, "yes_edge_below_threshold", 1.5) == "EDGE_BELOW_DYNAMIC_THRESHOLD"
    # Non-positive net EV -> NO_POSITIVE_EXECUTABLE_EDGE.
    assert dt._terminal_code({}, None, False, "yes_edge_below_threshold", -3.0) == "NO_POSITIVE_EXECUTABLE_EDGE"
    assert dt._terminal_code({}, None, False, "yes_edge_below_threshold", 0.0) == "NO_POSITIVE_EXECUTABLE_EDGE"


def test_terminal_code_candidate_not_selected_is_allocator_reject():
    rec_wf = _wf(
        market_discovered={"status": True},
        spot_price={"status": True},
        market_open={"status": True},
        signal_generated={"status": True},
        candidate_generated={"status": True},
    )
    assert dt._terminal_code(rec_wf, {"ticker": "T", "side": "yes"}, False, "allocator_loss", 5.0) == "ALLOCATION_NOT_SELECTED"


def test_build_asset_record_surface_fields():
    """A rejected evaluation still carries quotes, per-side EV, eligibility,
    block reasons, probabilities, and a terminal code."""
    rec = dt.build_asset_record(
        cycle_id=7,
        asset="ETH",
        decision={
            "ticker": "KXETH15M-TEST",
            "decision_id": "d1",
            "spot_price": 2685.0,
            "minutes_to_expiry": 8.0,
            "model_p_yes": 0.60,
            "model_p_no": 0.40,
            "p_yes_raw": 0.62,
            "yes_bid_cents": 52.0,
            "yes_ask_cents": 54.0,
            "no_bid_cents": 46.0,
            "no_ask_cents": 48.0,
            "yes_ev_net_cents": -1.2,
            "no_ev_net_cents": 0.8,
            "required_edge_yes_cents": 2.5,
            "required_edge_no_cents": 3.0,
            "yes_eligible": False,
            "no_eligible": False,
            "yes_block": "edge_below_threshold_yes",
            "no_block": "calibration_evidence_no",
            "rejection_reason": "no_edge_below_threshold",
        },
        waterfall=_wf(
            market_discovered={"status": True},
            spot_price={"status": True},
            market_open={"status": True},
            signal_generated={"status": False, "reason": "no_edge_below_threshold"},
        ),
        candidate=None,
    )
    assert rec["terminal_code"] == "EDGE_BELOW_DYNAMIC_THRESHOLD"
    assert rec["ticker"] == "KXETH15M-TEST"
    assert rec["yes_bid_cents"] == 52.0
    assert rec["no_ask_cents"] == 48.0
    assert rec["yes_ev_net_cents"] == -1.2
    assert rec["no_ev_net_cents"] == 0.8
    assert rec["required_edge_yes_cents"] == 2.5
    assert rec["yes_eligible"] is False
    assert rec["yes_block"] == "edge_below_threshold_yes"
    assert rec["no_block"] == "calibration_evidence_no"
    assert rec["p_yes_raw"] == 0.62
    assert rec["p_yes_calibrated"] == 0.60
    assert rec["spot_price"] == 2685.0
    assert rec["minutes_to_expiry"] == 8.0


@pytest.mark.slow
def test_compute_trade_decision_exports_candidate_surface():
    """compute_trade_decision indicators carry the per-side executable
    economics and per-side first-failing-condition on every outcome."""
    from merid.prediction.trade_decision import compute_trade_decision

    d = compute_trade_decision(
        run_id="t",
        decision_id="t1",
        ticker="KXETH15M-T",
        asset="ETH",
        spot_price=2685.0,
        strike_price=2680.0,
        seconds_to_expiry=480.0,
        yes_bid_cents=52.0,
        yes_ask_cents=54.0,
        no_bid_cents=46.0,
        no_ask_cents=48.0,
        yes_depth_cc=500.0,
        no_depth_cc=500.0,
        fee_per_contract_cents=1.75,
        annualized_vol=0.5,
        data_state="healthy",
        regime_label="normal",
        regime_probability=0.9,
    )
    ind = d.indicators
    for key in (
        "yes_bid_cents", "yes_ask_cents", "no_bid_cents", "no_ask_cents",
        "yes_entry_price_cents", "no_entry_price_cents",
        "yes_ev_net_cents", "no_ev_net_cents",
        "yes_qualifies", "no_qualifies",
    ):
        assert ind.get(key) is not None, f"missing indicator {key}"
    assert ind["yes_bid_cents"] == 52.0
    assert ind["yes_entry_price_cents"] == 54
    assert ind["no_entry_price_cents"] == 48
    # Per-side block reasons resolve to the first failing condition or None.
    assert ind["yes_qualifies"] in (True, False)
    assert ind["no_qualifies"] in (True, False)
    if not ind["yes_qualifies"]:
        assert ind["yes_block"] is not None
    if not ind["no_qualifies"]:
        assert ind["no_block"] is not None


@pytest.mark.slow
def test_compute_trade_decision_early_gate_still_stamps_quotes():
    """Layer-1/2 no-trades (e.g. data_state_not_healthy) still carry quotes
    and entry prices so the funnel record is never bare."""
    from merid.prediction.trade_decision import compute_trade_decision

    d = compute_trade_decision(
        run_id="t",
        decision_id="t2",
        ticker="KXBTC15M-T",
        asset="BTC",
        spot_price=100000.0,
        strike_price=99900.0,
        seconds_to_expiry=480.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=58.0,
        no_ask_cents=60.0,
        fee_per_contract_cents=1.75,
        annualized_vol=0.5,
    )
    assert d.selected_outcome is None
    ind = d.indicators
    assert ind["yes_bid_cents"] == 40.0
    assert ind["yes_ask_cents"] == 42.0
    assert ind["no_bid_cents"] == 58.0
    assert ind["no_ask_cents"] == 60.0
    assert ind["yes_entry_price_cents"] == 42
    assert ind["no_entry_price_cents"] == 60
