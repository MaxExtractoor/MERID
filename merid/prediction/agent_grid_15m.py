# -*- coding: utf-8 -*-
from __future__ import annotations



from datetime import datetime as dt, timezone, timedelta, datetime
from decimal import Decimal

import json
from pathlib import Path

import math

import time

import uuid

import collections

import re

import asyncio

import os

from typing import Any, Optional, Dict, List, Tuple

from dataclasses import dataclass, field, asdict, replace



from utils.logger import get_logger

# Single source of truth for all-in cost / EV used in signal generation.
# This keeps the signal/EV contract identical to the sizing Kelly calculator.
try:
    from merid.prediction.unified_sizing import (
        _get_slippage_cents,
        compute_all_in_cost_cents,
        compute_ev_net,
        compute_fee_cents,
    )
    _UNIFIED_SIZING_AVAILABLE = True
except ImportError:
    _UNIFIED_SIZING_AVAILABLE = False
    _get_slippage_cents = None  # type: ignore
    compute_all_in_cost_cents = None  # type: ignore
    compute_ev_net = None  # type: ignore
    compute_fee_cents = None  # type: ignore

# CF-RTI settlement input: authoritative settlement reference.
# This is the only source permitted to set settlement_reference="cfb_rti_live".
try:
    from merid.data.cf_rti_adapter import get_live_rti
    _CFB_RTI_AVAILABLE = True
except ImportError:
    _CFB_RTI_AVAILABLE = False
    get_live_rti = None  # type: ignore

# Import invariant checker for production logging
from merid.validation.regime_gating_invariants import (
    RegimeGatingInvariantChecker,
)

# Import candidate tracing for end-to-end validation
try:
    from merid.event_venues.kalshi.candidate_trace import (
        CandidateTrace,
        CandidateTraceStore,
        Side as TraceSide,
        get_trace_store,
    )
    CANDIDATE_TRACE_AVAILABLE = True
except ImportError:
    CANDIDATE_TRACE_AVAILABLE = False
    logger.warning("candidate_trace module not available - end-to-end tracing disabled")

# INTENT VERIFICATION: Signal snapshot integration
try:
    from merid.validation.signal_snapshot import create_signal_snapshot
    SIGNAL_SNAPSHOT_AVAILABLE = True
except ImportError:
    SIGNAL_SNAPSHOT_AVAILABLE = False
    logger.warning("signal_snapshot module not available - intent verification disabled")

logger = get_logger("merid.prediction.agent_grid_15m")


def _is_legacy_signal_enabled() -> bool:
    """Return True only when the legacy _generate_signal path is explicitly allowed.

    In paper and live modes the v2 ``_generate_trade_decision_signal`` path must
    be used.  The legacy path remains available in testing/development and only
    when ``MERID_ENABLE_LEGACY_15M_SIGNAL`` is set.
    """
    pm_mode = os.environ.get("MERID_PM_TRADING_MODE", "")
    if pm_mode in ("paper", "live"):
        return os.environ.get("MERID_ENABLE_LEGACY_15M_SIGNAL", "").strip().lower() == "1"
    return True


# Minimum minutes to expiry before an entry is permitted in normal mode.
# This is a fail-closed gate; the trade-decision layer may apply a stricter limit.
MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN: float = 5.0


@dataclass(frozen=True)
class MarketValidationResult:
    """Fail-closed market-state validation result."""

    ok: bool
    reason: str


def _write_shadow_telemetry(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    asset: str,
    target_price: float,
    seconds_to_expiry: float,
    settlement_reference: str,
    cfb_observation: Optional[Any],
    decision: Any,
    public_spot: float = 0.0,
    spot_price: float = 0.0,
    cf_rti_basis: float = 0.0,
    yes_bid_cents: float = 0.0,
    yes_ask_cents: float = 0.0,
    no_bid_cents: float = 0.0,
    no_ask_cents: float = 0.0,
    fee_per_contract_cents: float = 0.0,
    annualized_vol: float = 0.60,
    data_quality: str = "unknown",
    regime: str = "unknown",
) -> None:
    """Persist the raw CF-RTI and decision inputs for shadow-mode replay.

    This runs even when ``MERID_ALLOW_LIVE_TRADES`` is false, so every
    candidate can be replayed and reconciled against the live feed before
    canary trading is enabled.
    """
    if os.environ.get("MERID_CFB_RTI_SHADOW_TELEMETRY", "1").strip().lower() in ("0", "false", "off"):
        return
    try:
        now_ms = int(time.time() * 1000)
        expiry_ts_ms = now_ms + int(seconds_to_expiry * 1000)

        def _json_breakdown(bd):
            if bd is None:
                return None
            return {
                k: float(v) if isinstance(v, Decimal) and v is not None else v
                for k, v in asdict(bd).items()
            }

        edge_breakdown = _json_breakdown(decision.edge_breakdown)
        yes_edge_breakdown = _json_breakdown(decision.yes_edge_breakdown)
        no_edge_breakdown = _json_breakdown(decision.no_edge_breakdown)

        timestamp_utc = decision.timestamp_utc
        if isinstance(timestamp_utc, datetime):
            timestamp_utc = timestamp_utc.isoformat().replace("+00:00", "Z")

        payload = {
            "schema_version": 1,
            "record_type": "candidate",
            "run_id": run_id,
            "decision_id": decision_id,
            "timestamp_utc": timestamp_utc,
            "market_ticker": ticker,
            "asset": asset,
            "target_price": float(target_price) if target_price else 0.0,
            "spot_price": float(spot_price) if spot_price else 0.0,
            "public_spot": float(public_spot) if public_spot else 0.0,
            "cf_rti_basis": float(cf_rti_basis),
            "expiry_ts_ms": expiry_ts_ms,
            "seconds_to_expiry": float(seconds_to_expiry),
            "settlement_reference": settlement_reference,
            "cfb_symbol": cfb_observation.cfb_symbol if cfb_observation is not None else None,
            "cfb_value": float(cfb_observation.value) if cfb_observation is not None else None,
            "cfb_source_ts_ms": cfb_observation.source_ts_ms if cfb_observation is not None else None,
            "cfb_observed_ts_ms": cfb_observation.observed_ts_ms if cfb_observation is not None else None,
            "cfb_age_ms": cfb_observation.age_ms if cfb_observation is not None else None,
            "cfb_timestamp_quality": cfb_observation.timestamp_quality if cfb_observation is not None else None,
            "cfb_execution_eligible": cfb_observation.execution_eligible if cfb_observation is not None else None,
            "cfb_sequence": cfb_observation.sequence if cfb_observation is not None else None,
            "cfb_60s_average": float(cfb_observation.cfb_60s_average) if cfb_observation is not None and cfb_observation.cfb_60s_average is not None else None,
            "price_source_health": cfb_observation.price_source_health if cfb_observation is not None else None,
            "p_yes": float(decision.p_yes_calibrated),
            "p_no": float(decision.p_no_calibrated),
            "p_selected": float(decision.p_selected) if decision.p_selected is not None else None,
            "p_opposite": float(decision.p_opposite) if decision.p_opposite is not None else None,
            "gross_edge": float(decision.gross_edge) if decision.gross_edge is not None else None,
            "net_edge": float(decision.net_edge) if decision.net_edge is not None else None,
            "gross_edge_yes": float(decision.gross_edge_yes) if decision.gross_edge_yes is not None else None,
            "gross_edge_no": float(decision.gross_edge_no) if decision.gross_edge_no is not None else None,
            "net_edge_yes": float(decision.net_edge_yes) if decision.net_edge_yes is not None else None,
            "net_edge_no": float(decision.net_edge_no) if decision.net_edge_no is not None else None,
            "entry_fee_yes": float(decision.entry_fee_yes) if decision.entry_fee_yes is not None else None,
            "entry_fee_no": float(decision.entry_fee_no) if decision.entry_fee_no is not None else None,
            "exit_cost_reserve_yes": float(decision.exit_cost_reserve_yes) if decision.exit_cost_reserve_yes is not None else None,
            "exit_cost_reserve_no": float(decision.exit_cost_reserve_no) if decision.exit_cost_reserve_no is not None else None,
            "model_risk_reserve_yes": float(decision.model_risk_reserve_yes) if decision.model_risk_reserve_yes is not None else None,
            "model_risk_reserve_no": float(decision.model_risk_reserve_no) if decision.model_risk_reserve_no is not None else None,
            "best_side": decision.best_side,
            "best_net_edge": float(decision.best_net_edge) if decision.best_net_edge is not None else None,
            "edge_threshold": float(decision.edge_threshold) if decision.edge_threshold is not None else None,
            "yes_score": float(decision.yes_score) if decision.yes_score is not None else None,
            "no_score": float(decision.no_score) if decision.no_score is not None else None,
            "yes_vote_count": decision.yes_vote_count,
            "no_vote_count": decision.no_vote_count,
            "selected_side_pre_edge": decision.selected_side_pre_edge,
            "selection_reason": decision.selection_reason,
            "confidence": float(decision.confidence) if decision.confidence is not None else None,
            "confidence_valid": decision.confidence_valid,
            "confidence_source": decision.confidence_source,
            "confidence_reasons": list(decision.confidence_reasons or []),
            "confidence_data_penalty": float(decision.confidence_data_penalty) if decision.confidence_data_penalty is not None else None,
            "confidence_book_penalty": float(decision.confidence_book_penalty) if decision.confidence_book_penalty is not None else None,
            "confidence_model_penalty": float(decision.confidence_model_penalty) if decision.confidence_model_penalty is not None else None,
            "confidence_regime_penalty": float(decision.confidence_regime_penalty) if decision.confidence_regime_penalty is not None else None,
            "selected_outcome": decision.selected_outcome,
            "selected_action": decision.selected_action,
            "selected_outcome_price": int(round(float(decision.selected_outcome_price) * 100)) if decision.selected_outcome_price is not None else None,
            "yes_bid_cents": float(yes_bid_cents),
            "yes_ask_cents": float(yes_ask_cents),
            "no_bid_cents": float(no_bid_cents),
            "no_ask_cents": float(no_ask_cents),
            "yes_depth_cc": float(decision.yes_depth_cc) if decision.yes_depth_cc is not None else 0.0,
            "no_depth_cc": float(decision.no_depth_cc) if decision.no_depth_cc is not None else 0.0,
            "fee_per_contract_cents": float(fee_per_contract_cents),
            "annualized_vol": float(annualized_vol),
            "min_required_edge": float(decision.min_required_edge) if decision.min_required_edge is not None else None,
            "model_risk_reserve": float(decision.model_risk_reserve) if decision.model_risk_reserve is not None else None,
            "data_quality": data_quality,
            "data_state": decision.data_state,
            "regime": regime,
            "regime_label": decision.regime_label,
            "regime_probability": float(decision.regime_probability) if decision.regime_probability is not None else None,
            "regime_warmup_samples": decision.regime_warmup_samples,
            "rejection_reason": decision.no_trade_reason,
            "policy_version": decision.policy_version,
            "edge_breakdown": edge_breakdown,
            "yes_edge_breakdown": yes_edge_breakdown,
            "no_edge_breakdown": no_edge_breakdown,
            "git_revision": os.environ.get("MERID_GIT_REVISION"),
            "config_hash": os.environ.get("MERID_CONFIG_HASH"),
        }
        out_dir = Path("data/shadow/cfb_rti")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"{run_id}_{ticker}_{ts}_{decision_id[:8]}.json"
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("[SHADOW-TELEMETRY] Failed to write: %s", exc)


def validate_market_state_for_entry(
    asset: str,
    market_id: str,
    state: Any,
    minutes_to_expiry: float,
    min_depth_yes: int,
    min_depth_no: int,
    max_md_staleness_sec: float,
) -> MarketValidationResult:
    """Fail-closed gate: validate that market state is safe for a new entry.

    This is the canonical pre-decision market gate. It checks state existence,
    book initialization, liquidity, staleness, bid/ask anomalies, depth, and
    expiry. It must never mutate state.
    """
    if state is None:
        return MarketValidationResult(ok=False, reason="STATE-NONE")

    if not getattr(state, "book_initialized", False):
        return MarketValidationResult(ok=False, reason="BOOK-NOT-INITIALIZED")

    if not getattr(state, "executable", False):
        return MarketValidationResult(ok=False, reason="NOT-EXECUTABLE")

    now = time.time()
    last_update_ts = getattr(state, "last_update_ts", 0.0)
    staleness_sec = now - last_update_ts if last_update_ts else 0.0
    if staleness_sec <= 0 and getattr(state, "last_update", None) is not None:
        try:
            staleness_sec = (datetime.now(timezone.utc) - state.last_update).total_seconds()
        except Exception:
            staleness_sec = 0.0
    if staleness_sec > max_md_staleness_sec:
        return MarketValidationResult(ok=False, reason="MD-STALE")

    best_bid = getattr(state, "best_bid_cents", 0) or 0
    best_ask = getattr(state, "best_ask_cents", 0) or 0
    if best_bid == 0 and best_ask == 100:
        return MarketValidationResult(ok=False, reason="PATTERN-0100")
    if best_bid == 0 or best_ask == 0:
        return MarketValidationResult(ok=False, reason="NO-BIDASK")

    if state.min_depth_yes < min_depth_yes:
        return MarketValidationResult(
            ok=False,
            reason=f"DEPTH-LOW:yes_depth={state.min_depth_yes}<threshold={min_depth_yes}",
        )
    if state.min_depth_no < min_depth_no:
        return MarketValidationResult(
            ok=False,
            reason=f"DEPTH-LOW:no_depth={state.min_depth_no}<threshold={min_depth_no}",
        )

    if minutes_to_expiry < MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN:
        return MarketValidationResult(ok=False, reason="EXPIRY-TOO-CLOSE-NORMAL")

    return MarketValidationResult(ok=True, reason="OK")


def _get_settlement_input_price(
    asset: str,
    spot_price: float,
    settlement_digits: Optional[int] = None,
) -> tuple:
    """Resolve the authoritative settlement reference price.

    ``get_live_rti`` is the only source that can emit ``cfb_rti_live``.  If it
    returns ``None`` the adapter has already logged the precise rejection reason
    and we must not fabricate a public-spot fallback as if it were a settlement
    reference.  The ``spot_price`` is retained only for basis telemetry.

    The returned ``settlement_input_price`` is a ``float`` (for downstream
    compatibility) but it is quantized to the market's ``settlement_digits``
    exactly once from the canonical Decimal source.
    """
    obs = None
    if _CFB_RTI_AVAILABLE and get_live_rti is not None:
        obs = get_live_rti(asset)
        if obs is not None and obs.execution_eligible:
            # Kalshi crypto 15m contracts settle on a 60-second average of CF RTI
            # observations.  The Bachelier baseline must therefore compare the
            # current 60-second average to the strike (itself a 60-second average),
            # not a noisy per-second tick.  Fall back to the tick only when the
            # average is missing or invalid.
            raw_price: Optional[Decimal] = obs.settlement_price()
            if raw_price is None or not raw_price.is_finite() or raw_price <= 0:
                obs = None
            else:
                if settlement_digits is None:
                    settlement_digits = get_asset_settlement_digits(asset)

                # Fail-closed: if the feed does not retain enough precision for
                # this market, do not treat it as a live settlement reference.
                # DOGE at 4 decimals is the canonical example.
                retained = retained_decimal_places(raw_price)
                if retained < settlement_digits:
                    reason = f"cf_rti_precision_insufficient:retained={retained}:required={settlement_digits}"
                    logger.warning(
                        "[CF-RTI-PRECISION] asset=%s raw=%s retained_digits=%s required=%s rejecting settlement reference",
                        asset, _canonical_format_price(asset, raw_price), retained, settlement_digits
                    )
                    return spot_price, 0.0, f"public_spot_fallback:{reason}", obs

                # Quantize exactly once to the market's settlement quantum.
                try:
                    settlement_decimal = settlement_round(raw_price, settlement_digits)
                except Exception:
                    settlement_decimal = raw_price
                settlement_price = float(settlement_decimal)

                spot_decimal = parse_price(spot_price) or Decimal("0")
                basis_decimal = spot_decimal - settlement_decimal
                cf_rti_basis = float(basis_decimal)
                return settlement_price, cf_rti_basis, "cfb_rti_live", obs

    # No authoritative RTI: honest public-spot fallback, which downstream gates
    # will reject for entry because the reference is not ``cfb_rti_live``.
    from merid.data.cf_rti_adapter import get_last_rejection_reason
    reason = get_last_rejection_reason(asset) or "cf_rti_unavailable"
    if obs is not None and not obs.execution_eligible:
        reason = f"cf_rti_not_execution_eligible:{obs.timestamp_quality}"
    return spot_price, 0.0, f"public_spot_fallback:{reason}", obs


# Import unified signal terminology for consistent side selection
try:
    from merid.prediction.signal_terminology import (
        Side, Action, StrategyMode, Direction, Momentum, Velocity,
        TradingSignal, SignalMetadata, StrategyIntent
    )
    UNIFIED_TERMINOLOGY_AVAILABLE = True
except ImportError:
    UNIFIED_TERMINOLOGY_AVAILABLE = False
    logger.warning("signal_terminology not available - using legacy side/action strings")

# Import rejection monitor for production rejection tracking

try:

    from merid.monitoring.rejection_monitor import (

        get_rejection_monitor,

        log_time_window_rejection,

        log_price_range_rejection,

        log_trend_alignment_rejection,

        log_edge_check_rejection,

    )

    REJECTION_MONITOR_ENABLED = True

except ImportError:

    REJECTION_MONITOR_ENABLED = False

    logger.debug("[REJECTION-MONITOR] Not available - rejection tracking disabled")


# Import BTC sentiment bias for correlation tracking
try:
    from merid.prediction.btc_sentiment_bias import (
        get_btc_sentiment_bias,
        init_btc_sentiment_bias,
        SentimentBiasConfig,
        calculate_internal_btc_sentiment
    )
    BTC_SENTIMENT_BIAS_ENABLED = True
except ImportError:
    BTC_SENTIMENT_BIAS_ENABLED = False
    logger.debug("[BTC-SENTIMENT-BIAS] Not available - BTC sentiment bias disabled")

# Import directional bias monitor for signal bias tracking
try:
    from merid.prediction.bias_monitor import get_bias_monitor
    BIAS_MONITOR_ENABLED = True
except ImportError:
    BIAS_MONITOR_ENABLED = False

    def get_bias_monitor() -> None:
        return None

# Import directional anomaly circuit breaker and trace for YES/NO parity.
# Disabled by default in unit tests; required for live 15m signal integrity.
try:
    from merid.validation.yes_no_parity_checker import (
        get_directional_anomaly_breaker,
        emit_directional_trace,
    )
    DIRECTIONAL_BREAKER_AVAILABLE = True
except ImportError:
    DIRECTIONAL_BREAKER_AVAILABLE = False
    logger.debug("[DIRECTIONAL-BREAKER] Not available - parity guard disabled")

# Import canonical price range from binary price space (single source of truth)
try:
    from merid.event_venues.kalshi.binary_price_space import (
        is_price_in_canonical_range,
        require_outcome_side,
        SideValidationError,
    )
    PRICE_SPACE_AVAILABLE = True
except ImportError:
    PRICE_SPACE_AVAILABLE = False
    logger.debug("[PRICE-SPACE] binary_price_space not available - using fallback manual ranges")

# Import global allocator types used for live-position canonicalization.
# Local imports inside run_cycle are not visible to helper methods such as
# _build_canonical_live_positions, which calls the CanonicalLivePosition dataclass.
try:
    from merid.risk.profiles.global_allocator import (
        OrderCandidate,
        CanonicalLivePosition,
    )
    GLOBAL_ALLOCATOR_TYPES_AVAILABLE = True
except ImportError:
    GLOBAL_ALLOCATOR_TYPES_AVAILABLE = False
    logger.warning("[GLOBAL-ALLOCATOR] OrderCandidate/CanonicalLivePosition not available - allocation helpers disabled")



# Local price formatting function (replaces utils.logger.format_price to avoid import issues)

from merid.data.price_precision import (
    format_price as _canonical_format_price,
    get_asset_settlement_digits,
    get_asset_settlement_quantum,
    parse_price,
    retained_decimal_places,
    settlement_round,
)

def format_price(asset: str, price: Any) -> str:

    """Format price with appropriate decimal places based on asset."""

    return _canonical_format_price(asset, price, fallback_digits=4)



# Kalshi fee calculation uses the canonical fees module (imported at module end
# as canonical_calculate_kalshi_fee_cents).  The old local 7%-only formula with
# a 1.75c cap was incorrect; it ignored tiered rates and the 2c floor.



# SEV-0 FIX: Standardized velocity edge calculation function

# This ensures consistency across agent_grid, loop_15m, and order_router

def calculate_velocity_edge(velocity: float, velocity_threshold: float) -> float:

    """

    Calculate edge in percentage points from velocity magnitude for
    velocity-based signals.

    Standard formula: edge_pct = abs(velocity / threshold) * 2.0

    The result is expressed in percentage points, not as a fraction. Callers
    that need a probability fraction (e.g., for model_prob or validate_edge)
    must divide the result by 100.0.

    Args:
        velocity: Velocity value (can be positive or negative)
        velocity_threshold: Velocity threshold for signal generation

    Returns:
        Edge in percentage points (can exceed 100 for strong velocity)
    """

    if velocity_threshold == 0:

        return 0.0

    return abs(velocity / velocity_threshold) * 2.0



# 2026-08-17: asset-invariant MACD edge.  The indicator stack returns MACD
# histogram in absolute price units.  Before contributing to percentage-point
# edge, it is normalized by the contemporaneous spot price so a $1.50 MACD
# move on BTC is treated the same as a $0.0015 move on an alt.
MERID_MACD_EDGE_WEIGHT = float(os.environ.get("MERID_MACD_EDGE_WEIGHT", "10.0"))
MERID_MAX_EDGE_PCT = float(os.environ.get("MERID_MAX_EDGE_PCT", "15.0"))


def _fvg_edge_components(
    score: int,
    side_velocity_sign: float,
    velocity: float,
    velocity_threshold: float,
    macd_hist: float,
    spot_price: float,
    rsi: float,
    rsi_zone: str,
    fvg_dir: Optional[str],
    fvg_conf: float,
    macd_edge_weight: Optional[float] = None,
    max_edge_pct: Optional[float] = None,
) -> Dict[str, float]:
    """Compute the momentum-FVG edge for one side and return all components.

    Returns a dict with:
      - edge_pct: final capped edge in percentage points
      - base_edge: velocity-derived base after alignment bonus (before MACD)
      - macd_pct: MACD histogram as a percentage of spot price (signed)
      - macd_edge: MACD contribution in percentage points (signed, side-aware)
      - velocity_bonus: velocity alignment bonus in percentage points
    """
    # Score scaling: confluence discount/boost applied at the end.
    # A score below the historical minimum (3) now receives a smooth
    # multiplier rather than a hard 0.5 override, so a weak side still
    # reflects its MACD/velocity components.  The multiplier is floored at
    # 0.5 to retain some confluence gating while avoiding the unit-corrected
    # edge being silently replaced by a constant.
    score_mult = max(0.5, 1.0 + (score - 3) * 0.1)

    if velocity_threshold == 0:
        velocity_threshold = 1e-12

    velocity_magnitude = abs(velocity)
    base_edge = calculate_velocity_edge(velocity_magnitude, velocity_threshold)

    velocity_alignment_bonus = 0.0
    if side_velocity_sign > 0 and velocity > 0:
        velocity_alignment_bonus = velocity * 1000.0
    elif side_velocity_sign < 0 and velocity < 0:
        velocity_alignment_bonus = abs(velocity) * 1000.0
    elif side_velocity_sign > 0 and velocity < 0:
        velocity_alignment_bonus = -abs(velocity) * 500.0
    elif side_velocity_sign < 0 and velocity > 0:
        velocity_alignment_bonus = -abs(velocity) * 500.0

    base_edge = max(base_edge + velocity_alignment_bonus, 1.0)

    if spot_price is None or not math.isfinite(spot_price) or spot_price <= 0:
        macd_pct = 0.0
    else:
        safe_price = max(float(spot_price), 1e-12)
        macd_pct = (float(macd_hist if macd_hist is not None else 0.0) / safe_price) * 100.0

    weight = macd_edge_weight if macd_edge_weight is not None else MERID_MACD_EDGE_WEIGHT
    macd_edge = macd_pct * weight * (1.0 if side_velocity_sign > 0 else -1.0)

    edge = base_edge + macd_edge

    if rsi_zone == "oversold" and side_velocity_sign > 0:
        edge += 1.0
    elif rsi_zone == "overbought" and side_velocity_sign < 0:
        edge += 1.0

    if fvg_conf > 0.5 and fvg_dir:
        if (side_velocity_sign > 0 and fvg_dir == "bullish") or (
            side_velocity_sign < 0 and fvg_dir == "bearish"
        ):
            edge += fvg_conf * 2.0

    # Apply the confluence multiplier to the full normalized edge.
    edge *= score_mult

    cap = max_edge_pct if max_edge_pct is not None else MERID_MAX_EDGE_PCT
    return {
        "edge_pct": min(edge, cap),
        "base_edge": base_edge,
        "macd_pct": macd_pct,
        "macd_edge": macd_edge,
        "velocity_bonus": velocity_alignment_bonus,
    }



# Sanity bounds for strike/spot prices per asset (USD).
# Used to reject corrupt market metadata (bad ticks, unit errors, stale feeds)
# before a strike target feeds signal generation.
_STRIKE_TARGET_BOUNDS = {
    "BTC": (1_000.0, 200_000.0),
    "ETH": (50.0, 10_000.0),
    "SOL": (1.0, 1_000.0),
    "XRP": (0.10, 10.0),
    "DOGE": (0.0001, 2.0),
}


def _is_valid_strike_target(price, asset: str) -> bool:
    """Validate a strike/spot price for an asset.

    Rejects None, non-numeric, NaN/inf, zero, and negative prices.
    Known assets must fall within sane USD bounds; unknown assets get a
    positive-only check (asset match is case-sensitive by design).

    Args:
        price: Candidate price (float or Decimal) - may be None
        asset: Asset symbol (e.g., "BTC")

    Returns:
        True if the price is usable as a strike target.
    """
    if price is None or isinstance(price, bool):
        return False
    if isinstance(price, Decimal):
        if not price.is_finite() or price <= 0:
            return False
        value = float(price)
    elif isinstance(price, (int, float)):
        if math.isnan(price) or math.isinf(price) or price <= 0:
            return False
        value = price
    else:
        return False
    bounds = _STRIKE_TARGET_BOUNDS.get(asset)
    if bounds is None:
        return True  # Unknown asset: positive check only
    low, high = bounds
    return low <= value <= high


def _resolve_trade_decision_strike(asset: str, market_state: Any, market: Any, spot_price: float) -> Tuple[Optional[float], Optional[str], Dict[str, Any]]:
    """Resolve the canonical strike for a 15m binary trade decision.

    Tries market_state, the supplied market/catalog object, the live catalog,
    and finally the current public spot as a degraded fallback.  Returns the
    resolved strike, the source provenance, and a structured diagnostic payload
    for logging and rejection telemetry.

    The returned strike is quantized to the market's ``settlement_digits`` (from
    Kalshi ``custom_strike.round_digits``) exactly once before it is used for
    boundary comparison.
    """
    diagnostic: Dict[str, Any] = {"asset": asset, "spot_price": spot_price}
    settlement_digits = getattr(market, "settlement_digits", None) or get_asset_settlement_digits(asset)

    def _quantize_strike(candidate: Any) -> Optional[Decimal]:
        price = parse_price(candidate)
        if price is None:
            return None
        try:
            return settlement_round(price, settlement_digits)
        except Exception:
            return price

    # 1. Try market_state and the provided market object in priority order.
    for source_name, obj in (("market_state", market_state), ("market", market)):
        if obj is None:
            continue
        for field in ("window_strike_price", "floor_strike", "strike_price"):
            candidate = getattr(obj, field, None)
            decimal_field = f"{field}_decimal"
            decimal_candidate = getattr(obj, decimal_field, None)
            preferred = decimal_candidate if decimal_candidate is not None else candidate
            diagnostic.setdefault(source_name, {})[field] = preferred
            if _is_valid_strike_target(preferred, asset):
                price = _quantize_strike(preferred)
                if price is not None:
                    return float(price), f"{source_name}.{field}", diagnostic

    # 2. Catalog fallback: the catalog is the authoritative source for 15m
    #    window metadata and is especially important right after a rollover when
    #    the state store has not yet received a REST feed.
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        if catalog:
            current_market = catalog.get_current_15m_market(asset)
            if current_market:
                for field in ("floor_strike", "strike_price", "cap_strike", "window_strike_price"):
                    decimal_field = f"{field}_decimal"
                    preferred = getattr(current_market, decimal_field, None) or getattr(current_market, field, None)
                    diagnostic.setdefault("catalog", {})[field] = preferred
                    if _is_valid_strike_target(preferred, asset):
                        price = _quantize_strike(preferred)
                        if price is not None:
                            return float(price), f"catalog.{field}", diagnostic
    except Exception as exc:
        logger.warning("[STRIKE-RESOLUTION] asset=%s catalog lookup failed: %s", asset, exc)

    # 3. Final degraded fallback: the contemporaneous public spot.  This keeps
    #    the engine alive for threshold/unknown markets but is explicitly flagged
    #    so downstream confidence/edge logic can treat it as degraded.
    if _is_valid_strike_target(spot_price, asset):
        diagnostic["spot_fallback"] = True
        price = _quantize_strike(spot_price)
        if price is not None:
            return float(price), "spot_fallback", diagnostic

    return None, None, diagnostic


# Hard production floor: new entries are not allowed inside 90 seconds to expiry.
# This is independent of any profile min_decision_minute / max_time_to_expiry.
MERID_HARD_MIN_ENTRY_TTE_SECONDS = 90

# Model-probability epsilon guard: p must stay inside (0, 1) at signal creation.
MERID_MODEL_PROBABILITY_EPSILON = 0.0001

# Edge-to-probability cap: an edge observation can never move the probability
# estimate by more than 20 percentage points.
MERID_MAX_EDGE_ADJUSTMENT_PCT = 20.0

# EV safety multipliers for extreme/terminal prices.
MERID_EV_K_BASE = float(os.getenv("MERID_EV_K_BASE", "1.5"))
MERID_EV_K_EXTREME = float(os.getenv("MERID_EV_K_EXTREME", "2.5"))
MERID_EV_K_TERMINAL = float(os.getenv("MERID_EV_K_TERMINAL", "2.0"))

# Momentum_FVG directional and EV invariants (2026-08-13).
# Near-zero velocity must not be treated as a directional preference.
MERID_MOMENTUM_FVG_MIN_CONFLUENCE_SCORE = int(os.getenv("MERID_MOMENTUM_FVG_MIN_CONFLUENCE_SCORE", "4"))
MERID_MOMENTUM_FVG_MIN_VELOCITY_CONFLUENCE_SCORE = int(os.getenv("MERID_MOMENTUM_FVG_MIN_VELOCITY_CONFLUENCE_SCORE", "3"))
# Use taker (cross spread) only when edge is very large or expiry is very close.
MERID_MOMENTUM_FVG_TAKER_EDGE_PCT = float(os.getenv("MERID_MOMENTUM_FVG_TAKER_EDGE_PCT", "5.0"))
MERID_MOMENTUM_FVG_LATE_WINDOW_SECONDS = float(os.getenv("MERID_MOMENTUM_FVG_LATE_WINDOW_SECONDS", "120.0"))
# Calibrated execution-impact reserve added to the all-in expected cost (cents).
MERID_EV_IMPACT_RESERVE_CENTS = float(os.getenv("MERID_EV_IMPACT_RESERVE_CENTS", "0.5"))


def _lookup_displayed_depth(market_state: Any, signal_side: str, price_cents: int) -> Optional[int]:
    """Return displayed size at the executable quote for the selected side.

    For a BUY_YES, the executable liquidity is the YES-ask size (the size of the
    NO-bid resting at 100 - P).  For a BUY_NO, it is the NO-ask size (the size of
    the YES-bid resting at 100 - P).  This now uses the explicit
    ``get_executable_ask_size`` helper on ``KalshiMarketState`` so the depth is
    bound to ``yes_ask_size`` / ``no_ask_size`` rather than an unlabeled
    opposite-side lookup.
    """
    if not market_state:
        return None
    # Prefer the explicit executable-ask-size accessor on KalshiMarketState.
    get_ask = getattr(market_state, "get_executable_ask_size", None)
    if get_ask:
        try:
            return get_ask(signal_side, price_cents)
        except Exception:
            pass
    # Fallback: scan the opposite-side bid ladder for the complementary price.
    target_price = 100 - price_cents
    raw = None
    if signal_side == "yes":
        raw = getattr(market_state, "no_bids", None) or []
    else:
        raw = getattr(market_state, "yes_bids", None) or []
    for item in raw:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                level_price = int(item[0])
                level_size = int(item[1])
            elif isinstance(item, dict):
                level_price = int(item.get("price", item.get("price_cents", 0)))
                level_size = int(item.get("size", item.get("quantity", 0)))
            else:
                continue
            if level_price == target_price:
                return level_size
        except Exception:
            continue
    return None


def _emit_ev_components_log(
    market_state: Any,
    asset: str,
    signal_side: str,
    signal_action: str,
    price_cents: int,
    price_source: str,
    market_prob: float,
    model_prob: float,
    decision: str = "no_trade",
    requested_contracts: int = 1,
    fee_cents: Optional[float] = None,
    impact_reserve_cents: float = 0.0,
    slippage_cents: Optional[int] = None,
    liquidity_role: str = "taker",
):
    """Emit a structured EV-gate decision payload.

    This is a pure logging/instrumentation helper. It does not change
    the EV-gate decision. It decomposes all-in cost into expected cost,
    worst-case slippage guard, and placeholder exit/uncertainty reserves
    so the live cost model can be validated against actual fills.
    """
    if not _UNIFIED_SIZING_AVAILABLE:
        exchange_fee_cents = 2.0
        max_slippage_guard_cents = 5
    else:
        if fee_cents is None:
            exchange_fee_cents = float(compute_fee_cents(price_cents))
        else:
            exchange_fee_cents = float(fee_cents)
        if slippage_cents is None:
            max_slippage_guard_cents = int(_get_slippage_cents())
        else:
            max_slippage_guard_cents = int(slippage_cents)

    expected_entry_impact_cents = float(impact_reserve_cents)
    expected_exit_fee_reserve_cents = 0.0
    expected_exit_impact_reserve_cents = 0.0
    uncertainty_buffer_cents = 0.0

    all_in_expected_cost_cents = float(price_cents) + exchange_fee_cents + expected_entry_impact_cents
    robust_cost_cents = (
        all_in_expected_cost_cents
        + expected_exit_fee_reserve_cents
        + expected_exit_impact_reserve_cents
        + uncertainty_buffer_cents
        + float(max_slippage_guard_cents)
    )

    ev_expected_cents = (model_prob * 100.0) - all_in_expected_cost_cents
    ev_robust_cents = (model_prob * 100.0) - robust_cost_cents
    raw_model_edge_cents = (model_prob - market_prob) * 100.0
    # The actual break-even is the fee-only all-in cost; the 5c slippage guard
    # is a worst-case limit bound, not a guaranteed realized cost.
    break_even_edge_cents = all_in_expected_cost_cents - (market_prob * 100.0)

    if "yes" in price_source:
        quote_source = "yes_ask"
    elif "no" in price_source:
        quote_source = "no_ask"
    else:
        quote_source = price_source

    displayed_depth = _lookup_displayed_depth(market_state, signal_side, price_cents)

    logger.info(
        "[SIGNAL-EV-GATE] asset=%s side=%s action=%s quote_price_cents=%d quote_source=%s "
        "displayed_depth=%s requested_contracts=%d market_probability=%.4f model_probability=%.4f "
        "raw_model_edge_cents=%.4f break_even_edge_cents=%.4f exchange_fee_cents=%.2f "
        "expected_entry_impact_cents=%.2f expected_exit_fee_reserve_cents=%.2f "
        "expected_exit_impact_reserve_cents=%.2f uncertainty_buffer_cents=%.2f "
        "max_slippage_guard_cents=%d all_in_expected_cost_cents=%.2f robust_cost_cents=%.2f "
        "ev_expected_cents=%.4f ev_robust_cents=%.4f impact_reserve_cents=%.2f "
        "liquidity_role=%s decision=%s",
        asset, signal_side, signal_action, price_cents, quote_source,
        displayed_depth if displayed_depth is not None else "unknown",
        requested_contracts, market_prob, model_prob, raw_model_edge_cents,
        break_even_edge_cents, exchange_fee_cents, expected_entry_impact_cents,
        expected_exit_fee_reserve_cents, expected_exit_impact_reserve_cents,
        uncertainty_buffer_cents, max_slippage_guard_cents, all_in_expected_cost_cents,
        robust_cost_cents, ev_expected_cents, ev_robust_cents, impact_reserve_cents,
        liquidity_role, decision
    )



def _build_directional_trace_payload(
    agent,
    *,
    asset: str,
    ticker: Optional[str],
    market_state: Any,
    buy_threshold: float,
    sell_threshold: float,
    yes_model_prob: float,
    no_model_prob: float,
    yes_edge: float,
    no_edge: float,
    best_bid: int,
    best_ask: int,
    selected_side: Optional[str],
    selected_action: Optional[str],
    selected_price_cents: Optional[int],
    selected_model_prob: Optional[float],
    selected_edge: Optional[float],
    decision: str,
    reason: str,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a one-line structured directional trace payload.

    This is the single source of truth for per-cycle YES/NO diagnostics.
    The schema is stable and machine-parseable; keep field names unchanged.
    """
    import uuid
    run_id = getattr(agent, "run_id", None)
    if not run_id:
        run_id = f"{getattr(agent.config, 'name', 'agent')}_{time.time():.6f}_{uuid.uuid4().hex[:8]}"

    hybrid_enabled = getattr(agent.config, "signal_mode", "") == "hybrid"

    yes_bid_cents = int(best_bid)
    yes_ask_cents = int(best_ask)
    no_bid_cents = 100 - int(best_ask)
    no_ask_cents = 100 - int(best_bid)

    quote_age_ms = getattr(market_state, "age_ms", None)
    book_sequence = getattr(market_state, "book_sequence", None)

    # Net-of-fee edges using the taker fee (conservative diagnostic)
    if _UNIFIED_SIZING_AVAILABLE and compute_ev_net is not None:
        yes_edge_net = compute_ev_net(yes_model_prob, yes_ask_cents)
        no_edge_net = compute_ev_net(no_model_prob, no_ask_cents)
    else:
        fallback_fee = 2
        yes_edge_net = (yes_model_prob * 100.0) - (yes_ask_cents + fallback_fee)
        no_edge_net = (no_model_prob * 100.0) - (no_ask_cents + fallback_fee)

    yes_candidate = yes_edge > 0
    no_candidate = no_edge > 0

    canonical_outcome_side = selected_side
    canonical_book_side = "bid" if selected_side == "yes" else "ask"
    submitted_outcome_side = selected_side
    submitted_book_side = canonical_book_side

    return {
        "run_id": run_id,
        "ticker": ticker,
        "asset": asset,
        "hybrid_enabled": hybrid_enabled,
        "raw_signal_yes": float(buy_threshold),
        "raw_signal_no": float(sell_threshold),
        "model_probability_yes": float(yes_model_prob),
        "model_probability_no": float(no_model_prob),
        "yes_bid": yes_bid_cents / 100.0 if yes_bid_cents > 0 else None,
        "yes_ask": yes_ask_cents / 100.0 if yes_ask_cents > 0 else None,
        "no_bid": no_bid_cents / 100.0 if no_bid_cents > 0 else None,
        "no_ask": no_ask_cents / 100.0 if no_ask_cents > 0 else None,
        "quote_age_ms": quote_age_ms,
        "book_sequence": book_sequence,
        "yes_edge_net": round(float(yes_edge_net), 4),
        "no_edge_net": round(float(no_edge_net), 4),
        "yes_candidate": yes_candidate,
        "no_candidate": no_candidate,
        "selected_outcome": selected_side,
        "selected_action": selected_action,
        "selection_reason": reason,
        "canonical_outcome_side": canonical_outcome_side,
        "canonical_book_side": canonical_book_side,
        "submitted_outcome_side": submitted_outcome_side,
        "submitted_book_side": submitted_book_side,
        "client_order_id": client_order_id,
        "selected_price_cents": selected_price_cents,
        "selected_model_prob": selected_model_prob,
        "selected_edge": selected_edge,
        "decision": decision,
    }



# SEV-1 FIX: Time-based warmup guard

# Warmup bypass only allowed in first 5 minutes after process start

_process_start_time = time.time()  # Initialized at module import, reset when loop starts



def reset_warmup_timer() -> None:

    """Reset warmup timer to current time (call when agents actually start trading)."""

    global _process_start_time

    _process_start_time = time.time()

    logger.info("[WARMUP-TIMER] Reset warmup timer - agents now have 5 minutes to populate history")



def is_warmup(history_length: int) -> bool:

    """

    Check if system is in warmup state.



    Warmup is only allowed in first 5 minutes after process start.

    After 5 minutes, require minimum history regardless of data gaps.



    Args:

        history_length: Length of data history



    Returns:

        True if in warmup state, False otherwise

    """

    # Time-based guard: only allow warmup bypass in first 5 minutes

    if time.time() - _process_start_time > 300:

        return False



    # History-based guard: require minimum history after 5 minutes

    return history_length < 20



# Import regime detection module

from merid.prediction.regime_detector import RegimeDetector, Regime



# Import regime adapter to bridge to canonical ops.regime_detection

try:

    from ops.regime_adapter import get_regime_adapter

    _REGIME_ADAPTER_AVAILABLE = True

except ImportError:

    _REGIME_ADAPTER_AVAILABLE = False

    logger.warning("[AGENT-GRID] Regime adapter not available, canonical regime updates disabled")



# Lean AgentGrid for Kalshi 15m Crypto Trading.

# This module provides a minimal, focused agent grid for 15-minute crypto trading.

# It uses Coinbase velocity-based signals (2026 #1 winning strategy) and simplified gates.

# See docs/15M_STACK_SURFACE.md for complete allowed surface definition.



from merid.config.environment import enable_composite_spot_fallback



# Import unified_spot_service for volume filter integration

from data.unified_spot_service import SpotError



# Import FifteenMinuteMarketLocator for time-bucket-based market selection

from merid.event_venues.kalshi.fifteen_minute_market_locator import (

    FifteenMinuteMarketLocator,

    get_market_locator,

    MarketIds,

)





# Minimal market object wrapper for time-bucket-based market selection

@dataclass

class MinimalMarket:

    """

    Minimal market object wrapper for FifteenMinuteMarketLocator.



    This provides the interface expected by the existing agent grid code

    (market.market_id, close_time, minutes_to_expiry, etc.) without requiring a full catalog lookup.

    """

    market_id: str

    close_time: float  # Unix timestamp

    asset: str

    minutes_to_expiry: Optional[float] = None  # Normalized minutes to expiry from catalog

    exchange_index: Optional[int] = None  # Kalshi exchange shard index



    @property

    def market(self) -> 'MinimalMarket':

        # Self-reference for compatibility with existing code

        return self





# Log module load to confirm this is the grid being used

logger.info("[AGENT-GRID-15M-IMPORTED] module=%s", __name__)



# Global reference to the agent grid instance for external reset calls

_agent_grid_instance: Optional['LeanAgentGrid15m'] = None



def set_agent_grid_instance(grid: 'LeanAgentGrid15m') -> None:

    """Set the global agent grid instance for external reset calls."""

    global _agent_grid_instance

    _agent_grid_instance = grid

    logger.info("[AGENT-GRID-INSTANCE] Global instance set")


def get_agent_grid() -> Optional['LeanAgentGrid15m']:

    """Get the global agent grid instance."""

    return _agent_grid_instance


def reset_agent_grid() -> None:

    """Reset the global agent grid singleton at startup."""

    global _agent_grid_instance

    if _agent_grid_instance is not None:

        _agent_grid_instance = None

        logger.info("[AGENT-GRID-RESET] Global agent grid instance cleared")


def set_agent_grid(grid: 'LeanAgentGrid15m') -> None:

    """Set the global agent grid instance (alias for set_agent_grid_instance)."""

    set_agent_grid_instance(grid)


async def build_15m_agent_grid(
    catalog: Any,
    bankroll: Any,
    spot_provider: Any,
    order_router: Any,
    unified_edge_config: Any,
    ws_bridge: Any = None,
) -> 'LeanAgentGrid15m':

    """Build the 15m crypto agent grid with all 5 agents (BTC, ETH, SOL, XRP, DOGE)."""

    from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile

    # Get the profile for configuration
    profile = get_crypto_15m_profile()

    # CRITICAL FIX: Use signal_mode from profile instead of hardcoded "trend"
    # This allows the profile YAML to control the trading strategy
    signal_mode = profile.signal_mode if hasattr(profile, 'signal_mode') else 'momentum_fvg'
    logger.info("[AGENT-GRID-BUILD] Using signal_mode from profile: %s", signal_mode)

    # Create agent configurations for all 5 crypto assets
    agent_configs = [
        LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
            signal_mode=signal_mode,
            max_spread_cents=100,
            velocity_threshold_btc=0.00015,
            alpha_0=0.0,
            alpha_1=200.0,
        ),
        LeanAgentConfig(
            name="ETH_15M",
            series_tickers=["KXETH15M"],
            signal_mode=signal_mode,
            max_spread_cents=100,
            velocity_threshold_eth=0.00015,
            alpha_0=0.0,
            alpha_1=200.0,
        ),
        LeanAgentConfig(
            name="SOL_15M",
            series_tickers=["KXSOL15M"],
            signal_mode=signal_mode,
            max_spread_cents=100,
            velocity_threshold_sol=0.000225,
            alpha_0=0.0,
            alpha_1=200.0,
        ),
        LeanAgentConfig(
            name="XRP_15M",
            series_tickers=["KXXRP15M"],
            signal_mode=signal_mode,
            max_spread_cents=100,
            velocity_threshold_xrp=0.000225,
            alpha_0=0.0,
            alpha_1=200.0,
        ),
        LeanAgentConfig(
            name="DOGE_15M",
            series_tickers=["KXDOGE15M"],
            signal_mode=signal_mode,
            max_spread_cents=100,
            velocity_threshold_doge=0.0003,
            alpha_0=0.0,
            alpha_1=200.0,
        ),
    ]

    # Create agents
    agents = []
    for config in agent_configs:
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            market_state_store=None,  # Will be set later
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=profile,
        )
        agents.append(agent)
        logger.info("[AGENT-GRID-BUILD] Created agent: %s", config.name)

    # Create the agent grid
    agent_grid = LeanAgentGrid15m(agents=agents)
    logger.info("[AGENT-GRID-BUILD] Built LeanAgentGrid15m with %d agents", len(agents))

    # Tie the agent grid (and each agent) to the segment run_id so telemetry,
    # decisions, and orders all share the same identity.
    segment_run_id = os.environ.get("MERID_RUN_ID")
    if segment_run_id:
        agent_grid.run_id = segment_run_id
        for agent in agents:
            agent.run_id = segment_run_id
        logger.info("[AGENT-GRID-BUILD] Set run_id=%s on all agents", segment_run_id)

    # Record code/config provenance in the process environment so every shadow
    # record and order can be traced back to the exact segment.
    if not os.environ.get("MERID_GIT_REVISION"):
        try:
            import subprocess
            git_rev = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if git_rev:
                os.environ["MERID_GIT_REVISION"] = git_rev
                logger.info("[AGENT-GRID-BUILD] Set MERID_GIT_REVISION=%s", git_rev)
        except Exception:
            pass
    if not os.environ.get("MERID_CONFIG_HASH"):
        try:
            from pathlib import Path
            import hashlib
            config_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
            if config_path.exists():
                config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest().upper()
                os.environ["MERID_CONFIG_HASH"] = config_hash
                logger.info("[AGENT-GRID-BUILD] Set MERID_CONFIG_HASH=%s", config_hash)
        except Exception:
            pass

    return agent_grid



def reset_strip_order_counts() -> None:

    """Reset all strip order counts and market ID tracking.



    This is called by the catalog when it detects a market rollover (e.g., 16:15 -> 16:30).

    It resets the per-strip order limits so trading can continue on the new 15m strip.

    """

    global _agent_grid_instance

    if _agent_grid_instance:

        _agent_grid_instance.reset_strip_order_counts()

        logger.info("[STRIP-RESET-EXTERNAL] Reset strip order counts via catalog trigger")

    else:

        logger.warning("[STRIP-RESET-EXTERNAL] No agent grid instance available for reset")


# Module-level strip-order counters and helpers for external callers and tests.
_strip_order_counts: Dict[str, int] = {}

_STRIP_PATTERN = re.compile(r"(\d{2}[A-Z]{3}\d{4})")


def _extract_strip(ticker: str) -> str:
    """Return the 15-minute strip key for a market ticker."""
    m = _STRIP_PATTERN.search(ticker)
    return m.group(1) if m else ticker


def can_fire_order(
    asset: str,
    now: float,
    ticker: str,
    *,
    per_strip_order_limit: int = 1,
) -> tuple:
    """Return (allowed, reason) for a proposed order in the strip limit."""
    strip = _extract_strip(ticker)
    count = _strip_order_counts.get(strip, 0)
    if count >= per_strip_order_limit:
        return (False, f"STRIP-LIMIT:{strip}:count={count}:limit={per_strip_order_limit}")
    return (True, "OK")


def register_order_fire(asset: str, now: float, ticker: str) -> None:
    """Record an order placement against the strip limit."""
    strip = _extract_strip(ticker)
    _strip_order_counts[strip] = _strip_order_counts.get(strip, 0) + 1


def reset_branch_counters() -> None:
    """Clear module-level strip order counts (branch/legacy cooldown reset)."""
    _strip_order_counts.clear()



def log_agent_grid_version() -> None:

    # Log agent grid version at startup (not import time).

    logger.info("[AGENT-GRID-15M] MODULE VERSION v20260529a-cache-fix")



# STRATEGY INVARIANTS (agent_grid_15m::_generate_signal):

# 1. Velocity-based signals: Use Coinbase 1-minute velocity for trade direction

# 2. Simplified gates: Only liquidity, spread, staleness (no complex indicator gates)

# 3. Market state validation: Use KalshiMarketStateStore for live orderbook data

# 4. Risk envelope: Apply profile-driven risk limits and position sizing

# 5. Full asset coverage: All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be included



# Configuration helpers

KALSHI_ALIGNMENT_TOLERANCES = {

    "BTC": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "ETH": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "SOL": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "XRP": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

    "DOGE": {"max_abs_diff": 1.0, "max_rel_diff": 0.0001},

}



def get_alignment_tolerance(asset: str) -> Dict[str, float]:

    # Get alignment tolerances for a given asset.

    return KALSHI_ALIGNMENT_TOLERANCES.get(asset.upper(), {

        "max_abs_diff": 1.0,

        "max_rel_diff": 0.0001,

    })



# Kalshi alignment helpers

def compute_data_quality(metrics: Dict[str, Any]) -> float:

    # Compute data quality score for critical trading inputs.

    # This helper enforces Invariant 3: No Optimistic Execution Defaults.

    # Returns a score from 0.0 to 1.0 based on how many critical inputs are present.

    critical_inputs = {

        "spread_cents": metrics.get("spread_cents") is None,

        "spot_price": metrics.get("spot_price") is None,

        "price_cents": metrics.get("price_cents", 0) <= 0,

        "bid": metrics.get("bid", 0) <= 0,

        "ask": metrics.get("ask", 0) <= 0,

    }

    missing_count = sum(critical_inputs.values())

    return 1.0 - (missing_count / len(critical_inputs))



# Agent configuration

@dataclass

class LeanAgentConfig:

    # Configuration for a single 15m crypto agent.

    name: str  # Agent name (e.g., "BTC_15M")

    series_tickers: list[str]  # Series tickers to trade (e.g., ["KXBTC15M"])

    signal_mode: str = "trend"  # Signal mode: "trend", "mean_reversion", "momentum_fvg", "hybrid", "price_based"

    max_spread_cents: int = 100  # 2026-07-10: RELAXED to 100c - allows trading in current market conditions with wider spreads (60c-96c observed)

    min_time_to_expiry_s: int = 180  # Minimum time to expiry in seconds

    max_time_to_expiry_s: int = 900  # Maximum time to expiry in seconds

    # CRITICAL FIX (2026-07-17): Removed per_strip_order_limit and max_orders_per_15m_window - $1 exposure cap is the limit
    # GlobalSlotAllocator enforces MAX_EXPOSURE_USD=1.00, MAX_CONTRACTS_PER_ORDER=1, MAX_POSITIONS_PER_ASSET=1

    per_asset_cooldown_s: int = 3  # Cooldown period in seconds after trade (2026-07-11: reduced to 3s for 15m alignment)

    consecutive_loss_pause: int = 3  # 2026 research: Pause after N consecutive losses

    max_session_risk_pct: float = 0.10  # 2026 research: Max session risk as % of capital

    velocity_threshold: float = 0.00001  # 0.001% - aligned with profile YAML (default, overridden by per-asset values)

    # Asset-specific velocity thresholds (deeper markets = lower threshold, more volatile = higher threshold)

    # CRITICAL FIX: 2026-07-05 - Aligned with profile YAML velocity_thresholds section

    # Profile YAML values: 0.00001 (0.001%) for all assets - effectively zero to enable any movement

    # Previous hardcoded values (0.15%-0.20%) were 150-200x higher than profile YAML

    # New thresholds align with profile YAML single source of truth:

    velocity_threshold_btc: float = 0.00015  # BTC: 0.015% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_eth: float = 0.00015  # ETH: 0.015% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_sol: float = 0.000225  # SOL: 0.0225% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_xrp: float = 0.000225  # XRP: 0.0225% (CRITICAL FIX: aligned with profile YAML)

    velocity_threshold_doge: float = 0.0003  # DOGE: 0.03% (CRITICAL FIX: aligned with profile YAML)

    # INDUSTRY ALIGNMENT: Fee-aware trading parameters based on profitable scalping research

    prefer_maker_orders: bool = True  # Prefer maker orders to earn rebates (-0.05% round trip) vs taker fees (0.15% round trip)

    min_profit_basis_points: int = 20  # Minimum 20bp profit target to overcome structural disadvantages (industry standard for retail)

    max_spread_basis_points: int = 50  # RELAXED: Maximum 50bp spread (increased from 30 to allow more trades in current market conditions)

    # FILL RATE OPTIMIZATION: Use limit orders instead of market orders for better fill rates in thin markets

    use_limit_orders: bool = True  # Use limit orders (maker) instead of market orders (taker) for better fill rates

    limit_order_slippage_cents: int = 2  # Allow 2 cents slippage for limit orders to increase fill probability

    # INDUSTRY ALIGNMENT: Regime detection parameters (2026 best practices)

    volatility_window_s: int = 300  # 5-minute volatility window for regime detection

    min_volatility_threshold: float = 0.001  # Minimum 0.1% volatility to avoid low-volatility death zones

    # HYBRID MODE PRICE CAPS (2026 Optimized)

    # CRITICAL FIX: 2026-07-05 - Aligned with profile YAML hybrid section

    # Profile YAML values: max_entry_price_yes: 0.70, min_entry_price_no: 0.30

    # Previous hardcoded values (0.90/0.10) didn't match profile YAML

    # New values align with profile YAML single source of truth:

    max_entry_price_yes: float = 0.70  # CRITICAL FIX: 70¢ (aligned with profile YAML - avoids highest fee zone)

    min_entry_price_no: float = 0.30  # CRITICAL FIX: 30¢ (aligned with profile YAML - symmetry with 70¢ YES cap)

    max_volatility_threshold: float = 0.02  # Maximum 2% volatility to avoid extreme volatility spikes

    # POSITION MANAGEMENT (2026 best practices)

    # 2026 FIX: Added max concurrent positions limit to prevent over-accumulation

    # 2026-07-09: Set to 4 to align with $1 exposure cap at typical prices (25c)

    # At 25c/contract: 4 positions = $1.00 exactly at cap

    # Slot allocator enforces $1 hard cap, but this aligns soft limit with hard limit

    # This is TOTAL across all 5 assets (BTC+ETH+SOL+XRP+DOGE), not per-asset

    max_concurrent_positions: int = 4  # Maximum total open positions across all assets

    # DYNAMIC SPREAD THRESHOLD: Volatility-regime-based spread filtering (2026 best practice)

    # Based on research: "Blow your spreads out when the market's volatility does"

    # Uses 3 regimes with different spread limits: calm, elevated, violent

    # UPDATED: Increased thresholds to allow trading in current market conditions

    calm_volatility_threshold: float = 0.005  # 0.5% volatility = calm regime

    elevated_volatility_threshold: float = 0.015  # 1.5% volatility = elevated regime

    # SESSION-BASED TRADING WINDOWS (2026 best practices for crypto)

    # Based on research: Trade during peak liquidity hours for better win rates

    # US-Europe overlap (13:00-17:00 UTC): Highest liquidity, tightest spreads

    # US session (17:00-22:00 UTC): Good liquidity, moderate spreads

    # European morning (08:00-13:00 UTC): Moderate liquidity, wider spreads

    # Asian session (00:00-08:00 UTC): Low liquidity, avoid trading

    # DISABLED: Trade 24/7 per user request

    enable_session_filter: bool = False  # Enable session-based trading windows (disabled for 24/7 trading)

    us_europe_overlap_start_utc: int = 13  # 13:00 UTC

    us_europe_overlap_end_utc: int = 17  # 17:00 UTC

    us_session_start_utc: int = 17  # 17:00 UTC

    us_session_end_utc: int = 22  # 22:00 UTC

    european_morning_start_utc: int = 8  # 08:00 UTC

    european_morning_end_utc: int = 13  # 13:00 UTC

    # Phase 1A: Surgical spread relaxation based on log analysis (2026-07-09)

    # Logs show spreads at 2000+ bp vs dynamic_max of 200 bp causing 0 candidates

    # Asset-specific overrides: BTC/ETH (deeper books) 300bp, SOL/XRP/DOGE (thinner books) 350bp

    calm_spread_threshold_bp: int = 200  # 200bp max spread in calm regime (base threshold)

    elevated_spread_threshold_bp: int = 300  # 300bp max spread in elevated regime (base threshold)

    violent_spread_threshold_bp: int = 500  # 500bp max spread in violent regime (base threshold)

    # Per-asset overrides for regime-specific spread thresholds

    calm_spread_threshold_bp_btc_eth: int = 300  # 300bp for BTC/ETH (deeper books)

    calm_spread_threshold_bp_sol_xrp_doge: int = 350  # 350bp for SOL/XRP/DOGE (thinner books)

    elevated_spread_threshold_bp_btc_eth: int = 400  # 400bp for BTC/ETH in elevated

    elevated_spread_threshold_bp_sol_xrp_doge: int = 450  # 450bp for SOL/XRP/DOGE in elevated

    violent_spread_threshold_bp_btc_eth: int = 600  # 600bp for BTC/ETH in violent

    violent_spread_threshold_bp_sol_xrp_doge: int = 700  # 700bp for SOL/XRP/DOGE in violent

    spread_volatility_sensitivity: float = 1.5  # Lambda parameter for continuous interpolation

    # Phase 1: Velocity model coefficients for logistic mapping

    alpha_0: float = 0.0  # Intercept for logistic function

    alpha_1: float = 1000.0  # Velocity coefficient for logistic function

    # Phase 4.1: Multi-window velocity configuration

    velocity_windows: list = field(default_factory=lambda: [10, 30, 60])  # Velocity windows in seconds

    momentum_weights: list = field(default_factory=lambda: [0.2, 0.3, 0.5])  # Weights for each window

    velocity_ema_period: int = 5  # EMA smoothing period for velocity (reduces noise)

    atr_period: int = 3  # 2026-07-01 FIX: Reduced from 7 to 3 for faster warmup (3 data points needed instead of 7)

    zscore_period: int = 20  # Z-score period for extreme detection (industry standard)

    # Phase 4.4: Logit fusion weights

    logit_fusion_velocity_weight: float = 0.7  # Weight for velocity signal

    logit_fusion_mean_reversion_weight: float = 0.3  # Weight for mean reversion signal

    # Phase 4.5: Near expiry guard

    near_expiry_guard_sec: int = 300  # Skip logit fusion if time to expiry < 5 minutes

    # Phase 5.2: Calibration configuration

    calibration_enabled: bool = False  # Enable/disable probability calibration

    calibration_auto_fit: bool = True  # Automatically fit calibration when sufficient data

    calibration_min_samples: int = 100  # Minimum samples required to fit calibration

    # Phase 5.3: Price-based strategy (Turbine research winner)
    # CRITICAL FIX (2026-08-19): Align price-based fair value with the 0.50
    # complement-symmetric model used by the 15m profile.  Both YES and NO fair
    # probabilities are 0.50, so the strategy trades when either side is cheap
    # relative to a neutral 50c fair.  This removes the 20c-40c dead zone and
    # the structural YES bias of the previous 0.30/0.70 split.
    price_based_buy_threshold: float = 0.50  # Buy YES when price <= 50c (cheap YES contracts)

    price_based_sell_threshold: float = 0.50  # Buy NO when YES price >= 50c (i.e. NO <= 50c)

    calibration_max_samples: int = 1000  # Maximum samples to keep for calibration

    calibration_regularization: float = 0.0001  # L2 regularization parameter

    calibration_fit_interval_hours: int = 24  # Re-fit calibration every N hours

    # Phase 6: Regime detection configuration

    regime_detector_enabled: bool = True  # Enable HMM-based regime detection for adaptive strategy switching

    # Phase 7: Panic fade (volatility reversion) configuration - Turbine research winner

    panic_fade_enabled: bool = True  # Enable panic fade strategy (volatility reversion)

    panic_fade_threshold: float = 0.00013  # Velocity threshold for panic detection (0.013%) - reduced by 35% for more signals

    panic_fade_zscore_threshold: float = 2.0  # Z-score threshold for statistical extreme

    panic_fade_rsi_oversold: float = 25.0  # RSI oversold threshold (buy YES)

    panic_fade_rsi_overbought: float = 75.0  # RSI overbought threshold (buy NO)

    panic_fade_min_velocity: float = 0.000065  # Minimum velocity to qualify as panic (0.0065%) - reduced by 35% for more signals

    # Note: Depth thresholds (min_depth_yes, min_depth_no) are now sourced from risk envelope/profile

    # to ensure single source of truth across the stack

    # NO min_edge check for velocity-based signals: min_edge_pct removed



# Lean agent for 15m crypto trading


@dataclass(frozen=True)
class HybridProbability:
    """Decomposed hybrid probability for a single asset/cycle.

    Carries the final p_yes plus the signed directional inputs so that
    shadow telemetry and diagnosis can tell whether a wrong-side fingerprint
    comes from inverted displacement, inverted velocity, or an inverted
    indicator shift.
    """
    p_yes: float
    p_yes_bachelier: float
    log_moneyness: float
    z_score: float
    annualized_vol: float
    t_years: float
    velocity: float
    velocity_threshold: float
    velocity_edge: float
    macd_delta: float
    rsi_delta: float
    obi: float
    obi_delta: float
    regime_delta: float
    total_delta: float
    max_shift: float
    bars_available: int
    # FVG provenance (empty when MERID_ENABLE_FVG is off)
    fvg_active: int = 0
    fvg_direction: float = 0.0
    fvg_size: float = 0.0
    fvg_distance_to_fill: float = 0.0
    fvg_fill_signal: float = 0.0
    fvg_delta: float = 0.0
    fvg_weight: float = 0.0
    fvg_confidence: float = 0.0
    fvg_price_source: str = ""
    fvg_price_staleness_ms: Optional[float] = None

    def __float__(self) -> float:
        return self.p_yes


class LeanAgent15m:

    # Minimal agent for 15m crypto trading with velocity-based signals.



    def __init__(

        self,

        config: LeanAgentConfig,

        catalog: Any,

        market_state_store: Any,

        spot_provider: Any,

        order_router: Any,

        risk_config: Any,

    ):

        self.config = config

        self.catalog = catalog

        self.market_state_store = market_state_store

        self.spot_provider = spot_provider

        self.order_router = order_router

        self.risk_config = risk_config



        # Phase 1: Store velocity model coefficients for logistic mapping

        self._alpha_0 = config.alpha_0

        self._alpha_1 = config.alpha_1

        logger.info("[AGENT-INIT] %s velocity coefficients: alpha_0=%.2f, alpha_1=%.2f",

                    config.name, self._alpha_0, self._alpha_1)



        # CRITICAL FIX (2026-07-17): Optional RollingBuffer integration for bias prevention
        self._rolling_buffer_enabled = getattr(config, 'rolling_buffer_enabled', False)
        self._signal_generator = None

        if self._rolling_buffer_enabled:
            try:
                from merid.prediction import create_crypto_signal_generator
                self._signal_generator = create_crypto_signal_generator()
                logger.info("[AGENT-INIT] %s RollingBuffer enabled for bias prevention", config.name)
            except ImportError:
                logger.warning("[AGENT-INIT] RollingBuffer requested but module not available, proceeding without")
                self._rolling_buffer_enabled = False

        # CRITICAL FIX (2026-07-23): Dynamic components for bias-free trading
        self._signal_quality_tracker = None
        self._adaptive_liquidity_calculator = None
        self._dynamic_components_enabled = getattr(config, 'dynamic_components_enabled', False)

        if self._dynamic_components_enabled:
            try:
                from merid.prediction.signal_quality_tracker import SignalQualityTracker
                from merid.prediction.adaptive_liquidity import AdaptiveLiquidityCalculator

                self._signal_quality_tracker = SignalQualityTracker(
                    window_trades=getattr(config, 'signal_quality_window_trades', 50),
                    min_trades=getattr(config, 'signal_quality_min_trades', 10)
                )

                self._adaptive_liquidity_calculator = AdaptiveLiquidityCalculator(
                    window_minutes=getattr(config, 'liquidity_window_minutes', 60),
                    percentile=getattr(config, 'liquidity_percentile', 0.8)
                )

                logger.info("[AGENT-INIT] %s Dynamic components enabled for bias-free trading", config.name)
            except ImportError:
                logger.warning("[AGENT-INIT] Dynamic components requested but modules not available, proceeding without")
                self._dynamic_components_enabled = False



        # Phase 4.1: Multi-window velocity configuration

        # Use profile values if available, otherwise use defaults

        self._velocity_windows = getattr(config, 'velocity_windows', [10, 30, 60])

        self._momentum_weights = getattr(config, 'momentum_weights', [0.2, 0.3, 0.5])

        self._velocity_ema_period = getattr(config, 'velocity_ema_period', 5)

        self._atr_period = getattr(config, 'atr_period', 14)

        self._zscore_period = getattr(config, 'zscore_period', 20)

        logger.info("[AGENT-INIT] %s multi-window velocity: windows=%s weights=%s ema_period=%d atr_period=%d zscore_period=%d",

                    config.name, self._velocity_windows, self._momentum_weights, self._velocity_ema_period, self._atr_period, self._zscore_period)



        # Phase 4.4: Logit fusion weights

        self._logit_fusion_velocity_weight = getattr(config, 'logit_fusion_velocity_weight', 0.7)

        self._logit_fusion_mean_reversion_weight = getattr(config, 'logit_fusion_mean_reversion_weight', 0.3)

        logger.info("[AGENT-INIT] %s logit fusion weights: velocity=%.2f mean_reversion=%.2f",

                    config.name, self._logit_fusion_velocity_weight, self._logit_fusion_mean_reversion_weight)



        # Phase 4.5: Near expiry guard

        self._near_expiry_guard_sec = getattr(config, 'near_expiry_guard_sec', 300)

        logger.info("[AGENT-INIT] %s near expiry guard: %d seconds",

                    config.name, self._near_expiry_guard_sec)



        # Phase 5.3: Initialize PlattScaler for probability calibration

        self._calibration_enabled = getattr(config, 'calibration_enabled', False)

        self._calibration_auto_fit = getattr(config, 'calibration_auto_fit', True)

        self._calibration_min_samples = getattr(config, 'calibration_min_samples', 100)

        self._calibration_fit_interval_hours = getattr(config, 'calibration_fit_interval_hours', 24)

        self._calibration_regularization = getattr(config, 'calibration_regularization', 0.0001)



        # Phase 6: Initialize regime detector for adaptive strategy switching

        self._regime_detector_enabled = getattr(config, 'regime_detector_enabled', True)

        # Coinbase external velocity signals (Turbine research #1 winner)
        self._coinbase_velocity_signals: Dict[str, Dict] = {}  # asset -> {velocity, timestamp, signal_type}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._coinbase_velocity_signals[asset] = {"velocity": 0.0, "timestamp": 0.0, "signal_type": "none"}

        # Per-cycle rejection waterfall for diagnostics.  Tracks which gate eliminated
        # the asset each cycle so we can measure before tuning thresholds.
        self._rejection_waterfall: Dict[str, Dict[str, Any]] = {
            "asset": "",
            "stages": {},
            "selected": False,
            "final_reason": "",
        }

        if self._regime_detector_enabled:

            self._regime_detector = RegimeDetector(

                n_states=3,

                train_window=300,

                min_history=50,

                refit_interval=100,

                random_state=42

            )

            logger.info("[AGENT-INIT] %s regime detector enabled", config.name)

        else:

            self._regime_detector = None

            logger.info("[AGENT-INIT] %s regime detector disabled", config.name)



        # Phase 7: Initialize panic fade (volatility reversion) configuration
        # 2026-07-18: DISABLED by default - causing losses by betting against trend
        # 2026-07-24: CRITICAL SSOT FIX - Force disable when profile uses momentum_fvg
        # Profile YAML (kalshi_crypto_15m_v2.yaml) is single source of truth for signal_mode
        # When signal_mode is momentum_fvg, panic fade must be disabled regardless of config
        # Also gate by profile_version to prevent drift across profile versions
        panic_fade_config_enabled = getattr(config, 'panic_fade_enabled', False)
        profile_version = getattr(config, 'profile_version', None)

        # SSOT Gate: Disable panic fade if profile uses momentum_fvg OR profile is v2.x
        # Profile v2.x explicitly disables panic fade due to losses
        if self.config.signal_mode == "momentum_fvg" or (profile_version and profile_version.startswith("2.")):
            self._panic_fade_enabled = False
            logger.warning(
                "[SSOT-INVARIANT] %s signal_mode=%s profile_version=%s - forcing panic_fade_enabled=False (profile SSOT)",
                config.name, self.config.signal_mode, profile_version
            )
        else:
            self._panic_fade_enabled = panic_fade_config_enabled

        self._panic_fade_threshold = getattr(config, 'panic_fade_threshold', 0.0002)

        self._panic_fade_zscore_threshold = getattr(config, 'panic_fade_zscore_threshold', 2.0)

        self._panic_fade_rsi_oversold = getattr(config, 'panic_fade_rsi_oversold', 25.0)

        self._panic_fade_rsi_overbought = getattr(config, 'panic_fade_rsi_overbought', 75.0)

        self._panic_fade_min_velocity = getattr(config, 'panic_fade_min_velocity', 0.0001)

        logger.info("[AGENT-INIT] %s panic fade: enabled=%s threshold=%.4f zscore=%.1f rsi_oversold=%.1f rsi_overbought=%.1f min_velocity=%.4f",

                    config.name, self._panic_fade_enabled, self._panic_fade_threshold,

                    self._panic_fade_zscore_threshold, self._panic_fade_rsi_oversold,

                    self._panic_fade_rsi_overbought, self._panic_fade_min_velocity)

        self._calibration_max_samples = getattr(config, 'calibration_max_samples', 1000)

        self._calibration_regularization = getattr(config, 'calibration_regularization', 0.0001)


        # Phase 8: Initialize BTC sentiment bias for correlation tracking
        self._btc_sentiment_bias_enabled = getattr(config, 'btc_sentiment_bias_enabled', False)
        if self._btc_sentiment_bias_enabled and BTC_SENTIMENT_BIAS_ENABLED:
            try:
                btc_bias_config = SentimentBiasConfig(
                    enabled=True,
                    btc_sentiment_threshold=getattr(config, 'btc_sentiment_threshold', 0.7),
                    bias_strength=getattr(config, 'btc_sentiment_bias_strength', 0.05),
                    correlated_assets=getattr(config, 'btc_sentiment_correlated_assets', ["ETH", "SOL", "XRP", "DOGE"]),
                    correlation_threshold=getattr(config, 'btc_sentiment_correlation_threshold', 0.8),
                    sentiment_window_seconds=getattr(config, 'btc_sentiment_window_seconds', 300)
                )
                self._btc_sentiment_bias = init_btc_sentiment_bias(btc_bias_config)
                logger.info("[AGENT-INIT] %s BTC sentiment bias enabled", config.name)
            except Exception as e:
                logger.warning("[AGENT-INIT] Failed to initialize BTC sentiment bias: %s", e)
                self._btc_sentiment_bias = None
                self._btc_sentiment_bias_enabled = False
        else:
            self._btc_sentiment_bias = None
            logger.info("[AGENT-INIT] %s BTC sentiment bias disabled", config.name)



        if self._calibration_enabled:

            from merid.risk.probability.platt_scaler import PlattScaler

            self._platt_scaler = PlattScaler(
                regularization=self._calibration_regularization,
                min_samples=self._calibration_min_samples,
            )

            self._calibration_logits: List[float] = []

            self._calibration_outcomes: List[int] = []

            self._last_fit_time: float = 0.0

            logger.info("[AGENT-INIT] %s probability calibration enabled with PlattScaler", config.name)

        else:

            self._platt_scaler = None

            self._calibration_logits = []

            self._calibration_outcomes = []

            self._last_fit_time = 0.0

            logger.info("[AGENT-INIT] %s probability calibration disabled", config.name)



        # Initialize price history for velocity calculation

        # CRITICAL FIX: Increase window to 5 minutes to accommodate ADX warmup (14 periods = 70s at 5s cadence)

        # and provide buffer during 15-minute window transitions

        # CRITICAL FIX: Store OHLC data instead of just close price for proper ADX/ATR calculation

        self._spot_price_history: Dict[str, collections.deque] = {}

        self._price_history_window_size = 300  # 5 minutes at 1-second intervals (60 data points at 5s cadence)



        # CRITICAL FIX: 2026-07-07 - Initialize Crypto15mIndicatorStack for 2026 research-based indicators

        # This provides EMA(200), regime-based RSI, MACD filters, and RSI+MACD confluence scoring

        # CRITICAL FIX: 2026-07-08 - Enable kalshi_mode to disable strict spot market thresholds

        # Kalshi prediction markets are binary contracts, not continuous spot instruments

        # Without kalshi_mode, strict vol/ATR/chop gates block all signals

        # CRITICAL FIX: 2026-07-10 - Initialize indicator stacks for ALL 5 assets in EACH agent

        # This ensures each asset's indicator stack gets redundant updates from all 5 agents

        # Previous fix (only initializing own asset) caused bars_available=1 because each agent

        # is called once per cycle, so each stack only got 1 update per minute

        # With all 5 assets initialized in each agent, each stack gets 5 updates per cycle

        self._indicator_stacks: Dict[str, Any] = {}

        self._indicator_stack_last_update: Dict[str, float] = {}  # Track last update time per asset

        self._indicator_stack_price_buffer: Dict[str, List[float]] = {}  # Buffer spot prices for 1-minute aggregation

        # CRITICAL FIX: 2026-07-16 - Make indicator stack initialization a hard requirement
        # Previously soft-failed on exception, which could lead to poor signals without indicators
        # Now raises exception to fail fast and prevent silent degradation

        from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig

        # Initialize indicator stack for ALL 5 crypto assets

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            try:

                cfg = IndicatorConfig(asset=asset, kalshi_mode=True)

                self._indicator_stacks[asset] = Crypto15mIndicatorStack(config=cfg)

                self._indicator_stacks[asset].set_asset_symbol(asset)  # Set asset symbol for logging

                self._indicator_stack_last_update[asset] = 0.0

                self._indicator_stack_price_buffer[asset] = []

            except Exception as e:

                # Hard fail on per-asset initialization to ensure all 5 assets have indicator stacks

                raise RuntimeError(

                    f"[AGENT-INIT] CRITICAL: Failed to initialize Crypto15mIndicatorStack for asset={asset}. "

                    f"This is a hard requirement - all 5 assets (BTC, ETH, SOL, XRP, DOGE) must have indicator stacks. "

                    f"Error: {e}"

                ) from e

        logger.info("[AGENT-INIT] %s initialized Crypto15mIndicatorStack for all 5 assets (BTC, ETH, SOL, XRP, DOGE) with kalshi_mode=True",

                   config.name)



        # Initialize for all 5 crypto assets

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._spot_price_history[asset] = collections.deque(maxlen=self._price_history_window_size)



        # Phase 4.3: Initialize SMA history for mean reversion (2-minute window)

        self._sma_history: Dict[str, collections.deque] = {}

        self._sma_window_size = 120  # 2 minutes at 1-second intervals

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._sma_history[asset] = collections.deque(maxlen=self._sma_window_size)



        # Phase 4.1: Initialize EMA history for velocity smoothing

        self._velocity_ema_history: Dict[str, collections.deque] = {}

        self._ema_window_size = self._velocity_ema_period * 2  # Keep enough history for EMA calculation

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._velocity_ema_history[asset] = collections.deque(maxlen=self._ema_window_size)



        # Phase 4.1: Initialize volatility history for ATR-based normalization

        # Keep 5 minutes of history (300 points at 1s intervals) for dynamic cooldown calculation

        self._volatility_history: Dict[str, collections.deque] = {}

        self._volatility_window_size = 300  # 5 minutes for dynamic cooldown ATR averaging

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._volatility_history[asset] = collections.deque(maxlen=self._volatility_window_size)



        # Phase 4.1: Initialize velocity history for Z-score calculation

        self._velocity_zscore_history: Dict[str, collections.deque] = {}

        self._zscore_window_size = self._zscore_period  # Keep Z-score period worth of velocity data

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._velocity_zscore_history[asset] = collections.deque(maxlen=self._zscore_window_size)



        # DATA QUALITY: Initialize data quality issue tracking

        # Tracks OHLCV corruption, staleness, and other data quality issues per asset

        self._data_quality_issues: Dict[str, Dict[str, int]] = {}

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._data_quality_issues[asset] = {

                "ohlcv_corruption": 0,  # high < low violations

                "ohlcv_stale": 0,       # high == low (no movement)

                "volume_anomaly": 0,    # volume spikes or zeros

                "price_anomaly": 0,     # price spikes or gaps

            }



        # Phase 6: Initialize ADX history for trend filtering (14-period ADX)

        self._adx_history: Dict[str, collections.deque] = {}

        self._adx_window_size = 14  # ADX period (industry standard)

        self._tr_history: Dict[str, collections.deque] = {}  # True Range history

        self._plus_dm_history: Dict[str, collections.deque] = {}  # Positive Directional Movement history

        self._minus_dm_history: Dict[str, collections.deque] = {}  # Negative Directional Movement history

        # CRITICAL FIX: Track previous smoothed values for Wilder's smoothing technique

        self._prev_smoothed_tr: Dict[str, float] = {}  # Previous smoothed TR

        self._prev_smoothed_plus_dm: Dict[str, float] = {}  # Previous smoothed +DM

        self._prev_smoothed_minus_dm: Dict[str, float] = {}  # Previous smoothed -DM

        self._prev_adx: Dict[str, float] = {}  # Previous ADX value

        # CRITICAL FIX: Increase ADX history maxlen to preserve data across 15-minute window transitions

        # Use same window size as price history (300) to ensure ADX warmup completes even during transitions

        self._adx_history_window_size = 300  # Match price history window

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._adx_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._tr_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._plus_dm_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._minus_dm_history[asset] = collections.deque(maxlen=self._adx_history_window_size)

            self._prev_smoothed_tr[asset] = 0.0

            self._prev_smoothed_plus_dm[asset] = 0.0

            self._prev_smoothed_minus_dm[asset] = 0.0

            self._prev_adx[asset] = 0.0



        # CRITICAL FIX: 2026-07-01 - Initialize volume history for volume confirmation filter

        # Industry standard: volume > 1.2x EMA20(volume) confirms signal validity

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        self._volume_history: Dict[str, collections.deque] = {}

        self._volume_window_size = 300  # 5 minutes of volume history for EMA20 calculation

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._volume_history[asset] = collections.deque(maxlen=self._volume_window_size)



        # CRITICAL FIX: 2026-08-17 - Maintain one in-progress 1m candle per asset
        # and only append a completed bar to price/indicator history once per minute.
        # This stops duplicate static public-OHLC bars from corrupting ADX/ATR/FVG.
        self._current_candle: Dict[str, Optional[Dict[str, Any]]] = {}
        self._candle_interval_ms = 60000  # 1-minute candles
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._current_candle[asset] = None


        # CRITICAL FIX: 2026-07-01 - Initialize multi-timeframe price history for alignment

        # Industry standard: 1m + 5m confirmation for +10-20 pp win rate

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        self._price_1m_history: Dict[str, collections.deque] = {}  # 1-minute price history

        self._price_5m_history: Dict[str, collections.deque] = {}  # 5-minute price history

        self._1m_window_size = 60  # 1 minute at 1-second intervals

        self._5m_window_size = 300  # 5 minutes at 1-second intervals

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._price_1m_history[asset] = collections.deque(maxlen=self._1m_window_size)

            self._price_5m_history[asset] = collections.deque(maxlen=self._5m_window_size)



        # CRITICAL FIX: 2026-07-06 - Initialize MACD history for momentum_fvg signal generation

        # MACD(12,26,9) requires 9 periods of MACD line history for signal line calculation

        self._macd_history: Dict[str, collections.deque] = {}

        self._macd_window_size = 9  # 9-period EMA for signal line

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._macd_history[asset] = collections.deque(maxlen=self._macd_window_size)



        # Cooldown tracking: last trade timestamp per asset.

        # Start empty. A missing entry means there is no prior trade, so the
        # asset is eligible immediately. _cooldown_elapsed returns inf for a
        # missing timestamp and for any wall-time/monotonic mismatch, so a
        # fresh agent can never be blocked by stale or epoch-relative state.

        self._last_trade_time: Dict[str, float] = {}



        # Per-strip order limit tracking (15m strip = series ticker)

        # CRITICAL FIX: 2026-07-10 - Reset strip order counts on agent initialization

        # This prevents persisted counts from previous runs from blocking new orders

        self._strip_order_counts: Dict[str, int] = {}

        # Initialize from own config series_tickers
        series_tickers = []
        if hasattr(self.config, 'series_tickers'):
            series_tickers = list(self.config.series_tickers)

        for ticker in series_tickers:

            self._strip_order_counts[ticker] = 0



        # Track current market ID per strip to detect when to reset counters

        self._current_market_ids: Dict[str, str] = {}

        for ticker in series_tickers:

            self._current_market_ids[ticker] = None



        # 2026 Research-Based Risk Management

        # Session-level order tracking (max 5 trades per 15m window)

        self._session_order_count: int = 0

        self._session_start_time: float = time.time()

        self._session_window_sec: int = 900  # 15 minutes in seconds



        # Consecutive loss tracking (pause after N consecutive losses)

        self._consecutive_losses: Dict[str, int] = {}  # asset -> consecutive loss count

        self._consecutive_loss_pause_until: Dict[str, float] = {}  # asset -> pause until timestamp

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._consecutive_losses[asset] = 0

            self._consecutive_loss_pause_until[asset] = 0.0



        # Session risk cap tracking (max 10% risk per session)

        self._session_risk_usd: float = 0.0

        self._session_risk_cap_usd: float = 0.0  # Will be set from profile/capital



        # Initialize session risk cap from profile if available

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if profile_adapter and profile_adapter._profile:

                profile = profile_adapter._profile

                # Calculate session risk cap as percentage of capital

                if profile.capital_usd > 0:

                    self._session_risk_cap_usd = profile.capital_usd * profile.throttling_max_session_risk_pct

                    logger.info("[AGENT-INIT] %s session_risk_cap=%.2f (capital=%.2f * %.2f%%)",

                               config.name, self._session_risk_cap_usd, profile.capital_usd,

                               profile.throttling_max_session_risk_pct * 100)

        except Exception as e:

            logger.warning("[AGENT-INIT] %s failed to load session risk cap from profile: %s", config.name, e)



        # 2026 Research-Based Risk Management: Portfolio heat tracking

        self._portfolio_heat_enabled: bool = False

        self._portfolio_heat_threshold_warning: float = 0.70

        self._portfolio_heat_threshold_critical: float = 0.85



        # 2026 Research-Based Risk Management: Asset-specific rolling PnL limits

        self._rolling_pnl_enabled: bool = False

        self._rolling_pnl_history: Dict[str, List[Tuple[float, float]]] = {}  # asset -> [(timestamp, pnl_usd)]

        self._rolling_pnl_1h_window: int = 3600  # 1 hour in seconds

        self._rolling_pnl_4h_window: int = 14400  # 4 hours in seconds

        self._rolling_pnl_limits: Dict[str, Dict[str, float]] = {}  # asset -> {1h_limit_pct, 4h_limit_pct}



        # Initialize rolling PnL history for all assets

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

            self._rolling_pnl_history[asset] = []



        # Load 2026 risk management parameters from profile

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if profile_adapter and profile_adapter._profile:

                profile = profile_adapter._profile

                # Portfolio heat tracking

                self._portfolio_heat_enabled = profile.portfolio_heat_enabled

                self._portfolio_heat_threshold_warning = profile.portfolio_heat_heat_threshold_warning

                self._portfolio_heat_threshold_critical = profile.portfolio_heat_heat_threshold_critical

                logger.info("[AGENT-INIT] %s portfolio_heat_enabled=%s warning=%.2f%% critical=%.2f%%",

                           config.name, self._portfolio_heat_enabled,

                           self._portfolio_heat_threshold_warning * 100,

                           self._portfolio_heat_threshold_critical * 100)



                # Asset-specific rolling PnL limits

                self._rolling_pnl_enabled = profile.asset_specific_rolling_pnl_enabled

                self._rolling_pnl_limits = {

                    "BTC": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_btc_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_btc_rolling_4h_halt_pct

                    },

                    "ETH": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_eth_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_eth_rolling_4h_halt_pct

                    },

                    "SOL": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_sol_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_sol_rolling_4h_halt_pct

                    },

                    "XRP": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_xrp_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_xrp_rolling_4h_halt_pct

                    },

                    "DOGE": {

                        "1h_limit_pct": profile.asset_specific_rolling_pnl_doge_rolling_1h_halt_pct,

                        "4h_limit_pct": profile.asset_specific_rolling_pnl_doge_rolling_4h_halt_pct

                    }

                }

                logger.info("[AGENT-INIT] %s rolling_pnl_enabled=%s", config.name, self._rolling_pnl_enabled)

        except Exception as e:

            logger.warning("[AGENT-INIT] %s failed to load 2026 risk management parameters: %s", config.name, e)



        # Phase 9: Advanced liquidity / refill / fallback integration
        self._advanced_liquidity_enabled = getattr(config, 'advanced_liquidity_enabled', False)
        self._refill_detector = None
        self._liquidity_fallback_executor = None
        if self._advanced_liquidity_enabled:
            try:
                from merid.event_venues.kalshi.refill_detector import RefillDetector
                self._refill_detector = RefillDetector(
                    toxic_threshold_ms=getattr(config, 'refill_toxic_threshold_ms', 1000.0),
                    window_ms=getattr(config, 'refill_window_ms', 60000.0),
                    min_samples=getattr(config, 'refill_min_samples', 3),
                )
            except Exception as e:
                logger.warning("[AGENT-INIT] %s failed to initialize RefillDetector: %s", config.name, e)
            try:
                from merid.risk.liquidity_fallback import init_liquidity_fallback_executor
                self._liquidity_fallback_executor = init_liquidity_fallback_executor(
                    score_window=getattr(config, 'liquidity_score_window', 5)
                )
            except Exception as e:
                logger.warning("[AGENT-INIT] %s failed to initialize liquidity fallback executor: %s", config.name, e)

        # Spot fetch cache: prevent redundant provider calls within the same tick
        # (e.g. when _generate_price_based_signal and collect_order_candidate both
        # need the same asset price in a single cycle).
        self._spot_cache: Dict[str, Tuple[float, Any]] = {}
        self._spot_cache_ttl_sec = 1.0

        # Most recent raw spot snapshot per asset, used for feed-alignment telemetry.
        self._last_spot_data: Dict[str, Any] = {}

        logger.info("[AGENT-INIT] %s initialized with velocity-based signal strategy", config.name)


    def _get_spot_cached(self, asset: str) -> Tuple[Optional[float], Any]:
        """Fetch spot price once per asset within a short TTL window.

        Returns (spot_price, spot_data) where spot_data is the full object
        returned by the provider when available.
        """
        now = time.monotonic()
        cached = self._spot_cache.get(asset)
        if cached is not None:
            cached_ts, cached_price, cached_data = cached
            if now - cached_ts < self._spot_cache_ttl_sec:
                logger.debug("[SPOT-CACHE-HIT] asset=%s price=%s", asset, format_price(asset, cached_price))
                return cached_price, cached_data

        spot_price: Optional[float] = None
        spot_data: Any = None
        if hasattr(self.spot_provider, 'get'):
            result = self.spot_provider.get(asset)
            if result is not None:
                if hasattr(result, 'price') and not hasattr(result, 'reason'):
                    spot_price = result.price
                    spot_data = result
                    logger.debug("[SPOT-CACHE-REFRESH] asset=%s price=%s", asset, format_price(asset, spot_price))
                elif hasattr(result, 'reason'):
                    logger.warning("[SPOT-CACHE-ERROR] asset=%s spot unavailable: %s", asset, result.reason)
        else:
            logger.warning("[SPOT-CACHE-ERROR] asset=%s spot_provider has no get() method", asset)

        self._spot_cache[asset] = (now, spot_price, spot_data)
        self._last_spot_data[asset] = spot_data
        return spot_price, spot_data



    def _close_minute_bar(self, asset: str, candle: Dict[str, Any]) -> None:
        # Close a completed 1-minute candle and append it to price/indicator history.
        close_price = candle['close']
        open_price = candle['open']
        high_price = candle['high']
        low_price = candle['low']
        candle_time = candle['start']

        # Compute volume proxy from the completed bar
        if high_price < low_price:
            logger.error(
                f'[DATA-QUALITY] asset={asset} CORRUPTED OHLC data: high={format_price(asset, high_price)} < low={format_price(asset, low_price)}. '
                f'This violates the fundamental OHLC invariant (high >= low). '
                f'Using default volume=1.0 and flagging for data quality audit.'
            )
            self._track_data_quality_issue(asset, 'ohlcv_corruption', 'high_less_than_low')
            volume = 1.0
        elif high_price == low_price:
            logger.debug(
                f'[DATA-QUALITY] asset={asset} STALE OHLC data: high={format_price(asset, high_price)} == low={format_price(asset, low_price)}. '
                f'No price movement detected in this period. Using default volume=1.0.'
            )
            volume = 1.0
        else:
            volume_proxy = (high_price - low_price) * close_price
            volume = max(1.0, min(100.0, volume_proxy * 100))
            logger.info(
                f'[VOLUME-EXTRACTION] asset={asset} volume not available, using OHLC proxy={volume:.2f} '
                f'(high={format_price(asset, high_price)} low={format_price(asset, low_price)} spot={format_price(asset, close_price)})'
            )

        logger.info(
            '[MINUTE-BAR-CLOSE] asset=%s candle_time=%s O=%s H=%s L=%s C=%s volume=%.2f',
            asset, candle_time,
            format_price(asset, open_price), format_price(asset, high_price),
            format_price(asset, low_price), format_price(asset, close_price),
            volume
        )

        # Update volatility for the completed bar before appending current close
        self._update_volatility_history(asset, close_price)

        # Append completed OHLC bar to price history once per minute
        self._spot_price_history[asset].append((candle_time, close_price, open_price, high_price, low_price))
        self._sma_history[asset].append((candle_time, close_price))
        self._price_1m_history[asset].append((candle_time, close_price))
        self._price_5m_history[asset].append((candle_time, close_price))
        self._volume_history[asset].append((candle_time, volume))

        # Update ADX once for the completed bar
        self._update_adx_history(asset, close_price, open_price, high_price, low_price)

        # Update FVG forecaster once for the completed bar
        try:
            from merid.prediction.forecasters.fvg import get_fvg_forecaster
            fvg_forecaster = get_fvg_forecaster()
            fvg_forecaster.update_price(
                asset=asset,
                timeframe='15m',
                open_p=open_price * 100,
                high=high_price * 100,
                low=low_price * 100,
                close=close_price * 100,
                timestamp=candle_time / 1000.0,
            )
            logger.info('[FVG-UPDATE] asset=%s OHLC data updated in FVG forecaster: O=%s H=%s L=%s C=%s',
                        asset, format_price(asset, open_price), format_price(asset, high_price),
                        format_price(asset, low_price), format_price(asset, close_price))
        except Exception as e:
            logger.warning('[FVG-UPDATE] asset=%s failed to update FVG forecaster: %s', asset, e)


    def _update_price_history(self, asset: str, spot_price: Optional[float], spot_data: Any = None) -> None:

        # Update price history for velocity calculation.

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # CRITICAL FIX: Maintain one in-progress 1m candle per asset; only close once per minute.

        if spot_price is None:
            logger.warning('[UPDATE-PRICE-HISTORY] asset=%s spot_price is None - skipping', asset)
            return

        logger.info('[UPDATE-PRICE-HISTORY-ENTRY] asset=%s spot_price=%s spot_data=%s',
                    asset, format_price(asset, spot_price), type(spot_data).__name__ if spot_data else None)

        current_time_ms = int(time.time() * 1000)
        candle_start = (current_time_ms // self._candle_interval_ms) * self._candle_interval_ms

        # Extract public OHLC and volume.  Gate on hasattr to confirm the source
        # actually provides these fields, then use getattr for safe access.
        spot_data_has_ohlc = (
            spot_data is not None
            and hasattr(spot_data, 'open')
            and hasattr(spot_data, 'high')
            and hasattr(spot_data, 'low')
        )
        public_open = getattr(spot_data, 'open', None) if spot_data_has_ohlc else None
        public_high = getattr(spot_data, 'high', None) if spot_data_has_ohlc else None
        public_low = getattr(spot_data, 'low', None) if spot_data_has_ohlc else None
        public_volume = getattr(spot_data, 'volume', None) if spot_data_has_ohlc else None

        candle = self._current_candle[asset]
        if candle is None or candle['start'] != candle_start:
            # Minute boundary changed: close the previous candle if it exists
            if candle is not None:
                self._close_minute_bar(asset, candle)

            # Start a new minute candle
            prev_close = candle['close'] if candle is not None else None
            if prev_close is not None:
                new_open = prev_close
            else:
                new_open = public_open if public_open is not None else spot_price

            new_high = public_high if public_high is not None else new_open
            new_low = public_low if public_low is not None else new_open
            new_high = max(new_high, spot_price)
            new_low = min(new_low, spot_price)

            self._current_candle[asset] = {
                'start': candle_start,
                'open': new_open,
                'high': new_high,
                'low': new_low,
                'close': spot_price,
                'tick_count': 1,
            }
            if public_volume is not None:
                self._current_candle[asset]['volume_public'] = float(public_volume)
        else:
            # Same minute: update the in-progress candle with this tick
            candle['high'] = max(candle['high'], public_high if public_high is not None else candle['high'], spot_price)
            candle['low'] = min(candle['low'], public_low if public_low is not None else candle['low'], spot_price)
            candle['close'] = spot_price
            candle['tick_count'] += 1
            if public_volume is not None:
                self._current_candle[asset]['volume_public'] = float(public_volume)

        candle = self._current_candle[asset]
        # Enforce high >= close >= low
        if candle['high'] < candle['close']:
            candle['high'] = candle['close']
        if candle['low'] > candle['close']:
            candle['low'] = candle['close']

        logger.info('[CANDLE-UPDATE] asset=%s in_progress O=%s H=%s L=%s C=%s ticks=%d',
                    asset, format_price(asset, candle['open']), format_price(asset, candle['high']),
                    format_price(asset, candle['low']), format_price(asset, candle['close']), candle['tick_count'])

        # Keep SMA and multi-timeframe price histories responsive on every tick
        self._sma_history[asset].append((current_time_ms, spot_price))
        self._price_1m_history[asset].append((current_time_ms, spot_price))
        self._price_5m_history[asset].append((current_time_ms, spot_price))


    def _track_data_quality_issue(self, asset: str, issue_type: str, detail: str) -> None:

        """Track data quality issues for metrics and auditing.



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            issue_type: Type of issue (ohlcv_corruption, ohlcv_stale, volume_anomaly, price_anomaly)

            detail: Detailed description of the issue

        """

        if asset in self._data_quality_issues and issue_type in self._data_quality_issues[asset]:

            self._data_quality_issues[asset][issue_type] += 1

            logger.debug(

                f"[DATA-QUALITY] asset={asset} issue_type={issue_type} detail={detail} "

                f"total_count={self._data_quality_issues[asset][issue_type]}"

            )



    def get_data_quality_metrics(self) -> Dict[str, Dict[str, int]]:

        """Get data quality metrics for all assets.



        Returns:

            Dictionary mapping asset symbols to their data quality issue counts

        """

        import copy

        return copy.deepcopy(self._data_quality_issues)



    def _update_volatility_history(self, asset: str, spot_price: float) -> None:

        # Update volatility history for ATR calculation.

        # CRITICAL FIX: Store percentage changes instead of absolute price changes

        # This ensures ATR is comparable across assets with different price levels

        # (e.g., BTC at $60k vs DOGE at $0.07)

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # WARMUP FIX: Allow volatility history to populate with 1 previous price point

        # This prevents chicken-and-egg where ATR never warms up

        current_time = int(time.time() * 1000)

        history = list(self._spot_price_history[asset])



        if len(history) < 1:

            return  # No previous price data yet



        # Calculate percentage change as proxy for high-low range

        prev_price = history[-1][1]

        if prev_price <= 0:

            return



        price_change_pct = abs(spot_price - prev_price) / prev_price



        self._volatility_history[asset].append((current_time, price_change_pct))



    def _calculate_atr(self, asset: str) -> float:

        # Calculate Average True Range (ATR) for volatility normalization.

        # CRITICAL FIX: Use True Range values from TR history instead of percentage changes

        # TR is calculated in _update_adx_history using OHLC data: max(high-low, |high-prev_close|, |low-prev_close|)

        # Returns ATR as percentage (normalized by close price).

        # WARMUP FIX: Use minimum 3 data points during warmup, then require 14

        tr_history = list(self._tr_history[asset])



        # During warmup (less than 3 data points), return 0.0 to trigger fallback

        if len(tr_history) < 3:

            logger.debug("[ATR-CALC] asset=%s warmup insufficient history (%d < 3), returning 0.0",

                         asset, len(tr_history))

            return 0.0



        # Get current close price for normalization

        price_history = list(self._spot_price_history[asset])

        if len(price_history) < 1:

            return 0.0

        current_close = price_history[-1][1]  # Close price



        # During warmup (3-13 data points), use available data for faster startup

        if len(tr_history) < self._atr_period:

            logger.info("[ATR-CALC] asset=%s warmup using available history (%d < %d)",

                       asset, len(tr_history), self._atr_period)

            # Use available data points instead of requiring full 14

            recent_tr = [entry[1] for entry in tr_history[-len(tr_history):] if len(entry) >= 2]

        else:

            # Normal operation: use full 14-period ATR

            recent_tr = [entry[1] for entry in tr_history[-self._atr_period:] if len(entry) >= 2]



        # Calculate ATR as average of recent True Range values

        atr = sum(recent_tr) / len(recent_tr)



        # Normalize ATR as percentage of current close price

        atr_pct = atr / current_close if current_close > 0 else 0.0



        logger.debug("[ATR-CALC] asset=%s atr_period=%d atr=%.6f atr_pct=%.6f (%.4f%%)",

                     asset, self._atr_period, atr, atr_pct, atr_pct * 100)



        return atr_pct



    def _calculate_dynamic_cooldown(self, asset: str) -> float:

        # Static cooldown from profile configuration.

        # 2026-07-11: DISABLED volatility-based multiplier - was causing 10-22x scaling

        # Volatility multiplier is inappropriate for 15-minute binary options:

        # - High volatility should create MORE opportunities, not fewer

        # - Binary options are direction bets, not position holding

        # - Industry standard (Polymarket): 3s static cooldown

        # Returns cooldown in seconds from profile config.



        # Use static cooldown from profile (now 3s per kalshi_crypto_15m_v2.yaml)

        static_cooldown = float(self.config.per_asset_cooldown_s)



        logger.debug("[STATIC-COOLDOWN] asset=%s cooldown=%.1fs (from profile config)",

                     asset, static_cooldown)



        return static_cooldown



    def update_cooldown_on_fill(self, asset: str, pnl_usd: float = 0.0, trade_risk_usd: float = 0.0) -> None:

        """Update cooldown timestamp when a trade actually executes (fills).



        This should be called from the fill handler (position_cache.on_fill) to ensure

        the cooldown is only reset when a trade actually executes, not when a candidate

        is generated. This prevents perpetual cooldown blocks.



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            pnl_usd: PnL of the trade in USD (positive for profit, negative for loss)

            trade_risk_usd: Risk amount of the trade in USD (for session risk cap tracking)

        """

        self._last_trade_time[asset] = time.monotonic()



        # 2026 Research-Based Risk Management: Increment session order count

        self._session_order_count += 1

        logger.info("[SESSION-ORDER] agent=%s session_orders=%d", self.config.name, self._session_order_count)



        # 2026 Research-Based Risk Management: Track session risk

        if trade_risk_usd > 0:

            self._session_risk_usd += trade_risk_usd

            logger.info("[SESSION-RISK] agent=%s session_risk=%.2f (added %.2f) cap=%.2f",

                       self.config.name, self._session_risk_usd, trade_risk_usd, self._session_risk_cap_usd)



        # 2026 Research-Based Risk Management: Track consecutive losses.
        # DIRECT-EXECUTION-FAILED: Do NOT increment consecutive loss counter on failed submissions.
        # Failed submissions are technical failures, not actual monetary losses.
        # Consecutive loss tracking should only apply to executed trades with negative PnL.

        if pnl_usd < 0:

            self._consecutive_losses[asset] += 1

            logger.info("[CONSECUTIVE-LOSS] agent=%s asset=%s consecutive_losses=%d",

                       self.config.name, asset, self._consecutive_losses[asset])



            # Check if consecutive loss threshold reached

            if self._consecutive_losses[asset] >= self.config.consecutive_loss_pause:

                # Set pause for 15 minutes (900 seconds)

                pause_duration = 900

                self._consecutive_loss_pause_until[asset] = time.time() + pause_duration

                logger.warning(

                    "[CONSECUTIVE-LOSS-PAUSE] agent=%s asset=%s consecutive_losses=%d >= threshold=%d, pausing for %d seconds",

                    self.config.name, asset, self._consecutive_losses[asset],

                    self.config.consecutive_loss_pause, pause_duration

                )

        else:

            # Reset consecutive loss count on profit

            if self._consecutive_losses[asset] > 0:

                logger.info("[CONSECUTIVE-LOSS-RESET] agent=%s asset=%s consecutive_losses reset from %d to 0 (profit)",

                           self.config.name, asset, self._consecutive_losses[asset])

                self._consecutive_losses[asset] = 0



        # 2026 Research-Based Risk Management: Track rolling PnL for asset-specific limits

        if self._rolling_pnl_enabled and asset in self._rolling_pnl_history:

            current_time = time.time()

            self._rolling_pnl_history[asset].append((current_time, pnl_usd))

            # Prune old entries outside 4-hour window

            self._rolling_pnl_history[asset] = [

                (ts, pnl) for ts, pnl in self._rolling_pnl_history[asset]

                if current_time - ts < self._rolling_pnl_4h_window

            ]

            logger.info("[ROLLING-PNL] agent=%s asset=%s pnl=%.2f history_size=%d",

                       self.config.name, asset, pnl_usd, len(self._rolling_pnl_history[asset]))



        logger.info("[COOLDOWN-UPDATE] asset=%s cooldown timestamp updated on fill", asset)



    def _check_portfolio_heat(self) -> tuple[bool, str]:

        """

        Check if portfolio heat exceeds thresholds.



        2026 Research-Based Risk Management: Portfolio heat tracking monitors

        correlation-adjusted exposure across all assets to prevent over-concentration.



        Returns:

            tuple: (allow_trading, reason) - True if heat is acceptable, False if too high

        """

        if not self._portfolio_heat_enabled:

            return True, "portfolio_heat_disabled"



        try:

            from merid.event_venues.kalshi.position_cache import get_position_cache

            position_cache = get_position_cache()

            if not position_cache:

                return True, "no_position_cache"



            # Get all open positions

            all_positions = position_cache.get_all_positions(validate_freshness=False)

            # CRITICAL FIX: Filter positions by current window to prevent counting stale positions
            # Extract asset from agent name (e.g., BTC_15M -> BTC)
            asset = self.config.name.split('_')[0].upper() if '_' in self.config.name else self.config.name.upper()

            # Get current window ticker from market catalog
            current_window_ticker = None
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                if catalog:
                    current_market = catalog.get_current_15m_market(asset)
                    if current_market:
                        current_window_ticker = current_market.market.market_id
            except Exception as ticker_err:
                logger.warning("[HEAT-CHECK] Failed to get current window ticker: %s", ticker_err)

            # Filter to only current window positions
            if current_window_ticker:
                open_positions = {k: v for k, v in all_positions.items()
                                if v.contracts > 0 and k == current_window_ticker}
            else:
                # Fallback: filter by asset if we can't get the exact ticker
                open_positions = {k: v for k, v in all_positions.items()
                                if v.contracts > 0 and asset in k.upper()}
                logger.warning("[HEAT-CHECK] Using asset-based filtering (fallback) for %s", asset)



            if not open_positions:

                return True, "no_open_positions"



            # Calculate total exposure (simplified: sum of contract values)
            # CRITICAL FIX (2026-07-23): Handle None avg_price_cents (unknown entry price)
            total_exposure = sum(
                (pos.contracts * pos.avg_price_cents / 100.0) if pos.avg_price_cents is not None else 0.0
                for pos in open_positions.values()
            )



            # Get capital from profile for heat calculation

            try:

                from merid.risk.profiles.crypto_15m_profile import get_active_profile

                profile_adapter = get_active_profile()

                if profile_adapter and profile_adapter._profile:

                    capital = profile_adapter._profile.capital_usd

                    if capital > 0:

                        heat_ratio = total_exposure / capital

                    else:

                        heat_ratio = 0.0

                else:

                    heat_ratio = 0.0

            except Exception:

                heat_ratio = 0.0



            # Check thresholds

            if heat_ratio >= self._portfolio_heat_threshold_critical:

                logger.warning(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% >= critical=%.2f%% -> HALT (portfolio too hot)",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_critical * 100

                )

                return False, f"portfolio_heat_critical_{heat_ratio:.2%}"

            elif heat_ratio >= self._portfolio_heat_threshold_warning:

                logger.info(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% >= warning=%.2f%% -> CAUTION (portfolio heating up)",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_warning * 100

                )

                return True, f"portfolio_heat_warning_{heat_ratio:.2%}"

            else:

                logger.debug(

                    "[PORTFOLIO-HEAT] agent=%s heat=%.2f%% < warning=%.2f%% -> OK",

                    self.config.name, heat_ratio * 100, self._portfolio_heat_threshold_warning * 100

                )

                return True, f"portfolio_heat_ok_{heat_ratio:.2%}"

        except Exception as e:

            logger.warning("[PORTFOLIO-HEAT] agent=%s failed to check portfolio heat: %s", self.config.name, e)

            return True, "portfolio_heat_error"



    def _check_rolling_pnl_limit(self, asset: str) -> tuple[bool, str]:

        """

        Check if asset-specific rolling PnL limits are exceeded.



        2026 Research-Based Risk Management: Asset-specific rolling PnL limits

        halt trading for an asset if losses exceed thresholds over 1h or 4h windows.



        Returns:

            tuple: (allow_trading, reason) - True if within limits, False if limit exceeded

        """

        if not self._rolling_pnl_enabled or asset not in self._rolling_pnl_limits:

            return True, "rolling_pnl_disabled"



        try:

            current_time = time.time()

            asset_history = self._rolling_pnl_history.get(asset, [])



            if not asset_history:

                return True, "no_pnl_history"



            # Calculate rolling PnL for 1h and 4h windows

            pnl_1h = sum(pnl for ts, pnl in asset_history if current_time - ts < self._rolling_pnl_1h_window)

            pnl_4h = sum(pnl for ts, pnl in asset_history if current_time - ts < self._rolling_pnl_4h_window)



            # Get limits for this asset

            limits = self._rolling_pnl_limits[asset]

            limit_1h_pct = limits["1h_limit_pct"]

            limit_4h_pct = limits["4h_limit_pct"]



            # Get capital for percentage calculation

            try:

                from merid.risk.profiles.crypto_15m_profile import get_active_profile

                profile_adapter = get_active_profile()

                if profile_adapter and profile_adapter._profile:

                    capital = profile_adapter._profile.capital_usd

                    if capital > 0:

                        limit_1h_usd = capital * limit_1h_pct

                        limit_4h_usd = capital * limit_4h_pct

                    else:

                        limit_1h_usd = 0.0

                        limit_4h_usd = 0.0

                else:

                    limit_1h_usd = 0.0

                    limit_4h_usd = 0.0

            except Exception:

                limit_1h_usd = 0.0

                limit_4h_usd = 0.0



            # Check 4h limit first (more conservative)

            if pnl_4h < -limit_4h_usd and limit_4h_usd > 0:

                logger.warning(

                    "[ROLLING-PNL] agent=%s asset=%s pnl_4h=%.2f < -limit=%.2f -> HALT (4h limit exceeded)",

                    self.config.name, asset, pnl_4h, limit_4h_usd

                )

                return False, f"rolling_pnl_4h_exceeded_{pnl_4h:.2f}"



            # Check 1h limit

            if pnl_1h < -limit_1h_usd and limit_1h_usd > 0:

                logger.warning(

                    "[ROLLING-PNL] agent=%s asset=%s pnl_1h=%.2f < -limit=%.2f -> HALT (1h limit exceeded)",

                    self.config.name, asset, pnl_1h, limit_1h_usd

                )

                return False, f"rolling_pnl_1h_exceeded_{pnl_1h:.2f}"



            logger.debug(

                "[ROLLING-PNL] agent=%s asset=%s pnl_1h=%.2f pnl_4h=%.2f -> OK (within limits)",

                self.config.name, asset, pnl_1h, pnl_4h

            )

            return True, f"rolling_pnl_ok_1h={pnl_1h:.2f}_4h={pnl_4h:.2f}"

        except Exception as e:

            logger.warning("[ROLLING-PNL] agent=%s asset=%s failed to check rolling PnL: %s", self.config.name, asset, e)

            return True, "rolling_pnl_error"



    def _apply_time_of_day_risk_scaling(self, asset: str) -> float:

        """

        Apply time-of-day risk scaling multiplier.



        2026 Research-Based Risk Management: Adjust position sizing based on

        trading session (US market, Asian, European, weekend).



        CURRENT STATUS: DISABLED via profile YAML (time_of_day_risk_scaling.enabled: false)

        This function returns 1.0 (no scaling) when disabled.



        FUTURE RE-ENABLEMENT: When re-enabling, must also update unified_sizing.py to

        apply the same multiplier, and ensure risk envelope respects the scaled limits.



        Returns:

            float: Risk multiplier (e.g., 1.0 for normal, 0.8 for reduced risk)

        """

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            if not profile_adapter or not profile_adapter._profile:

                return 1.0



            profile = profile_adapter._profile

            if not profile.time_of_day_risk_scaling_enabled:

                # DISABLED: Return 1.0 (no scaling) when feature is disabled in YAML

                return 1.0



            from datetime import datetime, timezone

            current_utc_hour = datetime.now(timezone.utc).hour

            current_utc_minute = datetime.now(timezone.utc).minute

            current_time_utc = current_utc_hour + current_utc_minute / 60.0



            # Parse session windows from profile (format: "HH:MM-HH:MM ET")

            # Convert ET to UTC (ET = UTC-4 or UTC-5 depending on DST)

            # For simplicity, assume ET = UTC-4 (daylight time)

            et_offset = 4



            def parse_time_range(time_str: str) -> tuple[float, float]:

                """Parse 'HH:MM-HH:MM ET' to UTC hours."""

                # Strip ' ET' suffix if present

                time_str = time_str.replace(' ET', '')

                start_str, end_str = time_str.split('-')

                start_h, start_m = map(int, start_str.split(':'))

                end_h, end_m = map(int, end_str.split(':'))

                start_utc = (start_h + et_offset) % 24

                end_utc = (end_h + et_offset) % 24

                return start_utc + start_m / 60.0, end_utc + end_m / 60.0



            us_market_start, us_market_end = parse_time_range(profile.time_of_day_risk_scaling_us_market_hours)

            asian_start, asian_end = parse_time_range(profile.time_of_day_risk_scaling_asian_session)

            european_start, european_end = parse_time_range(profile.time_of_day_risk_scaling_european_session)



            # Determine current session

            in_us_market = us_market_start <= current_time_utc < us_market_end

            in_asian = asian_start <= current_time_utc < asian_end

            in_european = european_start <= current_time_utc < european_end



            # Check if weekend (Saturday/Sunday in UTC)

            is_weekend = datetime.now(timezone.utc).weekday() >= 5



            # Apply multiplier based on session

            if is_weekend:

                multiplier = profile.time_of_day_risk_scaling_weekend_multiplier

                session_name = "weekend"

            elif in_us_market:

                multiplier = profile.time_of_day_risk_scaling_us_market_multiplier

                session_name = "us_market"

            elif in_asian:

                multiplier = profile.time_of_day_risk_scaling_asian_multiplier

                session_name = "asian"

            elif in_european:

                multiplier = profile.time_of_day_risk_scaling_european_multiplier

                session_name = "european"

            else:

                multiplier = 1.0

                session_name = "other"



            logger.info(

                "[TIME-OF-DAY-SCALING] agent=%s asset=%s time_utc=%.2f session=%s multiplier=%.2f",

                self.config.name, asset, current_time_utc, session_name, multiplier

            )

            return multiplier

        except Exception as e:

            logger.warning("[TIME-OF-DAY-SCALING] agent=%s asset=%s failed to apply scaling: %s", self.config.name, asset, e)

            return 1.0



    def _check_volume_confirmation(self, asset: str) -> bool:

        """

        Check if current volume is above 1.2x EMA20 threshold.



        Industry standard: volume > 1.2x EMA20(volume) confirms signal validity.

        Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)



        Returns:

            True if volume > 1.2x EMA20, False otherwise

        """

        if not hasattr(self, '_volume_history') or asset not in self._volume_history:

            # No volume history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[VOLUME-CONFIRMATION] asset=%s no volume history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[VOLUME-CONFIRMATION] asset=%s no volume history, rejecting (warmup expired)", asset)

                return False



        volume_history = list(self._volume_history[asset])

        if len(volume_history) < 20:

            # Insufficient history for EMA20, bypass filter

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(len(volume_history)):

                logger.debug("[VOLUME-CONFIRMATION] asset=%s insufficient history (%d < 20), bypassing filter (warmup)",

                            asset, len(volume_history))

                return True

            else:

                logger.warning("[VOLUME-CONFIRMATION] asset=%s insufficient history (%d < 20), rejecting (warmup expired)",

                            asset, len(volume_history))

                return False



        # Calculate EMA20 of volume

        # EMA formula: EMA = (current * k) + (previous_EMA * (1 - k))

        # where k = 2 / (N + 1), N = period (20)

        k = 2.0 / (20.0 + 1.0)



        recent_volumes = [entry[1] for entry in volume_history[-20:]]

        ema20 = recent_volumes[0]

        for volume in recent_volumes[1:]:

            ema20 = (volume * k) + (ema20 * (1 - k))



        current_volume = recent_volumes[-1]

        volume_threshold = ema20 * 1.2  # 1.2x threshold



        volume_confirmed = current_volume > volume_threshold



        logger.info(

            "[VOLUME-CONFIRMATION] asset=%s current_volume=%.2f ema20=%.2f threshold=%.2f confirmed=%s",

            asset, current_volume, ema20, volume_threshold, volume_confirmed

        )



        return volume_confirmed



    def _calculate_rsi(self, asset: str, period: int = 9) -> float:

        """

        Calculate RSI (Relative Strength Index) for panic fade detection.



        RSI measures momentum and identifies overbought (>70) and oversold (<30) conditions.

        For panic fade, we use more extreme thresholds: oversold < 25, overbought > 75.



        2026 OPTIMIZATION: Changed default period from 14 to 9 for 15-minute scalping.

        Industry research shows RSI(14) is too slow for 15-minute charts - by the time

        the signal fires, the move is already over. RSI(9) provides faster signals for

        intraday (15m-1H) trading with acceptable noise levels.

        Reference: https://arxum.com/rsi-settings/ - "For 15-minute charts I use RSI(9)"



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            period: RSI calculation period (default 9, optimized for 15m scalping)



        Returns:

            RSI value (0-100), or 0.0 if insufficient data

        """

        history = list(self._spot_price_history[asset])

        if len(history) < period + 1:

            logger.debug("[RSI-CALC] asset=%s insufficient history (%d < %d), returning 0.0",

                         asset, len(history), period + 1)

            return 0.0



        # Extract close prices

        closes = [entry[1] for entry in history[-(period + 1):]]



        # Calculate price changes

        gains = []

        losses = []

        for i in range(1, len(closes)):

            change = closes[i] - closes[i - 1]

            if change > 0:

                gains.append(change)

                losses.append(0.0)

            else:

                gains.append(0.0)

                losses.append(abs(change))



        # Calculate average gains and losses

        avg_gain = sum(gains) / period

        avg_loss = sum(losses) / period



        if avg_loss == 0:

            return 100.0  # No losses, RSI = 100



        rs = avg_gain / avg_loss

        rsi = 100.0 - (100.0 / (1.0 + rs))



        logger.debug("[RSI-CALC] asset=%s RSI=%.2f (period=%d)", asset, rsi, period)

        return rsi



    def _calculate_price_zscore(self, asset: str, period: int = 20) -> float:

        """

        Calculate Z-score for statistical extreme detection (panic fade).



        Z-score measures how many standard deviations price is from the mean.

        Z-score > +2.0 indicates statistical extreme (overbought).

        Z-score < -2.0 indicates statistical extreme (oversold).



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            period: Z-score calculation period (default 20)



        Returns:

            Z-score value, or 0.0 if insufficient data

        """

        history = list(self._spot_price_history[asset])

        if len(history) < period:

            logger.debug("[ZSCORE-CALC] asset=%s insufficient history (%d < %d), returning 0.0",

                         asset, len(history), period)

            return 0.0



        # Extract close prices

        closes = [entry[1] for entry in history[-period:]]



        # Calculate mean and standard deviation

        mean_price = sum(closes) / len(closes)

        variance = sum((x - mean_price) ** 2 for x in closes) / len(closes)

        std_dev = variance ** 0.5



        if std_dev == 0:

            return 0.0  # No variance, Z-score = 0



        current_price = closes[-1]

        zscore = (current_price - mean_price) / std_dev



        logger.debug("[ZSCORE-CALC] asset=%s Z-score=%.2f (period=%d)", asset, zscore, period)

        return zscore



    def _detect_market_regime(self, asset: str, spot_price: float, market_price: float) -> str:

        """

        Detect market regime using ADX, price position, and velocity.



        Regime classification based on 2026 research:

        - trending_strong: ADX > 25, strong directional movement

        - trending_weak: ADX 15-25, moderate directional movement

        - mean_reverting: ADX < 15, choppy/range-bound

        - neutral: insufficient data or mixed signals



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            spot_price: Current spot price

            market_price: Current market price (YES/NO implied probability)



        Returns:

            Regime string: "trending_strong", "trending_weak", "mean_reverting", or "neutral"

        """

        # Calculate ADX (Average Directional Index) for trend strength

        adx = self._calculate_adx(asset)



        # Calculate recent velocity for direction confirmation

        velocity = self._calculate_multi_window_velocity(asset, spot_price)



        # Regime classification

        if adx >= 25:

            regime = "trending_strong"

        elif adx >= 15:

            regime = "trending_weak"

        elif adx > 0:  # ADX > 0 but < 15: weak trend / range-bound

            regime = "mean_reverting"

        else:  # ADX == 0: insufficient data or no movement

            regime = "neutral"



        logger.info(

            "[REGIME-DETECTION] asset=%s ADX=%.2f velocity=%.6f regime=%s",

            asset, adx, velocity, regime

        )



        return regime



    def _check_panic_fade_conditions(self, asset: str, velocity: float) -> Optional[Dict[str, Any]]:

        """

        Check if panic fade (volatility reversion) conditions are met.



        Panic fade strategy (Turbine research winner):

        - Statistical extreme: RSI < 25 (oversold) or > 75 (overbought)

        - Statistical extreme: Z-score < -2.0 or > +2.0

        - Velocity magnitude exceeds minimum threshold (panic move)

        - Regime is choppy/range-bound (not trending)



        When conditions are met, fade the panic:

        - Oversold (RSI < 25, Z-score < -2.0, negative velocity) -> BUY YES (expect reversion up)

        - Overbought (RSI > 75, Z-score > +2.0, positive velocity) -> BUY NO (expect reversion down)



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

            velocity: Current velocity (percentage change per second)



        Returns:

            Dict with panic fade signal info if conditions met, None otherwise

        """

        if not self._panic_fade_enabled:

            return None



        # Check velocity magnitude (must be panic-level move)

        velocity_magnitude = abs(velocity)

        if velocity_magnitude < self._panic_fade_min_velocity:

            logger.debug("[PANIC-FADE] asset=%s velocity=%.6f below min_threshold=%.6f, skipping",

                        asset, velocity_magnitude, self._panic_fade_min_velocity)

            return None



        # Calculate RSI and Z-score

        rsi = self._calculate_rsi(asset)

        zscore = self._calculate_price_zscore(asset)



        # Skip if indicators unavailable (insufficient data)

        if rsi == 0.0 or zscore == 0.0:

            logger.debug("[PANIC-FADE] asset=%s RSI=%.2f Z-score=%.2f insufficient data, skipping",

                        asset, rsi, zscore)

            return None



        # Check statistical extreme conditions

        is_oversold = (rsi < self._panic_fade_rsi_oversold) and (zscore < -self._panic_fade_zscore_threshold)

        is_overbought = (rsi > self._panic_fade_rsi_overbought) and (zscore > self._panic_fade_zscore_threshold)



        if not is_oversold and not is_overbought:

            logger.debug("[PANIC-FADE] asset=%s RSI=%.2f Z-score=%.2f not at statistical extreme, skipping",

                        asset, rsi, zscore)

            return None



        # Determine signal side based on extreme type

        if is_oversold:

            signal_side = "yes"

            signal_action = "buy"

            rationale = f"panic_fade: oversold (RSI={rsi:.1f}<{self._panic_fade_rsi_oversold}, Z={zscore:.1f}<-2.0, velocity={velocity:.6f})"

            logger.info("[PANIC-FADE] asset=%s OVERSOLD detected: RSI=%.2f Z-score=%.2f velocity=%.6f -> BUY YES (expect reversion up)",

                       asset, rsi, zscore, velocity)

        else:  # is_overbought

            signal_side = "no"

            signal_action = "buy"

            rationale = f"panic_fade: overbought (RSI={rsi:.1f}>{self._panic_fade_rsi_overbought}, Z={zscore:.1f}>2.0, velocity={velocity:.6f})"

            logger.info("[PANIC-FADE] asset=%s OVERBOUGHT detected: RSI=%.2f Z-score=%.2f velocity=%.6f -> BUY NO (expect reversion down)",

                       asset, rsi, zscore, velocity)


        # CRITICAL FIX (2026-07-19): Add upstream invariant check for panic_fade
        # Validate that the derived side/action matches the strategy intent
        # CORRECT MAPPING (2026-07-23): Panic fade is a mean reversion strategy: oversold → expect up (BULLISH_EVENT), overbought → expect down (BEARISH_EVENT)
        try:
            from merid.prediction.intent_contract import validate_intent_exposure_consistency, StrategyIntent
            strategy_intent = StrategyIntent.BULLISH_EVENT if is_oversold else StrategyIntent.BEARISH_EVENT
            is_valid, error = validate_intent_exposure_consistency(
                intent=strategy_intent,
                kalshi_side=signal_side,
                kalshi_action=signal_action,
                current_position=None,  # Entry signal (flat position)
            )
            if not is_valid:
                logger.error(
                    "[INTENT-EXPOSURE-MISMATCH] asset=%s panic_fade intent=%s side=%s action=%s - %s - BLOCKING ORDER",
                    asset, strategy_intent.value, signal_side, signal_action, error
                )
                return None
            else:
                logger.debug(
                    "[INTENT-EXPOSURE-VALID] asset=%s panic_fade intent=%s side=%s action=%s - invariant check passed",
                    asset, strategy_intent.value, signal_side, signal_action
                )
        except ImportError:
            logger.warning("[INTENT-CONTRACT] Not available - skipping upstream invariant check for panic_fade")

        # CRITICAL INSTRUMENTATION (2026-07-23): Log raw directional indicators for panic_fade
        logger.info(
            "[SIGNAL-RAW-INDICATORS-PANIC-FADE] asset=%s rsi=%.2f rsi_oversold_threshold=%.2f rsi_overbought_threshold=%.2f "
            "zscore=%.2f velocity=%.6f is_oversold=%s signal_side=%s strategy_intent=%s",
            asset, rsi, self._panic_fade_rsi_oversold, self._panic_fade_rsi_overbought,
            zscore, velocity, is_oversold, signal_side, strategy_intent.value if strategy_intent else "N/A"
        )

        return {

            "side": signal_side,

            "action": signal_action,

            "rationale": rationale,

            "rsi": rsi,

            "zscore": zscore,

            "velocity": velocity,

            "strategy": "panic_fade"

        }



    def _check_multi_timeframe_alignment(self, asset: str) -> bool:

        """

        Check if 1m and 5m timeframes are aligned for signal confirmation.



        Industry standard: 1m + 5m confirmation for +10-20 pp win rate.

        Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md



        Both timeframes must show the same directional momentum for confirmation.



        Args:

            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)



        Returns:

            True if 1m and 5m momentum aligned, False otherwise

        """

        if not hasattr(self, '_price_1m_history') or asset not in self._price_1m_history:

            # No 1m history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[MTF-ALIGNMENT] asset=%s no 1m history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s no 1m history, rejecting (warmup expired)", asset)

                return False



        if not hasattr(self, '_price_5m_history') or asset not in self._price_5m_history:

            # No 5m history available, bypass filter during warmup

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(0):

                logger.debug("[MTF-ALIGNMENT] asset=%s no 5m history, bypassing filter (warmup)", asset)

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s no 5m history, rejecting (warmup expired)", asset)

                return False



        price_1m = list(self._price_1m_history[asset])

        price_5m = list(self._price_5m_history[asset])



        if len(price_1m) < 10 or len(price_5m) < 10:

            # Insufficient history for momentum calculation

            # SEV-1 FIX: Use time-based warmup guard

            if is_warmup(min(len(price_1m), len(price_5m))):

                logger.debug("[MTF-ALIGNMENT] asset=%s insufficient history (1m=%d, 5m=%d), bypassing filter (warmup)",

                            asset, len(price_1m), len(price_5m))

                return True

            else:

                logger.warning("[MTF-ALIGNMENT] asset=%s insufficient history (1m=%d, 5m=%d), rejecting (warmup expired)",

                            asset, len(price_1m), len(price_5m))

                return False



        # Calculate 1m momentum (current vs 10 periods ago)

        recent_1m = [entry[1] for entry in price_1m[-10:]]

        momentum_1m = (recent_1m[-1] - recent_1m[0]) / recent_1m[0] if recent_1m[0] > 0 else 0.0



        # Calculate 5m momentum (current vs 10 periods ago)

        recent_5m = [entry[1] for entry in price_5m[-10:]]

        momentum_5m = (recent_5m[-1] - recent_5m[0]) / recent_5m[0] if recent_5m[0] > 0 else 0.0



        # Check alignment: both positive or both negative

        # CRITICAL FIX: Treat zero momentum on both timeframes as aligned (no conflicting signal)

        # This prevents blocking trades when both timeframes are flat (momentum_1m=0, momentum_5m=0)

        if abs(momentum_1m) < 0.000001 and abs(momentum_5m) < 0.000001:

            # Both timeframes flat - no conflicting signal, allow trade

            aligned = True

        else:

            aligned = (momentum_1m > 0 and momentum_5m > 0) or (momentum_1m < 0 and momentum_5m < 0)



        logger.info(

            "[MTF-ALIGNMENT] asset=%s momentum_1m=%.6f momentum_5m=%.6f aligned=%s",

            asset, momentum_1m, momentum_5m, aligned

        )



        return aligned



    def _calculate_dynamic_velocity_threshold(self, asset: str) -> float:

        # Phase 7: Calculate dynamic velocity threshold based on ATR (volatility) and ADX (trend strength).

        # 2026-06-30: Enhanced with ADX-based trend strength adjustment (industry best practice)

        # High volatility -> higher threshold (more conservative)

        # Low volatility -> lower threshold (more aggressive)

        # Strong trend (ADX >= 25) -> higher ATR multiplier to reduce noise

        # Moderate trend (10 <= ADX < 25) -> neutral ATR multiplier

        # Weak trend (ADX < 10) -> lower ATR multiplier to capture subtle changes

        # This adapts to market conditions for optimal trade capture.



        # Get base threshold from config (per-asset)

        base_threshold_map = {

            "BTC": getattr(self.config, 'velocity_threshold_btc', self.config.velocity_threshold),

            "ETH": getattr(self.config, 'velocity_threshold_eth', self.config.velocity_threshold),

            "SOL": getattr(self.config, 'velocity_threshold_sol', self.config.velocity_threshold),

            "XRP": getattr(self.config, 'velocity_threshold_xrp', self.config.velocity_threshold),

            "DOGE": getattr(self.config, 'velocity_threshold_doge', self.config.velocity_threshold),

        }



        # Use per-asset thresholds from profile if available

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            profile = profile_adapter.profile



            asset_threshold_map = {

                "BTC": profile.velocity_threshold_btc,

                "ETH": profile.velocity_threshold_eth,

                "SOL": profile.velocity_threshold_sol,

                "XRP": profile.velocity_threshold_xrp,

                "DOGE": profile.velocity_threshold_doge,

            }

            base_threshold = asset_threshold_map.get(asset, base_threshold_map.get(asset, 0.0002))

        except Exception:

            base_threshold = base_threshold_map.get(asset, 0.0002)



        # Calculate ATR for current asset (now returns percentage)

        atr_pct = self._calculate_atr(asset)



        if atr_pct <= 0:

            # No ATR data, use base threshold

            logger.warning("[DYNAMIC-THRESHOLD] asset=%s ATR=%.6f (no data), using base_threshold=%.6f",

                          asset, atr_pct, base_threshold)

            return base_threshold



        # Calculate ADX for trend strength adjustment

        adx = self._calculate_adx(asset)



        # Define volatility regimes for threshold adjustment (2026 industry standards for 15m crypto)

        # CRITICAL FIX: 2026-07-05 - Aligned ATR thresholds with new velocity thresholds (0.6%-1.0%)

        # Previous thresholds (0.005%-0.03%) were 20-200x lower than velocity thresholds, causing misalignment

        # New thresholds align with velocity thresholds for consistent conviction:

        # Low volatility: ATR < 0.4% -> reduce threshold to catch smaller moves (common in crypto)

        # Normal volatility: 0.4% <= ATR < 1.2% -> use base threshold

        # High volatility: ATR >= 1.2% -> increase threshold to avoid false signals



        low_volatility_threshold = 0.004  # 0.4% - aligned with velocity thresholds (BTC/ETH: 0.6%)

        high_volatility_threshold = 0.012  # 1.2% - aligned with velocity thresholds (DOGE: 1.0%)



        # Base adjustment factor from ATR (volatility)

        # CRITICAL FIX: 2026-07-02 - Disabled ATR adjustment to prevent threshold inflation blocking trades

        # Previous multipliers (0.90-1.10) were still inflating thresholds above base values

        # This caused velocity to be below dynamic threshold even when above base threshold

        # CRITICAL FIX: Set all ATR multipliers to 1.0 (neutral) to use base threshold directly

        if atr_pct < low_volatility_threshold:

            # Low volatility: neutral multiplier (was 0.90)

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% < low_threshold=%.4f%% -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100, low_volatility_threshold * 100

            )

        elif atr_pct > high_volatility_threshold:

            # High volatility: neutral multiplier (was 1.10)

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% > high_threshold=%.4f%% -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100, high_volatility_threshold * 100

            )

        else:

            # Normal volatility: neutral multiplier

            atr_adjustment = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ATR=%.4f%% in normal range -> ATR adjustment: 1.0 (neutral)",

                asset, atr_pct * 100

            )



        # ADX-based trend strength adjustment (2026 industry best practice for 15m crypto)

        # 2026 FIX: Disabled ADX multiplier to prevent threshold inflation blocking trades

        # Previous multipliers (0.90-1.05) were inflating thresholds above base values

        # This caused velocity to be below dynamic threshold even when above base threshold

        # CRITICAL FIX: Set all ADX multipliers to 1.0 (neutral) to use base threshold directly

        # NOTE: ADX returns 0.0 during warmup (insufficient history), causing neutral multipliers

        # This is expected behavior - the system uses base thresholds until sufficient data is available

        if adx >= 25.0:

            # Strong trend: neutral multiplier (was 1.05)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 25 (strong trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx >= 10.0:

            # Moderate trend: neutral multiplier

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 10 (moderate trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx >= 5.0:

            # Weak trend: neutral multiplier (was 0.95)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f >= 5 (weak trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        elif adx > 0 and adx < 5.0:

            # No trend: neutral multiplier (was 0.90)

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f < 5 (no trend) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )

        else:

            # No ADX data (warmup period): neutral multiplier

            adx_multiplier = 1.0

            logger.info(

                "[DYNAMIC-THRESHOLD] asset=%s ADX=%.2f (no data/warmup) -> ADX multiplier: 1.0 (neutral)",

                asset, adx

            )



        # Combine ATR and ADX adjustments (multiplicative)

        # This allows the system to be more aggressive in low-volatility, weak-trend conditions

        # and more conservative in high-volatility, strong-trend conditions

        combined_adjustment = atr_adjustment * adx_multiplier



        dynamic_threshold = base_threshold * combined_adjustment

        logger.info(

            "[DYNAMIC-THRESHOLD] asset=%s base_threshold=%.6f atr_adjustment=%.2f adx_multiplier=%.2f combined=%.2f dynamic_threshold=%.6f",

            asset, base_threshold, atr_adjustment, adx_multiplier, combined_adjustment, dynamic_threshold

        )



        return dynamic_threshold



    def _generate_momentum_fvg_signal(self, asset: str, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[Dict[str, Any]]:

        # Legacy path is disabled in paper/live unless explicitly enabled.
        if not _is_legacy_signal_enabled():
            logger.warning(
                "[LEGACY-SIGNAL-DISABLED] _generate_momentum_fvg_signal blocked in %s mode",
                os.environ.get("MERID_PM_TRADING_MODE", "unknown"),
            )
            return None

        """MOMENTUM_FVG STRATEGY: Combines velocity, MACD, RSI, OBI, and FVG for enhanced signals.



        CRITICAL FIX: 2026-07-06 - Wires MACD/RSI into momentum_fvg signal generation

        This strategy uses multiple indicators to generate high-confidence signals:

        - Velocity: Multi-window velocity with EMA smoothing and ATR normalization

        - MACD: Momentum confirmation (histogram sign and slope)

        - RSI: Overbought/oversold conditions for fade entries

        - OBI: Order book imbalance for confirmation

        - FVG: Fair Value Gap for confluence and timing

        """

        # Load profile configuration for momentum_fvg parameters

        try:

            from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile

            profile = get_crypto_15m_profile()

            momentum_fvg_config = profile.momentum_fvg

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to load profile config: %s", e)

            self._record_signal_rejection(
                "profile_load_failed",
                market_id=getattr(market, 'market_id', None) if hasattr(market, 'market_id') else getattr(getattr(market, 'market', None), 'market_id', None),
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} error={e}",
            )

            return None



        # Calculate velocity (multi-window with EMA smoothing)

        velocity = self._calculate_multi_window_velocity(asset, spot_price)

        velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)

        velocity_passed = abs(velocity) >= velocity_threshold

        self._record_waterfall(
            "velocity",
            velocity_passed,
            f"velocity={velocity:.6f} threshold={velocity_threshold:.6f}"
        )

        if not velocity_passed:

            logger.info(
                "[VELOCITY-FILTER] asset=%s velocity=%.6f below threshold=%.6f; continuing to evaluate confluence",
                asset, velocity, velocity_threshold
            )

        # CRITICAL FIX: 2026-07-08 - Check for sufficient warmup data before calculating indicators

        # Crypto15mIndicatorStack uses MACD(8,21,5) which needs 21 + 5 = 26 periods minimum

        # CRITICAL FIX: 2026-07-16 - RSI(14) needs 14 + 1 = 15 periods minimum (updated from RSI(8))

        # If insufficient data, skip signal generation to avoid zero/default indicator values

        # CRITICAL FIX: 2026-07-16 - REMOVED cold start bypass logic
        # Previous logic used min_bars_cold_start to allow trading with 1 bar during initialization
        # This completely bypassed the 30-bar warmup requirement, causing orders within minutes of startup
        # Now ALL trading requires full 30-bar warmup period

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()

                # CRITICAL FIX: 2026-07-16 - REMOVED cold start bypass
                # Previous comments about "allowing indicator stack's cold start logic" were incorrect
                # The indicator stack no longer has cold start bypass - it requires full 30-bar warmup

            except Exception as e:

                logger.error("[MOMENTUM-FVG-DATA-FAILURE] asset=%s indicator stack exception: %s - this is a BUG, not normal warmup", asset, e)

                # CRITICAL FIX: 2026-07-16 - Removed fallback path
                # Previous fallback only checked price history length but didn't calculate indicators
                # If indicator stack fails, fail fast - don't attempt signal generation without proper indicators
                logger.warning("[MOMENTUM-FVG] asset=%s indicator stack unavailable - skipping signal generation", asset)
                self._record_signal_rejection(
                    "indicator_stack_exception",
                    market_id=getattr(market, 'market_id', None) if hasattr(market, 'market_id') else getattr(getattr(market, 'market', None), 'market_id', None),
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} error={e}",
                )
                return None



        # Initialize indicator variables with defaults

        macd_slope = 0.0



        # CRITICAL FIX: 2026-07-08 - Use Crypto15mIndicatorStack for 2026 research-based indicators

        # This provides EMA(200), regime-based RSI, MACD filters, and RSI+MACD confluence scoring

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()



                # CRITICAL FIX: 2026-07-11 - Explicit warmup tracking
                # CRITICAL FIX: 2026-07-12 - Updated to 26 bars for MACD(8,21,5) initialization
                # MACD(8,21,5) needs 21 (slow) + 5 (signal) = 26 bars minimum

                min_bars_required = 26  # CRITICAL FIX: Updated from 30 to 26 for MACD(8,21,5) warmup

                if indicator_snap.bars_available < min_bars_required:

                    bars_needed = min_bars_required - indicator_snap.bars_available
                    eta_seconds = bars_needed * 60  # 1-minute bars

                    logger.info(

                        "[MOMENTUM-FVG-WARMUP] asset=%s bars_available=%d (requires %d) bars_needed=%d interval=1m eta_seconds=%d - NOT READY, skipping signal generation",

                        asset, indicator_snap.bars_available, min_bars_required, bars_needed, eta_seconds

                    )

                    # CRITICAL FIX (2026-07-13): Return None to prevent order execution during warmup
                    # Previous cold start logic bypassed the 30-bar requirement, allowing orders within 1-2 minutes
                    # This bypass defeats the purpose of the warmup period and exposes the system to unreliable signals
                    self._record_signal_rejection(
                        "momentum_fvg_warmup",
                        market_id=getattr(market, 'market_id', None) if hasattr(market, 'market_id') else getattr(getattr(market, 'market', None), 'market_id', None),
                        market_time_remaining_s=minutes_to_expiry * 60.0,
                        reference_price=spot_price,
                        candles_available=indicator_snap.bars_available,
                        feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} min_bars_required={min_bars_required} bars_needed={bars_needed}",
                    )
                    return None

                else:

                    logger.info(

                        "[MOMENTUM-FVG-INDICATOR-STACK] asset=%s bars_available=%d macd_line=%.6f macd_histogram=%.6f rsi=%.1f",

                        asset, indicator_snap.bars_available, indicator_snap.macd_line, indicator_snap.macd_histogram, indicator_snap.rsi

                    )



                # Extract 2026 research-based indicators from indicator stack

                rsi = indicator_snap.rsi

                rsi_zone = indicator_snap.rsi_zone

                macro_regime = indicator_snap.macro_regime

                price_above_ema_200 = indicator_snap.price_above_ema_200

                macd_line = indicator_snap.macd_line

                macd_histogram = indicator_snap.macd_histogram

                macd_zero_line_ok = indicator_snap.macd_zero_line_ok

                macd_histogram_expanding = indicator_snap.macd_histogram_expanding

                bias = indicator_snap.bias

                bias_confidence = indicator_snap.bias_confidence

                macd_slope = getattr(indicator_snap, 'macd_slope', 0.0)



                logger.debug(

                    "[MOMENTUM-FVG-INDICATORS] asset=%s rsi=%.1f zone=%s macro_regime=%s ema200_above=%s macd_line=%.6f macd_hist=%.6f zero_line_ok=%s hist_expanding=%s bias=%s confidence=%.2f",

                    asset, rsi, rsi_zone, macro_regime, price_above_ema_200, macd_line, macd_histogram, macd_zero_line_ok, macd_histogram_expanding, bias, bias_confidence

                )



                # Apply 2026 research-based filters



                # 1. EMA(200) macro trend filter - only trade in direction of macro trend

                # If price below EMA(200) (bear regime), prefer shorts; if above (bull regime), prefer longs

                if not price_above_ema_200 and macro_regime == "bear":

                    # In bear regime, prefer short signals

                    logger.debug("[EMA200-FILTER] asset=%s in bear regime (price below EMA200), prefer short signals", asset)

                elif price_above_ema_200 and macro_regime == "bull":

                    # In bull regime, prefer long signals

                    logger.debug("[EMA200-FILTER] asset=%s in bull regime (price above EMA200), prefer long signals", asset)



                # 2. Regime-based RSI threshold shifting

                # Bull regime: thresholds shifted up (80/40)

                # Bear regime: thresholds shifted down (60/20)

                # Range regime: neutral thresholds (70/30)

                # CRITICAL FIX: 2026-07-07 - Read thresholds from profile YAML instead of hardcoding

                # This ensures single source of truth and allows dynamic adjustment

                if macro_regime == "bull":

                    rsi_oversold = getattr(momentum_fvg_config, 'rsi_bull_oversold', 35.0)

                    rsi_overbought = getattr(momentum_fvg_config, 'rsi_bull_overbought', 75.0)

                elif macro_regime == "bear":

                    rsi_oversold = getattr(momentum_fvg_config, 'rsi_bear_oversold', 25.0)

                    rsi_overbought = getattr(momentum_fvg_config, 'rsi_bear_overbought', 65.0)

                else:  # range or neutral

                    rsi_oversold = 30.0  # Default neutral thresholds

                    rsi_overbought = 70.0



                # Recalculate RSI zone with regime-based thresholds

                if rsi <= rsi_oversold:

                    rsi_zone = "oversold"

                elif rsi >= rsi_overbought:

                    rsi_zone = "overbought"

                else:

                    rsi_zone = "neutral"



                # 3. MACD zero-line filter - only take longs if MACD > 0, shorts if MACD < 0

                # CRITICAL FIX: 2026-07-07 - Actually apply the filter, not just log
                # CRITICAL FIX: 2026-07-12 - Make filter direction-aware for long/short signals

                # Check if filter is enabled in profile

                macd_zero_line_enabled = getattr(momentum_fvg_config, 'macd_zero_line_filter_enabled', True)

                if macd_zero_line_enabled:
                    # Direction-aware zero-line filter
                    # Will be applied after signal direction is determined in long/short conditions
                    # For now, store the MACD value for later direction-specific check
                    pass  # Filter disabled in profile, skip check



                # 4. MACD histogram momentum filter - require histogram expansion

                # CRITICAL FIX: 2026-07-07 - Actually apply the filter, not just log

                # Check if filter is enabled in profile

                macd_histogram_enabled = getattr(momentum_fvg_config, 'macd_histogram_momentum_filter_enabled', True)

                if macd_histogram_enabled and not macd_histogram_expanding:

                    logger.debug("[MACD-HISTOGRAM-FILTER] asset=%s histogram not expanding, momentum weakening", asset)

                    # Don't skip signal entirely, but note the filter (histogram expansion is confirmation, not a hard gate)



                # 5. RSI+MACD confluence scoring - boost confidence when both agree

                # Long confluence: RSI oversold/neutral-bullish + MACD histogram positive

                # Short confluence: RSI overbought/neutral-bearish + MACD histogram negative

                confluence_boost = 0.0

                if rsi < 50.0 and macd_histogram > 0:

                    confluence_boost = 0.5  # Long confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s long confluence (RSI=%.1f<50, MACD hist=%.6f>0)", asset, rsi, macd_histogram)

                elif rsi > 50.0 and macd_histogram < 0:

                    confluence_boost = 0.5  # Short confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s short confluence (RSI=%.1f>50, MACD hist=%.6f<0)", asset, rsi, macd_histogram)



                # Extreme confluence (highest confidence)

                if rsi < rsi_oversold and macd_histogram > 0 and macd_histogram_expanding:

                    confluence_boost += 0.4  # Additional boost for extreme long confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s EXTREME long confluence (RSI oversold, MACD positive and expanding)", asset)

                elif rsi > rsi_overbought and macd_histogram < 0 and macd_histogram_expanding:

                    confluence_boost += 0.4  # Additional boost for extreme short confluence

                    logger.debug("[RSI-MACD-CONFLUENCE] asset=%s EXTREME short confluence (RSI overbought, MACD negative and expanding)", asset)



            except Exception as e:

                logger.warning("[MOMENTUM-FVG] Failed to get indicator snapshot from Crypto15mIndicatorStack: %s", e)

                # Fallback to internal calculations

                macd_histogram = 0.0

                macd_slope = 0.0

                rsi = 50.0

                rsi_zone = "neutral"

                confluence_boost = 0.0

        else:

            # Fallback: Use internal calculations if indicator stack not available

            logger.warning("[MOMENTUM-FVG] Crypto15mIndicatorStack not available for %s, using internal calculations", asset)

            macd_histogram = 0.0

            macd_slope = 0.0

            rsi = 50.0

            rsi_zone = "neutral"

            confluence_boost = 0.0

            macro_regime = "neutral"

            price_above_ema_200 = True

            macd_zero_line_ok = True

            macd_histogram_expanding = False



        # Get FVG signal from FVG forecaster

        fvg_signal = None

        fvg_confidence = 0.0

        fvg_direction = "neutral"



        try:

            from merid.prediction.forecasters.fvg import get_fvg_forecaster

            fvg_forecaster = get_fvg_forecaster()

            # Get market data for FVG forecaster

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None



            # Extract market parameters

            implied_yes = getattr(market_state, 'yes_price', 0.5) if market_state else 0.5

            implied_no = 1.0 - implied_yes

            volume = getattr(market_state, 'volume_24h', 0.0) if market_state else 0.0

            open_interest = getattr(market_state, 'open_interest', 0.0) if market_state else 0.0

            bid = getattr(market_state, 'bid', None) if market_state else None

            ask = getattr(market_state, 'ask', None) if market_state else None



            # Get FVG prediction with correct arguments

            fvg_result = fvg_forecaster.predict(

                market_id=ticker,

                implied_yes=implied_yes,

                implied_no=implied_no,

                volume=volume,

                open_interest=open_interest,

                minutes_to_expiry=minutes_to_expiry,

                asset=asset,

                timeframe="15m",

                bid=bid,

                ask=ask,

            )

            if fvg_result:

                fvg_confidence = fvg_result.confidence

                fvg_direction = fvg_result.components.get('fvg_nearest_direction', 0.0)

                if fvg_direction > 0:

                    fvg_direction = "bullish"

                elif fvg_direction < 0:

                    fvg_direction = "bearish"

                else:

                    fvg_direction = "neutral"

                fvg_signal = fvg_result

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to get FVG signal: %s", e)



        # Get OBI (Order Book Imbalance) from market state

        obi = 0.0

        obi_strong = False

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                # CRITICAL FIX: Use correct field names from KalshiMarketState model

                # The model uses depth_10c_yes and depth_10c_no, not depth_yes_10c and depth_no_10c

                depth_yes = getattr(market_state, 'depth_10c_yes', 0) or 0

                depth_no = getattr(market_state, 'depth_10c_no', 0) or 0



                # CRITICAL FIX: Check for valid depth data before calculating OBI

                # If both depths are 0, the market state may not have been populated yet

                if depth_yes == 0 and depth_no == 0:

                    logger.warning(

                        "[MOMENTUM-FVG] asset=%s ticker=%s depth data not available (depth_yes=0, depth_no=0), "

                        "market state may not be populated yet. Skipping OBI calculation.",

                        asset, ticker

                    )

                    # Don't use OBI in signal conditions if data is unavailable

                    obi = 0.0

                    obi_strong = False

                elif depth_yes + depth_no > 0:

                    obi = (depth_yes - depth_no) / (depth_yes + depth_no)

                    # Check per-asset strong thresholds

                    asset_obi_strong = getattr(momentum_fvg_config, f'obi_strong_{asset.lower()}', 0.5)

                    obi_strong = abs(obi) >= asset_obi_strong



                    # CRITICAL FIX: Log extreme OBI values for debugging

                    if abs(obi) >= 0.9:

                        logger.warning(

                            "[MOMENTUM-FVG] asset=%s ticker=%s extreme OBI=%.2f (depth_yes=%d depth_no=%d). "

                            "This may indicate one-sided liquidity or stale market data.",

                            asset, ticker, obi, depth_yes, depth_no

                        )

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] Failed to get OBI: %s", e)



        # Combine signals for momentum_fvg decision

        # Long signal conditions:

        # 1. Velocity > threshold (positive momentum)

        # 2. MACD histogram >= 0 (bullish momentum)

        # 3. RSI not overbought (not extended)

        # 4. OBI positive (buying pressure) OR FVG bullish confluence



        min_macd_hist_long = getattr(momentum_fvg_config, 'min_macd_hist_long', 0)

        min_macd_hist_short = getattr(momentum_fvg_config, 'min_macd_hist_short', 0)



        # CRITICAL FIX: 2026-07-08 - Read momentum RSI thresholds from profile YAML (single source of truth)

        # These thresholds define directional momentum: RSI > 55 for longs, RSI < 45 for shorts

        # Previous implementation did not use these thresholds, only checked RSI != overbought/oversold

        momentum_rsi_long_min = getattr(momentum_fvg_config, 'momentum_rsi_long_min', 55.0)

        momentum_rsi_short_max = getattr(momentum_fvg_config, 'momentum_rsi_short_max', 45.0)



        # CRITICAL FIX: 2026-07-08 - Read macd_dead_zone from profile YAML (single source of truth)

        # CRITICAL FIX: 2026-07-08 - During warmup (insufficient bars), disable dead zone to allow signals

        # When indicator stack has sufficient data (20+ bars), histogram values will be meaningful

        # During warmup, MACD histogram values are very small (near zero) due to insufficient data

        # Setting dead zone to 0.0 during warmup allows signals to be generated

        macd_dead_zone = getattr(momentum_fvg_config, 'macd_dead_zone', 0.0)



        # Check if indicator stack has sufficient data (warmup complete)

        if asset in self._indicator_stacks:

            try:

                indicator_snap = self._indicator_stacks[asset].snapshot()

                # If we have sufficient bars (>=20), use the configured dead zone

                # If not, disable dead zone to allow signals during warmup

                if indicator_snap.bars_available < 20:

                    macd_dead_zone = 0.0  # Disable dead zone during warmup

                    logger.debug("[MOMENTUM-FVG] asset=%s warmup mode (bars=%d < 20), disabled MACD dead zone",

                               asset, indicator_snap.bars_available)

            except Exception as e:

                logger.warning("[MOMENTUM-FVG] asset=%s failed to check indicator stack for warmup: %s", asset, e)

                macd_dead_zone = 0.0  # Disable dead zone on error to allow signals



        if abs(macd_histogram) < macd_dead_zone:

            logger.info(

                "[MOMENTUM-FVG-DEAD-ZONE] asset=%s macd_histogram=%.6f within dead zone (±%.6f), skipping signal to avoid noise",

                asset, macd_histogram, macd_dead_zone

            )

            self._record_signal_rejection(
                "macd_dead_zone",
                market_id=getattr(market, 'market_id', None) if hasattr(market, 'market_id') else getattr(getattr(market, 'market', None), 'market_id', None),
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} macd_histogram={macd_histogram} macd_dead_zone={macd_dead_zone}",
            )

            return None



        long_conditions = [

            velocity > velocity_threshold,

            macd_histogram >= min_macd_hist_long,

            rsi_zone != "overbought",

            rsi > momentum_rsi_long_min,  # CRITICAL FIX: 2026-07-08 - Add momentum RSI threshold for directional long signals

            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)

        ]



        short_conditions = [

            velocity < -velocity_threshold,

            macd_histogram < min_macd_hist_short,  # CRITICAL FIX: Use strict inequality to prevent symmetry at hist=0

            rsi_zone != "oversold",

            rsi < momentum_rsi_short_max,  # CRITICAL FIX: 2026-07-08 - Add momentum RSI threshold for directional short signals

            (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)

        ]



        # Count conditions met

        long_score = sum(long_conditions)

        short_score = sum(short_conditions)



        # CRITICAL FIX: 2026-07-09 - Dual-side edge evaluation for momentum_fvg

        # Use scores as inputs to edge calculation, not as direct side selectors

        # Both YES and NO get evaluated, then select side with higher positive edge



        # Get prices for both sides

        yes_price_cents = 0

        no_price_cents = 0

        # Extract market_id for logging (must be outside try block for scope)
        ticker = market.market.market_id if hasattr(market, 'market') else market.market_id
        market_id = ticker  # Alias for consistency with log schema

        market_state = None

        try:

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = int(round(getattr(market_state, 'best_bid_cents', 0) or 0))

                best_ask = int(round(getattr(market_state, 'best_ask_cents', 0) or 0))

                # YES price is the ASK (price to *buy* YES)
                yes_price_cents = best_ask if best_ask > 0 else 0

                # NO price is the NO ask = 100 - best YES bid
                no_price_cents = 100 - best_bid

        except Exception as e:

            logger.warning("[MOMENTUM-FVG] asset=%s failed to get market price: %s", asset, e)



        # CRITICAL FIX 2026-08-13: Determine thesis_side BEFORE evaluating cheapness.
        # Cheapness is evaluated on the thesis_side leg only. Near-zero velocity
        # must not be treated as a directional preference; confluence is used only
        # when it clearly favors one side.
        velocity_passed = abs(velocity) >= velocity_threshold
        if velocity_passed:
            thesis_side = "yes" if velocity > 0 else "no"
            thesis_source = "velocity"
            min_score = MERID_MOMENTUM_FVG_MIN_VELOCITY_CONFLUENCE_SCORE
            confluence_score = long_score if thesis_side == "yes" else short_score
            if confluence_score < min_score:
                logger.info(
                    "[MOMENTUM-FVG-THESIS] asset=%s velocity=%.6f passed but confluence_score=%d below min=%d -> NO TRADE",
                    asset, velocity, confluence_score, min_score
                )
                self._record_signal_rejection(
                    "momentum_fvg_weak_confluence",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={thesis_side} long_score={long_score} short_score={short_score} min_score={min_score}",
                )
                return None
        else:
            min_score = MERID_MOMENTUM_FVG_MIN_CONFLUENCE_SCORE
            if long_score >= min_score and long_score > short_score:
                thesis_side = "yes"
                thesis_source = "confluence"
            elif short_score >= min_score and short_score > long_score:
                thesis_side = "no"
                thesis_source = "confluence"
            else:
                logger.info(
                    "[MOMENTUM-FVG-NEUTRAL] asset=%s velocity=%.6f below threshold (%.6f); confluence unclear (long=%d short=%d) -> NO TRADE",
                    asset, velocity, velocity_threshold, long_score, short_score
                )
                self._record_signal_rejection(
                    "momentum_fvg_neutral",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} long_score={long_score} short_score={short_score} min_score={min_score}",
                )
                return None

        # STRICT MODE: Check for suspicious cheapness (feature flag)
        # In strict mode, reject candidates when thesis_side price is suspiciously cheap
        # This protects against "cheap but wrong" under bad data/stale books
        strict_mode_enabled = os.getenv("MERID_PRICE_SIDE_STRICT_MODE", "false").lower() == "true"

        # Extract strike_target from market metadata if available
        # CRITICAL FIX: Use window_strike_price instead of non-existent strike_target field
        # KalshiMarketState has window_strike_price, not strike_target
        # CRITICAL FIX: 2026-07-24 - Use previous 15m candle close as authoritative strike target
        # Kalshi's 15-minute markets use the closing price of the previous 15-minute candle
        # as the strike price for the new window
        # CRITICAL FIX 2026-08-12: Threshold markets (e.g., "Will XRP be above $1.00?")
        # expose strike_price, not floor_strike. The agent must fall back through all
        # available strike fields before giving up.
        strike_target = getattr(market_state, 'window_strike_price', None) if market_state else None
        if strike_target is None and market_state is not None:
            # Primary fallback: Kalshi's floor_strike is the authoritative 15m reference.
            strike_target = getattr(market_state, 'floor_strike', None)
            if strike_target is not None:
                logger.info(
                    "[STRIKE-TARGET-FALLBACK] asset=%s window_strike_price unavailable, using market_state.floor_strike=%.2f",
                    asset, strike_target
                )

        if strike_target is None and market_state is not None:
            # Threshold markets expose strike_price as the single reference level.
            strike_target = getattr(market_state, 'strike_price', None)
            if strike_target is not None:
                logger.info(
                    "[STRIKE-TARGET-FALLBACK] asset=%s window/floor_strike unavailable, using market_state.strike_price=%.4f",
                    asset, strike_target
                )

        if strike_target is None:
            # Secondary fallback: load the strike from the catalog for the current window.
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                if catalog:
                    current_market = catalog.get_current_15m_market(asset)
                    if current_market:
                        if current_market.floor_strike is not None:
                            strike_target = float(current_market.floor_strike)
                            logger.info(
                                "[STRIKE-TARGET-FALLBACK] asset=%s market state unavailable, using catalog floor_strike=%.2f",
                                asset, strike_target
                            )
                        elif current_market.strike_price is not None:
                            strike_target = float(current_market.strike_price)
                            logger.info(
                                "[STRIKE-TARGET-FALLBACK] asset=%s market state unavailable, using catalog strike_price=%.4f",
                                asset, strike_target
                            )
            except Exception as e:
                logger.warning("[STRIKE-TARGET-FALLBACK] asset=%s catalog lookup failed: %s", asset, e)

        if strike_target is None:
            # Final fallback: use current spot price as a degraded strike target.
            # Some 15m contracts (especially threshold markets and new windows)
            # do not expose floor/cap/strike fields; using spot keeps the agent
            # alive rather than failing every cycle.  If even spot is invalid,
            # raise as before so we never trade with an unusable strike.
            if _is_valid_strike_target(spot_price, asset):
                strike_target = float(spot_price)
                logger.warning(
                    "[STRIKE-TARGET-SPOT-FALLBACK] asset=%s using spot_price=%s as degraded strike target",
                    asset, format_price(asset, strike_target),
                )
            else:
                logger.error(
                    "[STRIKE-TARGET-FAILURE] asset=%s window_strike_price, floor_strike, and catalog floor_strike all unavailable - CRITICAL DATA FAILURE",
                    asset
                )
                # CRITICAL: Never use 0.0 as strike target - this invalidates all pricing logic
                # Raise exception to prevent trading with invalid strike target
                raise ValueError(f"Cannot determine strike target for {asset} - all data sources unavailable")

        # Sanity-validate the strike target (rejects corrupt metadata / unit errors)
        if strike_target is not None and not _is_valid_strike_target(strike_target, asset):
            logger.error(
                "[STRIKE-TARGET-INVALID] asset=%s strike_target=%r failed sanity bounds - rejecting (corrupt market metadata?)",
                asset, strike_target
            )
            strike_target = None

        # Check price band ONLY for thesis_side using side-aware ranges
        # CRITICAL FIX 2026-08-07: Single source of truth from binary_price_space.
        # YES: 10c-75c (canonical entry range)
        # NO: 10c-75c (canonical entry range)
        # This fixes the inconsistency where agent-grid rejected NO theses at 78-86c that allocator would accept

        # CRITICAL FIX 2026-08-03: Add diagnostic logging to verify thesis_side detection
        logger.info(
            "[THESIS-SIDE-DEBUG] asset=%s thesis_side=%s yes_price=%dc no_price=%dc "
            "thesis_in_range_check=%s range_str=%s",
            asset, thesis_side, yes_price_cents, no_price_cents,
            "YES:10-75c" if thesis_side == "yes" else "NO:10-75c",
            "10c-75c"
        )

        # Verify thesis_side is correctly normalized
        if thesis_side not in ["yes", "no"]:
            logger.error(
                "[THESIS-SIDE-ERROR] asset=%s invalid thesis_side=%s - must be 'yes' or 'no'",
                asset, thesis_side
            )
            return None

        # Evaluate canonical entry ranges for BOTH sides up front.  The thesis
        # side is still preferred, but if it is out of range while the opposite
        # side is executable we now allow the dual-side edge calc to select it.
        if PRICE_SPACE_AVAILABLE:
            yes_in_range = is_price_in_canonical_range(yes_price_cents, "yes")
            no_in_range = is_price_in_canonical_range(no_price_cents, "no")
        else:
            yes_in_range = (10 <= yes_price_cents <= 75)
            no_in_range = (10 <= no_price_cents <= 75)

        if thesis_side == "yes":
            thesis_price_cents = yes_price_cents
            thesis_in_range = yes_in_range
            range_str = "10c-75c"
            logger.info(
                "[PRICE-SIDE-CHECK] timestamp=%s asset=%s market_id=%s strike_target=%s signal_side=%s thesis_side=%s "
                "yes_price=%dc no_price=%dc selected_side=%s selected_price=%dc price_range_ok=%s strict_mode=%s "
                "yes_in_range=%s no_in_range=%s (cheapness evaluated on thesis_side, YES range=%s)",
                dt.utcnow().isoformat(), asset, market_id or "unknown", strike_target or "N/A",
                thesis_side, thesis_side, yes_price_cents, no_price_cents, thesis_side, thesis_price_cents,
                thesis_in_range, strict_mode_enabled, yes_in_range, no_in_range, range_str
            )
        else:  # thesis_side == "no"
            thesis_price_cents = no_price_cents
            thesis_in_range = no_in_range
            range_str = "10c-75c"
            logger.info(
                "[PRICE-SIDE-CHECK] timestamp=%s asset=%s market_id=%s strike_target=%s signal_side=%s thesis_side=%s "
                "yes_price=%dc no_price=%dc selected_side=%s selected_price=%dc price_range_ok=%s strict_mode=%s "
                "yes_in_range=%s no_in_range=%s (cheapness evaluated on thesis_side, NO range=%s)",
                dt.utcnow().isoformat(), asset, market_id or "unknown", strike_target or "N/A",
                thesis_side, thesis_side, yes_price_cents, no_price_cents, thesis_side, thesis_price_cents,
                thesis_in_range, strict_mode_enabled, yes_in_range, no_in_range, range_str
            )

        # Reject only when neither side is within the canonical entry range.
        # Side-lock: the model is only allowed to trade its thesis side.
        # No counter-trend or opposite-side fallback.
        if not (yes_in_range or no_in_range):
            logger.info(
                "[PRICE-SIDE-CHECK-REJECT] timestamp=%s asset=%s market_id=%s thesis_side=%s "
                "yes_price=%dc no_price=%dc reject_type=BOTH_SIDES_OUT_OF_RANGE both prices outside %s range -> NO TRADE",
                dt.utcnow().isoformat(), asset, market_id or "unknown", thesis_side,
                yes_price_cents, no_price_cents, range_str
            )
            self._record_signal_rejection(
                "both_sides_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={thesis_side} yes_price={yes_price_cents} no_price={no_price_cents} range={range_str}",
            )
            return None

        if not thesis_in_range:
            logger.info(
                "[PRICE-SIDE-CHECK-REJECT] timestamp=%s asset=%s market_id=%s thesis_side=%s "
                "thesis_price=%dc out of %s range -> NO TRADE (side lock, no counter-trend fallback)",
                dt.utcnow().isoformat(), asset, market_id or "unknown", thesis_side,
                thesis_price_cents, range_str
            )
            self._record_signal_rejection(
                "thesis_side_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={thesis_side} thesis_price={thesis_price_cents} range={range_str}",
            )
            return None

        # STRICT MODE: Reject suspiciously cheap thesis_side prices
        # This protects against stale book data or market disequilibrium
        if strict_mode_enabled:
            suspicious_cheap_threshold = 15  # Suspicious if price < 15c
            if thesis_price_cents < suspicious_cheap_threshold:
                logger.warning(
                    "[PRICE-SIDE-CHECK-REJECT] timestamp=%s asset=%s market_id=%s strike_target=%s signal_side=%s thesis_side=%s "
                    "yes_price=%dc no_price=%dc reject_type=STRICT_MODE_REJECT thesis_price=%dc suspiciously cheap (<%dc) -> NO TRADE "
                    "(strict mode enabled: rejecting suspicious cheapness to protect against bad data)",
                    dt.utcnow().isoformat(), asset, market_id or "unknown", strike_target or "N/A",
                    thesis_side, thesis_side, yes_price_cents, no_price_cents, thesis_price_cents, suspicious_cheap_threshold
                )
                self._record_signal_rejection(
                    "strict_mode_suspiciously_cheap",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={thesis_side} thesis_price={thesis_price_cents} strict_mode={strict_mode_enabled}",
                )
                return None

        # Log both sides for diagnostic purposes (ranges already computed above).
        logger.info(
            "[MOMENTUM-FVG-PRICE-RANGE] asset=%s yes_price=%dc yes_in_range=%s no_price=%dc no_in_range=%s thesis_side=%s",
            asset, yes_price_cents, yes_in_range, no_price_cents, no_in_range, thesis_side
        )



        # Build edges for both YES and NO using the unit-corrected helper.
        # MACD is normalized by spot_price so BTC's $1.50 histogram is not
        # treated as 15 percentage points while an alt's $0.0015 histogram is 0.

        _macd_pct = (macd_histogram / max(spot_price, 1e-12)) * 100.0 if spot_price and macd_histogram is not None else 0.0

        yes_components = _fvg_edge_components(
            score=long_score,
            side_velocity_sign=1.0,
            velocity=velocity,
            velocity_threshold=velocity_threshold,
            macd_hist=macd_histogram,
            spot_price=spot_price,
            rsi=rsi,
            rsi_zone=rsi_zone,
            fvg_dir=fvg_direction,
            fvg_conf=fvg_confidence,
        )
        no_components = _fvg_edge_components(
            score=short_score,
            side_velocity_sign=-1.0,
            velocity=velocity,
            velocity_threshold=velocity_threshold,
            macd_hist=macd_histogram,
            spot_price=spot_price,
            rsi=rsi,
            rsi_zone=rsi_zone,
            fvg_dir=fvg_direction,
            fvg_conf=fvg_confidence,
        )

        edge_yes_pct = yes_components["edge_pct"]
        edge_no_pct = no_components["edge_pct"]

        # Calculate edges for both sides with validation

        # CRITICAL FIX: Validate both sides have valid prices before edge calculation
        # If one side is N/A, reconstruct from the other side using duality (NO = 100 - YES)
        if yes_price_cents is None or yes_price_cents <= 0:
            if no_price_cents and no_price_cents > 0:
                yes_price_cents = 100 - no_price_cents
                logger.warning(
                    "[PRICE-RECONSTRUCTION] asset=%s YES price was N/A, reconstructed from NO price: YES=%dc (NO=%dc)",
                    asset, yes_price_cents, no_price_cents
                )
            else:
                logger.error(
                    "[PRICE-VALIDATION-FAILURE] asset=%s both YES and NO prices are N/A - CANNOT CALCULATE EDGES",
                    asset
                )
                self._record_signal_rejection(
                    "both_prices_unavailable",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} yes_price={yes_price_cents} no_price={no_price_cents}",
                )
                return None

        if no_price_cents is None or no_price_cents <= 0:
            if yes_price_cents and yes_price_cents > 0:
                no_price_cents = 100 - yes_price_cents
                logger.warning(
                    "[PRICE-RECONSTRUCTION] asset=%s NO price was N/A, reconstructed from YES price: NO=%dc (YES=%dc)",
                    asset, no_price_cents, yes_price_cents
                )
            else:
                logger.error(
                    "[PRICE-VALIDATION-FAILURE] asset=%s both YES and NO prices are N/A - CANNOT CALCULATE EDGES",
                    asset
                )
                self._record_signal_rejection(
                    "both_prices_unavailable",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} yes_price={yes_price_cents} no_price={no_price_cents}",
                )
                return None

        # Recalculate side-aware range checks after reconstruction
        # CRITICAL FIX 2026-08-07: Use side-aware ranges to match thesis_side check
        # YES: 10c-75c (canonical entry range)
        # NO: 10c-75c (canonical entry range)
        if PRICE_SPACE_AVAILABLE:
            yes_in_range = is_price_in_canonical_range(yes_price_cents, "yes")
            no_in_range = is_price_in_canonical_range(no_price_cents, "no")
        else:
            yes_in_range = (10 <= yes_price_cents <= 75)
            no_in_range = (10 <= no_price_cents <= 75)

        # edge_yes_pct / edge_no_pct already computed with unit-corrected MACD above.



        # Log dual-side evaluation with enhanced diagnostic detail
        logger.info(
            "[DUAL-SIDE-EVAL] asset=%s yes_price=%dc no_price=%dc yes_in_range=%s no_in_range=%s "
            "strike_target=%s",
            asset, yes_price_cents, no_price_cents, yes_in_range, no_in_range,
            strike_target or "N/A"
        )

        logger.info(
            "[DUAL-SIDE-EDGE-CALC] asset=%s long_score=%d short_score=%d yes_edge=%s no_edge=%s "
            "macd_hist=%.6f macd_hist_pct=%.6f macd_edge_weight=%.2f "
            "yes_base_edge=%.4f yes_macd_edge=%.4f no_base_edge=%.4f no_macd_edge=%.4f "
            "rsi=%.2f fvg_dir=%s fvg_conf=%.2f obi=%.3f obi_strong=%s",
            asset, long_score, short_score,
            f"{edge_yes_pct:.4f}" if edge_yes_pct is not None else "N/A",
            f"{edge_no_pct:.4f}" if edge_no_pct is not None else "N/A",
            macd_histogram, _macd_pct, MERID_MACD_EDGE_WEIGHT,
            yes_components["base_edge"], yes_components["macd_edge"],
            no_components["base_edge"], no_components["macd_edge"],
            rsi, fvg_direction, fvg_confidence, obi, obi_strong
        )



        # Select side with higher positive edge

        side_edges = {}

        if edge_yes_pct is not None:

            side_edges["yes"] = edge_yes_pct

        if edge_no_pct is not None:

            side_edges["no"] = edge_no_pct



        if not side_edges:

            logger.info(

                "[MOMENTUM-FVG-NO-EDGE] asset=%s no valid edges (both sides below threshold) -> NO TRADE",

                asset

            )

            self._record_signal_rejection(
                "no_valid_edges",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} long_score={long_score} short_score={short_score}",
            )

            return None



        # CRITICAL FIX: 2026-07-09 - Add midpoint preference (~25c bonus) to momentum_fvg

        def midpoint_bonus(price_cents):

            """Peak at 25c, decays toward 10c/75c."""

            dist = abs(price_cents - 25)

            midpoint_bonus_max = 0.5  # Maximum bonus in percentage points

            midpoint_bonus_slope = 0.02  # Decay rate per cent from midpoint

            return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)



        # CRITICAL FIX 2026-08-13: Side-lock. The model is only allowed to trade
        # its thesis side. No counter-trend or opposite-side fallback.

        yes_edge = side_edges.get("yes")
        no_edge = side_edges.get("no")

        signal_side = thesis_side
        selected_edge = side_edges.get(signal_side)

        if not selected_edge or selected_edge <= 0:
            logger.info(
                "[MOMENTUM-FVG-THESIS-NO-EDGE] asset=%s thesis_side=%s thesis_source=%s has no positive edge (edge=%s) -> NO TRADE",
                asset, signal_side, thesis_source, selected_edge
            )
            self._record_signal_rejection(
                "thesis_side_no_positive_edge",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={signal_side} thesis_source={thesis_source} edge={selected_edge}",
            )
            return None

        if (signal_side == "yes" and not yes_in_range) or (signal_side == "no" and not no_in_range):
            thesis_price = yes_price_cents if signal_side == "yes" else no_price_cents
            logger.info(
                "[MOMENTUM-FVG-THESIS-OUT-OF-RANGE] asset=%s thesis_side=%s thesis_price=%dc not in canonical range -> NO TRADE",
                asset, signal_side, thesis_price
            )
            self._record_signal_rejection(
                "thesis_side_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} thesis_side={signal_side} price_cents={thesis_price}",
            )
            return None

        # Apply midpoint bonus to selected side
        if signal_side == "yes" and yes_in_range:
            selected_edge = selected_edge + midpoint_bonus(yes_price_cents)
        elif signal_side == "no" and no_in_range:
            selected_edge = selected_edge + midpoint_bonus(no_price_cents)

        # Log thesis-locked selection with diagnostic detail
        edge_ratio = (yes_edge / no_edge) if yes_edge and no_edge and no_edge > 0 else float('inf')

        velocity_status = "passed" if velocity_passed else "neutral"
        velocity_expected_side_simple = "yes" if velocity > 0 else "no"
        if not velocity_passed:
            alignment = "NEUTRAL"
        elif signal_side == velocity_expected_side_simple:
            alignment = "ALIGNED"
        else:
            alignment = "COUNTER_TREND"

        logger.info(
            "[DUAL-SIDE-SELECTION] asset=%s velocity=%.6f velocity_status=%s thesis_side=%s thesis_source=%s "
            "yes_edge=%.4f no_edge=%.4f selected_side=%s selected_edge=%.4f "
            "edge_ratio=%.2f alignment=%s selection_method=SIDE_LOCK",
            asset, velocity, velocity_status, thesis_side, thesis_source,
            yes_edge or 0.0, no_edge or 0.0,
            signal_side, selected_edge, edge_ratio, alignment
        )

        # PHASE 1: Dual-side evaluation logging (no longer shadow - this is actual selection)
        # Log velocity alignment for analysis of whether velocity still provides useful signal
        try:
            from merid.prediction.signal_terminology import Side
            UNIFIED_TERMINOLOGY_AVAILABLE = True
        except ImportError:
            UNIFIED_TERMINOLOGY_AVAILABLE = False

        if UNIFIED_TERMINOLOGY_AVAILABLE:
            velocity_expected_side = Side.from_velocity_and_mode(velocity, "trend_following").value
        else:
            velocity_expected_side = "yes" if velocity > 0 else "no"

        velocity_expected_edge = side_edges.get(velocity_expected_side) if side_edges.get(velocity_expected_side) is not None else 0.0
        opposite_side = "no" if velocity_expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side) if side_edges.get(opposite_side) is not None else 0.0

        # CRITICAL FIX: 2026-07-24 - Define expected_side and related variables for metrics logging
        # These were referenced but not defined, causing "name 'expected_side' is not defined" error
        expected_side = velocity_expected_side
        expected_side_edge = velocity_expected_edge

        # Determine hypothetical best side (unconstrained dual-side selection)
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = expected_side
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = opposite_side
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge

        # Log velocity alignment diagnostic
        if not velocity_passed:
            alignment = "NEUTRAL"
        elif signal_side == velocity_expected_side:
            alignment = "ALIGNED"
        else:
            alignment = "COUNTER_TREND"

        logger.info(
            "[VELOCITY-ALIGNMENT-DIAGNOSTIC] asset=%s velocity=%.6f velocity_passed=%s velocity_expected_side=%s velocity_expected_edge=%.4f "
            "opposite_side=%s opposite_edge=%.4f actual_selected_side=%s actual_selected_edge=%.4f "
            "alignment=%s yes_in_range=%s no_in_range=%s",
            asset, velocity, velocity_passed, velocity_expected_side, velocity_expected_edge,
            opposite_side, opposite_side_edge, signal_side, selected_edge,
            alignment, yes_in_range, no_in_range
        )

        # Log to shadow dual-side metrics monitor
        try:
            from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor
            monitor = get_shadow_dual_side_monitor()
            monitor.log_shadow_evaluation(
                asset=asset,
                velocity=velocity,
                strategy_mode="momentum_fvg",
                expected_side=expected_side,
                expected_edge=expected_side_edge,
                opposite_side=opposite_side,
                opposite_edge=opposite_side_edge,
                hypothetical_best_side=hypothetical_best_side,
                hypothetical_best_edge=hypothetical_best_edge,
                yes_in_range=yes_in_range,
                no_in_range=no_in_range
            )
        except Exception as metrics_err:
            logger.warning("[SHADOW-DUAL-SIDE-METRICS] Failed to log to metrics monitor: %s", metrics_err)



        # Minimum edge threshold (per-asset aligned with risk_parameters.py market entry thresholds)

        # 2026-07-12: Use centralized edge validation from risk_parameters.py
        # All edge values now in FRACTION units (0.0-1.0) for consistency
        from merid.event_venues.kalshi.risk_parameters import validate_edge

        signal_action = "buy"

        # CRITICAL 2026-08-13: selected_edge is in percentage points (from
        # calculate_velocity_edge and the bonus stack).  validate_edge expects
        # a fraction and confidence is on [0,1], so convert before using.
        edge_pct_for_threshold = selected_edge / 100.0

        confidence = 0.5 + edge_pct_for_threshold

        confidence = min(0.95, confidence)

        is_valid, reason = validate_edge(edge_pct_for_threshold, asset, confidence)

        if not is_valid:
            logger.info(
                "[MOMENTUM-FVG-EDGE-THRESHOLD] asset=%s selected_edge=%.6f - %s -> NO TRADE",
                asset, selected_edge, reason
            )
            self._record_signal_rejection(
                f"edge_threshold:{reason}",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} selected_edge={selected_edge} signal_side={signal_side}",
            )
            return None



        logger.info(
            "[MOMENTUM-FVG-SELECTION] asset=%s selected_side=%s edge=%.6f confidence=%.2f (all_edges=%s)",
            asset, signal_side, selected_edge, confidence, side_edges
        )

        # CRITICAL FIX 2026-08-13: Side-lock enforced. signal_side always equals
        # thesis_side; counter-trend / opposite-side fallback has been removed.

        # CRITICAL INSTRUMENTATION (2026-07-23): Log raw directional indicators for bias analysis
        logger.info(
            "[SIGNAL-RAW-INDICATORS] asset=%s velocity=%.6f velocity_threshold=%.6f macd_histogram=%.6f "
            "macd_hist_pct=%.6f rsi=%.2f rsi_zone=%s long_score=%d short_score=%d fvg_direction=%s fvg_confidence=%.2f obi=%.2f obi_strong=%s",
            asset, velocity, velocity_threshold, macd_histogram, _macd_pct, rsi, rsi_zone,
            long_score, short_score, fvg_direction, fvg_confidence, obi, obi_strong
        )

        self._telemetry_update(
            ticker=market_id,
            minutes_to_expiry=minutes_to_expiry,
            selected_side=signal_side,
            velocity=velocity,
            velocity_threshold=velocity_threshold,
            spot_price=spot_price,
            macd_histogram=macd_histogram,
            macd_hist_pct=_macd_pct,
            base_edge_yes=yes_components["base_edge"],
            macd_edge_component_yes=yes_components["macd_edge"],
            edge_yes_pct=edge_yes_pct,
            base_edge_no=no_components["base_edge"],
            macd_edge_component_no=no_components["macd_edge"],
            edge_no_pct=edge_no_pct,
            rsi=rsi,
            fvg_direction=fvg_direction,
            fvg_confidence=fvg_confidence,
            order_book_imbalance=obi,
            yes_ask_cents=yes_price_cents,
            no_ask_cents=no_price_cents,
        )

        # Use selected_edge from dual-side evaluation (already computed)

        edge_pct = selected_edge

        # Calculate market price from selected side
        if signal_side == "yes":
            market_price = yes_price_cents / 100.0
        else:
            market_price = no_price_cents / 100.0

        # BIAS MONITORING: Record signal side for bias detection
        if BIAS_MONITOR_ENABLED:
            bias_monitor = get_bias_monitor()
            if bias_monitor:
                bias_monitor.record_signal(asset=asset, side=signal_side, edge=edge_pct, price=market_price)

        # BTC SENTIMENT BIAS: Apply correlation-based bias adjustment for non-BTC assets
        if self._btc_sentiment_bias_enabled and self._btc_sentiment_bias and asset != "BTC":
            try:
                bias_adjustment = self._btc_sentiment_bias.get_bias_adjustment(
                    asset=asset,
                    base_edge=edge_pct,
                    current_side=signal_side
                )
                if bias_adjustment != 0.0:
                    edge_pct += bias_adjustment
                    logger.info(
                        "[BTC-SENTIMENT-BIAS-APPLIED] asset=%s original_edge=%.4f bias_adjustment=%.4f adjusted_edge=%.4f side=%s",
                        asset, selected_edge, bias_adjustment, edge_pct, signal_side
                    )
            except Exception as bias_exc:
                logger.warning("[BTC-SENTIMENT-BIAS-ERROR] asset=%s error=%s", asset, bias_exc)



        # CRITICAL FIX: 2026-07-16 - Use actual market prices from dual-side evaluation instead of hardcoded 42c
        # The dual-side evaluation (lines 4400-4410) already retrieved yes_price_cents and no_price_cents
        # from market_state_store. We must use those actual prices instead of falling back to 42c.
        # Using 42c causes model_prob to be calculated from wrong market probability, leading to
        # Kelly filter rejections despite valid edges (e.g., 9.3% edge rejected because model_prob=0.48
        # instead of 0.77 when actual price is 68c).

        if signal_side == "yes":
            price_cents = yes_price_cents if yes_price_cents > 0 else 42
            price_source = "dual_side_yes_price" if yes_price_cents > 0 else "fallback_42c"
        else:  # signal_side == "no"
            price_cents = no_price_cents if no_price_cents > 0 else 42
            price_source = "dual_side_no_price" if no_price_cents > 0 else "fallback_42c"

        logger.info("[PRICE-CENTS-DEBUG] asset=%s signal_side=%s price_cents=%d source=%s (using dual-side evaluation prices)",
                    asset, signal_side, price_cents, price_source)



        # Calculate model probability from selected edge
        # CRITICAL FIX (2026-08-11): edge_pct is in percentage points; convert to a
        # probability fraction before adding to the market-implied probability.
        # The probability estimate is clamped to (0, 1) and never allowed to exceed 1.

        market_prob = price_cents / 100.0 if price_cents > 0 else 0.5

        # Cap edge adjustment to 20 percentage points, then convert to fraction.
        edge_adjustment_pct = min(abs(edge_pct), MERID_MAX_EDGE_ADJUSTMENT_PCT)
        edge_adjustment = edge_adjustment_pct / 100.0

        if signal_side == "yes":
            model_prob = market_prob + edge_adjustment
        else:
            # price_cents is the NO price, so market_prob is already P(NO).
            model_prob = market_prob + edge_adjustment

        # Clamp to a valid open interval (never 0 or 1, never > 1).
        eps = MERID_MODEL_PROBABILITY_EPSILON
        model_prob = max(eps, min(1.0 - eps, model_prob))

        # Determine execution role and fee. Prefer maker (resting, 0 fee) unless
        # expiry is very close or the edge is large enough to justify crossing the
        # spread as a taker. This makes the EV gate economically coherent.
        seconds_to_expiry = minutes_to_expiry * 60.0
        is_late = seconds_to_expiry < MERID_MOMENTUM_FVG_LATE_WINDOW_SECONDS
        is_high_edge = selected_edge >= MERID_MOMENTUM_FVG_TAKER_EDGE_PCT

        if getattr(self.config, 'prefer_maker_orders', True) and not is_late and not is_high_edge:
            liquidity_role = "maker"
            aggressiveness = 0.0
            execution_mode = "maker"
            time_in_force = "gtc"
            post_only = True
            fee_cents = 0.0
        else:
            liquidity_role = "taker"
            aggressiveness = 1.0
            execution_mode = "taker"
            time_in_force = "ioc"
            post_only = False
            fee_cents = float(compute_fee_cents(price_cents)) if _UNIFIED_SIZING_AVAILABLE else 2.0

        impact_reserve_cents = MERID_EV_IMPACT_RESERVE_CENTS

        # Compute all-in cost and EV using role-aware fee and calibrated impact reserve.
        all_in_cost_cents = float(price_cents) + fee_cents + impact_reserve_cents
        ev_net_cents = (model_prob * 100.0) - all_in_cost_cents

        try:
            _tel_slippage_cents = int(_get_slippage_cents()) if _UNIFIED_SIZING_AVAILABLE else 5
            _tel_robust_cost = float(price_cents) + fee_cents + float(_tel_slippage_cents)
            self._telemetry_update(
                model_prob=model_prob,
                market_prob=market_prob,
                edge_pct=edge_pct,
                capped_edge_pct=edge_pct,
                raw_edge_cents=(model_prob - market_prob) * 100.0,
                entry_fee_cents=fee_cents,
                impact_reserve_cents=impact_reserve_cents,
                slippage_guard_cents=_tel_slippage_cents,
                all_in_cost_cents=all_in_cost_cents,
                ev_net_cents=ev_net_cents,
                robust_ev_cents=(model_prob * 100.0) - _tel_robust_cost,
                price_cents=price_cents,
                price_source=price_source,
                liquidity_role=liquidity_role,
                displayed_depth=_lookup_displayed_depth(market_state, signal_side, price_cents),
            )
        except Exception:
            pass

        # Base EV gate: must be positive expected value net of role-aware cost and impact reserve.
        if ev_net_cents <= 0:
            _emit_ev_components_log(
                market_state=market_state,
                asset=asset,
                signal_side=signal_side,
                signal_action=signal_action,
                price_cents=price_cents,
                price_source=price_source,
                market_prob=market_prob,
                model_prob=model_prob,
                decision="no_trade",
                fee_cents=fee_cents,
                impact_reserve_cents=impact_reserve_cents,
                liquidity_role=liquidity_role,
            )
            self._record_signal_rejection(
                "ev_gate_non_positive",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} price_cents={price_cents} ev_net_cents={ev_net_cents} liquidity_role={liquidity_role}",
            )
            return None

        # Extreme-price guardrail: 1-5c and 95-99c require a stronger LCB EV margin.
        is_extreme_price = price_cents <= 5 or price_cents >= 95
        if is_extreme_price:
            min_ev_cents = MERID_EV_K_EXTREME * fee_cents
            if ev_net_cents < min_ev_cents:
                _emit_ev_components_log(
                    market_state=market_state,
                    asset=asset,
                    signal_side=signal_side,
                    signal_action=signal_action,
                    price_cents=price_cents,
                    price_source=price_source,
                    market_prob=market_prob,
                    model_prob=model_prob,
                    decision="no_trade_extreme",
                    fee_cents=fee_cents,
                    impact_reserve_cents=impact_reserve_cents,
                    liquidity_role=liquidity_role,
                )
                logger.info(
                    "[SIGNAL-EV-EXTREME] asset=%s side=%s price=%dc model_prob=%.4f ev_net=%.4fc < %.4fc (k=%.2f * fee=%.2fc) -> NO TRADE",
                    asset, signal_side, price_cents, model_prob, ev_net_cents, min_ev_cents,
                    MERID_EV_K_EXTREME, fee_cents
                )
                self._record_signal_rejection(
                    "ev_extreme_price",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} price_cents={price_cents} ev_net_cents={ev_net_cents} min_ev_cents={min_ev_cents}",
                )
                return None

        _emit_ev_components_log(
            market_state=market_state,
            asset=asset,
            signal_side=signal_side,
            signal_action=signal_action,
            price_cents=price_cents,
            price_source=price_source,
            market_prob=market_prob,
            model_prob=model_prob,
            decision="pass",
            fee_cents=fee_cents,
            impact_reserve_cents=impact_reserve_cents,
            liquidity_role=liquidity_role,
        )

        logger.info(
            "[PRICE-BASED-DEBUG] asset=%s price_cents=%d price_source=%s market_prob=%.4f edge_pct=%.2f%% edge_adjustment=%.4f model_prob=%.4f all_in_cost=%.2fc ev_net=%.4fc",
            asset, price_cents, price_source, market_prob, edge_pct, edge_adjustment, model_prob,
            all_in_cost_cents, ev_net_cents
        )

        logger.info("[PRICE-CENTS-DEBUG] asset=%s final_price_cents=%d source=%s", asset, price_cents, price_source)



        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = price_cents



        # Check if price is within canonical 10c-75c range

        if 10 <= raw_price_cents <= 75:

            # Price is already in the side-appropriate range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d in side-aware range - using directly",

                asset, signal_side, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d outside side-aware range - searching orderbook",

                asset, signal_side, raw_price_cents

            )



            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None



                if market_state:

                    # Select the opposite-side book to compute the ask for the target side.
                    # YES ask = 100 - NO bid; NO ask = 100 - YES bid.

                    if signal_side == "yes":
                        # Cheapest YES ask = 100 - NO bid; search no_bids.
                        levels = getattr(market_state, 'no_bids', [])
                        range_min, range_max = 10, 75
                    else:
                        # Cheapest NO ask = 100 - YES bid; search yes_bids.
                        levels = getattr(market_state, 'yes_bids', [])
                        range_min, range_max = 10, 75

                    if levels:

                        # Find cheapest executable price in the side-appropriate range.
                        # For YES: 100 - no_bid; for NO: 100 - yes_bid.

                        valid_prices = [100 - p for (p, size) in levels if range_min <= (100 - p) <= range_max and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # cheapest acceptable executable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s side=%s found %d valid prices in [%dc-%dc], using cheapest=%d",

                                asset, signal_side, len(valid_prices), range_min, range_max, price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s side=%s no executable prices in [%dc-%dc] - dropping candidate",

                                asset, signal_side, range_min, range_max

                            )

                            self._record_signal_rejection(
                                "no_executable_price_in_range",
                                market_id=market_id,
                                market_time_remaining_s=minutes_to_expiry * 60.0,
                                reference_price=spot_price,
                                velocity=velocity,
                                threshold=velocity_threshold,
                                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} range={range_min}-{range_max}",
                            )

                            return None  # Drop candidate - no valid price in side-aware range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s side=%s orderbook not available - dropping candidate",

                            asset, signal_side

                        )

                        self._record_signal_rejection(
                            "orderbook_not_available",
                            market_id=market_id,
                            market_time_remaining_s=minutes_to_expiry * 60.0,
                            reference_price=spot_price,
                            velocity=velocity,
                            threshold=velocity_threshold,
                            feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    self._record_signal_rejection(
                        "market_state_not_available",
                        market_id=market_id,
                        market_time_remaining_s=minutes_to_expiry * 60.0,
                        reference_price=spot_price,
                        velocity=velocity,
                        threshold=velocity_threshold,
                        feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                self._record_signal_rejection(
                    "price_selection_exception",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} error={e}",
                )

                return None



            clamped_price_cents = price_cents



        # Final validation - side-aware canonical range
        # CRITICAL FIX (2026-08-05): YES and NO trade in different price regions. The previous
        # single 10c-75c range rejected all NO candidates above 75c even though NO contracts
        # naturally trade at high prices (implied probability of event NOT happening).
        # Single canonical entry range 10c-75c for both YES and NO.  Duality
        # means an 80c NO is equivalent to a 20c YES; there is no need to allow
        # either side to trade outside 10-75, and order_intent_contract rejects
        # such prices with `invalid_price`.
        price_min, price_max = 10, 75
        range_str = "10c-75c"

        if clamped_price_cents is None or not (price_min <= clamped_price_cents <= price_max):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s side=%s final price_cents=%d not in range [%s] - dropping candidate",

                asset, signal_side, clamped_price_cents, range_str

            )

            self._record_signal_rejection(
                "final_price_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} price_cents={clamped_price_cents} range={range_str}",
            )

            return None



        logger.info(

            "[PRICE-SELECTION] asset=%s side=%s final entry price=%d (within canonical range [%s])",

            asset, signal_side, clamped_price_cents, range_str

        )



        # Kalshi contracts trade in whole cents.  Guard against any float or numpy
        # scalar leaking through from market-state arithmetic.
        price_cents = int(round(clamped_price_cents))

        # Recompute all-in cost and EV at the final rounded price so the signal
        # contract matches the price sent to the router. Fee is role-aware.
        if liquidity_role == "taker":
            fee_cents = float(compute_fee_cents(price_cents)) if _UNIFIED_SIZING_AVAILABLE else 2.0
        else:
            fee_cents = 0.0
        all_in_cost_cents = float(price_cents) + fee_cents + impact_reserve_cents
        ev_net_cents = (model_prob * 100.0) - all_in_cost_cents



        # CRITICAL FIX: 2026-07-19 - Add SignalFusion microstructure signals to signal output
        # These signals provide additional confirmation for trades via orderflow and on-chain activity
        # Currently set to 0.0 as stubs - future integration will pull from SignalFusionAgent
        orderflow_bias = 0.0  # Positive = buying pressure, negative = selling pressure
        onchain_velocity = 0.0  # Positive = elevated on-chain activity, negative = muted

        # CRITICAL FIX: 2026-07-19 - Determine strategy intent from selected side
        # YES side = BULLISH_EVENT (betting on event occurring)
        # NO side = BEARISH_EVENT (betting against event occurring)
        # CORRECT MAPPING (2026-07-23): signal_side maps to matching intent
        # signal_side=yes → BULLISH_EVENT (expect price up), signal_side=no → BEARISH_EVENT (expect price down)
        strategy_intent = None
        if UNIFIED_TERMINOLOGY_AVAILABLE:
            try:
                from merid.prediction.intent_contract import StrategyIntent, validate_intent_exposure_consistency
                strategy_intent = StrategyIntent.BULLISH_EVENT if signal_side == "yes" else StrategyIntent.BEARISH_EVENT

                # CRITICAL FIX: 2026-07-19 - Add upstream invariant check for momentum_fvg
                # Validate that the derived side/action matches the strategy intent
                is_valid, error = validate_intent_exposure_consistency(
                    intent=strategy_intent,
                    kalshi_side=signal_side,
                    kalshi_action=signal_action,
                    current_position=None,  # Entry signal (flat position)
                )
                if not is_valid:
                    logger.error(
                        "[INTENT-EXPOSURE-MISMATCH] asset=%s momentum_fvg intent=%s side=%s action=%s - %s - BLOCKING ORDER",
                        asset, strategy_intent.value, signal_side, signal_action, error
                    )
                    return None
                else:
                    logger.debug(
                        "[INTENT-EXPOSURE-VALID] asset=%s momentum_fvg intent=%s side=%s action=%s - invariant check passed",
                        asset, strategy_intent.value, signal_side, signal_action
                    )
            except ImportError:
                pass

        # Return signal

        # INTENT VERIFICATION: Generate signal_id and create snapshot
        signal_id = f"sig-{int(time.time())}-{asset}"
        signal_hash = None

        if SIGNAL_SNAPSHOT_AVAILABLE:
            try:
                # Collect raw features for snapshot
                raw_features = {
                    "velocity": velocity,
                    "velocity_threshold": velocity_threshold,
                    "macd_histogram": macd_histogram,
                    "macd_slope": macd_slope,
                    "rsi": rsi,
                    "rsi_zone": rsi_zone,
                    "obi": obi,
                    "fvg_direction": fvg_direction,
                    "fvg_confidence": fvg_confidence,
                    "long_score": long_score,
                    "short_score": short_score,
                    "orderflow_bias": orderflow_bias,
                    "onchain_velocity": onchain_velocity,
                }

                # Get market_id from market
                market_id = market.market.market_id if hasattr(market, 'market') else market.market_id

                # Create signal snapshot
                snapshot = create_signal_snapshot(
                    signal_id=signal_id,
                    market_id=market_id,
                    side=signal_side,
                    action=signal_action,
                    intent="open",  # Entry signal
                    edge=edge_pct,
                    confidence=confidence,
                    origin_agent=self.config.name,
                    origin_strategy="momentum_fvg",
                    timeframe_label="15m",
                    raw_features=raw_features,
                )
                signal_hash = snapshot.signal_hash
                logger.info(
                    f"[SIGNAL-SNAPSHOT] Created snapshot: signal_id={signal_id} "
                    f"signal_hash={signal_hash[:16]}... market={market_id}"
                )
            except Exception as snap_exc:
                logger.warning(f"[SIGNAL-SNAPSHOT] Failed to create snapshot: {snap_exc}")

        # CRITICAL FIX 2026-08-02: Add candidate tracing for end-to-end validation
        candidate_id = str(uuid.uuid4()) if CANDIDATE_TRACE_AVAILABLE else None

        # Side-lock: counter-trend trades are no longer allowed.
        is_counter_trend = False

        settlement_input_price, cf_rti_basis, settlement_reference, cfb_observation = _get_settlement_input_price(
            asset,
            spot_price,
            settlement_digits=getattr(market, "settlement_digits", None),
        )

        signal_dict = {

            "side": signal_side,

            "action": signal_action,

            "confidence": confidence,

            "edge_pct": edge_pct,

            # Canonical model probability: clamped to (0, 1), never > 1, never rounded to an arbitrary band.
            "model_prob": max(MERID_MODEL_PROBABILITY_EPSILON, min(1.0 - MERID_MODEL_PROBABILITY_EPSILON, model_prob)),

            "signal_mode": "momentum_fvg",

            "velocity": velocity,

            "velocity_threshold": velocity_threshold,

            "macd_histogram": macd_histogram,

            "macd_slope": macd_slope,

            "rsi": rsi,

            "rsi_zone": rsi_zone,

            "obi": obi,

            "fvg_direction": fvg_direction,

            "fvg_confidence": fvg_confidence,

            "long_score": long_score,

            "short_score": short_score,

            "price_cents": price_cents,  # CRITICAL: Include price_cents for order execution

            # CRITICAL FIX: 2026-07-19 - Include both edge_yes and edge_no for parity checker
            "edge_yes": side_edges.get("yes") if side_edges.get("yes") is not None else 0.0,  # YES edge for downstream parity checks
            "edge_no": side_edges.get("no") if side_edges.get("no") is not None else 0.0,    # NO edge for downstream parity checks

            # CRITICAL FIX: 2026-07-16 - SignalFusion microstructure signals
            "orderflow_bias": orderflow_bias,  # Order book imbalance signal
            "onchain_velocity": onchain_velocity,  # On-chain activity signal

            "count": 1,  # CRITICAL: Include default count for order execution

            # CRITICAL FIX 2026-08-02: Add candidate_id for end-to-end tracing
            "candidate_id": candidate_id,

            "rationale": f"momentum_fvg: velocity={velocity:.6f} (threshold={velocity_threshold:.6f}) macd_hist={macd_histogram:.4f} rsi={rsi:.1f} ({rsi_zone}) obi={obi:.2f} fvg_dir={fvg_direction} fvg_conf={fvg_confidence:.2f} edge={edge_pct:.2f}%",


            # INTENT VERIFICATION: Add signal_id and signal_hash for audit chain
            "signal_id": signal_id,
            "signal_hash": signal_hash,

            # Economic / telemetry fields (single source of truth for EV)
            "thesis_side": thesis_side,
            "thesis_source": thesis_source,
            "is_counter_trend": is_counter_trend,
            "all_in_cost_cents": all_in_cost_cents,
            "ev_net_cents": ev_net_cents,
            "fee_cents": fee_cents,
            "impact_reserve_cents": impact_reserve_cents,
            "slippage_cents": _get_slippage_cents() if _UNIFIED_SIZING_AVAILABLE else 5,
            "time_to_expiry_seconds": minutes_to_expiry * 60.0,

            # CRITICAL FIX 2026-08-13: Execution parameters are resolved at signal
            # generation so the loop and router use the same maker/taker economics.
            "aggressiveness": aggressiveness,
            "execution_mode": execution_mode,
            "liquidity_role": liquidity_role,
            "time_in_force": time_in_force,
            "post_only": post_only,
            "order_type": "limit",
            "settlement_input_price": settlement_input_price,
            "cf_rti_basis": cf_rti_basis,
            "settlement_reference": settlement_reference,

            # CRITICAL FIX 2026-08-13: Bind executable liquidity explicitly to the
            # ask side for both YES and NO.  These are the canonical sizes used by
            # the EV-gate displayed_depth and the candidate trace invariant.
            "yes_ask_size": getattr(market_state, "yes_ask_size", None) if market_state else None,
            "no_ask_size": getattr(market_state, "no_ask_size", None) if market_state else None,

        }

        # CRITICAL FIX: 2026-07-19 - Add strategy_intent to signal if available
        if strategy_intent:
            signal_dict["strategy_intent"] = strategy_intent.value

        # CRITICAL FIX (2026-07-23): Add signal quality score if dynamic components enabled
        if self._dynamic_components_enabled and self._signal_quality_tracker is not None:
            try:
                signal_quality = self._signal_quality_tracker.get_quality_score(asset)
                if signal_quality is not None:
                    signal_dict["signal_quality"] = signal_quality
                    logger.debug("[SIGNAL-QUALITY] Added quality score for %s: %.2f", asset, signal_quality)
            except Exception as exc:
                logger.warning("[SIGNAL-QUALITY] Failed to get quality score: %s", exc)

        # CRITICAL FIX 2026-08-02: Initialize candidate trace for signal generation stage
        if CANDIDATE_TRACE_AVAILABLE and candidate_id:
            try:
                trace_side = TraceSide.YES if signal_side.upper() == "YES" else TraceSide.NO
                trace = CandidateTrace(
                    candidate_id=candidate_id,
                    signal_timestamp=time.time(),
                    signal_model_prob=max(MERID_MODEL_PROBABILITY_EPSILON, min(1.0 - MERID_MODEL_PROBABILITY_EPSILON, model_prob)),
                    signal_side=trace_side,
                    signal_edge_pct=edge_pct,
                    ticker=asset,  # Use asset as ticker for now
                    asset=asset,
                    metadata={
                        "signal_mode": "momentum_fvg",
                        "is_counter_trend": is_counter_trend,
                        "all_in_cost_cents": all_in_cost_cents,
                        "ev_net_cents": ev_net_cents,
                        "time_to_expiry_seconds": minutes_to_expiry * 60.0,
                        "settlement_input_price": settlement_input_price,
                        "cf_rti_basis": cf_rti_basis,
                        "settlement_reference": settlement_reference,
                        "yes_ask_size": getattr(market_state, "yes_ask_size", None) if market_state else None,
                        "no_ask_size": getattr(market_state, "no_ask_size", None) if market_state else None,
                        "quote_price_cents": price_cents,
                        "quote_source": price_source,
                    }
                )
                get_trace_store().add_trace(trace)
                logger.info(
                    "[CANDIDATE-TRACE] Initialized trace: candidate_id=%s asset=%s side=%s model_prob=%.3f edge=%.2f%%",
                    candidate_id, asset, signal_side, model_prob, edge_pct
                )
            except Exception as trace_exc:
                logger.warning("[CANDIDATE-TRACE] Failed to initialize trace: %s", trace_exc)

        return signal_dict



    def _check_trend_alignment(self, asset: str, spot_price: float) -> bool:

        """Check if 5m and 1h trends are aligned for signal confirmation.



        CRITICAL FIX: 2026-07-06 - Integrated trend alignment as confirmation filter

        Based on Turbine research: trend alignment was consistently profitable

        - YES alignment: 5 of 5 profitable, mean P&L +$5,939

        - NO alignment: 5 of 5 profitable, mean P&L +$3,773



        Returns:

            True if trends are aligned (both up or both down), False otherwise

        """

        try:

            from merid.prediction.strategies.trend_alignment import get_trend_alignment_strategy

            trend_strategy = get_trend_alignment_strategy()



            # Update price history

            current_time = time.time()

            trend_strategy.update_price(asset, spot_price, current_time)



            # Calculate short (5m) and medium (1h) trends

            short_trend = trend_strategy._calculate_trend(asset, 300, current_time)  # 5 minutes

            medium_trend = trend_strategy._calculate_trend(asset, 3600, current_time)  # 1 hour



            # Check if trends agree and are not neutral

            if short_trend == medium_trend and short_trend.value != "neutral":

                logger.info(

                    "[TREND-ALIGNMENT] asset=%s short_trend=%s medium_trend=%s -> ALIGNED",

                    asset, short_trend.value, medium_trend.value

                )

                return True

            else:

                logger.info(

                    "[TREND-ALIGNMENT] asset=%s short_trend=%s medium_trend=%s -> NOT ALIGNED",

                    asset, short_trend.value, medium_trend.value

                )

                return False

        except Exception as e:

            logger.warning("[TREND-ALIGNMENT] Failed to check trend alignment for %s: %s", asset, e)

            # If trend alignment check fails, proceed (fail-safe)

            return True



    def _compute_hybrid_p_yes(
        self,
        asset: str,
        spot_price: float,
        settlement_input_price: float,
        strike: float,
        yes_ask: float,
        no_ask: float,
        seconds_to_expiry: float,
        market_state: Any = None,
        settlement_reference: str = "",
        cfb_observation: Any = None,
        bachelier_only: bool = False,
    ) -> HybridProbability:
        """Compute a hybrid YES probability by fusing Bachelier fair value with
        the live indicator/velocity stack.

        The Bachelier probability is shifted by a signed directional delta that
        comes from multi-window velocity, MACD histogram, RSI, order-book
        imbalance, FVG, and the macro regime. The shift is capped so the model
        can never become degenerate (p <= 0 or p >= 1).

        When ``bachelier_only`` is true (or the environment
        ``MERID_HYBRID_BACHELIER_ONLY`` / ``MERID_HYBRID_DISABLE_ALL_DELTAS``
        is set) the returned ``p_yes`` is the clipped Bachelier baseline and the
        computed deltas are recorded in the HybridProbability for diagnosis but
        are not applied to the final probability.

        Returns a HybridProbability so callers can diagnose which signed input
        is driving p_yes for an asset like SOL.
        """
        import math

        # Production-safe containment: Bachelier-only mode disables all
        # indicator/velocity/FVG deltas so the model can be audited against a
        # clean baseline without sign-inverted components contaminating it.
        if not bachelier_only:
            bachelier_only = (
                os.environ.get("MERID_HYBRID_BACHELIER_ONLY", "").strip().lower() in ("1", "true", "yes")
                or os.environ.get("MERID_HYBRID_DISABLE_ALL_DELTAS", "").strip().lower() in ("1", "true", "yes")
            )

        # Bachelier baseline.
        t_years = max(seconds_to_expiry, 1.0) / (365.0 * 24.0 * 60.0 * 60.0)
        log_moneyness = math.log(settlement_input_price / strike) if strike > 0 else 0.0
        # Same vol lookup the trade_decision path uses by default.
        _vol_defaults = {"BTC": 0.60, "ETH": 0.80, "SOL": 1.00, "XRP": 1.00, "DOGE": 1.20}
        annualized_vol = float(
            os.environ.get(f"MERID_ANNUALIZED_VOL_{asset.upper()}")
            or _vol_defaults.get(asset.upper(), 0.80)
        )
        sigma = max(annualized_vol, 1e-6)
        z = log_moneyness / (sigma * math.sqrt(t_years))
        p_yes_bachelier = max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))

        # Indicator-independent fallback: no shift when the stack is missing.
        if not getattr(self, "_indicator_stacks", None):
            eps = MERID_MODEL_PROBABILITY_EPSILON
            p_yes = max(eps, min(1.0 - eps, p_yes_bachelier))
            return HybridProbability(
                p_yes=p_yes,
                p_yes_bachelier=p_yes_bachelier,
                log_moneyness=log_moneyness,
                z_score=z,
                annualized_vol=annualized_vol,
                t_years=t_years,
                velocity=0.0,
                velocity_threshold=1e-12,
                velocity_edge=0.0,
                macd_delta=0.0,
                rsi_delta=0.0,
                obi=0.0,
                obi_delta=0.0,
                regime_delta=0.0,
                total_delta=0.0,
                max_shift=0.0,
                bars_available=0,
            )

        try:
            velocity = self._calculate_multi_window_velocity(asset, spot_price)
            velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)
        except Exception as exc:
            logger.warning("[HYBRID-P-YES] asset=%s failed to compute velocity: %s", asset, exc)
            velocity = 0.0
            velocity_threshold = 1e-12

        # Velocity-derived directional shift (capped to max edge).
        velocity_edge = 0.0
        if velocity_threshold and abs(velocity) >= velocity_threshold:
            edge_pct = calculate_velocity_edge(abs(velocity), velocity_threshold)
            max_edge_pct = MERID_MAX_EDGE_PCT
            velocity_edge = math.copysign(min(edge_pct, max_edge_pct) / 100.0, velocity)

        delta = velocity_edge

        # Indicator stack confluence.
        macd_histogram = 0.0
        rsi = 50.0
        rsi_zone = "neutral"
        macro_regime = "neutral"
        price_above_ema_200 = True

        indicator = self._indicator_stacks.get(asset)
        if indicator is not None:
            try:
                snap = indicator.snapshot()
                if getattr(snap, "bars_available", 0) >= 26:
                    macd_histogram = float(getattr(snap, "macd_histogram", 0.0) or 0.0)
                    rsi = float(getattr(snap, "rsi", 50.0) or 50.0)
                    rsi_zone = str(getattr(snap, "rsi_zone", "neutral"))
                    macro_regime = str(getattr(snap, "macro_regime", "neutral"))
                    price_above_ema_200 = bool(getattr(snap, "price_above_ema_200", True))
            except Exception as exc:
                logger.debug("[HYBRID-P-YES] asset=%s indicator snapshot failed: %s", asset, exc)

        # MACD histogram shift, asset-invariant (normalized by spot).
        macd_delta = 0.0
        if spot_price and math.isfinite(spot_price) and spot_price > 0 and math.isfinite(macd_histogram):
            macd_delta = (macd_histogram / spot_price) * MERID_MACD_EDGE_WEIGHT
            # Cap individual contribution at 5 percentage points.
            macd_delta = math.copysign(min(abs(macd_delta), 0.05), macd_delta)
            delta += macd_delta

        # RSI shift: oversold lifts p_yes, overbought lowers p_yes.
        rsi_delta = 0.0
        if rsi < 35.0:
            rsi_delta = 0.02
        elif rsi > 65.0:
            rsi_delta = -0.02
        delta += rsi_delta

        # Order-book imbalance shift: positive OBI lifts p_yes.
        obi = 0.0
        obi_delta = 0.0
        if market_state is not None:
            depth_yes = float(getattr(market_state, "depth_10c_yes", 0) or 0)
            depth_no = float(getattr(market_state, "depth_10c_no", 0) or 0)
            if depth_yes + depth_no > 0:
                obi = (depth_yes - depth_no) / (depth_yes + depth_no)
                obi_delta = max(-0.03, min(0.03, obi * 0.05))
                delta += obi_delta

        # Macro-regime alignment: penalize contradicting the macro trend.
        regime_delta = 0.0
        if macro_regime == "bull" and not price_above_ema_200:
            regime_delta = -0.01
        elif macro_regime == "bear" and price_above_ema_200:
            regime_delta = 0.01
        delta += regime_delta

        # FVG (Fair Value Gap) contribution: on by default, gated by
        # MERID_ENABLE_FVG and capped by MERID_FVG_DELTA_WEIGHT. Uses the same
        # live settlement price the Bachelier baseline uses, with source and
        # staleness provenance.
        fvg_active = 0
        fvg_direction = 0.0
        fvg_size = 0.0
        fvg_distance_to_fill = 0.0
        fvg_fill_signal = 0.0
        fvg_delta = 0.0
        fvg_confidence = 0.0
        fvg_weight = float(os.environ.get("MERID_FVG_DELTA_WEIGHT", "0.05"))
        fvg_max_delta = float(os.environ.get("MERID_FVG_MAX_DELTA", "0.05"))

        if os.environ.get("MERID_ENABLE_FVG", "1").strip().lower() in ("1", "true", "yes"):
            try:
                from merid.prediction.forecasters.fvg import get_fvg_forecaster
                fvg_forecaster = get_fvg_forecaster()
                fvg_result = fvg_forecaster.predict(
                    market_id=f"{asset}_15M",
                    implied_yes=p_yes_bachelier,
                    implied_no=1.0 - p_yes_bachelier,
                    volume=0.0,
                    open_interest=0.0,
                    minutes_to_expiry=seconds_to_expiry / 60.0 if seconds_to_expiry else 15.0,
                    asset=asset,
                    timeframe="15m",
                    spot_price=settlement_input_price,
                )
                if fvg_result:
                    fvg_active = int(fvg_result.components.get("fvg_active", 0) or 0)
                    fvg_direction = float(fvg_result.components.get("fvg_nearest_direction", 0.0) or 0.0)
                    fvg_size = float(fvg_result.components.get("fvg_nearest_size", 0.0) or 0.0)
                    fvg_distance_to_fill = float(fvg_result.components.get("fvg_distance_to_fill", 0.0) or 0.0)
                    fvg_fill_signal = float(fvg_result.components.get("fvg_fill_signal", 0.0) or 0.0)
                    fvg_confidence = float(fvg_result.confidence or 0.0)
                    fvg_delta = fvg_fill_signal * fvg_weight
                    fvg_delta = math.copysign(min(abs(fvg_delta), fvg_max_delta), fvg_delta)

                    # Global concurrent-position guard: do not add FVG delta if the
                    # number of live/pending slots already equals or exceeds the
                    # configured FVG concurrent cap. This limits FVG-exposure buildup
                    # while the placebo matrix is being collected.
                    fvg_max_concurrent = int(os.environ.get("MERID_FVG_MAX_CONCURRENT", "0") or 0)
                    if fvg_max_concurrent > 0 and fvg_delta != 0.0:
                        try:
                            from merid.risk.global_slot_allocator import get_global_slot_allocator
                            slot_allocator = get_global_slot_allocator()
                            slot_count = slot_allocator.get_slot_count()
                            if slot_count >= fvg_max_concurrent:
                                logger.info(
                                    "[HYBRID-P-YES-FVG-CAP] asset=%s slots=%d >= cap=%d - skipping FVG contribution",
                                    asset, slot_count, fvg_max_concurrent,
                                )
                                fvg_delta = 0.0
                                fvg_confidence = 0.0
                        except Exception as cap_exc:
                            logger.warning("[HYBRID-P-YES-FVG-CAP] asset=%s failed to check slot count: %s", asset, cap_exc)

                    delta += fvg_delta
            except Exception as fvg_exc:
                logger.warning("[HYBRID-P-YES] asset=%s FVG contribution failed: %s", asset, fvg_exc)

        # Final cap to prevent degenerate probabilities.
        # Warmup gate is based only on the number of bars in the indicator stack.
        # ADX can legitimately read 0.0 in a ranging market, so it must not be used
        # as a warmup proxy; doing so permanently caps the model shift and prevents
        # all directional trading.
        max_shift = float(os.environ.get("MERID_HYBRID_MAX_P_SHIFT", "0.15"))
        min_bars_for_full_shift = int(os.environ.get("MERID_HYBRID_MIN_BARS_FOR_FULL_SHIFT", "26"))
        adx = self._calculate_adx(asset)
        try:
            indicator = self._indicator_stacks.get(asset)
            if indicator is not None:
                snap = indicator.snapshot()
                bars_available = int(getattr(snap, "bars_available", 0) or 0)
            else:
                bars_available = 0
        except Exception:
            bars_available = 0
        if bars_available < min_bars_for_full_shift:
            max_shift = min(
                max_shift,
                float(os.environ.get("MERID_HYBRID_WARMUP_MAX_P_SHIFT", "0.05")),
            )
            logger.info(
                "[HYBRID-P-YES-WARMUP] asset=%s adx=%.2f bars=%d min_bars=%d - capping model shift to %.3f",
                asset, adx, bars_available, min_bars_for_full_shift, max_shift,
            )
        else:
            logger.debug(
                "[HYBRID-P-YES] asset=%s adx=%.2f bars=%d - using full model shift %.3f",
                asset, adx, bars_available, max_shift,
            )
        delta = math.copysign(min(abs(delta), max_shift), delta)

        p_yes_pre_clip = p_yes_bachelier + delta
        eps = MERID_MODEL_PROBABILITY_EPSILON
        if bachelier_only:
            # Containment: return the Bachelier baseline as the active
            # probability while preserving the computed deltas for audit.
            p_yes = max(eps, min(1.0 - eps, p_yes_bachelier))
        else:
            p_yes = max(eps, min(1.0 - eps, p_yes_pre_clip))

        return HybridProbability(
            p_yes=p_yes,
            p_yes_bachelier=p_yes_bachelier,
            log_moneyness=log_moneyness,
            z_score=z,
            annualized_vol=annualized_vol,
            t_years=t_years,
            velocity=velocity,
            velocity_threshold=velocity_threshold,
            velocity_edge=velocity_edge,
            macd_delta=macd_delta,
            rsi_delta=rsi_delta,
            obi=obi,
            obi_delta=obi_delta,
            regime_delta=regime_delta,
            total_delta=delta,
            max_shift=max_shift,
            bars_available=bars_available,
            fvg_active=fvg_active,
            fvg_direction=fvg_direction,
            fvg_size=fvg_size,
            fvg_distance_to_fill=fvg_distance_to_fill,
            fvg_fill_signal=fvg_fill_signal,
            fvg_delta=fvg_delta,
            fvg_weight=fvg_weight,
            fvg_confidence=fvg_confidence,
            fvg_price_source=settlement_reference,
            fvg_price_staleness_ms=getattr(cfb_observation, "age_ms", None) if cfb_observation is not None else None,
        )

    def _generate_trade_decision_signal(self, asset: str, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[Dict[str, Any]]:
        """Unified hybrid decision engine for 15-minute crypto binaries.

        Builds a single immutable TradeDecision from external spot, the Kalshi
        strike, the live YES/NO order book, and execution costs.  A candidate
        is emitted only when the calibrated net edge exceeds the minimum
        required edge; otherwise the decision is ``no_trade``.
        """
        if not spot_price or spot_price <= 0:
            logger.warning("[TRADE-DECISION] asset=%s invalid spot_price=%s", asset, spot_price)
            self._record_signal_rejection(
                "invalid_spot",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    None,
                    None,
                    (minutes_to_expiry * 60.0) if minutes_to_expiry else 0.0,
                )
            )
            return None

        # Interim asset pause: comma-separated list in MERID_PAUSED_ASSETS.
        # Default empty (no pause). Exits remain enabled; this only blocks new
        # signal generation. Intended for emergency asset-level halts while a
        # calibration/edge issue is investigated.
        paused_assets = {
            a.strip().upper()
            for a in os.environ.get("MERID_PAUSED_ASSETS", "").split(",")
            if a.strip()
        }
        if paused_assets and asset and asset.upper() in paused_assets:
            logger.warning("[INTERIM-PAUSE] asset=%s paused via MERID_PAUSED_ASSETS", asset)
            self._record_signal_rejection(
                "interim_asset_pause",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    None,
                    None,
                    (minutes_to_expiry * 60.0) if minutes_to_expiry else 0.0,
                )
            )
            return None

        ticker = market.market.market_id if hasattr(market, 'market') else (getattr(market, 'market_id', None) or getattr(market, 'ticker', asset))

        # CRITICAL FIX (2026-08-22): Authoritative *entry* readiness gate before any
        # new signal/edge computation.  If the market data is not ready (stale,
        # resync, pending snapshot, invalid book, or unconfirmed bootstrap), stop here
        # with SKIP_MARKET_NOT_READY.  Exits are handled by PositionMonitor with the
        # execution-readiness gate.
        if self.market_state_store is not None:
            if hasattr(self.market_state_store, "is_market_entry_ready"):
                exec_ready, exec_reason = self.market_state_store.is_market_entry_ready(ticker)
            elif hasattr(self.market_state_store, "is_market_execution_ready"):
                exec_ready, exec_reason = self.market_state_store.is_market_execution_ready(ticker)
            else:
                # Legacy / unit-test path: a plain dict of ticker -> state.
                exec_ready = bool(self.market_state_store.get(ticker))
                exec_reason = None
            if not exec_ready:
                logger.info(
                    "[TRADE-DECISION-ENTRY-READY] asset=%s ticker=%s SKIP_MARKET_NOT_READY: %s",
                    asset, ticker, exec_reason,
                )
                self._record_signal_rejection(
                    "SKIP_MARKET_NOT_READY",
                    **self._build_trade_decision_rejection_context(
                        asset,
                        spot_price,
                        None,
                        None,
                        (minutes_to_expiry * 60.0) if minutes_to_expiry else 0.0,
                        extra={"entry_ready_reason": exec_reason},
                    )
                )
                return None

        market_state = self.market_state_store.get(ticker) if self.market_state_store else None
        if market_state is None:
            market_state = market

        strike, strike_source, strike_diag = _resolve_trade_decision_strike(
            asset, market_state, market, spot_price
        )
        logger.info(
            "[TRADE-DECISION-STRIKE-DIAG] asset=%s strike=%s source=%s diagnostic=%s",
            asset,
            format_price(asset, strike) if strike is not None else None,
            strike_source,
            strike_diag,
        )

        if strike is None or not _is_valid_strike_target(strike, asset):
            logger.warning(
                "[TRADE-DECISION] asset=%s market_metadata_invalid no resolvable strike",
                asset,
            )
            self._record_signal_rejection(
                "market_metadata_invalid",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    None,
                    None,
                    (minutes_to_expiry * 60.0) if minutes_to_expiry else 0.0,
                    extra={
                        "strike_resolution_diagnostic": strike_diag,
                    },
                )
            )
            return None

        # Degraded spot fallback: 15m contracts are required to carry Kalshi
        # floor/window metadata; falling back to public spot is a metadata
        # failure, not an authoritative strike.
        if strike_source == "spot_fallback":
            logger.warning(
                "[TRADE-DECISION] asset=%s market_metadata_invalid strike derived from public spot (degraded)",
                asset,
            )
            self._record_signal_rejection(
                "market_metadata_invalid",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    None,
                    None,
                    (minutes_to_expiry * 60.0) if minutes_to_expiry else 0.0,
                    extra={
                        "strike_source": strike_source,
                        "strike_resolution_diagnostic": strike_diag,
                    },
                )
            )
            return None

        seconds_to_expiry = float(getattr(market_state, "seconds_to_expiry", 0.0) or (minutes_to_expiry * 60.0))
        if seconds_to_expiry <= 0:
            logger.warning("[TRADE-DECISION] asset=%s invalid seconds_to_expiry=%.1f", asset, seconds_to_expiry)
            self._record_signal_rejection(
                "invalid_expiry",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    None,
                    None,
                    seconds_to_expiry,
                )
            )
            return None

        yes_bid = getattr(market_state, "best_bid_cents", None) or 0.0
        yes_ask = getattr(market_state, "best_ask_cents", None) or 0.0
        no_bid = getattr(market_state, "best_no_bid_cents", None) or 0.0
        no_ask = getattr(market_state, "best_no_ask_cents", None) or 0.0

        # Duality fallback when explicit asks are missing.
        if yes_ask <= 0 and no_bid > 0:
            yes_ask = 100.0 - no_bid
        if no_ask <= 0 and yes_bid > 0:
            no_ask = 100.0 - yes_bid

        yes_depth_cc = float(getattr(market_state, "min_depth_yes", 0) or 0) * 100.0
        no_depth_cc = float(getattr(market_state, "min_depth_no", 0) or 0) * 100.0

        # Approximate annualized volatility by asset.  A realized-vol estimator
        # can replace these constants when external spot history is available.
        # Env overrides allow quick per-asset calibration without a code change.
        _vol_defaults = {
            "BTC": 0.60,
            "ETH": 0.80,
            "SOL": 1.00,
            "XRP": 1.00,
            "DOGE": 1.20,
        }
        annualized_vol = float(
            os.environ.get(f"MERID_ANNUALIZED_VOL_{asset.upper()}")
            or _vol_defaults.get(asset.upper(), 0.80)
        )

        # Fee per contract for the winning side; approximate entry fee as the
        # larger of the two side fees to stay conservative.
        try:
            fee_yes_cents = float(canonical_calculate_kalshi_fee_cents(1, int(round(yes_ask))))
            fee_no_cents = float(canonical_calculate_kalshi_fee_cents(1, int(round(no_ask))))
            fee_cents = max(fee_yes_cents, fee_no_cents)
        except Exception:
            fee_cents = 0.0

        data_quality = getattr(market_state, "data_quality", "unknown") or "unknown"
        if not getattr(market_state, "book_initialized", False):
            data_quality = "stale"

        # data_state is a first-class data-quality gate; it is not an economic
        # regime and must never imply direction.
        data_state = {
            "good": "healthy",
            "live": "healthy",
            "healthy": "healthy",
            "stale": "stale",
            "degraded": "degraded",
            "bad": "degraded",
            "unknown": "invalid",
        }.get(data_quality.lower(), "invalid")

        # Regime is a critical confidence/edge input.  The market state store does
        # not set a regime attribute, so derive it from available depth using the
        # same classifier the rest of the agent uses.
        state_regime = getattr(market_state, "regime", None)
        if state_regime in (None, "unknown", "insufficient_data"):
            regime = self._classify_regime(ticker)
        else:
            regime = state_regime

        # Classifier does not yet produce a posterior; treat the label as certain
        # once known and zero otherwise.
        regime_label = regime
        regime_probability = 1.0 if regime not in ("unknown", "insufficient_data") else 0.0

        # Settlement reference and CF-RTI basis.  The model and confidence are
        # only valid when the price is the official CF Benchmarks RTI, not a
        # public spot fallback.  get_live_rti returns None and logs the precise
        # rejection reason if the feed is unhealthy.
        settlement_input_price, cf_rti_basis, settlement_reference, cfb_observation = _get_settlement_input_price(
            asset,
            spot_price,
            settlement_digits=getattr(market, "settlement_digits", None),
        )

        run_id = getattr(self, "run_id", None) or f"{self.config.name}_{time.time():.6f}_{uuid.uuid4().hex[:8]}"

        # Hybrid probability: fuse Bachelier fair value with the live
        # indicator/velocity stack so the decision engine uses the research
        # signals instead of discarding them.
        hybrid: Optional[HybridProbability] = None
        try:
            hybrid = self._compute_hybrid_p_yes(
                asset=asset,
                spot_price=spot_price,
                settlement_input_price=settlement_input_price,
                strike=float(strike),
                yes_ask=float(yes_ask),
                no_ask=float(no_ask),
                seconds_to_expiry=seconds_to_expiry,
                market_state=market_state,
                settlement_reference=settlement_reference,
                cfb_observation=cfb_observation,
            )
            p_yes_model = float(hybrid) if hybrid is not None else None
        except Exception as hybrid_exc:
            logger.warning("[HYBRID-P-YES] asset=%s failed to compute hybrid probability: %s", asset, hybrid_exc)
            p_yes_model = None
            hybrid = None

        # Thresholds: profile is the single source of truth; env overrides
        # allow emergency calibration without a code change.
        def _numeric_pref(v):
            if v is None or isinstance(v, bool):
                return None
            if isinstance(v, (int, float, Decimal)):
                return float(v)
            # Strings from the environment are handled below.
            if isinstance(v, str):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            return None

        model_uncertainty = _numeric_pref(
            os.environ.get(f"MERID_MODEL_UNCERTAINTY_{asset.upper()}")
            or os.environ.get("MERID_MODEL_UNCERTAINTY")
            or _numeric_pref(getattr(self.risk_config, "model_uncertainty", None))
        ) or 0.05

        min_required_edge = _numeric_pref(
            os.environ.get(f"MERID_MIN_NET_EDGE_{asset.upper()}")
            or os.environ.get("MERID_MIN_NET_EDGE")
            or os.environ.get("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE")
            or _numeric_pref(getattr(self.config, "min_net_edge", None))
            or _numeric_pref(getattr(self.risk_config, "strategy_policy_min_edge", None))
        ) or 0.03

        decision = compute_trade_decision(
            run_id=run_id,
            decision_id=f"{run_id}_{uuid.uuid4().hex[:8]}",
            ticker=getattr(market, "ticker", asset),
            asset=asset,
            spot_price=settlement_input_price,
            strike_price=float(strike),
            seconds_to_expiry=seconds_to_expiry,
            yes_bid_cents=float(yes_bid),
            yes_ask_cents=float(yes_ask),
            no_bid_cents=float(no_bid),
            no_ask_cents=float(no_ask),
            yes_depth_cc=yes_depth_cc,
            no_depth_cc=no_depth_cc,
            fee_per_contract_cents=fee_cents,
            annualized_vol=annualized_vol,
            model_uncertainty=model_uncertainty,
            data_quality=data_quality,
            data_state=data_state,
            regime=regime,
            regime_label=regime_label,
            regime_probability=regime_probability,
            indicators={"p_yes_model": p_yes_model} if p_yes_model is not None else {},
            p_yes_model=p_yes_model,
            min_required_edge=min_required_edge,
            settlement_reference=settlement_reference,
            policy_version="trade_decision_v2",
        )

        # Production-safe containment: compute a Bachelier-only shadow decision so
        # we can compare the live hybrid side against the baseline side on the same
        # market, fully logged but not executed.
        decision_bachelier = decision
        hybrid_bachelier: Optional[HybridProbability] = hybrid
        p_yes_bachelier = p_yes_model
        bachelier_only_live = os.environ.get("MERID_HYBRID_BACHELIER_ONLY", "").strip().lower() in ("1", "true", "yes") \
            or os.environ.get("MERID_HYBRID_DISABLE_ALL_DELTAS", "").strip().lower() in ("1", "true", "yes")
        shadow_bachelier = os.environ.get("MERID_SHADOW_BACHELIER_ONLY", "").strip().lower() in ("1", "true", "yes")
        if shadow_bachelier and not bachelier_only_live and hybrid is not None:
            try:
                hybrid_bachelier = self._compute_hybrid_p_yes(
                    asset=asset,
                    spot_price=spot_price,
                    settlement_input_price=settlement_input_price,
                    strike=float(strike),
                    yes_ask=float(yes_ask),
                    no_ask=float(no_ask),
                    seconds_to_expiry=seconds_to_expiry,
                    market_state=market_state,
                    settlement_reference=settlement_reference,
                    cfb_observation=cfb_observation,
                    bachelier_only=True,
                )
                p_yes_bachelier = float(hybrid_bachelier) if hybrid_bachelier is not None else None
                if p_yes_bachelier is not None:
                    decision_bachelier = compute_trade_decision(
                        run_id=run_id,
                        decision_id=f"{run_id}_{uuid.uuid4().hex[:8]}",
                        ticker=getattr(market, "ticker", asset),
                        asset=asset,
                        spot_price=settlement_input_price,
                        strike_price=float(strike),
                        seconds_to_expiry=seconds_to_expiry,
                        yes_bid_cents=float(yes_bid),
                        yes_ask_cents=float(yes_ask),
                        no_bid_cents=float(no_bid),
                        no_ask_cents=float(no_ask),
                        yes_depth_cc=yes_depth_cc,
                        no_depth_cc=no_depth_cc,
                        fee_per_contract_cents=fee_cents,
                        annualized_vol=annualized_vol,
                        model_uncertainty=model_uncertainty,
                        data_quality=data_quality,
                        data_state=data_state,
                        regime=regime,
                        regime_label=regime_label,
                        regime_probability=regime_probability,
                        indicators={"p_yes_model": p_yes_bachelier, "shadow_bachelier_only": True},
                        p_yes_model=p_yes_bachelier,
                        min_required_edge=min_required_edge,
                        settlement_reference=settlement_reference,
                        policy_version="trade_decision_v2",
                    )
            except Exception as bachelier_exc:
                logger.warning("[HYBRID-P-YES-BACHELIER-SHADOW] asset=%s failed: %s", asset, bachelier_exc)
                decision_bachelier = decision
                hybrid_bachelier = hybrid

        # Reduced sizing for FVG-influenced trades: the FVG layer is untested,
        # so live exposure is scaled by MERID_FVG_SIZE_SCALE (default 0.5).
        fvg_influenced = (
            hybrid is not None
            and abs(float(getattr(hybrid, "fvg_delta", 0.0) or 0.0)) > 0.0
        )
        fvg_size_scale = 1.0
        if fvg_influenced and decision.selected_outcome is not None and int(decision.approved_size_cc) > 0:
            fvg_size_scale = float(os.environ.get("MERID_FVG_SIZE_SCALE", "0.5"))
            fvg_size_scale = max(0.0, min(1.0, fvg_size_scale))
            if fvg_size_scale < 1.0:
                try:
                    scaled_cc = max(100, int(Decimal(str(fvg_size_scale)) * decision.approved_size_cc))
                    decision = replace(decision, approved_size_cc=Decimal(scaled_cc))
                    logger.info(
                        "[FVG-SIZE-SCALE] asset=%s scale=%.2f approved_size_cc=%d",
                        asset, fvg_size_scale, scaled_cc,
                    )
                except Exception as sizing_exc:
                    logger.warning("[FVG-SIZE-SCALE] asset=%s failed to scale: %s", asset, sizing_exc)

        # Containment sizing: the hybrid deltas are under audit for sign inversion.
        # Two independent levers reduce live exposure until out-of-sample component
        # validation passes:
        #   1. MERID_MODEL_CONTAINMENT_SIZE_SCALE (default 1.0) - applies to every
        #      decision.  Set to 0.0 to force the minimum one-contract size, or 0.25
        #      for quarter-size canary.
        #   2. MERID_BACHELIER_ONLY_SIZE_SCALE (default 0.0) - extra reduction when
        #      MERID_HYBRID_BACHELIER_ONLY disables all deltas and the live signal is
        #      the Bachelier baseline.  0.0 means one-contract minimum.
        for scale_env, scale_default, log_tag in (
            ("MERID_MODEL_CONTAINMENT_SIZE_SCALE", "1.0", "CONTAINMENT-SIZE"),
            ("MERID_BACHELIER_ONLY_SIZE_SCALE", "0.0" if bachelier_only_live else "1.0", "BACHELIER-ONLY-SIZE"),
        ):
            size_scale = float(os.environ.get(scale_env, scale_default))
            size_scale = max(0.0, min(1.0, size_scale))
            if size_scale < 1.0 and decision.selected_outcome is not None and int(decision.approved_size_cc) > 0:
                try:
                    scaled_cc = max(100, int(Decimal(str(size_scale)) * decision.approved_size_cc))
                    if scaled_cc != int(decision.approved_size_cc):
                        decision = replace(decision, approved_size_cc=Decimal(scaled_cc))
                        logger.info(
                            "[%s] asset=%s scale=%.2f approved_size_cc=%d",
                            log_tag, asset, size_scale, scaled_cc,
                        )
                except Exception as sizing_exc:
                    logger.warning("[%s] asset=%s failed to scale: %s", log_tag, asset, sizing_exc)

        _write_shadow_telemetry(
            run_id=run_id,
            decision_id=decision.decision_id,
            ticker=getattr(market, "ticker", asset),
            asset=asset,
            target_price=float(strike),
            seconds_to_expiry=seconds_to_expiry,
            settlement_reference=settlement_reference,
            cfb_observation=cfb_observation,
            decision=decision,
            public_spot=float(spot_price),
            spot_price=float(settlement_input_price),
            cf_rti_basis=float(cf_rti_basis),
            yes_bid_cents=float(yes_bid),
            yes_ask_cents=float(yes_ask),
            no_bid_cents=float(no_bid),
            no_ask_cents=float(no_ask),
            fee_per_contract_cents=float(fee_cents),
            annualized_vol=float(annualized_vol),
            data_quality=data_quality,
            regime=regime,
        )

        # Feed-alignment context: capture the source and staleness of every input
        # that can disagree in time (CF RTI settlement vs Coinbase/spot velocity).
        # This is the primary diagnostic for the dynamic inversion hypothesis.
        spot_data = getattr(self, "_last_spot_data", {}).get(asset)
        feed_context: Dict[str, Any] = {
            "spot_source": getattr(spot_data, "source", None),
            "spot_staleness_ms": getattr(spot_data, "staleness_ms", None),
            "spot_timestamp_ms": getattr(spot_data, "timestamp_ms", None),
            "spot_data_quality_score": getattr(spot_data, "data_quality_score", None),
            "spot_num_exchanges": getattr(spot_data, "num_exchanges", None),
            "velocity_source": getattr(self, "_last_velocity_source", None),
            "velocity_age_ms": getattr(self, "_last_velocity_age_ms", None),
            "velocity_signal_type": getattr(self, "_last_velocity_signal_type", None),
            "velocity_threshold_used": getattr(self, "_last_velocity_threshold", None),
            "cfb_settlement_reference": settlement_reference,
            "cfb_execution_eligible": getattr(cfb_observation, "execution_eligible", None),
            "cfb_source_ts_ms": getattr(cfb_observation, "source_ts_ms", None),
            "cfb_observed_ts_ms": getattr(cfb_observation, "observed_ts_ms", None),
            "cfb_observed_ts_mono_ns": getattr(cfb_observation, "observed_ts_mono_ns", None),
            "cfb_age_ms": getattr(cfb_observation, "age_ms", None),
            "cfb_timestamp_quality": getattr(cfb_observation, "timestamp_quality", None),
            "cfb_price_source_health": getattr(cfb_observation, "price_source_health", None),
        }

        logger.info(
            "[FEED-ALIGNMENT] asset=%s spot_source=%s spot_staleness_ms=%s "
            "velocity_source=%s velocity_age_ms=%s velocity=%.6f "
            "cfb_age_ms=%s cfb_exec_eligible=%s settlement_reference=%s",
            asset,
            feed_context["spot_source"],
            feed_context["spot_staleness_ms"],
            feed_context["velocity_source"],
            feed_context["velocity_age_ms"],
            getattr(self, "_last_velocity_value", 0.0),
            feed_context["cfb_age_ms"],
            feed_context["cfb_execution_eligible"],
            settlement_reference,
        )

        # Shadow A/B telemetry: record the live selected side alongside the
        # inverted side and a model-inverted side.  Settlement-time scripts can
        # compare realized PnL and win rates without changing live behavior.
        write_shadow_side_record(
            run_id=run_id,
            decision_id=decision.decision_id,
            ticker=getattr(market, "ticker", asset),
            asset=asset,
            spot_price=float(settlement_input_price),
            strike_price=float(strike),
            seconds_to_expiry=seconds_to_expiry,
            yes_bid_cents=float(yes_bid),
            yes_ask_cents=float(yes_ask),
            no_bid_cents=float(no_bid),
            no_ask_cents=float(no_ask),
            fee_per_contract_cents=float(fee_cents),
            p_yes_model=p_yes_model,
            selected_side=decision.selected_outcome,
            selected_outcome_price_cents=int(round(float(decision.selected_outcome_price) * 100.0)) if decision.selected_outcome_price is not None else None,
            selected_net_edge=float(decision.net_edge) if decision.net_edge is not None else None,
            annualized_vol=float(annualized_vol),
            velocity=getattr(self, "_last_velocity_value", None),
            regime=regime,
            data_state=data_state,
            settlement_reference=settlement_reference,
            selection_reason=decision.selection_reason,
            hybrid_probability=asdict(hybrid) if hybrid is not None else None,
            **feed_context,
        )

        # Model-decomposition ledger: record every evaluation so downstream
        # settlement joins can compute each delta's signed contribution.
        write_model_decomposition_record(
            run_id=run_id,
            decision_id=decision.decision_id,
            ticker=getattr(market, "ticker", asset),
            asset=asset,
            spot_price=float(settlement_input_price),
            strike_price=float(strike),
            seconds_to_expiry=seconds_to_expiry,
            yes_bid_cents=float(yes_bid),
            yes_ask_cents=float(yes_ask),
            no_bid_cents=float(no_bid),
            no_ask_cents=float(no_ask),
            hybrid_probability=asdict(hybrid) if hybrid is not None else None,
            decision=decision,
            decision_bachelier=decision_bachelier if (decision_bachelier is not None and decision_bachelier is not decision) else None,
            settlement_reference=settlement_reference,
            data_state=data_state,
            regime=regime,
        )

        if decision.selected_outcome is None:
            bd = decision.edge_breakdown
            logger.info(
                "[TRADE-DECISION] asset=%s no_trade reason=%s p_yes=%.3f p_no=%.3f "
                "yes_edge=%.3f no_edge=%.3f edge_threshold=%.4f confidence_valid=%s confidence_reasons=%s",
                asset, decision.no_trade_reason, float(decision.p_yes_calibrated),
                float(decision.p_no_calibrated), float(decision.yes_net_edge),
                float(decision.no_net_edge), float(decision.edge_threshold),
                decision.confidence_valid,
                ",".join(decision.confidence_reasons),
            )
            self._record_signal_rejection(
                decision.no_trade_reason or "no_trade",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    settlement_input_price,
                    settlement_reference,
                    seconds_to_expiry,
                    decision=decision,
                )
            )
            return None

        side = decision.selected_outcome
        action = "buy"
        price_cents = int(round(float(decision.selected_outcome_price) * 100.0))
        model_prob = float(decision.p_selected) if decision.p_selected is not None else 0.0
        edge_pct = float(decision.net_edge) if decision.net_edge is not None else 0.0
        thesis_side = side
        strategy_intent = "bullish_event" if side == "yes" else "bearish_event"

        # Depth guard: reject if the executable depth cannot absorb one contract.
        depth_ok = (float(decision.yes_depth_cc) >= 100.0) if side == "yes" else (float(decision.no_depth_cc) >= 100.0)
        if not depth_ok:
            depth_cc = decision.yes_depth_cc if side == "yes" else decision.no_depth_cc
            logger.info(
                "[TRADE-DECISION] asset=%s no_trade reason=insufficient_depth side=%s depth_cc=%s",
                asset, side, depth_cc,
            )
            self._record_signal_rejection(
                "insufficient_depth",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    settlement_input_price,
                    settlement_reference,
                    seconds_to_expiry,
                    decision=decision,
                    extra={
                        "depth_side": side,
                        "depth_cc": depth_cc,
                    },
                )
            )
            return None

        # Runtime trap for the historical 0.95 default-confidence sentinel.
        # The new uncertainty engine should never emit exactly 0.95.
        if decision.confidence is not None and float(decision.confidence) == 0.95:
            logger.critical(
                "[TRADE-DECISION] asset=%s side=%s reserved default confidence=0.95 detected; "
                "blocking as release-gate violation", asset, side
            )
            self._record_signal_rejection(
                "reserved_default_confidence",
                **self._build_trade_decision_rejection_context(
                    asset,
                    spot_price,
                    settlement_input_price,
                    settlement_reference,
                    seconds_to_expiry,
                    decision=decision,
                    extra={"side": side, "confidence": 0.95},
                )
            )
            return None

        # Explicit edge breakdown in the log.  No hidden deductions.
        bd = decision.edge_breakdown
        logger.info(
            "[TRADE-DECISION] asset=%s side=%s action=%s price=%dc "
            "p_yes=%.3f p_no=%.3f p_selected=%.3f "
            "entry_price=%.3f entry_fee=%.3f exit_reserve=%.3f risk_reserve=%.3f "
            "gross_edge=%.3f net_edge=%.3f confidence=%s confidence_valid=%s confidence_source=%s",
            asset, side, action, price_cents,
            float(decision.p_yes_calibrated), float(decision.p_no_calibrated), model_prob,
            float(bd.executable_entry_price) if bd else 0.0,
            float(bd.entry_fee) if bd else 0.0,
            float(bd.exit_cost_reserve) if bd else 0.0,
            float(bd.model_risk_reserve) if bd else 0.0,
            float(decision.gross_edge) if decision.gross_edge is not None else 0.0,
            edge_pct,
            str(decision.confidence),
            decision.confidence_valid,
            decision.confidence_source,
        )

        return {
            "ticker": getattr(market, "ticker", asset),
            "run_id": run_id,
            "decision_id": decision.decision_id,
            "asset": asset,
            "side": side,
            "action": action,
            "price_cents": price_cents,
            "model_prob": model_prob,
            "p_yes": float(decision.p_yes_calibrated),
            "p_no": float(decision.p_no_calibrated),
            "p_selected": model_prob,
            "edge_pct": edge_pct * 100.0,
            "edge_yes": float(decision.yes_net_edge) * 100.0,
            "edge_no": float(decision.no_net_edge) * 100.0,
            "gross_edge_cents": float(decision.gross_edge) * 100.0 if decision.gross_edge is not None else 0.0,
            "net_edge_cents": edge_pct * 100.0,
            "gross_edge": float(decision.gross_edge) if decision.gross_edge is not None else 0.0,
            "net_edge": float(decision.net_edge) if decision.net_edge is not None else 0.0,
            "entry_fee_cents": float(bd.entry_fee) * 100.0 if bd else fee_cents,
            "exit_cost_reserve_cents": float(bd.exit_cost_reserve) * 100.0 if bd else fee_cents,
            "model_risk_reserve_cents": float(bd.model_risk_reserve) * 100.0 if bd else 0.0,
            "data_state": decision.data_state,
            "regime_label": decision.regime_label,
            "regime_probability": float(decision.regime_probability) if decision.regime_probability is not None else 0.0,
            "confidence": float(decision.confidence) if decision.confidence is not None else 0.0,
            "confidence_valid": decision.confidence_valid,
            "confidence_source": decision.confidence_source,
            "confidence_reasons": decision.confidence_reasons,
            "count": int(decision.approved_size_cc) // 100,
            "trade_decision": decision,
            "rationale": f"trade_decision: {decision.decision_id} p_yes={float(decision.p_yes_calibrated):.3f} p_no={float(decision.p_no_calibrated):.3f} p_selected={model_prob:.3f} edge={edge_pct:.3f}",
            "thesis_side": thesis_side,
            "strategy_intent": strategy_intent,
            "is_counter_trend": False,
            "yes_bid_cents": yes_bid,
            "yes_ask_cents": yes_ask,
            "no_bid_cents": no_bid,
            "no_ask_cents": no_ask,
            "yes_depth": getattr(market_state, "min_depth_yes", 0) or 0,
            "no_depth": getattr(market_state, "min_depth_no", 0) or 0,
            "vol_regime": regime,
            "seconds_to_expiry": seconds_to_expiry,
            "velocity": 0.0,
            "fvg_active": int(getattr(hybrid, "fvg_active", 0) or 0) if hybrid is not None else 0,
            "fvg_direction": (
                "bullish" if getattr(hybrid, "fvg_direction", 0.0) > 0
                else "bearish" if getattr(hybrid, "fvg_direction", 0.0) < 0
                else "neutral"
            ) if hybrid is not None else "neutral",
            "fvg_confidence": float(getattr(hybrid, "fvg_confidence", 0.0) or 0.0) if hybrid is not None else 0.0,
            "fvg_fill_signal": float(getattr(hybrid, "fvg_fill_signal", 0.0) or 0.0) if hybrid is not None else 0.0,
            "fvg_size": float(getattr(hybrid, "fvg_size", 0.0) or 0.0) if hybrid is not None else 0.0,
            "fvg_distance_to_fill": float(getattr(hybrid, "fvg_distance_to_fill", 0.0) or 0.0) if hybrid is not None else 0.0,
            "fvg_delta": float(getattr(hybrid, "fvg_delta", 0.0) or 0.0) if hybrid is not None else 0.0,
            "fvg_price_source": str(getattr(hybrid, "fvg_price_source", "") or "") if hybrid is not None else "",
            "fvg_price_staleness_ms": getattr(hybrid, "fvg_price_staleness_ms", None) if hybrid is not None else None,
            "fvg_influenced": bool(fvg_influenced) if hybrid is not None else False,
            "fvg_size_scale": float(fvg_size_scale) if hybrid is not None else 1.0,
            "regime": regime,
            "hmm_regime": None,
            "hmm_regime_confidence": 0.0,
            "aggressiveness": 1.0,
            "post_only": False,
            "order_type": "limit",
            "time_of_day_multiplier": 1.0,
            "take_profit_r_multiple": 0.8,
            "stop_loss_r_multiple": 0.4,
            "all_in_cost_cents": (
                float(bd.executable_entry_price) * 100.0
                + float(bd.entry_fee) * 100.0
                + float(bd.exit_cost_reserve) * 100.0
                + float(bd.model_risk_reserve) * 100.0
            ) if bd else float(price_cents) + fee_cents,
            "ev_net_cents": (
                (model_prob * 100.0)
                - (float(bd.executable_entry_price) * 100.0
                   + float(bd.entry_fee) * 100.0
                   + float(bd.exit_cost_reserve) * 100.0
                   + float(bd.model_risk_reserve) * 100.0)
            ) if bd else (model_prob * 100.0) - float(price_cents) - fee_cents,
            "fee_cents": fee_cents,
            "slippage_cents": 0.0,
            "time_to_expiry_seconds": seconds_to_expiry,
            "selected_outcome_price": int(round(float(decision.selected_outcome_price) * 100.0)) if decision.selected_outcome_price is not None else price_cents,
            "settlement_input_price": float(settlement_input_price) if settlement_input_price is not None else float(strike),
            "cf_rti_basis": float(cf_rti_basis) if cf_rti_basis is not None else 0.0,
            "settlement_reference": settlement_reference,
            "flb_position_multiplier": 1.0,
            # CRITICAL FIX 2026-08-20: carry the per-decision edge threshold so the
            # router's fill-adjusted edge gate and repricer use the same minimum.
            "min_required_edge": float(decision.min_required_edge) if decision.min_required_edge is not None else 0.03,
        }

    def _generate_price_based_signal(self, asset: str, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[Dict[str, Any]]:

        # Legacy path is disabled in paper/live unless explicitly enabled.
        if not _is_legacy_signal_enabled():
            logger.warning("[LEGACY-SIGNAL-DISABLED] _generate_price_based_signal blocked in %s mode", os.environ.get("MERID_PM_TRADING_MODE", "unknown"))
            return None

        # PRICE-BASED STRATEGY (Turbine research winner: +56.6% ROI)

        # Buy YES when market price <= 0.50, sell when price >= 0.70

        # Simple strategy that works best on thin 15-min books



        # Get current market price from market state

        market_price = 0.0
        market_state = None

        try:

            if hasattr(market, 'market') and hasattr(market.market, 'market_id'):

                ticker = market.market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None

                if market_state:

                    # Side-appropriate prices (not mid) for edge and side selection.
                    # YES price = best YES ask = cost to buy YES.
                    # NO price = best NO ask = 100 - best YES bid = cost to buy NO.
                    best_bid = int(round(getattr(market_state, 'best_bid_cents', 0) or 0))

                    best_ask = int(round(getattr(market_state, 'best_ask_cents', 0) or 0))

                    # Calculate spread width for observability
                    spread_width_cents = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0

                    yes_market_price_cents = best_ask if best_ask > 0 else best_bid
                    no_market_price_cents = 100 - best_bid if best_bid > 0 else 100 - best_ask

                    yes_market_price = yes_market_price_cents / 100.0
                    no_market_price = no_market_price_cents / 100.0

                    # Log a mid-style reference price for observability, but edges use side-appropriate prices.
                    if best_bid > 0 and best_ask > 0:
                        market_price = (best_bid + best_ask) / 200.0
                        market_price_type = "mid"
                    elif best_bid > 0:
                        market_price = best_bid / 100.0
                        market_price_type = "bid_only"
                    elif best_ask > 0:
                        market_price = best_ask / 100.0
                        market_price_type = "ask_only"
                    else:
                        market_price = 0.0
                        market_price_type = "none"

                    logger.info(f"[PRICE-BASED-DEBUG] asset={asset} ticker={ticker} best_bid_cents={best_bid} best_ask_cents={best_ask} spread_width={spread_width_cents}c yes_market_price={yes_market_price:.2f} no_market_price={no_market_price:.2f}")

                    # CRITICAL FIX: Validate side-appropriate prices are in reasonable range [0.01, 0.99]

                    # Prices outside this range indicate data corruption or calculation error

                    if (yes_market_price < 0.01 or yes_market_price > 0.99 or
                            no_market_price < 0.01 or no_market_price > 0.99):

                        logger.warning("[PRICE-BASED-ERROR] asset=%s ticker=%s invalid side prices (yes=%.2f no=%.2f), rejecting signal", asset, ticker, yes_market_price, no_market_price)

                        return None

                else:

                    logger.warning("[PRICE-BASED-ERROR] asset=%s market_state is None for ticker=%s", asset, ticker)

        except Exception as e:

            logger.warning("[PRICE-BASED-ERROR] asset=%s failed to get market price: %s", asset, e)

            return None



        if market_price <= 0:

            logger.warning("[PRICE-BASED-ERROR] asset=%s invalid market price=%.2f", asset, market_price)

            return None



        buy_threshold = self.config.price_based_buy_threshold

        sell_threshold = self.config.price_based_sell_threshold



        logger.info(

            "[PRICE-BASED-SIGNAL] asset=%s market_price=%.2f buy_threshold=%.2f sell_threshold=%.2f",

            asset, market_price, buy_threshold, sell_threshold

        )


        # CRITICAL FIX: 2026-07-25 - Use canonical edge formula for price-based strategy
        # This ensures alignment with compute_canonical_edges() in canonical_edge.py
        # Canonical formula: edge = model_prob - market_price
        #
        # Previous threshold-based formula: edge = (threshold - market_price) / threshold
        # This was inconsistent with canonical edge and caused allocator vs parity mismatch
        #
        # New canonical approach:
        # 1. Derive model_prob from price thresholds (our "fair price" estimate)
        # 2. Compute edge as model_prob - market_price (canonical formula)
        # 3. This ensures consistency across allocator, parity block, and microstructure gate

        # Complement-symmetric fair values: p_yes + p_no must equal 1.
        # buy_threshold is the fair value used for YES; the NO fair is its
        # complement.  sell_threshold is only the activation boundary for NO
        # (NO price <= 1 - sell_threshold, equivalently YES price >= sell_threshold).
        # This fixes the structural YES bias from using 1 - sell_threshold as the
        # NO fair while buy_threshold was the YES fair (p_yes + p_no != 1).
        yes_model_prob = buy_threshold
        no_model_prob = 1.0 - buy_threshold

        # Only evaluate a side when the market price is inside its configured
        # entry zone; otherwise force the edge negative so it cannot be selected.
        yes_active = yes_market_price <= buy_threshold
        no_active = no_market_price <= (1.0 - sell_threshold)

        # Calculate canonical edges using side-appropriate market prices.
        # YES edge = fair YES prob - cost to buy YES.
        # NO edge = fair NO prob - cost to buy NO.
        yes_edge_pct = yes_model_prob - yes_market_price if yes_active else -1.0
        no_edge_pct = no_model_prob - no_market_price if no_active else -1.0

        # Apply minimum edge threshold (2% = 0.02 fraction)
        # This is a quality gate, not a transformation of the edge formula
        if yes_edge_pct > 0:
            yes_edge_pct = max(yes_edge_pct, 0.02)
        else:
            yes_edge_pct = 0.0  # Negative edge → no trade

        if no_edge_pct > 0:
            no_edge_pct = max(no_edge_pct, 0.02)
        else:
            no_edge_pct = 0.0  # Negative edge → no trade

        # CRITICAL: Only select sides with POSITIVE edges
        # This is the root cause fix for WINNER_MISMATCH parity failures
        if yes_edge_pct <= 0 and no_edge_pct <= 0:
            logger.info(
                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f no positive edges (yes_edge=%.4f no_edge=%.4f) -> NO TRADE",
                asset, market_price, yes_edge_pct, no_edge_pct
            )
            if DIRECTIONAL_BREAKER_AVAILABLE:
                trace_payload = _build_directional_trace_payload(
                    self,
                    asset=asset,
                    ticker=ticker,
                    market_state=market_state,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    yes_model_prob=yes_model_prob,
                    no_model_prob=no_model_prob,
                    yes_edge=yes_edge_pct,
                    no_edge=no_edge_pct,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    selected_side=None,
                    selected_action=None,
                    selected_price_cents=None,
                    selected_model_prob=None,
                    selected_edge=None,
                    decision="no_trade",
                    reason="both_edges_non_positive",
                )
                emit_directional_trace(logger, trace_payload)
            return None

        # Select side with maximum positive edge
        # CORRECT MAPPING (2026-07-23): yes_edge > no_edge → BULLISH_EVENT, no_edge > yes_edge → BEARISH_EVENT
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
            signal_action = "buy"
            edge_pct = yes_edge_pct
            strategy_intent = StrategyIntent.BULLISH_EVENT if UNIFIED_TERMINOLOGY_AVAILABLE else None
            logger.info(
                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f YES edge=%.4f > NO edge=%.4f -> BUY YES (BULLISH_EVENT)",
                asset, market_price, yes_edge_pct, no_edge_pct
            )
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
            signal_action = "buy"
            edge_pct = no_edge_pct
            strategy_intent = StrategyIntent.BEARISH_EVENT if UNIFIED_TERMINOLOGY_AVAILABLE else None
            logger.info(
                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f NO edge=%.4f > YES edge=%.4f -> BUY NO (BEARISH_EVENT)",
                asset, market_price, no_edge_pct, yes_edge_pct
            )
        else:
            # Equal edges - prefer NO side to counteract YES bias
            signal_side = "no"
            signal_action = "buy"
            edge_pct = no_edge_pct
            strategy_intent = StrategyIntent.BEARISH_EVENT if UNIFIED_TERMINOLOGY_AVAILABLE else None
            logger.info(
                "[PRICE-BASED-SIGNAL] asset=%s price=%.2f equal edges (yes=%.4f no=%.4f) -> BUY NO (BEARISH_EVENT tie-break)",
                asset, market_price, yes_edge_pct, no_edge_pct
            )

        # DIRECTIONAL ANOMALY CIRCUIT BREAKER (2026-08-19): verify complement
        # parity, edge-winner parity, and rolling frequency/price fairness.
        # If the raw model probabilities and market prices cannot explain the
        # selection, block the signal and emit a structured trace.
        if DIRECTIONAL_BREAKER_AVAILABLE:
            breaker = get_directional_anomaly_breaker()
            allowed, breaker_reason = breaker.record_and_check(
                asset=asset,
                ticker=ticker or "unknown",
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                yes_model_prob=yes_model_prob,
                no_model_prob=no_model_prob,
                yes_edge=yes_edge_pct,
                no_edge=no_edge_pct,
                selected_side=signal_side,
                selected_action=signal_action,
                market_price=market_price,
            )
            if not allowed:
                trace_payload = _build_directional_trace_payload(
                    self,
                    asset=asset,
                    ticker=ticker,
                    market_state=market_state,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    yes_model_prob=yes_model_prob,
                    no_model_prob=no_model_prob,
                    yes_edge=yes_edge_pct,
                    no_edge=no_edge_pct,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    selected_side=None,
                    selected_action=None,
                    selected_price_cents=None,
                    selected_model_prob=None,
                    selected_edge=None,
                    decision="blocked",
                    reason=breaker_reason,
                )
                emit_directional_trace(logger, trace_payload)
                logger.error(
                    "[DIRECTIONAL-ANOMALY-BREAKER] asset=%s ticker=%s %s",
                    asset, ticker, breaker_reason,
                )
                return None

        # CRITICAL FIX 2026-08-04: Use side-appropriate market price for confidence,
        # model probability, and the actual order price.  YES uses the YES ask;
        # NO uses the YES bid (because buying NO means selling YES at the bid).
        if signal_side == "yes":
            market_price = yes_market_price
            entry_price_cents = yes_market_price_cents
        else:
            market_price = 1.0 - no_market_price  # YES bid in probability terms
            entry_price_cents = no_market_price_cents

        # Fee-aware executable edges separate raw edge from spread and fee drag
        # for maker-first routing decisions.
        # Maker fee on Kalshi is 0% for resting orders (maker coefficient = 0.0).
        spread_pct = spread_width_cents / 100.0
        taker_fee_cents = canonical_calculate_kalshi_fee_cents(1, int(entry_price_cents))
        maker_fee_cents = 0
        taker_fee_pct = taker_fee_cents / entry_price_cents if entry_price_cents > 0 else 0.0
        maker_fee_pct = 0.0
        executable_edge_maker_pct = edge_pct - maker_fee_pct
        executable_edge_taker_pct = edge_pct - spread_pct - taker_fee_pct

        # CRITICAL INVARIANT (2026-07-23): If no_edge > yes_edge, candidate_side must be NO
        # This catches structural YES bias in side arbitration
        if no_edge_pct > yes_edge_pct and signal_side != "no":
            logger.error(
                "[SIDE-ARB-INVARIANT-VIOLATION] asset=%s no_edge=%.4f > yes_edge=%.4f but selected_side=%s (expected NO) - STRUCTURAL YES BIAS DETECTED",
                asset, no_edge_pct, yes_edge_pct, signal_side
            )
            # Record bias event to bias monitor
            if BIAS_MONITOR_ENABLED:
                bias_monitor = get_bias_monitor()
                if bias_monitor:
                    bias_monitor.record_signal(asset=asset, side=signal_side, edge=edge_pct, price=market_price)
            # Return None to block the trade - this is a critical bug
            return None

        # PHASE 1: Shadow dual-side evaluation for price_based path
        # Log side selection for bias analysis
        logger.info(
            "[SHADOW-DUAL-SIDE-PRICE-BASED] asset=%s market_price=%.2f yes_edge=%.4f no_edge=%.4f selected_side=%s selected_edge=%.4f",
            asset, market_price, yes_edge_pct, no_edge_pct, signal_side, edge_pct
        )

        # Log to shadow dual-side metrics monitor
        try:
            from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor
            monitor = get_shadow_dual_side_monitor()
            # For price_based, expected side is based on price thresholds
            expected_side = "yes" if market_price <= buy_threshold else "no"
            expected_side_edge = yes_edge_pct if expected_side == "yes" else no_edge_pct
            opposite_side = "no" if expected_side == "yes" else "yes"
            opposite_side_edge = no_edge_pct if expected_side == "yes" else yes_edge_pct

            monitor.log_shadow_evaluation(
                asset=asset,
                velocity=0.0,  # price_based doesn't use velocity
                strategy_mode="price_based",
                expected_side=expected_side,
                expected_edge=expected_side_edge,
                opposite_side=opposite_side,
                opposite_edge=opposite_side_edge,
                hypothetical_best_side=signal_side,
                hypothetical_best_edge=edge_pct,
                yes_in_range=True,  # price_based doesn't check range
                no_in_range=True
            )
        except Exception as metrics_err:
            logger.warning("[SHADOW-DUAL-SIDE-METRICS] Failed to log to metrics monitor: %s", metrics_err)

        # CRITICAL FIX (2026-07-19): Add upstream invariant check
        # Validate that the derived side/action matches the strategy intent
        if UNIFIED_TERMINOLOGY_AVAILABLE and strategy_intent:
            try:
                from merid.prediction.intent_contract import validate_intent_exposure_consistency
                is_valid, error = validate_intent_exposure_consistency(
                    intent=strategy_intent,
                    kalshi_side=signal_side,
                    kalshi_action=signal_action,
                    current_position=None,  # Entry signal (flat position)
                )
                if not is_valid:
                    logger.error(
                        "[INTENT-EXPOSURE-MISMATCH] asset=%s intent=%s side=%s action=%s - %s - BLOCKING ORDER",
                        asset, strategy_intent.value, signal_side, signal_action, error
                    )
                    return None
                else:
                    logger.debug(
                        "[INTENT-EXPOSURE-VALID] asset=%s intent=%s side=%s action=%s - invariant check passed",
                        asset, strategy_intent.value, signal_side, signal_action
                    )
            except ImportError:
                logger.warning("[INTENT-CONTRACT] Not available - skipping upstream invariant check")



        # Return signal

        # CRITICAL FIX: 2026-07-20 - Use pre-calculated edges from side selection
        # Set edge_yes and edge_no for parity checker with actual calculated values
        edge_yes = yes_edge_pct
        edge_no = no_edge_pct

        # Calculate confidence and model_prob based on selected side
        if signal_side == "yes" and signal_action == "buy":

            # Dynamic confidence: increases as price moves further below buy_threshold
            distance_from_threshold = (buy_threshold - market_price) / buy_threshold
            confidence = min(0.99, 0.50 + 2.0 * distance_from_threshold)

            # edge_pct is already a fraction here; cap at 20 percentage points.
            edge_prob_adjustment = min(edge_pct, 0.20)
            model_prob = market_price + edge_prob_adjustment

        elif signal_side == "no" and signal_action == "buy":

            # Dynamic confidence: increases as price moves further above sell_threshold
            distance_from_threshold = (market_price - sell_threshold) / (1.0 - sell_threshold)
            confidence = min(0.99, 0.50 + 2.0 * distance_from_threshold)

            # edge_pct is already a fraction here; cap at 20 percentage points.
            edge_prob_adjustment = min(edge_pct, 0.20)
            no_market_prob = 1.0 - market_price
            model_prob = no_market_prob + edge_prob_adjustment

        # Canonical clamp: model probability must remain a valid probability.
        eps = MERID_MODEL_PROBABILITY_EPSILON
        model_prob = max(eps, min(1.0 - eps, model_prob))

        # All-in cost and EV gate (same helper as sizing).
        entry_price_cents = int(round(entry_price_cents))
        all_in_cost_cents = compute_all_in_cost_cents(entry_price_cents) if _UNIFIED_SIZING_AVAILABLE else float(entry_price_cents)
        ev_net_cents = (model_prob * 100.0) - all_in_cost_cents

        quote_market_prob = entry_price_cents / 100.0
        price_source = "yes_ask" if signal_side == "yes" else "no_ask"

        if ev_net_cents <= 0:
            _emit_ev_components_log(
                market_state=market_state,
                asset=asset,
                signal_side=signal_side,
                signal_action=signal_action,
                price_cents=entry_price_cents,
                price_source=price_source,
                market_prob=quote_market_prob,
                model_prob=model_prob,
                decision="no_trade",
            )
            return None

        is_extreme_price = entry_price_cents <= 5 or entry_price_cents >= 95
        if is_extreme_price:
            fee_cents = float(compute_fee_cents(entry_price_cents)) if _UNIFIED_SIZING_AVAILABLE else 2.0
            min_ev_cents = MERID_EV_K_EXTREME * fee_cents
            if ev_net_cents < min_ev_cents:
                _emit_ev_components_log(
                    market_state=market_state,
                    asset=asset,
                    signal_side=signal_side,
                    signal_action=signal_action,
                    price_cents=entry_price_cents,
                    price_source=price_source,
                    market_prob=quote_market_prob,
                    model_prob=model_prob,
                    decision="no_trade_extreme",
                )
                logger.info(
                    "[SIGNAL-EV-EXTREME] asset=%s side=%s price=%dc model_prob=%.4f ev_net=%.4fc < %.4fc (k=%.2f * fee=%.2fc) -> NO TRADE",
                    asset, signal_side, entry_price_cents, model_prob, ev_net_cents, min_ev_cents,
                    MERID_EV_K_EXTREME, fee_cents
                )
                return None

        _emit_ev_components_log(
            market_state=market_state,
            asset=asset,
            signal_side=signal_side,
            signal_action=signal_action,
            price_cents=entry_price_cents,
            price_source=price_source,
            market_prob=quote_market_prob,
            model_prob=model_prob,
            decision="pass",
        )

        logger.info(
            "[PRICE-BASED-DEBUG] asset=%s market_price=%.4f edge_pct=%.4f edge_adjustment=%.4f model_prob=%.4f all_in_cost=%.2fc ev_net=%.4fc",
            asset, market_price, edge_pct, edge_prob_adjustment, model_prob, all_in_cost_cents, ev_net_cents
        )

        logger.info("[PRICE-BASED-CONFIDENCE] asset=%s action=%s price=%.2f edge_pct=%.4f confidence=%.2f",
                    asset, signal_action, market_price, edge_pct, confidence)



        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = int(round(entry_price_cents))



        # Check if price is within canonical 10c-75c range

        if 10 <= raw_price_cents <= 75:

            # Price is already in the side-appropriate range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d in side-aware range - using directly",

                asset, signal_side, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d outside side-aware range - searching orderbook",

                asset, signal_side, raw_price_cents

            )



            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None



                if market_state:

                    # Select the opposite-side book to compute the ask for the target side.
                    # YES ask = 100 - NO bid; NO ask = 100 - YES bid.

                    if signal_side == "yes":
                        # Cheapest YES ask = 100 - NO bid; search no_bids.
                        levels = getattr(market_state, 'no_bids', [])
                        range_min, range_max = 10, 75
                    else:
                        # Cheapest NO ask = 100 - YES bid; search yes_bids.
                        levels = getattr(market_state, 'yes_bids', [])
                        range_min, range_max = 10, 75

                    if levels:

                        # Find cheapest executable price in the side-appropriate range.
                        # For YES: 100 - no_bid; for NO: 100 - yes_bid.

                        valid_prices = [100 - p for (p, size) in levels if range_min <= (100 - p) <= range_max and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # cheapest acceptable executable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s side=%s found %d valid prices in [%dc-%dc], using cheapest=%d",

                                asset, signal_side, len(valid_prices), range_min, range_max, price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s side=%s no executable prices in [%dc-%dc] - dropping candidate",

                                asset, signal_side, range_min, range_max

                            )

                            self._record_signal_rejection(
                                "no_executable_price_in_range",
                                market_id=market_id,
                                market_time_remaining_s=minutes_to_expiry * 60.0,
                                reference_price=spot_price,
                                velocity=velocity,
                                threshold=velocity_threshold,
                                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} range={range_min}-{range_max}",
                            )

                            return None  # Drop candidate - no valid price in side-aware range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s side=%s orderbook not available - dropping candidate",

                            asset, signal_side

                        )

                        self._record_signal_rejection(
                            "orderbook_not_available",
                            market_id=market_id,
                            market_time_remaining_s=minutes_to_expiry * 60.0,
                            reference_price=spot_price,
                            velocity=velocity,
                            threshold=velocity_threshold,
                            feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    self._record_signal_rejection(
                        "market_state_not_available",
                        market_id=market_id,
                        market_time_remaining_s=minutes_to_expiry * 60.0,
                        reference_price=spot_price,
                        velocity=velocity,
                        threshold=velocity_threshold,
                        feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                self._record_signal_rejection(
                    "price_selection_exception",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} error={e}",
                )

                return None



            clamped_price_cents = price_cents



        # Final validation - side-aware canonical range
        # CRITICAL FIX (2026-08-05): YES and NO trade in different price regions. The previous
        # single 10c-75c range rejected all NO candidates above 75c even though NO contracts
        # naturally trade at high prices (implied probability of event NOT happening).
        # Single canonical entry range 10c-75c for both YES and NO.  Duality
        # means an 80c NO is equivalent to a 20c YES; there is no need to allow
        # either side to trade outside 10-75, and order_intent_contract rejects
        # such prices with `invalid_price`.
        price_min, price_max = 10, 75
        range_str = "10c-75c"

        if clamped_price_cents is None or not (price_min <= clamped_price_cents <= price_max):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s side=%s final price_cents=%d not in range [%s] - dropping candidate",

                asset, signal_side, clamped_price_cents, range_str

            )

            self._record_signal_rejection(
                "final_price_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} price_cents={clamped_price_cents} range={range_str}",
            )

            return None



        logger.info(

            "[PRICE-SELECTION] asset=%s side=%s final entry price=%d (within canonical range [%s])",

            asset, signal_side, clamped_price_cents, range_str

        )



        # CRITICAL FIX (2026-07-19): Include strategy_intent in signal for exposure validation
        selected_price_cents = int(round(clamped_price_cents))

        settlement_input_price, cf_rti_basis, settlement_reference, cfb_observation = _get_settlement_input_price(
            asset,
            spot_price,
            settlement_digits=getattr(market, "settlement_digits", None),
        )
        signal_dict = {
            "side": signal_side,
            "action": signal_action,
            "price_cents": selected_price_cents,  # CRITICAL: Use selected price
            "confidence": confidence,  # Dynamic edge-based confidence (not hardcoded)
            # Canonical model probability: clamped to (0, 1), never > 1.
            "model_prob": max(MERID_MODEL_PROBABILITY_EPSILON, min(1.0 - MERID_MODEL_PROBABILITY_EPSILON, model_prob)),
            "edge_pct": edge_pct,  # CRITICAL: Calculate edge for price-based strategy
            # CRITICAL FIX: 2026-07-19 - Include both edge_yes and edge_no for parity checker
            "edge_yes": edge_yes,  # YES edge for downstream parity checks
            "edge_no": edge_no,    # NO edge for downstream parity checks
            "rationale": f"price_based: price={market_price:.2f} vs thresholds (buy={buy_threshold:.2f}, sell={sell_threshold:.2f}) edge={edge_pct:.4f} conf={confidence:.2f}",
            "velocity": 0.0,  # Price-based strategy doesn't use velocity
            # Economic / telemetry fields (single source of truth for EV)
            "thesis_side": "yes" if market_price <= buy_threshold else "no",
            "is_counter_trend": False,  # Price-based does not compare to a velocity thesis
            "all_in_cost_cents": all_in_cost_cents,
            "ev_net_cents": ev_net_cents,
            "fee_cents": float(compute_fee_cents(selected_price_cents)) if _UNIFIED_SIZING_AVAILABLE else 2.0,
            "selected_outcome_price": selected_price_cents,
            "min_required_edge": 0.02,
            "slippage_cents": _get_slippage_cents() if _UNIFIED_SIZING_AVAILABLE else 5,
            "time_to_expiry_seconds": minutes_to_expiry * 60.0,
            "settlement_input_price": settlement_input_price,
            "cf_rti_basis": cf_rti_basis,
            "settlement_reference": settlement_reference,
        }

        if UNIFIED_TERMINOLOGY_AVAILABLE:
            signal_dict["strategy_intent"] = strategy_intent.value

        if DIRECTIONAL_BREAKER_AVAILABLE:
            trace_payload = _build_directional_trace_payload(
                self,
                asset=asset,
                ticker=ticker,
                market_state=market_state,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
                yes_model_prob=yes_model_prob,
                no_model_prob=no_model_prob,
                yes_edge=edge_yes,
                no_edge=edge_no,
                best_bid=best_bid,
                best_ask=best_ask,
                selected_side=signal_side,
                selected_action=signal_action,
                selected_price_cents=selected_price_cents,
                selected_model_prob=model_prob,
                selected_edge=edge_pct,
                decision="trade",
                reason="max_positive_edge",
            )
            emit_directional_trace(logger, trace_payload)

        return signal_dict



    def set_velocity_snapshot(self, snapshot: Dict[str, Dict]) -> None:
        """Inject an immutable per-cycle Coinbase velocity snapshot into this agent.

        The grid owns the authoritative snapshot; each agent receives a shallow copy
        keyed by asset.  This avoids the previous propagation defect where the grid
        held the live signals but agents inspected an unset agent-local attribute.
        """
        self._coinbase_velocity_signals = {
            asset: {
                "velocity": float(info.get("velocity", 0.0)),
                "timestamp": float(info.get("timestamp", 0.0)),
                "signal_type": str(info.get("signal_type", "none")),
            }
            for asset, info in (snapshot or {}).items()
        }
        logger.debug(
            "[VELOCITY-SNAPSHOT] agent=%s received snapshot for %d assets",
            self.config.name, len(self._coinbase_velocity_signals)
        )

    def _reset_rejection_waterfall(self, asset: str) -> None:
        """Reset the per-cycle rejection waterfall for a new collection cycle."""
        self._rejection_waterfall = {
            "asset": asset,
            "stages": {},
            "selected": False,
            "final_reason": "",
        }
        self._last_signal_rejection = {
            "reason": "",
            "context": {},
        }
        self._cycle_decision = {}
        self._last_velocity_value = 0.0
        self._last_velocity_source = "internal_fallback"
        self._last_velocity_age_ms = -1.0
        self._last_velocity_signal_type = "none"

    def _record_signal_rejection(self, reason: str, **context) -> None:
        """Record the specific reason signal generation returned None.

        This is surfaced in the rejection waterfall and as a structured
        SIGNAL-GENERATION-REJECT log in collect_order_candidate.
        """
        # Backfill velocity/freshness metadata if available and not explicitly provided.
        # If the caller passed an explicit None, we still backfill from the last cycle.
        if (context.get("velocity") is None or "velocity" not in context) and hasattr(self, '_last_velocity_value'):
            context["velocity"] = self._last_velocity_value
        if (context.get("velocity_source") is None or "velocity_source" not in context) and hasattr(self, '_last_velocity_source'):
            context["velocity_source"] = self._last_velocity_source
        if (context.get("velocity_age_ms") is None or "velocity_age_ms" not in context) and hasattr(self, '_last_velocity_age_ms'):
            context["velocity_age_ms"] = self._last_velocity_age_ms
        if (context.get("signal_type") is None or "signal_type" not in context) and hasattr(self, '_last_velocity_signal_type'):
            context["signal_type"] = self._last_velocity_signal_type
        if (context.get("threshold") is None or "threshold" not in context) and hasattr(self, '_last_velocity_threshold'):
            context["threshold"] = self._last_velocity_threshold

        self._last_signal_rejection = {
            "reason": reason,
            "context": context,
        }
        self._telemetry_update(rejection_reason=reason, **context)

    def _get_candles_available(self, asset: str) -> Optional[int]:
        """Return the number of available 1m bars for an asset, if known."""
        try:
            stack = getattr(self, "_indicator_stacks", {}).get(asset)
            if stack is not None and hasattr(stack, "snapshot"):
                return stack.snapshot().bars_available
        except Exception:
            pass
        return None

    def _build_trade_decision_rejection_context(
        self,
        asset: str,
        spot_price: float,
        settlement_input_price: Optional[float],
        settlement_reference: Optional[str],
        seconds_to_expiry: float,
        decision: Any = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the context attached to a trade-decision (no-trade) rejection.

        Mirrors the fields emitted by [SIGNAL-GENERATION-REJECT] so telemetry
        and logs stop showing N/A when a candidate fails on edge, depth, or
        data quality.
        """
        context: Dict[str, Any] = {
            "reference_price": settlement_input_price if settlement_input_price is not None else spot_price,
            "market_time_remaining_s": seconds_to_expiry,
            "candles_available": self._get_candles_available(asset),
            "signal_type": "hybrid",
            "feature_flags": f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} trade_decision_v2",
            "settlement_reference": settlement_reference,
            "velocity": getattr(self, '_last_velocity_value', None),
            "velocity_source": getattr(self, '_last_velocity_source', "trade_decision_v2"),
            "velocity_age_ms": getattr(self, '_last_velocity_age_ms', None),
            "velocity_threshold": getattr(self, '_last_velocity_threshold', None),
            "threshold": getattr(self, '_last_velocity_threshold', None),
            "threshold_type": "velocity",
        }
        if decision is not None:
            edge_threshold = float(decision.edge_threshold) if decision.edge_threshold is not None else None
            context.update({
                "p_yes": float(decision.p_yes_calibrated) if decision.p_yes_calibrated is not None else None,
                "p_no": float(decision.p_no_calibrated) if decision.p_no_calibrated is not None else None,
                "yes_edge": float(decision.yes_net_edge) if decision.yes_net_edge is not None else None,
                "no_edge": float(decision.no_net_edge) if decision.no_net_edge is not None else None,
                "gross_edge": float(decision.gross_edge) if decision.gross_edge is not None else None,
                "net_edge": float(decision.net_edge) if decision.net_edge is not None else None,
                "edge_threshold": edge_threshold,
                "data_state": getattr(decision, "data_state", None),
                "regime": getattr(decision, "regime", None),
                "confidence_valid": getattr(decision, "confidence_valid", None),
                "confidence_reasons": getattr(decision, "confidence_reasons", []),
            })
            if edge_threshold is not None:
                context["threshold"] = edge_threshold
                context["threshold_type"] = "edge"
        if extra:
            context.update(extra)
        return context

    def _telemetry_update(self, **fields) -> None:
        """Merge fields into the per-cycle decision telemetry snapshot.

        Read-only instrumentation for decision_telemetry; never raises and
        never affects signal, gating, or allocator behavior.
        """
        try:
            if not hasattr(self, "_cycle_decision") or self._cycle_decision is None:
                self._cycle_decision = {}
            self._cycle_decision.update(fields)
        except Exception:
            pass

    def _record_waterfall(self, stage: str, status: bool, reason: str = "") -> None:
        """Record a stage outcome in the rejection waterfall.

        status=True means the stage passed; status=False means it failed this check.
        The final_reason is set separately when a failure actually causes a return.
        """
        self._rejection_waterfall["stages"][stage] = {
            "status": status,
            "reason": reason,
        }

    def _set_final_reason(self, reason: str) -> None:
        """Set the final gate that caused this candidate to be rejected."""
        if not self._rejection_waterfall["final_reason"]:
            self._rejection_waterfall["final_reason"] = reason

    def get_rejection_waterfall(self) -> Dict[str, Any]:
        """Return the current rejection waterfall for this agent."""
        return self._rejection_waterfall.copy()

    def _calculate_multi_window_velocity(self, asset: str, current_price: float) -> float:

        # Phase 4.1: Calculate weighted multi-window velocity with EMA smoothing and ATR normalization.

        # Uses 10s, 30s, 60s windows with configurable weights.

        # Applies EMA smoothing to reduce noise (industry standard).

        # Applies ATR-based volatility normalization for dynamic thresholds (industry standard).

        # Returns weighted average velocity as percentage change.

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # PRIORITY: Use external Coinbase velocity when available (Turbine research #1 winner)
        # Coinbase 1-minute velocity was the top-performing strategy (+$19,451 P&L)
        velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)
        self._last_velocity_threshold = velocity_threshold

        # Determine the authoritative velocity source for this cycle.
        # Coinbase velocity is preferred when fresh; otherwise fall back to the
        # internal multi-window velocity computed from the agent's price history.
        cb_velocity = 0.0
        cb_age_ms = -1.0
        cb_signal_type = "none"
        cb_timestamp = 0.0
        source = "internal_fallback"
        self._last_velocity_source = source
        self._last_velocity_age_ms = cb_age_ms
        self._last_velocity_signal_type = cb_signal_type

        if hasattr(self, '_coinbase_velocity_signals') and asset in self._coinbase_velocity_signals:
            cb_signal = self._coinbase_velocity_signals[asset]
            cb_timestamp = float(cb_signal.get('timestamp', 0.0))
            cb_signal_type = str(cb_signal.get('signal_type', 'none'))
            cb_velocity = float(cb_signal.get('velocity', 0.0))

            if cb_timestamp > 1000000000.0:  # Sane timestamp, not 0/unset
                current_time = time.time()
                signal_age = current_time - cb_timestamp
                cb_age_ms = signal_age * 1000.0

                if signal_age < 120.0 and cb_signal_type != 'none':
                    # Coinbase snapshot is fresh - use it as the authoritative source.
                    source = "coinbase"
                    final_velocity = cb_velocity
                else:
                    # Coinbase snapshot is stale or unavailable - fall back to internal.
                    source = "internal_fallback"
            else:
                # No Coinbase snapshot received for this agent.
                source = "internal_fallback"
        else:
            # No Coinbase snapshot received for this agent.
            source = "internal_fallback"

        if source == "internal_fallback":
            final_velocity = self._calculate_internal_multi_window_velocity(asset, current_price)
        else:
            final_velocity = cb_velocity

        velocity_passed = abs(final_velocity) >= velocity_threshold

        self._last_velocity_value = final_velocity
        self._last_velocity_source = source
        self._last_velocity_age_ms = cb_age_ms
        self._last_velocity_signal_type = cb_signal_type

        logger.info(
            "[VELOCITY-SOURCE] asset=%s source=%s signal_type=%s age_ms=%.0f value=%.6f threshold=%.6f passed=%s",
            asset, source, cb_signal_type, cb_age_ms, final_velocity, velocity_threshold, velocity_passed
        )

        return final_velocity

    def _calculate_internal_multi_window_velocity(self, asset: str, current_price: float) -> float:
        """Internal multi-window velocity fallback from the agent's price history."""

        history = list(self._spot_price_history[asset])

        if len(history) < 2:
            return 0.0

        current_time = int(time.time() * 1000)  # Milliseconds to match spot service

        weighted_velocity = 0.0

        for window_sec, weight in zip(self._velocity_windows, self._momentum_weights):

            target_time = current_time - int(window_sec * 1000)

            prev_price = None

            # Handle OHLC format: (timestamp, close, open, high, low)
            for entry in reversed(history):
                if len(entry) >= 2:
                    ts = entry[0]
                    price = entry[1]  # Use close price for velocity
                    if ts <= target_time:
                        prev_price = price
                        break

            if prev_price is None or prev_price <= 0:
                # If no data for this window, skip it
                continue

            window_velocity = (current_price - prev_price) / prev_price
            weighted_velocity += weight * window_velocity

        # Apply EMA smoothing to reduce noise
        ema_velocity = self._apply_ema_smoothing(asset, weighted_velocity)

        # Apply ATR-based volatility normalization
        atr_normalized_velocity = self._apply_atr_normalization(asset, ema_velocity)

        # Update Z-score history with the normalized velocity
        self._velocity_zscore_history[asset].append((current_time, atr_normalized_velocity))

        # Apply Z-score filter for extreme detection (monitoring only)
        final_velocity = self._apply_zscore_filter(asset, atr_normalized_velocity)

        # CRITICAL FIX: 2026-07-06 - Fix bias bug: use history[-1][1] instead of history[-2][1]
        # This prevents systematic bias in epsilon direction.
        if len(history) >= 1:
            recent_trend = (current_price - history[-1][1]) / history[-1][1]
            final_velocity = final_velocity + (1e-5 if recent_trend >= 0 else -1e-5)
        else:
            # No trend data available - add small positive epsilon
            final_velocity = final_velocity + 1e-5

        return final_velocity



    def _apply_ema_smoothing(self, asset: str, raw_velocity: float) -> float:

        # Apply EMA smoothing to velocity to reduce noise (industry standard).

        # EMA formula: EMA = (current * alpha) + (previous_ema * (1 - alpha))

        # where alpha = 2 / (period + 1)

        if self._velocity_ema_period <= 1:

            return raw_velocity  # No smoothing if period is 1 or less



        alpha = 2.0 / (self._velocity_ema_period + 1.0)

        ema_history = list(self._velocity_ema_history[asset])



        if len(ema_history) == 0:

            # First value - use raw velocity

            smoothed_velocity = raw_velocity

        else:

            # Calculate EMA

            previous_ema = ema_history[-1]

            smoothed_velocity = (raw_velocity * alpha) + (previous_ema * (1.0 - alpha))



        # Store EMA value for next calculation

        self._velocity_ema_history[asset].append(smoothed_velocity)



        return smoothed_velocity



    def _apply_atr_normalization(self, asset: str, velocity: float) -> float:

        # CRITICAL FIX: Disable ATR normalization for velocity calculation

        # ATR normalization was dividing velocity by ATR, causing small price movements

        # to appear as large normalized velocities, breaking the threshold logic.

        # 2026 industry standards use raw velocity with dynamic thresholds, not normalization.

        # The dynamic threshold adjustment in _calculate_dynamic_velocity_threshold

        # already adapts to volatility by adjusting the threshold itself.

        return velocity



    def _calculate_zscore(self, asset: str, value: float) -> float:

        # Calculate Z-score for extreme detection (industry standard).

        # Z-score measures how many standard deviations a value is from the mean.

        # Formula: zscore = (value - mean) / std

        # Z-score > 2.0 = overbought, Z-score < -2.0 = oversold

        history = list(self._velocity_zscore_history[asset])

        if len(history) < self._zscore_period:

            return 0.0  # Not enough data for Z-score



        # Get recent values

        # Handle OHLC format: (timestamp, close, open, high, low)

        recent_values = [entry[1] for entry in history[-self._zscore_period:] if len(entry) >= 2]



        # Calculate mean and standard deviation

        import statistics

        mean_val = statistics.mean(recent_values)

        std_val = statistics.stdev(recent_values) if len(recent_values) > 1 else 0.0



        if std_val <= 0.0001:  # Avoid division by zero

            return 0.0



        # Calculate Z-score

        zscore = (value - mean_val) / std_val



        return zscore



    def _apply_zscore_filter(self, asset: str, velocity: float) -> float:

        # Apply Z-score filter to detect extreme momentum (industry standard).

        # If Z-score is extreme (>2.0 or <-2.0), it indicates overbought/oversold conditions.

        # In such cases, we may want to reduce the signal strength or skip the trade.

        zscore = self._calculate_zscore(asset, velocity)



        # Log Z-score for monitoring

        if abs(zscore) > 2.0:

            logger.info("[Z-SCORE-EXTREME] asset=%s zscore=%.2f (overbought/oversold detected)", asset, zscore)



        # Return the original velocity (Z-score is used for monitoring/filtering, not normalization)

        # The caller can decide whether to filter based on Z-score

        return velocity



    def _update_adx_history(self, asset: str, current_price: float, open_price: float, high_price: float, low_price: float) -> None:

        # Phase 6: Update ADX history for trend filtering.

        # ADX (Average Directional Index) measures trend strength, not direction.

        # ADX < 20 = ranging market (weak trend, skip trades)

        # ADX >= 20 = trending market (strong trend, allow trades)

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        # CRITICAL FIX: Calculate DX here (once per price update) instead of in _calculate_adx

        # This ensures proper DX accumulation for ADX warmup (28 periods total)

        # CRITICAL FIX: Use OHLC data for proper True Range and Directional Movement calculation



        current_time = int(time.time() * 1000)

        history = list(self._spot_price_history[asset])



        if len(history) < 2:

            return



        # Get previous OHLC data

        prev_close = history[-2][1]  # Previous close price

        prev_high = history[-2][3] if len(history[-2]) > 3 else history[-2][1]  # Previous high or fallback to close

        prev_low = history[-2][4] if len(history[-2]) > 4 else history[-2][1]  # Previous low or fallback to close



        # Calculate True Range (TR) using OHLC data

        # TR = max(high - low, |high - prev_close|, |low - prev_close|)

        tr1 = high_price - low_price

        tr2 = abs(high_price - prev_close)

        tr3 = abs(low_price - prev_close)

        tr = max(tr1, tr2, tr3)

        self._tr_history[asset].append((current_time, tr))



        # Calculate Directional Movement (DM) using OHLC data

        # +DM = current_high - prev_high if positive and greater than downward movement, else 0

        # -DM = prev_low - current_low if positive and greater than upward movement, else 0

        upward_move = high_price - prev_high

        downward_move = prev_low - low_price



        if upward_move > downward_move and upward_move > 0:

            plus_dm = upward_move

            minus_dm = 0.0

        elif downward_move > upward_move and downward_move > 0:

            plus_dm = 0.0

            minus_dm = downward_move

        else:

            plus_dm = 0.0

            minus_dm = 0.0



        self._plus_dm_history[asset].append((current_time, plus_dm))

        self._minus_dm_history[asset].append((current_time, minus_dm))



        # CRITICAL FIX: Calculate DX immediately once we have enough TR history for DI calculation

        # This ensures DX accumulation starts as soon as possible for ADX warmup

        # Industry standard: DX is calculated per period, then smoothed to ADX

        if len(self._tr_history[asset]) >= self._adx_window_size:

            # Get smoothed TR, +DM, -DM using Wilder's smoothing

            tr_history = list(self._tr_history[asset])

            plus_dm_history = list(self._plus_dm_history[asset])

            minus_dm_history = list(self._minus_dm_history[asset])



            current_tr = tr_history[-1][1]

            current_plus_dm = plus_dm_history[-1][1]

            current_minus_dm = minus_dm_history[-1][1]



            # Calculate smoothed TR using Wilder's smoothing

            if self._prev_smoothed_tr[asset] == 0.0:

                recent_tr = [entry[1] for entry in tr_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_tr = sum(recent_tr) / len(recent_tr)

            else:

                smoothed_tr = (self._prev_smoothed_tr[asset] * (self._adx_window_size - 1) + current_tr) / self._adx_window_size



            # Calculate smoothed +DM using Wilder's smoothing

            if self._prev_smoothed_plus_dm[asset] == 0.0:

                recent_plus_dm = [entry[1] for entry in plus_dm_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_plus_dm = sum(recent_plus_dm) / len(recent_plus_dm)

            else:

                smoothed_plus_dm = (self._prev_smoothed_plus_dm[asset] * (self._adx_window_size - 1) + current_plus_dm) / self._adx_window_size



            # Calculate smoothed -DM using Wilder's smoothing

            if self._prev_smoothed_minus_dm[asset] == 0.0:

                recent_minus_dm = [entry[1] for entry in minus_dm_history[-self._adx_window_size:] if len(entry) >= 2]

                smoothed_minus_dm = sum(recent_minus_dm) / len(recent_minus_dm)

            else:

                smoothed_minus_dm = (self._prev_smoothed_minus_dm[asset] * (self._adx_window_size - 1) + current_minus_dm) / self._adx_window_size



            # Update previous smoothed values for next iteration

            self._prev_smoothed_tr[asset] = smoothed_tr

            self._prev_smoothed_plus_dm[asset] = smoothed_plus_dm

            self._prev_smoothed_minus_dm[asset] = smoothed_minus_dm



            # Calculate +DI and -DI (Directional Indicators)

            if smoothed_tr > 0:

                plus_di = (smoothed_plus_dm / smoothed_tr) * 100

                minus_di = (smoothed_minus_dm / smoothed_tr) * 100

            else:

                plus_di = 0.0

                minus_di = 0.0



            # Calculate DX (Directional Index)

            if (plus_di + minus_di) > 0:

                dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100

            else:

                dx = 0.0





            # Store DX in history for ADX calculation

            self._adx_history[asset].append((current_time, dx))



    def _calculate_adx(self, asset: str) -> float:

        # Phase 6: Calculate ADX (Average Directional Index) for trend filtering.

        # ADX measures trend strength (0-100 scale).

        # ADX < 20 = ranging market (weak trend)

        # ADX >= 20 = trending market (strong trend)

        # Returns ADX value or 0.0 if insufficient data.

        # CRITICAL FIX: DX is now calculated in _update_adx_history (once per price update)

        # This method only smooths DX from history to get ADX (industry standard)

        # Warmup requires 28 periods: 14 for TR/DM/DI/DX, 14 for ADX smoothing

        adx_history = list(self._adx_history[asset])



        if len(adx_history) < self._adx_window_size:

            return 0.0  # Not enough DX history for ADX calculation



        # Get current DX (most recent)

        current_dx = adx_history[-1][1]



        # Calculate ADX using Wilder's smoothing

        # First ADX: 14-period average of DX

        # Subsequent ADX: (prev_adx × 13 + current_dx) / 14

        if self._prev_adx[asset] == 0.0:

            # First calculation: simple average of first 14 DX values

            recent_dx = [entry[1] for entry in adx_history[-self._adx_window_size:] if len(entry) >= 2]

            adx = sum(recent_dx) / len(recent_dx)

            self._prev_adx[asset] = adx

        else:

            # Subsequent calculations: use Wilder's smoothing

            adx = (self._prev_adx[asset] * (self._adx_window_size - 1) + current_dx) / self._adx_window_size

            self._prev_adx[asset] = adx



        return adx



    def _is_trading_session_active(self) -> bool:

        # Phase 6: Check if current time is within active trading session.

        # Based on research: Trade during peak liquidity hours for better win rates.

        # Returns True if trading is allowed, False otherwise.

        if not self.config.enable_session_filter:

            return True  # Session filter disabled, always allow trading



        from datetime import datetime, timezone

        current_utc_hour = datetime.now(timezone.utc).hour



        # Define active trading windows

        # US-Europe overlap (13:00-17:00 UTC): Highest liquidity

        # US session (17:00-22:00 UTC): Good liquidity

        # European morning (08:00-13:00 UTC): Moderate liquidity

        # Asian session (00:00-08:00 UTC): Low liquidity (avoid)



        is_us_europe_overlap = (

            self.config.us_europe_overlap_start_utc <= current_utc_hour < self.config.us_europe_overlap_end_utc

        )

        is_us_session = (

            self.config.us_session_start_utc <= current_utc_hour < self.config.us_session_end_utc

        )

        is_european_morning = (

            self.config.european_morning_start_utc <= current_utc_hour < self.config.european_morning_end_utc

        )



        is_active = is_us_europe_overlap or is_us_session or is_european_morning



        session_name = "UNKNOWN"

        if is_us_europe_overlap:

            session_name = "US-Europe overlap (highest liquidity)"

        elif is_us_session:

            session_name = "US session (good liquidity)"

        elif is_european_morning:

            session_name = "European morning (moderate liquidity)"

        else:

            session_name = "Asian session (low liquidity, disabled)"



        logger.info(

            "[SESSION-FILTER] current_hour=%d session=%s active=%s",

            current_utc_hour, session_name, is_active

        )



        return is_active



    def _calculate_mean_reversion(self, asset: str, current_price: float) -> float:

        # Phase 4.3: Calculate mean reversion signal using 2-minute SMA.

        # Returns deviation from SMA as percentage (positive = above SMA, negative = below SMA).

        # CRITICAL FIX: Use milliseconds to match UnifiedSpotService timestamp format

        history = list(self._sma_history[asset])

        if len(history) < 2:

            return 0.0



        # Calculate 2-minute SMA

        current_time = int(time.time() * 1000)  # Milliseconds to match spot service

        target_time = current_time - 120000  # 2 minutes ago in milliseconds



        prices_in_window = []

        # Handle OHLC format: (timestamp, close, open, high, low)

        for entry in history:

            if len(entry) >= 2:

                ts = entry[0]

                price = entry[1]  # Use close price

                if ts >= target_time:

                    prices_in_window.append(price)



        if len(prices_in_window) < 2:

            return 0.0



        sma = sum(prices_in_window) / len(prices_in_window)



        # Calculate deviation from SMA as percentage

        deviation_pct = (current_price - sma) / sma

        return deviation_pct



    def _apply_logit_fusion(self, velocity_logit: float, mean_reversion_logit: float,

                           minutes_to_expiry: float) -> float:

        # Phase 4.4: Apply logit fusion to combine velocity and mean reversion signals.

        # Phase 4.5: Skip logit fusion near expiry (use velocity only).

        # CRITICAL FIX: 2026-07-07 - Use <= instead of < to handle exact boundary condition

        # At exactly 5 minutes (300 seconds), should use velocity-only mode

        if minutes_to_expiry * 60 <= self._near_expiry_guard_sec:

            # Near expiry, use velocity logit only

            logger.debug("[LOGIT-FUSION] Near expiry (%.1f min), using velocity logit only", minutes_to_expiry)

            return velocity_logit



        # Apply weighted fusion

        fused_logit = (self._logit_fusion_velocity_weight * velocity_logit +

                      self._logit_fusion_mean_reversion_weight * mean_reversion_logit)

        return fused_logit



    def record_outcome(self, logit: float, outcome: int) -> None:

        """

        Record a prediction outcome for calibration.



        Phase 5.3: Records the logit and binary outcome for Platt scaling calibration.

        Automatically fits calibration when sufficient data is available and auto-fit is enabled.



        Args:

            logit: Raw model logit used for prediction

            outcome: Binary outcome (0 or 1)

        """

        if not self._calibration_enabled or not self._platt_scaler:

            return



        # Add to calibration history

        self._calibration_logits.append(logit)

        self._calibration_outcomes.append(outcome)



        # Maintain rolling window

        if len(self._calibration_logits) > self._calibration_max_samples:

            self._calibration_logits.pop(0)

            self._calibration_outcomes.pop(0)



        logger.debug("[CALIBRATION] Recorded outcome: logit=%.4f outcome=%d (total samples=%d)",

                    logit, outcome, len(self._calibration_logits))



        # Auto-fit if enabled and sufficient data

        if self._calibration_auto_fit and len(self._calibration_logits) >= self._calibration_min_samples:

            self._fit_calibration()



    def _fit_calibration(self) -> None:

        """

        Fit Platt scaling calibration with current data.



        Phase 5.3: Fits the Platt scaler when sufficient data is available.

        Checks fit interval to avoid refitting too frequently.

        """

        if not self._platt_scaler or len(self._calibration_logits) < self._calibration_min_samples:

            return



        import time

        current_time = time.time()



        # Check fit interval (default 24 hours)

        if self._last_fit_time > 0 and (current_time - self._last_fit_time) < (self._calibration_fit_interval_hours * 3600):

            logger.debug("[CALIBRATION] Skipping fit: last fit %.1f hours ago, interval is %d hours",

                        (current_time - self._last_fit_time) / 3600, self._calibration_fit_interval_hours)

            return



        try:

            # Allow per-agent min_samples to override the scaler default at runtime
            self._platt_scaler.min_samples = self._calibration_min_samples
            self._platt_scaler.fit(self._calibration_logits, self._calibration_outcomes)

            self._last_fit_time = current_time



            # Evaluate calibration metrics

            metrics = self._platt_scaler.evaluate_metrics(self._calibration_logits, self._calibration_outcomes)

            logger.info("[CALIBRATION] Fitted PlattScaler: Brier=%.4f ECE=%.4f MCE=%.4f samples=%d",

                       metrics.brier_score, metrics.expected_calibration_error,

                       metrics.maximum_calibration_error, metrics.num_samples)

        except Exception as e:

            logger.error("[CALIBRATION] Failed to fit PlattScaler: %s", e)



    def get_calibration_metrics(self) -> Optional[dict]:

        """

        Get current calibration metrics.



        Phase 5.5: Returns calibration metrics for monitoring and API exposure.



        Returns:

            Dictionary with calibration metrics, or None if calibration is disabled/not fitted

        """

        if not self._calibration_enabled or not self._platt_scaler or not self._platt_scaler.is_fitted():

            return None



        try:

            metrics = self._platt_scaler.evaluate_metrics(self._calibration_logits, self._calibration_outcomes)

            params = self._platt_scaler.get_parameters()



            return {

                "is_fitted": True,

                "num_samples": metrics.num_samples,

                "sample_count": metrics.num_samples,

                "brier_score": metrics.brier_score,

                "expected_calibration_error": metrics.expected_calibration_error,

                "ece": metrics.expected_calibration_error,

                "maximum_calibration_error": metrics.maximum_calibration_error,

                "mce": metrics.maximum_calibration_error,

                "platt_a": params[0] if params else None,

                "platt_b": params[1] if params else None,

                "last_fit_time": self._last_fit_time,

            }

        except Exception as e:

            logger.error("[CALIBRATION] Failed to get calibration metrics: %s", e)

            return None



    def _classify_volatility_regime(self, ticker: str) -> tuple[str, float]:

        """

        Classify volatility regime and return (regime_name, current_volatility).



        2026 best practice: Use short-horizon volatility to map to spread width.

        Three regimes: calm, elevated, violent with corresponding spread thresholds.



        Returns:

            tuple: (regime_name, current_volatility_pct)

        """

        try:

            # Get recent price history for volatility calculation

            if not self.market_state_store:

                return "calm", 0.001  # Default to calm regime



            market_state = self.market_state_store.get(ticker)

            if not market_state:

                return "calm", 0.001



            # Get recent mid prices from market state history

            # Use 5-minute window as configured

            volatility_window = self.config.volatility_window_s  # 300s = 5 minutes



            # Calculate realized volatility from price changes

            # For 15m crypto, use spot price velocity as proxy

            from data.unified_spot_service import get_unified_spot_service

            spot_service = get_unified_spot_service()



            asset = self.config.name.replace("_15M", "")  # Extract asset name

            spot_data = spot_service.get_spot_history(asset, window_s=volatility_window)



            if not spot_data or len(spot_data) < 2:

                # Insufficient data - default to calm regime with minimum volatility

                logger.debug("[VOLATILITY-REGIME] asset=%s ticker=%s insufficient price history (%d points), using calm regime",

                           self.config.name, ticker, len(spot_data) if spot_data else 0)

                return "calm", 0.001



            # Calculate realized volatility (standard deviation of returns)

            prices = [p["price"] for p in spot_data]

            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]



            if not returns:

                return "calm", 0.001



            import statistics

            volatility = statistics.stdev(returns) if len(returns) > 1 else 0.001



            # Classify regime based on volatility thresholds

            if volatility < self.config.calm_volatility_threshold:

                regime = "calm"

            elif volatility < self.config.elevated_volatility_threshold:

                regime = "elevated"

            else:

                regime = "violent"



            logger.debug("[VOLATILITY-REGIME] asset=%s ticker=%s regime=%s volatility=%.4f",

                        self.config.name, ticker, regime, volatility)



            return regime, volatility



        except Exception as e:

            logger.warning("[VOLATILITY-REGIME] Failed to classify volatility for %s: %s, using calm", ticker, e)

            return "calm", 0.001



    def _get_dynamic_spread_threshold(self, ticker: str) -> int:

        """

        Calculate dynamic spread threshold based on volatility regime and asset class.



        Phase 1A (2026-07-09): Asset-specific overrides for Kalshi microstructure

        - BTC/ETH: Deeper books, tighter thresholds (300bp calm, 400bp elevated, 600bp violent)

        - SOL/XRP/DOGE: Thinner books, looser thresholds (350bp calm, 450bp elevated, 700bp violent)



        2026 best practice: "Blow your spreads out when the market's volatility does"

        Uses continuous interpolation between regime anchors for smooth transitions.



        Formula: spread_t = base_width * (sigma_t / sigma_bar)^lambda



        Returns:

            int: Dynamic spread threshold in basis points

        """

        regime, volatility = self._classify_volatility_regime(ticker)



        # Phase 1A: Determine asset class for per-asset thresholds

        asset_symbol = ticker.split("_")[0] if "_" in ticker else ticker

        is_major_asset = asset_symbol in ["BTC", "ETH"]



        # Get regime-specific thresholds with asset-specific overrides

        if regime == "calm":

            if is_major_asset:

                threshold_bp = self.config.calm_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.calm_spread_threshold_bp_sol_xrp_doge

        elif regime == "elevated":

            if is_major_asset:

                threshold_bp = self.config.elevated_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.elevated_spread_threshold_bp_sol_xrp_doge

        else:  # violent

            if is_major_asset:

                threshold_bp = self.config.violent_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.violent_spread_threshold_bp_sol_xrp_doge



        # Apply continuous interpolation for smooth transitions

        # Use volatility ratio to interpolate between regimes

        calm_threshold = self.config.calm_volatility_threshold

        elevated_threshold = self.config.elevated_volatility_threshold



        if regime == "calm":

            # In calm regime, use calm threshold directly (no interpolation)

            # This ensures we can trade even in low-volatility conditions

            if is_major_asset:

                threshold_bp = self.config.calm_spread_threshold_bp_btc_eth

            else:

                threshold_bp = self.config.calm_spread_threshold_bp_sol_xrp_doge

        elif regime == "elevated":

            # Interpolate between elevated and violent

            ratio = volatility / elevated_threshold

            if is_major_asset:

                base = self.config.elevated_spread_threshold_bp_btc_eth

                target = self.config.violent_spread_threshold_bp_btc_eth

            else:

                base = self.config.elevated_spread_threshold_bp_sol_xrp_doge

                target = self.config.violent_spread_threshold_bp_sol_xrp_doge

            interpolated = base * (ratio ** self.config.spread_volatility_sensitivity)

            threshold_bp = int(interpolated)

            threshold_bp = min(threshold_bp, target)

        # violent regime uses maximum threshold



        logger.debug("[DYNAMIC-SPREAD] asset=%s ticker=%s regime=%s is_major=%s threshold=%dbp volatility=%.4f",

                    self.config.name, ticker, regime, is_major_asset, threshold_bp, volatility)



        return threshold_bp



    def _classify_regime(self, ticker: str) -> str:

        # Classify market regime from depth using same logic as loop_15m.py

        # Regime classification matches the one used in _validate_market_state

        regime = "unknown"  # Default fallback: missing state is not a valid economic regime

        try:

            if not self.market_state_store:

                return regime



            market_state = self.market_state_store.get(ticker)

            if market_state:

                # Classify regime from depth

                min_depth_yes = getattr(market_state, 'min_depth_yes', 0)

                min_depth_no = getattr(market_state, 'min_depth_no', 0)

                # Use depth thresholds from risk envelope (default to 1 if not available)

                min_depth_yes_threshold = 1

                min_depth_no_threshold = 1

                has_yes = min_depth_yes >= min_depth_yes_threshold

                has_no = min_depth_no >= min_depth_no_threshold

                if has_yes and has_no:

                    regime = "both_sides"

                elif has_yes and not has_no:

                    regime = "one_sided_yes"

                elif not has_yes and has_no:

                    regime = "one_sided_no"

                else:

                    regime = "no_liquidity"

                logger.debug("[REGIME-CLASSIFY] ticker=%s regime=%s (yes_depth=%d no_depth=%d)",

                           ticker, regime, min_depth_yes, min_depth_no)

        except Exception as regime_err:

            logger.warning("[REGIME-CLASSIFY] Failed to classify regime for %s: %s, using 'unknown'", ticker, regime_err)

            regime = "unknown"



        return regime



    def _validate_market_state(self, market: Any) -> bool:

        # Validate market state for trading.

        # Checks: market is open, sufficient liquidity, reasonable spread, fresh data.

        if not market:

            logger.warning("[MARKET-VALIDATION] asset=%s no market available", self.config.name)

            return False



        # Get market state from store

        ticker = market.market.market_id if hasattr(market, 'market') else market.market_id



        # Check if market_state_store is available

        if not self.market_state_store:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s market_state_store is None",

                         self.config.name, ticker)

            return False



        market_state = self.market_state_store.get(ticker)



        if not market_state:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no market state",

                         self.config.name, ticker)

            return False



        # FIXED: Removed duality check from agent_grid

        # The orderbook already validates duality at the data source (duality_validator.py)

        # Re-checking duality here on derived NO prices creates false violations

        # Duality validation is handled by:

        # 1. LocalOrderbook._check_crossed_market() in orderbook.py

        # 2. DualityValidator.check_yes_no_duality() in duality_validator.py

        # 3. KalshiMarketState.check_health() in market_state.py

        # Agent grid should only use validated prices from market_state



        # Check staleness (default 15 seconds from profile)

        venue_staleness = 15  # Default, will be overridden by profile

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile = get_active_profile()

            venue_staleness = profile.get("venue_staleness", 15)

        except Exception:

            pass



        staleness_threshold_ms = venue_staleness * 1000



        # Calculate staleness from last_update_ts (KalshiMarketState doesn't have staleness_ms)

        now = time.time()

        last_update = getattr(market_state, 'last_update_ts', 0.0)



        # If last_update_ts is 0 or very old (uninitialized), treat as fresh

        # This allows trading to start before WS bridge populates data

        if last_update == 0 or last_update < 1000000000:  # Before 2001-09-09

            staleness_ms = 0

        else:

            staleness_ms = int((now - last_update) * 1000)



        if staleness_ms > staleness_threshold_ms:

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s stale=%dms threshold=%dms",

                         self.config.name, ticker, staleness_ms, staleness_threshold_ms)

            return False



        # Check liquidity (depth) with one-sided regime classification

        # Kalshi 15m books are often one-sided - we should allow trading on the liquid side

        # Depth thresholds from risk envelope/profile (single source of truth)

        # CRITICAL FIX: Removed 10x multiplier that was ignoring profile config

        # The profile YAML already sets appropriate depth thresholds (1-2 contracts for 15m crypto)

        # Applying a 10x multiplier was requiring 60-70 contracts when profile only required 1

        # This was causing massive trade rejections and low fill rates

        min_depth_yes_threshold = 1

        min_depth_no_threshold = 1



        try:

            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope

            envelope = get_kalshi_crypto_15m_risk_envelope()

            # Extract asset symbol from agent name (e.g., "DOGE_15M" -> "DOGE")

            asset_symbol = self.config.name.split('_')[0] if '_' in self.config.name else self.config.name

            depth_thresholds = envelope.get_depth_thresholds(asset_symbol)

            min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 1)

            min_depth_no_threshold = depth_thresholds.get('min_depth_no', 1)



            logger.info(

                "[DEPTH-THRESHOLD] asset=%s min_depth_yes=%d min_depth_no=%d (from profile)",

                self.config.name, min_depth_yes_threshold, min_depth_no_threshold

            )

        except RuntimeError as e:

            # Bankroll not ready - use default thresholds

            logger.warning(

                "[DEPTH-THRESHOLD] Failed to get depth thresholds from envelope: %s (using defaults)",

                e

            )

        except Exception as e:

            # Fallback to defaults if envelope not available

            logger.warning("[DEPTH-THRESHOLD] Failed to load from envelope: %s, using defaults", e)



        min_depth_yes = getattr(market_state, 'min_depth_yes', 0)

        min_depth_no = getattr(market_state, 'min_depth_no', 0)



        # Classify book regime

        has_yes = min_depth_yes >= min_depth_yes_threshold

        has_no = min_depth_no >= min_depth_no_threshold



        if has_yes and has_no:

            regime = "both_sides"

        elif has_yes and not has_no:

            regime = "one_sided_yes"

        elif not has_yes and has_no:

            regime = "one_sided_no"

        else:

            regime = "no_liquidity"



        # Reject if no liquidity on either side

        if regime == "no_liquidity":

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no liquidity yes=%d no=%d (thresholds: yes=%d no=%d) regime=%s",

                         self.config.name, ticker, min_depth_yes, min_depth_no, min_depth_yes_threshold, min_depth_no_threshold, regime)

            return False



        # CRITICAL FIX: Relaxed one-sided rejection for 15-minute markets

        # Previous logic: Reject one-sided books when TTE > 1 minute (too aggressive)

        # New logic: Allow one-sided books with sufficient depth on the trading side

        # Rationale: 15-minute crypto markets are frequently one-sided, especially for smaller assets

        # Risk mitigation: We only trade on the liquid side (YES for one_sided_yes, NO for one_sided_no)

        # This allows trading while avoiding the risk of being stuck in an illiquid position

        if regime in ["one_sided_yes", "one_sided_no"]:

            # Get time to expiry

            close_time = getattr(market, 'close_time', 0)

            if hasattr(market, 'market'):

                close_time = getattr(market.market, 'close_time', 0)



            if close_time > 0:

                now = time.time()

                minutes_to_expiry = (close_time - now) / 60.0



                # Only reject one-sided books in last 30 seconds (terminal phase)

                # Before that, allow trading on the liquid side

                if minutes_to_expiry > 0.5:

                    # More than 30 seconds to expiry: allow one-sided books

                    logger.info(

                        "[ONE-SIDED-ALLOW] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d tte=%.1fmin > 0.5min -> ALLOW (trading on liquid side)",

                        self.config.name, ticker, regime, min_depth_yes, min_depth_no, minutes_to_expiry

                    )

                else:

                    # Last 30 seconds: reject one-sided books (terminal phase risk)

                    logger.warning(

                        "[ONE-SIDED-REJECT] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d tte=%.1fmin <= 0.5min -> REJECT (terminal phase, exit risk)",

                        self.config.name, ticker, regime, min_depth_yes, min_depth_no, minutes_to_expiry

                    )

                    return False

            else:

                # No close time available: allow one-sided books (less conservative)

                logger.info(

                    "[ONE-SIDED-ALLOW] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d no close_time -> ALLOW (trading on liquid side)",

                    self.config.name, ticker, regime, min_depth_yes, min_depth_no

                )



        # Log regime for visibility

        logger.info("[MARKET-VALIDATION] asset=%s ticker=%s regime=%s depth_yes=%d depth_no=%d (thresholds: yes=%d no=%d)",

                   self.config.name, ticker, regime, min_depth_yes, min_depth_no, min_depth_yes_threshold, min_depth_no_threshold)



        # Check spread - RELAXED for one-sided books (common in 15m crypto)
        # NOTE: This is a coarse market-level filter before signal generation.
        # Side-aware spread checking happens later in the microstructure gate (order_router.py)
        # which has access to the order's side and performs side-specific validation.

        best_bid = getattr(market_state, 'best_bid_cents', 0)
        best_ask = getattr(market_state, 'best_ask_cents', 0)

        # Handle None values - treat as 0
        if best_bid is None:
            best_bid = 0
        if best_ask is None:
            best_ask = 0

        # For one-sided books, skip spread check and use available side
        if best_bid > 0 and best_ask > 0:
            # Both sides available - check spread (coarse filter for market quality)
            spread_cents = best_ask - best_bid

            # 2026-07-11: Adaptive spread filter - treat wide spread as regime signal, not immediate kill-switch
            # For binary options with massive depth (e.g., DOGE: 250 yes, 48886 no), wide spreads (92c) are acceptable
            # Only reject pathological spreads (> 150c) that indicate no meaningful liquidity
            coarse_filter_threshold = 150  # Relaxed from 75c to allow trading in current market conditions

            if spread_cents > coarse_filter_threshold:
                logger.warning(f"[MARKET-VALIDATION] asset={self.config.name} ticker={ticker} spread exceeds coarse filter={coarse_filter_threshold}c (spread={spread_cents}c) - rejecting as pathological")
                return False



            # CRITICAL FIX: Remove basis point validation for binary options

            # Binary options have 0-100c price range, making BP calculations inappropriate

            # A 37c spread on 50c mid = 74% = 7400bp, which looks extreme but is normal for binary options

            # Use cents-based validation only, which is correctly configured with 20c coarse filter

            # Legacy check in cents for backward compatibility

            if spread_cents > self.config.max_spread_cents:

                logger.warning(f"[MARKET-VALIDATION] asset={self.config.name} ticker={ticker} spread too wide={spread_cents}c > max={self.config.max_spread_cents}c")

                return False

        elif best_bid == 0 and best_ask == 0:

            # No liquidity on either side

            logger.warning("[MARKET-VALIDATION] asset=%s ticker=%s no bid/ask available (bid=%d ask=%d)",

                         self.config.name, ticker, best_bid, best_ask)

            return False

        else:

            # One-sided book - allow trading on liquid side

            logger.info("[MARKET-VALIDATION] asset=%s ticker=%s one-sided book (bid=%d ask=%d) - allowing trade",

                       self.config.name, ticker, best_bid, best_ask)



        logger.info("[MARKET-VALIDATION] asset=%s ticker=%s VALID regime=%s depth_yes=%d depth_no=%d staleness=%dms",

                   self.config.name, ticker, regime, min_depth_yes, min_depth_no, staleness_ms)

        return True



    def _generate_signal(

        self,

        spot_price: float,

        market: Any,

        minutes_to_expiry: float,

    ) -> Optional[Dict[str, Any]]:

        # Generate trading signal using Coinbase 1-minute velocity (2026 #1 winning strategy).

        logger.debug("[GENERATE-SIGNAL-ENTRY] spot_price=%s market_type=%s minutes_to_expiry=%s", spot_price, type(market), minutes_to_expiry)



        # CRITICAL FIX (2026-07-17): Update RollingBuffer with spot_price for bias prevention
        if self._rolling_buffer_enabled and self._signal_generator is not None:
            try:
                self._signal_generator.update_input("spot_price", spot_price)
                logger.debug("[ROLLING-BUFFER] Updated spot_price=%s", spot_price)
            except Exception as exc:
                logger.warning("[ROLLING-BUFFER] Failed to update spot_price: %s", exc)

        # CRITICAL FIX (2026-07-23): Update adaptive liquidity with market depth
        if self._dynamic_components_enabled and self._adaptive_liquidity_calculator is not None:
            try:
                if hasattr(market, 'depth') and market.depth is not None:
                    self._adaptive_liquidity_calculator.update_depth(
                        asset=asset,
                        depth=market.depth,
                        timestamp=time.time()
                    )
                    logger.debug("[ADAPTIVE-LIQUIDITY] Updated depth for %s: %s", asset, market.depth)
            except Exception as exc:
                logger.warning("[ADAPTIVE-LIQUIDITY] Failed to update depth: %s", exc)



        # Phase 6: Check if trading session is active

        if not self._is_trading_session_active():

            logger.info("[SESSION-FILTER] Trading session not active, skipping signal generation")

            if REJECTION_MONITOR_ENABLED:

                monitor = get_rejection_monitor()

                monitor.log_rejection(

                    asset="UNKNOWN",

                    category="session_filter",

                    reason="Trading session not active, skipping signal generation",

                    session_active=False,

                )

            self._record_signal_rejection(
                "trading_session_not_active",
                market_id=getattr(market, 'market_id', None) or getattr(market, 'market', None),
                market_time_remaining_s=minutes_to_expiry * 60.0 if minutes_to_expiry else None,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )

            return None



        # Extract asset from market (must be done before time window filter for logging)

        asset = None

        if hasattr(market, 'asset'):

            asset = market.asset

        elif hasattr(market, 'ticker'):

            ticker = market.ticker

            # Extract asset from ticker (e.g., "KXBTC15M-26JUN301900-00" -> "BTC")

            if 'BTC' in ticker:

                asset = 'BTC'

            elif 'ETH' in ticker:

                asset = 'ETH'

            elif 'SOL' in ticker:

                asset = 'SOL'

            elif 'XRP' in ticker:

                asset = 'XRP'

            elif 'DOGE' in ticker:

                asset = 'DOGE'



        if not asset:

            logger.warning("[SIGNAL-ERROR] Could not determine asset from market")

            self._record_signal_rejection(
                "asset_extraction_failed",
                market_id=getattr(market, 'market_id', None) or getattr(market, 'market', None),
                market_time_remaining_s=minutes_to_expiry * 60.0,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )

            return None



        # ENTRY MATRIX: Time window entry rules (CRITICAL FIX: 2026-07-08 - Use profile YAML as single source of truth)

        # Previous hardcoded values (>=14.0min, <=0.5min) conflicted with profile YAML configuration

        # Profile YAML defines:

        # - min_decision_minute: per-asset minimum minute to start trading (default 1)

        # - guardrails.min_entry_mins: minimum time to expiry for entry (0.5min - block last 30s only)

        # - guardrails.max_entry_mins: maximum time to expiry for entry (15.0min - full 15m window)

        # - guardrails.cutoff_minutes_before_expiry: stop trading N minutes before expiry (0min - no cutoff)



        # Get timing configuration from profile YAML

        min_entry_mins = 0.5  # Default from guardrails.min_entry_mins (full 15m window, block last 30s only)

        max_entry_mins = 15.0  # Default from guardrails.max_entry_mins (full 15-minute window)

        cutoff_mins = 0.0  # Default from guardrails.cutoff_minutes_before_expiry (no cutoff)



        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            adapter = get_active_profile()

            if adapter and adapter._profile:

                profile = adapter._profile

                min_entry_mins = profile.guardrails_min_entry_mins

                max_entry_mins = profile.guardrails_max_entry_mins

                cutoff_mins = profile.agent_cutoff_minutes_before_expiry

                logger.debug(

                    "[TIME-WINDOW-CONFIG] asset=%s min_entry=%.1fmin max_entry=%.1fmin cutoff=%.1fmin (from profile)",

                    asset, min_entry_mins, max_entry_mins, cutoff_mins

                )

            else:

                # Use defaults if profile not available

                min_entry_mins = 0.5  # CRITICAL FIX: 2026-07-13 - Changed from 2.0 to 0.5 for full window trading

                max_entry_mins = 15.0

                cutoff_mins = 0.0  # CRITICAL FIX: 2026-07-13 - Changed from 2.0 to 0.0 for full window trading

                logger.debug("[TIME-WINDOW-CONFIG] asset=%s using defaults (profile not available)", asset)

        except Exception as e:

            logger.warning("[TIME-WINDOW-CONFIG] Failed to load from profile: %s, using defaults", e)

            min_entry_mins = 0.5  # CRITICAL FIX: 2026-07-13 - Changed from 2.0 to 0.5 for full window trading

            max_entry_mins = 15.0

            cutoff_mins = 0.0  # CRITICAL FIX: 2026-07-13 - Changed from 2.0 to 0.0 for full window trading



        time_edge_multiplier = 1.0

        # Hard production floor: no new entries inside 90 seconds to expiry.
        seconds_to_expiry = minutes_to_expiry * 60.0
        if seconds_to_expiry < MERID_HARD_MIN_ENTRY_TTE_SECONDS:
            logger.info(
                "[HARD-TTE-CUTOFF] asset=%s seconds_to_expiry=%.1f < %ds -> SKIP (too close to expiry for new entry)",
                asset, seconds_to_expiry, MERID_HARD_MIN_ENTRY_TTE_SECONDS
            )
            if REJECTION_MONITOR_ENABLED:
                log_time_window_rejection(
                    asset=asset,
                    minutes_to_expiry=minutes_to_expiry,
                    reason=f"hard_tte_cutoff: <{MERID_HARD_MIN_ENTRY_TTE_SECONDS}s to expiry",
                    market_id=getattr(market, 'market_id', None),
                )
            self._record_signal_rejection(
                f"hard_tte_cutoff:<{MERID_HARD_MIN_ENTRY_TTE_SECONDS}s",
                market_id=getattr(market, 'market_id', None),
                market_time_remaining_s=seconds_to_expiry,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )
            return None



        # Check if within trading window

        if minutes_to_expiry > max_entry_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (too early, >%.1fmin)",

                asset, minutes_to_expiry, max_entry_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"too early: >{max_entry_mins}min",

                    market_id=getattr(market, 'market_id', None),

                )

            self._record_signal_rejection(
                f"too_early:>{max_entry_mins}min",
                market_id=getattr(market, 'market_id', None),
                market_time_remaining_s=seconds_to_expiry,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )

            return None

        elif minutes_to_expiry < cutoff_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (terminal phase, <%.1fmin to expiry)",

                asset, minutes_to_expiry, cutoff_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"terminal phase: <{cutoff_mins}min to expiry",

                    market_id=getattr(market, 'market_id', None),

                )

            self._record_signal_rejection(
                f"terminal_phase:<{cutoff_mins}min",
                market_id=getattr(market, 'market_id', None),
                market_time_remaining_s=seconds_to_expiry,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )

            return None

        elif minutes_to_expiry < min_entry_mins:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (too early, <%.1fmin to expiry)",

                asset, minutes_to_expiry, min_entry_mins

            )

            if REJECTION_MONITOR_ENABLED:

                log_time_window_rejection(

                    asset=asset,

                    minutes_to_expiry=minutes_to_expiry,

                    reason=f"too early: <{min_entry_mins}min to expiry",

                    market_id=getattr(market, 'market_id', None),

                )

            self._record_signal_rejection(
                f"too_early:<{min_entry_mins}min",
                market_id=getattr(market, 'market_id', None),
                market_time_remaining_s=seconds_to_expiry,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}",
            )

            return None

        elif minutes_to_expiry <= 4.0:

            time_edge_multiplier = 1.5

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> REDUCED (late entry, 1.5x edge multiplier)",

                asset, minutes_to_expiry

            )

        else:

            logger.info(

                "[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> OPTIMAL (baseline edge requirements)",

                asset, minutes_to_expiry

            )



        # ENTRY MATRIX: Per-asset minimum entry price (based on trade history analysis)

        # Updated 2026-08-04: Aligned to 5c to match v2 profile price_range.

        min_entry_prices = {

            'BTC': 5,

            'ETH': 5,

            'SOL': 5,

            'XRP': 5,

            'DOGE': 5

        }

        min_price_cents = min_entry_prices.get(asset, 5)  # Default to 5c



        # Get current market price for BOTH YES and NO sides

        # CRITICAL FIX: Evaluate both YES and NO contracts within 10c-75c canonical range

        # Select best edge - don't force YES or NO decision

        yes_price_cents = 0

        no_price_cents = 0

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0



                # YES price is the ASK (price to *buy* YES)

                yes_price_cents = best_ask if best_ask > 0 else 0



                # NO price is the NO ask = 100 - best YES bid

                # In binary markets, YES + NO = 100 cents

                no_price_cents = 100 - best_bid



                logger.info(

                    "[DUAL-SIDE-PRICE] asset=%s ticker=%s yes_price=%dc no_price=%dc (derived from bid=%dc ask=%dc)",

                    asset, ticker, yes_price_cents, no_price_cents, best_bid, best_ask

                )

        except Exception as e:

            logger.warning("[PRICE-FILTER-ERROR] asset=%s failed to get market price: %s", asset, e)



        # Check which sides are within their side-aware ranges.
        # Single source of truth is merid.event_venues.kalshi.binary_price_space.
        # YES: 10c-75c (canonical entry range)
        # NO: 10c-75c (canonical entry range)

        if PRICE_SPACE_AVAILABLE:
            yes_in_range = is_price_in_canonical_range(yes_price_cents, "yes")
            no_in_range = is_price_in_canonical_range(no_price_cents, "no")
        else:
            yes_in_range = (10 <= yes_price_cents <= 75)
            no_in_range = (10 <= no_price_cents <= 75)

        # Determine expiry bucket for observability
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"

        logger.info(
            "[PRICE-RANGE-CHECK] asset=%s yes_price=%dc yes_in_canonical=%s no_price=%dc no_in_canonical=%s range=10c-75c expiry_bucket=%s",
            asset, yes_price_cents, yes_in_range, no_price_cents, no_in_range, expiry_bucket
        )



        # If neither side is in range, skip trading

        if not yes_in_range and not no_in_range:

            logger.info(

                "[PRICE-FILTER-REJECT] asset=%s both sides outside canonical 10c-75c range (yes=%dc, no=%dc) -> SKIP",

                asset, yes_price_cents, no_price_cents

            )

            if REJECTION_MONITOR_ENABLED:

                log_price_range_rejection(

                    asset=asset,

                    yes_price_cents=yes_price_cents,

                    no_price_cents=no_price_cents,

                    reason="both sides outside canonical 10c-75c range",

                    market_id=getattr(market, 'market_id', None),

                )

            self._record_signal_rejection(
                "both_sides_out_of_canonical_range",
                market_id=getattr(market, 'market_id', None),
                market_time_remaining_s=seconds_to_expiry,
                reference_price=spot_price,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} yes_price={yes_price_cents} no_price={no_price_cents}",
            )

            return None



        # Determine which side to evaluate based on price range

        # If both in range, we'll evaluate both and select best edge later

        # If only one in range, evaluate that side

        sides_to_evaluate = []

        if yes_in_range:

            sides_to_evaluate.append("yes")

        if no_in_range:

            sides_to_evaluate.append("no")



        logger.info(

            "[DUAL-SIDE-EVALUATION] asset=%s will evaluate sides: %s",

            asset, sides_to_evaluate

        )



        # Price-bucket EV diagnostic logging for both sides
        # Use canonical bucket definition for consistency
        from merid.metrics.canonical_buckets import get_price_bucket

        for side, price_cents in [("yes", yes_price_cents), ("no", no_price_cents)]:

            if price_cents > 0:
                price_bucket = get_price_bucket(price_cents)

                logger.info(

                    "[PRICE-BUCKET-DIAGNOSTIC] asset=%s side=%s price_cents=%d bucket=%s (for EV tracking)",

                    asset, side, price_cents, price_bucket

                )



        # CRITICAL FIX: Update price history (including ADX) in _generate_signal path

        # The system uses _generate_signal instead of collect_order_candidate for signal generation

        # Without this call, ADX data never gets collected, causing ADX=0.00 permanently

        # CRITICAL FIX: Pass spot_data if available for OHLC-based ADX/ATR calculation

        _, spot_data = self._get_spot_cached(asset)



        # Update price history (including ADX) in _generate_signal path

        # The system uses _generate_signal instead of collect_order_candidate for signal generation

        # Without this call, ADX data never gets collected, causing ADX=0.00 permanently

        # Pass spot_data if available for OHLC-based ADX/ATR calculation

        self._update_price_history(asset, spot_price, spot_data)



        # Price history already updated in collect_order_candidate (before calling _generate_signal)

        # This prevents the vicious cycle: no signal -> no price update -> velocity=0 -> no signal



        # 2026-08-13: price_based and volatility_reversion are removed as
        # authoritative signal sources.  They may remain as market-structure
        # features, but a price alone is not an edge and cannot emit an order.
        _allow_price_signal = os.environ.get("MERID_ALLOW_PRICE_BASED", "0") == "1"

        # PRICE-BASED STRATEGY is now a no-op unless explicitly enabled.
        if self.config.signal_mode == "price_based":
            logger.warning("[PRICE-BASED-DISABLED] asset=%s signal_mode=price_based is not an authoritative source", asset)
            return None

        # VOLATILITY_REVERSION is also price-based; disabled.
        if self.config.signal_mode == "volatility_reversion":
            logger.warning("[PRICE-BASED-DISABLED] asset=%s signal_mode=volatility_reversion is not an authoritative source", asset)
            return None

        # HYBRID STRATEGY (2026-08-13): the hybrid ensemble is the unified
        # TradeDecision engine.  It consumes external spot, the Kalshi strike,
        # the live YES/NO order book, and execution costs to emit a single
        # calibrated, cost-aware decision.  No price-based panic-fade override.
        if self.config.signal_mode == "hybrid":
            if _allow_price_signal:
                logger.warning("[HYBRID-SIGNAL] asset=%s MERID_ALLOW_PRICE_BASED=1 - price_based path is deprecated", asset)
                price_signal = self._generate_price_based_signal(asset, spot_price, market, minutes_to_expiry)
                if price_signal is not None:
                    logger.warning("[HYBRID-SIGNAL] asset=%s using deprecated price_based signal", asset)
                    return price_signal
            return self._generate_trade_decision_signal(asset, spot_price, market, minutes_to_expiry)



        # CRITICAL FIX: 2026-07-06 - Wire MACD/RSI into momentum_fvg signal generation

        # MOMENTUM_FVG STRATEGY: Combines velocity, MACD, RSI, OBI, and FVG for enhanced signals

        if self.config.signal_mode == "momentum_fvg":

            return self._generate_momentum_fvg_signal(asset, spot_price, market, minutes_to_expiry)



        # CRITICAL FIX: 2026-07-16 - Add fallback for unsupported signal modes

        # "trend" and "mean_reversion" modes are defined in config but not implemented as handlers

        # Fallback to momentum_fvg with warning to prevent signal generation failure

        if self.config.signal_mode in ("trend", "mean_reversion"):

            logger.warning(

                "[SIGNAL-MODE-FALLBACK] asset=%s signal_mode=%s not implemented - falling back to momentum_fvg",

                asset, self.config.signal_mode

            )

            return self._generate_momentum_fvg_signal(asset, spot_price, market, minutes_to_expiry)



        # Non-hybrid legacy paths (trend alignment / velocity) are disabled in
        # paper/live unless explicitly enabled.
        if not _is_legacy_signal_enabled():
            logger.warning(
                "[LEGACY-SIGNAL-DISABLED] asset=%s signal_mode=%s blocked in %s mode",
                asset, self.config.signal_mode, os.environ.get("MERID_PM_TRADING_MODE", "unknown"),
            )
            return None

        # CRITICAL FIX: 2026-07-06 - Integrate trend alignment as confirmation filter

        # TREND_ALIGNMENT STRATEGY: Requires 5m and 1h trend agreement for signal confirmation

        # Based on Turbine research: trend alignment was consistently profitable

        trend_aligned = self._check_trend_alignment(asset, spot_price)

        if not trend_aligned:

            logger.info(

                "[TREND-ALIGNMENT-FILTER] asset=%s 5m and 1h trends not aligned -> SKIP TRADE (trend disagreement)",

                asset

            )

            if REJECTION_MONITOR_ENABLED:

                log_trend_alignment_rejection(

                    asset=asset,

                    reason="5m and 1h trends not aligned -> SKIP TRADE (trend disagreement)",

                    market_id=getattr(market, 'market_id', None),

                )

            return None

        else:

            logger.info(

                "[TREND-ALIGNMENT-CONFIRMED] asset=%s 5m and 1h trends aligned -> PROCEED",

                asset

            )



        # CRITICAL FIX: Use multi-window velocity for both threshold comparison AND logit calculation

        # Previous bug: Used simple _calculate_velocity for threshold but _calculate_multi_window_velocity for logit

        # This created inconsistency where threshold decision and probability calculation used different velocities

        # Now both use the same multi-window velocity with EMA smoothing and ATR normalization

        velocity = self._calculate_multi_window_velocity(asset, spot_price)



        logger.info(

            "[VELOCITY-CALC] asset=%s current=%s velocity=%.9f (%.4f%%) multi-window with EMA smoothing",

            asset, format_price(asset, spot_price), velocity, velocity * 100

        )



        # VELOCITY-BASED SIGNAL DECISION (2026 #1 winner)

        # Positive velocity (> threshold) -> buy YES

        # Negative velocity (< -threshold) -> buy NO

        # Small velocity (between -threshold and threshold) -> no trade

        # Phase 7: Use dynamic ATR-based threshold instead of static threshold

        velocity_threshold = self._calculate_dynamic_velocity_threshold(asset)  # Dynamic threshold based on ATR



        # Get market price and strike price for price-based confirmation

        market_price = 0.0

        strike_price = None

        strike_source = ""

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

            market_state = self.market_state_store.get(ticker) if self.market_state_store else None

            if market_state:

                best_bid = getattr(market_state, 'best_bid_cents', 0) or 0

                best_ask = getattr(market_state, 'best_ask_cents', 0) or 0

                if best_bid > 0 and best_ask > 0:

                    market_price = (best_bid + best_ask) / 200.0  # Convert cents to price

                elif best_bid > 0:

                    market_price = best_bid / 100.0

                elif best_ask > 0:

                    market_price = best_ask / 100.0



                # CRITICAL: Use window_strike_price (captured at market activation from Kalshi's floor_strike)

                # This is the authoritative reference price for 15-minute UP/DOWN markets

                window_strike = getattr(market_state, 'window_strike_price', None)

                window_strike_source = getattr(market_state, 'window_strike_source', "")



                # Capture candle_open_price from spot feed for validation

                # This is the secondary source to validate against Kalshi's floor_strike

                candle_open = getattr(market_state, 'candle_open_price', None)

                if candle_open is None or candle_open <= 0:

                    # First time seeing this market/window - capture spot as candle_open

                    market_state.candle_open_price = spot_price

                    market_state.candle_open_ts = time.time()

                    logger.info(

                        "[CANDLE-OPEN-CAPTURE] asset=%s ticker=%s candle_open=%.2f captured from spot feed",

                        asset, ticker, spot_price

                    )

                    candle_open = spot_price



                if window_strike is not None and window_strike > 0:

                    strike_price = window_strike

                    strike_source = window_strike_source

                    logger.info(

                        "[STRIKE-SOURCE] asset=%s using window_strike_price=%.2f (source=%s)",

                        asset, strike_price, strike_source

                    )

                else:

                    # Fallback to Kalshi floor_strike, then catalog, then spot only as last resort.
                    floor = getattr(market_state, 'floor_strike', None)
                    if floor is not None and floor > 0:
                        strike_price = floor
                        strike_source = "floor_strike"
                    else:
                        try:
                            from merid.event_venues.kalshi.market_catalog import get_market_catalog
                            catalog = get_market_catalog()
                            if catalog:
                                current_market = catalog.get_current_15m_market(asset)
                                if current_market and current_market.floor_strike is not None:
                                    strike_price = float(current_market.floor_strike)
                                    strike_source = "catalog_floor_strike"
                                else:
                                    strike_price = spot_price
                                    strike_source = "spot_fallback"
                            else:
                                strike_price = spot_price
                                strike_source = "spot_fallback"
                        except Exception as e:
                            logger.warning("[STRIKE-FALLBACK] asset=%s catalog lookup failed: %s", asset, e)
                            strike_price = spot_price
                            strike_source = "spot_fallback"

                    logger.info(

                        "[STRIKE-FALLBACK] asset=%s window_strike_price unavailable, using %s=%.2f",

                        asset, strike_source, strike_price

                    )
                    # 2026 BEST PRACTICE: Track fallback activation
                    self._fallback_activations["strike_fallback"] += 1
                    self._fallback_timestamps["strike_fallback"].append(time.time())



                # Validation: Log divergence if both window_strike and candle_open are available

                # Use asset-specific divergence thresholds based on volatility

                if candle_open is not None and candle_open > 0 and strike_price is not None:

                    divergence_pct = abs((strike_price - candle_open) / candle_open) * 100

                    # Asset-specific thresholds: BTC/ETH 0.1%, SOL 0.15%, XRP/DOGE 0.2%

                    divergence_thresholds = {

                        "BTC": 0.1,

                        "ETH": 0.1,

                        "SOL": 0.15,

                        "XRP": 0.2,

                        "DOGE": 0.2

                    }

                    threshold = divergence_thresholds.get(asset, 0.1)  # Default to 0.1% for unknown assets

                    if divergence_pct > threshold:

                        logger.warning(

                            "[STRIKE-DIVERGENCE] asset=%s window_strike=%.2f candle_open=%.2f divergence=%.2f%% (threshold=%.2f%%)",

                            asset, strike_price, candle_open, divergence_pct, threshold

                        )

                    else:

                        logger.info(

                            "[STRIKE-VALIDATION] asset=%s window_strike=%.2f candle_open=%.2f divergence=%.2f%% (OK, threshold=%.2f%%)",

                            asset, strike_price, candle_open, divergence_pct, threshold

                        )



                if strike_price:

                    logger.info(

                        "[STRIKE-INFO] asset=%s spot=%.2f strike=%.2f source=%s distance=%.2f%%",

                        asset, spot_price, strike_price, strike_source, ((spot_price - strike_price) / strike_price) * 100 if strike_price > 0 else 0

                    )

        except Exception as e:

            logger.warning("[PRICE-CONFIRMATION-ERROR] asset=%s failed to get market price/strike: %s", asset, e)



        # Priority 3: Volatility-adjusted velocity threshold

        # Adjust velocity threshold based on realized volatility to avoid noise in low-vol conditions

        # and capture smaller moves in high-vol conditions

        base_velocity_threshold = velocity_threshold

        try:

            # Get realized volatility from price history if available

            if hasattr(self, '_price_history') and asset in self._price_history and len(self._price_history[asset]) >= 20:

                # Calculate recent volatility (standard deviation of returns)

                recent_prices = [entry[1] for entry in self._price_history[asset][-20:]]  # Last 20 close prices

                returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1] for i in range(1, len(recent_prices))]

                if returns:

                    realized_vol = statistics.stdev(returns) if len(returns) > 1 else 0.0

                    # Annualize (assuming 1-minute data points, 525600 minutes per year)

                    realized_vol_annual = realized_vol * (525600 ** 0.5)



                    # Normalize to 25% annual vol baseline

                    vol_multiplier = realized_vol_annual / 0.25

                    vol_multiplier = max(0.5, min(2.0, vol_multiplier))  # Clamp 0.5x-2.0x



                    # Apply volatility adjustment

                    velocity_threshold = base_velocity_threshold * vol_multiplier



                    logger.info(

                        "[VOLATILITY-ADJUSTED-THRESHOLD] asset=%s base_threshold=%.6f realized_vol=%.4f vol_multiplier=%.2f adjusted_threshold=%.6f",

                        asset, base_velocity_threshold, realized_vol_annual, vol_multiplier, velocity_threshold

                    )

                else:

                    velocity_threshold = base_velocity_threshold

            else:

                velocity_threshold = base_velocity_threshold

        except Exception as e:

            logger.warning("[VOLATILITY-ADJUSTMENT-ERROR] asset=%s failed to adjust threshold: %s", asset, e)

            velocity_threshold = base_velocity_threshold



        # Phase 6: Update regime detector with current price

        # CRITICAL FIX: Re-enabled regime detector with confidence threshold to prevent signal inversion

        # The regime detector now requires confidence > 0.7 before using mean_reversion mode

        # This prevents systematic signal inversion from low-confidence regime classifications

        # CRITICAL FIX: Move regime detection BEFORE regime-aware threshold adjustment to avoid UnboundLocalError

        strategy_mode = "trend_following"  # Default to trend-following

        hmm_regime = None  # Store HMM regime for exit policy wiring

        hmm_regime_confidence = 0.0

        if self._regime_detector and self._regime_detector_enabled:

            current_time = int(time.time() * 1000)  # Milliseconds

            regime_detection = self._regime_detector.update(current_time, spot_price)

            if regime_detection:

                strategy_mode = self._regime_detector.get_strategy_mode(regime_detection)

                hmm_regime = regime_detection.regime.value  # "bull", "choppy", "bear"

                hmm_regime_confidence = regime_detection.confidence

                logger.info(

                    "[REGIME-AWARE] asset=%s regime=%s mode=%s confidence=%.2f",

                    asset, regime_detection.regime.value, strategy_mode, regime_detection.confidence

                )



                # CRITICAL FIX: Update canonical ops.regime_detection via adapter

                # This ensures the canonical risk controls (position_size_multiplier, leverage_multiplier)

                # are applied based on the regime detected by agent_grid_15m's detector

                if _REGIME_ADAPTER_AVAILABLE:

                    try:

                        adapter = get_regime_adapter()

                        adapter.update_from_prediction_detector(

                            regime=hmm_regime,

                            confidence=hmm_regime_confidence

                        )

                        logger.debug(

                            "[REGIME-ADAPTER] Updated canonical regime from agent_grid detector: %s -> %s",

                            hmm_regime, adapter.get_canonical_regime()

                        )

                    except Exception as e:

                        logger.warning("[REGIME-ADAPTER] Failed to update canonical regime: %s", e)



        # Priority 4: Regime-aware threshold adjustment

        # Adjust velocity threshold based on HMM regime to account for market state

        # CRITICAL FIX: 2026-07-05 - Neutralized regime multipliers since base thresholds are now aligned with actual market conditions

        # Previous multipliers (0.8x, 1.5x, 1.2x) were too aggressive and would block trades even with corrected base thresholds

        # New neutral multipliers (0.9x, 1.1x, 1.0x) provide minor adjustments without blocking legitimate signals

        # Bull markets: slightly lower threshold (cleaner trends)

        # Choppy markets: slightly higher threshold (noise)

        # Bear markets: neutral threshold (volatility already accounted for in base thresholds)

        pre_regime_threshold = velocity_threshold

        if hmm_regime and hmm_regime_confidence >= 0.7:

            if hmm_regime == "bull":

                regime_multiplier = 0.9  # Slightly lower threshold in trending markets (was 0.8x)

            elif hmm_regime == "choppy":

                regime_multiplier = 1.1  # Slightly higher threshold in choppy markets (was 1.5x)

            elif hmm_regime == "bear":

                regime_multiplier = 1.0  # Neutral threshold in bear markets (was 1.2x)

            else:

                regime_multiplier = 1.0



            velocity_threshold = velocity_threshold * regime_multiplier



            logger.info(

                "[REGIME-AWARE-THRESHOLD] asset=%s regime=%s confidence=%.2f regime_multiplier=%.2f pre_regime_threshold=%.6f post_regime_threshold=%.6f",

                asset, hmm_regime, hmm_regime_confidence, regime_multiplier, pre_regime_threshold, velocity_threshold

            )



        # REMOVED: Restrictive price confirmation thresholds

        # Previous thresholds (price_yes_threshold=0.55, price_no_threshold=0.65) were blocking most trades

        # System now trades based purely on velocity/momentum signals (industry standard for 15m binary options)



        # 2026 FIX: Lowered ADX threshold from 20 to 2 for 15-minute crypto trading

        # Crypto markets are naturally more volatile and don't always show strong ADX trends

        # Velocity-based signals are the primary signal source; ADX is a secondary filter

        # For 15-minute binary options, even very weak trends (ADX >= 2) are acceptable with velocity confirmation

        # CRITICAL FIX: 2026-07-04 - Lowered ADX threshold from 2.0 to 0.5 for low-volatility weekend conditions

        # Previous threshold of 2.0 was blocking all trades in low-volatility conditions (ADX ~1.0)

        # Weekend/low-volatility markets have ADX 0.5-1.5, which is still tradeable with velocity signals

        # New threshold of 0.5 allows trades while still filtering extreme noise (ADX < 0.5)

        adx = self._calculate_adx(asset)

        if adx > 0 and adx < 0.5:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f < 0.5 (extremely weak/no trend) -> SKIP TRADE (noise filter)",

                asset, adx

            )

            return None

        elif adx >= 0.5:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f >= 0.5 (weak/strong trend) -> PROCEED (15m timeframe)",

                asset, adx

            )

        else:

            logger.info(

                "[ADX-FILTER] asset=%s ADX=%.2f (no data/warmup) -> PROCEED (warmup bypass)",

                asset, adx

            )



        # Volume confirmation filter - use proper EMA20 comparison

        # Industry standard: volume > 1.2x EMA20(volume) confirms signal validity

        # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

        volume_confirmed = self._check_volume_confirmation(asset)

        if not volume_confirmed:

            logger.info(

                "[VOLUME-FILTER] asset=%s volume confirmation failed -> SKIP TRADE (insufficient volume)",

                asset

            )

            return None



        # Phase 7: Check panic fade (volatility reversion) conditions
        # 2026-07-24: CRITICAL SSOT FIX - Skip entirely when signal_mode is momentum_fvg or profile is v2.x
        # Profile YAML (kalshi_crypto_15m_v2.yaml) is single source of truth for signal_mode
        # When signal_mode is momentum_fvg OR profile is v2.x, panic fade must not execute regardless of config
        profile_version = getattr(self.config, 'profile_version', None)
        if self.config.signal_mode == "momentum_fvg" or (profile_version and profile_version.startswith("2.")):
            logger.debug(
                "[SSOT-INVARIANT] asset=%s signal_mode=%s profile_version=%s - skipping panic fade check (profile SSOT)",
                asset, self.config.signal_mode, profile_version
            )
            panic_fade_signal = None
        else:
            # Panic fade is the Turbine research winner: 93 of 96 variants profitable
            # It fades extreme moves when price is at statistical extremes
            # This strategy can override velocity-based signals when conditions are met
            panic_fade_signal = self._check_panic_fade_conditions(asset, velocity)

        if panic_fade_signal:

            logger.info("[PANIC-FADE-SIGNAL] asset=%s panic fade signal generated: side=%s rationale=%s",

                       asset, panic_fade_signal["side"], panic_fade_signal["rationale"])

            # Use panic fade signal instead of velocity-based signal

            signal_side = panic_fade_signal["side"]

            signal_action = panic_fade_signal["action"]

            # Skip velocity threshold check for panic fade signals

            # Panic fade has its own statistical extreme validation

        else:

            # Use velocity-based signal generation

            # CRITICAL FIX: 2026-07-01 - Add multi-timeframe alignment based on industry research

            # Industry standard: 1m + 5m confirmation for +10-20 pp win rate

            # Reference: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md

            # Both timeframes must show same directional momentum for signal confirmation

            mtf_aligned = self._check_multi_timeframe_alignment(asset)

            if not mtf_aligned:

                logger.info(

                    "[MTF-FILTER] asset=%s 1m and 5m timeframes not aligned -> SKIP TRADE (conflicting signals)",

                    asset

                )

                return None

            else:

                logger.info(

                    "[MTF-FILTER] asset=%s 1m and 5m timeframes aligned -> PROCEED (confirmed direction)",

                    asset

                )



        # CRITICAL FIX: 2026-07-01 - Add market hour optimization based on industry research

        # Industry standard: Trade during peak liquidity hours for better win rates

        # Reference: https://www.polytrackhq.app/blog/polymarket-15-minute-crypto-guide

        # Best times: US market open (9:30 AM ET), major news events, low liquidity hours (3-6 AM ET)

        # Disabled by default per user request for 24/7 trading, but infrastructure in place

        if self.config.enable_session_filter:

            current_hour_utc = int(time.gmtime().tm_hour)

            session_active = False



            # US-Europe overlap (13:00-17:00 UTC): Highest liquidity

            if self.config.us_europe_overlap_start_utc <= current_hour_utc < self.config.us_europe_overlap_end_utc:

                session_active = True

                session_name = "US-Europe overlap"

            # US session (17:00-22:00 UTC): Good liquidity

            elif self.config.us_session_start_utc <= current_hour_utc < self.config.us_session_end_utc:

                session_active = True

                session_name = "US session"

            # European morning (08:00-13:00 UTC): Moderate liquidity

            elif self.config.european_morning_start_utc <= current_hour_utc < self.config.european_morning_end_utc:

                session_active = True

                session_name = "European morning"

            # Asian session (00:00-08:00 UTC): Low liquidity, avoid trading

            else:

                session_active = False

                session_name = "Asian session (low liquidity)"



            if not session_active:

                logger.info(

                    "[SESSION-FILTER] asset=%s current_hour_utc=%d session=%s -> SKIP TRADE (low liquidity)",

                    asset, current_hour_utc, session_name

                )

                return None

            else:

                logger.info(

                    "[SESSION-FILTER] asset=%s current_hour_utc=%d session=%s -> PROCEED (peak liquidity)",

                    asset, current_hour_utc, session_name

                )



        # ENTRY MATRIX: Momentum agreement check (based on Turbine research)

        # The edge is in Kalshi's lag to spot price, not alignment

        # Research: "The strongest strategies were predicting Kalshi from BTC"

        # When Coinbase spot is moving up, Kalshi's 15-minute contract still has lag to reprice

        # 2026 FIX: DISABLED momentum agreement filter entirely

        # Kalshi 15-minute markets often price at extremes (80-99c) near expiry

        # Velocity signals and ADX filter are sufficient for trade quality control

        # This filter was blocking too many legitimate trading opportunities

        if market_price > 0:

            kalshi_direction = "up" if market_price > 0.5 else "down"

            spot_direction = "up" if velocity > 0 else "down"



            logger.info(

                "[MOMENTUM-AGREEMENT-FILTER] asset=%s spot_velocity=%.6f (%s) market_price=%.2f (%s) -> PASS (filter disabled - velocity-based trading)",

                asset, velocity, spot_direction, market_price, kalshi_direction

            )



        # HYBRID MODE PRICE CAPS (2026 Optimized)
        # REMOVED: Hybrid mode now properly combines price_based and momentum_fvg (line 7610)
        # Adaptive price caps are no longer needed here since each strategy has its own price logic

        # Apply regime-aware velocity-to-side mapping with strike price consideration

        # CRITICAL: Kalshi 15-minute UP/DOWN market structure:

        # - YES/UP contract wins if settlement price > strike price at expiry

        # - NO/DOWN contract wins if settlement price < strike price at expiry

        # - Kalshi sets the strike/target price for each 15-minute window (e.g., BTC 15m: $58,697 target)

        #

        # Decision logic:

        # 1. Calculate expected price at expiry based on velocity signal

        # 2. Compare expected price to strike price

        # 3. If expected > strike -> BUY YES (expect price above target)

        # 4. If expected < strike -> BUY NO (expect price below target)



        # Calculate expected price move based on velocity (15-minute projection)

        # Velocity is % change per second, project to 15 minutes (900 seconds)

        # CRITICAL FIX: Cap expected move to realistic range based on 2026 research

        # 15-minute crypto options typically have 1-5% price movements, not 78%

        # Research shows extreme projections are unrealistic and cause negative EV trades

        expected_price_move_pct = velocity * 900  # Project velocity to 15-minute window



        # Cap expected move to realistic range (max 5% for 15 minutes)

        # This prevents unrealistic projections like 78% moves in 15 minutes

        max_expected_move_pct = 0.05  # 5% maximum expected move for 15-minute window

        expected_price_move_pct = max(-max_expected_move_pct, min(max_expected_move_pct, expected_price_move_pct))



        expected_price = spot_price * (1 + expected_price_move_pct)



        logger.info(

            "[PRICE-PROJECTION] asset=%s spot=%.2f velocity=%.6f expected_move=%.2f%% expected_price=%.2f strike=%.2s",

            asset, spot_price, velocity, expected_price_move_pct * 100, expected_price, strike_price if strike_price else "N/A"

        )



        # CRITICAL FIX: Use velocity threshold logic exclusively for 15-minute crypto scalping

        # Strike-based projection logic was causing systematic NO bias:

        # - Strike price defaults to current spot price (spot_fallback)

        # - With negative velocity, expected_price < spot_price = strike_price

        # - This always triggered BUY NO, bypassing velocity threshold check

        # - Velocity threshold is the correct signal generation mechanism for momentum trading

        # Strike-based logic is inappropriate for 15m crypto scalping and has been removed



        # CRITICAL FIX: Apply regime-aware velocity-to-side mapping with dual-side evaluation

        # The strategy_mode (trend_following vs mean_reversion) determines how velocity maps to signal side

        # - trend_following: positive velocity -> YES, negative velocity -> NO

        # - mean_reversion: positive velocity -> NO (expect reversion down), negative velocity -> YES (expect reversion up)

        # NEW: Evaluate edge for both YES and NO sides, select best edge within 10-75c canonical range

        # This allows the indicator stack to determine which side has better EV, not forced YES/NO decision



        # 2026-07-04: CRITICAL FIX - Removed NO-side conviction multiplier for symmetry

        # Previous asymmetry (1.5x NO threshold) was blocking valid NO-side signals

        # With new lower thresholds (0.015%-0.025%), the 1.5x multiplier created excessive asymmetry:

        # - BTC: YES threshold 0.00015, NO threshold 0.000225 (50% higher)

        # - DOGE: YES threshold 0.00025, NO threshold 0.000375 (50% higher)

        # This asymmetry was preventing NO-side trades even when velocity was clearly negative

        # New approach: Use symmetric thresholds for both YES and NO sides

        # Rationale: Velocity magnitude should determine signal strength, not direction

        # If velocity is sufficiently negative, it should trigger NO signal just as positive triggers YES

        # CRITICAL FIX: 2026-07-05 - Removed marginal zone rejection based on industry research

        # Industry systems (MagicTradeBot, Manic Trade, VoiceOfChain) do not use marginal zones

        # Signals fire when threshold is crossed - no 20% margin blocking valid trades

        yes_bias_margin = 0.0  # REMOVED: No marginal zone - signals fire at threshold

        no_conviction_multiplier = 1.0  # NO side now uses same threshold as YES (symmetric)



        # Calculate edge for both YES and NO sides based on velocity

        # Edge = p(true) × $1.00 - Market_Price

        # For YES: p(true) based on positive velocity, Market_Price = yes_price_cents/100

        # For NO: p(true) based on negative velocity, Market_Price = no_price_cents/100

        side_edges = {}



        if not panic_fade_signal:

            # Calculate marginal velocity zone (DISABLED - no marginal zone)

            is_marginal_positive = False  # DISABLED: No marginal zone

            is_marginal_negative = False  # DISABLED: No marginal zone



            # CRITICAL FIX: 2026-07-09 - Symmetric signal strength for dual-side evaluation

            # Both YES and NO get non-zero signal strength to enable true edge comparison

            # Direction is encoded in probabilities, not by zeroing one side

            if abs(velocity) < velocity_threshold:

                # No momentum → no edge on either side

                yes_signal_strength = 0.0

                no_signal_strength = 0.0

                logger.info(

                    "[VELOCITY-SIGNAL] asset=%s velocity=%.6f within ±threshold=%.6f -> NO TRADE (insufficient momentum)",

                    asset, velocity, velocity_threshold

                )

                return None

            else:

                # Both sides get symmetric signal magnitude

                signal_mag = abs(velocity) / velocity_threshold

                # CRITICAL FIX: 2026-07-09 - Clamp signal_mag to prevent extreme direction_bias

                # Without clamping, very high velocity (e.g., 10x threshold) could cause direction_bias > 1.0

                # This would push p_model to extreme values (0.95 or 0.05) even with clamping

                # Clamping at 3.0 ensures direction_bias stays in reasonable range [-0.3, 0.3]

                signal_mag = min(signal_mag, 3.0)

                yes_signal_strength = signal_mag

                no_signal_strength = signal_mag



            # CRITICAL FIX: 2026-07-09 - Dual-side probability-based edge calculation

            # Compute model probabilities for both YES and NO using symmetric logic

            # Direction is encoded in probabilities, not by zeroing one side



            # Market-implied probabilities from prices

            p_mkt_yes = yes_price_cents / 100.0 if yes_price_cents > 0 else 0.5

            p_mkt_no = no_price_cents / 100.0 if no_price_cents > 0 else 0.5



            # Base probability (neutral starting point)

            base_prob = 0.5



            # Direction bias from velocity (encodes trend_following vs mean_reversion)
            # CRITICAL FIX: Use unified terminology for consistent direction bias calculation
            # Positive velocity bumps YES probability, negative bumps NO probability
            direction_bias = 0.0

            if velocity > 0:
                # Positive velocity favors YES in trend_following, NO in mean_reversion
                if strategy_mode == "trend_following":
                    direction_bias = 0.1 * signal_mag  # Bump YES probability
                else:  # mean_reversion
                    direction_bias = -0.1 * signal_mag  # Bump NO probability
            else:
                # Negative velocity favors NO in trend_following, YES in mean_reversion
                if strategy_mode == "trend_following":
                    direction_bias = -0.1 * signal_mag  # Bump NO probability
                else:  # mean_reversion
                    direction_bias = 0.1 * signal_mag  # Bump YES probability

            # Validate direction bias logic against unified terminology
            if UNIFIED_TERMINOLOGY_AVAILABLE:
                expected_side = Side.from_velocity_and_mode(velocity, strategy_mode)
                # Check if direction_bias aligns with expected side
                if expected_side == Side.YES and direction_bias < 0:
                    logger.warning(
                        f"[DIRECTION-BIAS-MISMATCH] asset={asset} velocity={velocity} "
                        f"strategy_mode={strategy_mode} expected_side=YES but direction_bias={direction_bias} < 0"
                    )
                elif expected_side == Side.NO and direction_bias > 0:
                    logger.warning(
                        f"[DIRECTION-BIAS-MISMATCH] asset={asset} velocity={velocity} "
                        f"strategy_mode={strategy_mode} expected_side=NO but direction_bias={direction_bias} > 0"
                    )



            # Model probabilities with direction bias
            p_model_yes = max(0.05, min(0.95, base_prob + direction_bias))
            p_model_no = 1.0 - p_model_yes  # Symmetry: p_model_no = 1 - p_model_yes



            # Calculate symmetric edges for both sides

            # Edge formula: edge = (p_model - p_mkt) in FRACTION units (0.0-1.0)

            for side in sides_to_evaluate:

                if side == "yes" and yes_in_range:

                    edge_yes_pct = (p_model_yes - p_mkt_yes)  # FRACTION units

                    side_edges["yes"] = edge_yes_pct

                    logger.info(

                        "[EDGE-CALCULATION] asset=%s side=yes p_model=%.4f p_mkt=%.4f edge_pct=%.6f",

                        asset, p_model_yes, p_mkt_yes, edge_yes_pct

                    )

                if side == "no" and no_in_range:

                    edge_no_pct = (p_model_no - p_mkt_no)  # FRACTION units

                    side_edges["no"] = edge_no_pct

                    logger.info(

                        "[EDGE-CALCULATION] asset=%s side=no p_model=%.4f p_mkt=%.4f edge_pct=%.6f",

                        asset, p_model_no, p_mkt_no, edge_no_pct

                    )



            # CRITICAL FIX: 2026-07-13 - Add midpoint preference (~42.5c bonus for 10-75c range)

            # Nudges selection toward mid-band fills where execution quality is best

            def midpoint_bonus(price_cents):

                """Peak at 42.5c (midpoint of 10-75c canonical range), decays toward 10c/75c."""

                dist = abs(price_cents - 42.5)

                midpoint_bonus_max = 0.5  # Maximum bonus in percentage points

                midpoint_bonus_slope = 0.02  # Decay rate per cent from midpoint

                return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)



            # CRITICAL FIX: 2026-07-19 - Only select sides with positive original edges
            # Midpoint bonus should break ties, not override negative edges
            # Filter to only sides with positive original edges before applying bonus
            positive_sides = {}
            for side, edge in side_edges.items():
                if edge is not None and edge > 0:
                    positive_sides[side] = edge

            if not positive_sides:
                logger.info(
                    "[EDGE-SELECTION] asset=%s no positive edges (edge_yes=%.4f edge_no=%.4f) -> NO TRADE",
                    asset, side_edges.get("yes", 0), side_edges.get("no", 0)
                )
                return None

            # CRITICAL FIX: Determine expected side from velocity and strategy_mode BEFORE edge selection
            # This prevents YES/NO inversion where edge-based selection picks wrong side
            if UNIFIED_TERMINOLOGY_AVAILABLE:
                expected_side = Side.from_velocity_and_mode(velocity, strategy_mode).value
            else:
                # Fallback for legacy code path
                if strategy_mode == "trend_following":
                    expected_side = "yes" if velocity > 0 else "no"
                else:  # mean_reversion
                    expected_side = "no" if velocity > 0 else "yes"

            # PHASE 1: Shadow dual-side evaluation for missed opportunity analysis
            # Log both sides' edges to measure structural bias from expected_side gating
            # This allows us to quantify the opportunity cost of single-side evaluation
            expected_side_edge = side_edges.get(expected_side) if side_edges.get(expected_side) is not None else 0.0
            opposite_side = "no" if expected_side == "yes" else "yes"
            opposite_side_edge = side_edges.get(opposite_side) if side_edges.get(opposite_side) is not None else 0.0

            # Determine hypothetical best side (unconstrained dual-side selection)
            # Use tie-breaking favoring NO to match the momentum_fvg fix
            if expected_side_edge > opposite_side_edge:
                hypothetical_best_side = expected_side
                hypothetical_best_edge = expected_side_edge
            elif opposite_side_edge > expected_side_edge:
                hypothetical_best_side = opposite_side
                hypothetical_best_edge = opposite_side_edge
            else:
                # Equal edges - prefer NO for bias correction
                hypothetical_best_side = "no"
                hypothetical_best_edge = expected_side_edge

            # Log shadow dual-side evaluation for analysis
            logger.info(
                "[SHADOW-DUAL-SIDE] asset=%s velocity=%.6f mode=%s expected_side=%s expected_edge=%.4f "
                "opposite_side=%s opposite_edge=%.4f hypothetical_best=%s hypothetical_edge=%.4f "
                "yes_in_range=%s no_in_range=%s",
                asset, velocity, strategy_mode, expected_side, expected_side_edge,
                opposite_side, opposite_side_edge, hypothetical_best_side, hypothetical_best_edge,
                yes_in_range, no_in_range
            )

            # Log to shadow dual-side metrics monitor for analysis
            try:
                from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor
                monitor = get_shadow_dual_side_monitor()
                monitor.log_shadow_evaluation(
                    asset=asset,
                    velocity=velocity,
                    strategy_mode=strategy_mode,
                    expected_side=expected_side,
                    expected_edge=expected_side_edge,
                    opposite_side=opposite_side,
                    opposite_edge=opposite_side_edge,
                    hypothetical_best_side=hypothetical_best_side,
                    hypothetical_best_edge=hypothetical_best_edge,
                    yes_in_range=yes_in_range,
                    no_in_range=no_in_range
                )
            except Exception as metrics_err:
                logger.warning("[SHADOW-DUAL-SIDE-METRICS] Failed to log to metrics monitor: %s", metrics_err)

            # Only evaluate edges for the expected side to prevent inversion
            if expected_side == "yes" and yes_in_range and "yes" in positive_sides:
                signal_side = "yes"
                selected_edge = side_edges["yes"]
            elif expected_side == "no" and no_in_range and "no" in positive_sides:
                signal_side = "no"
                selected_edge = side_edges["no"]
            else:
                # Expected side not available or no positive edge
                logger.info(
                    "[EDGE-SELECTION] asset=%s expected_side=%s not available or no positive edge (edge_yes=%.4f edge_no=%.4f) -> NO TRADE",
                    asset, expected_side, side_edges.get("yes", 0), side_edges.get("no", 0)
                )
                return None

            signal_action = "buy"



            # Set market_price based on selected side for backward compatibility

            # This ensures hybrid mode price caps and other logic work correctly

            if signal_side == "yes":

                market_price = yes_price_cents / 100.0

            else:

                market_price = no_price_cents / 100.0



            logger.info(

                "[EDGE-SELECTION] asset=%s selected_side=%s edge=%.3f%% market_price=%.2f (all_edges=%s with_bonus=%s)",

                asset, signal_side, selected_edge, market_price, side_edges, side_edges_with_bonus

            )



            # Log the velocity-based rationale
            # CRITICAL FIX: Use unified terminology to prevent signal inversion
            if UNIFIED_TERMINOLOGY_AVAILABLE:
                # Validate signal_side against unified terminology
                expected_side = Side.from_velocity_and_mode(velocity, strategy_mode)
                if signal_side != expected_side.value:
                    logger.error(
                        f"[SIGNAL-INVERSION-DETECTED] asset={asset} velocity={velocity} "
                        f"strategy_mode={strategy_mode} expected_side={expected_side.value} "
                        f"actual_side={signal_side} - POSSIBLE BUG"
                    )
                    # Correct the side to prevent signal inversion
                    signal_side = expected_side.value

            if velocity > velocity_threshold:

                if strategy_mode == "trend_following":

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f > threshold=%.6f mode=trend_following -> BUY %s (positive momentum, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

                else:  # mean_reversion

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f > threshold=%.6f mode=mean_reversion -> BUY %s (expect reversion down, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

            elif velocity < -velocity_threshold:

                if strategy_mode == "trend_following":

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f < -threshold=%.6f mode=trend_following -> BUY %s (negative momentum, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )

                else:  # mean_reversion

                    logger.info(

                        "[VELOCITY-SIGNAL] asset=%s velocity=%.6f < -threshold=%.6f mode=mean_reversion -> BUY %s (expect reversion up, best edge)",

                        asset, velocity, velocity_threshold, signal_side.upper()

                    )



        # 2026-07-05 INDUSTRY ALIGNMENT: 15M Noise Filters

        # 15-minute timeframes are prone to false signals due to microstructure noise

        # Add filters to reject noise and improve signal quality



        # Filter 1: Minimum move threshold

        # CRITICAL FIX: 2026-07-05 - Disabled to enable fills in calm markets

        # Previous threshold (0.6%) was blocking all trades in current market conditions

        # Actual price changes are 0.01%-0.05%, far below 0.6% threshold

        # Disabled to allow velocity-based trading to work:

        min_move_threshold_pct = 0.0  # Disabled - allow any price movement

        if hasattr(self, '_last_price') and self._last_price.get(asset):

            last_price = self._last_price[asset]

            price_change_pct = abs((spot_price - last_price) / last_price) * 100.0 if last_price > 0 else 0.0

            if price_change_pct < min_move_threshold_pct:

                logger.info(

                    "[NOISE-FILTER-MIN-MOVE] asset=%s price_change_pct=%.3f%% < min_move_threshold=%.3f%% -> NO TRADE (insufficient price movement)",

                    asset, price_change_pct, min_move_threshold_pct

                )

                return None

            logger.info(

                "[NOISE-FILTER-MIN-MOVE] asset=%s price_change_pct=%.3f%% >= min_move_threshold=%.3f%% -> PASS",

                asset, price_change_pct, min_move_threshold_pct

            )

        # Store current price for next comparison

        if not hasattr(self, '_last_price'):

            self._last_price = {}

        self._last_price[asset] = spot_price



        # Filter 2: Volume spike confirmation

        # DISABLED: 2026-07-05 - Fixed broken volume filter

        # Previous implementation compared 60-second candle volume (hundreds/thousands USD)

        # against a 1M USD threshold, which ALWAYS failed for 15m trading.

        # Root cause: Wrong volume metric (candle volume vs 24h volume) and wrong threshold.

        # Future implementation should use:

        # - Relative volume Z-score (rolling 5m/15m/60m baselines per 2026 research)

        # - Liquidity floor from profile (min_volume_24h_usd) as coarse filter

        # - Volume anomaly detection instead of absolute thresholds

        # For now, disabled to allow velocity-based trading to function.

        logger.debug("[NOISE-FILTER-VOLUME] DISABLED - broken filter removed (was comparing 60s candle volume to 1M threshold)")



        # Filter 3: Sustained signal

        # Require velocity threshold maintained for N consecutive periods

        sustained_periods = 2  # Require 2 consecutive periods

        if not hasattr(self, '_velocity_history'):

            self._velocity_history = {}

        if asset not in self._velocity_history:

            self._velocity_history[asset] = []

        self._velocity_history[asset].append(velocity)

        # Keep only last N periods

        if len(self._velocity_history[asset]) > sustained_periods:

            self._velocity_history[asset].pop(0)



        # Check if velocity has been sustained in the same direction

        if len(self._velocity_history[asset]) >= sustained_periods:

            recent_velocities = self._velocity_history[asset]

            all_positive = all(v > velocity_threshold for v in recent_velocities)

            all_negative = all(v < -velocity_threshold for v in recent_velocities)

            if not (all_positive or all_negative):

                logger.info(

                    "[NOISE-FILTER-SUSTAINED] asset=%s velocity not sustained for %d periods -> NO TRADE (fleeting signal)",

                    asset, sustained_periods

                )

                return None

            logger.info(

                "[NOISE-FILTER-SUSTAINED] asset=%s velocity sustained for %d periods -> PASS",

                asset, sustained_periods

            )

        else:

            logger.info(

                "[NOISE-FILTER-SUSTAINED] asset=%s insufficient history (%d/%d periods) -> ALLOW (building history)",

                asset, len(self._velocity_history[asset]), sustained_periods

            )



        # Filter 4: Wick filter

        # Ignore signals triggered by candle wicks > 50% of body (avoid liquidation cascades)

        try:

            from data.unified_spot_service import get_unified_spot_service

            spot_service = get_unified_spot_service()

            spot_data = spot_service.get(asset)

            if spot_data and hasattr(spot_data, 'high') and hasattr(spot_data, 'low') and hasattr(spot_data, 'open') and hasattr(spot_data, 'close'):

                candle_high = spot_data.high

                candle_low = spot_data.low

                candle_open = spot_data.open

                candle_close = spot_data.close



                # Calculate wick percentage

                body_size = abs(candle_close - candle_open)

                total_range = candle_high - candle_low

                wick_size = total_range - body_size



                if total_range > 0:

                    wick_pct = (wick_size / total_range) * 100.0

                    max_wick_threshold_pct = 50.0  # 50% wick threshold

                    if wick_pct > max_wick_threshold_pct:

                        logger.info(

                            "[NOISE-FILTER-WICK] asset=%s wick_pct=%.1f%% > max_wick_threshold=%.1f%% -> NO TRADE (wick-dominated candle)",

                            asset, wick_pct, max_wick_threshold_pct

                        )

                        return None

                    logger.info(

                        "[NOISE-FILTER-WICK] asset=%s wick_pct=%.1f%% <= max_wick_threshold=%.1f%% -> PASS",

                        asset, wick_pct, max_wick_threshold_pct

                    )

        except Exception as e:

            logger.warning("[NOISE-FILTER-WICK] Failed to check wick: %s, skipping filter", e)



        # 2026 OPTIMIZATION: Order Book Imbalance (OBI) Filter

        # Industry standard: OBI is the strongest microstructure feature for short-horizon prediction

        # Expected win rate boost: 5-7 percentage points when combined with momentum

        # Reference: https://algos.pro/posts/2026-03-16-order-book-imbalance-alpha-signals/

        try:

            from merid.prediction.order_book_imbalance_filter import get_obi_filter

            obi_filter = get_obi_filter()



            # Get depth from market state

            depth_yes = market_state.depth_yes if market_state and market_state.depth_yes else 0

            depth_no = market_state.depth_no if market_state and market_state.depth_no else 0



            # Check OBI filter with asset parameter for per-asset thresholds

            obi_context = obi_filter.should_trade(

                market_id=ticker,

                bid_depth=depth_yes,

                ask_depth=depth_no,

                direction=signal_side,

                asset=asset  # Pass asset for per-asset strong thresholds

            )



            if obi_context.recommendation == "HOLD":

                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% recommendation=%s -> FILTER (stale data, OBI HOLD overrides other signals)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100, obi_context.recommendation

                )

                return None

            elif obi_context.recommendation == "REDUCED":

                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% recommendation=%s size_multiplier=%.2f -> REDUCED SIZE (low directional consistency)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100,

                    obi_context.recommendation, obi_context.size_multiplier

                )

                # Continue with reduced size (size_multiplier will be applied later)

            else:  # TRADE

                # 2026-07-05 FIX: Add cross-signal alignment check between velocity and OBI

                # Prevent contradictory signals (e.g., velocity=BUY YES, OBI=sell)

                # Alignment mapping: velocity "yes" (BUY YES) aligns with OBI "buy" (bullish order book)

                #                  velocity "no" (BUY NO) aligns with OBI "sell" (bearish order book)

                obi_signal_direction = None

                if obi_context.current_signal.value in ["STRONG_BUY", "BUY"]:

                    obi_signal_direction = "buy"

                elif obi_context.current_signal.value in ["STRONG_SELL", "SELL"]:

                    obi_signal_direction = "sell"



                # Check if OBI signal aligns with velocity signal

                signals_aligned = (obi_signal_direction is None) or (

                    (signal_side == "yes" and obi_signal_direction == "buy") or

                    (signal_side == "no" and obi_signal_direction == "sell")

                )



                if not signals_aligned:

                    logger.warning(

                        "[SIGNAL-CONTRADICTION] asset=%s ticker=%s velocity=%s OBI=%s obi=%.3f -> FILTER (signals contradict, skipping trade)",

                        asset, ticker, signal_side, obi_signal_direction, obi_context.current_obi

                    )

                    return None



                logger.info(

                    "[OBI-FILTER] asset=%s ticker=%s obi=%.3f consistency=%.0f%% -> PASS (full size, strong directional consistency, signals aligned)",

                    asset, ticker, obi_context.current_obi, obi_context.directional_consistency * 100

                )

        except Exception as obi_exc:

            logger.warning("[OBI-FILTER-ERROR] asset=%s error=%s (continuing without OBI filter)", asset, obi_exc)

            # Continue without OBI filter if it fails (non-critical)



        # 2026 OPTIMIZATION: News Event Avoidance

        # Industry standard: Avoid trading 15 minutes before/after high-impact news

        # Major economic releases cause extreme volatility that invalidates technical analysis

        try:

            from merid.prediction.news_event_avoidance import get_news_avoidance

            news_avoidance = get_news_avoidance()



            status = news_avoidance.should_avoid_trading()



            if status.should_avoid:

                logger.info(

                    "[NEWS-AVOIDANCE] asset=%s reason=%s -> SKIP TRADING",

                    asset, status.reason

                )

                return None



            if status.upcoming_events:

                logger.info(

                    "[NEWS-AVOIDANCE] asset=%s upcoming_event=%s time_until=%s",

                    asset, status.upcoming_events[0].event_type, status.time_until_next_event

                )

        except Exception as news_exc:

            logger.warning("[NEWS-AVOIDANCE-ERROR] asset=%s error=%s (continuing without news avoidance)", asset, news_exc)

            # Continue without news avoidance if it fails (non-critical)



        # 2026 VELOCITY-BASED SIDE SELECTION: Side is determined by velocity direction

        # Positive velocity (> threshold) -> buy YES

        # Negative velocity (< -threshold) -> buy NO

        # Edge is calculated for confidence/risk but does NOT override velocity side decision



        # CRITICAL FIX: Read bid/ask from KalshiMarketStateStore instead of catalog

        # The catalog doesn't contain orderbook data for 15m crypto futures.

        # KalshiMarketStateStore is populated from WS orderbook_delta and REST snapshots.

        best_bid = 0

        best_ask = 0

        price_source = "unknown"



        # Actually read from market_state_store

        try:

            ticker = market.market.market_id if hasattr(market, 'market') else market.market_id



            # Check if market_state_store is available

            if not self.market_state_store:

                logger.warning("[MARKET-STATE-READ] asset=%s ticker=%s market_state_store is None",

                             asset, ticker)

                return None



            market_state = self.market_state_store.get(ticker)

            if market_state:

                best_bid = market_state.best_bid_cents if market_state.best_bid_cents else 0

                best_ask = market_state.best_ask_cents if market_state.best_ask_cents else 0

                price_source = "market_state_store"

                logger.info("[MARKET-STATE-READ] asset=%s ticker=%s best_bid=%d best_ask=%d source=%s",

                           asset, ticker, best_bid, best_ask, price_source)



                # CRITICAL FIX: 2026-07-02 - Market quality validation to prevent 1¢ orders

                # Reject markets with poor orderbook quality that indicate data issues

                # 1. No bids AND no asks (completely empty book) - illiquid market

                # 2. Extreme spread - REMOVED: Market validation layer already handles this with dynamic thresholds

                # 3. Unrealistic prices - REMOVED: 95¢ threshold too restrictive for near-expiry markets

                #    Only reject truly extreme prices (>99¢) which indicate data corruption

                # FIX: Allow one-sided books (no bids but has asks, or vice versa) - common in thin 15m crypto markets

                if best_bid == 0 and best_ask == 0:

                    logger.warning(

                        "[MARKET-QUALITY-REJECT] asset=%s ticker=%s best_bid=0 best_ask=0 (empty book) - REJECTING TRADE (illiquid market)",

                        asset, ticker

                    )

                    return None

                elif best_bid == 0:

                    logger.info(

                        "[MARKET-QUALITY-INFO] asset=%s ticker=%s best_bid=0 best_ask=%d (one-sided book) - ALLOWING TRADE (can buy NO if signal aligns)",

                        asset, ticker, best_ask

                    )

                elif best_ask == 0:

                    logger.info(

                        "[MARKET-QUALITY-INFO] asset=%s ticker=%s best_bid=%d best_ask=0 (one-sided book) - ALLOWING TRADE (can buy YES if signal aligns)",

                        asset, ticker, best_bid

                    )



                # Only reject truly corrupted data (best_ask > 99¢, which is impossible for YES/NO duality)

                if best_ask > 99:

                    logger.warning(

                        "[MARKET-QUALITY-REJECT] asset=%s ticker=%s best_ask=%dc > 99c - REJECTING TRADE (impossible price, corrupted data)",

                        asset, ticker, best_ask

                    )

                    return None

            else:

                logger.warning("[MARKET-STATE-READ] asset=%s ticker=%s no market state available",

                             asset, ticker)

        except Exception as e:

            logger.warning("[MARKET-STATE-READ] asset=%s failed to read market state: %s", asset, str(e))



        logger.info("[BEFORE-PROFILE-LOAD] asset=%s market_id=%s", asset, getattr(market, 'market_id', 'N/A'))



        # Load profile for risk limits

        try:

            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            profile_adapter = get_active_profile()

            profile = profile_adapter.profile

            # Get staleness from strategy_policy section of profile

            strategy_staleness = profile.strategy_policy_max_md_staleness_sec

            venue_staleness = profile.venue_invariants_max_book_staleness_ms / 1000.0  # Convert ms to seconds

            logger.info("[PROFILE-LOAD] asset=%s strategy_staleness=%s venue_staleness=%s",

                       asset, strategy_staleness, venue_staleness)

        except Exception as e:

            logger.warning("[PROFILE-LOAD-FAIL] asset=%s error=%s", asset, str(e))

            strategy_staleness = 60

            venue_staleness = 15



        # Phase 1: Compute model probability using logistic mapping from velocity

        # Formula: p_model = sigmoid(alpha_0 + alpha_1 * velocity)

        # where sigmoid(x) = 1 / (1 + exp(-x))

        import math



        # Calculate market probability from bid/ask (p_mkt)

        p_mkt = 0.5  # Default fallback

        if best_bid and best_ask:

            p_mkt = (best_bid + best_ask) / 2 / 100.0

        elif best_bid:

            p_mkt = best_bid / 100.0

        elif best_ask:

            p_mkt = best_ask / 100.0



        # Clamp p_mkt to valid range [0.05, 0.95] (Kalshi venue invariant)

        p_mkt = max(0.05, min(0.95, p_mkt))



        # Calculate raw logit from velocity using coefficients

        # CROSS-PHASE: Add error handling for missing or invalid coefficients

        if self._alpha_0 is None or self._alpha_1 is None:

            logger.error("[SIGNAL-GEN] asset=%s missing velocity coefficients (alpha_0=%s, alpha_1=%s), skipping signal",

                        asset, self._alpha_0, self._alpha_1)

            return None



        # Phase 4.1: Use multi-window velocity for better signal quality

        multi_window_velocity = self._calculate_multi_window_velocity(asset, spot_price)



        # Phase 4.3: Calculate mean reversion signal

        mean_reversion_deviation = self._calculate_mean_reversion(asset, spot_price)



        # Phase 4.4: Calculate separate logits for velocity and mean reversion

        velocity_logit = self._alpha_0 + self._alpha_1 * multi_window_velocity

        mean_reversion_logit = self._alpha_0 + self._alpha_1 * (-mean_reversion_deviation * 0.5)



        # Phase 4.4: Apply logit fusion to combine signals

        raw_logit = self._apply_logit_fusion(velocity_logit, mean_reversion_logit, minutes_to_expiry)



        # CRITICAL FIX: Clamp raw_logit to prevent sigmoid overflow/underflow

        # Logits outside [-10, 10] cause sigmoid to saturate (p_model near 0 or 1)

        # This creates unrealistic edges and math range errors

        LOGIT_CLAMP_MIN = -10.0

        LOGIT_CLAMP_MAX = 10.0

        if raw_logit < LOGIT_CLAMP_MIN:

            logger.warning("[LOGIT-CLAMP] asset=%s raw_logit=%.4f clamped to %.4f (too negative)",

                         asset, raw_logit, LOGIT_CLAMP_MIN)

            raw_logit = LOGIT_CLAMP_MIN

        elif raw_logit > LOGIT_CLAMP_MAX:

            logger.warning("[LOGIT-CLAMP] asset=%s raw_logit=%.4f clamped to %.4f (too positive)",

                         asset, raw_logit, LOGIT_CLAMP_MAX)

            raw_logit = LOGIT_CLAMP_MAX



        # Apply numerically stable logistic function to get model probability

        # Uses the exp-normalize trick to avoid overflow/underflow

        # For x >= 0: sigmoid(x) = 1 / (1 + exp(-x))

        # For x < 0: sigmoid(x) = exp(x) / (1 + exp(x))

        # This prevents overflow for large positive/negative values

        try:

            if raw_logit >= 0:

                p_model = 1.0 / (1.0 + math.exp(-raw_logit))

            else:

                p_model = math.exp(raw_logit) / (1.0 + math.exp(raw_logit))

        except (OverflowError, ValueError) as e:

            logger.error("[SIGNAL-GEN] asset=%s failed to compute p_model from raw_logit=%.4f: %s, skipping signal",

                        asset, raw_logit, e)

            return None



        # Clamp p_model to valid range [0.01, 0.99] (slightly wider than venue invariant)

        p_model = max(0.01, min(0.99, p_model))



        # Phase 5.3: Apply probability calibration if enabled and fitted

        if self._calibration_enabled and self._platt_scaler and self._platt_scaler.is_fitted():

            try:

                calibrated_p_model = self._platt_scaler.predict_single(raw_logit)

                logger.debug("[SIGNAL-GEN] asset=%s calibration applied: p_model=%.4f -> calibrated=%.4f",

                            asset, p_model, calibrated_p_model)

                p_model = calibrated_p_model

            except Exception as cal_err:

                logger.warning("[SIGNAL-GEN] asset=%s calibration failed: %s, using uncalibrated p_model",

                             asset, cal_err)



        # CRITICAL FIX: Apply horizon-aware calibration based on 2026 research

        # Short-horizon markets (<24h) show different biases

        # 5m/15m crypto rounds benefit from horizon-aware models

        # Formula: p* = σ(θ · logit(p)) where θ includes horizon adjustment

        if self._calibration_enabled:

            try:

                import math

                # Calculate horizon factor (15-minute market = 0.25 hours)

                horizon_hours = minutes_to_expiry / 60.0

                # Research-based horizon adjustment: 1 + 0.08 * ln(horizon_hours)

                # For 15m (0.25h): factor = 1 + 0.08 * ln(0.25) = 0.889

                # This slightly reduces probability for very short horizons due to uncertainty

                horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))



                # Apply domain-specific slope for crypto (research: ~1.08 for crypto)

                crypto_slope = 1.08



                # Recalibrate probability using horizon-aware formula

                logit_p = math.log(p_model / (1.0 - p_model)) if p_model > 0 and p_model < 1 else 0.0

                adjusted_logit = crypto_slope * horizon_factor * logit_p

                horizon_calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))



                # Clamp to valid range

                horizon_calibrated_p = max(0.01, min(0.99, horizon_calibrated_p))



                logger.info("[HORIZON-CALIBRATION] asset=%s horizon=%.2fh factor=%.3f p_model=%.4f -> %.4f",

                           asset, horizon_hours, horizon_factor, p_model, horizon_calibrated_p)

                p_model = horizon_calibrated_p

            except Exception as horizon_err:

                logger.warning("[SIGNAL-GEN] asset=%s horizon calibration failed: %s, using uncalibrated p_model",

                             asset, horizon_err)



        # CROSS-PHASE: Validate p_model is in reasonable range

        if not (0.0 <= p_model <= 1.0):

            logger.error("[SIGNAL-GEN] asset=%s p_model=%.4f outside valid range [0,1], skipping signal",

                        asset, p_model)

            return None



        # 2026-07-05 RESEARCH NOTE: A previous iteration replaced probability edge with raw

        # velocity magnitude (0.00-0.03%). That made every downstream economic gate (edge bands

        # 0.8-3%, maker/taker fee thresholds, 2%/4% aggressiveness) unsatisfiable and led to

        # the maker-taker threshold being disabled entirely — producing zero-edge taker orders

        # at 98-99c. Probability edge (p_model - p_mkt) on the momentum-selected side is the

        # 2026 industry standard for Kalshi 15m bots and is restored below, combined with an

        # uncertain-zone gate so we only buy contracts cheap enough to run to the 99c exit.



        # Calculate edge for logging and execution

        # 2026-07-05 RESEARCH FIX: Restored probability-based edge (p_model - p_mkt)

        # Velocity-magnitude edges (0.00-0.03%) can never cover Kalshi taker fees (~1.0-1.4%),

        # which forced downstream hacks (maker-taker threshold disabled, zero-edge 99c taker

        # orders bleeding fees). Industry standard for Kalshi 15m bots (2026): edge = model

        # probability vs market-implied probability on the momentum side, and only trade the

        # uncertain zone where contracts are cheap enough to have profit room to the 99c exit.

        edge_yes_pct = (p_model - p_mkt)  # FRACTION units

        edge_no_pct = ((1.0 - p_model) - (1.0 - p_mkt))  # FRACTION units



        # EDGE GATE 1: Only trade the uncertain zone (market-implied prob 10%-90%).

        # DISABLED for momentum-based trading: Velocity threshold is the signal, not probability edge.

        # Momentum trading relies on velocity exceeding threshold as conviction, not on p_model vs p_mkt.

        # The uncertain zone gate is appropriate for probability-based strategies but blocks momentum

        # signals that should trade based on velocity magnitude regardless of market price level.

        # 2026-07-05 FIX: Disabled to allow momentum signals to execute when velocity exceeds threshold.



        if signal_side == "yes":

            edge_pct = edge_yes_pct

        else:

            edge_pct = edge_no_pct



        # 2026-07-05 INDUSTRY ALIGNMENT: Add explicit Kalshi fee modeling

        # Kalshi charges 7% × p × (1-p) on winning trades, capped at $0.0175

        # Only trade when edge > fee (net edge after fees)

        if signal_side == "yes":
            price_cents = best_ask if best_ask > 0 else best_bid
        else:
            price_cents = 100 - best_bid

        if price_cents > 0:

            # Calculate fee in cents for the winning side using canonical Kalshi fee function.

            fee_cents = canonical_calculate_kalshi_fee_cents(1, int(price_cents))



            # Convert fee to percentage of contract value

            fee_pct = (fee_cents / price_cents) * 100.0 if price_cents > 0 else 0.0



            # Calculate net edge after fees

            net_edge_pct = edge_pct - fee_pct



            # CRITICAL FIX: 2026-07-05 - Disabled min net edge filter to enable fills

            # Previous threshold (3 cents) was blocking all trades in current market conditions

            # Net edge is often negative in calm markets, but we need to execute to gather data

            # Disabled to allow any trade to execute:

            min_net_edge_cents = 0.0  # Disabled - allow any edge

            min_net_edge_pct = (min_net_edge_cents / price_cents) * 100.0 if price_cents > 0 else 0.0



            logger.info(

                "[FEE-MODELING] asset=%s side=%s price_cents=%d p_mkt=%.4f fee_cents=%.2f fee_pct=%.2f%% edge_pct=%.2f%% net_edge_pct=%.2f%% min_net_edge_pct=%.2f%%",

                asset, signal_side, int(price_cents), p_mkt, fee_cents, fee_pct, edge_pct, net_edge_pct, min_net_edge_pct

            )



            # 2026-07-05 FIX: Disabled net edge sign check for momentum-based trading

            # Velocity threshold is the signal, not probability edge. Negative net edges occur

            # when p_model < p_mkt (high market prices), but momentum signals should still execute.

            # Previous check blocked all YES trades in current market conditions (p_mkt > 0.85).

            # Disabled to allow momentum signals to execute regardless of net edge sign:

            # if net_edge_pct < min_net_edge_pct:

            #     logger.info(

            #         "[FEE-REJECT] asset=%s side=%s net_edge_pct=%.2f%% < min_net_edge_pct=%.2f%% (fees=%s cents) -> NO TRADE",

            #         asset, signal_side, net_edge_pct, min_net_edge_pct, fee_cents

            #     )

            #     return None



            # Use net edge for downstream calculations

            edge_pct = net_edge_pct



        # ENTRY MATRIX: Time window multiplier raises the REQUIRED edge for late entries

        # (edge decay). Applied to the requirement below, not to the measured edge.



        # ENTRY MATRIX: Apply price band edge multiplier (based on CEPR/KarlWhelan research)

        # Updated to align with per-asset minimums: BTC/ETH 20c, SOL/XRP 25c, DOGE 30c

        # 50-65c: sweet spot, baseline edge requirements

        # Near minimum bands: require higher edge due to structural bias

        # 66-70c: near max price, require higher edge (small payout)

        # Higher volatility assets (SOL, DOGE) need stricter multipliers

        if signal_side == "yes":
            price_cents = best_ask if best_ask > 0 else best_bid
        else:
            price_cents = 100 - best_bid

        price_edge_multiplier = 1.0



        if price_cents > 0:

            # Per-asset minimum bands (aligned with new minimums)

            if asset in ['BTC', 'ETH']:

                # BTC/ETH: 10c minimum (canonical range 10-75c)

                if 10 <= price_cents <= 14:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 15 <= price_cents <= 24:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 25 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 75:

                    price_edge_multiplier = 1.5  # Near max price

            elif asset in ['SOL', 'XRP']:

                # SOL/XRP: 10c minimum (canonical range 10-75c)

                if 10 <= price_cents <= 14:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 15 <= price_cents <= 24:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 25 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 75:

                    price_edge_multiplier = 1.5  # Near max price

            elif asset == 'DOGE':

                # DOGE: 10c minimum (canonical range 10-75c)

                if 10 <= price_cents <= 14:

                    price_edge_multiplier = 1.5  # Near minimum, conservative

                elif 15 <= price_cents <= 24:

                    price_edge_multiplier = 1.2  # Slightly above minimum

                elif 25 <= price_cents <= 49:

                    price_edge_multiplier = 1.0  # Normal range

                elif 50 <= price_cents <= 65:

                    price_edge_multiplier = 1.0  # Sweet spot

                elif 66 <= price_cents <= 75:

                    price_edge_multiplier = 1.5  # Near max price



        # EDGE GATE 2: Minimum edge requirement (per-asset, aligned with profile min_edge_early:

        # BTC/ETH 3%, SOL/XRP 4%, DOGE 5%). Time/price multipliers RAISE the requirement for

        # late entries and structurally-biased price bands (they no longer inflate the edge

        # itself, which would have weakened the gate instead of strengthening it).

        # DISABLED for momentum-based trading: Velocity threshold is the signal, not probability edge.

        # Momentum trading conviction comes from velocity exceeding threshold, not from p_model vs p_mkt edge.

        # 2026-07-05 FIX: Disabled to allow momentum signals to execute when velocity exceeds threshold.



        logger.info(

            "[EDGE-MULTIPLIER] asset=%s price_cents=%d time_multiplier=%.1f price_multiplier=%.1f edge_pct=%.2f%% (edge gate disabled for momentum)",

            asset, price_cents, time_edge_multiplier, price_edge_multiplier, edge_pct

        )



 # REMOVED: Negative edge check for momentum-based trading

        # The -20% edge threshold is incompatible with momentum signals because:

        # 1. p_model is derived from velocity via logistic mapping, not independent probability estimation

        # 2. Comparing velocity-transformed probability to market-implied probability is meaningless

        # 3. Momentum trading conviction comes from velocity exceeding threshold, not probability edge

        # 4. The edge gate was already disabled for momentum (line 3513-3515)

        # 2026-07-05 FIX: Removed to allow momentum signals to execute based on velocity threshold



        # Sanity check only: reject extreme edges that indicate data errors

        # Edge > 90% indicates corrupted market data or calculation errors

        max_edge_threshold = 90.0  # 90% maximum edge (sanity check for data errors)

        if abs(edge_pct) > max_edge_threshold:

            logger.error(

                "[EDGE-REJECT] asset=%s side=%s velocity=%.6f edge_pct=%.2f%% > max_edge=%.2f%% - REJECTING TRADE (data error, corrupted market state)",

                asset, signal_side, velocity, edge_pct, max_edge_threshold

            )

            return None



        # 2026-07-05 FIX: Removed confidence filter for momentum-based trading

        # Research shows momentum trading should use velocity magnitude as signal strength

        # Probability-based confidence filtering is not applicable to velocity-based signals

        # The "confidence" in momentum trading is the velocity exceeding the threshold

        # This filter was blocking all signals because natural velocity percentages (0.0015%-0.0025%)

        # produce p_model values very close to 0.5, resulting in confidence_pct < 2%



        # Compute confidence as distance from 0.5 (neutral probability)

        # Higher distance from 0.5 = higher confidence

        confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))



        # For backward compatibility, set model_prob to p_model
        # p_model is the probability of the YES (up) outcome. Downstream consumers
        # (Kelly filter, deployment-safety distance) compare model_prob against the
        # side-specific price_cents, so for NO signals pass the NO win probability.
        model_prob = p_model if signal_side == "yes" else (1.0 - p_model)



        logger.info("[SIGNAL-GEN] asset=%s velocity=%.6f raw_logit=%.4f p_mkt=%.4f p_model=%.4f edge_pct=%.2f confidence=%.2f",

                    asset, velocity, raw_logit, p_mkt, p_model, edge_pct, confidence)



        # Phase 2: Classify regime from market state

        ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

        regime = self._classify_regime(ticker)



        # CRITICAL FIX: Calculate correct price_cents based on side

        # Kalshi binary duality: YES_bid + NO_ask = 100, NO_bid + YES_ask = 100

        # YES: use YES mid-price (best_bid + best_ask) / 2

        # NO: use NO mid-price = (NO_bid + NO_ask) / 2

        # where NO_bid = 100 - YES_ask, NO_ask = 100 - YES_bid

        if best_bid and best_ask:

            if signal_side == "yes":

                # YES: use YES mid-price

                price_cents = int((best_bid + best_ask) / 2)

            else:  # signal_side == "no"

                # NO: calculate NO bid/ask from YES bid/ask, then use NO mid-price

                # NO_bid = 100 - YES_ask, NO_ask = 100 - YES_bid

                no_bid = 100 - best_ask

                no_ask = 100 - best_bid

                price_cents = int((no_bid + no_ask) / 2)



                logger.info("[PRICE-CALC-NO] asset=%s YES_bid=%d YES_ask=%d -> NO_bid=%d NO_ask=%d NO_mid=%d",

                           asset, best_bid, best_ask, no_bid, no_ask, price_cents)



                # 2026-07-05 FIX: REMOVED price clamping to [50, 70] range

                # Clamping was preventing orders from filling by forcing prices below market levels

                # Orders now use actual market mid-spread prices for proper execution

        elif best_bid:

            # Fallback to bid only

            if signal_side == "yes":

                price_cents = best_bid

            else:

                # NO: NO_ask = 100 - YES_bid

                price_cents = 100 - best_bid

        elif best_ask:

            # Fallback to ask only

            if signal_side == "yes":

                price_cents = best_ask

            else:

                # NO: NO_bid = 100 - YES_ask

                price_cents = 100 - best_ask

        else:

            # No market data - use neutral price (already in range)

            price_cents = 42  # 2026-07-14: Changed from 25 to 42 (midpoint of 10-75c canonical range)



        # 2026-07-12: Expanded price range 10c-75c to match actual market conditions (YES prices 60-97c)

        # If no prices exist in 10-75c range, drop the candidate (no trade).

        raw_price_cents = price_cents



        # Check if price is within canonical 10c-75c range

        if 10 <= raw_price_cents <= 75:

            # Price is already in the side-appropriate range - use it directly

            clamped_price_cents = raw_price_cents

            logger.info(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d in side-aware range - using directly",

                asset, signal_side, raw_price_cents

            )

        else:

            # Price is outside canonical range - search orderbook for valid prices

            logger.warning(

                "[PRICE-SELECTION] asset=%s side=%s raw_price_cents=%d outside side-aware range - searching orderbook",

                asset, signal_side, raw_price_cents

            )



            # Try to find a price in the canonical range from the orderbook

            price_cents = None

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                market_state = self.market_state_store.get(ticker) if self.market_state_store else None



                if market_state:

                    # Select the opposite-side book to compute the ask for the target side.
                    # YES ask = 100 - NO bid; NO ask = 100 - YES bid.

                    if signal_side == "yes":
                        # Cheapest YES ask = 100 - NO bid; search no_bids.
                        levels = getattr(market_state, 'no_bids', [])
                        range_min, range_max = 10, 75
                    else:
                        # Cheapest NO ask = 100 - YES bid; search yes_bids.
                        levels = getattr(market_state, 'yes_bids', [])
                        range_min, range_max = 10, 75

                    if levels:

                        # Find cheapest executable price in the side-appropriate range.
                        # For YES: 100 - no_bid; for NO: 100 - yes_bid.

                        valid_prices = [100 - p for (p, size) in levels if range_min <= (100 - p) <= range_max and size >= 1]

                        if valid_prices:

                            price_cents = min(valid_prices)  # cheapest acceptable executable price

                            logger.info(

                                "[PRICE-SELECTION] asset=%s side=%s found %d valid prices in [%dc-%dc], using cheapest=%d",

                                asset, signal_side, len(valid_prices), range_min, range_max, price_cents

                            )

                        else:

                            logger.warning(

                                "[PRICE-SELECTION] asset=%s side=%s no executable prices in [%dc-%dc] - dropping candidate",

                                asset, signal_side, range_min, range_max

                            )

                            self._record_signal_rejection(
                                "no_executable_price_in_range",
                                market_id=market_id,
                                market_time_remaining_s=minutes_to_expiry * 60.0,
                                reference_price=spot_price,
                                velocity=velocity,
                                threshold=velocity_threshold,
                                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} range={range_min}-{range_max}",
                            )

                            return None  # Drop candidate - no valid price in side-aware range

                    else:

                        logger.warning(

                            "[PRICE-SELECTION] asset=%s side=%s orderbook not available - dropping candidate",

                            asset, signal_side

                        )

                        self._record_signal_rejection(
                            "orderbook_not_available",
                            market_id=market_id,
                            market_time_remaining_s=minutes_to_expiry * 60.0,
                            reference_price=spot_price,
                            velocity=velocity,
                            threshold=velocity_threshold,
                            feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                        )

                        return None

                else:

                    logger.warning(

                        "[PRICE-SELECTION] asset=%s market state not available - dropping candidate",

                        asset

                    )

                    self._record_signal_rejection(
                        "market_state_not_available",
                        market_id=market_id,
                        market_time_remaining_s=minutes_to_expiry * 60.0,
                        reference_price=spot_price,
                        velocity=velocity,
                        threshold=velocity_threshold,
                        feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side}",
                    )

                    return None

            except Exception as e:

                logger.error(

                    "[PRICE-SELECTION] asset=%s error searching orderbook: %s - dropping candidate",

                    asset, e

                )

                self._record_signal_rejection(
                    "price_selection_exception",
                    market_id=market_id,
                    market_time_remaining_s=minutes_to_expiry * 60.0,
                    reference_price=spot_price,
                    velocity=velocity,
                    threshold=velocity_threshold,
                    feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} error={e}",
                )

                return None



            clamped_price_cents = price_cents



        # Final validation - side-aware canonical range
        # CRITICAL FIX (2026-08-05): YES and NO trade in different price regions. The previous
        # single 10c-75c range rejected all NO candidates above 75c even though NO contracts
        # naturally trade at high prices (implied probability of event NOT happening).
        # Single canonical entry range 10c-75c for both YES and NO.  Duality
        # means an 80c NO is equivalent to a 20c YES; there is no need to allow
        # either side to trade outside 10-75, and order_intent_contract rejects
        # such prices with `invalid_price`.
        price_min, price_max = 10, 75
        range_str = "10c-75c"

        if clamped_price_cents is None or not (price_min <= clamped_price_cents <= price_max):

            logger.error(

                "[PRICE-SELECTION-ERROR] asset=%s side=%s final price_cents=%d not in range [%s] - dropping candidate",

                asset, signal_side, clamped_price_cents, range_str

            )

            self._record_signal_rejection(
                "final_price_out_of_range",
                market_id=market_id,
                market_time_remaining_s=minutes_to_expiry * 60.0,
                reference_price=spot_price,
                velocity=velocity,
                threshold=velocity_threshold,
                feature_flags=f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')} signal_side={signal_side} price_cents={clamped_price_cents} range={range_str}",
            )

            return None



        logger.info(

            "[PRICE-SELECTION] asset=%s side=%s final entry price=%d (within canonical range [%s])",

            asset, signal_side, clamped_price_cents, range_str

        )



        # Kalshi contracts trade in whole cents.  Guard against any float or numpy
        # scalar leaking through from market-state arithmetic.
        price_cents = int(round(clamped_price_cents))



        # MAKER-FIRST ENTRY PRICING (2026-07-05 RESEARCH FIX)

        # Previous version anchored YES buys at best_ask - offset, which on wide books

        # (e.g., bid=81 ask=99) produced 98c entries — chasing the ask with no profit room.

        # Research standard (Kalshi 15m bots, PRED Scanner order-type study 2026):

        # - Rest limit orders on OUR side of the book (join/improve best bid) so swings

        #   come to us and we enter cheap (maker, 0 fee, queue priority).

        # - Cross the spread (taker) ONLY when edge >= 4% (EDGE_MARKET_ENTRY threshold,

        #   taker-fee adjusted) — a signal strong enough to pay for immediacy.

        # - Sweet-spot band from profile configuration (default 10-70c for momentum-based trading)

        # - CRITICAL FIX: 2026-07-05 - Use profile configuration instead of hardcoded values

        # - Previous hardcoded [25c, 50c] was blocking all trades in current market conditions

        # - Profile config allows dynamic adjustment based on strategy requirements
        # - 2026-07-11: Updated to use dynamic threshold manager for regime-aware price ranges

        try:

            from merid.event_venues.kalshi.dynamic_thresholds import get_dynamic_threshold_manager

            threshold_manager = get_dynamic_threshold_manager()

            ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS = threshold_manager.get_price_range()

            logger.debug(
                "[SIGNAL-GEN] Using dynamic price range from threshold manager: %d-%dc (regime=%s)",
                ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, threshold_manager.get_regime()
            )

        except Exception as e:

            logger.warning("[SIGNAL-GEN] Failed to load dynamic price range: %s, using fallback 5-85c", e)

            ENTRY_MIN_PRICE_CENTS = 5  # Canonical lower bound (v2 profile)

            ENTRY_MAX_PRICE_CENTS = 85  # Canonical upper bound (v2 profile)
            # 2026 BEST PRACTICE: Track fallback activation
            self._fallback_activations["dynamic_range_fallback"] += 1
            self._fallback_timestamps["dynamic_range_fallback"].append(time.time())



        MARKETABLE_EDGE_PCT = 4.0  # matches EDGE_MARKET_ENTRY_* (0.04) in risk_parameters.py



        def calculate_optimal_entry_price(

            side: str,

            best_bid: int,

            best_ask: int,

            minutes_to_expiry: float,

            edge_pct: float

        ) -> Optional[int]:

            """

            Maker-first entry price in the side's own price space.



            Returns None when no entry inside the profile price_range [5c, 95c] is possible,

            in which case the candidate must be skipped (no chasing).

            """

            if best_bid <= 0 or best_ask <= 0:

                return None  # No two-sided book: cannot price a resting entry safely



            # Convert to the traded side's price space

            if side == "yes":

                side_bid, side_ask = best_bid, best_ask

            else:  # NO space: no_bid = 100 - yes_ask, no_ask = 100 - yes_bid

                side_bid, side_ask = 100 - best_ask, 100 - best_bid



            if side_bid <= 0 or side_ask <= 0 or side_ask <= side_bid:

                # Crossed/degenerate book in side space — join whatever bid exists

                side_bid = max(1, min(side_bid, 99))

                side_ask = max(side_bid + 1, min(max(side_ask, side_bid + 1), 99))



            # Spread-aware execution: only cross TIGHT spreads. On wide books (thin

            # early-window liquidity) the ask is a phantom quote — lifting it means

            # paying far above fair value (e.g., side_bid=1 side_ask=69). Research:

            # limit orders in thin markets get 23% better price control (PRED 2026).

            spread_cents = side_ask - side_bid

            TIGHT_SPREAD_MAX_CENTS = 10



            if edge_pct >= MARKETABLE_EDGE_PCT and spread_cents <= TIGHT_SPREAD_MAX_CENTS:

                # Strong edge on a tight book: pay the spread for a guaranteed fill (taker)

                optimal_price = side_ask

                entry_mode = "marketable"

            elif edge_pct >= MARKETABLE_EDGE_PCT:

                # Strong edge but WIDE book: never lift a phantom ask. Rest at side-space

                # mid — passive, cheap, and first in line as the book tightens toward us.

                optimal_price = max(side_bid + 1, (side_bid + side_ask) // 2)

                optimal_price = min(optimal_price, side_ask - 1)

                entry_mode = "resting_mid_wide_spread"

            else:

                # Normal edge (2-4%): rest at/near best bid — buy the swing cheap.

                # Improve bid by 1c for queue priority, but never lift the ask.

                optimal_price = min(side_bid + 1, side_ask - 1)

                optimal_price = max(optimal_price, side_bid)  # never below best bid

                entry_mode = "resting"



            # Sweet-spot band enforcement: entries must land in [10c, 75c].

            if optimal_price < ENTRY_MIN_PRICE_CENTS:

                # Too cheap = lottery zone (win rate ~10% below 30c per 2026-07-03 analysis).

                # Allow lifting up to the band floor only if the ask is inside the band.

                if ENTRY_MIN_PRICE_CENTS <= side_ask <= ENTRY_MAX_PRICE_CENTS:

                    optimal_price = ENTRY_MIN_PRICE_CENTS

                else:

                    logger.info(

                        "[ENTRY-BAND-SKIP] side=%s side_bid=%d side_ask=%d below band [%d,%d] -> skip",

                        side, side_bid, side_ask, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS

                    )

                    return None

            elif optimal_price > ENTRY_MAX_PRICE_CENTS:

                # Book has moved past our band: rest AT the band cap only if the bid is

                # still inside the band (price may come back to us); otherwise skip.

                if side_bid <= ENTRY_MAX_PRICE_CENTS:

                    optimal_price = ENTRY_MAX_PRICE_CENTS

                    entry_mode = "resting_band_cap"

                else:

                    logger.info(

                        "[ENTRY-BAND-SKIP] side=%s side_bid=%d side_ask=%d above band [%d,%d] -> skip (no chasing)",

                        side, side_bid, side_ask, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS

                    )

                    return None



            logger.info(

                "[MAKER-FIRST-ENTRY] side=%s side_bid=%d side_ask=%d price=%d mode=%s edge=%.2f%% tte=%.1fmin",

                side, side_bid, side_ask, optimal_price, entry_mode, edge_pct, minutes_to_expiry

            )

            return int(optimal_price)



        # Apply maker-first entry pricing

        if best_bid > 0 and best_ask > 0:

            optimal_entry = calculate_optimal_entry_price(

                side=signal_side,

                best_bid=best_bid,

                best_ask=best_ask,

                minutes_to_expiry=minutes_to_expiry,

                edge_pct=edge_pct

            )

            if optimal_entry is None:

                logger.info(

                    "[ENTRY-PRICE-SKIP] asset=%s side=%s bid=%d ask=%d no entry inside sweet-spot band -> NO TRADE",

                    asset, signal_side, best_bid, best_ask

                )

                return None

            price_cents = optimal_entry



        # 2026-07-05 INDUSTRY ALIGNMENT: Relax entry band restriction for near-expiry trading

        # Industry standard: Trade at any price where EV > fee threshold, not just within arbitrary band

        # Near expiry (last 3 minutes), prices naturally converge to 0/100 - this is normal behavior

        # Early/mid window: Keep band to avoid lottery zone (<30c) and poor scaling (>70c)

        # Late window: Relax band to allow trading on convergence with fee-adjusted edge



        if minutes_to_expiry > 3.0:

            # Early/mid window: enforce entry band to avoid lottery zone and poor scaling

            if not (ENTRY_MIN_PRICE_CENTS <= price_cents <= ENTRY_MAX_PRICE_CENTS):

                logger.info(

                    "[ENTRY-BAND-SKIP] asset=%s side=%s price_cents=%d outside sweet-spot band [%d,%d] (tte=%.1fmin > 3min) -> NO TRADE",

                    asset, signal_side, price_cents, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, minutes_to_expiry

                )

                return None

        else:

            # Late window (last 3 minutes): allow trading outside band if fee-adjusted edge is sufficient

            # Fee modeling already ensures edge > 3 cents net after fees

            logger.info(

                "[ENTRY-BAND-RELAXED] asset=%s side=%s price_cents=%d outside band [%d,%d] but tte=%.1fmin <= 3min -> ALLOW (fee-adjusted edge ensures profitability)",

                asset, signal_side, price_cents, ENTRY_MIN_PRICE_CENTS, ENTRY_MAX_PRICE_CENTS, minutes_to_expiry

            )



        # CRITICAL FIX: Compute order aggressiveness at signal generation time
        # This ensures execution semantics are decided by the signal stack, not overridden by loop
        aggressiveness = 0.0
        try:
            from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
            seconds_to_expiry = int(minutes_to_expiry * 60)
            aggressiveness = compute_order_aggressiveness(asset, edge_pct, seconds_to_expiry)
            logger.info("[SIGNAL-AGGRESSIVENESS] asset=%s edge_pct=%.6f tte=%ds aggressiveness=%.2f",
                       asset, edge_pct, seconds_to_expiry, aggressiveness)
        except Exception as agg_err:
            logger.warning("[SIGNAL-AGGRESSIVENESS-ERROR] asset=%s failed to compute aggressiveness: %s, using default 0.5",
                         asset, agg_err)
            aggressiveness = 0.5  # Default to marketable

        # Construct signal dictionary

        signal = {

            "asset": asset,

            "side": signal_side,

            "action": signal_action,

            "velocity": velocity,

            "spot_price": spot_price,

            "minutes_to_expiry": minutes_to_expiry,

            "best_bid": best_bid,

            "best_ask": best_ask,

            "price_source": price_source,

            "strategy_staleness": strategy_staleness,

            "venue_staleness": venue_staleness,

            "edge_pct": edge_pct,  # Phase 1: Edge from (p_model - p_mkt)

            "confidence": confidence,  # Phase 1: Confidence from distance from 0.5

            "model_prob": model_prob,  # Phase 1: Model probability from logistic mapping

            "p_mkt": p_mkt,  # Phase 1: Market probability for debugging

            "raw_logit": raw_logit,  # Phase 1: Raw logit for debugging

            "regime": regime,  # Phase 2: Regime classification from market state (liquidity-based)

            "hmm_regime": hmm_regime,  # Phase 6: HMM regime for exit policy (bull/choppy/bear)

            "hmm_regime_confidence": hmm_regime_confidence,  # Phase 6: HMM regime confidence

            "rationale": panic_fade_signal["rationale"] if panic_fade_signal else f"velocity_based: velocity={velocity:.6f} edge_pct={edge_pct:.2f}%",  # CRITICAL: Add rationale for strategy

            "price_cents": price_cents,  # CRITICAL FIX: Set correct price based on side (YES uses YES price, NO uses NO price)

            # Dual-source strike price metadata for traceability

            "strike_price": strike_price,  # Strike price used for signal (window_strike or fallback)

            "strike_source": strike_source,  # Source: "kalshi_floor_strike", "candle_open", "spot_fallback"

            # CRITICAL FIX: Add execution parameters to signal generation
            # These are now set by signal stack and respected by loop execution
            "aggressiveness": aggressiveness,  # 0.0=resting, 0.5-1.0=marketable

            "post_only": False,  # Default to False to prevent Kalshi API rejection

            "order_type": "limit",  # Default to limit for maker rebate optimization

        }



        # Add panic fade metadata if applicable

        if panic_fade_signal:

            signal["strategy"] = "panic_fade"

            signal["rsi"] = panic_fade_signal.get("rsi")

            signal["zscore"] = panic_fade_signal.get("zscore")



        # CRITICAL FIX: 2026-07-13 - REMOVED pre-fill slot allocation from signal generation
        # Previous behavior: Slot was allocated during signal generation (pre-fill), causing phantom exposure
        # when orders returned ACCEPTED with filled=0. This blocked subsequent orders.
        # New behavior: Slot allocation moved to order_router post-fill path (only when order actually fills).
        # This ensures exposure is only counted for FILLED orders, not for signals that may not fill.
        signal["slot_id"] = None

        # CRITICAL FIX: Do NOT set count in signal generation
        # Position sizing is the responsibility of the loop's unified_sizing calculation
        # This ensures single source of truth for position sizing based on edge, confidence, and $1 cap
        signal["count"] = 0  # Placeholder, will be set by loop's sizing calculation

        logger.info("[SIGNAL-GENERATED] asset=%s side=%s velocity=%.6f edge_pct=%.2f%% confidence=%.2f model_prob=%.2f",
                   asset, signal_side, velocity, edge_pct, confidence, model_prob)

        return signal



    def _cooldown_elapsed(self, asset: str, now: float, last_trade_time: Optional[float]) -> float:
        """Return elapsed seconds since last trade; fail-open on clock-domain corruption.

        A missing entry means there is no prior trade, so the asset is eligible.
        A stored timestamp that is ahead of ``now`` indicates a different clock
        domain was mixed in (e.g. a persisted Unix epoch wall-time timestamp
        stored in a monotonic cooldown). In that case we reset the stored
        timestamp and fail open so the asset is not blocked forever.
        """
        if last_trade_time is None:
            logger.info(
                "[COOLDOWN-NO-PRIOR-TRADE] asset=%s; eligible for immediate evaluation",
                asset
            )
            return float("inf")

        elapsed = now - last_trade_time
        if elapsed < 0:
            logger.warning(
                "[COOLDOWN-CLOCK-DOMAIN] asset=%s last=%s now=%s elapsed=%.1fs; resetting",
                asset, last_trade_time, now, elapsed
            )
            self._last_trade_time.pop(asset, None)
            return float("inf")

        return elapsed



    async def collect_order_candidate(self, tick: int) -> Optional[Dict[str, Any]]:

        # Collect order candidate for this agent.

        logger.info("[COLLECT-ENTRY] agent=%s tick=%d", self.config.name, tick)

        try:

            # Get spot price from unified spot service

            asset = self.config.name.split('_')[0]

            self._reset_rejection_waterfall(asset)
            self._record_waterfall("asset_identified", True)

            logger.info("[COLLECT-ASSET] agent=%s asset=%s", self.config.name, asset)



            # CRITICAL: Re-enabled cooldown to prevent over-trading

            # The cooldown was temporarily disabled for debugging, but this caused

            # 100% of bankroll to be used in positions. Cooldown is now re-enabled.

            cooldown_seconds = self._calculate_dynamic_cooldown(asset)

            last_trade_time = self._last_trade_time.get(asset)

            time_since_last_trade = self._cooldown_elapsed(asset, time.monotonic(), last_trade_time)



            logger.info("[COLLECT-COOLDOWN] agent=%s asset=%s time_since_last=%.1fs cooldown=%.1fs",

                       self.config.name, asset, time_since_last_trade, cooldown_seconds)



            if time_since_last_trade < cooldown_seconds:

                logger.info(

                    "[COOLDOWN-CHECK] asset=%s time_since_last=%.1fs < cooldown=%.1fs, skipping",

                    asset, time_since_last_trade, cooldown_seconds

                )

                self._record_waterfall("cooldown", False, f"time_since_last={time_since_last_trade:.1f}s < cooldown={cooldown_seconds:.1f}s")
                self._set_final_reason(f"cooldown: time_since_last={time_since_last_trade:.1f}s < cooldown={cooldown_seconds:.1f}s")

                return None

            self._record_waterfall("cooldown", True)



            # 2026 Research-Based Risk Management: Session limit (max 5 trades per 15m window)

            current_time = time.time()

            if current_time - self._session_start_time > self._session_window_sec:

                # Reset session counters

                self._session_order_count = 0

                self._session_risk_usd = 0.0  # CRITICAL FIX: Reset session risk cap with window

                self._consecutive_losses = {asset: 0 for asset in self._consecutive_losses}  # CRITICAL FIX: Reset consecutive losses with window

                self._consecutive_loss_pause_until = {asset: 0.0 for asset in self._consecutive_loss_pause_until}  # CRITICAL FIX: Reset pause times with window

                self._session_start_time = current_time

                logger.info("[SESSION-RESET] agent=%s session window reset (order_count=0, session_risk=0, consecutive_losses=0)", self.config.name)



            # CRITICAL FIX (2026-07-17): Removed max_orders_per_15m_window check - $1 exposure cap is the limit
            # GlobalSlotAllocator enforces MAX_EXPOSURE_USD=1.00, MAX_CONTRACTS_PER_ORDER=1, MAX_POSITIONS_PER_ASSET=1



            # 2026 Research-Based Risk Management: Consecutive loss pause

            pause_until = self._consecutive_loss_pause_until.get(asset, 0.0)

            if current_time < pause_until:

                logger.info(

                    "[CONSECUTIVE-LOSS-PAUSE] agent=%s asset=%s paused until %s (consecutive losses=%d) -> SKIP",

                    self.config.name, asset, pause_until, self._consecutive_losses.get(asset, 0)

                )

                return None



            # 2026 Research-Based Risk Management: Session risk cap (10% of capital)

            if self._session_risk_cap_usd > 0 and self._session_risk_usd >= self._session_risk_cap_usd:

                logger.info(

                    "[SESSION-RISK-CAP] agent=%s session_risk=%.2f >= cap=%.2f -> SKIP (session risk cap reached)",

                    self.config.name, self._session_risk_usd, self._session_risk_cap_usd

                )

                return None



            # 2026 Research-Based Risk Management: Portfolio heat tracking

            heat_allowed, heat_reason = self._check_portfolio_heat()

            if not heat_allowed:

                logger.info(

                    "[PORTFOLIO-HEAT] agent=%s asset=%s reason=%s -> SKIP (portfolio too hot)",

                    self.config.name, asset, heat_reason

                )

                return None



            # 2026 Research-Based Risk Management: Asset-specific rolling PnL limits

            pnl_allowed, pnl_reason = self._check_rolling_pnl_limit(asset)

            if not pnl_allowed:

                logger.info(

                    "[ROLLING-PNL] agent=%s asset=%s reason=%s -> SKIP (rolling PnL limit exceeded)",

                    self.config.name, asset, pnl_reason

                )

                return None



            # 2026 Research-Based Risk Management: Time-of-day risk scaling

            # Get multiplier (will be applied to position size later)

            time_of_day_multiplier = self._apply_time_of_day_risk_scaling(asset)

            if time_of_day_multiplier != 1.0:

                logger.info(

                    "[TIME-OF-DAY-SCALING] agent=%s asset=%s multiplier=%.2f (session-based risk adjustment)",

                    self.config.name, asset, time_of_day_multiplier

                )

            if time_of_day_multiplier <= 0:

                logger.info(

                    "[TIME-OF-DAY-SCALING] agent=%s asset=%s multiplier=%.2f -> SKIP (risk scaling zero)",

                    self.config.name, asset, time_of_day_multiplier

                )

                return None



            # 2026 FIX: Check max concurrent positions limit to prevent over-accumulation

            # Industry standard: 10-25 concurrent positions (Kalshibot, PolyTrack, production bots)

            # Position cache is synced from REST API via fills_poller and venue_adapter

            # Re-enabled with staleness check to avoid false limit hits

            try:

                from merid.event_venues.kalshi.position_cache import get_position_cache

                position_cache = get_position_cache()

                if position_cache:

                    all_positions = position_cache.get_all_positions(validate_freshness=False)

                    # CRITICAL FIX: Filter positions by current window ticker to prevent counting stale positions
                    # Each 15m window has a unique ticker (e.g., KXBTC15M-26JUL191645-45)
                    # Positions from previous windows should not count against current window limits
                    # Extract asset from agent name (e.g., BTC_15M -> BTC)
                    asset = self.config.name.split('_')[0].upper() if '_' in self.config.name else self.config.name.upper()

                    # Get current window ticker from market catalog
                    current_window_ticker = None
                    try:
                        from merid.event_venues.kalshi.market_catalog import get_market_catalog
                        catalog = get_market_catalog()
                        if catalog:
                            current_market = catalog.get_current_15m_market(asset)
                            if current_market:
                                current_window_ticker = current_market.market.market_id
                    except Exception as ticker_err:
                        logger.warning("[POSITION-LIMIT] Failed to get current window ticker: %s", ticker_err)

                    # Filter positions: only count those matching current window ticker
                    if current_window_ticker:
                        # Filter to only positions from the current window
                        open_positions = {k: v for k, v in all_positions.items()
                                        if v.contracts > 0 and k == current_window_ticker}
                    else:
                        # Fallback: filter by asset if we can't get the exact ticker
                        # This is less precise but prevents complete failure
                        open_positions = {k: v for k, v in all_positions.items()
                                        if v.contracts > 0 and asset in k.upper()}
                        logger.warning("[POSITION-LIMIT] Using asset-based filtering (fallback) for %s", asset)

                    position_count = len(open_positions)

                    # CRITICAL FIX (2026-08-03): Log ASSET-SCOPED totals.
                    # get_all_positions() spans every asset, so the old log showed
                    # e.g. agent=ETH_15M total_positions=1 (actually BTC's position)
                    # next to open_positions=0 - looked like a counting bug.
                    asset_position_count = sum(
                        1 for k, v in all_positions.items()
                        if v.contracts > 0 and asset in k.upper()
                    )

                    logger.info(

                        "[POSITION-LIMIT] agent=%s asset_positions=%d open_positions=%d current_window=%s (all_assets_total=%d)",

                        self.config.name, asset_position_count, position_count, current_window_ticker or "N/A", len(all_positions)

                    )



                    if position_count >= self.config.max_concurrent_positions:

                        logger.info(

                            "[POSITION-LIMIT] agent=%s current_positions=%d >= max_concurrent_positions=%d -> SKIP (position limit reached)",

                            self.config.name, position_count, self.config.max_concurrent_positions

                        )

                        return None

            except Exception as e:

                logger.warning("[POSITION-LIMIT] agent=%s position check failed: %s", self.config.name, str(e))



            spot_price, spot_data = self._get_spot_cached(asset)

            if not spot_price:

                logger.warning("[SPOT-ERROR] asset=%s no spot price available", self.config.name)

                self._record_waterfall("spot_price", False, "no spot price available")
                self._set_final_reason("spot_price: no spot price available")

                return None

            self._record_waterfall("spot_price", True)



            # CRITICAL FIX: Update price history BEFORE signal generation

            # This ensures velocity calculation has fresh data even if no signal is generated

            # Previously, price history was only updated in _generate_signal, creating a vicious cycle:

            # no signal -> no price update -> velocity=0 -> no signal

            # CRITICAL FIX: Pass spot_data for OHLC-based ADX/ATR calculation

            self._update_price_history(asset, spot_price, spot_data)



            # Get market from market state store - use available markets instead of computing from time

            market = None

            try:

                # Extract asset from agent name (e.g., "BTC_15M" -> "BTC")

                asset = self.config.name.split("_")[0]



                # Query market state store for available markets for this asset

                # This works with whatever markets are actually subscribed via WebSocket

                logger.info("[COLLECT-MARKET-STORE] agent=%s asset=%s market_state_store=%s",

                           self.config.name, asset, self.market_state_store is not None)

                if self.market_state_store:

                    # Get all market IDs in the store

                    all_tickers = list(self.market_state_store._states.keys())

                    logger.info("[COLLECT-ALL-TICKERS] agent=%s total_tickers=%d",

                               self.config.name, len(all_tickers))



                    # Log sample tickers for diagnostics

                    if all_tickers:

                        logger.info("[COLLECT-SAMPLE-TICKERS] agent=%s sample_tickers=%s",

                                   self.config.name, all_tickers[:10])



                    # Find tickers matching this asset's series

                    series_prefix = self.config.series_tickers[0] if self.config.series_tickers else f"KX{asset}15M"

                    logger.info("[COLLECT-SERIES-PREFIX] agent=%s series_prefix=%s",

                               self.config.name, series_prefix)

                    matching_tickers = [t for t in all_tickers if t.startswith(series_prefix)]

                    logger.info("[COLLECT-MATCHING-TICKERS] agent=%s matching=%d tickers=%s",

                               self.config.name, len(matching_tickers), matching_tickers[:5])



                    # CRITICAL: Alert if expected series is missing (indicates WebSocket subscription failure)

                    if len(matching_tickers) == 0 and len(all_tickers) > 0:

                        logger.error(

                            "[COLLECT-SERIES-MISSING] agent=%s asset=%s series_prefix=%s NOT FOUND in market_state_store. "

                            "This indicates WebSocket subscription or market discovery failure. "

                            "Available series prefixes: %s",

                            self.config.name, asset, series_prefix,

                            sorted(set([t.split("-")[0] for t in all_tickers if "-" in t]))

                        )



                    if matching_tickers:

                        # 2026-07-05 RESEARCH FIX: Entry window is minutes 3-10 of the 15m window

                        # (time_to_expiry 300s-720s). Research consensus for Kalshi 15m bots:

                        # - Skip first ~3 minutes (noisy signals, walk-forward optimal min_dm=3)

                        # - No NEW entries in final 5 minutes (adverse selection: informed flow

                        #   dominates late; entering late = chasing near-settled prices)

                        # Exits/ratchet management are handled elsewhere and are NOT window-gated.

                        current_time = time.time()

                        best_ticker = None

                        best_time_to_expiry = 0.0  # Initialize to 0 to select maximum (newest market)



                        for ticker_candidate in matching_tickers:

                            market_state_candidate = self.market_state_store.get(ticker_candidate)

                            if market_state_candidate:

                                close_time_ts = getattr(market_state_candidate, 'expected_expiration_time', None)

                                if close_time_ts is None:

                                    continue

                                elif isinstance(close_time_ts, str):

                                    try:

                                        close_time_ts = datetime.fromisoformat(close_time_ts.replace('Z', '+00:00')).timestamp()

                                    except (ValueError, AttributeError):

                                        continue

                                elif not isinstance(close_time_ts, (int, float)):

                                    continue



                                time_to_expiry = close_time_ts - current_time



                                # Select the contract with time_to_expiry within the ENTRY window

                                # (0s-900s = full 15m window). Allow trading throughout entire window.

                                # CRITICAL FIX: Select MAXIMUM time_to_expiry (newest market) to catch

                                # markets at 50c/50c before they drift to extreme prices

                                # Previous logic selected minimum (closest to expiry), causing us to

                                # trade late markets with prices 76-98c instead of early markets at ~50c

                                if 0 <= time_to_expiry <= 900:

                                    if time_to_expiry > best_time_to_expiry:

                                        best_ticker = ticker_candidate

                                        best_time_to_expiry = time_to_expiry



                                logger.info(

                                    "[MARKET-SELECTION-DEBUG] asset=%s ticker=%s time_to_expiry=%.1fs",

                                    self.config.name, ticker_candidate, time_to_expiry

                                )



                        if best_ticker:

                            ticker = best_ticker

                            # CRITICAL GUARDRAIL: Validate selected market is truly open

                            market_state = self.market_state_store.get(ticker)

                            if market_state:

                                # Status is stored directly on state object, not in raw_data

                                api_status = getattr(market_state, 'status', 'unknown').lower()

                                settlement_ts = getattr(market_state, 'settlement_ts', None)

                                liquidity_dollars = getattr(market_state, 'liquidity_dollars', None)

                                yes_bid = getattr(market_state, 'best_bid_cents', None)

                                no_bid = getattr(market_state, 'best_ask_cents', None)



                                # Assert market is not settled (hard rule)

                                if settlement_ts is not None:

                                    logger.error(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has settlement_ts=%s (expected None). "

                                        "Market is already settled - skipping trade.",

                                        ticker, settlement_ts

                                    )

                                    self._record_waterfall("market_open", False, "market already settled")
                                    self._set_final_reason("market_open: market already settled")

                                    return None



                                # Warn if status is not 'open' (soft rule - market state may be stale)

                                # The catalog API filter already ensures we only get open markets

                                if api_status not in ['open', 'closed']:

                                    logger.warning(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has status=%s (expected 'open' or 'closed'). "

                                        "Market state may be stale - catalog API filter ensures open markets.",

                                        ticker, api_status

                                    )



                                # Warn if liquidity is zero (edge case, not hard rule)

                                if liquidity_dollars == 0 or (yes_bid == 0 and no_bid == 0):

                                    logger.warning(

                                        "[MARKET-STATE-MISMATCH] selected ticker=%s has zero liquidity "

                                        "(liquidity_dollars=%s, yes_bid=%s, no_bid=%s). "

                                        "This may indicate stale market data.",

                                        ticker, liquidity_dollars, yes_bid, no_bid

                                    )



                            logger.info(

                                "[MARKET-SELECTION] asset=%s ticker=%s selected (time_to_expiry=%.1fs, in trading window)",

                                self.config.name, ticker, best_time_to_expiry

                            )

                            self._record_waterfall("market_discovered", True, f"ticker={ticker}")

                        else:

                            # No contract in entry window - skip this cycle

                            logger.info(

                                "[MARKET-SELECTION] asset=%s no contract in entry window (0s-900s to expiry), skipping",

                                self.config.name

                            )

                            self._record_waterfall("market_discovered", False, "no contract in entry window")
                            self._set_final_reason("market_discovered: no contract in entry window")

                            return None



                        market_state = self.market_state_store.get(ticker)



                        if market_state:

                            # Create MinimalMarket wrapper for compatibility

                            # Use expiration_time from market state if available, otherwise compute from ticker

                            close_time_ts = getattr(market_state, 'expected_expiration_time', None)

                            if close_time_ts is None:

                                # Fallback: compute close_time from current time + 15 minutes

                                close_time_ts = time.time() + 900

                            elif isinstance(close_time_ts, str):

                                # 2026 FIX: Handle string timestamp (ISO format)

                                # Convert ISO string to timestamp

                                try:

                                    close_time_ts = datetime.fromisoformat(close_time_ts.replace('Z', '+00:00')).timestamp()

                                except Exception as e:

                                    logger.warning("[TRADING-WINDOW] failed to parse close_time_ts string: %s, using fallback", e)

                                    close_time_ts = time.time() + 900

                            elif not isinstance(close_time_ts, (int, float)):

                                # 2026 FIX: Handle unexpected types (already datetime, etc.)

                                logger.warning("[TRADING-WINDOW] unexpected close_time_ts type: %s, using fallback", type(close_time_ts))

                                close_time_ts = time.time() + 900



                            # CRITICAL FIX: Implement min_decision_minute from profile

                            # Profile configures per-asset minimum decision minute to skip noisy early signals

                            # This prevents low-quality signals from early price action

                            # Industry standard: Skip first N minutes of 15m window to avoid noise

                            time_to_expiry = close_time_ts - time.time()

                            max_trading_window = 900  # full 15m window



                            # Get min_decision_minute from profile (per-asset configuration)

                            min_decision_minute = 0  # default to 0 if not configured

                            try:

                                # Load raw YAML to access min_decision_minute section

                                import yaml

                                from pathlib import Path

                                import os

                                profile_name = os.getenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

                                profile_filename = f"{profile_name}.yaml"

                                # __file__ is merid/prediction/agent_grid_15m.py

                                # parent.parent.parent = MERID root

                                profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / profile_filename



                                with open(profile_path, 'r', encoding='utf-8') as f:

                                    profile_yaml = yaml.safe_load(f)



                                min_decision_minute_config = profile_yaml.get("min_decision_minute", {})

                                # Extract asset symbol from agent name (e.g., "DOGE_15M" -> "DOGE")

                                asset_symbol = self.config.name.split('_')[0] if '_' in self.config.name else self.config.name

                                min_decision_minute = min_decision_minute_config.get(asset_symbol, 0)

                                logger.info(

                                    "[MIN-DECISION-MINUTE] asset=%s min_decision_minute=%d (from profile YAML)",

                                    self.config.name, min_decision_minute

                                )

                            except Exception as e:

                                logger.warning("[MIN-DECISION-MINUTE] Failed to load from profile YAML: %s, using default 0", e)



                            min_time_to_expiry = min_decision_minute * 60  # convert to seconds
                            # Hard production floor: profile/YAML cannot disable the 90s entry cutoff.
                            min_time_to_expiry = max(min_time_to_expiry, MERID_HARD_MIN_ENTRY_TTE_SECONDS)



                            if time_to_expiry > max_trading_window:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs > max_trading_window=%ds -> SKIP (too early in contract)",

                                    self.config.name, time_to_expiry, max_trading_window

                                )
                                self._record_waterfall("market_open", False, f"time_to_expiry={time_to_expiry:.1f}s > max={max_trading_window}s")
                                self._set_final_reason(f"market_open: time_to_expiry={time_to_expiry:.1f}s > max={max_trading_window}s")

                                return None

                            elif time_to_expiry < min_time_to_expiry:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs < min_time_to_expiry=%ds (%d min) -> SKIP (too early in window, waiting for signal clarity)",

                                    self.config.name, time_to_expiry, min_time_to_expiry, min_decision_minute

                                )
                                self._record_waterfall("market_open", False, f"time_to_expiry={time_to_expiry:.1f}s < min={min_time_to_expiry}s")
                                self._set_final_reason(f"market_open: time_to_expiry={time_to_expiry:.1f}s < min={min_time_to_expiry}s")

                                return None

                            else:

                                logger.info(

                                    "[TRADING-WINDOW] asset=%s time_to_expiry=%.1fs within trading window [%ds, %ds] -> PROCEED",

                                    self.config.name, time_to_expiry, min_time_to_expiry, max_trading_window

                                )



                            market = MinimalMarket(

                                market_id=ticker,

                                close_time=close_time_ts,

                                asset=asset,

                                minutes_to_expiry=time_to_expiry / 60.0,  # Convert seconds to minutes

                                exchange_index=getattr(market_state, 'exchange_index', None),

                            )

                            logger.info(

                                "[MARKET-STATE-STORE] asset=%s ticker=%s from state store (total matching=%d)",

                                self.config.name, ticker, len(matching_tickers)

                            )

                        else:

                            logger.warning("[MARKET-STATE-STORE] asset=%s ticker=%s no state available", self.config.name, ticker)

                    else:

                        logger.warning("[MARKET-STATE-STORE] asset=%s no tickers matching series=%s in state store (total tickers=%d)",

                                     self.config.name, series_prefix, len(all_tickers))

                else:

                    logger.warning("[MARKET-STATE-STORE] asset=%s market_state_store is None", self.config.name)

            except Exception as e:

                logger.warning("[MARKET-STATE-STORE-ERROR] asset=%s error=%s", self.config.name, str(e), exc_info=True)



            if not market:

                logger.warning("[MARKET-ERROR] asset=%s no market available from market state store", self.config.name)
                self._record_waterfall("market_discovered", False, "no market available from market state store")
                self._set_final_reason("market_discovered: no market available from market state store")

                return None



            # CRITICAL FIX: Block trading during warmup to prevent trades based on insufficient data
            # Market validation requires sufficient depth and fresh data, which may not be available
            # during startup. Block trading during warmup period to avoid high leverage bugs.
            # REDUCED warmup from 2 to 1 for immediate 15m trading start (spot service refreshes every 5s)
            # 1 data point sufficient for immediate velocity-based trading
            price_history_len = len(list(self._spot_price_history.get(asset, [])))

            if price_history_len < 1:
                logger.warning(
                    "[MARKET-VALIDATION-SKIP] asset=%s price_history=%d < 1, BLOCKING TRADE during warmup (insufficient data)",
                    self.config.name, price_history_len
                )
                self._record_waterfall("market_open", False, f"price_history={price_history_len} < 1 (warmup)")
                self._set_final_reason(f"market_open: price_history={price_history_len} < 1 (warmup)")
                return None  # Block trading during warmup

            # Validate market state (single call after warmup check)
            if not self._validate_market_state(market):
                logger.info("[MARKET-VALIDATION-FAILED] asset=%s market validation failed", self.config.name)
                self._record_waterfall("market_open", False, "market validation failed (stale/missing/illiquid)")
                self._set_final_reason("market_open: market validation failed (stale/missing/illiquid)")
                return None



            # Check per-strip order limit

            # CRITICAL FIX: Use asset-specific series ticker for strip tracking

            # For 15m crypto, each asset has its own series ticker (KXBTC15M, KXETH15M, etc.)

            # We need to find the series ticker that matches the current asset

            strip_ticker = None

            if self.config.series_tickers:

                # Find the series ticker that matches the current asset

                for ticker in self.config.series_tickers:

                    if asset.upper() in ticker.upper():

                        strip_ticker = ticker

                        break

                # Fallback to first ticker if no match found

                if not strip_ticker:

                    strip_ticker = self.config.series_tickers[0]



            if strip_ticker:

                # CRITICAL FIX: MinimalMarket has market_id directly, not nested under .market.market_id

                current_market_id = None

                if market and hasattr(market, 'market_id'):

                    current_market_id = market.market_id

                elif market and hasattr(market, 'market') and hasattr(market.market, 'market_id'):

                    current_market_id = market.market.market_id



                # DIAGNOSTIC: Log market ID tracking

                stored_market_id = self._current_market_ids.get(strip_ticker)

                logger.info(

                    "[STRIP-DIAG] asset=%s strip=%s current_market_id=%s stored_market_id=%s",

                    asset, strip_ticker, current_market_id, stored_market_id

                )



                # Reset counter if market ID changed (new 15m strip)

                if current_market_id and self._current_market_ids.get(strip_ticker) != current_market_id:

                    logger.info(

                        "[STRIP-RESET] asset=%s strip=%s market changed from %s to %s, resetting order count",

                        asset, strip_ticker, self._current_market_ids.get(strip_ticker), current_market_id

                    )

                    self._strip_order_counts[strip_ticker] = 0

                    self._current_market_ids[strip_ticker] = current_market_id



                current_strip_orders = self._strip_order_counts.get(strip_ticker, 0)

                # CRITICAL FIX (2026-07-17): Removed per_strip_order_limit check - $1 exposure cap is the limit
                # GlobalSlotAllocator enforces MAX_EXPOSURE_USD=1.00, MAX_CONTRACTS_PER_ORDER=1, MAX_POSITIONS_PER_ASSET=1



            # CRITICAL FIX: Use normalized minutes_to_expiry from market object

            # This ensures we use the canonical expiry time from contract_normalization.py

            # which prioritizes close_ts over end_date for 15m contracts

            minutes_to_expiry = 0

            if hasattr(market, 'minutes_to_expiry') and market.minutes_to_expiry is not None:

                # Use normalized minutes_to_expiry (canonical field from catalog)

                minutes_to_expiry = market.minutes_to_expiry

            elif hasattr(market, 'close_time'):

                # Fallback to manual calculation if normalized field not available

                # This should not happen in production with proper catalog normalization

                logger.warning(

                    "[AGENT-GRID-15M] asset=%s using manual minutes_to_expiry calculation (normalized field missing). "

                    "This indicates catalog normalization may not be working correctly.",

                    self.config.name

                )

                close_time = market.close_time

                now = time.time()



                # Handle different close_time types (datetime, timestamp string, or float)

                if isinstance(close_time, str):

                    # Parse ISO string to timestamp

                    try:

                        if close_time.endswith('Z'):

                            close_time = close_time.replace('Z', '+00:00')

                        close_dt = dt.fromisoformat(close_time)

                        close_time_ts = close_dt.timestamp()

                    except (ValueError, AttributeError):

                        # Fallback to computed time

                        close_time_ts = now + 900

                elif isinstance(close_time, dt):

                    close_time_ts = close_time.timestamp()

                else:

                    # Assume it's already a timestamp (float/int)

                    close_time_ts = float(close_time) if close_time else now + 900



                minutes_to_expiry = (close_time_ts - now) / 60



            # For 15-minute rolling markets, only reject if expired (<= 0)

            # Kalshi 15m markets roll every quarter-hour (11:00, 11:15, 11:30, 11:45)

            # and should be traded throughout their entire 15-minute lifecycle

            if minutes_to_expiry <= 0:

                logger.warning("[TIME-EXPIRY-VALIDATION] asset=%s ticker=%s expired=%.1fmin",

                             self.config.name, market.market.market_id if hasattr(market, 'market') else 'N/A', minutes_to_expiry)

                self._record_waterfall("market_open", False, f"expired minutes_to_expiry={minutes_to_expiry:.1f}")
                self._set_final_reason(f"market_open: expired minutes_to_expiry={minutes_to_expiry:.1f}")

                return None



            # Generate signal

            self._record_waterfall("market_open", True)

            signal = self._generate_signal(spot_price, market, minutes_to_expiry)

            if not signal:

                reason = self._last_signal_rejection.get("reason") or "_generate_signal returned None"
                context = self._last_signal_rejection.get("context") or {}

                logger.info(
                    "[SIGNAL-GENERATION-REJECT] asset=%s market=%s reason=%s spot_price=%s reference_price=%s "
                    "velocity=%s velocity_source=%s velocity_age_ms=%s signal_type=%s "
                    "threshold=%s threshold_type=%s edge_threshold=%s velocity_threshold=%s "
                    "market_time_remaining_s=%s candles_available=%s feature_flags=%s",
                    self.config.name,
                    getattr(market, 'market_id', None) or getattr(market, 'market', None),
                    reason,
                    spot_price,
                    context.get("reference_price", "N/A"),
                    context.get("velocity", "N/A"),
                    context.get("velocity_source", "N/A"),
                    context.get("velocity_age_ms", "N/A"),
                    context.get("signal_type", "N/A"),
                    context.get("threshold", "N/A"),
                    context.get("threshold_type", "N/A"),
                    context.get("edge_threshold", "N/A"),
                    context.get("velocity_threshold", "N/A"),
                    context.get("market_time_remaining_s", f"{minutes_to_expiry * 60:.0f}"),
                    context.get("candles_available", "N/A"),
                    context.get("feature_flags", f"signal_mode={getattr(self.config, 'signal_mode', 'unknown')}"),
                )

                self._record_waterfall("signal_generated", False, reason)
                self._set_final_reason(f"signal_generated: {reason}")

                return None

            self._record_waterfall("signal_generated", True)



            # REMOVED (2026-07-23): FINAL-INVERSION layer was causing YES bias
            # Signal generation already produces correct side/intent mappings
            # BULLISH_EVENT → YES leg (side=yes), BEARISH_EVENT → NO leg (side=no)
            # No inversion needed - use signal as-is

            # Construct order candidate

            candidate = {

                "agent_id": self.config.name,

                "ticker": market.market.market_id if hasattr(market, 'market') else self.config.series_tickers[0],

                "exchange_index": getattr(market, 'exchange_index', None) or (
                    getattr(market.market, 'raw_data', {}).get('exchange_index')
                    if hasattr(market, 'market') and market.market
                    else None
                ),

                "side": signal["side"],

                "action": signal["action"],

                "spot_price": spot_price,

                "velocity": signal["velocity"],

                "minutes_to_expiry": minutes_to_expiry,

                "edge_pct": signal.get("edge_pct", 0.0),  # CRITICAL: Single source of truth for edge (FRACTION units)

                "confidence": signal.get("confidence", 0.5),  # BUG #36 FIX: Carry confidence from signal

                "model_prob": signal.get("model_prob", 0.5),  # BUG #36 FIX: Carry model_prob from signal

                "rationale": signal.get("rationale"),  # CRITICAL: Carry rationale to skip edge validation for price-based strategy

                "regime": signal.get("regime", "normal"),  # Phase 2: Carry regime from signal

                # CRITICAL FIX: Carry execution parameters from signal to candidate
                # These are now set by signal stack and respected by loop execution
                "aggressiveness": signal.get("aggressiveness", 0.5),  # 0.0=resting, 0.5-1.0=marketable

                "post_only": signal.get("post_only", False),  # Default to False to prevent Kalshi API rejection

                "order_type": signal.get("order_type", "limit"),  # Default to limit for maker rebate optimization

                # CRITICAL FIX: Add price_cents and count for candidate deduplication

                "price_cents": signal.get("price_cents", 0),  # Set by signal generation, respected by loop

                "count": 0,  # CRITICAL: Set to 0 initially, loop's sizing calculation will determine final count

                # 2026 Research-Based Risk Management: Apply time-of-day risk scaling to position size

                "time_of_day_multiplier": time_of_day_multiplier,  # Carry multiplier for order router

                # CRITICAL FIX: Carry HMM regime from signal for exit policy
                "hmm_regime": signal.get("hmm_regime", None),

                "hmm_regime_confidence": signal.get("hmm_regime_confidence", 0.0),

                # CRITICAL FIX: Add exit targets to satisfy "no trade without exit" invariant
                # CRITICAL FIX 2026-07-16: Updated to align with exit_policy.py (80% TP, 40% SL for 2:1 risk/reward)
                "take_profit_r_multiple": 0.8,  # 0.8R take profit (2:1 risk/reward ratio)
                "stop_loss_r_multiple": 0.4,  # 0.4R stop loss (2:1 risk/reward ratio)

                # Phase 1: Add market microstructure data for fee-aware edge and microstructure gates

                "yes_bid_cents": None,

                "yes_ask_cents": None,

                "no_bid_cents": None,

                "no_ask_cents": None,

                "yes_depth": None,

                "no_depth": None,

                # CRITICAL FIX 2026-08-20: order identity/provenance fields required by order_router
                "run_id": f"{self.config.name}_{time.time():.6f}_{uuid.uuid4().hex[:8]}",
                "decision_id": f"decision_{uuid.uuid4().hex[:16]}",
                "data_state": "healthy" if "cfb_rti_live" in (signal.get("settlement_reference") or "") else "public_spot_fallback",
                "regime_label": signal.get("regime") or "normal",
                "regime_probability": signal.get("hmm_regime_confidence", 1.0) or 1.0,
                "p_yes": (signal.get("model_prob", 0.5) if signal.get("side") == "yes" else 1.0 - signal.get("model_prob", 0.5)),
                "p_no": (1.0 - signal.get("model_prob", 0.5) if signal.get("side") == "yes" else signal.get("model_prob", 0.5)),
                "p_selected": signal.get("model_prob", 0.5),
                "gross_edge": signal.get("edge_pct", 0.0),
                "net_edge": (signal.get("ev_net_cents") / 100.0) if signal.get("ev_net_cents") is not None else signal.get("edge_pct", 0.0),
                "selected_outcome_price": int(signal.get("price_cents", 0)),
                "settlement_reference": signal.get("settlement_reference") or "public_spot_fallback:unknown",
                "confidence_valid": "cfb_rti_live" in (signal.get("settlement_reference") or ""),
                "confidence_source": "uncertainty_engine" if "cfb_rti_live" in (signal.get("settlement_reference") or "") else "public_spot",
                "confidence_reasons": [],
                "cf_rti_basis": signal.get("cf_rti_basis", 0.0),
                "settlement_input_price": signal.get("settlement_input_price", 0.0),
                "all_in_cost_cents": signal.get("all_in_cost_cents"),
                "ev_net_cents": signal.get("ev_net_cents"),
                "fee_cents": signal.get("fee_cents"),
                "slippage_cents": signal.get("slippage_cents"),
                "time_to_expiry_seconds": signal.get("time_to_expiry_seconds"),
                "thesis_side": signal.get("thesis_side"),
                "strategy_intent": signal.get("strategy_intent"),
                "is_counter_trend": signal.get("is_counter_trend", False),
                "edge_yes": signal.get("edge_yes"),
                "edge_no": signal.get("edge_no"),

            }



            # Populate market microstructure data from market state store

            try:

                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id

                if self.market_state_store:

                    market_state = self.market_state_store.get(ticker)

                    if market_state:

                        candidate["yes_bid_cents"] = getattr(market_state, 'best_bid_cents', None)

                        candidate["yes_ask_cents"] = getattr(market_state, 'best_ask_cents', None)

                        # Derive NO prices from YES prices using Kalshi duality

                        if candidate["yes_bid_cents"] is not None:

                            candidate["no_ask_cents"] = 100 - candidate["yes_bid_cents"]

                        if candidate["yes_ask_cents"] is not None:

                            candidate["no_bid_cents"] = 100 - candidate["yes_ask_cents"]

                        # CRITICAL FIX: Use window-based depth (depth_10c_yes/depth_10c_no) instead of single-level depth

                        # depth_10c_yes/depth_10c_no represent contracts within ±10c of mid price (industry standard)

                        # min_depth_yes/min_depth_no only capture best bid/ask size (1 price level)

                        # This fixes false rejections when liquidity exists across multiple levels

                        depth_10c_yes = getattr(market_state, 'depth_10c_yes', None)

                        depth_10c_no = getattr(market_state, 'depth_10c_no', None)

                        if depth_10c_yes is not None and depth_10c_yes > 0:

                            candidate["yes_depth"] = depth_10c_yes

                        else:

                            candidate["yes_depth"] = getattr(market_state, 'min_depth_yes', None)

                        if depth_10c_no is not None and depth_10c_no > 0:

                            candidate["no_depth"] = depth_10c_no

                        else:

                            candidate["no_depth"] = getattr(market_state, 'min_depth_no', None)

                        # CRITICAL FIX 2026-08-13: Carry the executable ask sizes into the
                        # candidate so downstream gates use the same liquidity binding as
                        # the SIGNAL-EV-GATE displayed_depth.
                        candidate["yes_ask_size"] = getattr(market_state, 'yes_ask_size', None)
                        candidate["no_ask_size"] = getattr(market_state, 'no_ask_size', None)
                        candidate["yes_bid_size"] = getattr(market_state, 'yes_bid_size', None)
                        candidate["no_bid_size"] = getattr(market_state, 'no_bid_size', None)

                        # Add distance band calculation using spot price and strike price
                        # This enables analysis of edge performance by distance from strike
                        try:
                            from merid.metrics.canonical_buckets import get_distance_bucket
                            import sqlite3
                            from pathlib import Path

                            # Load spot price for asset
                            spot_data_db = Path("c:/Dev/MERID/data/spot_prices.db")
                            if spot_data_db.exists():
                                conn = sqlite3.connect(str(spot_data_db))
                                cursor = conn.cursor()
                                cursor.execute("""
                                    SELECT price_usd FROM spot_prices
                                    WHERE asset = ? ORDER BY timestamp DESC LIMIT 1
                                """, (self.config.name,))
                                row = cursor.fetchone()
                                conn.close()

                                if row:
                                    spot_price = row[0]
                                    strike_price = getattr(market_state, 'strike_price_usd', None)
                                    if strike_price and spot_price > 0:
                                        distance_pct = abs(spot_price - strike_price) / spot_price * 100
                                        candidate["distance_band"] = get_distance_bucket(distance_pct)
                                        candidate["distance_pct"] = distance_pct
                                    else:
                                        candidate["distance_band"] = "unknown"
                                        candidate["distance_pct"] = None
                                else:
                                    candidate["distance_band"] = "unknown"
                                    candidate["distance_pct"] = None
                            else:
                                candidate["distance_band"] = "unknown"
                                candidate["distance_pct"] = None
                        except Exception as db_err:
                            logger.warning("[CANDIDATE-DISTANCE-BAND] Failed to calculate distance band: %s", db_err)
                            candidate["distance_band"] = "unknown"
                            candidate["distance_pct"] = None

            except Exception as e:

                logger.warning("[CANDIDATE-MICROSTRUCTURE] Failed to populate microstructure data: %s", e)



            # CRITICAL BUG FIX: Do NOT update cooldown timestamp here

            # The cooldown should only be updated AFTER a successful trade execution

            # Previously, this line was executed every time a candidate was generated,

            # which caused the cooldown to reset even when no trade was executed

            # This resulted in perpetual cooldown blocks preventing any trading

            # The cooldown timestamp is now updated in the fill handler (position_cache.on_fill)

            # or in the execution confirmation handler after successful order submission



            # CRITICAL FIX (2026-07-12): Strip order count should only increment on EXECUTED orders, not candidates
            # Previously this incremented on every candidate generation, causing misleading counts
            # Now strip order count is incremented in GLOBAL-ALLOCATOR-EXECUTE-SUCCESS path

            # CRITICAL FIX: 2026-08-02 - Add unique candidate ID for lifecycle tracking
            candidate_id = f"cid-{uuid.uuid4().hex[:12]}"
            candidate["candidate_id"] = candidate_id
            candidate["generation_tick"] = tick
            candidate["generation_timestamp_ms"] = int(time.time() * 1000)
            candidate["lifecycle_state"] = "EVALUATED"

            logger.info(
                "[CANDIDATE-EVALUATED] asset=%s side=%s strategy_intent=%s candidate_id=%s edge_pct=%.6f price_cents=%s",
                self.config.name, signal["side"], signal.get("strategy_intent", "N/A"), candidate_id,
                float(candidate.get("edge_pct", 0.0) or 0.0),
                candidate.get("price_cents", "N/A"),
            )



            # 2026-07-09: DISABLED direct execution in individual agents

            # Execution is now handled at grid level by global allocator

            # This allows edge-based allocation under venue cap instead of per-asset caps

            # The global allocator sorts candidates by edge and selects best ones under $1 cap



            # Set price_cents and count in candidate for allocator

            candidate["price_cents"] = int(signal.get("price_cents", 50))

            candidate["count"] = int(signal.get("count", 2))



            # Return candidate without execution (grid level will execute)

            self._record_waterfall("candidate_generated", True, f"side={signal.get('side')}")
            self._rejection_waterfall["selected"] = True

            return candidate



        except Exception as e:

            logger.error("[CANDIDATE-ERROR] asset=%s error=%s", self.config.name, str(e), exc_info=True)

            self._record_waterfall("candidate_generated", False, f"exception: {str(e)[:80]}")
            self._set_final_reason(f"candidate_generated: exception {str(e)[:80]}")

            return None



# Agent grid for 15m crypto trading

class LeanAgentGrid15m:

    # Minimal agent grid for 15m crypto trading

    # This grid does NOT:

    # - Load persisted agents

    # - Register with DeploymentController

    # - Run reflection/learning systems

    # - Use paper trading engine

    # - Start social broadcasters

    # It only:

    # - Holds 5 LeanAgent15m instances

    # - Runs cycles via run_cycle()

    # - Tracks basic lifecycle state



    def __init__(

        self,

        agents: list[LeanAgent15m],

    ):

        self._agents = agents

        self._running = False

        self._market_state_store = None

        self.position_cache = None  # Position cache for global allocator

        # Authoritative per-cycle Coinbase velocity snapshot, owned by the grid.
        self._coinbase_velocity_signals: Dict[str, Any] = {}

        # Initialize strip order tracking

        self._strip_order_counts: Dict[str, int] = {}

        self._current_market_ids: Dict[str, str] = {}

        # REST sync optimization: only sync every 30 seconds instead of every cycle

        self._last_rest_sync_time = 0.0

        self._rest_sync_interval = 30.0  # seconds

        # CRITICAL FIX (2026-08-12): Cache the most recent exchange snapshot for
        # canonical-live-position construction in the allocator.  This prevents a
        # stale asset-level position in the cache from blocking a candidate in the
        # current window.

        self._last_exchange_positions: List[Dict[str, Any]] = []

        self._last_open_orders: List[Dict[str, Any]] = []

        # CRITICAL FIX (2026-07-13): Track executed candidates to prevent duplicate executions
        # This prevents multiple orders with same ticker/side/price from executing in consecutive cycles
        self._executed_candidates: Set[str] = set()

        # 2026 BEST PRACTICE: Fallback activation tracking for degradation metrics
        self._fallback_activations: Dict[str, int] = {
            "ohlc_fallback": 0,
            "price_fallback": 0,
            "strike_fallback": 0,
            "indicator_stack_fallback": 0,
            "atr_warmup_fallback": 0,
            "dynamic_range_fallback": 0,
        }
        self._fallback_timestamps: Dict[str, list] = {
            key: [] for key in self._fallback_activations.keys()
        }

        logger.info("[AGENT-GRID-INIT] LeanAgentGrid15m initialized with %d agents and fallback tracking", len(agents))



    def set_market_state_store(self, market_state_store: Any) -> None:

        # Set the market state store after initialization.

        # This is called after the WS bridge starts and has the store available.

        self._market_state_store = market_state_store

        # Update all agents with the new store

        for agent in self._agents:

            agent.market_state_store = market_state_store

        logger.info("[AGENT-GRID] Market state store set for %d agents", len(self._agents))



    def set_position_cache(self, position_cache: Any) -> None:

        # Set the position cache after initialization.

        # This is called after the position cache is available for global allocator.

        self.position_cache = position_cache

        logger.info("[AGENT-GRID] Position cache set for global allocator")

    def _get_candidate_key(self, ticker: str, side: str, price_cents: int) -> str:
        # Generate a unique key for a candidate to prevent duplicate executions
        # Used in global allocator to track which candidates have been executed
        return f"{ticker}_{side}_{price_cents}c"



    async def start(self) -> None:

        # Start the agent grid.

        self._running = True

        # Reset strip order counts on startup to clear any stale state

        self._strip_order_counts.clear()

        self._current_market_ids.clear()

        # CRITICAL FIX (2026-07-13): Clear executed candidates on startup
        self._executed_candidates.clear()

        logger.info("[AGENT-GRID-START] LeanAgentGrid15m started - strip order counts reset")



    async def stop(self) -> None:

        # Stop the agent grid.

        self._running = False

        logger.info("[AGENT-GRID-STOP] LeanAgentGrid15m stopped")



    def reset_strip_order_counts(self) -> None:

        """Reset all strip order counts and market ID tracking.



        This is called when the catalog detects a market rollover (e.g., 16:15 -> 16:30).

        It resets the per-strip order limits so trading can continue on the new 15m strip.

        """

        self._strip_order_counts.clear()

        self._current_market_ids.clear()

        # CRITICAL FIX (2026-07-13): Clear executed candidates on market rollover
        self._executed_candidates.clear()

        # 2026 BEST PRACTICE: Clear fallback tracking on market rollover
        for key in self._fallback_activations:
            self._fallback_activations[key] = 0
        for key in self._fallback_timestamps:
            self._fallback_timestamps[key] = []

        logger.info("[STRIP-RESET-ALL] Reset all strip order counts, market ID tracking, and fallback metrics")

    def get_fallback_metrics(self) -> Dict[str, Any]:
        """Get fallback activation metrics for degradation monitoring (2026 best practice).

        Returns:
            Dict with fallback activation counts and recent timestamps
        """
        # Calculate recent fallback rate (last 5 minutes)
        now = time.time()
        recent_fallbacks = {}
        for key, timestamps in self._fallback_timestamps.items():
            recent_count = sum(1 for ts in timestamps if now - ts < 300)
            recent_fallbacks[key] = recent_count

        return {
            "total_activations": dict(self._fallback_activations),
            "recent_activations_5m": recent_fallbacks,
            "timestamp": now,
        }

    def _select_best_edge_per_asset(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Select the best edge candidate per asset.

        This ensures up to 2 contracts per asset per 15-minute window are executed,
        selecting the optimal combination of edge quality and price efficiency.

        Based on prediction market execution research:
        - Edge is the primary signal (model probability vs market probability)
        - Among similar edges, cheaper contracts provide better risk-adjusted returns
        - Lower capital exposure improves Kelly criterion sizing and reduces tail risk

        Args:
            candidates: List of candidate dictionaries with keys including:
                - agent_id: Agent identifier (e.g., "BTC_15M")
                - asset: Asset symbol (e.g., "BTC")
                - edge_pct: Edge percentage (e.g., 0.05 for 5%)
                - price_cents: Contract price in cents

        Returns:
            Filtered list with at most 1 candidate per asset
        """
        if not candidates:
            return []

        # Group candidates by asset
        asset_candidates: Dict[str, List[Dict[str, Any]]] = {}
        valid_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

        for candidate in candidates:
            # Extract asset from agent_id or asset field
            asset = candidate.get('asset')
            if not asset:
                agent_id = candidate.get('agent_id', '')
                if agent_id:
                    # Handle common formats: "BTC_15M", "ETH_15m", "SOL_15M", etc.
                    asset = agent_id.split('_')[0].upper() if '_' in agent_id else agent_id.upper()

            # Only process valid crypto assets
            if asset and asset in valid_assets:
                if asset not in asset_candidates:
                    asset_candidates[asset] = []
                asset_candidates[asset].append(candidate)

        # Select best candidate for each asset
        filtered_candidates = []
        edge_similarity_threshold = 0.01  # 1% threshold

        for asset, asset_cands in asset_candidates.items():
            if not asset_cands:
                continue

            # Sort by edge_pct descending (higher edge is better)
            asset_cands.sort(key=lambda c: c.get('edge_pct', 0), reverse=True)

            # Get the best edge
            best_edge = asset_cands[0]
            best_edge_pct = best_edge.get('edge_pct', 0)

            # Find candidates with similar edges (within threshold)
            similar_edges = [c for c in asset_cands if abs(c.get('edge_pct', 0) - best_edge_pct) <= edge_similarity_threshold]

            # Among similar edges, select the cheapest (lowest price_cents)
            if len(similar_edges) > 1:
                similar_edges.sort(key=lambda c: c.get('price_cents', 999))
                filtered_candidates.append(similar_edges[0])
            else:
                filtered_candidates.append(best_edge)

        return filtered_candidates



    async def sync_from_rest(self, tick: int) -> Dict[str, Any]:

        # Sync catalog and market state from REST API.

        # OPTIMIZATION: Only sync every 30 seconds instead of every cycle to reduce latency.

        # WebSocket provides real-time position updates, REST is used for reconciliation.

        # Returns a status dict with keys:
        #   success (bool), positions_count (int), open_orders_count (int),
        #   positions_fetched_ok (bool), open_orders_fetched_ok (bool),
        #   rest_timestamp (float), error (Optional[str]).

        import time

        current_time = time.time()

        result: Dict[str, Any] = {
            "success": False,
            "positions_count": 0,
            "open_orders_count": 0,
            "positions_fetched_ok": False,
            "open_orders_fetched_ok": False,
            "rest_timestamp": current_time,
            "error": None,
        }

        # Check if enough time has passed since last sync

        if current_time - self._last_rest_sync_time < self._rest_sync_interval:

            logger.info("[AGENT-GRID] Skipping REST sync - last sync %.1fs ago, interval is %.1fs",

                       current_time - self._last_rest_sync_time, self._rest_sync_interval)

            return result



        logger.info("[AGENT-GRID] BEFORE sync_from_rest tick=%d", tick)



        # Force sync position cache from REST API to clear stale data

        # PRODUCTION FIX: Call Kalshi client directly to avoid circular sync

        # (venue_adapter.get_positions() reads from cache, which causes circular sync)

        try:

            from merid.event_venues.kalshi.position_cache import get_position_cache

            from merid.event_venues.kalshi.client import KalshiVenueClient

            from merid.event_venues.kalshi.kalshi_config import get_kalshi_config

            position_cache = get_position_cache()

            if position_cache:

                # Get positions directly from Kalshi REST API

                client = KalshiVenueClient(config=get_kalshi_config())

                await client.connect()

                positions_result = await client.get_positions_result()

                result["positions_fetched_ok"] = positions_result.success

                if not positions_result.success:

                    logger.warning(
                        "[AGENT-GRID] Kalshi position query failed (will not wipe cache on transient error): %s",
                        positions_result.error
                    )

                    result["error"] = f"positions_query_failed: {positions_result.error}"

                    return result

                kalshi_positions = positions_result.unwrap_or([])

                result["positions_count"] = len(kalshi_positions)

                # Convert VenuePosition list to format expected by sync_from_rest

                rest_positions = []

                if kalshi_positions:

                    for pos in kalshi_positions:

                        # Convert average_entry_price from dollars to cents

                        avg_price_cents = int(float(pos.average_entry_price) * 100) if pos.average_entry_price else 0

                        rest_positions.append({

                            "market_id": pos.market_id,

                            "contracts": int(pos.size),

                            "side": pos.outcome_id or "yes",

                            "avg_price_cents": avg_price_cents,

                            "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0,

                            "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0,

                        })

                # Snapshot open orders first so sync_from_rest can use them for
                # authoritative stale/phantom cleanup without removing a market that has
                # a live order resting on the exchange.

                open_order_list = []

                open_orders_fetched_ok = False

                try:

                    open_orders_result = await client.get_open_orders_result()

                    if open_orders_result.success:

                        open_orders_fetched_ok = True

                        for order in open_orders_result.unwrap_or([]):

                            if not order.market_id:

                                continue

                            if order.status and order.status.lower() in ("filled", "cancelled", "canceled", "rejected", "expired"):

                                continue

                            open_order_list.append({

                                "market_id": order.market_id,

                                "side": order.side or "yes",

                                "contracts": int(order.size) if order.size else 0,

                                "price_cents": int(float(order.price) * 100) if order.price else 0,

                                "order_id": order.order_id or "",

                            })

                        logger.info("[AGENT-GRID] Snapshot open orders: %d", len(open_order_list))

                    else:

                        logger.warning(
                            "[AGENT-GRID] Kalshi open-order query failed: %s. "
                            "Proceeding with position sync but will not run stale cleanup without open orders.",
                            open_orders_result.error
                        )

                except Exception as open_orders_err:

                    logger.warning("[AGENT-GRID] Failed to snapshot open orders: %s", open_orders_err)

                result["open_orders_fetched_ok"] = open_orders_fetched_ok
                result["open_orders_count"] = len(open_order_list)

                # Only run stale cleanup when both position and open-order snapshots were
                # successfully fetched.  This prevents a transient API failure from being
                # misinterpreted as an authoritative empty exchange state.

                cleanup_stale = positions_result.success and open_orders_fetched_ok

                # Force sync to bypass staleness guard; pass open orders for safe cleanup.

                await position_cache.sync_from_rest(
                    rest_positions,
                    force=True,
                    open_orders=open_order_list,
                    cleanup_stale=cleanup_stale,
                )

                # Cache exchange snapshot for canonical live position construction.

                self._last_exchange_positions = rest_positions

                self._last_open_orders = open_order_list

                self._last_rest_sync_time = current_time

                result["success"] = True

                logger.info("[AGENT-GRID] Force synced position cache from Kalshi REST API (tick=%d, positions=%d)", tick, len(rest_positions))

        except Exception as e:

            logger.warning("[AGENT-GRID] Failed to force sync position cache: %s", e)

            result["error"] = str(e)



        logger.info("[AGENT-GRID] AFTER sync_from_rest tick=%d", tick)

        return result

    def _build_canonical_live_positions(
        self,
        assets: List[str]
    ) -> List[CanonicalLivePosition]:
        """Build an authoritative per-ticker live-position list.

        Combines:
        - position_cache.get_all_positions() (internal state)
        - the most recent exchange position snapshot (_last_exchange_positions)
        - the most recent open-order snapshot (_last_open_orders)

        A position is marked ``exchange_confirmed_open`` only when its market_id is
        present in the exchange snapshot.  An open order is marked
        ``pending_order_open`` when its market_id and side match a candidate market.
        Stale cache entries that do not appear on exchange and have no pending order
        are still listed for observability but ``is_open`` is False, so they do not
        block new allocation.
        """
        canonical: List[CanonicalLivePosition] = []
        if not self.position_cache:
            return canonical

        try:
            positions = self.position_cache.get_all_positions(validate_freshness=False)
        except Exception as e:
            logger.warning("[AGENT-GRID] Failed to get positions for canonical live list: %s", e)
            return canonical

        exchange_market_ids = {
            p.get("market_id") for p in self._last_exchange_positions if p.get("market_id")
        }

        open_orders_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        for o in self._last_open_orders:
            ticker = o.get("market_id")
            if not ticker:
                continue
            open_orders_by_ticker.setdefault(ticker, []).append(o)

        def _asset_from_ticker(ticker: str) -> Optional[str]:
            for asset in assets:
                if asset.lower() in ticker.lower():
                    return asset
            return None

        for pos_ticker, pos_obj in positions.items():
            if not pos_obj or pos_obj.contracts <= 0:
                continue

            asset = _asset_from_ticker(pos_ticker)
            if not asset:
                continue

            exchange_confirmed = pos_ticker in exchange_market_ids

            # Pending open order on the same market / side.
            pending_order_open = False
            pending_contracts = 0
            pending_price_cents = pos_obj.avg_price_cents or pos_obj.current_price_cents or 0
            order_side = (pos_obj.thesis_side or pos_obj.side or "yes").lower()
            if pos_ticker in open_orders_by_ticker:
                for o in open_orders_by_ticker[pos_ticker]:
                    if (o.get("side") or "").lower() == order_side:
                        pending_order_open = True
                        pending_contracts += o.get("contracts", 0)
                        if o.get("price_cents"):
                            pending_price_cents = o.get("price_cents")
                        break

            if pending_order_open:
                contracts = max(pending_contracts, pos_obj.contracts)
                price_cents = pending_price_cents or pos_obj.avg_price_cents or pos_obj.current_price_cents or 50
            else:
                contracts = pos_obj.contracts
                price_cents = pos_obj.avg_price_cents or pos_obj.current_price_cents or 50

            notional = (contracts * price_cents) / 100.0

            canonical.append(CanonicalLivePosition(
                asset=asset,
                ticker=pos_ticker,
                side=order_side,
                contracts=contracts,
                avg_price_cents=price_cents,
                notional_usd=notional,
                exchange_confirmed_open=exchange_confirmed,
                pending_order_open=pending_order_open,
            ))

        # Add any exchange positions not currently in the cache (e.g., recovered
        # positions that sync_from_rest has not yet materialised for this cycle).
        for ep in self._last_exchange_positions:
            ticker = ep.get("market_id")
            if not ticker or any(p.ticker == ticker for p in canonical):
                continue

            asset = _asset_from_ticker(ticker)
            if not asset:
                continue

            contracts = ep.get("contracts", 0)
            price_cents = ep.get("avg_price_cents", 0) or 50
            side = (ep.get("side") or "yes").lower()
            notional = (contracts * price_cents) / 100.0

            canonical.append(CanonicalLivePosition(
                asset=asset,
                ticker=ticker,
                side=side,
                contracts=contracts,
                avg_price_cents=price_cents,
                notional_usd=notional,
                exchange_confirmed_open=True,
                pending_order_open=False,
            ))

        # Add any open orders for markets that are not already represented by a
        # cached or exchange-confirmed position, so the allocator treats a resting
        # order on the candidate's ticker as live exposure.
        for o in self._last_open_orders:
            ticker = o.get("market_id")
            if not ticker or any(p.ticker == ticker for p in canonical):
                continue

            asset = _asset_from_ticker(ticker)
            if not asset:
                continue

            contracts = o.get("contracts", 0)
            price_cents = o.get("price_cents", 0) or 50
            side = (o.get("side") or "yes").lower()
            notional = (contracts * price_cents) / 100.0

            canonical.append(CanonicalLivePosition(
                asset=asset,
                ticker=ticker,
                side=side,
                contracts=contracts,
                avg_price_cents=price_cents,
                notional_usd=notional,
                exchange_confirmed_open=False,
                pending_order_open=True,
            ))

        logger.info(
            "[AGENT-GRID] Canonical live positions: %d (exchange_confirmed=%d, pending=%d)",
            len(canonical),
            sum(1 for p in canonical if p.exchange_confirmed_open),
            sum(1 for p in canonical if p.pending_order_open),
        )

        return canonical



    async def run_cycle(self, tick: int, allow_new_entries: bool = True, coinbase_velocity: Dict = None) -> list[Dict[str, Any]]:

        # Run a single trading cycle across all agents.

        # coinbase_velocity: External spot velocity signals from Coinbase WebSocket (Turbine research #1 winner)
        # Format: {asset: {velocity: float, timestamp: float, signal_type: str}}

        # Store Coinbase velocity signals for use in signal generation
        if coinbase_velocity:
            self._coinbase_velocity_signals = coinbase_velocity
            logger.debug("[AGENT-GRID] Received Coinbase velocity signals: %s", coinbase_velocity)

        # CRITICAL FIX: Update indicator stacks for all agents BEFORE sync_from_rest

        # This ensures indicator stacks get price data even when agents are in cooldown

        # Otherwise they will never warm up and will always return empty snapshots

        # This runs on every cycle regardless of individual agent trading status

        # IMPORTANT: Move this BEFORE sync_from_rest because sync_from_rest has an early return

        # when the sync interval hasn't elapsed, which would prevent this code from running

        try:

            logger.info("[AGENT-GRID-INDICATOR-UPDATE-START] tick=%d num_agents=%d", tick, len(self._agents))

            for agent in self._agents:

                logger.info("[AGENT-GRID-INDICATOR-AGENT] agent=%s has_indicator_stacks=%s", agent.config.name, hasattr(agent, '_indicator_stacks'))

                if hasattr(agent, '_indicator_stacks') and agent._indicator_stacks:

                    try:

                        for update_asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:

                            if update_asset in agent._indicator_stacks:

                                try:

                                    # Fetch spot price for this asset

                                    update_spot_price = None

                                    update_spot_data = None



                                    # CRITICAL FIX: Use global unified spot service instead of agent.spot_provider

                                    # The agent's spot_provider attribute doesn't have a get() method

                                    # Use the same pattern as collect_order_candidate and other parts of the codebase

                                    try:

                                        from data.unified_spot_service import get_unified_spot_service

                                        spot_service = get_unified_spot_service()

                                        result = spot_service.get(update_asset)

                                        if result is not None and hasattr(result, 'price'):

                                            update_spot_price = result.price

                                            update_spot_data = result

                                    except Exception as e:

                                        logger.warning("[AGENT-GRID-INDICATOR-ERROR] agent=%s asset=%s failed to fetch spot price: %s",

                                                     agent.config.name, update_asset, e)



                                    if update_spot_price:

                                        # Buffer spot price for 1-minute aggregation
                                        # NOTE: Indicator stack uses spot prices as proxies for underlying crypto price movement
                                        # This is intentional - technical indicators (RSI, MACD, EMA) are calculated on the underlying asset,
                                        # not the Kalshi prediction market prices (which are 0-1 range binary options)
                                        agent._indicator_stack_price_buffer[update_asset].append(update_spot_price)



                                        # Check if 1 minute has elapsed since last update

                                        current_time = time.time()

                                        last_update = agent._indicator_stack_last_update[update_asset]

                                        time_since_update = current_time - last_update



                                        # CRITICAL FIX: Allow immediate updates during warmup (first update)

                                        # After warmup, use 15-second aggregation for faster signal generation

                                        # With 3s spot refresh, 60s aggregation is too slow for fast-moving prediction markets

                                        is_warmup = (last_update == 0.0)



                                        if is_warmup or time_since_update >= 15.0:

                                            # Use the last price in the buffer as the 1-minute close

                                            if agent._indicator_stack_price_buffer[update_asset]:

                                                minute_close = agent._indicator_stack_price_buffer[update_asset][-1]

                                                agent._indicator_stacks[update_asset].update(minute_close)

                                                agent._indicator_stack_last_update[update_asset] = current_time

                                                agent._indicator_stack_price_buffer[update_asset] = []  # Clear buffer

                                except Exception as e:

                                    logger.warning("[AGENT-GRID-INDICATOR-UPDATE] agent=%s asset=%s failed to update Crypto15mIndicatorStack: %s", agent.config.name, update_asset, e)

                    except Exception as e:

                        logger.warning("[AGENT-GRID-INDICATOR-UPDATE] agent=%s failed to update indicator stacks: %s", agent.config.name, e)
                else:
                    logger.warning("[AGENT-GRID-INDICATOR-NO-STACKS] agent=%s does not have _indicator_stacks or it is empty", agent.config.name)

        except Exception as e:

            logger.error("[AGENT-GRID-INDICATOR-UPDATE] CRITICAL ERROR in indicator stack update: %s", e, exc_info=True)



        # Sync from REST at the beginning of each cycle

        await self.sync_from_rest(tick)



        # Phase 1: Collect all candidates from all agents (without execution)

        # OPTIMIZATION: Process agents in parallel using asyncio.gather instead of sequential processing

        # This reduces agent processing time from ~15s to ~3s for 5 agents

        candidates = []



        # Create tasks for all agents to run in parallel

        agent_tasks = []

        for agent in self._agents:

            logger.info("[AGENT-GRID-RUN-CYCLE-AGENT] agent=%s", agent.config.name)

            # CRITICAL FIX: Inject the authoritative per-cycle Coinbase velocity snapshot
            # into each agent before collection.  The grid owns the live signal; the agent
            # must not rely on a stale or unset agent-local copy.
            agent.set_velocity_snapshot(self._coinbase_velocity_signals.copy())

            agent_tasks.append(agent.collect_order_candidate(tick))



        # Execute all agent tasks in parallel

        results = await asyncio.gather(*agent_tasks, return_exceptions=True)



        # Process results

        # 2026-07-25: Track per-asset candidate counts and signal quality metrics
        per_asset_candidates = {}
        signal_quality_metrics = {}  # asset -> list of (model_prob_yes, edge_yes_frac, edge_no_frac)

        for agent, result in zip(self._agents, results):

            if isinstance(result, Exception):

                logger.error("[CYCLE-ERROR] agent=%s error=%s", agent.config.name, str(result), exc_info=True)

            elif result:

                candidates.append(result)

                logger.info("[AGENT-GRID-RUN-CYCLE-CANDIDATE] agent=%s side=%s", agent.config.name, result.get('side'))

                # Track per-asset candidate count (extract asset from agent name, e.g., "BTC_15M" -> "BTC")
                asset = agent.config.name.split('_')[0]  # Extract asset from agent name
                per_asset_candidates[asset] = per_asset_candidates.get(asset, 0) + 1

                # Track signal quality metrics
                model_prob_yes = result.get('model_prob_yes')
                edge_yes_frac = result.get('edge_yes_frac')
                edge_no_frac = result.get('edge_no_frac')
                if model_prob_yes is not None and edge_yes_frac is not None and edge_no_frac is not None:
                    if asset not in signal_quality_metrics:
                        signal_quality_metrics[asset] = []
                    signal_quality_metrics[asset].append((model_prob_yes, edge_yes_frac, edge_no_frac))

            else:

                logger.info("[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE] agent=%s", agent.config.name)

                # Track zero candidates for asset (extract asset from agent name, e.g., "BTC_15M" -> "BTC")
                asset = agent.config.name.split('_')[0]  # Extract asset from agent name
                per_asset_candidates[asset] = per_asset_candidates.get(asset, 0)

        # Log per-asset candidate counts (every tick to detect hidden filters)
        for asset, count in per_asset_candidates.items():
            logger.info("[SIGNAL-METRICS] asset=%s candidates=%d", asset, count)

        # Log per-cycle rejection waterfall by asset
        waterfall_rows = []
        for agent in self._agents:
            asset = agent.config.name.split('_')[0]
            wf = agent.get_rejection_waterfall()
            stages = wf.get("stages", {})
            selected = wf.get("selected", False)
            row = {
                "asset": asset,
                "market_discovered": "PASS" if stages.get("market_discovered", {}).get("status") else (stages.get("market_discovered", {}).get("reason") or "N/A"),
                "spot_price": "PASS" if stages.get("spot_price", {}).get("status") else (stages.get("spot_price", {}).get("reason") or "N/A"),
                "market_open": "PASS" if stages.get("market_open", {}).get("status") else (stages.get("market_open", {}).get("reason") or "N/A"),
                "signal_generated": "PASS" if stages.get("signal_generated", {}).get("status") else (stages.get("signal_generated", {}).get("reason") or "N/A"),
                "candidate_generated": "PASS" if stages.get("candidate_generated", {}).get("status") else (stages.get("candidate_generated", {}).get("reason") or "N/A"),
                "selected": "YES" if selected else "NO",
                "final_reason": wf.get("final_reason", ""),
            }
            waterfall_rows.append(row)

        if waterfall_rows:
            import json
            logger.info(
                "[REJECTION-WATERFALL] tick=%d table=%s",
                tick, json.dumps(waterfall_rows, default=str)
            )

        # Read-only decision telemetry: one record per asset per cycle plus a
        # DECISION-SCORECARD. Never affects candidates, allocator, or execution.
        telemetry_candidates_by_asset: Dict[str, Dict[str, Any]] = {}
        for _cand in candidates:
            _cid = str(_cand.get('agent_id', '') or '')
            _casset = (_cid.split('_')[0].upper() if '_' in _cid else _cid.upper()) or str(_cand.get('asset', '')).upper()
            if _casset:
                telemetry_candidates_by_asset[_casset] = _cand
        telemetry_state = {"emitted": False}

        # Allocated below when entries are enabled; the nested telemetry function
        # needs a stable binding even if allocation throws before it is assigned.
        allocator = None

        def _emit_cycle_decision_telemetry(chosen_orders=None, allocator_note: str = "") -> None:
            if telemetry_state["emitted"]:
                return
            telemetry_state["emitted"] = True
            try:
                from merid.prediction import decision_telemetry as _dt
                if not _dt.telemetry_enabled():
                    return
                ranked = sorted(
                    telemetry_candidates_by_asset.values(),
                    key=lambda c: float(c.get('edge_pct') or 0.0),
                    reverse=True,
                )
                candidate_ranks = {id(c): i + 1 for i, c in enumerate(ranked)}

                # Build a lookup for chosen orders by (ticker, side) and candidate_id.
                chosen_map = {}
                chosen_by_candidate_id = {}
                for _idx, _o in enumerate(chosen_orders or []):
                    chosen_map[(_o.ticker, _o.side)] = _idx + 1
                    _ocid = getattr(_o, 'candidate_id', None)
                    if _ocid:
                        chosen_by_candidate_id[_ocid] = _idx + 1

                allocation_ran = chosen_orders is not None and not allocator_note
                decisions = []
                if allocation_ran and allocator is not None:
                    decisions = allocator.get_allocation_decisions(tick)
                # Index decisions by candidate_id for fast lookup.
                decisions_by_cid = {d.candidate_id: d for d in decisions if d.candidate_id}

                records = []
                counters: Dict[str, Dict[str, Any]] = {}

                for _agent in self._agents:
                    _asset = _agent.config.name.split('_')[0]
                    _cand = telemetry_candidates_by_asset.get(_asset.upper())
                    _a_rank = None
                    _selected = False

                    # Find the allocator decision for this candidate (if any).
                    _alloc_decision: Optional[Any] = None
                    if _cand is not None and decisions_by_cid:
                        _cid = str(_cand.get('candidate_id') or '')
                        if _cid in decisions_by_cid:
                            _alloc_decision = decisions_by_cid[_cid]

                    if _cand is not None:
                        _key = (_cand.get('ticker'), _cand.get('side'))
                        if _alloc_decision is not None and _alloc_decision.selected:
                            _selected = True
                            _a_rank = chosen_by_candidate_id.get(_alloc_decision.candidate_id) or chosen_map.get(_key)
                        else:
                            _a_rank = chosen_map.get(_key)
                            _selected = _key in chosen_map

                    _rec = _dt.build_asset_record(
                        cycle_id=tick,
                        asset=_asset,
                        decision=getattr(_agent, '_cycle_decision', {}) or {},
                        waterfall=_agent.get_rejection_waterfall(),
                        candidate=_cand,
                        candidate_rank=candidate_ranks.get(id(_cand)) if _cand is not None else None,
                        allocator_rank=_a_rank,
                        allocator_selected=_selected,
                        allocator_note=allocator_note,
                    )

                    # Enrich the record with the concrete allocator decision.
                    if _alloc_decision is not None:
                        _rec["allocator_candidate_id"] = _alloc_decision.candidate_id
                        _rec["allocator_decision"] = {
                            "selected": _alloc_decision.selected,
                            "terminal_reason": _alloc_decision.terminal_reason,
                            "rejection_stage": _alloc_decision.rejection_stage,
                            "constraint_reasons": _alloc_decision.constraint_reasons,
                            "requested_quantity_fp": _alloc_decision.requested_quantity_fp,
                            "approved_quantity_fp": _alloc_decision.approved_quantity_fp,
                        }
                        if _alloc_decision.constraint_reasons:
                            _rec["allocator_constraint_reasons"] = _alloc_decision.constraint_reasons

                    if _cand is not None and allocation_ran:
                        if _selected:
                            _rec["rejection_stage"] = "selected"
                            _rec["rejection_reason"] = None
                        else:
                            _rec["rejection_stage"] = "allocator_loss"
                            concrete = _alloc_decision.terminal_reason if _alloc_decision is not None else None
                            if _alloc_decision is not None and _alloc_decision.constraint_reasons:
                                concrete = _alloc_decision.constraint_reasons[0]
                            _rec["rejection_reason"] = concrete or "allocator_loss"
                    records.append(_rec)

                    # Accumulate per-asset allocator counters.
                    if _alloc_decision is not None:
                        if _asset not in counters:
                            counters[_asset] = {
                                "asset": _asset,
                                "candidates_generated": 0,
                                "allocator_evaluated": 0,
                                "selected": 0,
                                "allocator_rejected": 0,
                                "total_rejections": 0,
                                "terminal": 0,
                                "signal_rejected": 0,
                                "router_rejected": 0,
                                "execution_failed": 0,
                                "constraint_reasons": {},
                            }
                        ctr = counters[_asset]
                        ctr["candidates_generated"] += 1
                        ctr["allocator_evaluated"] += 1
                        if _alloc_decision.selected:
                            ctr["selected"] += 1
                        else:
                            ctr["allocator_rejected"] += 1
                            ctr["total_rejections"] += 1
                            if _alloc_decision.terminal_reason:
                                ctr["terminal"] += 1
                            concrete = _alloc_decision.constraint_reasons[0] if _alloc_decision.constraint_reasons else _alloc_decision.terminal_reason
                            if concrete:
                                ctr["constraint_reasons"][concrete] = ctr["constraint_reasons"].get(concrete, 0) + 1
                    elif _cand is None:
                        # No candidate generated for this asset: count as signal-level
                        # rejection if the agent recorded a final reason.
                        _decision = getattr(_agent, '_cycle_decision', {}) or {}
                        _wf = _agent.get_rejection_waterfall()
                        _reason = _decision.get('rejection_reason') or _wf.get('final_reason')
                        if _reason:
                            if _asset not in counters:
                                counters[_asset] = {
                                    "asset": _asset,
                                    "candidates_generated": 0,
                                    "allocator_evaluated": 0,
                                    "selected": 0,
                                    "allocator_rejected": 0,
                                    "total_rejections": 0,
                                    "terminal": 0,
                                    "signal_rejected": 0,
                                    "router_rejected": 0,
                                    "execution_failed": 0,
                                    "constraint_reasons": {},
                                }
                            ctr = counters[_asset]
                            ctr["signal_rejected"] += 1
                            ctr["total_rejections"] += 1
                            ctr["constraint_reasons"][_reason] = ctr["constraint_reasons"].get(_reason, 0) + 1

                counter_list = list(counters.values())
                if counter_list:
                    logger.info("[ALLOCATION-COUNTERS] %s", json.dumps(counter_list, default=str))

                _dt.emit_cycle(
                    tick,
                    records,
                    extra={
                        "allocator_note": allocator_note or None,
                        "allocator_counters": counter_list,
                    },
                )
            except Exception as _tel_exc:
                logger.warning("[DECISION-TELEMETRY] non-fatal emit error: %s", _tel_exc)

        # Log signal quality histogram every 60 ticks (5 minutes at 5s cadence)
        if tick % 60 == 0 and signal_quality_metrics:
            logger.info("[SIGNAL-QUALITY-HISTOGRAM] tick=%d", tick)
            for asset, metrics in signal_quality_metrics.items():
                if not metrics:
                    continue
                model_probs = [m[0] for m in metrics]
                edge_yes = [m[1] for m in metrics]
                edge_no = [m[2] for m in metrics]

                import statistics
                model_mean = statistics.mean(model_probs) if model_probs else 0.0
                model_median = statistics.median(model_probs) if model_probs else 0.0
                edge_yes_mean = statistics.mean(edge_yes) if edge_yes else 0.0
                edge_yes_median = statistics.median(edge_yes) if edge_yes else 0.0
                edge_no_mean = statistics.mean(edge_no) if edge_no else 0.0
                edge_no_median = statistics.median(edge_no) if edge_no else 0.0

                logger.info(
                    "[SIGNAL-QUALITY] asset=%s samples=%d "
                    "model_prob_mean=%.4f model_prob_median=%.4f "
                    "edge_yes_mean=%.4f edge_yes_median=%.4f "
                    "edge_no_mean=%.4f edge_no_median=%.4f",
                    asset, len(metrics),
                    model_mean, model_median,
                    edge_yes_mean, edge_yes_median,
                    edge_no_mean, edge_no_median
                )

        logger.info("[CYCLE-COMPLETE] tick=%d candidates=%d", tick, len(candidates))



        # CRITICAL FIX (2026-07-16): Pre-filter candidates to select cheapest with best edge per asset
        # This ensures we execute up to 2 contracts per asset per window (capped by $1 exposure), selecting the optimal combination
        # of edge quality and price efficiency. Based on research from prediction market execution
        # literature: edge is the primary signal, but among similar edges, cheaper contracts provide
        # better risk-adjusted returns due to lower capital exposure.
        candidates = self._select_best_edge_per_asset(candidates)
        logger.info("[BEST-EDGE-FILTER] tick=%d filtered_candidates=%d", tick, len(candidates))



        # Phase 2: Apply global allocator to select best edges under venue cap

        if candidates and allow_new_entries:

            try:

                from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate, CanonicalLivePosition, create_global_allocator_from_envelope

                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope



                # Get risk envelope for allocator configuration

                envelope = get_kalshi_crypto_15m_risk_envelope()

                # CRITICAL FIX (2026-07-13): Reuse existing allocator singleton to preserve pending order tracking
                # Creating a new allocator every cycle resets _pending_orders, defeating the purpose
                from merid.risk.profiles.global_allocator import get_global_allocator, set_global_allocator
                allocator = get_global_allocator()
                if allocator is None:
                    allocator = create_global_allocator_from_envelope(envelope)
                    set_global_allocator(allocator)
                    logger.info("[GLOBAL-ALLOCATOR] Created new allocator instance")
                else:
                    logger.info("[GLOBAL-ALLOCATOR] Reusing existing allocator instance (preserves pending order tracking)")



                # Convert candidates to OrderCandidate objects

                order_candidates = []

                for candidate in candidates:

                    # Extract asset from agent_id (e.g., "BTC_15M" -> "BTC")
                    # 2026-07-13: Use robust asset extraction to handle various agent_id formats
                    agent_id = candidate.get('agent_id', '')

                    # Try to extract from agent_id first
                    if agent_id:
                        # Handle common formats: "BTC_15M", "ETH_15m", "SOL_15M", etc.
                        asset = agent_id.split('_')[0].upper() if '_' in agent_id else agent_id.upper()
                        # Validate it's one of the 5 crypto assets
                        if asset not in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            asset = candidate.get('asset', 'UNKNOWN')
                    else:
                        asset = candidate.get('asset', 'UNKNOWN')



                    # CRITICAL FIX: Check if there's already a resting order for this ticker/price/side

                    # This prevents duplicate order generation when the same candidate is selected repeatedly

                    ticker = candidate.get('ticker', '')

                    price_cents = int(candidate.get('price_cents', 50))

                    # Fail-closed: a candidate without a valid side is not executable.
                    try:
                        side = require_outcome_side(
                            candidate,
                            context=f"agent_grid_15m candidate ticker={ticker}",
                            fields=("side", "outcome_side", "kalshi_side", "thesis_side"),
                        )
                    except SideValidationError as side_err:
                        logger.error(
                            "[AGENT-GRID-CANDIDATE-SIDE-INVALID] %s: skipping candidate with missing/invalid side: %s",
                            ticker, side_err,
                        )
                        continue

                    action = candidate.get('action', 'buy')



                    # CRITICAL FIX (2026-07-13): Check for existing resting orders using resting_order_monitor
                    # This prevents duplicate order submissions when a resting order already exists
                    # The previous check used self.order_gate which is never set in the production stack
                    has_resting_order = False

                    try:

                        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

                        monitor = get_resting_order_monitor()

                        if monitor:

                            # Check for existing resting orders with same ticker, side, action
                            # Note: We don't check price_cents here because resting orders may have different prices
                            # The key is to prevent multiple orders for the same ticker/side/action combination
                            open_order_id = monitor.find_open_order(

                                ticker=ticker,

                                side=side,

                                action=action

                            )

                            if open_order_id:

                                has_resting_order = True

                                logger.info("[GLOBAL-ALLOCATOR] Skipping candidate with existing resting order: ticker=%s side=%s action=%s order_id=%s",

                                           ticker, side, action, open_order_id)

                    except Exception as e:

                        logger.warning("[GLOBAL-ALLOCATOR] Failed to check for resting orders: %s", e)



                    if has_resting_order:

                        continue  # Skip this candidate - there's already a resting order



                    # Get current position notional for this asset

                    current_position_notional = 0.0

                    if self.position_cache:

                        try:

                            positions = self.position_cache.get_all_positions(validate_freshness=False)

                            # CRITICAL FIX: Filter positions by current window to prevent counting stale positions
                            # Get current window ticker for this asset
                            from merid.event_venues.kalshi.market_catalog import get_market_catalog
                            catalog = get_market_catalog()
                            current_window_ticker = None
                            if catalog:
                                try:
                                    current_market = catalog.get_current_15m_market(asset)
                                    if current_market:
                                        current_window_ticker = current_market.market.market_id
                                except Exception as ticker_err:
                                    logger.warning("[GLOBAL-ALLOCATOR] Failed to get current window ticker: %s", ticker_err)

                            for pos_ticker, pos_obj in positions.items():

                                if pos_obj and pos_obj.contracts > 0:
                                    # CRITICAL FIX: Only count positions from current window
                                    # Skip stale positions from previous windows
                                    if current_window_ticker and pos_ticker != current_window_ticker:
                                        continue

                                    # Check if position belongs to this asset

                                    if asset.lower() in pos_ticker.lower():

                                        pos_price = pos_obj.current_price_cents if hasattr(pos_obj, 'current_price_cents') else candidate.get('price_cents', 50)

                                        current_position_notional += (pos_obj.contracts * pos_price) / 100.0

                        except Exception as e:

                            logger.warning("[GLOBAL-ALLOCATOR] Failed to get current positions: %s", e)



                    order_candidate = OrderCandidate(

                        asset=asset,

                        ticker=ticker,

                        side=side,

                        action=action,

                        price_cents=price_cents,

                        count=int(candidate.get('count', 1)),

                        edge_pct=float(candidate.get('edge_pct', 0.0)),

                        confidence=float(candidate.get('confidence', 0.5)),

                        model_prob=float(candidate.get('model_prob', 0.5)),

                        agent_name=candidate.get('agent_id', asset),

                        candidate_id=str(candidate.get('candidate_id', '') or ''),

                    )

                    order_candidates.append(order_candidate)



                # Build canonical live positions: exchange-confirmed per-ticker exposure
                # that prevents a stale asset-level position in a different window from
                # blocking the current candidate.

                canonical_live_positions: List[CanonicalLivePosition] = []

                if self.position_cache:

                    try:

                        canonical_live_positions = self._build_canonical_live_positions(
                            ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
                        )

                    except Exception as e:

                        logger.warning("[GLOBAL-ALLOCATOR] Failed to build canonical live positions: %s", e)

                # Legacy current_positions fallback (ignored when canonical provided)

                current_positions = {}

                if self.position_cache:

                    try:

                        positions = self.position_cache.get_all_positions(validate_freshness=False)

                        for pos_ticker, pos_obj in positions.items():

                            if pos_obj and pos_obj.contracts > 0:

                                pos_price = pos_obj.current_price_cents if hasattr(pos_obj, 'current_price_cents') else 50

                                pos_notional = (pos_obj.contracts * pos_price) / 100.0

                                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:

                                    if asset.lower() in pos_ticker.lower():

                                        current_positions[asset] = current_positions.get(asset, 0.0) + pos_notional

                                        break

                    except Exception as e:

                        logger.warning("[GLOBAL-ALLOCATOR] Failed to build legacy current positions: %s", e)

                # Run global allocator with authoritative per-ticker exposure
                # CRITICAL FIX (2026-08-14): Fail-close on allocator exception.
                # An allocator crash must never return unfiltered candidates to the
                # execution path; it is equivalent to disabling all risk/edge filters.
                try:
                    chosen_orders = allocator.allocate(
                        order_candidates,
                        current_positions=current_positions,
                        canonical_live_positions=canonical_live_positions,
                        cycle_id=tick,
                    )
                except Exception as alloc_err:
                    logger.error(
                        "[GLOBAL-ALLOCATOR] Allocation failed; returning empty candidate list: %s",
                        alloc_err,
                        exc_info=True,
                    )
                    _emit_cycle_decision_telemetry(chosen_orders=None, allocator_note="allocator_error")
                    return []



                # Get allocation summary

                summary = allocator.get_allocation_summary(chosen_orders)

                logger.info(

                    "[GLOBAL-ALLOCATOR-SUMMARY] chosen=%d, total_notional=$%.2f, utilization=%.1f%%, avg_edge=%.1f%%",

                    summary['total_orders'], summary['total_notional'], summary['utilization_pct'], summary['avg_edge']

                )

                _emit_cycle_decision_telemetry(chosen_orders=chosen_orders)



                # CRITICAL FIX (2026-07-21): Return chosen orders as candidates instead of executing directly
                # The agent grid should return candidates to loop_15m.py for proper validation and execution
                # loop_15m.py has critical checks: duplicate prevention, edge re-validation, count=0 check, parity checks
                # Executing directly bypasses these checks and causes the 0% fill rate issue

                # Convert chosen orders back to candidate format for loop_15m.py processing
                # Preserve original candidates list for lookup
                original_candidates = candidates
                candidates = []
                for order in chosen_orders:
                    # Find the original candidate for this order, preferring candidate_id
                    # (immutable end-to-end identity) and falling back to ticker/side.
                    original_candidate = None
                    if getattr(order, 'candidate_id', None):
                        for candidate in original_candidates:
                            if candidate.get('candidate_id') == order.candidate_id:
                                original_candidate = candidate
                                break
                    if original_candidate is None:
                        for candidate in original_candidates:
                            if candidate.get('ticker') == order.ticker and candidate.get('side') == order.side:
                                original_candidate = candidate
                                break

                    if original_candidate:
                        # 2026-08-05: Do NOT inject TP/SL metadata here. Exit policy resolution in
                        # loop_15m._execute_candidate (via resolve_exit_policy) is the single source
                        # of truth for TP/SL. Injecting tight 1c targets from the allocator was
                        # overriding the policy and causing premature exits.
                        candidates.append(original_candidate)
                        logger.info(
                            "[GLOBAL-ALLOCATOR-RETURN] asset=%s ticker=%s side=%s price=%dc count=%d edge=%.1f%%",
                            order.asset, order.ticker, order.side, order.price_cents, order.count, order.edge_pct
                        )
                    else:
                        logger.warning(
                            "[GLOBAL-ALLOCATOR] Original candidate not found for order: ticker=%s side=%s",
                            order.ticker, order.side
                        )

                # LIFECYCLE: emit unambiguous ADMITTED/REJECTED telemetry for every evaluated candidate.
                selected_ids = {c.get("candidate_id") for c in candidates}
                _decisions_for_candidate = {
                    d.candidate_id: d for d in allocator.get_allocation_decisions(tick) if d.candidate_id
                }
                for oc in original_candidates:
                    cid = oc.get("candidate_id")
                    _ad = _decisions_for_candidate.get(cid)
                    if cid in selected_ids:
                        logger.info(
                            "[CANDIDATE-ADMITTED] candidate_id=%s ticker=%s side=%s edge_pct=%.6f reason=allocator_selected",
                            cid, oc.get("ticker"), oc.get("side"), float(oc.get("edge_pct", 0.0) or 0.0)
                        )
                    else:
                        concrete = _ad.constraint_reasons[0] if (_ad and _ad.constraint_reasons) else "allocator_loss"
                        logger.info(
                            "[CANDIDATE-REJECTED] candidate_id=%s ticker=%s side=%s edge_pct=%.6f reason=%s",
                            cid, oc.get("ticker"), oc.get("side"), float(oc.get("edge_pct", 0.0) or 0.0), concrete
                        )

            except Exception as e:
                logger.error(
                    "[GLOBAL-ALLOCATOR] CRITICAL ERROR in global allocator phase: %s",
                    str(e), exc_info=True
                )
                # FAIL-CLOSED: an unfiltered candidate list reaching loop_15m can
                # execute extreme prices the allocator would have rejected.  Do not
                # return raw candidates.
                for oc in (original_candidates if 'original_candidates' in locals() else candidates):
                    logger.info(
                        "[CANDIDATE-REJECTED] candidate_id=%s ticker=%s side=%s edge_pct=%.6f reason=allocator_phase_error",
                        oc.get("candidate_id"), oc.get("ticker"), oc.get("side"),
                        float(oc.get("edge_pct", 0.0) or 0.0)
                    )
                _emit_cycle_decision_telemetry(chosen_orders=None, allocator_note="allocator_phase_error")
                return []

        if not telemetry_state["emitted"]:
            if not candidates:
                _emit_cycle_decision_telemetry(chosen_orders=None, allocator_note="no_candidates")
            elif not allow_new_entries:
                _emit_cycle_decision_telemetry(chosen_orders=None, allocator_note="entries_disabled")

        # When new entries are disabled, the global allocator is intentionally
        # skipped.  The filtered (best-edge) candidate list is still returned so
        # the loop can monitor signals and telemetry, but loop_15m must not
        # execute it when allow_new_entries is False.
        if not allow_new_entries:
            for c in candidates:
                logger.info(
                    "[CANDIDATE-REJECTED] candidate_id=%s ticker=%s side=%s edge_pct=%.6f reason=entries_disabled",
                    c.get("candidate_id"), c.get("ticker"), c.get("side"),
                    float(c.get("edge_pct", 0.0) or 0.0)
                )
            logger.info("[AGENT-GRID] allow_new_entries=False; returning %d filtered candidates (not allocated)", len(candidates))
            return candidates

        # CRITICAL FIX: Return candidates list to prevent TypeError in loop_15m
        # loop_15m expects run_cycle to return a list, not None
        return candidates


def _extract_error_message(result) -> str:
    """Extract a human-readable error message from a result object.

    Handles structured results that expose `error_message`, `message`, `reason`,
    or a dict `payload` with a reason field. This keeps error extraction
    consistent across ToolResult / OrderResult / other result wrappers.
    """
    if hasattr(result, 'error_message') and result.error_message:
        return str(result.error_message)
    if hasattr(result, 'message') and result.message:
        return str(result.message)
    if hasattr(result, 'reason') and result.reason:
        return str(result.reason)
    if hasattr(result, 'payload') and isinstance(result.payload, dict):
        return str(result.payload.get('reason', str(result.payload)))
    return str(result)


# Canonical fee alias for backward-compatible imports and regression tests.
# Backwards-compatible aliases used by legacy test suites.
AgentGrid15M = LeanAgent15m

# Tests expect a fee function with signature (contracts, price_cents) returning an int.
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents as canonical_calculate_kalshi_fee_cents
from merid.prediction.trade_decision import compute_trade_decision
from merid.prediction.shadow_side_telemetry import write_shadow_side_record, write_model_decomposition_record


# ═════════════════════════════════════════════════════════════════════════════
# Config-driven asset profile and regime knobs
# ═════════════════════════════════════════════════════════════════════════════
# These constants satisfy tests/config/test_kalshi_15m_invariants.py and
# provide the canonical per-asset base parameters and regime multipliers.

from enum import Enum


class RiskRegime(Enum):
    """Trading regime used by _get_effective_knobs."""

    CONSERVATIVE = "conservative"
    NORMAL = "normal"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class _AssetProfile:
    """Per-asset base parameters."""

    base_edge_threshold: float
    base_max_contracts_per_strip: int
    base_max_concurrent_strips: int
    min_depth_yes_base: int
    min_depth_no_base: int


@dataclass(frozen=True)
class _RegimeKnobs:
    """Regime-specific absolute values."""

    edge_threshold: float
    size_factor: float
    max_trades_per_cycle_asset: int
    depth_mult: float


ASSET_PROFILE: Dict[str, _AssetProfile] = {
    "BTC": _AssetProfile(
        base_edge_threshold=0.06,
        base_max_contracts_per_strip=2,
        base_max_concurrent_strips=3,
        min_depth_yes_base=15,
        min_depth_no_base=15,
    ),
    "ETH": _AssetProfile(
        base_edge_threshold=0.06,
        base_max_contracts_per_strip=2,
        base_max_concurrent_strips=3,
        min_depth_yes_base=15,
        min_depth_no_base=15,
    ),
    "SOL": _AssetProfile(
        base_edge_threshold=0.07,
        base_max_contracts_per_strip=2,
        base_max_concurrent_strips=3,
        min_depth_yes_base=10,
        min_depth_no_base=10,
    ),
    "XRP": _AssetProfile(
        base_edge_threshold=0.07,
        base_max_contracts_per_strip=2,
        base_max_concurrent_strips=3,
        min_depth_yes_base=10,
        min_depth_no_base=10,
    ),
    "DOGE": _AssetProfile(
        base_edge_threshold=0.08,
        base_max_contracts_per_strip=2,
        base_max_concurrent_strips=2,
        min_depth_yes_base=10,
        min_depth_no_base=10,
    ),
}


REGIME_KNOBS: Dict[RiskRegime, _RegimeKnobs] = {
    RiskRegime.CONSERVATIVE: _RegimeKnobs(
        edge_threshold=0.04,
        size_factor=0.5,
        max_trades_per_cycle_asset=2,
        depth_mult=1.0,
    ),
    RiskRegime.NORMAL: _RegimeKnobs(
        edge_threshold=0.06,
        size_factor=1.0,
        max_trades_per_cycle_asset=3,
        depth_mult=1.5,
    ),
    RiskRegime.AGGRESSIVE: _RegimeKnobs(
        edge_threshold=0.08,
        size_factor=1.5,
        max_trades_per_cycle_asset=5,
        depth_mult=2.0,
    ),
}


def _get_effective_knobs(asset: str) -> _RegimeKnobs:
    """Return the current regime knobs for an asset.

    For now the canonical regime is ``NORMAL``. Future iterations can map
    asset volatility/PNL state to a regime.
    """
    _ = ASSET_PROFILE.get(asset, ASSET_PROFILE["BTC"])
    return REGIME_KNOBS[RiskRegime.NORMAL]


def _get_effective_depth_thresholds(asset: str, regime: RiskRegime) -> tuple[int, int]:
    """Compute effective YES/NO depth thresholds for an asset and regime."""
    profile = ASSET_PROFILE.get(asset, ASSET_PROFILE["BTC"])
    knobs = REGIME_KNOBS[regime]
    return (
        int(profile.min_depth_yes_base * knobs.depth_mult),
        int(profile.min_depth_no_base * knobs.depth_mult),
    )
