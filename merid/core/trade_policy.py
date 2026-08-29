"""
Coherent Trade Policy Utility

Centralizes trading policy decisions based on liquidity, spread, and volatility.
Used by both _select_markets() and candidate_optimizer to ensure consistent
gating across the stack.

This prevents some parts of the stack from treating "WIDE but deep" as tradable
while others silently block it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from utils.logger import get_logger

logger = get_logger("merid.core.trade_policy")


# Liquidity classification
LiquidityClass = Literal[
    "NO_STATE",      # No market state available
    "NO_BID_NO_ASK", # No liquidity
    "ONE_SIDED_BID_ONLY",  # Partial liquidity (bids only)
    "ONE_SIDED_ASK_ONLY",  # Partial liquidity (asks only)
    "TWO_SIDED",    # Full liquidity
]

# Spread quality classification
SpreadQuality = Literal[
    "GOOD",   # spread < 40c
    "WIDE",   # 40c <= spread < 100c
    "POOR",   # spread >= 100c
]

# Volatility regime
VolatilityRegime = Literal[
    "LOW",      # spread <= 2c
    "NORMAL",   # 2c < spread <= 5c
    "HIGH",     # 5c < spread <= 8c
    "EXTREME",  # spread > 8c
]

# Trade policy decision
TradePolicy = Literal[
    "BLOCKED",        # Do not trade
    "SIZE_LIMITED",  # Trade but with reduced size
    "ALLOWED",       # Trade normally
]

# Market phase based on time to expiry
MarketPhase = Literal[
    "WARMUP",  # >= 10 minutes to expiry - smaller sizes, cautious entry
    "ACTIVE",  # 2-10 minutes to expiry - normal trading
    "TAIL",    # < 2 minutes to expiry - no new positions, profit-taking only
]

# Order decision type
OrderDecision = Literal[
    "OPEN",      # Open new position
    "ADJUST",    # Adjust existing position (add/reduce)
    "CLOSE",     # Close existing position
    "SKIP",      # Skip this ticker
]


@dataclass
class TradePolicyResult:
    """Result of trade policy evaluation."""
    policy: TradePolicy
    reason_code: str
    description: str

    def __repr__(self) -> str:
        return f"TradePolicyResult(policy={self.policy}, reason={self.reason_code})"


@dataclass
class OrderDecisionResult:
    """Result of order decision based on phase, policy, and positions."""
    decision: OrderDecision
    reason: str
    phase: MarketPhase
    max_size_multiplier: float = 1.0  # Size multiplier based on phase

    def __repr__(self) -> str:
        return f"OrderDecisionResult(decision={self.decision}, phase={self.phase}, reason={self.reason})"


def classify_liquidity(
    has_bid: bool,
    has_ask: bool,
    depth_yes: int = 0,
    depth_no: int = 0,
) -> LiquidityClass:
    """
    Classify market liquidity based on bid/ask availability and depth.

    Note: NO_STATE should be handled upstream when no market state object exists.
    This function assumes a valid state object and classifies its liquidity.

    Args:
        has_bid: Whether bid exists
        has_ask: Whether ask exists
        depth_yes: Depth at bid
        depth_no: Depth at ask

    Returns:
        LiquidityClass classification
    """
    if not has_bid and not has_ask:
        return "NO_BID_NO_ASK"
    elif has_bid and not has_ask:
        return "ONE_SIDED_BID_ONLY"
    elif has_ask and not has_bid:
        return "ONE_SIDED_ASK_ONLY"
    else:
        return "TWO_SIDED"


def classify_spread(spread_cents: float) -> SpreadQuality:
    """
    Classify spread quality based on cents.
    
    Args:
        spread_cents: Spread in cents
    
    Returns:
        SpreadQuality classification
    """
    if spread_cents < 40:
        return "GOOD"
    elif spread_cents < 100:
        return "WIDE"
    else:
        return "POOR"


def classify_volatility(spread_cents: float) -> VolatilityRegime:
    """
    Classify volatility regime based on spread.
    
    Args:
        spread_cents: Spread in cents
    
    Returns:
        VolatilityRegime classification
    """
    if spread_cents <= 2:
        return "LOW"
    elif spread_cents <= 5:
        return "NORMAL"
    elif spread_cents <= 8:
        return "HIGH"
    else:
        return "EXTREME"


def evaluate_trade_policy(
    liquidity_class: LiquidityClass,
    spread_quality: SpreadQuality,
    volatility_regime: VolatilityRegime,
    depth_yes: int = 0,
    depth_no: int = 0,
    minutes_to_expiry: float = 0.0,
) -> TradePolicyResult:
    """
    Evaluate trade policy based on market conditions.
    
    This is the centralized policy engine that determines whether a market
    is tradable, size-limited, or blocked. Both _select_markets() and
    candidate_optimizer should use this to ensure consistent gating.
    
    Args:
        liquidity_class: Liquidity classification
        spread_quality: Spread quality classification
        volatility_regime: Volatility regime
        depth_yes: Depth at bid
        depth_no: Depth at ask
        minutes_to_expiry: Time to expiry in minutes
    
    Returns:
        TradePolicyResult with policy decision and reason code
    """
    # Hard blocks - no trading under these conditions
    if liquidity_class == "NO_STATE":
        return TradePolicyResult(
            policy="BLOCKED",
            reason_code="LIQUIDITY_NO_STATE",
            description="No market state available"
        )
    
    if liquidity_class == "NO_BID_NO_ASK":
        return TradePolicyResult(
            policy="BLOCKED",
            reason_code="LIQUIDITY_NO_BID_NO_ASK",
            description="No bid or ask available"
        )
    
    if spread_quality == "POOR":
        return TradePolicyResult(
            policy="BLOCKED",
            reason_code="SPREAD_POOR",
            description=f"Spread too wide ({spread_quality})"
        )
    
    # DESIGN CHANGE: Removed ultra-short expiry guard
    # Trade policy now uses MD health (event freshness) to determine tradeability
    # This allows trading the full 15-minute window including the tail
    # Phase-based behavior (warmup/active/tail) will be added separately
    
    # One-sided markets - size limit
    if liquidity_class in ["ONE_SIDED_BID_ONLY", "ONE_SIDED_ASK_ONLY"]:
        return TradePolicyResult(
            policy="SIZE_LIMITED",
            reason_code="LIQUIDITY_ONE_SIDED",
            description=f"One-sided liquidity ({liquidity_class})"
        )
    
    # Wide spread with shallow depth - size limit
    if spread_quality == "WIDE" and min(depth_yes, depth_no) < 10:
        return TradePolicyResult(
            policy="SIZE_LIMITED",
            reason_code="SPREAD_WIDE_SHALLOW",
            description=f"Wide spread with shallow depth (spread={spread_quality}, min_depth={min(depth_yes, depth_no)})"
        )
    
    # Extreme volatility - size limit
    if volatility_regime == "EXTREME":
        return TradePolicyResult(
            policy="SIZE_LIMITED",
            reason_code="VOLATILITY_EXTREME",
            description=f"Extreme volatility regime ({volatility_regime})"
        )
    
    # All checks passed - allow trading
    return TradePolicyResult(
        policy="ALLOWED",
        reason_code="OK",
        description="All policy checks passed"
    )


def compute_market_phase(minutes_to_expiry: float) -> MarketPhase:
    """
    Compute market phase based on time to expiry.

    Args:
        minutes_to_expiry: Time to expiry in minutes

    Returns:
        MarketPhase classification
    """
    if minutes_to_expiry >= 10:
        return "WARMUP"
    elif minutes_to_expiry >= 2:
        return "ACTIVE"
    else:
        return "TAIL"


def decide_orders_for_ticker(
    policy_result: TradePolicyResult,
    minutes_to_expiry: float,
    has_position: bool = False,
    position_side: Optional[Literal["YES", "NO"]] = None,
) -> OrderDecisionResult:
    """
    Decide order type based on trade policy, phase, and current positions.

    This is the strategy layer that determines what kinds of orders to send
    in each phase. It respects the trade policy (BLOCKED/SIZE_LIMITED/ALLOWED)
    and adds phase-specific behavior.

    Args:
        policy_result: Result from evaluate_trade_policy
        minutes_to_expiry: Time to expiry in minutes
        has_position: Whether we have an existing position
        position_side: Side of existing position (YES or NO)

    Returns:
        OrderDecision with decision type, reason, phase, and size multiplier
    """
    phase = compute_market_phase(minutes_to_expiry)

    # Hard block from trade policy - skip entirely
    if policy_result.policy == "BLOCKED":
        return OrderDecisionResult(
            decision="SKIP",
            reason=f"Trade policy blocked: {policy_result.reason_code}",
            phase=phase,
            max_size_multiplier=0.0,
        )

    # TAIL phase: no new positions, only profit-taking or risk reduction
    if phase == "TAIL":
        if not has_position:
            return OrderDecisionResult(
                decision="SKIP",
                reason="TAIL phase: no new positions allowed",
                phase=phase,
                max_size_multiplier=0.0,
            )
        else:
            # Has position - allow close or adjust for profit-taking
            return OrderDecisionResult(
                decision="CLOSE",
                reason="TAIL phase: profit-taking or risk reduction only",
                phase=phase,
                max_size_multiplier=0.5,  # Smaller sizes in tail
            )

    # WARMUP phase: smaller sizes, cautious entry
    if phase == "WARMUP":
        if policy_result.policy == "SIZE_LIMITED":
            return OrderDecisionResult(
                decision="OPEN",
                reason=f"WARMUP phase with size limit: {policy_result.reason_code}",
                phase=phase,
                max_size_multiplier=0.5,  # Even smaller in warmup
            )
        else:
            return OrderDecisionResult(
                decision="OPEN",
                reason="WARMUP phase: cautious entry with reduced size",
                phase=phase,
                max_size_multiplier=0.7,  # Reduced size in warmup
            )

    # ACTIVE phase: normal trading
    if phase == "ACTIVE":
        if policy_result.policy == "SIZE_LIMITED":
            return OrderDecisionResult(
                decision="ADJUST",
                reason=f"ACTIVE phase with size limit: {policy_result.reason_code}",
                phase=phase,
                max_size_multiplier=0.5,
            )
        else:
            return OrderDecisionResult(
                decision="OPEN",
                reason="ACTIVE phase: normal trading",
                phase=phase,
                max_size_multiplier=1.0,
            )

    # Fallback (should not reach here)
    return OrderDecisionResult(
        decision="SKIP",
        reason="Unknown phase or policy combination",
        phase=phase,
        max_size_multiplier=0.0,
    )


def log_policy_evaluation(
    ticker: str,
    liquidity_class: LiquidityClass,
    spread_quality: SpreadQuality,
    volatility_regime: VolatilityRegime,
    depth_yes: int,
    depth_no: int,
    minutes_to_expiry: float,
    policy_result: TradePolicyResult,
) -> None:
    """
    Log policy evaluation for debugging and audit.

    Args:
        ticker: Market ticker
        liquidity_class: Liquidity classification
        spread_quality: Spread quality classification
        volatility_regime: Volatility regime
        depth_yes: Depth at bid
        depth_no: Depth at ask
        minutes_to_expiry: Time to expiry
        policy_result: Result from evaluate_trade_policy
    """
    logger.info(
        "[TRADE-POLICY] ticker=%s liquidity=%s spread=%s volatility=%s "
        "depth_yes=%d depth_no=%d minutes_to_expiry=%.2f "
        "policy=%s reason=%s description=%s",
        ticker,
        liquidity_class,
        spread_quality,
        volatility_regime,
        depth_yes,
        depth_no,
        minutes_to_expiry,
        policy_result.policy,
        policy_result.reason_code,
        policy_result.description,
    )
