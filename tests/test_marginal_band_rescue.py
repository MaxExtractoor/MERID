"""Marginal-band rescue regression tests (2026-10-04).

The counterfactual join over rejected candidates showed candidates priced
50-89c whose net edge fell <=1c short of the stacked dynamic threshold were
net-profitable (+3.75c/contract, 76.8% counterfactual win rate, n=6,268),
while <50c and >89c near-misses were unprofitable.  The rescue applies a
bounded 1c slack to ONLY the edge-threshold qualification leg for taker-route
evaluations, stamps the slackened admission bound onto the decision so
downstream re-gates (loop lane-EV floor, router stale-decision check) compare
against what the candidate actually cleared, and flags the selection for
taker routing (the counterfactual measured ask-priced fills).
"""
import math

import pytest

import merid.prediction.trade_decision as _td


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Disable confounding gates so each test exercises the rescue leg alone."""
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", False)


def _decision(
    *,
    yes_ask: float = 55.0,
    no_ask: float = 47.0,
    route: str = "taker",
    seconds_to_expiry: float = 400.0,
):
    return _td.compute_trade_decision(
        run_id="t",
        decision_id="t",
        ticker="KXBTC15M-26AUG190930-30",
        asset="BTC",
        spot_price=100.05,
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


def _sweep_shortfall(state, yes_ask, no_ask, route, p_range):
    """Yield decisions whose YES net edge sits within the 1c slack band.

    The dynamic threshold is composed at runtime, so we probe rather than
    hardcode — a test that can't even reach the band should fail loudly.
    """
    hits = []
    for p_i in p_range:
        state["p"] = p_i / 1000.0
        d = _decision(yes_ask=yes_ask, no_ask=no_ask, route=route)
        ind = d.indicators or {}
        yb = d.yes_edge_breakdown
        if yb is None:
            continue
        thr = float(ind.get("yes_effective_required_edge_cents") or 0.0)
        shortfall = thr / 100.0 - float(yb.net_edge)
        if 0.0 < shortfall <= 0.0101:
            hits.append(d)
    assert hits, (
        f"no p_yes produced a marginal shortfall at ask={yes_ask} "
        f"route={route} — band unreachable under current threshold stack"
    )
    return hits


def test_rescue_admits_in_band_marginal_candidate(monkeypatch):
    """55c ask, net edge within 1c of threshold -> rescued + slackened bound."""
    state = _pin_and_sweep(monkeypatch)
    rescued = None
    for p_i in range(500, 995):
        state["p"] = p_i / 1000.0
        d = _decision(yes_ask=55.0)
        ind = d.indicators or {}
        if (ind.get("marginal_band") or {}).get("yes_rescued"):
            rescued = d
            break
    assert rescued is not None, "no p_yes produced a YES rescue at 55c"
    ind = rescued.indicators or {}
    assert rescued.selected_outcome == "yes", rescued.no_trade_reason
    assert ind.get("marginal_band_rescue") is True
    bound = float(ind["marginal_band_admission_bound_cents"]) / 100.0
    assert math.isclose(float(rescued.min_required_edge), bound, abs_tol=1e-9)
    assert math.isclose(float(rescued.edge_threshold), bound, abs_tol=1e-9)
    assert math.isclose(
        float(ind["yes_effective_required_edge_cents"]),
        bound * 100.0,
        abs_tol=1e-6,
    )
    # Same pinned p on the maker route gets no slack — its reported bound is
    # the true un-slackened threshold, exactly 1c above the rescue bound.
    d_maker = _decision(yes_ask=55.0, route="maker")
    true_bound = float(
        (d_maker.indicators or {}).get("yes_effective_required_edge_cents")
        or -999
    )
    assert math.isclose(true_bound - bound * 100.0, 1.0, abs_tol=1e-6)


def test_no_rescue_below_band(monkeypatch):
    """40c ask at the same marginal shortfall -> still rejected (sub-50c)."""
    state = _pin_and_sweep(monkeypatch)
    for d in _sweep_shortfall(state, 40.0, 62.0, "taker", range(380, 560)):
        ind = d.indicators or {}
        assert d.selected_outcome is None
        assert not (ind.get("marginal_band") or {}).get("yes_rescued")
        assert ind.get("marginal_band_rescue") is not True


def test_band_boundaries():
    """Slack is nonzero only inside [50, 89]c — the empirically profitable
    near-miss band.  The 90c+ tail cohort LOST -3.76c/trade at 86.8% win rate
    and must stay hard-gated."""
    slack = _td.MERID_MARGINAL_BAND_SLACK
    assert _td._marginal_band_slack(50.0) == slack
    assert _td._marginal_band_slack(70.0) == slack
    assert _td._marginal_band_slack(89.0) == slack
    assert _td._marginal_band_slack(89.999) == slack
    assert _td._marginal_band_slack(90.0) == 0.0
    assert _td._marginal_band_slack(95.0) == 0.0
    assert _td._marginal_band_slack(49.999) == 0.0
    assert _td._marginal_band_slack(10.0) == 0.0
    assert _td._marginal_band_slack(None) == 0.0


def test_no_rescue_above_band_via_slack_boundary(monkeypatch):
    """A >=90c ask can never produce a rescue: the slack function returns 0
    above the band, so even a marginal shortfall is rejected at the full
    threshold.  (End-to-end sweep is unreachable — tail calibration pins
    p_sel below ask at >=88c, so net edge can never be marginal-positive.)"""
    state = _pin_and_sweep(monkeypatch)
    for p in (0.90, 0.95, 0.99):
        state["p"] = p
        d = _decision(yes_ask=92.0, no_ask=10.0)
        ind = d.indicators or {}
        assert ind.get("marginal_band") is None
        assert ind.get("marginal_band_rescue") is not True


def test_no_rescue_beyond_slack(monkeypatch):
    """Shortfall > 1c slack -> still rejected inside the band."""
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.50
    d = _decision(yes_ask=55.0)
    ind = d.indicators or {}
    yb = d.yes_edge_breakdown
    thr = float(ind.get("yes_effective_required_edge_cents") or 0.0)
    assert yb is not None and (thr / 100.0 - float(yb.net_edge)) > 0.0101
    assert d.selected_outcome is None
    assert not (ind.get("marginal_band") or {}).get("yes_rescued")


def test_maker_route_does_not_inherit_slack(monkeypatch):
    """Resting-bid fills are a different distribution — no slack on maker."""
    state = _pin_and_sweep(monkeypatch)
    for d in _sweep_shortfall(state, 55.0, 47.0, "maker", range(550, 800)):
        ind = d.indicators or {}
        assert ind.get("marginal_band") is None
        assert ind.get("marginal_band_rescue") is not True


def test_rescue_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(_td, "MERID_MARGINAL_BAND_ENABLED", False)
    state = _pin_and_sweep(monkeypatch)
    for d in _sweep_shortfall(state, 55.0, 47.0, "taker", range(550, 800)):
        ind = d.indicators or {}
        assert ind.get("marginal_band") is None
        assert ind.get("marginal_band_rescue") is not True


def test_non_rescued_candidate_keeps_full_threshold(monkeypatch):
    """A candidate clearing the full threshold is NOT a rescue and keeps the
    un-slackened bound so submit-time decay protection is unchanged."""
    state = _pin_and_sweep(monkeypatch)
    state["p"] = 0.80
    d = _decision(yes_ask=55.0)
    ind = d.indicators or {}
    assert d.selected_outcome == "yes"
    assert ind.get("marginal_band_rescue") is not True
    eff = float(ind.get("yes_effective_required_edge_cents") or -999)
    assert math.isclose(float(d.min_required_edge), eff / 100.0, abs_tol=1e-6)
    assert math.isclose(float(d.edge_threshold), eff / 100.0, abs_tol=1e-6)
