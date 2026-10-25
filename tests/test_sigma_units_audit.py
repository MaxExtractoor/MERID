"""Sigma-unit audit: endpoint lognormal digital vs settlement-average model.

Diagnostic-only checks required by the EV/volatility reconciliation phase:

  * the estimator emits RELATIVE log-return sigma per sqrt(year);
  * the endpoint d2 consumes sigma_rel directly (dimensionless);
  * the settlement model converts sigma_rel -> sigma_abs via x S_latest;
  * the discrete remaining-average variance keeps price^2 units;
  * scale invariance, boundary continuity, expired/missing-sample rules.

No production behavior is exercised or mutated here - every test builds
fresh SettlementState/EdgeBreakdown inputs.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merid.prediction import realized_vol, settlement_distribution as sd
from merid.prediction.trade_decision import (
    _compute_bachelier_components,
    _compute_market_implied_vol,
)

_SPY = 365.0 * 24.0 * 60.0 * 60.0  # 31_536_000 s

# Representative decision-time snapshots (asset: latest_rti, strike).
_SNAPSHOTS = {
    "BTC": (67000.0, 67100.0),
    "ETH": (3200.0, 3210.0),
    "SOL": (155.0, 155.4),
    "XRP": (0.62, 0.621),
    "DOGE": (0.21, 0.2105),
}

_SIGMA_REL = {"BTC": 0.60, "ETH": 0.80, "SOL": 1.00, "XRP": 1.00, "DOGE": 1.20}


def _state(*, tte: float, latest: float, strike: float, observed=None, asset="BTC"):
    """Build a pre_window/in_window/expired SettlementState at whole-second tte."""
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    now = expiry - timedelta(seconds=tte)
    window_start = expiry - timedelta(seconds=60)
    obs = list(observed or [])
    obs_sum = sum((v for _, v in obs), Decimal("0"))
    phase = "expired" if tte <= 0 else ("in_window" if tte <= 60 else "pre_window")
    elapsed = max(0.0, min(60.0, (now - window_start).total_seconds()))
    remaining = 0 if phase == "expired" else max(0, int(60 - int(elapsed)))
    return sd.SettlementState(
        ticker=f"KX{asset}15M-T",
        asset=asset,
        strike_price=strike,
        latest_rti=latest,
        latest_rti_decimal=None,
        seconds_to_expiry=tte,
        expiry_ts=expiry,
        window_start_ts=window_start,
        now_ts=now,
        observed_samples=obs,
        observed_count=len(obs),
        observed_sum=obs_sum,
        remaining_count=remaining,
        latest_rti_ts=now,
        latest_rti_age_ms=0,
        phase=phase,
        source="cf_rti",
        settlement_reference="cfb_rti_live",
    )


def _obs_series(now: datetime, n: int, base: float) -> list:
    """n consecutive 1-second samples ending at `now`."""
    return [
        (now - timedelta(seconds=i), Decimal(str(base)))
        for i in range(n - 1, -1, -1)
    ]


# ---------------------------------------------------------------------------
# 1. Time-basis: every module annualizes with the same seconds-per-year.
# ---------------------------------------------------------------------------

def test_time_basis_constants_agree():
    assert realized_vol.SECONDS_PER_YEAR == _SPY
    assert sd._SECONDS_PER_YEAR == _SPY
    # Endpoint t_years is the same denominator (verified via components).
    c = _compute_bachelier_components(100.0, 100.0, _SPY, 0.5)
    assert c["t_years"] == pytest.approx(1.0)


def test_seconds_to_year_conversion_reproduces_same_physical_vol():
    """The same per-second return variance must annualize identically whether
    the estimator is fed 1-second-spaced or 5-second-spaced samples."""
    target_var_per_sec = 1e-8
    expected = math.sqrt(target_var_per_sec * _SPY)
    ests = []
    for dt, step in ((1.0, 1e-4), (5.0, math.sqrt(5.0 * 1e-8))):
        tr = realized_vol.RealizedVolTracker(
            half_life_s=10.0, min_samples=10, min_span_s=1.0,
            max_sample_age_s=1e9, max_dt_s=10.0,
        )
        t0 = 1_000_000.0
        tr.record("BTC", 100.0, t0)
        px, sign = 100.0, -1.0
        n = int(round(300.0 / dt))
        for i in range(n):
            sign = -sign
            px *= math.exp(sign * step)
            tr.record("BTC", px, t0 + (i + 1) * dt)
        ests.append(tr.annualized_vol("BTC", now=t0 + n * dt + dt))
    for e in ests:
        assert e is not None
        # converged EWMA var/sec -> sigma_ann = sqrt(var_per_sec * SPY) = 0.56157
        assert e.value == pytest.approx(expected, rel=0.05)
    assert ests[0].value == pytest.approx(ests[1].value, rel=0.02)


# ---------------------------------------------------------------------------
# 2. sigma_rel vs sigma_abs: the conversion must multiply by the ref price.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_settlement_sigma_conversion_uses_latest_rti(asset):
    latest, strike = _SNAPSHOTS[asset]
    sig = _SIGMA_REL[asset]
    # _price_volatility is the sole rel->abs conversion in the chain.
    sigma_abs = sd._price_volatility(sig, latest)
    assert sigma_abs == pytest.approx(sig * latest)
    # Feeding the absolute price-vol as the sigma_rel input would inflate
    # std by a factor of the price itself -- the conversion is explicit,
    # never silent.
    st = _state(tte=120.0, latest=latest, strike=strike, asset=asset)
    d_rel = sd.compute_settlement_distribution(st, sig)
    d_wrong = sd.compute_settlement_distribution(st, sigma_abs)
    assert d_wrong.std == pytest.approx(d_rel.std * latest, rel=1e-9)


# ---------------------------------------------------------------------------
# 3. Scale invariance: z-scores unchanged under common price rescaling.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_endpoint_d2_scale_invariant(asset):
    latest, strike = _SNAPSHOTS[asset]
    k = 3.7
    a = _compute_bachelier_components(latest, strike, 300.0, _SIGMA_REL[asset])
    b = _compute_bachelier_components(latest * k, strike * k, 300.0, _SIGMA_REL[asset])
    assert a["z_score"] == pytest.approx(b["z_score"], abs=1e-12)
    assert a["p_yes_raw"] == pytest.approx(b["p_yes_raw"], abs=1e-12)


@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
@pytest.mark.parametrize("tte", [300.0, 90.0])
def test_settlement_z_scale_invariant(asset, tte):
    latest, strike = _SNAPSHOTS[asset]
    k = 2.5
    st1 = _state(tte=tte, latest=latest, strike=strike, asset=asset)
    st2 = _state(tte=tte, latest=latest * k, strike=strike * k, asset=asset)
    d1 = sd.compute_settlement_distribution(st1, _SIGMA_REL[asset])
    d2 = sd.compute_settlement_distribution(st2, _SIGMA_REL[asset])
    assert d1.z_score == pytest.approx(d2.z_score, rel=1e-9)
    assert d1.p_yes_raw == pytest.approx(d2.p_yes_raw, abs=1e-9)
    # std must scale with price -- absolute units confirmed.
    assert d2.std == pytest.approx(d1.std * k, rel=1e-9)


@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_settlement_z_scale_invariant_in_window(asset):
    """Same check inside the averaging window: strike, latest, and every
    observed sample scaled by k leaves z unchanged while std scales."""
    latest, strike = _SNAPSHOTS[asset]
    k = 2.5
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    obs1 = _elapsed_obs(expiry, base=latest)
    obs2 = [(ts, v * Decimal(str(k))) for ts, v in obs1]
    st1 = _state(tte=30.0, latest=latest, strike=strike, observed=obs1, asset=asset)
    st2 = _state(tte=30.0, latest=latest * k, strike=strike * k, observed=obs2, asset=asset)
    d1 = sd.compute_settlement_distribution(st1, _SIGMA_REL[asset])
    d2 = sd.compute_settlement_distribution(st2, _SIGMA_REL[asset])
    assert d1.z_score == pytest.approx(d2.z_score, rel=1e-9)
    assert d1.p_yes_raw == pytest.approx(d2.p_yes_raw, abs=1e-9)
    assert d2.mean == pytest.approx(d1.mean * k, rel=1e-9)
    assert d2.std == pytest.approx(d1.std * k, rel=1e-9)


# ---------------------------------------------------------------------------
# 4. Boundary: pre-window vs in-window variance agree at tte = W.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_pre_in_window_variance_continuity(asset):
    """As tte -> 60s from above (pre_window) the forecast variance must
    approach the in_window (zero-observed) variance at tte=60 exactly -
    both are sigma_abs^2 * variance_seconds / SPY over the same schedule."""
    latest, strike = _SNAPSHOTS[asset]
    sig = _SIGMA_REL[asset]
    pre = sd.compute_settlement_distribution(
        _state(tte=60.001, latest=latest, strike=strike, asset=asset), sig
    )
    boundary = sd.compute_settlement_distribution(
        _state(tte=60.0, latest=latest, strike=strike, asset=asset), sig
    )
    assert pre.mean == pytest.approx(boundary.mean)
    assert pre.std == pytest.approx(boundary.std, rel=2e-3)


def test_discrete_variance_matches_continuous_identity_at_boundary():
    """variance_seconds at tte=60 must equal the discrete R^3/3W^2 identity
    (the docstring's continuous-limit reference) within the documented
    right-endpoint-schedule correction."""
    latest, strike = _SNAPSHOTS["BTC"]
    st = _state(tte=60.0, latest=latest, strike=strike)
    d = sd.compute_settlement_distribution(st, 1.0)  # sigma_rel = 1 -> sigma_abs = latest
    # var = (latest^2) * variance_seconds / SPY  ->  variance_seconds = var*SPY/latest^2
    variance_seconds = (d.std ** 2) * _SPY / (latest ** 2)
    continuous_identity = (60.0 ** 3) / (3.0 * 60.0 ** 2)  # R^3/(3W^2) = 20.0 s
    assert variance_seconds == pytest.approx(continuous_identity, rel=0.05)


# ---------------------------------------------------------------------------
# 5. Fully observed settlement: rounding/tie rule, no div-by-zero.
# ---------------------------------------------------------------------------

def test_expired_uses_observed_average_above_strike():
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    now = expiry  # tte == 0 -> expired
    obs = _obs_series(now, 60, 101.0)
    st = _state(tte=0.0, latest=101.0, strike=100.0, observed=obs)
    d = sd.compute_settlement_distribution(st, 0.6)
    assert d.std == 0.0
    assert d.mean == pytest.approx(101.0)
    assert d.p_yes_raw == 1.0
    assert math.isinf(d.z_score) and d.z_score > 0


def test_expired_tie_settles_yes():
    """mean == strike -> p_yes 1.0 (>= settlement rule), z = 0 not inf."""
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    obs = _obs_series(expiry, 60, 100.0)
    st = _state(tte=0.0, latest=100.0, strike=100.0, observed=obs)
    d = sd.compute_settlement_distribution(st, 0.6)
    assert d.std == 0.0
    assert d.p_yes_raw == 1.0
    assert d.z_score == 0.0


def test_expired_below_strike_settles_no():
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    obs = _obs_series(expiry, 60, 99.0)
    st = _state(tte=0.0, latest=99.0, strike=100.0, observed=obs)
    d = sd.compute_settlement_distribution(st, 0.6)
    assert d.p_yes_raw == 0.0
    assert math.isinf(d.z_score) and d.z_score < 0


# ---------------------------------------------------------------------------
# 6. Missing samples: explicit failure vs bounded forward-fill.
# ---------------------------------------------------------------------------

def _elapsed_obs(expiry: datetime, drop: set = frozenset(), base: float = 100.0) -> list:
    """All 30 elapsed slots at tte=30 (expiry-59 .. expiry-30), minus `drop`."""
    return [
        (expiry - timedelta(seconds=i), Decimal(str(base)))
        for i in range(30, 60)
        if i not in drop
    ]


def test_missing_elapsed_slot_fails_closed_by_default():
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    st = _state(
        tte=30.0, latest=100.0, strike=100.0,
        observed=_elapsed_obs(expiry, {45}),
    )
    with pytest.raises(ValueError):
        sd.compute_settlement_distribution(st, 0.6, max_missing_samples=0)


def test_missing_elapsed_slot_bounded_forward_fill():
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    st = _state(
        tte=30.0, latest=100.0, strike=100.0,
        observed=_elapsed_obs(expiry, {45}),
    )
    d = sd.compute_settlement_distribution(st, 0.6, max_missing_samples=1)
    assert d.filled_count == 1
    assert d.observed_count == 29


def test_missing_slot_beyond_bound_still_fails():
    expiry = datetime(2026, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
    st = _state(
        tte=30.0, latest=100.0, strike=100.0,
        observed=_elapsed_obs(expiry, {45, 44}),
    )
    with pytest.raises(ValueError):
        sd.compute_settlement_distribution(st, 0.6, max_missing_samples=1)


# ---------------------------------------------------------------------------
# 7. Same as-of snapshot: endpoint vs settlement read the same sigma/spot.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_both_models_same_snapshot_consistent_sign(asset):
    """With one sigma_rel and one spot, both z-scores must at least agree on
    direction for a common snapshot - a sign flip here would mean a unit or
    reference-price bug, not a model-structure difference."""
    latest, strike = _SNAPSHOTS[asset]
    sig = _SIGMA_REL[asset]
    # Push the snapshot off-the-money in both directions.
    for offset in (0.995, 1.005):
        s = latest * offset
        ep = _compute_bachelier_components(s, strike, 300.0, sig)
        st = _state(tte=300.0, latest=s, strike=strike, asset=asset)
        d = sd.compute_settlement_distribution(st, sig)
        assert math.copysign(1.0, ep["z_score"]) == math.copysign(
            1.0, d.z_score
        ), f"{asset} sign mismatch at offset {offset}"


# ---------------------------------------------------------------------------
# 8. Market-implied vol: same lognormal units as the estimator path.
# ---------------------------------------------------------------------------

def test_market_implied_vol_is_relative_annualized():
    """Inversion is no-Ito (sigma = ln(S/K)/(z*sqrt(T))); feeding it back into
    the full d2 leaves a residual of exactly -sigma^2 T/2 in the numerator.
    At realistic 15m vols this is a small systematic, not a unit error."""
    implied = _compute_market_implied_vol(
        spot_price=100.06, strike_price=100.0, seconds_to_expiry=300.0,
        market_prob=0.60,
    )
    assert implied is not None and 0.05 < implied < 3.0  # relative, annualized
    c = _compute_bachelier_components(100.06, 100.0, 300.0, implied)
    # d2 = z_target - sigma*sqrt(T)/2 by construction of the inversion.
    t_years = 300.0 / _SPY
    correction = implied * math.sqrt(t_years) / 2.0
    expected_p = 0.5 * (1.0 + math.erf(
        (statistics_inv_cdf(0.60) - correction) / math.sqrt(2.0)
    ))
    assert c["p_yes_raw"] == pytest.approx(expected_p, abs=2e-4)
    assert abs(c["p_yes_raw"] - 0.60) < 0.01  # bounded systematic


def statistics_inv_cdf(p: float) -> float:
    import statistics
    return statistics.NormalDist().inv_cdf(p)


def test_implied_vol_residual_scales_with_sigma_squared_t():
    """The omitted -sigma^2 T/2 term means the inversion under-prices by an
    amount growing with implied vol; at extreme implied vols the bias is a
    few tenths of a probability point - worth flagging, not a defect."""
    implied = _compute_market_implied_vol(
        spot_price=100.0, strike_price=100.5, seconds_to_expiry=300.0,
        market_prob=0.35,
    )
    assert implied is not None
    c = _compute_bachelier_components(100.0, 100.5, 300.0, implied)
    t_years = 300.0 / _SPY
    correction = implied * math.sqrt(t_years) / 2.0
    expected_p = 0.5 * (1.0 + math.erf(
        (statistics_inv_cdf(0.35) - correction) / math.sqrt(2.0)
    ))
    assert c["p_yes_raw"] == pytest.approx(expected_p, abs=2e-4)


# ---------------------------------------------------------------------------
# 9. Held-side sign conventions: NO-side probability is 1 - p_yes.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", sorted(_SNAPSHOTS))
def test_no_side_is_exact_complement(asset):
    latest, strike = _SNAPSHOTS[asset]
    ep = _compute_bachelier_components(latest, strike, 300.0, _SIGMA_REL[asset])
    st = _state(tte=300.0, latest=latest, strike=strike, asset=asset)
    d = sd.compute_settlement_distribution(st, _SIGMA_REL[asset])
    # Both models define p_no = 1 - p_yes.
    assert (1.0 - ep["p_yes_raw"]) == pytest.approx(
        1.0 - 0.5 * (1.0 + math.erf(ep["z_score"] / math.sqrt(2.0)))
    )
    mirrored = _state(
        tte=300.0, latest=2 * strike - latest, strike=strike, asset=asset
    )
    # (a) With the same sigma_abs the strike mirror must negate z exactly.
    sigma_abs = sd._price_volatility(_SIGMA_REL[asset], latest)
    sigma_rel_mirror = sigma_abs / (2 * strike - latest)
    d_m = sd.compute_settlement_distribution(mirrored, sigma_rel_mirror)
    assert d_m.z_score == pytest.approx(-d.z_score, rel=1e-9)
    # (b) With the same sigma_rel the mirror is only approximate: sigma_abs
    # keys off the *latest* RTI, so it differs across the mirror. The exact
    # drift is 2|S-K|/(2K-S) - a structural property of the conversion
    # reference, not a silent unit swap.
    d_m2 = sd.compute_settlement_distribution(mirrored, _SIGMA_REL[asset])
    drift = abs(d_m2.z_score + d.z_score) / max(abs(d.z_score), 1e-12)
    exact_drift = 2 * abs(latest - strike) / (2 * strike - latest)
    assert drift == pytest.approx(exact_drift, rel=1e-9)


def test_metadata_fields_present():
    """The required sigma metadata vocabulary exists on the distribution."""
    st = _state(tte=120.0, latest=100.0, strike=100.0, asset="BTC")
    d = sd.compute_settlement_distribution(st, 0.6)
    assert d.model_version == "settlement-average-normal-v2-discrete"
    assert d.forecast_method == "zero_drift_forward_average"
    assert d.seconds_to_expiry == pytest.approx(120.0)
    assert d.remaining_count == 60
    assert math.isfinite(d.mean) and math.isfinite(d.std) and d.std > 0
