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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple

from merid.risk.probability.tail_calibrator import load_tail_calibrator


# Minimum posterior for a regime classification to be usable.
MIN_REGIME_POSTERIOR = Decimal(os.environ.get("MERID_MIN_REGIME_POSTERIOR", "0.5"))

# Minimum model probability for a side to be considered "believed" by the
# decision engine.  Lowering this below 0.5 allows cost-basis (positive-EV)
# trades on the less-likely side; raising it makes the engine more
# directional.  Default 0.5 preserves the existing release-gate invariants.
TRADE_DECISION_MIN_P_SELECTED = float(os.environ.get("MERID_TRADE_DECISION_MIN_P_SELECTED", "0.5"))

# Minimum net edge (as a fraction of notional) for a side to be selected.
# Can be lowered to loosen the edge filter, e.g. for cost-basis or momentum
# strategies, without changing the call-sites.
TRADE_DECISION_MIN_REQUIRED_EDGE = float(os.environ.get("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.03"))

# Hard entry-price floor for the held side.  Contracts with a held-side price
# below this (in cents) are rejected because the 7-day data showed 0/16 wins in
# the 0-19c tail.  Override with MERID_MIN_HELD_PRICE_CENTS to raise/lower.
MERID_MIN_HELD_PRICE_CENTS = float(os.environ.get("MERID_MIN_HELD_PRICE_CENTS", "20"))

# Tail calibration applies the isotonic correction from
# data/probability_tail_calibration.json (produced by scripts/calibrate_tail_probability.py).
# It caps model probability at historical actual_win_rate + buffer.
MERID_TAIL_CALIBRATION_ENABLED = os.environ.get("MERID_TAIL_CALIBRATION_ENABLED", "1").lower() in ("1", "true", "yes")
MERID_TAIL_CALIBRATION_BUFFER = float(os.environ.get("MERID_TAIL_CALIBRATION_BUFFER", "0.05"))
MERID_TAIL_CALIBRATION_PRICE_FLOOR = float(os.environ.get("MERID_TAIL_CALIBRATION_PRICE_FLOOR", "0.30"))

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
      3. The selected side's calibrated probability is > 0.5.
      4. Its net edge exceeds ``min_required_edge``.
      5. Confidence is valid (produced by the uncertainty engine, not a default).
    """
    now = datetime.now(timezone.utc)
    _data_state = _resolve_data_state(data_state=data_state, data_quality=data_quality)
    _regime_label = _resolve_regime_label(regime_label=regime_label, regime=regime)
    _regime_probability = _resolve_regime_probability(
        regime_probability=regime_probability, regime_label=_regime_label
    )

    def _no_trade(reason: str) -> TradeDecision:
        return TradeDecision(
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
        )

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

    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    if t_years <= 0:
        t_years = 1e-8

    log_moneyness = math.log(spot_price / strike_price) if strike_price > 0 else 0.0
    sigma = max(annualized_vol, 1e-6)
    z = log_moneyness / (sigma * math.sqrt(t_years))
    p_yes_raw = _normal_cdf(z)
    p_yes_raw = max(0.0, min(1.0, p_yes_raw))

    p_yes_calibrated = p_yes_raw
    if p_yes_model is not None and math.isfinite(p_yes_model):
        p_yes_calibrated = max(0.0, min(1.0, p_yes_model))
    # P0 FIX: Clamp to Kalshi venue-invariant [0.05, 0.95] so the downstream
    # order router does not reject high-confidence signals as invalid_model_prob.
    # This caps tail-risk overconfidence while preserving positive-EV trades.
    p_yes_calibrated = max(0.05, min(0.95, p_yes_calibrated))
    p_no_calibrated = 1.0 - p_yes_calibrated

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

    # Tail calibration: use the 7-day isotonic calibration to cap model
    # probability at actual_win_rate + buffer for the held-side price.  This
    # prevents the model from overestimating cheap-tail contracts where the
    # observed win rate was far below the market-implied probability.
    # The cap is applied only when the model actually believes the cheap side
    # (p_selected > 0.5), so it does not disturb well-calibrated 30-59c trades.
    if MERID_TAIL_CALIBRATION_ENABLED:
        tail_calibrator = load_tail_calibrator()
        if tail_calibrator is not None:
            if p_yes_calibrated > 0.5 and yes_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR:
                p_yes_calibrated = tail_calibrator.cap_p_yes(
                    p_yes_calibrated, yes_entry
                )
                p_no_calibrated = 1.0 - p_yes_calibrated
            if p_no_calibrated > 0.5 and no_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR:
                p_no_calibrated = tail_calibrator.cap_p_no(
                    p_no_calibrated, no_entry
                )
                p_yes_calibrated = 1.0 - p_no_calibrated

    fee = fee_per_contract_cents / 100.0
    expected_exit_cost_yes = fee
    expected_exit_cost_no = fee

    model_risk_reserve = _compute_model_risk_reserve(
        model_uncertainty, data_quality, regime, seconds_to_expiry
    )

    yes_breakdown = compute_edge(
        p_yes=p_yes_calibrated,
        selected_side="yes",
        entry_price=yes_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_yes,
        model_risk_reserve=model_risk_reserve,
    )
    no_breakdown = compute_edge(
        p_yes=p_yes_calibrated,
        selected_side="no",
        entry_price=no_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_no,
        model_risk_reserve=model_risk_reserve,
    )

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
    # A side qualifies only when its model probability is > 0.5 (no cost-basis
    # trading) and its net edge clears the threshold.  Ties are no-trade.
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

    yes_qualifies = (
        yes_breakdown.net_edge >= min_required_edge
        and yes_breakdown.p_selected > TRADE_DECISION_MIN_P_SELECTED
    )
    no_qualifies = (
        no_breakdown.net_edge >= min_required_edge
        and no_breakdown.p_selected > TRADE_DECISION_MIN_P_SELECTED
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
        elif best_net_edge < min_required_edge:
            if best_side == "yes":
                no_trade_reason = "yes_edge_below_threshold"
            else:
                no_trade_reason = "no_edge_below_threshold"
        else:
            # Edge is sufficient but the model does not believe the side is > 50%.
            no_trade_reason = f"cost_basis_override_{best_side}"

    if selected_outcome is not None:
        selected_action = "buy"
        approved_size_cc = Decimal("200")  # default 2 contracts; risk may resize down based on $1 cap and price
        p_selected = Decimal(str(edge_breakdown.p_selected))
        p_opposite = Decimal(str(edge_breakdown.p_opposite))
        selected_outcome_price = Decimal(str(edge_breakdown.executable_entry_price))
        gross_edge = Decimal(str(edge_breakdown.gross_edge))
        net_edge = Decimal(str(edge_breakdown.net_edge))

        # Held-side entry price floor.  The 7-day data showed 0/16 wins in the
        # 0-19c tail; block entries below ~20c until the model is recalibrated.
        min_held_price_dollars = MERID_MIN_HELD_PRICE_CENTS / 100.0
        held_price = float(selected_outcome_price)
        if held_price < min_held_price_dollars:
            selected_outcome = None
            selected_action = None
            approved_size_cc = Decimal("0")
            p_selected = None
            p_opposite = None
            selected_outcome_price = None
            gross_edge = None
            net_edge = None
            edge_breakdown = None
            no_trade_reason = f"held_entry_price_below_floor:{held_price:.2f}"

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

    return TradeDecision(
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
        indicators=indicators or {},
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
            yes_score if yes_score is not None
            else (p_yes_model if p_yes_model is not None else p_yes_calibrated)
        )),
        no_score=Decimal(str(
            no_score if no_score is not None
            else (p_no_model if p_no_model is not None else p_no_calibrated)
        )),
        yes_vote_count=yes_vote_count,
        no_vote_count=no_vote_count,
        selected_side_pre_edge=selected_side_pre_edge,
        selection_reason=selection_reason,
        yes_net_edge=Decimal(str(yes_breakdown.net_edge)),
        no_net_edge=Decimal(str(no_breakdown.net_edge)),
        best_side=best_side,
        best_net_edge=Decimal(str(best_net_edge)) if best_net_edge is not None else None,
        edge_threshold=Decimal(str(min_required_edge)),
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
        min_required_edge=Decimal(str(min_required_edge)),
        approved_size_cc=approved_size_cc,
        policy_version=policy_version,
    )
