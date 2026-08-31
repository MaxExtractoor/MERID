"""Canonical trade decision contract for 15-minute crypto binaries.

A TradeDecision is the single source of truth for whether an asset has a
tradable edge.  It is produced once per asset per cycle by the hybrid decision
engine and consumed by the candidate selector, risk manager, order router, and
monitor.  Price-only rules must never produce a candidate; they may only be
inputs to the decision engine.
"""
from __future__ import annotations

import math
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple

from merid.risk.probability.tail_calibrator import load_tail_calibrator
from merid.prediction.rejection_counterfactual import log_rejected_candidate
from merid.data.ingress_replay import replay_time
from merid.audit.replay_state_diff import record_state_checksum
from utils.logger import get_logger

logger = get_logger("merid.prediction.trade_decision")


# Minimum posterior for a regime classification to be usable.
MIN_REGIME_POSTERIOR = Decimal(os.environ.get("MERID_MIN_REGIME_POSTERIOR", "0.5"))

# Absolute minimum model probability for a side to be considered.  The
# effective per-side floor is computed in _min_p_for_side and is
# price-aware: p_selected must exceed executable_entry_price + all-in cost
# reserve (entry_fee + exit_cost_reserve + model_risk_reserve).  This
# preserves positive-EV cost-basis trades on cheap contracts without the
# old unconditional 0.5 directional-confidence veto.
TRADE_DECISION_MIN_P_SELECTED = float(os.environ.get("MERID_TRADE_DECISION_MIN_P_SELECTED", "0.0"))

# Minimum net edge (as a fraction of notional) for a side to be selected.
# 2026-08-30: Lowered to 0.02 (2%) as the hard global floor.  The actual
# threshold used at decision time is computed by ``_compute_dynamic_min_required_edge``,
# which adds an asset-tier base, a price-convexity term, and a half-spread
# reserve.  The resolved live config may raise this floor further, but never
# below the hard 0.02 floor.
TRADE_DECISION_MIN_REQUIRED_EDGE = float(os.environ.get("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.02"))

# Hard entry-price floor for the held side.  Contracts with a held-side price
# below this (in cents) are rejected because the 7-day data showed 0/16 wins in
# the 0-19c tail.  Override with MERID_MIN_HELD_PRICE_CENTS to raise/lower.
# 2026-08-28: raised to 35c to match the cheap-tail filter.  Trades below this
# floor are only allowed when the model probability is exceptionally high (see
# MERID_CHEAP_TAIL_P_EXCEPTION).
MERID_MIN_HELD_PRICE_CENTS = float(os.environ.get("MERID_MIN_HELD_PRICE_CENTS", "35"))

# Very high-confidence cheap-tail exception.  DISABLED by default (threshold 1.0)
# because 7-day data showed the cheap tail (0-19c held) has a near-zero realized
# win rate and the model is overconfident there.  The per-side isotonic
# recalibration must be proven out-of-sample before re-enabling any value < 1.0.
# Setting this to 0.95 re-enables the old high-confidence exception.
MERID_CHEAP_TAIL_P_EXCEPTION = float(os.environ.get("MERID_CHEAP_TAIL_P_EXCEPTION", "1.0"))

# Tail calibration applies the isotonic correction from
# data/probability_tail_calibration.json (produced by scripts/calibrate_tail_probability.py).
# It caps model probability at historical actual_win_rate + buffer.
MERID_TAIL_CALIBRATION_ENABLED = os.environ.get("MERID_TAIL_CALIBRATION_ENABLED", "1").lower() in ("1", "true", "yes")
MERID_TAIL_CALIBRATION_BUFFER = float(os.environ.get("MERID_TAIL_CALIBRATION_BUFFER", "0.05"))
MERID_TAIL_CALIBRATION_PRICE_FLOOR = float(os.environ.get("MERID_TAIL_CALIBRATION_PRICE_FLOOR", "0.35"))
# 2026-08-30: When the NO tail curve is still the YES dual (not re-fit on
# real NO-held records), only apply the dual tail cap if the raw NO model
# probability is itself in the cheap-tail region.  Capping a moderate or
# high raw p_no down to 0.05 based on a derived dual is an over-correction
# that structurally suppresses the NO side.  This is a stop-gap until the
# real NO curve is fit.
MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR = float(
    os.environ.get("MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR", "0.20")
)

# Fail-closed gate for externally supplied hybrid p_yes.  Bachelier-only is the
# live baseline; a hybrid probability is only accepted when this flag is
# explicitly enabled, and still subject to tail calibration / π* / floor gates.
MERID_TRADE_DECISION_ALLOW_HYBRID_P = os.environ.get("MERID_TRADE_DECISION_ALLOW_HYBRID_P", "").strip().lower() in ("1", "true", "yes")

# Per-bucket π* EV gate.  The minimum required p_selected for a positive
# risk-adjusted EV is (held_price + fee + risk_premium) / 100.  The risk
# premium is tiered by held price to reflect the observed tail overconfidence:
# cheap-tail contracts need a much larger safety margin than high-price ones.
MERID_PI_STAR_TIERED = os.environ.get("MERID_PI_STAR_TIERED", "1").lower() in ("1", "true", "yes")
MERID_PI_STAR_FLAT_PREMIUM_CENTS = int(os.environ.get("MERID_PI_STAR_FLAT_PREMIUM_CENTS", "0"))
MERID_PI_STAR_TIERS_CENTS = os.environ.get("MERID_PI_STAR_TIERS_CENTS", "0:40,20:25,40:10,60:0")

# 2026-08-29: Executable-cost EV gate becomes the final entry authority.
# When enabled, the gate is evaluated after the existing edge/π* computation
# and can overrule a selected side if the net dollar EV or EV/tail-risk ratio
# does not clear the configured thresholds.  The old edge-%/p_selected gates
# remain visible in the decision as telemetry, but the EV gate is the sole
# authority for live entries.
MERID_EV_GATE_AUTHORITATIVE = os.environ.get("MERID_EV_GATE_AUTHORITATIVE", "1").lower() in ("1", "true", "yes")

# 2026-08-29: Order decision ledger collection.  When enabled, every trade
# decision is persisted before any order is submitted.
MERID_ORDER_DECISION_LEDGER_ENABLED = os.environ.get("MERID_ORDER_DECISION_LEDGER_ENABLED", "1").lower() in ("1", "true", "yes")

# 2026-08-30: Annualized-volatility sanity controls.  The Bachelier baseline is
# only defensible when sigma is in a TWAP-appropriate band for the asset.
# Values below the band produce overconfident p_yes (e.g. 0.95 for a 30-80c
# spot-strike move) and can create false edges.  Values above the band are
# economically implausible for 15m crypto.  Env vars override the band per asset
# or globally; MERID_ANNUALIZED_VOL_{ASSET} is still the primary requested value
# when set, but it is clamped to this band unless an explicit override is given.
_ANNUALIZED_VOL_BANDS = {
    "BTC": (0.30, 0.90),
    "ETH": (0.35, 1.00),
    "SOL": (0.40, 1.10),
    "XRP": (0.40, 1.10),
    "DOGE": (0.45, 1.20),
}
_ANNUALIZED_VOL_GLOBAL_MIN = float(os.environ.get("MERID_MIN_ANNUALIZED_VOL", "0.25"))
_ANNUALIZED_VOL_GLOBAL_MAX = float(os.environ.get("MERID_MAX_ANNUALIZED_VOL", "1.20"))

# Optional vol sources (off by default).  Realized vol is preferred when fresh;
# market-implied vol is a cross-check against the Kalshi price.  Both are sanity
# clamped before use.
MERID_USE_REALIZED_VOL = os.environ.get("MERID_USE_REALIZED_VOL", "").strip().lower() in ("1", "true", "yes")
MERID_REALIZED_VOL_MAX_AGE_S = float(os.environ.get("MERID_REALIZED_VOL_MAX_AGE_S", "300"))
MERID_REALIZED_VOL_MIN_CONFIDENCE = float(os.environ.get("MERID_REALIZED_VOL_MIN_CONFIDENCE", "0.5"))
MERID_ANCHOR_VOL_TO_MARKET = os.environ.get("MERID_ANCHOR_VOL_TO_MARKET", "").strip().lower() in ("1", "true", "yes")


def _inverse_normal_cdf(p: float) -> float:
    """Return the inverse CDF of the standard normal distribution.

    Uses the standard-library ``statistics.NormalDist`` so no external
    dependencies are required.  Values are clamped to (epsilon, 1-epsilon) to
    avoid divergence at the tails.
    """
    p = max(1e-9, min(1.0 - 1e-9, p))
    return statistics.NormalDist().inv_cdf(p)


def _compute_bachelier_components(
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    annualized_vol: float,
) -> Optional[Dict[str, float]]:
    """Return Bachelier z-score, log-moneyness, and raw p_yes.

    ``p_yes_raw`` is not clipped to the [0.05, 0.95] venue band so callers can
    see the model's unclipped opinion.
    """
    if not all(math.isfinite(x) for x in (spot_price, strike_price, seconds_to_expiry, annualized_vol)):
        return None
    if seconds_to_expiry <= 0 or strike_price <= 0 or annualized_vol <= 0:
        return None
    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    log_moneyness = math.log(spot_price / strike_price) if strike_price > 0 else 0.0
    sigma = max(annualized_vol, 1e-6)
    z = log_moneyness / (sigma * math.sqrt(t_years))
    p_yes_raw = max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))
    return {
        "log_moneyness": log_moneyness,
        "z_score": z,
        "p_yes_raw": p_yes_raw,
        "t_years": t_years,
        "sigma": sigma,
    }


def _compute_market_implied_vol(
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    market_prob: float,
) -> Optional[float]:
    """Back out annualized vol from the Kalshi market price via the Bachelier model.

    This is a diagnostic/anchor, not the primary p_yes.  Returns None when the
    market is at-the-money, the price is too close to 0/1, or spot and market
    disagree on direction, in which case the caller falls back to the configured
    default.
    """
    if not all(math.isfinite(x) for x in (spot_price, strike_price, seconds_to_expiry, market_prob)):
        return None
    if seconds_to_expiry <= 0 or strike_price <= 0:
        return None
    if market_prob <= 1e-4 or market_prob >= 1.0 - 1e-4:
        return None
    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    if t_years <= 0:
        return None
    log_moneyness = math.log(spot_price / strike_price)
    if abs(log_moneyness) < 1e-9:
        return None
    z_target = _inverse_normal_cdf(market_prob)
    if z_target == 0.0:
        return None
    # Market price and spot must agree on direction.  If they disagree, the
    # quoted price is stale or the strike is stale; do not trust the implied vol.
    if log_moneyness * z_target <= 0:
        return None
    sigma = log_moneyness / (z_target * math.sqrt(t_years))
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    return sigma


def _clamp_annualized_vol(asset: str, vol: float, source: str = "default") -> float:
    """Clamp annualized vol to the per-asset sanity band and log drift.

    A value outside the band is a config/input-drift red flag.  The band can be
    widened via ``MERID_MIN_ANNUALIZED_VOL`` / ``MERID_MAX_ANNUALIZED_VOL`` or
    per-asset env overrides.  Non-finite or non-positive values fallback to the
    band minimum.
    """
    asset = asset.upper() if asset else ""
    band = _ANNUALIZED_VOL_BANDS.get(asset, (_ANNUALIZED_VOL_GLOBAL_MIN, _ANNUALIZED_VOL_GLOBAL_MAX))
    env_min = os.environ.get(f"MERID_MIN_ANNUALIZED_VOL_{asset}")
    env_max = os.environ.get(f"MERID_MAX_ANNUALIZED_VOL_{asset}")
    if env_min is not None:
        try:
            band = (float(env_min), band[1])
        except ValueError:
            pass
    if env_max is not None:
        try:
            band = (band[0], float(env_max))
        except ValueError:
            pass
    mn, mx = band
    mn = max(mn, _ANNUALIZED_VOL_GLOBAL_MIN)
    mx = min(mx, _ANNUALIZED_VOL_GLOBAL_MAX)

    if not math.isfinite(vol) or vol <= 0:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%s is non-finite or non-positive; falling back to %.4f",
            asset, source, vol, mn,
        )
        return mn
    if vol < mn:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%.4f below band [%.4f, %.4f]; clamping to %.4f",
            asset, source, vol, mn, mx, mn,
        )
        return mn
    if vol > mx:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%.4f above band [%.4f, %.4f]; clamping to %.4f",
            asset, source, vol, mn, mx, mx,
        )
        return mx
    return vol


def _fetch_realized_vol(asset: str) -> Optional[float]:
    """Return the canonical realized vol if it is fresh and confident."""
    if not MERID_USE_REALIZED_VOL:
        return None
    try:
        from merid.prediction.risk.sentiment_vol_service import get_current_volatility
        scalar = get_current_volatility(asset)
        if scalar is None:
            return None
        if scalar.value <= 0 or scalar.confidence < MERID_REALIZED_VOL_MIN_CONFIDENCE:
            return None
        age_s = (datetime.now(timezone.utc) - scalar.timestamp).total_seconds()
        if age_s > MERID_REALIZED_VOL_MAX_AGE_S:
            logger.warning(
                "[VOL-REALIZED] asset=%s realized vol stale (age=%.0fs > %.0fs); ignoring",
                asset, age_s, MERID_REALIZED_VOL_MAX_AGE_S,
            )
            return None
        return float(scalar.value)
    except Exception as exc:
        logger.warning("[VOL-REALIZED] asset=%s failed to fetch realized vol: %s", asset, exc)
        return None


def _resolve_annualized_vol(
    asset: str,
    requested_vol: float,
    spot_price: Optional[float] = None,
    strike_price: Optional[float] = None,
    seconds_to_expiry: Optional[float] = None,
    market_prob: Optional[float] = None,
) -> Tuple[float, str, float, float, Optional[Dict[str, float]]]:
    """Resolve the final annualized vol for the Bachelier model.

    Priority:
      1. Explicit env override ``MERID_ANNUALIZED_VOL_{ASSET}`` (legacy).
      2. Realized vol from SentimentVolService (if ``MERID_USE_REALIZED_VOL=1`` and fresh).
      3. Market-implied vol backed out of the Kalshi price (if ``MERID_ANCHOR_VOL_TO_MARKET=1``).
      4. The caller-supplied ``requested_vol`` (usually the code default).

    The chosen value is sanity-clamped and returned along with the source, the
    band min/max, and the Bachelier components computed with the clamped vol.
    If spot/strike/TTE are not supplied, the Bachelier components are None.
    """
    asset = asset.upper() if asset else ""
    source = "requested"
    env_override = os.environ.get(f"MERID_ANNUALIZED_VOL_{asset}")
    if env_override is not None:
        try:
            requested_vol = float(env_override)
            source = "env_override"
        except ValueError:
            logger.warning("[VOL-RESOLVE] asset=%s invalid MERID_ANNUALIZED_VOL_%s=%s; ignoring", asset, asset, env_override)

    resolved_vol: Optional[float] = None
    tried: List[str] = []

    realized = _fetch_realized_vol(asset)
    if realized is not None:
        resolved_vol = realized
        source = "realized"
        tried.append("realized")

    if resolved_vol is None and MERID_ANCHOR_VOL_TO_MARKET:
        if market_prob is not None and spot_price is not None and strike_price is not None and seconds_to_expiry is not None:
            implied = _compute_market_implied_vol(spot_price, strike_price, seconds_to_expiry, market_prob)
            if implied is not None:
                resolved_vol = implied
                source = "market_implied"
            tried.append("market_implied")

    if resolved_vol is None:
        resolved_vol = requested_vol
        source = source if source != "requested" else "default"

    band = _ANNUALIZED_VOL_BANDS.get(asset, (_ANNUALIZED_VOL_GLOBAL_MIN, _ANNUALIZED_VOL_GLOBAL_MAX))
    env_min = os.environ.get(f"MERID_MIN_ANNUALIZED_VOL_{asset}")
    env_max = os.environ.get(f"MERID_MAX_ANNUALIZED_VOL_{asset}")
    if env_min is not None:
        try:
            band = (float(env_min), band[1])
        except ValueError:
            pass
    if env_max is not None:
        try:
            band = (band[0], float(env_max))
        except ValueError:
            pass
    mn, mx = band
    mn = max(mn, _ANNUALIZED_VOL_GLOBAL_MIN)
    mx = min(mx, _ANNUALIZED_VOL_GLOBAL_MAX)

    clamped = _clamp_annualized_vol(asset, resolved_vol, source)
    if clamped != resolved_vol:
        source = f"{source}_clamped"

    components: Optional[Dict[str, float]] = None
    if spot_price is not None and strike_price is not None and seconds_to_expiry is not None:
        components = _compute_bachelier_components(spot_price, strike_price, seconds_to_expiry, clamped)

    return clamped, source, mn, mx, components


def _get_resolved_live_config() -> Optional[Any]:
    """Return the resolved live config if available, otherwise None."""
    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved.resolved:
            return resolved
    except Exception:
        pass
    return None


def _get_resolved_min_required_edge(default: float) -> float:
    """Use the resolved live config edge floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return default
    resolved_edge = float(resolved.min_required_edge)
    return max(default, resolved_edge)


def _compute_dynamic_min_required_edge(
    asset: str,
    price_cents: int,
    side: Literal["yes", "no"],
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    floor_min_required_edge: float,
) -> float:
    """Compute a fee-aware, asset-tiered, spread-aware edge threshold.

    The threshold is applied to ``net_edge`` (after Kalshi fees, exit-cost
    reserve, and model-risk reserve).  It therefore represents the required
    *pure edge* profit floor, not the full cost stack.

    Components:
      - Asset-tier base floor (BTC most liquid, DOGE/XRP least).
      - Convex price-risk term: ``K * p * (1-p)`` peaks at 50c where taker
        fee and adverse-selection risk are largest and shrinks in the tails.
      - Half-spread reserve for the selected side, using live book data when
        available and conservative per-asset defaults otherwise.

    The final value is clamped to the global floor and a 15% sanity ceiling.
    """
    # Asset-tier base floor.  These are the research-backed net-of-fee floors:
    # BTC ~3%, ETH/SOL ~4%, XRP/DOGE ~5%.  They are intentionally conservative
    # enough to keep the Kelly / half-Kelly sizing positive-EV.
    asset_base = {
        "BTC": 0.03,
        "ETH": 0.04,
        "SOL": 0.04,
        "XRP": 0.05,
        "DOGE": 0.05,
    }.get(asset.upper(), 0.05)

    base = max(float(floor_min_required_edge), asset_base)

    # Price-adj convexity term.  At 50c, p*(1-p) = 0.25 -> 0.01 (1 point).
    # At 10c/90c, p*(1-p) = 0.09 -> 0.0036 (0.36 points).
    p = float(price_cents) / 100.0
    p = max(0.01, min(0.99, p))
    price_adj = 0.04 * p * (1.0 - p)

    # Half-spread term for the selected side.
    spread_cents: float = 0.0
    if side == "yes" and yes_bid_cents > 0 and yes_ask_cents > yes_bid_cents:
        spread_cents = yes_ask_cents - yes_bid_cents
    elif side == "no" and no_bid_cents > 0 and no_ask_cents > no_bid_cents:
        spread_cents = no_ask_cents - no_bid_cents
    if spread_cents <= 0:
        # Conservative per-asset defaults when the book is unavailable.
        spread_cents = {
            "BTC": 1.0,
            "ETH": 1.5,
            "SOL": 2.0,
            "XRP": 2.5,
            "DOGE": 3.0,
        }.get(asset.upper(), 2.0)
    spread_adj = 0.5 * spread_cents / 100.0

    dynamic = base + price_adj + spread_adj
    return max(0.02, min(dynamic, 0.15))


def _get_resolved_min_p_selected(default: float) -> float:
    """Use the resolved live config p_selected floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return float(default)
    resolved_p = float(resolved.min_p_selected)
    return max(float(default), resolved_p)


def _min_p_for_side(breakdown: EdgeBreakdown, floor: float) -> float:
    """Return the side-aware minimum p_selected for a positive-EV trade.

    The model probability must exceed the all-in cost basis of the held
    side: executable entry price plus entry fee, expected exit cost, and
    model-risk reserve.  The absolute ``floor`` (from env / live config) is
    applied as an additional hard minimum.
    """
    cost_basis = (
        breakdown.executable_entry_price
        + breakdown.entry_fee
        + breakdown.exit_cost_reserve
        + breakdown.model_risk_reserve
    )
    return max(floor, cost_basis)


def _get_resolved_min_held_price_cents(default: float) -> float:
    """Use the resolved live config held-price floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return default
    resolved_floor = float(resolved.min_held_price_cents)
    return max(default, resolved_floor)


def _get_resolved_config_hash() -> Optional[str]:
    """Return the resolved live config hash if available."""
    resolved = _get_resolved_live_config()
    return resolved.config_hash if resolved is not None else None


def _get_resolved_max_contracts() -> int:
    """Return the resolved per-order contract cap, falling back to env/default."""
    resolved = _get_resolved_live_config()
    if resolved is not None and resolved.max_contracts_per_order is not None:
        return int(resolved.max_contracts_per_order)
    try:
        return int(os.environ.get("MERID_MAX_CONTRACTS_PER_ORDER", "2"))
    except Exception:
        return 2


def _parse_pi_star_tiers() -> List[Tuple[int, int]]:
    tiers: List[Tuple[int, int]] = []
    for part in MERID_PI_STAR_TIERS_CENTS.split(","):
        if not part:
            continue
        price, premium = part.split(":")
        tiers.append((int(price), int(premium)))
    tiers.sort(key=lambda x: x[0])
    return tiers

def _pi_star_risk_premium(held_price_cents: int) -> int:
    if not MERID_PI_STAR_TIERED:
        return MERID_PI_STAR_FLAT_PREMIUM_CENTS
    tiers = _parse_pi_star_tiers()
    premium = 0
    for price_threshold, tier_premium in tiers:
        if held_price_cents >= price_threshold:
            premium = tier_premium
    return premium

# Allowed data-state and regime-label values.
# `unknown` is a data-quality state; it must never be an economic regime.
ALLOWED_DATA_STATES = frozenset({"warming_up", "healthy", "stale", "degraded", "invalid"})
ALLOWED_REGIME_LABELS = frozenset({
    "unknown",
    "low_vol", "normal", "high_vol", "trend_up", "trend_down", "transition",
    "both_sides", "one_sided_yes", "one_sided_no", "no_liquidity",
})


@dataclass(frozen=True)
class EdgeBreakdown:
    """Explicit, side-aware EV decomposition for a single candidate side.

    Every field is in fractional units (0.0-1.0) so that:

        gross_edge = p_selected - executable_entry_price
        net_edge   = gross_edge - entry_fee - exit_cost_reserve - model_risk_reserve

    No hidden constants are permitted.  If a cost cannot be explained, the
    decision must be ``no_trade``.
    """
    p_yes: float
    p_no: float
    selected_side: Literal["yes", "no"]
    p_selected: float
    p_opposite: float
    executable_entry_price: float
    entry_fee: float
    exit_cost_reserve: float
    model_risk_reserve: float
    gross_edge: float
    net_edge: float


@dataclass(frozen=True)
class ConfidenceResult:
    """Confidence must carry provenance and a validity flag.

    A confidence value without an uncertainty engine is not a valid trading
    input.  Invalid confidence always blocks entry.  Component penalties are
    the additive uncertainty terms that produced ``value``.
    """
    value: Optional[float]
    valid: bool
    source: str
    reasons: List[str] = field(default_factory=list)
    data_penalty: float = 0.0
    book_penalty: float = 0.0
    model_penalty: float = 0.0
    regime_penalty: float = 0.0


@dataclass(frozen=True)
class TradeDecision:
    """Immutable per-asset trade decision produced by the hybrid engine.

    Required fields
    ---------------
    If any required field is missing, non-finite, or logically inconsistent,
    the decision is ``no_trade`` and downstream must not emit an order.
    """
    run_id: str
    decision_id: str
    ticker: str
    asset: str
    timestamp_utc: datetime

    # Probability (raw -> calibrated) with explicit side semantics
    p_yes_raw: Decimal
    p_yes_calibrated: Decimal
    p_yes_uncertainty: Decimal
    p_no_calibrated: Decimal
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None

    # Evidence
    indicators: Dict[str, Any] = field(default_factory=dict)
    regime: str = "unknown"
    data_quality: str = "unknown"
    data_state: str = "unknown"
    regime_label: str = "unknown"
    regime_probability: Decimal = Decimal("0")
    regime_warmup_samples: int = 0
    seconds_to_expiry: Decimal = Decimal("0")
    settlement_reference: str = "unknown"

    # Executable economics (depth-weighted)
    yes_entry_vwap: Decimal = Decimal("0")
    no_entry_vwap: Decimal = Decimal("0")
    yes_depth_cc: Decimal = Decimal("0")
    no_depth_cc: Decimal = Decimal("0")
    fee_yes: Decimal = Decimal("0")
    fee_no: Decimal = Decimal("0")
    expected_exit_cost_yes: Decimal = Decimal("0")
    expected_exit_cost_no: Decimal = Decimal("0")

    # Upstream signal / vote provenance
    yes_score: Optional[Decimal] = None
    no_score: Optional[Decimal] = None
    yes_vote_count: int = 0
    no_vote_count: int = 0
    selected_side_pre_edge: Optional[Literal["yes", "no"]] = None
    selection_reason: str = "unknown"

    # Per-side edge / cost / reserve decomposition
    gross_edge_yes: Optional[Decimal] = None
    gross_edge_no: Optional[Decimal] = None
    net_edge_yes: Decimal = Decimal("0")
    net_edge_no: Decimal = Decimal("0")
    yes_net_edge: Decimal = Decimal("0")
    no_net_edge: Decimal = Decimal("0")
    best_side: Optional[Literal["yes", "no"]] = None
    best_net_edge: Optional[Decimal] = None
    edge_threshold: Decimal = Decimal("0")
    entry_fee_yes: Decimal = Decimal("0")
    entry_fee_no: Decimal = Decimal("0")
    exit_cost_reserve_yes: Decimal = Decimal("0")
    exit_cost_reserve_no: Decimal = Decimal("0")
    model_risk_reserve_yes: Decimal = Decimal("0")
    model_risk_reserve_no: Decimal = Decimal("0")
    selected_outcome: Optional[Literal["yes", "no"]] = None
    selected_action: Optional[Literal["buy"]] = None
    selected_outcome_price: Optional[Decimal] = None
    gross_edge: Optional[Decimal] = None
    net_edge: Optional[Decimal] = None
    no_trade_reason: Optional[str] = None

    # Explicit edge and confidence provenance
    edge_breakdown: Optional[EdgeBreakdown] = None
    yes_edge_breakdown: Optional[EdgeBreakdown] = None
    no_edge_breakdown: Optional[EdgeBreakdown] = None
    confidence: Optional[Decimal] = None
    confidence_valid: bool = False
    confidence_source: str = "missing"
    confidence_reasons: List[str] = field(default_factory=list)
    confidence_data_penalty: Optional[Decimal] = None
    confidence_book_penalty: Optional[Decimal] = None
    confidence_model_penalty: Optional[Decimal] = None
    confidence_regime_penalty: Optional[Decimal] = None
    model_risk_reserve: Decimal = Decimal("0")
    min_required_edge: Decimal = Decimal("0")
    approved_size_cc: Decimal = Decimal("0")
    policy_version: str = "trade_decision_v2"

    # 2026-08-29: Executable-cost EV gate state.
    # The EV gate is the final entry authority; these fields carry its economics
    # and its allow/reject outcome for audit and ledger provenance.
    adverse_selection_reserve: Decimal = Decimal("0")
    uncertainty_reserve: Decimal = Decimal("0")
    ev_gate_allowed: bool = False
    ev_gate_result: Optional[Dict[str, Any]] = None

    # 2026-08-29: Hash of the resolved live config that authorized this decision.
    config_hash: Optional[str] = None
    build_sha: Optional[str] = None

    @property
    def side(self) -> Optional[Literal["yes", "no"]]:
        """Alias for the selected (consumed) side used by downstream paths."""
        return self.selected_outcome

    @property
    def evaluated_side(self) -> Optional[Literal["yes", "no"]]:
        """Alias for the dual-side evaluator's unconstrained best side."""
        return self.best_side

    def __post_init__(self) -> None:
        if not (Decimal("0") <= self.p_yes_raw <= Decimal("1")):
            raise ValueError(f"p_yes_raw out of [0,1]: {self.p_yes_raw}")
        if not (Decimal("0") <= self.p_yes_calibrated <= Decimal("1")):
            raise ValueError(f"p_yes_calibrated out of [0,1]: {self.p_yes_calibrated}")
        if not (Decimal("0") <= self.p_yes_uncertainty <= Decimal("1")):
            raise ValueError(f"p_yes_uncertainty out of [0,1]: {self.p_yes_uncertainty}")
        if not (Decimal("0") <= self.p_no_calibrated <= Decimal("1")):
            raise ValueError(f"p_no_calibrated out of [0,1]: {self.p_no_calibrated}")
        if self.selected_outcome is not None and self.selected_action is None:
            raise ValueError("selected_action required when selected_outcome is set")
        if self.selected_outcome is None and self.selected_action is not None:
            raise ValueError("selected_outcome required when selected_action is set")
        if self.selected_outcome is not None and self.no_trade_reason is not None:
            raise ValueError("no_trade_reason must be None when a side is selected")

        # Data-state and regime are data-quality gates; they cannot co-exist with a trade.
        if self.data_state not in ALLOWED_DATA_STATES:
            raise ValueError(f"data_state not in {ALLOWED_DATA_STATES}: {self.data_state}")
        if self.data_state != "healthy" and self.selected_outcome is not None:
            raise ValueError(f"data_state={self.data_state} cannot produce selected_outcome")
        if self.regime_label not in ALLOWED_REGIME_LABELS:
            raise ValueError(f"regime_label not in {ALLOWED_REGIME_LABELS}: {self.regime_label}")
        if self.regime_label == "unknown" and self.selected_outcome is not None:
            raise ValueError("regime_label=unknown cannot produce selected_outcome")

        # Score finiteness
        for score in (self.yes_score, self.no_score):
            if score is not None and not score.is_finite():
                raise ValueError(f"non-finite score: {score}")
        for edge in (self.yes_net_edge, self.no_net_edge, self.best_net_edge or Decimal("0"), self.net_edge or Decimal("0")):
            if edge is not None and not edge.is_finite():
                raise ValueError(f"non-finite edge: {edge}")


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _data_quality_to_data_state(data_quality: str) -> str:
    """Map legacy data_quality string to data_state."""
    dq = (data_quality or "unknown").strip().lower()
    if dq in ("good", "live", "healthy"):
        return "healthy"
    if dq in ("stale", "degraded"):
        return dq
    if dq == "bad":
        return "degraded"
    return "invalid"


def _regime_to_regime_label(regime: str) -> str:
    """Coerce a raw regime string to an allowed regime_label."""
    rl = (regime or "unknown").strip().lower()
    if rl in ALLOWED_REGIME_LABELS:
        return rl
    if rl == "insufficient_data":
        return "no_liquidity"
    if rl in ("calm", "elevated", "violent"):
        return rl  # volatility regime labels are intentionally allowed
    return "unknown"


def _resolve_data_state(
    *,
    data_state: Optional[str],
    data_quality: str,
) -> str:
    if data_state is not None:
        return data_state
    return _data_quality_to_data_state(data_quality)


def _resolve_regime_label(
    *,
    regime_label: Optional[str],
    regime: str,
) -> str:
    if regime_label is not None:
        return regime_label
    return _regime_to_regime_label(regime)


def _resolve_regime_probability(
    *,
    regime_probability: Optional[float],
    regime_label: str,
) -> Decimal:
    if regime_probability is not None:
        return Decimal(str(regime_probability))
    if regime_label == "unknown":
        return Decimal("0")
    return Decimal("1")


def compute_edge(
    p_yes: float,
    selected_side: Literal["yes", "no"],
    entry_price: float,
    entry_fee: float,
    exit_cost_reserve: float,
    model_risk_reserve: float,
) -> EdgeBreakdown:
    """Compute a fully explained net edge for one side.

    ``p_yes`` is the model probability of YES.  The selected side's probability
    is derived from it so that ``p_yes + p_no == 1`` is invariant.
    """
    if not (0.0 <= p_yes <= 1.0):
        raise ValueError(f"p_yes must be in [0,1]: {p_yes}")
    if selected_side not in ("yes", "no"):
        raise ValueError(f"selected_side must be 'yes' or 'no': {selected_side}")
    if not (0.0 <= entry_price <= 1.0):
        raise ValueError(f"entry_price must be in [0,1]: {entry_price}")

    p_no = 1.0 - p_yes
    p_selected = p_yes if selected_side == "yes" else p_no
    p_opposite = p_no if selected_side == "yes" else p_yes
    gross_edge = p_selected - entry_price
    net_edge = gross_edge - entry_fee - exit_cost_reserve - model_risk_reserve

    return EdgeBreakdown(
        p_yes=p_yes,
        p_no=p_no,
        selected_side=selected_side,
        p_selected=p_selected,
        p_opposite=p_opposite,
        executable_entry_price=entry_price,
        entry_fee=entry_fee,
        exit_cost_reserve=exit_cost_reserve,
        model_risk_reserve=model_risk_reserve,
        gross_edge=gross_edge,
        net_edge=net_edge,
    )


def _compute_model_risk_reserve(
    model_uncertainty: float,
    data_quality: str,
    regime: str,
    seconds_to_expiry: float,
) -> float:
    """Observable uncertainty reserve used in the edge calculation."""
    reserve = max(0.0, min(1.0, model_uncertainty))
    if data_quality in ("stale", "bad", "unknown"):
        reserve = min(1.0, reserve + 0.15)
    if seconds_to_expiry < 60.0:
        reserve = min(1.0, reserve + 0.20)
    if regime in ("unknown", "insufficient_data"):
        reserve = min(1.0, reserve + 0.05)
    return reserve


def _compute_confidence(
    data_quality: str,
    regime: str,
    settlement_reference: str,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float,
    no_depth_cc: float,
    model_uncertainty: float,
) -> ConfidenceResult:
    """Derive confidence from observable uncertainty sources.

    Confidence is not a magic number.  It is produced only when every trust
    input is present and within bounds.  Missing or degraded inputs produce
    ``valid=False`` and block entry.
    """
    reasons: List[str] = []

    if data_quality in ("stale", "bad", "unknown"):
        reasons.append(f"data_quality={data_quality}")
    if regime in ("unknown", "insufficient_data"):
        reasons.append(f"regime={regime}")
    if settlement_reference != "cfb_rti_live":
        reasons.append(f"settlement_reference={settlement_reference}")
    if seconds_to_expiry < 60.0:
        reasons.append("near_expiry")

    # Spread and depth checks: a wide spread or thin book reduces confidence.
    yes_spread = yes_ask_cents - yes_bid_cents
    no_spread = no_ask_cents - no_bid_cents
    if yes_bid_cents > 0 and yes_ask_cents > 0 and yes_spread > 5.0:
        reasons.append(f"yes_spread={yes_spread:.1f}c")
    if no_bid_cents > 0 and no_ask_cents > 0 and no_spread > 5.0:
        reasons.append(f"no_spread={no_spread:.1f}c")
    if yes_depth_cc < 100.0:
        reasons.append(f"yes_depth_cc={yes_depth_cc:.0f}")
    if no_depth_cc < 100.0:
        reasons.append(f"no_depth_cc={no_depth_cc:.0f}")

    if reasons:
        return ConfidenceResult(
            value=None,
            valid=False,
            source="uncertainty_engine",
            reasons=reasons,
        )

    yes_spread = max(0.0, yes_ask_cents - yes_bid_cents)
    no_spread = max(0.0, no_ask_cents - no_bid_cents)
    avg_spread = (yes_spread + no_spread) / 2.0
    spread_penalty = min(0.08, avg_spread / 50.0)

    min_depth = max(1.0, min(yes_depth_cc, no_depth_cc, 1.0))
    depth_penalty = max(0.0, 0.05 - (min_depth / 5000.0))

    time_penalty = 0.05 if seconds_to_expiry < 120.0 else 0.0

    # Decompose uncertainty into four explicit additive terms.
    # Data: data-quality + near-expiry time penalty.
    data_penalty = 0.0
    if data_quality in ("stale", "bad", "unknown"):
        data_penalty += 0.15
    if seconds_to_expiry < 60.0:
        data_penalty += 0.20
    data_penalty += time_penalty
    data_penalty = min(1.0, data_penalty)

    # Book: spread + depth.
    book_penalty = min(1.0, spread_penalty + depth_penalty)

    # Model: base model uncertainty.
    model_penalty = max(0.0, min(1.0, model_uncertainty))

    # Regime: unclassified or insufficient-data.
    regime_penalty = 0.05 if regime in ("unknown", "insufficient_data") else 0.0

    total_uncertainty = min(0.99, data_penalty + book_penalty + model_penalty + regime_penalty)
    value = max(0.0, min(1.0, 1.0 - total_uncertainty))
    return ConfidenceResult(
        value=value,
        valid=True,
        source="uncertainty_engine",
        data_penalty=data_penalty,
        book_penalty=book_penalty,
        model_penalty=model_penalty,
        regime_penalty=regime_penalty,
    )


def _select_best_side(
    yes_breakdown: EdgeBreakdown,
    no_breakdown: EdgeBreakdown,
    tie_epsilon: float = 1e-9,
) -> Tuple[Optional[Literal["yes", "no"]], float, str]:
    """Return (best_side, best_net_edge, selection_reason).

    Ties are explicit no-trade events to avoid hidden directional bias.
    """
    yes_edge = yes_breakdown.net_edge
    no_edge = no_breakdown.net_edge
    if abs(yes_edge - no_edge) <= tie_epsilon:
        return None, (yes_edge + no_edge) / 2.0, "directional_tie"
    if yes_edge > no_edge:
        return "yes", yes_edge, "best_executable_edge_yes"
    return "no", no_edge, "best_executable_edge_no"


def compute_trade_decision(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    asset: str,
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float = 0.0,
    no_depth_cc: float = 0.0,
    fee_per_contract_cents: float = 0.0,
    annualized_vol: float = 0.60,
    model_uncertainty: float = 0.05,
    data_quality: str = "unknown",
    data_state: Optional[str] = None,
    regime: str = "unknown",
    regime_label: Optional[str] = None,
    regime_probability: Optional[float] = None,
    regime_warmup_samples: int = 0,
    yes_score: Optional[float] = None,
    no_score: Optional[float] = None,
    p_yes_model: Optional[float] = None,
    p_no_model: Optional[float] = None,
    yes_vote_count: int = 0,
    no_vote_count: int = 0,
    selected_side_pre_edge: Optional[Literal["yes", "no"]] = None,
    selection_reason: str = "best_executable_edge",
    indicators: Optional[Dict[str, Any]] = None,
    min_required_edge: float = TRADE_DECISION_MIN_REQUIRED_EDGE,
    settlement_reference: str = "unknown",
    policy_version: str = "trade_decision_v2",
    quote_age_ms: Optional[int] = None,
    build_sha: Optional[str] = None,
) -> TradeDecision:
    """Compute a calibrated, cost-aware trade decision for a 15m binary market.

    The raw probability uses the settlement-aware normal model from the
    production notes:

        z = ln(spot/strike) / (sigma * sqrt(T))
        p_yes_raw = Phi(z)

    where T is in years and sigma is annualized volatility.  Drift is shrunk
    to zero because 15-minute drift estimates are unreliable.

    A trade is emitted only when:
      1. The data_state is healthy.
      2. The regime_label is known and its posterior is high enough.
      3. The selected side's calibrated probability is > its all-in cost basis
         (entry price + fee + exit reserve + model-risk reserve).
      4. Its net edge exceeds ``min_required_edge``.
      5. Confidence is valid (produced by the uncertainty engine, not a default).
    """
    now = datetime.fromtimestamp(replay_time(), tz=timezone.utc)
    _data_state = _resolve_data_state(data_state=data_state, data_quality=data_quality)
    _regime_label = _resolve_regime_label(regime_label=regime_label, regime=regime)
    _regime_probability = _resolve_regime_probability(
        regime_probability=regime_probability, regime_label=_regime_label
    )

    # Layer-0: Resolve live config overrides.  When a resolved live config is
    # active, use its stricter safety floors for edge, p_selected, and the
    # held-side price floor.  Attach its hash to the decision for audit.
    _resolved = _get_resolved_live_config()
    _config_hash = _get_resolved_config_hash() if _resolved is not None else None
    _build_sha = getattr(_resolved, "build_sha", None) if _resolved is not None else None
    if _resolved is not None:
        min_required_edge = _get_resolved_min_required_edge(min_required_edge)
    min_p_selected = _get_resolved_min_p_selected(TRADE_DECISION_MIN_P_SELECTED)
    min_held_price_cents = _get_resolved_min_held_price_cents(MERID_MIN_HELD_PRICE_CENTS)

    # Initialize mutable indicators dict for provenance/telemetry.  Vol and
    # z-score are attached below after the quote and vol resolution.
    indicators = dict(indicators) if indicators else {}
    indicators.setdefault("annualized_vol_requested", float(annualized_vol))

    def _no_trade(reason: str) -> TradeDecision:
        decision = TradeDecision(
            run_id=run_id,
            decision_id=decision_id,
            ticker=ticker,
            asset=asset,
            timestamp_utc=now,
            p_yes_raw=Decimal("0.5"),
            p_yes_calibrated=Decimal("0.5"),
            p_yes_uncertainty=Decimal("1.0"),
            p_no_calibrated=Decimal("0.5"),
            data_state=_data_state,
            regime_label=_regime_label,
            regime_probability=_regime_probability,
            regime_warmup_samples=regime_warmup_samples,
            data_quality=data_quality,
            regime=regime,
            no_trade_reason=reason,
            confidence_valid=False,
            confidence_source="pre_trade_gate",
            confidence_reasons=[reason],
            settlement_reference=settlement_reference,
            min_required_edge=Decimal(str(min_required_edge)),
            yes_score=Decimal(str(yes_score)) if yes_score is not None else None,
            no_score=Decimal(str(no_score)) if no_score is not None else None,
            yes_vote_count=yes_vote_count,
            no_vote_count=no_vote_count,
            selected_side_pre_edge=selected_side_pre_edge,
            selection_reason=selection_reason,
            policy_version=policy_version,
            config_hash=_config_hash,
            build_sha=_build_sha,
            indicators=dict(indicators),
        )
        record_state_checksum(decision_id, asdict(decision), kind="trade_decision")
        return decision

    # Layer-1: market / time gates.
    # Missing, non-finite, or non-positive TTE is a fail-closed no-trade for
    # new entries.  Exits are routed through the execution firewall which has
    # its own reduce-only fallback for stale snapshots.
    if seconds_to_expiry is None or not math.isfinite(seconds_to_expiry) or seconds_to_expiry <= 0:
        return _no_trade("expired_or_no_time")

    # EXIT_ONLY window: no new entries inside the pre-close cutoff.
    # Exits (take-profit, stop, manual close) remain enabled.
    exit_only_cutoff = float(
        os.environ.get(
            "MERID_EXIT_ONLY_CUTOFF_S",
            os.environ.get("MERID_FINAL_MINUTE_CUTOFF_S", "30"),
        )
    )
    if seconds_to_expiry <= exit_only_cutoff:
        return _no_trade("final_minute_entry_disabled")

    # Layer-2: data and regime gates.
    if _data_state != "healthy":
        return _no_trade("data_state_not_healthy")
    if _regime_label == "unknown":
        return _no_trade("regime_unclassified")
    if _regime_probability < MIN_REGIME_POSTERIOR:
        return _no_trade("regime_uncertain")

    # Layer-3: score finiteness assertions (fail-closed).
    if yes_score is not None and not math.isfinite(yes_score):
        return _no_trade("non_finite_yes_score")
    if no_score is not None and not math.isfinite(no_score):
        return _no_trade("non_finite_no_score")
    if p_yes_model is not None and not math.isfinite(p_yes_model):
        return _no_trade("non_finite_p_yes_model")
    if p_no_model is not None and not math.isfinite(p_no_model):
        return _no_trade("non_finite_p_no_model")

    # Kalshi duality: YES ask = 100 - NO bid; NO ask = 100 - YES bid.
    # Prefer the explicit ask if present; otherwise derive it.
    yes_entry = yes_ask_cents / 100.0
    no_entry = no_ask_cents / 100.0
    if yes_ask_cents <= 0 and no_bid_cents > 0:
        yes_entry = (100.0 - no_bid_cents) / 100.0
    if no_ask_cents <= 0 and yes_bid_cents > 0:
        no_entry = (100.0 - yes_bid_cents) / 100.0

    # Validate executable asks are inside [0,1]; a bad quote is a no-trade.
    if not (0.0 <= yes_entry <= 1.0 and 0.0 <= no_entry <= 1.0):
        return _no_trade("invalid_executable_asks")

    # 2026-08-30: resolve and sanity-clamp the Bachelier volatility.  The
    # mid-market price is used only as an optional implied-vol cross-check, never
    # as the p_yes estimate.  Resolved vol, source, band, and z-score are
    # recorded in indicators for telemetry and audit.
    yes_mid_cents = (
        (yes_bid_cents + yes_ask_cents) / 2.0
        if yes_bid_cents > 0 and yes_ask_cents > 0
        else (yes_ask_cents if yes_ask_cents > 0 else 100.0 - no_bid_cents)
    )
    yes_mid_cents = max(1.0, min(99.0, yes_mid_cents))
    market_prob = yes_mid_cents / 100.0

    resolved_vol, vol_source, band_min, band_max, components = _resolve_annualized_vol(
        asset=asset,
        requested_vol=float(annualized_vol),
        spot_price=float(spot_price),
        strike_price=float(strike_price),
        seconds_to_expiry=float(seconds_to_expiry),
        market_prob=market_prob,
    )
    if components is None:
        return _no_trade("bachelier_vol_resolution_failed")
    log_moneyness = components["log_moneyness"]
    z = components["z_score"]
    p_yes_raw = components["p_yes_raw"]
    indicators.update({
        "annualized_vol": resolved_vol,
        "annualized_vol_source": vol_source,
        "annualized_vol_band_min": band_min,
        "annualized_vol_band_max": band_max,
        "log_moneyness": log_moneyness,
        "z_score": z,
        "market_prob_for_implied_vol": market_prob,
        "bachelier_spot": float(spot_price),
        "strike": float(strike_price),
    })

    # 2026-08-30: Per-side tail calibration.  The YES and NO held-side
    # probabilities are calibrated independently from their own tail curves,
    # then the opposite side is derived for logical consistency.  This fixes
    # the dual-inflation bug where capping cheap-YES p_yes forced p_no = 0.95,
    # fabricating large NO edges on expensive NO contracts.
    p_no_raw = 1.0 - p_yes_raw

    # 2026-08-28: accept externally supplied p_yes_model only when hybrid
    # probabilities are explicitly enabled.  Bachelier-only is the live default.
    p_yes_for_yes = float(p_yes_raw)
    p_no_for_no = float(p_no_raw)
    if MERID_TRADE_DECISION_ALLOW_HYBRID_P and p_yes_model is not None and math.isfinite(p_yes_model):
        p_yes_for_yes = max(0.0, min(1.0, p_yes_model))
        p_no_for_no = 1.0 - p_yes_for_yes

    # YES-held curve: calibrate p_yes if YES is in the cheap tail.
    p_yes_for_yes_pre_cap = p_yes_for_yes
    tail_cap_yes_reason = "none"
    tail_calibration_yes_configured = False
    tail_calibration_yes_applied = False
    if MERID_TAIL_CALIBRATION_ENABLED:
        tail_calibrator = load_tail_calibrator()
        if tail_calibrator is not None and yes_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR:
            tail_calibration_yes_configured = True
            tail_cap_yes_reason = "real_curve"
            p_yes_for_yes = tail_calibrator.cap_p_yes(p_yes_for_yes, yes_entry)
            if abs(p_yes_for_yes - p_yes_for_yes_pre_cap) > 1e-9:
                tail_calibration_yes_applied = True
    # Kalshi venue-invariant [0.05, 0.95] so the downstream order router does
    # not reject high-confidence signals as invalid_model_prob.
    p_yes_for_yes = max(0.05, min(0.95, p_yes_for_yes))
    p_no_for_yes = 1.0 - p_yes_for_yes

    # NO-held curve: calibrate p_no if NO is in the cheap tail.
    # The NO curve in the calibration file is currently a dual, so this is a
    # stop-gap until a real NO tail curve is refit from NO-held records.
    # 2026-08-30: To avoid over-correcting moderate NO beliefs, only apply the
    # dual NO cap when the raw NO model probability is itself in the cheap-tail
    # region (below MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR).  A real NO curve
    # (no_curve_is_dual=False) is applied unconditionally in the cheap-price tail.
    p_no_for_no_pre_cap = p_no_for_no
    tail_cap_no_reason = "none"
    tail_calibration_no_configured = False
    tail_calibration_no_applied = False
    if MERID_TAIL_CALIBRATION_ENABLED:
        tail_calibrator = load_tail_calibrator()
        if tail_calibrator is not None and no_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR:
            tail_calibration_no_configured = True
            if tail_calibrator.no_curve_is_dual:
                if p_no_for_no < MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR:
                    tail_cap_no_reason = "dual_raw_cheap"
                    p_no_for_no = tail_calibrator.cap_p_no(p_no_for_no, no_entry)
                    if abs(p_no_for_no - p_no_for_no_pre_cap) > 1e-9:
                        tail_calibration_no_applied = True
                else:
                    tail_cap_no_reason = "dual_moderate_skipped"
                    logger.info(
                        "[TAIL-CALIBRATION-NO-DUAL] asset=%s ticker=%s no_entry=%.3f "
                        "raw_p_no=%.3f >= dual_raw_floor=%.3f; skipping dual NO tail cap",
                        asset, ticker, no_entry, p_no_for_no,
                        MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR,
                    )
            else:
                tail_cap_no_reason = "real_curve"
                p_no_for_no = tail_calibrator.cap_p_no(p_no_for_no, no_entry)
                if abs(p_no_for_no - p_no_for_no_pre_cap) > 1e-9:
                    tail_calibration_no_applied = True
    p_no_for_no = max(0.05, min(0.95, p_no_for_no))
    p_yes_for_no = 1.0 - p_no_for_no

    # Deviation guard: fail-closed.  A large move from the raw model probability
    # on a non-tail held side is a calibration-inflation red flag.  Allow large
    # moves only when the held-side price is below the tail floor (data-backed
    # tail adjustment).  The threshold is configurable; default 0.15.
    tail_calibration_deviation_guard = float(
        os.environ.get("MERID_TAIL_CALIBRATION_DEVIATION_GUARD", "0.15")
    )
    yes_deviation = abs(p_yes_for_yes - p_yes_raw)
    no_deviation = abs(p_no_for_no - p_no_raw)
    yes_in_tail = yes_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR
    no_in_tail = no_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR

    tail_guard_violation_yes = False
    tail_guard_violation_no = False
    if yes_entry > 0 and yes_deviation > tail_calibration_deviation_guard and not yes_in_tail:
        tail_guard_violation_yes = True
        logger.warning(
            "[TAIL-CALIBRATION-GUARD] asset=%s ticker=%s YES held_price=%.2f not in tail; "
            "p_yes deviation %.3f exceeds guard %.3f (raw_p_yes=%.3f, final_p_yes=%.3f)",
            asset, ticker, yes_entry, yes_deviation, tail_calibration_deviation_guard,
            p_yes_raw, p_yes_for_yes,
        )
    if no_entry > 0 and no_deviation > tail_calibration_deviation_guard and not no_in_tail:
        tail_guard_violation_no = True
        logger.warning(
            "[TAIL-CALIBRATION-GUARD] asset=%s ticker=%s NO held_price=%.2f not in tail; "
            "p_no deviation %.3f exceeds guard %.3f (raw_p_no=%.3f, final_p_no=%.3f)",
            asset, ticker, no_entry, no_deviation, tail_calibration_deviation_guard,
            p_no_raw, p_no_for_no,
        )

    indicators.update({
        "p_yes_raw": p_yes_raw,
        "p_no_raw": p_no_raw,
        "p_yes_for_yes": p_yes_for_yes,
        "p_no_for_yes": p_no_for_yes,
        "p_yes_for_no": p_yes_for_no,
        "p_no_for_no": p_no_for_no,
        "p_yes_for_yes_pre_cap": p_yes_for_yes_pre_cap,
        "p_no_for_no_pre_cap": p_no_for_no_pre_cap,
        "tail_cap_yes": tail_calibration_yes_applied,
        "tail_cap_no": tail_calibration_no_applied,
        "tail_cap_yes_reason": tail_cap_yes_reason,
        "tail_cap_no_reason": tail_cap_no_reason,
        "tail_calibration_yes_configured": tail_calibration_yes_configured,
        "tail_calibration_yes_applied": tail_calibration_yes_applied,
        "tail_calibration_no_configured": tail_calibration_no_configured,
        "tail_calibration_no_applied": tail_calibration_no_applied,
        "tail_calibration_yes_reason": tail_cap_yes_reason,
        "tail_calibration_no_reason": tail_cap_no_reason,
        "tail_deviation_yes": yes_deviation,
        "tail_deviation_no": no_deviation,
        "tail_deviation_guard": tail_calibration_deviation_guard,
        "tail_guard_violation_yes": tail_guard_violation_yes,
        "tail_guard_violation_no": tail_guard_violation_no,
        "tail_calibration_no_dual_raw_floor": MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR,
    })

    fee = fee_per_contract_cents / 100.0
    expected_exit_cost_yes = fee
    expected_exit_cost_no = fee

    model_risk_reserve = _compute_model_risk_reserve(
        model_uncertainty, data_quality, regime, seconds_to_expiry
    )

    yes_breakdown = compute_edge(
        p_yes=p_yes_for_yes,
        selected_side="yes",
        entry_price=yes_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_yes,
        model_risk_reserve=model_risk_reserve,
    )
    no_breakdown = compute_edge(
        p_yes=p_yes_for_no,
        selected_side="no",
        entry_price=no_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_no,
        model_risk_reserve=model_risk_reserve,
    )

    # 2026-08-30: Fee-aware, asset-tiered, spread-aware edge threshold.
    # The threshold is evaluated per side because each side has a different
    # price and spread.  ``min_required_edge`` remains the hard global floor.
    yes_price_cents = int(round(yes_entry * 100.0))
    no_price_cents = int(round(no_entry * 100.0))
    yes_min_edge = _compute_dynamic_min_required_edge(
        asset=asset,
        price_cents=yes_price_cents,
        side="yes",
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        floor_min_required_edge=min_required_edge,
    )
    no_min_edge = _compute_dynamic_min_required_edge(
        asset=asset,
        price_cents=no_price_cents,
        side="no",
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        floor_min_required_edge=min_required_edge,
    )
    indicators["yes_min_edge"] = yes_min_edge
    indicators["no_min_edge"] = no_min_edge

    best_side, best_net_edge, best_reason = _select_best_side(yes_breakdown, no_breakdown)
    if selected_side_pre_edge is None and best_side is not None:
        selected_side_pre_edge = best_side
    if selection_reason == "best_executable_edge" and best_reason:
        selection_reason = best_reason

    # Confidence must be valid before any trade can be emitted.
    confidence_result = _compute_confidence(
        data_quality=data_quality,
        regime=regime,
        settlement_reference=settlement_reference,
        seconds_to_expiry=seconds_to_expiry,
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        yes_depth_cc=yes_depth_cc,
        no_depth_cc=no_depth_cc,
        model_uncertainty=model_uncertainty,
    )

    # Selection: prefer the side with the higher *qualifying* net edge.
    # A side qualifies only when its model probability clears the side-aware
    # positive-EV floor (entry + all-in cost reserve) and its net edge clears
    # the threshold.  Ties are no-trade.
    selected_outcome: Optional[Literal["yes", "no"]] = None
    selected_action: Optional[Literal["buy"]] = None
    no_trade_reason: Optional[str] = None
    approved_size_cc = Decimal("0")
    edge_breakdown: Optional[EdgeBreakdown] = None
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None
    selected_outcome_price: Optional[Decimal] = None
    gross_edge: Optional[Decimal] = None
    net_edge: Optional[Decimal] = None

    yes_min_p = _min_p_for_side(yes_breakdown, min_p_selected)
    no_min_p = _min_p_for_side(no_breakdown, min_p_selected)

    yes_qualifies = (
        yes_breakdown.net_edge >= yes_min_edge
        and yes_breakdown.p_selected > yes_min_p
        and not tail_guard_violation_yes
    )
    no_qualifies = (
        no_breakdown.net_edge >= no_min_edge
        and no_breakdown.p_selected > no_min_p
        and not tail_guard_violation_no
    )

    if yes_qualifies and no_qualifies:
        # This should not happen because of duality, but handle explicitly.
        if yes_breakdown.net_edge >= no_breakdown.net_edge:
            selected_outcome = "yes"
            edge_breakdown = yes_breakdown
        else:
            selected_outcome = "no"
            edge_breakdown = no_breakdown
    elif yes_qualifies:
        selected_outcome = "yes"
        edge_breakdown = yes_breakdown
    elif no_qualifies:
        selected_outcome = "no"
        edge_breakdown = no_breakdown
    else:
        # No side qualifies.  Determine the most informative rejection reason.
        if best_side is None:
            no_trade_reason = "directional_tie"
        else:
            best_threshold = yes_min_edge if best_side == "yes" else no_min_edge
            best_min_p = yes_min_p if best_side == "yes" else no_min_p
            if best_net_edge < best_threshold:
                if best_side == "yes":
                    no_trade_reason = "yes_edge_below_threshold"
                else:
                    no_trade_reason = "no_edge_below_threshold"
            else:
                # Edge is sufficient but p_selected does not clear the side-aware
                # positive-EV floor (entry + all-in cost reserve).
                best_p = yes_breakdown.p_selected if best_side == "yes" else no_breakdown.p_selected
                no_trade_reason = f"cost_basis_override_{best_side}"
                indicators[f"cost_basis_override_{best_side}_p"] = best_p
                indicators[f"cost_basis_override_{best_side}_floor"] = best_min_p

            # Counterfactual logging: record the rejected candidate so a
            # post-settlement join can classify saved/missed/flat per bucket.
            _rej_bd = yes_breakdown if best_side == "yes" else no_breakdown
            log_rejected_candidate(
                reason=no_trade_reason,
                run_id=run_id,
                decision_id=decision_id,
                asset=asset,
                ticker=ticker,
                side=best_side,
                model_p_selected=float(_rej_bd.p_selected),
                held_price_cents=float(_rej_bd.executable_entry_price) * 100.0,
                gross_edge=float(_rej_bd.gross_edge),
                net_edge=float(_rej_bd.net_edge),
                edge_threshold=float(best_threshold),
                min_p_selected=float(best_min_p),
                tte_seconds=float(seconds_to_expiry),
                spot_price=float(spot_price),
                strike_price=float(strike_price),
                fee_cents=float(fee) * 100.0,
            )

    if selected_outcome is not None:
        selected_action = "buy"
        # 2026-08-29: Use the resolved live-config per-order contract cap as the
        # default approved size.  In canary mode this is one contract (100 cc).
        _max_contracts = _get_resolved_max_contracts()
        approved_size_cc = Decimal(str(_max_contracts * 100))
        p_selected = Decimal(str(edge_breakdown.p_selected))
        p_opposite = Decimal(str(edge_breakdown.p_opposite))
        selected_outcome_price = Decimal(str(edge_breakdown.executable_entry_price))
        gross_edge = Decimal(str(edge_breakdown.gross_edge))
        net_edge = Decimal(str(edge_breakdown.net_edge))

        # 2026-08-28: Per-bucket π* EV gate.
        # The minimum model probability for a positive risk-adjusted expected
        # value is (held_price + fee + risk_premium) / 100.  Cheap-tail
        # contracts require a larger risk premium because the 7-day data showed
        # severe overconfidence and a 37c average loser.
        _held_price_cents = int(round(float(selected_outcome_price) * 100.0))
        _fee_cents = int(round(fee * 100.0))
        _risk_premium_cents = _pi_star_risk_premium(_held_price_cents)
        _pi_star = (_held_price_cents + _fee_cents + _risk_premium_cents) / 100.0
        if edge_breakdown.p_selected < _pi_star - 1e-9:
            _pi_star_p = edge_breakdown.p_selected
            log_rejected_candidate(
                reason=f"p_selected_below_pi_star:{_pi_star_p:.3f}<{_pi_star:.3f}",
                run_id=run_id,
                decision_id=decision_id,
                asset=asset,
                ticker=ticker,
                side=selected_outcome,
                model_p_selected=float(_pi_star_p),
                held_price_cents=float(_held_price_cents),
                gross_edge=float(edge_breakdown.gross_edge),
                net_edge=float(edge_breakdown.net_edge),
                edge_threshold=float(yes_min_edge if selected_outcome == "yes" else no_min_edge),
                pi_star=float(_pi_star),
                tte_seconds=float(seconds_to_expiry),
                spot_price=float(spot_price),
                strike_price=float(strike_price),
                fee_cents=float(_fee_cents),
            )
            selected_outcome = None
            selected_action = None
            approved_size_cc = Decimal("0")
            p_selected = None
            p_opposite = None
            selected_outcome_price = None
            gross_edge = None
            net_edge = None
            edge_breakdown = None
            no_trade_reason = f"p_selected_below_pi_star:{_pi_star_p:.3f}<{_pi_star:.3f}"

    if selected_outcome is not None:
        # 2026-08-28: Held-side entry price floor.  Cheap-tail contracts have a
        # near-zero realized win rate; we block entries below 35c unless the
        # model is extremely confident (p_selected >= MERID_CHEAP_TAIL_P_EXCEPTION).
        min_held_price_dollars = min_held_price_cents / 100.0
        held_price = float(selected_outcome_price)
        if (
            held_price < min_held_price_dollars
            and edge_breakdown.p_selected < MERID_CHEAP_TAIL_P_EXCEPTION - 1e-9
        ):
            _floor_p = edge_breakdown.p_selected
            log_rejected_candidate(
                reason=f"held_entry_price_below_floor:{held_price:.2f}<{min_held_price_cents/100.0:.2f}|p={_floor_p:.3f}",
                run_id=run_id,
                decision_id=decision_id,
                asset=asset,
                ticker=ticker,
                side=selected_outcome,
                model_p_selected=float(_floor_p),
                held_price_cents=held_price * 100.0,
                gross_edge=float(edge_breakdown.gross_edge),
                net_edge=float(edge_breakdown.net_edge),
                edge_threshold=float(yes_min_edge if selected_outcome == "yes" else no_min_edge),
                tte_seconds=float(seconds_to_expiry),
                spot_price=float(spot_price),
                strike_price=float(strike_price),
                fee_cents=float(fee) * 100.0,
            )
            selected_outcome = None
            selected_action = None
            approved_size_cc = Decimal("0")
            p_selected = None
            p_opposite = None
            selected_outcome_price = None
            gross_edge = None
            net_edge = None
            edge_breakdown = None
            no_trade_reason = (
                f"held_entry_price_below_floor:{held_price:.2f}<"
                f"{min_held_price_cents/100.0:.2f}|p={_floor_p:.3f}"
            )

    # Final confidence gate: even if a side qualifies, an invalid confidence
    # blocks the trade.  This is the hard no-trade rule for missing/fallback
    # confidence.
    if selected_outcome is not None and not confidence_result.valid:
        selected_outcome = None
        selected_action = None
        approved_size_cc = Decimal("0")
        p_selected = None
        p_opposite = None
        selected_outcome_price = None
        gross_edge = None
        net_edge = None
        edge_breakdown = None
        no_trade_reason = "invalid_confidence"

    # 2026-08-29: Executable-cost EV gate.  This is the final entry authority.
    # It is evaluated with the executable price, not the midpoint, and it
    # enforces a minimum dollar EV and a minimum EV/tail-risk ratio.  When it
    # rejects, the selected side is cleared and ``no_trade_reason`` is set to
    # the gate's reason.  The old edge-% and π* outputs remain in the decision
    # record as telemetry.
    ev_gate_allowed = False
    ev_gate_result: Optional[Dict[str, Any]] = None
    adverse_selection_reserve = Decimal("0")
    uncertainty_reserve = Decimal(str(model_risk_reserve))

    if selected_outcome is not None:
        from merid.risk.executable_cost_ev_gate import evaluate_executable_cost_ev, EVInput

        entry_fee = (
            Decimal(str(yes_breakdown.entry_fee))
            if selected_outcome == "yes"
            else Decimal(str(no_breakdown.entry_fee))
        )
        exit_cost = (
            Decimal(str(yes_breakdown.exit_cost_reserve))
            if selected_outcome == "yes"
            else Decimal(str(no_breakdown.exit_cost_reserve))
        )

        ev_input = EVInput(
            p_model=p_selected,
            p_exec=selected_outcome_price,
            qty_cc=int(approved_size_cc),
            entry_fee_per_contract=entry_fee,
            expected_exit_cost_per_contract=exit_cost,
            adverse_selection_reserve_per_contract=adverse_selection_reserve,
            uncertainty_reserve_per_contract=uncertainty_reserve,
            quote_age_ms=quote_age_ms,
            ticker=ticker,
            decision_id=decision_id,
        )
        ev_result = evaluate_executable_cost_ev(ev_input)
        ev_gate_allowed = ev_result.allowed
        ev_gate_result = ev_result.to_dict()

        if MERID_EV_GATE_AUTHORITATIVE and not ev_result.allowed:
            selected_outcome = None
            selected_action = None
            approved_size_cc = Decimal("0")
            p_selected = None
            p_opposite = None
            selected_outcome_price = None
            gross_edge = None
            net_edge = None
            edge_breakdown = None
            no_trade_reason = ev_result.reasons[0] if ev_result.reasons else "ev_gate_rejected"

    # CRITICAL FIX (2026-08-27): Fail fast on dual-side contradiction.
    # The consumed side must equal the dual-side evaluator's output whenever
    # both are non-None.  A mismatch means the candidate generator would use the
    # wrong side.
    if selected_outcome is not None and best_side is not None:
        assert selected_outcome == best_side, (
            f"DUAL-SIDE-CONTRADICTION: selected_outcome={selected_outcome} "
            f"best_side={best_side} decision_id={decision_id}"
        )

    # Use the selected side's dynamic threshold for telemetry; fall back to the
    # global floor when no side was selected.
    if selected_outcome == "yes" or (selected_outcome is None and best_side == "yes"):
        selected_threshold = yes_min_edge
    elif selected_outcome == "no" or (selected_outcome is None and best_side == "no"):
        selected_threshold = no_min_edge
    else:
        selected_threshold = min_required_edge

    # Calibrated p_yes/p_no are now side-specific.  Export the selected side's
    # probabilities; for no-trade telemetry use the best-side (most plausible)
    # pair so p_yes_calibrated reflects the tail cap on a cheap YES candidate.
    if selected_outcome == "yes" or best_side == "yes":
        p_yes_calibrated = p_yes_for_yes
        p_no_calibrated = p_no_for_yes
    elif selected_outcome == "no" or best_side == "no":
        p_yes_calibrated = p_yes_for_no
        p_no_calibrated = p_no_for_no
    else:
        p_yes_calibrated = max(0.05, min(0.95, float(p_yes_raw)))
        p_no_calibrated = 1.0 - p_yes_calibrated

    decision = TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        ticker=ticker,
        asset=asset,
        timestamp_utc=now,
        p_yes_raw=Decimal(str(p_yes_raw)),
        p_yes_calibrated=Decimal(str(p_yes_calibrated)),
        p_yes_uncertainty=Decimal(str(model_risk_reserve)),
        p_no_calibrated=Decimal(str(p_no_calibrated)),
        p_selected=p_selected,
        p_opposite=p_opposite,
        indicators=dict(indicators) if indicators else {},
        regime=regime,
        data_quality=data_quality,
        data_state=_data_state,
        regime_label=_regime_label,
        regime_probability=_regime_probability,
        regime_warmup_samples=regime_warmup_samples,
        seconds_to_expiry=Decimal(str(seconds_to_expiry)),
        settlement_reference=settlement_reference,
        yes_entry_vwap=Decimal(str(yes_entry)),
        no_entry_vwap=Decimal(str(no_entry)),
        yes_depth_cc=Decimal(str(yes_depth_cc)),
        no_depth_cc=Decimal(str(no_depth_cc)),
        fee_yes=Decimal(str(fee)),
        fee_no=Decimal(str(fee)),
        expected_exit_cost_yes=Decimal(str(expected_exit_cost_yes)),
        expected_exit_cost_no=Decimal(str(expected_exit_cost_no)),
        yes_score=Decimal(str(
            yes_score if yes_score is not None else p_yes_calibrated
        )),
        no_score=Decimal(str(
            no_score if no_score is not None else p_no_calibrated
        )),
        yes_vote_count=yes_vote_count,
        no_vote_count=no_vote_count,
        selected_side_pre_edge=selected_side_pre_edge,
        selection_reason=selection_reason,
        yes_net_edge=Decimal(str(yes_breakdown.net_edge)),
        no_net_edge=Decimal(str(no_breakdown.net_edge)),
        best_side=best_side,
        best_net_edge=Decimal(str(best_net_edge)) if best_net_edge is not None else None,
        edge_threshold=Decimal(str(selected_threshold)),
        gross_edge_yes=Decimal(str(yes_breakdown.gross_edge)),
        gross_edge_no=Decimal(str(no_breakdown.gross_edge)),
        net_edge_yes=Decimal(str(yes_breakdown.net_edge)),
        net_edge_no=Decimal(str(no_breakdown.net_edge)),
        entry_fee_yes=Decimal(str(yes_breakdown.entry_fee)),
        entry_fee_no=Decimal(str(no_breakdown.entry_fee)),
        exit_cost_reserve_yes=Decimal(str(yes_breakdown.exit_cost_reserve)),
        exit_cost_reserve_no=Decimal(str(no_breakdown.exit_cost_reserve)),
        model_risk_reserve_yes=Decimal(str(yes_breakdown.model_risk_reserve)),
        model_risk_reserve_no=Decimal(str(no_breakdown.model_risk_reserve)),
        selected_outcome=selected_outcome,
        selected_action=selected_action,
        selected_outcome_price=selected_outcome_price,
        gross_edge=gross_edge,
        net_edge=net_edge,
        no_trade_reason=no_trade_reason,
        edge_breakdown=edge_breakdown,
        yes_edge_breakdown=yes_breakdown,
        no_edge_breakdown=no_breakdown,
        confidence=Decimal(str(confidence_result.value)) if confidence_result.value is not None else None,
        confidence_valid=confidence_result.valid,
        confidence_source=confidence_result.source,
        confidence_reasons=confidence_result.reasons,
        confidence_data_penalty=Decimal(str(confidence_result.data_penalty)),
        confidence_book_penalty=Decimal(str(confidence_result.book_penalty)),
        confidence_model_penalty=Decimal(str(confidence_result.model_penalty)),
        confidence_regime_penalty=Decimal(str(confidence_result.regime_penalty)),
        model_risk_reserve=Decimal(str(model_risk_reserve)),
        min_required_edge=Decimal(str(selected_threshold)),
        approved_size_cc=approved_size_cc,
        policy_version=policy_version,
        adverse_selection_reserve=adverse_selection_reserve,
        uncertainty_reserve=uncertainty_reserve,
        ev_gate_allowed=ev_gate_allowed,
        ev_gate_result=ev_gate_result,
        config_hash=_config_hash,
        build_sha=_build_sha,
    )
    record_state_checksum(decision_id, asdict(decision), kind="trade_decision")

    # 2026-08-29: Write the decision-time ledger snapshot before any order is
    # submitted.  The ledger is append-only; subsequent fills/exit events are
    # recorded by the order lifecycle.
    if MERID_ORDER_DECISION_LEDGER_ENABLED:
        from merid.execution.order_decision_ledger import (
            build_order_decision_record_from_trade_decision,
            get_order_decision_ledger,
        )
        try:
            ledger = get_order_decision_ledger()
            record = build_order_decision_record_from_trade_decision(
                decision,
                ev_gate_result=ev_gate_result,
                build_sha=_build_sha,
            )
            ledger.start(record)
        except Exception as exc:
            logger.warning(
                "[TRADE-DECISION] failed to write decision ledger for %s: %s",
                decision_id,
                exc,
            )

    return decision
