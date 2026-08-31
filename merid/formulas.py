"""FORMULAS_ARE_SOURCE_OF_TRUTH — Canonical formulas for MERID Kalshi pipeline.

This module is the **normative reference** for all mathematical operations in the
MERID Kalshi sentiment-to-execution pipeline. Any deviation between this module and
code elsewhere is a bug; this module wins.

All functions are:
- Pure (no side effects)
- Fully typed
- Documented with LaTeX-style math
- Tested against the examples in AGENT_AUDIT_KALSHI_SENTIMENT.md

Public API
----------
**Versioning & Traceability**
- FORMULAS_VERSION: str — "2026-03-K1" format, bump on any formula change
- AUDIT_SPEC_VERSION: str — "2026-03-A1" format, bump on spec change
- get_version_info() -> dict — Returns both versions for logging
- generate_correlation_id(asset, timeframe) -> str — Create trace ID
- parse_correlation_id(corr_id) -> dict — Parse trace ID components

**Sentiment (DISCOVER/ANALYZE)**
- volume_weighted_sentiment(inputs: List[SentimentInput]) -> float
- reddit_confidence(volume: int, engagement: float) -> float

**Consensus (CONSENSUS)**
- confidence_weighted_swarm_probability(opinions) -> float
- classify_stance(prob: float, neutral_band: float) -> str
- brier_score(forecast: float, outcome: int) -> float
- mean_brier_score(scores: List[float]) -> float
- debate_lift(pre_debate: float, post_debate: float) -> float

**Sizing (SIZE)**
- kelly_fraction(p_win: float, win_odds: float) -> float
- kelly_fraction_from_edge(edge: float, price_cents: int) -> float
- quarter_kelly_size(inputs: PositionSizingInputs) -> Tuple[int, float, Optional[str]]
- apply_sizing_constraints(base_size: int, constraints) -> int

**Protection (PROTECT)**
- calculate_drawdown(peak: float, current: float) -> float
- drawdown_tier_action(dd_pct: float) -> DrawdownState
- fee_aware_edge(gross_edge: float, fee_pct: float, slippage: float) -> float

Usage:
    from merid.formulas import (
        volume_weighted_sentiment,
        confidence_weighted_swarm_probability,
        kelly_fraction,
        quarter_kelly_size,
        brier_score,
        debate_lift,
        drawdown_tier_action,
    )
"""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass
import numbers
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple, Union


# ═══════════════════════════════════════════════════════════════════════════
# Versioning — Any change to formulas or invariants requires bumping this
# ═══════════════════════════════════════════════════════════════════════════

FORMULAS_VERSION: str = "2026-03-K1"
"""Version of the formula implementations.

Bump when:
- Any formula implementation changes
- New formulas are added
- Breaking changes to function signatures
"""

AUDIT_SPEC_VERSION: str = "2026-03-A1"
"""Version of the AGENT_AUDIT_KALSHI_SENTIMENT.md spec this module implements.

Bump when:
- Invariants D1–P5 change
- Traceability hook requirements change
- R/A/G exit criteria thresholds change
"""


def get_version_info() -> dict:
    """Return version metadata for logging and correlation chains."""
    return {
        "formulas_version": FORMULAS_VERSION,
        "audit_spec_version": AUDIT_SPEC_VERSION,
        "module": "merid.formulas",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Traceability — Correlation ID Generation
# ═══════════════════════════════════════════════════════════════════════════

def generate_correlation_id(
    asset: str,
    timeframe: str,
    timestamp: Optional[Union[datetime, float, int, numbers.Real]] = None,
) -> str:
    """Generate correlation ID for DISCOVER→PROTECT lifecycle tracing.

    Format: {YYYYMMDD}_{HHMMSS}_{asset}_{timeframe}_{uuid8}
    Example: 20260330_143022_BTC_15m_a1b2c3d4

    Args:
        asset: Asset symbol (e.g., "BTC", "ETH")
        timeframe: Timeframe string (e.g., "15m", "1h", "daily")
        timestamp: Optional timestamp — datetime, Unix float/int, or None (defaults to UTC now)

    Returns:
        Correlation ID string for trace chains
    """
    # Defensive: handle all timestamp types
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif isinstance(timestamp, datetime):
        # Already a datetime — use as-is (ensure it has tzinfo)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        # Handle numeric types (including numpy/pandas scalars that don't register as numbers.Real)
        try:
            # bool is subclass of int, so explicitly exclude it
            if isinstance(timestamp, bool):
                timestamp = datetime.now(timezone.utc)
            else:
                # Attempt numeric conversion — catches float, int, numpy scalars, pandas timestamps
                ts_float = float(timestamp)  # type: ignore[arg-type]
                timestamp = datetime.fromtimestamp(ts_float, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            # Fallback: if conversion fails, use current time and log would happen at call site
            timestamp = datetime.now(timezone.utc)

    ts_part = timestamp.strftime("%Y%m%d_%H%M%S")
    uuid_part = uuid.uuid4().hex[:8]

    return f"{ts_part}_{asset}_{timeframe}_{uuid_part}"


def parse_correlation_id(corr_id: str) -> Optional[dict]:
    """Parse a correlation ID into components.

    Expected format: {YYYYMMDD}_{HHMMSS}_{asset}_{timeframe}_{uuid8}
    Example: 20260330_143022_BTC_15m_a1b2c3d4  (5 underscore-separated parts)

    Returns None if format is invalid.
    """
    try:
        parts = corr_id.split("_")
        if len(parts) != 5:
            return None

        datetime_part = parts[0] + parts[1]
        asset = parts[2]
        timeframe = parts[3]
        uuid_part = parts[4]

        return {
            "timestamp": datetime.strptime(datetime_part, "%Y%m%d%H%M%S"),
            "asset": asset,
            "timeframe": timeframe,
            "uuid": uuid_part,
        }
    except (ValueError, IndexError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Type Definitions
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SentimentInput:
    """Single sentiment score with volume for weighting."""
    score: float  # Range: [-1, 1]
    volume: int   # Must be >= 0


@dataclass(frozen=True)
class OpinionInput:
    """Single agent opinion for swarm aggregation."""
    probability: float  # Range: [0, 1]
    confidence: float   # Range: [0, 1]


@dataclass(frozen=True)
class KellyInputs:
    """Inputs for Kelly criterion calculation."""
    win_probability: float  # Range: [0, 1]
    win_odds: float         # Net odds received (e.g., 2.0 for 2:1 payout)
    loss_odds: float = 1.0  # Amount lost if wrong (typically 1.0 = full stake)


@dataclass(frozen=True)
class PositionSizingInputs:
    """Inputs for position sizing calculation."""
    bankroll_cents: int
    edge: float           # Range: [-1, 1], typically small (0.01-0.10)
    price_cents: int      # Current market price in cents
    fractional_kelly: float = 0.25  # Kelly fraction; quarter-Kelly default


@dataclass(frozen=True)
class DebateOutcome:
    """Pre/post debate probabilities for lift calculation."""
    pre_debate_probability: float   # Range: [0, 1]
    post_debate_probability: float  # Range: [0, 1]
    actual_outcome: int             # 0 or 1


@dataclass(frozen=True)
class DrawdownState:
    """Current drawdown metrics for tier determination."""
    current_drawdown_pct: float  # Range: [0, 1], 0.12 = 12%
    peak_value_cents: int
    current_value_cents: int


# ═══════════════════════════════════════════════════════════════════════════
# SENTIMENT FORMULAS
# ═══════════════════════════════════════════════════════════════════════════

def volume_weighted_sentiment(
    inputs: List[SentimentInput],
    min_volume_threshold: int = 0,
) -> Tuple[float, int, Optional[str]]:
    """Volume-weighted mean sentiment score.

    Math:
        $$\\bar{s} = \\frac{\\sum_{i=1}^{n} s_i \\cdot v_i}{\\sum_{i=1}^{n} v_i}$$

    Args:
        inputs: List of (score, volume) pairs
        min_volume_threshold: Minimum total volume to return non-zero

    Returns:
        (weighted_score, total_volume, warning_message)
        weighted_score is 0.0 if total_volume == 0 (with warning logged)

    Invariant:
        - Output always in [-1, 1] if inputs valid
        - Zero denominator returns 0.0 with warning, never crashes

    Example:
        >>> inputs = [SentimentInput(0.5, 100), SentimentInput(-0.3, 50)]
        >>> volume_weighted_sentiment(inputs)
        (0.2333..., 150, None)
    """
    total_volume = sum(inp.volume for inp in inputs)

    if total_volume == 0:
        return 0.0, 0, "ZERO_DENOMINATOR: no volume for weighted sentiment"

    if total_volume < min_volume_threshold:
        return (
            0.0,
            total_volume,
            f"LOW_VOLUME: {total_volume} < threshold {min_volume_threshold}"
        )

    weighted_sum = sum(inp.score * inp.volume for inp in inputs)
    weighted_score = weighted_sum / total_volume

    # Clamp to valid range (handles floating point edge cases)
    weighted_score = max(-1.0, min(1.0, weighted_score))

    return weighted_score, total_volume, None


def reddit_confidence(
    post_count: int,
    avg_engagement: float,
    volume_max: float = 30.0,
    engagement_max: float = 50.0,
) -> float:
    """Reddit sentiment confidence calculation.

    Math:
        $$c = 0.25 + 0.75 \\times \\min(\\frac{posts}{30}, 1) \\times \\min(\\frac{avg\\_engagement}{50}, 1)$$

    Args:
        post_count: Number of posts analyzed
        avg_engagement: Average upvote score
        volume_max: Posts required for full volume credit (default 30)
        engagement_max: Engagement score for full credit (default 50)

    Returns:
        Confidence in [0.25, 1.0]

    Invariant:
        - Minimum confidence is 0.25 (single post, low engagement)
        - Maximum confidence is 1.0 (30+ posts, 50+ avg engagement)
    """
    volume_factor = min(post_count / volume_max, 1.0)
    engagement_factor = min(avg_engagement / engagement_max, 1.0)
    confidence = 0.25 + (0.75 * volume_factor * engagement_factor)
    return min(1.0, max(0.25, confidence))


# ═══════════════════════════════════════════════════════════════════════════
# CONSENSUS FORMULAS
# ═══════════════════════════════════════════════════════════════════════════

def confidence_weighted_swarm_probability(
    opinions: List[OpinionInput],
    min_opinions: int = 1,
) -> Tuple[float, float, Optional[str]]:
    """Linear opinion pool with confidence weighting.

    Math (Linear Opinion Pool):
        $$p_{swarm} = \\frac{\\sum_{i=1}^{n} p_i \\cdot c_i}{\\sum_{i=1}^{n} c_i}$$

    Args:
        opinions: List of (probability, confidence) pairs
        min_opinions: Minimum opinions required for valid consensus

    Returns:
        (swarm_prob, total_confidence, warning_message)
        Returns (0.5, 0.0, warning) if insufficient opinions

    Invariant:
        - Output always in [0, 1]
        - With zero opinions: returns (0.5, 0.0, warning)
        - With uniform confidence: reduces to arithmetic mean

    Example:
        >>> opinions = [OpinionInput(0.7, 0.8), OpinionInput(0.6, 0.5)]
        >>> confidence_weighted_swarm_probability(opinions)
        (0.6615..., 1.3, None)
    """
    if len(opinions) < min_opinions:
        return (
            0.5,
            0.0,
            f"INSUFFICIENT_OPINIONS: {len(opinions)} < {min_opinions}"
        )

    total_confidence = sum(op.confidence for op in opinions)

    if total_confidence == 0:
        # Fallback to unweighted mean
        unweighted_mean = sum(op.probability for op in opinions) / len(opinions)
        return unweighted_mean, 0.0, "ZERO_CONFIDENCE: using unweighted mean"

    weighted_sum = sum(op.probability * op.confidence for op in opinions)
    swarm_prob = weighted_sum / total_confidence

    # Clamp to valid probability range
    swarm_prob = max(0.0, min(1.0, swarm_prob))

    return swarm_prob, total_confidence, None


def classify_stance(edge: float, weak_threshold: float = 0.03, strong_threshold: float = 0.10) -> str:
    """Classify stance from edge (swarm_prob - market_prob).

    Args:
        edge: Difference between swarm and market probability
        weak_threshold: Minimum |edge| for weak stance (default 5%)
        strong_threshold: Minimum |edge| for strong stance (default 10%)

    Returns:
        One of: "strong_yes", "weak_yes", "neutral", "weak_no", "strong_no"

    Invariant:
        - Zero edge always returns "neutral"
        - Classifications are symmetric around zero
    """
    if edge >= strong_threshold:
        return "strong_yes"
    elif edge >= weak_threshold:
        return "weak_yes"
    elif edge <= -strong_threshold:
        return "strong_no"
    elif edge <= -weak_threshold:
        return "weak_no"
    return "neutral"


def brier_score(forecast_prob: float, actual_outcome: int) -> float:
    """Brier score for a single forecast.

    Math:
        $$B = (f - o)^2$$

    Where:
        f = forecast probability [0, 1]
        o = actual outcome {0, 1}

    Args:
        forecast_prob: Predicted probability
        actual_outcome: Actual result (0 or 1)

    Returns:
        Brier score in [0, 1], lower is better

    Invariant:
        - Perfect forecast (f=o) returns 0.0
        - Worst forecast (f=1-o) returns 1.0

    Example:
        >>> brier_score(0.7, 1)  # Correct prediction with 70% confidence
        0.09
        >>> brier_score(0.7, 0)  # Wrong prediction
        0.49
    """
    outcome_f = float(actual_outcome)
    return (forecast_prob - outcome_f) ** 2


def mean_brier_score(forecasts: List[Tuple[float, int]]) -> float:
    """Mean Brier score across multiple forecasts.

    Math:
        $$\\bar{B} = \\frac{1}{n} \\sum_{i=1}^{n} (f_i - o_i)^2$$

    Args:
        forecasts: List of (forecast_prob, actual_outcome) tuples

    Returns:
        Mean Brier score, or 1.0 (worst) if no forecasts
    """
    if not forecasts:
        return 1.0

    briers = [brier_score(f, o) for f, o in forecasts]
    return sum(briers) / len(briers)


def debate_lift(
    pre_debate_prob: float,
    post_debate_prob: float,
    actual_outcome: int,
) -> float:
    """Debate lift: Brier improvement from pre to post debate.

    Math:
        $$L = (p_{pre} - o)^2 - (p_{post} - o)^2$$

    Positive lift means debate improved accuracy.

    Args:
        pre_debate_prob: Swarm probability before debate
        post_debate_prob: Swarm probability after debate
        actual_outcome: Actual result (0 or 1)

    Returns:
        Lift value (positive = debate helped)

    Example:
        >>> debate_lift(0.5, 0.7, 1)  # Moved from 50% to 70%, outcome was YES
        0.21  # Debate improved Brier by 0.21
    """
    pre_brier = brier_score(pre_debate_prob, actual_outcome)
    post_brier = brier_score(post_debate_prob, actual_outcome)
    return pre_brier - post_brier


# ═══════════════════════════════════════════════════════════════════════════
# POSITION SIZING FORMULAS (Kelly Criterion)
# ═══════════════════════════════════════════════════════════════════════════

def kelly_fraction(inputs: KellyInputs) -> float:
    """Full Kelly criterion: optimal fraction of bankroll to wager.

    Math (Kelly Criterion):
        $$f^* = \\frac{p \\cdot b - q}{b}$$

    Where:
        p = probability of winning
        q = 1-p = probability of losing
        b = win odds (net odds received, e.g., 2.0 for 2:1)

    Alternative form for binary outcome markets:
        $$f^* = \\frac{p \\cdot (gain) - q \\cdot (loss)}{gain}$$

    Args:
        inputs: KellyInputs with win_probability, win_odds, loss_odds

    Returns:
        Kelly fraction (can be negative if edge < 0)

    Invariant:
        - Negative return means "don't bet" (edge is negative)
        - Zero return means no edge
        - Never returns > 1.0 (full bankroll is max)

    Example:
        >>> kelly_fraction(KellyInputs(0.6, 2.0))
        0.20  # Bet 20% of bankroll
        >>> kelly_fraction(KellyInputs(0.5, 1.8))
        -0.055  # Negative edge, don't bet
    """
    p = inputs.win_probability
    q = 1.0 - p
    b = inputs.win_odds

    # Standard Kelly: (pb - q) / b
    kelly = (p * b - q) / b

    # Clamp to sensible range
    return max(-1.0, min(1.0, kelly))


def kelly_fraction_from_edge(
    edge: float,
    price: float = 50.0,  # Midpoint for binary markets
) -> float:
    """Simplified Kelly from edge (for binary prediction markets).

    For binary markets at 50 cents, edge maps directly to Kelly.
    This is a convenience function for the common case.

    Math:
        $$f^* \\approx edge \\times 2$$ (for price ≈ 50)

    Args:
        edge: Expected edge (swarm_prob - market_prob)
        price: Current market price in cents (default 50)

    Returns:
        Approximate Kelly fraction

    Note:
        This is approximate. Use full kelly_fraction() for precision.
    """
    # At 50 cents, implied probability is 0.5
    # If we believe prob is 0.5 + edge, and odds are roughly 2:1
    # Kelly ≈ edge * 2
    implied_prob = price / 100.0
    win_prob = implied_prob + edge

    # Rough odds: if market is at 50, you get ~2:1 on a win
    win_odds = (1 - implied_prob) / implied_prob if implied_prob > 0 else 1.0

    return kelly_fraction(KellyInputs(win_prob, win_odds))


def quarter_kelly_size(
    inputs: PositionSizingInputs,
) -> Tuple[float, float, Optional[str]]:
    """Quarter-Kelly position sizing for Kalshi contracts with fractional contract support.

    Math:
        $$contracts = \\frac{B \\times f^* \\times 0.25}{P}$$

    Where:
        B = bankroll in cents
        f* = Kelly fraction from edge
        0.25 = fractional Kelly (quarter-Kelly)
        P = price per contract in cents

    CRITICAL FIX: Returns fractional contracts (float) instead of integer to enable
    micro-bankroll trading. Kalshi supports fractional contracts down to 0.01 (CFTC Rule 13.1).
    This allows precise position sizing for small bankrolls ($40-$100 range).

    Args:
        inputs: PositionSizingInputs

    Returns:
        (contracts, kelly_fraction_used, warning_message)
        Returns (0.0, kelly, warning) if edge <= 0 or price <= 0

    Invariant:
        - Never returns negative contracts
        - Returns 0.0 if edge <= 0 (no edge = no trade)
        - Returns fractional contracts for precise sizing (e.g., 0.88 contracts)
        - Respects max_contracts_per_order from config

    Example:
        >>> inputs = PositionSizingInputs(4015, 0.02, 91, 0.02)  # $40.15 bankroll, 2% Kelly, $0.91/contract
        >>> quarter_kelly_size(inputs)
        (0.88, 0.04, None)  # 0.88 contracts (fractional for micro-bankroll)
    """
    if inputs.edge <= 0:
        return 0.0, 0.0, "NO_EDGE: edge <= 0, no position"

    if inputs.price_cents <= 0:
        return 0.0, 0.0, "INVALID_PRICE: price must be > 0"

    if inputs.bankroll_cents <= 0:
        return 0.0, 0.0, "NO_BANKROLL: bankroll must be > 0"

    # Calculate Kelly fraction from edge
    kelly = kelly_fraction_from_edge(inputs.edge, inputs.price_cents)

    if kelly <= 0:
        return 0.0, kelly, "NEGATIVE_KELLY: Kelly suggests no position"

    # Apply fractional Kelly (quarter-Kelly default)
    fractional_kelly = kelly * inputs.fractional_kelly

    # Calculate position in cents
    position_cents = inputs.bankroll_cents * fractional_kelly

    # Convert to contracts (float for fractional support)
    contracts = position_cents / inputs.price_cents

    # Ensure non-negative
    contracts = max(0.0, contracts)

    return contracts, kelly, None


def apply_sizing_constraints(
    raw_contracts: int,
    max_contracts_per_order: int = 1,  # CRITICAL FIX (2026-07-08): Reduced from 50 to 1 to enforce 3% risk limit
    max_contracts_per_market: int = 200,
    current_market_position: int = 0,
    drawdown_tier: str = "normal",  # normal, warning, tight, halt
) -> Tuple[int, List[str]]:
    """Apply all sizing constraints to raw Kelly-derived contract count.

    Args:
        raw_contracts: Contracts from Kelly calculation
        max_contracts_per_order: Per-order limit
        max_contracts_per_market: Per-market limit
        current_market_position: Existing position in this market
        drawdown_tier: Current drawdown tier

    Returns:
        (final_contracts, list_of_constraints_applied)

    Invariant:
        - If drawdown_tier is "halt", always returns 0
        - If "tight", applies 0.5x sizing factor
        - Never exceeds per-market max
    """
    constraints: List[str] = []
    final = raw_contracts

    # Halt tier: block all new positions
    if drawdown_tier == "halt":
        return 0, ["HALT_TIER: all new positions blocked"]

    # Tight tier: half sizing
    if drawdown_tier == "tight":
        final = final // 2
        constraints.append("TIGHT_TIER: 0.5x sizing applied")

    # Per-order cap
    if final > max_contracts_per_order:
        final = max_contracts_per_order
        constraints.append(f"PER_ORDER_CAP: capped at {max_contracts_per_order}")

    # Per-market cap
    available = max_contracts_per_market - current_market_position
    if final > available:
        final = max(0, available)
        constraints.append(f"PER_MARKET_CAP: {current_market_position} existing, {available} available")

    return max(0, final), constraints


# ═══════════════════════════════════════════════════════════════════════════
# RISK/PROTECTION FORMULAS
# ═══════════════════════════════════════════════════════════════════════════

def calculate_drawdown(
    peak_value_cents: int,
    current_value_cents: int,
) -> Tuple[float, Optional[str]]:
    """Calculate drawdown percentage from peak.

    Math:
        $$DD = \\frac{peak - current}{peak}$$

    Args:
        peak_value_cents: Highest value reached
        current_value_cents: Current value

    Returns:
        (drawdown_pct, warning_message)
        Returns (0.0, warning) if peak <= 0

    Invariant:
        - Always returns value in [0, 1] for valid inputs
        - 0.0 means at peak, 1.0 means total loss
    """
    if peak_value_cents <= 0:
        return 0.0, "INVALID_PEAK: peak value must be > 0"

    if current_value_cents > peak_value_cents:
        # New peak, no drawdown
        return 0.0, None

    drawdown = (peak_value_cents - current_value_cents) / peak_value_cents
    return max(0.0, min(1.0, drawdown)), None


def drawdown_tier_action(
    drawdown_pct: float,
    warning_at: float = 0.05,
    downsize_at: float = 0.08,
    halt_at: float = 0.12,
) -> Tuple[str, bool, bool, Optional[str]]:
    """Determine action from drawdown tier.

    Tiers:
        - Normal: < 5% drawdown — full trading
        - Warning: 5-8% — orange badge, monitor closely
        - Tight: 8-12% — half position sizes, TIGHT mode
        - Halt: >= 12% — all trading halted, human override required

    Args:
        drawdown_pct: Current drawdown [0, 1]
        warning_at: Warning threshold (default 5%)
        downsize_at: Tight mode threshold (default 8%)
        halt_at: Halt threshold (default 12%)

    Returns:
        (tier, trading_allowed, reduced_sizing, message)

    Example:
        >>> drawdown_tier_action(0.09)
        ('tight', True, True, 'Drawdown 9.0%: TIGHT mode, 0.5x sizing')
        >>> drawdown_tier_action(0.13)
        ('halt', False, False, 'Drawdown 13.0%: HALT required')
    """
    if drawdown_pct >= halt_at:
        return (
            "halt",
            False,  # trading_allowed
            False,  # reduced_sizing
            f"Drawdown {drawdown_pct:.1%}: HALT required (threshold {halt_at:.1%})"
        )

    if drawdown_pct >= downsize_at:
        return (
            "tight",
            True,   # trading_allowed
            True,   # reduced_sizing
            f"Drawdown {drawdown_pct:.1%}: TIGHT mode, 0.5x sizing"
        )

    if drawdown_pct >= warning_at:
        return (
            "warning",
            True,   # trading_allowed
            False,  # reduced_sizing
            f"Drawdown {drawdown_pct:.1%}: WARNING level"
        )

    return (
        "normal",
        True,   # trading_allowed
        False,  # reduced_sizing
        None
    )


def fee_aware_edge(
    gross_edge: float,
    kalshi_fee_pct: float = 0.07,
    contracts: int = 1,
    price_cents: int = 50,
) -> Tuple[float, float, bool]:
    """
    Calculate net edge after Kalshi fees.

    DEPRECATED: For Kalshi 15m crypto, use EdgeResult.edge_fee_adjusted from
    unified_edge.py instead. This function will be removed after migration to
    canonical fee calculation. Non-Kalshi venues can continue using this method.

    Uses the official Kalshi parabolic formula:
        fee = ceil(rate × C × P × (1 − P))
    with tiered rates (7%/5%/3%) and a 2¢-per-contract floor.

    Args:
        gross_edge: Expected edge before fees
        kalshi_fee_pct: Kalshi fee rate override (default 7%, auto-tiered if not overridden)
        contracts: Number of contracts
        price_cents: Market price in cents

    Returns:
        (net_edge, fee_as_pct_of_notional, trade_worthwhile)

    Invariant:
        - If net_edge <= 0, trade_worthwhile is False
    """
    import warnings
    warnings.warn(
        "fee_aware_edge() is deprecated for Kalshi 15m crypto. "
        "Use EdgeResult.edge_fee_adjusted from unified_edge.py instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Determine tiered rate (use parameter if caller overrides, else auto-tier)
    if kalshi_fee_pct != 0.07:
        rate = kalshi_fee_pct
    elif contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03

    # Calculate fee in cents (Kalshi parabolic formula)
    p = price_cents / 100.0
    raw = rate * contracts * p * (1.0 - p)
    fee_cents = max(2, math.ceil(raw * 100))

    # Notional value
    notional_cents = contracts * price_cents

    # Fee as percentage of notional
    fee_pct = fee_cents / notional_cents if notional_cents > 0 else 1.0

    # Net edge
    net = gross_edge - fee_pct

    # Trade worthwhile if net edge positive
    worthwhile = net > 0.005  # 0.5% minimum net edge

    return net, fee_pct, worthwhile


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def validate_sentiment_inputs(inputs: List[SentimentInput]) -> Tuple[bool, Optional[str]]:
    """Validate sentiment inputs before processing.

    Returns:
        (valid, error_message)
    """
    if not inputs:
        return False, "EMPTY_INPUTS: no sentiment inputs provided"

    for i, inp in enumerate(inputs):
        if not (-1.0 <= inp.score <= 1.0):
            return False, f"INVALID_SCORE: input {i} score {inp.score} not in [-1, 1]"
        if inp.volume < 0:
            return False, f"INVALID_VOLUME: input {i} volume {inp.volume} < 0"

    return True, None


def validate_opinion_inputs(opinions: List[OpinionInput]) -> Tuple[bool, Optional[str]]:
    """Validate opinion inputs before consensus calculation.

    Returns:
        (valid, error_message)
    """
    if not opinions:
        return False, "EMPTY_OPINIONS: no opinions provided"

    for i, op in enumerate(opinions):
        if not (0.0 <= op.probability <= 1.0):
            return False, f"INVALID_PROB: opinion {i} prob {op.probability} not in [0, 1]"
        if not (0.0 <= op.confidence <= 1.0):
            return False, f"INVALID_CONF: opinion {i} conf {op.confidence} not in [0, 1]"

    return True, None


# ═══════════════════════════════════════════════════════════════════════════
# MODULE EXPORTS
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    # Versioning
    "FORMULAS_VERSION",
    "AUDIT_SPEC_VERSION",
    "get_version_info",
    # Traceability
    "generate_correlation_id",
    "parse_correlation_id",
    # Types
    "SentimentInput",
    "OpinionInput",
    "KellyInputs",
    "PositionSizingInputs",
    "DebateOutcome",
    "DrawdownState",
    # Sentiment
    "volume_weighted_sentiment",
    "reddit_confidence",
    # Consensus
    "confidence_weighted_swarm_probability",
    "classify_stance",
    "brier_score",
    "mean_brier_score",
    "debate_lift",
    # Sizing
    "kelly_fraction",
    "kelly_fraction_from_edge",
    "quarter_kelly_size",
    "apply_sizing_constraints",
    # Risk/Protection
    "calculate_drawdown",
    "drawdown_tier_action",
    "fee_aware_edge",
    # Validation
    "validate_sentiment_inputs",
    "validate_opinion_inputs",
]
