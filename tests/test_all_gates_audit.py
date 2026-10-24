"""Phase-B all-gates auditor regression tests (shadow-only).

Covers the acceptance-criteria invariants: fee symmetry at complementary
prices, independent both-side evaluation, the EV-sum identity + residual,
the 50c coefficient boundary, cell-override precedence, sole-blocker
semantics, NOT_EVALUABLE/ERROR handling, env-overlay restoration, and
zero-mutation of inputs.
"""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal  # noqa: E402

from merid.prediction.all_gates_audit import (  # noqa: E402
    AuditSummary, ERROR, FAIL, NOT_EVALUABLE, PASS, GateResult,
    accounting_block, asset_of, attribute, evaluate_record,
    threshold_components)


# ---------------------------------------------------------------------------
# Fee symmetry (Kalshi standard taker formula is price-symmetric)
# ---------------------------------------------------------------------------

def test_fee_symmetry_complementary_prices():
    from merid.event_venues.kalshi.parabolic_fees import (
        kalshi_fee_cents_exact)
    for px in (5, 25, 40, 45, 50):
        a = kalshi_fee_cents_exact(Decimal(px) / 100, 1, "taker")
        b = kalshi_fee_cents_exact(Decimal(100 - px) / 100, 1, "taker")
        assert a == b, f"taker fee asymmetric at {px}/{100-px}"


# ---------------------------------------------------------------------------
# Gate-state attribution semantics
# ---------------------------------------------------------------------------

def _g(gid, status, cat="economics"):
    return GateResult(gid, cat, status)


def test_sole_blocker_strict():
    r = attribute([_g("a", PASS), _g("b", FAIL, "cell_policy"),
                   _g("c", PASS)])
    assert r["sole_blocking_gate"] == "b"
    assert r["sole_blocking_policy_family"] == "cell_policy"
    assert r["attribution"] == "otherwise_admissible_at_evaluated_size"


def test_not_evaluable_blocks_definitive_sole_blocker():
    r = attribute([_g("a", PASS), _g("b", FAIL, "cell_policy"),
                   _g("c", NOT_EVALUABLE)])
    assert r["attribution"] == "indeterminate_unresolved_gates"
    assert r["sole_blocking_gate"] == "b"  # reported but flagged


def test_error_blocks_definitive_sole_blocker():
    r = attribute([_g("a", PASS), _g("b", FAIL), _g("c", ERROR)])
    assert "indeterminate" in r["attribution"]


def test_multiple_blockers():
    r = attribute([_g("a", FAIL, "economics"),
                   _g("b", FAIL, "cell_policy"), _g("c", PASS)])
    assert r["attribution"] == "multiple_blockers"
    assert r["sole_blocking_gate"] is None
    assert r["sole_blocking_policy_family"] is None


def test_single_family_multiple_gates():
    r = attribute([_g("a", FAIL, "cell_policy"),
                   _g("b", FAIL, "cell_policy"), _g("c", PASS)])
    assert r["attribution"] == "single_family_multiple_gates"
    assert r["sole_blocking_gate"] is None
    assert r["sole_blocking_policy_family"] == "cell_policy"


def test_all_pass_and_no_result():
    assert attribute([_g("a", PASS)])["attribution"] == "all_pass"
    assert attribute([_g("a", NOT_EVALUABLE)])["attribution"] == \
        "indeterminate_no_result"


# ---------------------------------------------------------------------------
# EV-sum identity + accounting residual
# ---------------------------------------------------------------------------

def _record(**kw):
    base = {
        "type": "decision_record", "ticker": "KXDOGE15M-26OCT241600-00",
        "ts": 1792870000.0,
        "yes_ask_cents": 56, "no_ask_cents": 56,
        "yes_ev_net_cents": -8.12, "no_ev_net_cents": -7.19,
        "yes_fee_reserve_cents": 1.75, "no_fee_reserve_cents": 1.75,
        "yes_impact_reserve_cents": 0.175, "no_impact_reserve_cents": 0.175,
        "yes_model_uncertainty_reserve_cents": 2.0,
        "no_model_uncertainty_reserve_cents": 2.0,
        "yes_adverse_selection_reserve_cents": 0.0,
        "no_adverse_selection_reserve_cents": 0.0,
        "book_source_reserve_cents": 0.0,
        "yes_effective_required_edge_cents": 2.0,
        "no_effective_required_edge_cents": 3.4964,
        "p_yes_calibrated": 0.543, "p_no_calibrated": 0.457,
        "book_state": "trusted", "data_state": "healthy",
        "evidence_yes": {"allowed": True, "code": "CELL_EVIDENCE_PASS"},
        "evidence_no": {"allowed": False, "code": "SOFT_PENALTY_INSUFFICIENT",
                        "admission_state": "SOFT_PENALTY"},
    }
    base.update(kw)
    return base


def test_ev_sum_identity_decomposition():
    acc = accounting_block(_record())
    assert acc["observed_ev_sum_cents"] == pytest.approx(-15.31)
    # expected = -(ask sum - 100) - combined costs
    assert acc["expected_ev_sum_cents"] == pytest.approx(
        -(112 - 100) - 2 * (1.75 + 0.175 + 2.0))
    # residual isolates the unexplained component
    assert acc["ev_sum_residual_cents"] == pytest.approx(
        acc["observed_ev_sum_cents"] - acc["expected_ev_sum_cents"])
    assert acc["entry_price_excess_cents"] == pytest.approx(12.0)


def test_ev_sum_identity_exact_when_consistent():
    # Construct a record where identity holds exactly: asks sum 102,
    # costs 2c/side -> expected sum = -2 - 4 = -6
    r = _record(yes_ask_cents=52, no_ask_cents=50,
                yes_ev_net_cents=-3.0, no_ev_net_cents=-3.0,
                yes_fee_reserve_cents=1.0, no_fee_reserve_cents=1.0,
                yes_impact_reserve_cents=0.0, no_impact_reserve_cents=0.0,
                yes_model_uncertainty_reserve_cents=1.0,
                no_model_uncertainty_reserve_cents=1.0)
    acc = accounting_block(r)
    assert acc["expected_ev_sum_cents"] == pytest.approx(-6.0)
    assert acc["ev_sum_residual_cents"] == pytest.approx(0.0)


def test_generalized_minus_complement_delta():
    """Holding prices/costs fixed, generalized - complement == 100(q_sum-1).

    Reconciliation for the 20c-vs-29c example discrepancy: the two expected
    values must differ by exactly the probability-sum term.
    """
    for qy, qn in ((0.42, 0.38), (0.5, 0.5), (0.6, 0.55)):
        base = dict(
            yes_ask_cents=56, no_ask_cents=56,
            yes_ev_net_cents=-8.0, no_ev_net_cents=-7.0,
            yes_fee_reserve_cents=1.75, no_fee_reserve_cents=1.75,
            yes_impact_reserve_cents=0.175, no_impact_reserve_cents=0.175,
            yes_model_uncertainty_reserve_cents=2.0,
            no_model_uncertainty_reserve_cents=2.0,
            p_yes_calibrated=0.543, p_no_calibrated=0.457)
        gen = accounting_block(_record(
            yes_p_selected=qy, no_p_selected=qn, **base))
        comp = accounting_block(_record(**base))  # fallback: calibrated pair
        delta = gen["expected_ev_sum_cents"] - comp["expected_ev_sum_cents"]
        assert delta == pytest.approx(100.0 * (qy + qn - 1.0))


def test_probability_semantics_classification():
    bound = accounting_block(_record(yes_p_selected=0.42,
                                     no_p_selected=0.38))
    assert bound["ev_probability_semantics"] == "CONSERVATIVE_BOUND"
    assert bound["selected_probability_gap"] == pytest.approx(0.2)
    assert bound["record_class"] == "exact_selected_probability"
    fb = accounting_block(_record())
    assert fb["ev_probability_basis"] == "calibrated_complement_fallback"
    assert fb["record_class"] == "fallback_estimate"
    insuf = accounting_block({"type": "decision_record",
                              "ticker": "KXBTC15M-1"})
    assert insuf["record_class"] == "insufficient_telemetry"


def test_waterfall_separates_tightening_from_costs():
    a = evaluate_record(_record(yes_p_selected=0.42, no_p_selected=0.52))
    wf = a["accounting"]["waterfall"]["yes"]
    # point estimate 0.543 vs selected 0.42 -> 12.3c probability tightening
    assert wf["probability_tightening_cents"] == pytest.approx(12.3, abs=0.01)
    assert wf["bound_net_ev_cents"] == pytest.approx(-8.12)
    assert wf["admission_margin_cents"] == pytest.approx(-8.12 - 2.0)


def test_missing_prices_marks_residual_unavailable():
    r = _record()
    del r["yes_ask_cents"], r["no_ask_cents"]
    del r["yes_ev_net_cents"], r["no_ev_net_cents"]
    acc = accounting_block(r)
    assert acc["ev_sum_residual_cents"] is None
    assert acc["price_basis"] == "unavailable"


# ---------------------------------------------------------------------------
# Both-side independence
# ---------------------------------------------------------------------------

def test_yes_failure_does_not_suppress_no_eval():
    a = evaluate_record(_record())
    assert a is not None
    for side in ("yes", "no"):
        ids = {g["gate_id"] for g in a["sides"][side]["gates"]}
        assert f"{side}_positive_ev" in ids
        assert f"{side}_admission_margin" in ids
        assert f"{side}_evidence" in ids
    # YES passed evidence, NO failed -> distinct verdicts, both evaluated
    yev = [g for g in a["sides"]["yes"]["gates"]
           if g["gate_id"] == "yes_evidence"][0]
    nev = [g for g in a["sides"]["no"]["gates"]
           if g["gate_id"] == "no_evidence"][0]
    assert yev["status"] == PASS and nev["status"] == FAIL


# ---------------------------------------------------------------------------
# Threshold decomposition + 50c boundary + cell precedence
# ---------------------------------------------------------------------------

def test_convexity_k_boundary_exposed():
    lo = threshold_components("DOGE", "no", 49, 400)
    hi = threshold_components("DOGE", "no", 51, 400)
    assert lo["convexity_k"] == 0.04
    assert hi["convexity_k"] == 0.02
    # K discontinuity visible: term at 49c exceeds term at 51c
    assert lo["convexity_term_cents"] > hi["convexity_term_cents"]


def test_threshold_decomposition_components_present():
    d = threshold_components("DOGE", "no", 44, 400)
    for k in ("convexity_k", "convexity_term_cents", "base_threshold_cents",
              "band_relief_cents", "final_required_edge_cents",
              "override_operation", "cell_registered"):
        assert k in d


def test_env_overlay_restored():
    before = os.environ.get("MERID_EDGE_CONVEXITY_K_LO")
    threshold_components("DOGE", "no", 40, 400,
                         {"MERID_EDGE_CONVEXITY_K_LO": "0.02"})
    assert os.environ.get("MERID_EDGE_CONVEXITY_K_LO") == before


def test_symmetric_variant_lowers_sub50_threshold():
    base = threshold_components("DOGE", "no", 40, 400)
    var = threshold_components("DOGE", "no", 40, 400,
                               {"MERID_EDGE_CONVEXITY_K_LO": "0.02"})
    # cell override may still dominate final; compare formula totals
    assert var["formula_total_cents"] <= base["formula_total_cents"]
    assert var["convexity_k"] == 0.02


# ---------------------------------------------------------------------------
# Zero mutation + lane coverage
# ---------------------------------------------------------------------------

def test_evaluate_record_does_not_mutate_input():
    rec = _record()
    snapshot = copy.deepcopy(rec)
    evaluate_record(rec)
    assert rec == snapshot


def test_asset_of_mapping():
    assert asset_of("KXBTC15M-26OCT241600-00") == "BTC"
    assert asset_of("KXXRP15M-26OCT241600-00") == "XRP"
    assert asset_of("") == "UNKNOWN"


def test_all_ten_lanes_appear():
    s = AuditSummary()
    s.add(evaluate_record(_record()))
    report = s.report()
    for a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        for side in ("YES", "NO"):
            assert f"{a}_{side}" in report


def test_not_evaluable_gate_states_are_explicit():
    a = evaluate_record(_record())
    for side in ("yes", "no"):
        pr = [g for g in a["sides"][side]["gates"]
              if g["gate_id"] == f"{side}_portfolio_risk"][0]
        assert pr["status"] == NOT_EVALUABLE
