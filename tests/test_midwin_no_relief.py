"""Mid-window relief regression tests (2026-10-20).

The dynamic bound over-rejects mid-window candidates on BOTH sides: the
authoritative settled recut (rejected_candidates x settlement_outcomes,
first miss per ticker+side, positive net edge, >=35c, TTE 180-660s,
claim>=4c) measured NO +5.83c/tr and YES +3.68c/tr — with BTC YES the
only flat-negative cell (-0.3c/tr), excluded via
``MERID_EDGE_MIDWIN_EXCLUDED_ASSETS_YES``.  ``*_RELIEF_CENTS_{NO,YES}``
drops the effective bound by the relief amount (clamped at the NPEE floor
of 0), while the model-edge floor (raw claim >=4c) still gates every
selection.

These tests pin:
  * an in-domain NO/YES miss with positive executable edge is admitted
    and stamped ``midwin_{side}_relief`` with the relieved bound in
    ``min_required_edge`` / ``edge_threshold`` (the bound the candidate
    actually cleared - submit-time revalidation must honor it);
  * relief=0 leaves the bound untouched (backward-compatible default);
  * the domain gates: TTE outside [180,660]s, price <35c, and assets in
    the YES exclusion set get no relief;
  * the NPEE floor: a negative-edge candidate is never relieved;
  * the 4c raw-claim floor still vetoes relieved selections.
"""
import math

import pytest

import merid.prediction.trade_decision as _td


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Disable confounding gates so each test exercises the relief leg alone."""
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", False)
    monkeypatch.setenv("MERID_THRESHOLD_CELLS", "0")
    monkeypatch.setenv("MERID_PROVISIONAL_LANE", "0")
    monkeypatch.setattr(_td, "MERID_EDGE_MARGINAL_RELIEF_CENTS", 0.0)
    monkeypatch.setattr(_td, "MERID_EDGE_MID_BAND_RELIEF_CENTS", 0.0)
    # Pin the relief domain to the production-measured window so the tests
    # stay deterministic regardless of .env.
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_TTE_LO_S", 180.0)
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_TTE_HI_S", 660.0)
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_MIN_PRICE_CENTS_NO", 35.0)
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_MIN_PRICE_CENTS_YES", 35.0)
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_EXCLUDED_ASSETS_YES", frozenset({"BTC"}))
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 0.0)
    monkeypatch.setattr(_td, "MERID_MODEL_EDGE_FLOOR_CENTS", 4.0)


def _decision(
    *,
    yes_ask: float = 45.0,
    no_ask: float = 55.0,
    route: str = "taker",
    seconds_to_expiry: float = 400.0,
    asset: str = "SOL",
    spot_price: float = 99.85,
):
    return _td.compute_trade_decision(
        run_id="t",
        decision_id="t",
        ticker=f"KX{asset}15M-26AUG190930-30",
        asset=asset,
        spot_price=spot_price,
        strike_price=100.0,
        seconds_to_expiry=seconds_to_expiry,
        yes_bid_cents=yes_ask - 2.0,
        yes_ask_cents=yes_ask,
        no_bid_cents=no_ask - 2.0,
        no_ask_cents=no_ask,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route=route,
    )


def _pin_and_sweep(monkeypatch):
    """Install a p_yes pin controlled by the returned state dict."""
    real = _td._resolve_annualized_vol
    state = {"p": 0.5}

    def _wrapped(*args, **kwargs):
        resolved_vol, vol_source, band_min, band_max, components = real(
            *args, **kwargs
        )
        if components is not None:
            components["p_yes_raw"] = state["p"]
        return resolved_vol, vol_source, band_min, band_max, components

    monkeypatch.setattr(_td, "_resolve_annualized_vol", _wrapped)
    return state


def _find_relieved(state, **kwargs):
    """Sweep p_yes until a decision is admitted under the midwin relief stamp.

    ``no_effective_required_edge_cents`` already carries the relieved bound
    once relief is on, so the cohort can only be identified by the
    ``midwin_no_relief`` stamp itself.
    """
    for p_i in range(5, 995):
        state["p"] = p_i / 1000.0
        d = _decision(**kwargs)
        if (d.indicators or {}).get("midwin_no_relief") is True:
            return state["p"], d
    pytest.fail(
        f"no p_yes produced a midwin-relieved admission at {kwargs} - "
        "relief never fired"
    )


def test_relief_admits_in_domain_no_miss(monkeypatch):
    """Relief=8c: an in-domain NO candidate with positive net edge below the
    full bound is admitted, stamped midwin_no_relief, and carries the
    relieved bound into min_required_edge for submit-time revalidation."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    _, d = _find_relieved(state)
    ind = d.indicators or {}
    assert d.selected_outcome == "no", d.no_trade_reason
    assert ind.get("midwin_no_relief") is True
    assert ind.get("no_midwin_relief_cents") == 8.0
    bound = float(ind["midwin_no_admission_bound_cents"]) / 100.0
    assert math.isclose(
        float(d.min_required_edge), bound, abs_tol=1e-9
    )
    assert math.isclose(
        float(d.edge_threshold), bound, abs_tol=1e-9
    )


def test_relief_disabled_keeps_bound(monkeypatch):
    """Default relief=0: no midwin stamps on any decision in the sweep."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 0.0)
    state = _pin_and_sweep(monkeypatch)
    for p_i in range(5, 995):
        state["p"] = p_i / 1000.0
        d = _decision()
        ind = d.indicators or {}
        assert ind.get("no_midwin_relief_cents") is None
        assert ind.get("midwin_no_relief") is not True


def test_relief_tte_floor_excludes_early_tail(monkeypatch):
    """TTE below 180s: the domain gate denies relief to the identical
    candidate that was relieved in-domain (the counterfactual's final-tail
    cohort was not measured positive)."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    p_in_domain, _ = _find_relieved(state)
    state["p"] = p_in_domain
    d = _decision(seconds_to_expiry=120.0)
    ind = d.indicators or {}
    assert ind.get("no_midwin_relief_cents") is None
    assert ind.get("midwin_no_relief") is not True


def test_relief_tte_ceiling_excludes_late_misses(monkeypatch):
    """TTE above 660s: misses there measured -1.2c/tr - no relief."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    p_in_domain, _ = _find_relieved(state)
    state["p"] = p_in_domain
    d = _decision(seconds_to_expiry=700.0)
    ind = d.indicators or {}
    assert ind.get("no_midwin_relief_cents") is None
    assert ind.get("midwin_no_relief") is not True


def test_relief_price_floor_excludes_cheap_no(monkeypatch):
    """NO executable below 35c: the FLB-toxic sub-35c region keeps its bound
    for the same p that was relieved in-domain at 55c."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    p_in_domain, _ = _find_relieved(state)
    state["p"] = p_in_domain
    d = _decision(yes_ask=70.0, no_ask=32.0, spot_price=99.7)
    ind = d.indicators or {}
    assert ind.get("no_midwin_relief_cents") is None
    assert ind.get("midwin_no_relief") is not True


def test_relief_never_for_negative_edge(monkeypatch):
    """NPEE is the economic floor: a negative-net NO candidate can never be
    relieved - relief lowers the bound, not the sign of the edge."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    saw_neg = False
    for p_i in range(5, 995):
        state["p"] = p_i / 1000.0
        d = _decision()
        nb = d.no_edge_breakdown
        if nb is None:
            continue
        if float(nb.net_edge) >= 0.0:
            continue
        saw_neg = True
        ind = d.indicators or {}
        assert ind.get("midwin_no_relief") is not True
        assert d.selected_outcome != "no"
    assert saw_neg, "no negative-edge NO candidate constructed"


def test_no_relief_does_not_leak_to_yes_side(monkeypatch):
    """NO relief armed alone never relieves a YES miss — the side bound is
    independent (a YES miss exists somewhere in this sweep by
    construction, and no midwin stamp may appear on it)."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    saw_yes_miss = False
    for p_i in range(500, 995):
        state["p"] = p_i / 1000.0
        d = _decision(yes_ask=55.0, no_ask=45.0, spot_price=100.15)
        ind = d.indicators or {}
        yb = d.yes_edge_breakdown
        if yb is None:
            continue
        thr = float(ind.get("yes_effective_required_edge_cents") or 0.0)
        net = float(yb.net_edge)
        if 0.0 < net < thr / 100.0:
            saw_yes_miss = True
            assert ind.get("midwin_no_relief") is not True
            assert ind.get("midwin_yes_relief") is not True
            assert ind.get("yes_midwin_relief_cents") is None
            assert d.selected_outcome is None
    assert saw_yes_miss, "no YES-side miss constructed"


def test_relief_still_gated_by_model_edge_floor(monkeypatch):
    """The 4c raw-claim floor is the cohort safety: a relieved selection with
    raw claim <4c still dies at apply_model_edge_floor_gate."""
    from dataclasses import replace

    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_NO", 8.0)
    state = _pin_and_sweep(monkeypatch)
    _, d = _find_relieved(state)
    assert d.selected_outcome == "no"
    ind = dict(d.indicators or {})
    # Force a sub-4c raw claim on the admitted selection.
    ind["p_no_model_raw"] = (
        float(d.no_edge_breakdown.executable_entry_price) + 0.02
    )
    d2 = replace(d, indicators=ind)
    out = _td.apply_model_edge_floor_gate(d2)
    assert out.selected_outcome is None
    assert out.no_trade_reason.startswith("model_edge_floor:")


# ---------------------------------------------------------------------------
# YES-side relief (2026-10-20 recut: YES +3.68c/tr on the released domain,
# BTC YES -0.3c — excluded; the earlier -2.9c figure did not reproduce)
# ---------------------------------------------------------------------------


# The test fixture's fitted YES cells cap the cost-basis probability below
# every viable floor, so a YES side can never reach selection here — the
# post-selection stamp path (shared verbatim with NO, tested above) cannot
# be exercised for YES in this harness.  These tests therefore pin the
# pre-selection contract the new code owns: the bound must drop iff the
# candidate is in the released domain, and the domain gates are
# side-symmetric (TTE window, price floor, exclusion set, NPEE floor).
# YES relief arms only where a positive YES bound exists to relieve — in
# this fixture that is TTE=660s (route bound 2c).
_YES_REL_DOMAIN = dict(seconds_to_expiry=660.0)


def test_yes_relief_arms_in_domain(monkeypatch):
    """Relief=8c on a non-excluded asset inside the domain: the relief
    amount is stamped, and the bound the gate compares against
    (``yes_effective_gate_edge_cents``) drops from the positive route
    bound to the relieved one.  A positive-edge miss lands ``rescued``
    semantics: its ``effective_required_edge`` stamp carries the relieved
    bound, not the route bound."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 8.0)
    state = _pin_and_sweep(monkeypatch)
    # Find a p whose YES gate_ev is a positive-edge miss of the route bound.
    state["p"] = 0.8
    d = _decision(
        yes_ask=55.0, no_ask=45.0, spot_price=100.15, **_YES_REL_DOMAIN
    )
    ind = d.indicators or {}
    assert ind.get("yes_midwin_relief_cents") == 8.0
    route = ind.get("yes_route_required_edge_cents")
    assert route is not None and route > 0.0
    assert ind.get("yes_effective_gate_edge_cents") == max(0.0, route - 8.0)
    # In the miss band (0 < gate_ev < route bound): the stamped required
    # edge is the relieved bound — the bound the side actually cleared.
    found_miss = False
    for p_i in range(400, 995):
        state["p"] = p_i / 1000.0
        d = _decision(
            yes_ask=55.0, no_ask=45.0, spot_price=100.15, **_YES_REL_DOMAIN
        )
        ind = d.indicators or {}
        gev = ind.get("yes_gate_ev_cents")
        if gev is None or not (0.0 < gev < route):
            continue
        found_miss = True
        assert ind.get("yes_effective_required_edge_cents") == max(
            0.0, route - 8.0
        )
        break
    assert found_miss, "no YES-side positive-edge miss constructed"


def test_yes_relief_excluded_asset_keeps_bound(monkeypatch):
    """BTC is in the exclusion set (its YES miss cohort measured -0.3c/tr):
    the identical in-domain eval must keep the unrelieved 2c bound."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 8.0)
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.8
    d = _decision(
        asset="BTC", yes_ask=55.0, no_ask=45.0, spot_price=100.15,
        **_YES_REL_DOMAIN,
    )
    ind = d.indicators or {}
    assert ind.get("yes_midwin_relief_cents") is None
    # Bound unchanged: effective equals the route bound it started from.
    assert (
        ind.get("yes_effective_required_edge_cents")
        == ind.get("yes_route_required_edge_cents")
    )


def test_yes_relief_disabled_keeps_bound(monkeypatch):
    """Default relief=0: bound and stamps untouched in-domain."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 0.0)
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.8
    d = _decision(
        yes_ask=55.0, no_ask=45.0, spot_price=100.15, **_YES_REL_DOMAIN
    )
    ind = d.indicators or {}
    assert ind.get("yes_midwin_relief_cents") is None
    assert (
        ind.get("yes_effective_required_edge_cents")
        == ind.get("yes_route_required_edge_cents")
    )


def test_yes_relief_price_floor_excludes_cheap_yes(monkeypatch):
    """YES executable below 35c keeps its bound even in-domain."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 8.0)
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.8
    d = _decision(
        yes_ask=30.0, no_ask=72.0, spot_price=100.3, **_YES_REL_DOMAIN
    )
    ind = d.indicators or {}
    assert ind.get("yes_midwin_relief_cents") is None


def test_yes_relief_tte_bounds(monkeypatch):
    """TTE outside [180,660]s: identical candidate gets no relief — at 700s
    the route bound is again 2c and must stay 2c."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 8.0)
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.8
    d = _decision(
        yes_ask=55.0, no_ask=45.0, spot_price=100.15,
        seconds_to_expiry=700.0,
    )
    ind = d.indicators or {}
    assert ind.get("yes_midwin_relief_cents") is None
    assert (
        ind.get("yes_effective_required_edge_cents")
        == ind.get("yes_route_required_edge_cents")
    )


def test_yes_relief_never_for_negative_edge(monkeypatch):
    """NPEE is the economic floor on YES too: relief lowers the bound but
    never the sign — no negative-net YES candidate may be selected."""
    monkeypatch.setattr(_td, "MERID_EDGE_MIDWIN_RELIEF_CENTS_YES", 8.0)
    state = _pin_and_sweep(monkeypatch)
    saw_neg = False
    for p_i in range(500, 995):
        state["p"] = p_i / 1000.0
        d = _decision(yes_ask=55.0, no_ask=45.0, spot_price=100.15)
        yb = d.yes_edge_breakdown
        if yb is None:
            continue
        if float(yb.net_edge) >= 0.0:
            continue
        saw_neg = True
        ind = d.indicators or {}
        assert ind.get("midwin_yes_relief") is not True
        assert d.selected_outcome != "yes"
    assert saw_neg, "no negative-edge YES candidate constructed"
