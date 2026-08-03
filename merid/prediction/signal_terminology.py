"""
Unified Signal Terminology and Data Structures for Binary Options Trading

This module provides canonical type-safe enums and data structures to eliminate
terminology inconsistencies across the codebase.

Key Concepts:
- Direction: Trend bias (bullish/bearish/neutral) - independent of contract side
- Momentum: Strength/conviction of price movement (multi-window velocity fusion)
- Velocity: Instantaneous rate of price change (% per second)
- Side: Which contract to trade (YES/NO) - Kalshi-specific
- Action: Order action (BUY/SELL) - execution-specific
- Strategy Mode: How velocity maps to side (trend_following vs mean_reversion)

Usage::

    from merid.prediction.signal_terminology import (
        Direction, Momentum, Velocity, Side, Action, StrategyMode,
        TradingSignal, SignalMetadata
    )

    # Create a unified trading signal
    signal = TradingSignal(
        direction=Direction.BULLISH,
        momentum=Momentum.STRONG,
        velocity=0.00015,  # 0.015% per second
        side=Side.YES,
        action=Action.BUY,
        strategy_mode=StrategyMode.TREND_FOLLOWING,
        metadata=SignalMetadata(...)
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional, Dict, Any


class Direction(str, Enum):
    """Trend direction - independent of contract side.
    
    This represents the overall market trend bias, not which contract to trade.
    Direction is determined by multi-timeframe analysis (EMA crossovers, ADX, etc.).
    
    In trend_following mode: BULLISH → favors YES, BEARISH → favors NO
    In mean_reversion mode: BULLISH → favors NO (expect reversion), BEARISH → favors YES
    
    CRITICAL FIX (2026-07-19): Added StrategyIntent for explicit event-level intent.
    Direction describes market trend; StrategyIntent describes our betting direction.
    """
    BULLISH = "bullish"  # Uptrend - price generally rising
    BEARISH = "bearish"  # Downtrend - price generally falling
    NEUTRAL = "neutral"  # Ranging/no clear trend


class StrategyIntent(str, Enum):
    """Strategy-level intent for event outcome - independent of contract side.
    
    This represents our betting intent on the event outcome, not which contract to trade.
    StrategyIntent is used to ensure net exposure matches our directional thesis.
    
    BULLISH_EVENT: We believe the event will occur (e.g., "up in 15m")
    - Net exposure must be +Yes (buy_yes or sell_no)
    - Never +No (buy_no or sell_yes)
    
    BEARISH_EVENT: We believe the event will NOT occur (e.g., "not up in 15m")
    - Net exposure must be +No (buy_no or sell_yes)
    - Never +Yes (buy_yes or sell_no)
    
    CRITICAL FIX (2026-07-19): Added to prevent side/price mapping bugs.
    All signal generation must express intent explicitly, then derive Yes/No side.
    """
    BULLISH_EVENT = "bullish_event"  # Bet on event occurring (net +Yes exposure)
    BEARISH_EVENT = "bearish_event"  # Bet against event occurring (net +No exposure)
    NEUTRAL = "neutral"  # No directional bias


class Momentum(str, Enum):
    """Momentum strength/conviction - multi-window velocity fusion.
    
    Momentum is derived from weighted fusion of multiple velocity windows
    (10s, 30s, 60s) and represents the conviction/strength of price movement.
    
    Unlike velocity (instantaneous), momentum considers price behavior over
    multiple timeframes and is less susceptible to noise.
    """
    NONE = "none"        # No conviction - velocity below threshold
    WEAK = "weak"        # Low conviction - velocity just above threshold
    MODERATE = "moderate"  # Medium conviction - velocity 1.5-2x threshold
    STRONG = "strong"    # High conviction - velocity 2-3x threshold
    EXTREME = "extreme"  # Very high conviction - velocity >3x threshold


class Velocity(float):
    """Instantaneous rate of price change (% per second).
    
    Velocity is the raw metric from spot price feeds, measuring the
    instantaneous rate of change. Positive = price rising, negative = falling.
    
    Velocity is used for:
    - Signal generation (velocity threshold crossing)
    - Momentum calculation (multi-window fusion)
    - Regime detection (volatility estimation)
    
    Note: Velocity alone does not determine side - strategy_mode determines
    how velocity maps to YES/NO side selection.
    """
    def __new__(cls, value: float):
        return float.__new__(cls, value)
    
    @property
    def magnitude(self) -> float:
        """Absolute value of velocity (conviction strength)."""
        return abs(self)
    
    @property
    def sign(self) -> int:
        """Sign of velocity: 1 for positive, -1 for negative, 0 for zero."""
        return 1 if self > 0 else (-1 if self < 0 else 0)


class Side(str, Enum):
    """Kalshi contract side - which contract to trade.
    
    This is the canonical enum for Kalshi market sides, providing type safety
    and eliminating stringly-typed "yes"/"no" inconsistencies.
    
    Side is determined by:
    - Velocity direction (positive/negative)
    - Strategy mode (trend_following vs mean_reversion)
    - Strike price relative to spot (for directional markets)
    """
    YES = "yes"
    NO = "no"
    
    @classmethod
    def from_velocity_and_mode(
        cls, 
        velocity: float, 
        strategy_mode: str
    ) -> "Side":
        """Determine side from velocity and strategy mode.
        
        Args:
            velocity: Instantaneous velocity (% per second)
            strategy_mode: "trend_following" or "mean_reversion"
            
        Returns:
            Side.YES or Side.NO based on velocity and strategy mode
            
        Raises:
            ValueError: If strategy_mode is not recognized
        """
        if strategy_mode == "trend_following":
            # Trend following: positive velocity → YES, negative → NO
            return cls.YES if velocity > 0 else cls.NO
        elif strategy_mode == "mean_reversion":
            # Mean reversion: positive velocity → NO (expect reversion down)
            #                  negative velocity → YES (expect reversion up)
            return cls.NO if velocity > 0 else cls.YES
        else:
            raise ValueError(f"Unknown strategy_mode: {strategy_mode}")
    
    def opposite(self) -> "Side":
        """Return the opposite side."""
        return Side.NO if self == Side.YES else Side.YES


class Action(str, Enum):
    """Order action - execution-specific.
    
    Action is independent of side - you can BUY YES, SELL YES, BUY NO, SELL NO.
    The combination of side + action determines the full order type.
    """
    BUY = "buy"
    SELL = "sell"
    
    @classmethod
    def from_position_state(cls, current_side: Optional[Side], target_side: Side) -> "Action":
        """Determine action based on current position and target side.
        
        Args:
            current_side: Current position side (None if no position)
            target_side: Desired side (YES or NO)
            
        Returns:
            Action.BUY if entering new position, Action.SELL if exiting
        """
        if current_side is None:
            return cls.BUY  # Entering new position
        elif current_side == target_side:
            return cls.BUY  # Adding to existing position
        else:
            return cls.SELL  # Exiting/closing position


class StrategyMode(str, Enum):
    """Strategy mode - how velocity maps to side selection.
    
    This is a first-class parameter that must be explicitly specified
    when generating signals to avoid signal inversion bugs.
    """
    TREND_FOLLOWING = "trend_following"  # Positive velocity → YES, negative → NO
    MEAN_REVERSION = "mean_reversion"    # Positive velocity → NO, negative → YES (inverted)
    
    @classmethod
    def from_regime(cls, regime: str, confidence: float) -> "StrategyMode":
        """Determine strategy mode from regime detection.
        
        Args:
            regime: Regime type (e.g., "BULL", "BEAR", "CHOPPY")
            confidence: Regime detection confidence (0.0-1.0)
            
        Returns:
            StrategyMode based on regime and confidence
            
        Note:
            Mean reversion is only used for CHOPPY regime with high confidence (>0.7)
            to avoid signal inversion from uncertain regime detection.
        """
        if regime == "CHOPPY" and confidence > 0.7:
            return cls.MEAN_REVERSION
        else:
            return cls.TREND_FOLLOWING


@dataclass
class SignalMetadata:
    """Metadata about signal generation for audit and debugging."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    asset: str = ""
    velocity_threshold: float = 0.0
    velocity_windows: list = field(default_factory=list)
    momentum_weights: list = field(default_factory=list)
    regime: str = ""
    regime_confidence: float = 0.0
    indicators_used: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "asset": self.asset,
            "velocity_threshold": self.velocity_threshold,
            "velocity_windows": self.velocity_windows,
            "momentum_weights": self.momentum_weights,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "indicators_used": self.indicators_used,
            "rationale": self.rationale,
        }


@dataclass
class TradingSignal:
    """Unified trading signal data structure.
    
    This is the canonical signal format that should be used throughout
    the codebase to eliminate terminology inconsistencies.
    
    Attributes:
        direction: Trend bias (bullish/bearish/neutral)
        momentum: Conviction strength (none/weak/moderate/strong/extreme)
        velocity: Instantaneous rate of change (% per second)
        side: Which contract to trade (YES/NO)
        action: Order action (BUY/SELL)
        strategy_mode: How velocity mapped to side (trend_following/mean_reversion)
        confidence: Signal confidence (0.0-1.0)
        edge_pct: Expected edge in percentage points
        metadata: Signal generation metadata
    """
    direction: Direction
    momentum: Momentum
    velocity: Velocity
    side: Side
    action: Action
    strategy_mode: StrategyMode
    confidence: float = 0.0
    edge_pct: float = 0.0
    metadata: Optional[SignalMetadata] = None
    
    def to_kalshi_format(self) -> str:
        """Convert to Kalshi order format (BUY_YES, SELL_YES, BUY_NO, SELL_NO).
        
        Returns:
            Kalshi-formatted side+action string
        """
        if self.side == Side.YES and self.action == Action.BUY:
            return "BUY_YES"
        elif self.side == Side.YES and self.action == Action.SELL:
            return "SELL_YES"
        elif self.side == Side.NO and self.action == Action.BUY:
            return "BUY_NO"
        elif self.side == Side.NO and self.action == Action.SELL:
            return "SELL_NO"
        else:
            raise ValueError(f"Invalid side/action combination: {self.side}/{self.action}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "direction": self.direction.value,
            "momentum": self.momentum.value,
            "velocity": float(self.velocity),
            "side": self.side.value,
            "action": self.action.value,
            "strategy_mode": self.strategy_mode.value,
            "confidence": self.confidence,
            "edge_pct": self.edge_pct,
            "kalshi_format": self.to_kalshi_format(),
            "metadata": self.metadata.to_dict() if self.metadata else None,
        }
    
    def validate(self) -> bool:
        """Validate signal consistency.
        
        Returns:
            True if signal is internally consistent
            
        Raises:
            ValueError: If signal has inconsistencies
        """
        # Check velocity-side-mode consistency
        expected_side = Side.from_velocity_and_mode(self.velocity, self.strategy_mode.value)
        if self.side != expected_side:
            raise ValueError(
                f"Side inconsistency: velocity={self.velocity}, "
                f"strategy_mode={self.strategy_mode}, "
                f"expected_side={expected_side}, actual_side={self.side}"
            )
        
        # Check confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")
        
        # Check momentum-velocity consistency
        if self.momentum == Momentum.NONE and abs(self.velocity) > 0:
            raise ValueError(
                f"Momentum inconsistency: momentum=NONE but velocity={self.velocity}"
            )
        
        return True


# Type aliases for common patterns
DirectionLiteral = Literal["bullish", "bearish", "neutral"]
MomentumLiteral = Literal["none", "weak", "moderate", "strong", "extreme"]
SideLiteral = Literal["yes", "no"]
ActionLiteral = Literal["buy", "sell"]
StrategyModeLiteral = Literal["trend_following", "mean_reversion"]


def normalize_direction(value: str) -> str:
    """Normalize any direction representation to canonical lowercase string."""
    return Direction.from_string(value).value if hasattr(Direction, 'from_string') else value.lower()


def normalize_side(value: str) -> str:
    """Normalize any side representation to canonical lowercase string."""
    return Side.from_string(value).value if hasattr(Side, 'from_string') else value.lower()


def normalize_action(value: str) -> str:
    """Normalize any action representation to canonical lowercase string."""
    return Action.from_string(value).value if hasattr(Action, 'from_string') else value.lower()
