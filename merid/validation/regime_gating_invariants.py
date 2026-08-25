"""
Cross-Layer Invariants: Velocity, Volatility, and Volume Gating

This module enforces invariants for regime-based execution gating to prevent
trading when market conditions are unsuitable for the strategy.

Key Invariants:
- High volatility regime: either shrink position size or disable certain strategies
- Low volume or high spread regime: forbid large orders; enforce max notional or max participation
- Extreme velocity (fast moves): forbid contrarian entries or enforce only momentum entries with stricter edge
- Trade decisions must include regime tag
- No trade emitted when volatility_flag == "halt" or volume_flag == "illiquid"

Usage::

    from merid.validation.regime_gating_invariants import (
        RegimeGatingInvariantChecker,
        check_volatility_gating,
        check_volume_gating,
        check_velocity_gating,
        check_regime_tag_inclusion
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.validation.regime_gating_invariants")


class RegimeGatingViolation(str, Enum):
    """Types of regime gating violations."""
    VOLATILITY_HALT_TRADE = "volatility_halt_trade"
    VOLUME_ILLIQUID_TRADE = "volume_illiquid_trade"
    VELOCITY_EXTREME_CONTRARIAN = "velocity_extreme_contrainrian"
    POSITION_SIZE_NOT_SHRUNK = "position_size_not_shrunk"
    REGIME_TAG_MISSING = "regime_tag_missing"
    MAX_NOTIONAL_EXCEEDED = "max_notional_exceeded"
    SPREAD_TOO_WIDE = "spread_too_wide"


@dataclass
class RegimeGatingCheckResult:
    """Result of regime gating check."""
    is_valid: bool
    violation_type: Optional[RegimeGatingViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class RegimeGatingInvariantChecker:
    """Checks regime gating invariants for execution."""
    
    def __init__(
        self,
        max_volatility_threshold: float = 0.05,  # 5% max volatility
        min_volume_threshold: int = 10,  # Minimum volume at best bid/ask
        max_spread_cents: int = 30,  # Maximum spread in cents
        max_velocity_threshold: float = 0.002,  # Maximum velocity (0.2% per second)
        max_notional_usd: float = 1.00,  # $1 fixed exposure cap
    ):
        self.max_volatility_threshold = max_volatility_threshold
        self.min_volume_threshold = min_volume_threshold
        self.max_spread_cents = max_spread_cents
        self.max_velocity_threshold = max_velocity_threshold
        self.max_notional_usd = max_notional_usd
    
    def check_volatility_gating(
        self,
        volatility: float,
        volatility_flag: str,
        position_size: int,
        strategy_disabled: bool,
        trade_emitted: bool,
    ) -> RegimeGatingCheckResult:
        """INVARIANT: High volatility regime must shrink position size or disable strategy.
        
        If volatility exceeds threshold, either:
        - Position size must be reduced
        - Strategy must be disabled
        - No trade should be emitted
        """
        context = {
            "volatility": volatility,
            "volatility_flag": volatility_flag,
            "position_size": position_size,
            "strategy_disabled": strategy_disabled,
            "trade_emitted": trade_emitted,
            "max_volatility_threshold": self.max_volatility_threshold,
        }
        
        # Check if volatility is in halt regime
        if volatility_flag == "halt" and trade_emitted:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.VOLATILITY_HALT_TRADE,
                message=f"Volatility flag=HALT but trade emitted: volatility={volatility:.4f}",
                context=context,
            )
        
        # Check if volatility exceeds threshold
        if volatility > self.max_volatility_threshold:
            # High volatility - must have mitigation
            if not strategy_disabled and position_size >= 1 and trade_emitted:
                return RegimeGatingCheckResult(
                    is_valid=False,
                    violation_type=RegimeGatingViolation.POSITION_SIZE_NOT_SHRUNK,
                    message=f"Volatility={volatility:.4f} > threshold={self.max_volatility_threshold} but position_size={position_size} not shrunk and strategy not disabled",
                    context=context,
                )
        
        return RegimeGatingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Volatility gating consistent",
            context=context,
        )
    
    def check_volume_gating(
        self,
        bid_size: int,
        ask_size: int,
        volume_flag: str,
        notional_usd: float,
        trade_emitted: bool,
    ) -> RegimeGatingCheckResult:
        """INVARIANT: Low volume or high spread regime must forbid large orders.
        
        Enforces max notional or max participation when volume is low.
        """
        context = {
            "bid_size": bid_size,
            "ask_size": ask_size,
            "volume_flag": volume_flag,
            "notional_usd": notional_usd,
            "trade_emitted": trade_emitted,
            "min_volume_threshold": self.min_volume_threshold,
            "max_notional_usd": self.max_notional_usd,
        }
        
        # Check if volume is in illiquid regime
        if volume_flag == "illiquid" and trade_emitted:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.VOLUME_ILLIQUID_TRADE,
                message=f"Volume flag=ILLIQUID but trade emitted: bid_size={bid_size} ask_size={ask_size}",
                context=context,
            )
        
        # Check minimum volume requirements
        min_size = min(bid_size, ask_size)
        if min_size < self.min_volume_threshold and trade_emitted:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.VOLUME_ILLIQUID_TRADE,
                message=f"Volume below threshold: min_size={min_size} < {self.min_volume_threshold} but trade emitted",
                context=context,
            )
        
        # Check max notional
        if notional_usd > self.max_notional_usd and trade_emitted:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.MAX_NOTIONAL_EXCEEDED,
                message=f"Notional=${notional_usd:.2f} exceeds max=${self.max_notional_usd:.2f} but trade emitted",
                context=context,
            )
        
        return RegimeGatingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Volume gating consistent",
            context=context,
        )
    
    def check_velocity_gating(
        self,
        velocity: float,
        velocity_flag: str,
        entry_type: str,  # "momentum" or "contrarian"
        edge: float,
        trade_emitted: bool,
    ) -> RegimeGatingCheckResult:
        """INVARIANT: Extreme velocity must forbid contrarian entries or enforce stricter edge.
        
        When velocity is extreme:
        - Contrarian entries are forbidden
        - Momentum entries require stricter edge
        """
        context = {
            "velocity": velocity,
            "velocity_flag": velocity_flag,
            "entry_type": entry_type,
            "edge": edge,
            "trade_emitted": trade_emitted,
            "max_velocity_threshold": self.max_velocity_threshold,
        }
        
        # Check if velocity is extreme
        if abs(velocity) > self.max_velocity_threshold:
            # Extreme velocity - contrarian entries forbidden
            if entry_type == "contrarian" and trade_emitted:
                return RegimeGatingCheckResult(
                    is_valid=False,
                    violation_type=RegimeGatingViolation.VELOCITY_EXTREME_CONTRARIAN,
                    message=f"Velocity={velocity:.4f} > threshold={self.max_velocity_threshold} but contrarian entry emitted",
                    context=context,
                )
            
            # Momentum entries require stricter edge
            if entry_type == "momentum" and trade_emitted and edge < 0.02:
                return RegimeGatingCheckResult(
                    is_valid=False,
                    violation_type=RegimeGatingViolation.VELOCITY_EXTREME_CONTRARIAN,
                    message=f"Velocity={velocity:.4f} > threshold={self.max_velocity_threshold} but momentum entry with insufficient edge={edge:.4f}",
                    context=context,
                )
        
        return RegimeGatingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Velocity gating consistent",
            context=context,
        )
    
    def check_spread_gating(
        self,
        spread_cents: int,
        trade_emitted: bool,
    ) -> RegimeGatingCheckResult:
        """INVARIANT: Spread must not exceed maximum threshold for trading.
        
        Wide spreads indicate illiquidity and poor execution quality.
        """
        context = {
            "spread_cents": spread_cents,
            "trade_emitted": trade_emitted,
            "max_spread_cents": self.max_spread_cents,
        }
        
        if spread_cents > self.max_spread_cents and trade_emitted:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.SPREAD_TOO_WIDE,
                message=f"Spread={spread_cents}c > max={self.max_spread_cents}c but trade emitted",
                context=context,
            )
        
        return RegimeGatingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Spread gating consistent",
            context=context,
        )
    
    def check_regime_tag_inclusion(
        self,
        trade_decision: Dict[str, Any],
        regime_tag: Optional[str],
    ) -> RegimeGatingCheckResult:
        """INVARIANT: Trade decisions must include regime tag.
        
        Ensures regime information is propagated through the decision pipeline.
        """
        context = {
            "trade_decision_keys": list(trade_decision.keys()),
            "regime_tag": regime_tag,
        }
        
        if regime_tag is None:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.REGIME_TAG_MISSING,
                message="Trade decision missing regime tag",
                context=context,
            )
        
        if "regime_tag" not in trade_decision:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.REGIME_TAG_MISSING,
                message="Trade decision dict missing regime_tag field",
                context=context,
            )
        
        if trade_decision["regime_tag"] != regime_tag:
            return RegimeGatingCheckResult(
                is_valid=False,
                violation_type=RegimeGatingViolation.REGIME_TAG_MISSING,
                message=f"Trade decision regime_tag={trade_decision['regime_tag']} != expected={regime_tag}",
                context=context,
            )
        
        return RegimeGatingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Regime tag included in trade decision",
            context=context,
        )
    
    def check_all_invariants(
        self,
        volatility: float,
        volatility_flag: str,
        bid_size: int,
        ask_size: int,
        volume_flag: str,
        velocity: float,
        velocity_flag: str,
        entry_type: str,
        edge: float,
        spread_cents: int,
        position_size: int,
        notional_usd: float,
        strategy_disabled: bool,
        trade_emitted: bool,
        trade_decision: Dict[str, Any],
        regime_tag: Optional[str],
    ) -> List[RegimeGatingCheckResult]:
        """Run all regime gating invariants."""
        results = []
        
        # Check volatility gating
        result = self.check_volatility_gating(
            volatility, volatility_flag, position_size, strategy_disabled, trade_emitted
        )
        results.append(result)
        
        # Check volume gating
        result = self.check_volume_gating(
            bid_size, ask_size, volume_flag, notional_usd, trade_emitted
        )
        results.append(result)
        
        # Check velocity gating
        result = self.check_velocity_gating(
            velocity, velocity_flag, entry_type, edge, trade_emitted
        )
        results.append(result)
        
        # Check spread gating
        result = self.check_spread_gating(spread_cents, trade_emitted)
        results.append(result)
        
        # Check regime tag inclusion
        result = self.check_regime_tag_inclusion(trade_decision, regime_tag)
        results.append(result)
        
        return results


# Convenience functions for direct use

def check_volatility_gating(
    volatility: float,
    volatility_flag: str,
    position_size: int,
    strategy_disabled: bool,
    trade_emitted: bool,
    max_volatility_threshold: float = 0.05,
) -> RegimeGatingCheckResult:
    """Check volatility gating invariant."""
    checker = RegimeGatingInvariantChecker(max_volatility_threshold=max_volatility_threshold)
    return checker.check_volatility_gating(
        volatility, volatility_flag, position_size, strategy_disabled, trade_emitted
    )


def check_volume_gating(
    bid_size: int,
    ask_size: int,
    volume_flag: str,
    notional_usd: float,
    trade_emitted: bool,
    min_volume_threshold: int = 10,
    max_notional_usd: float = 1.00,
) -> RegimeGatingCheckResult:
    """Check volume gating invariant."""
    checker = RegimeGatingInvariantChecker(
        min_volume_threshold=min_volume_threshold,
        max_notional_usd=max_notional_usd,
    )
    return checker.check_volume_gating(
        bid_size, ask_size, volume_flag, notional_usd, trade_emitted
    )


def check_velocity_gating(
    velocity: float,
    velocity_flag: str,
    entry_type: str,
    edge: float,
    trade_emitted: bool,
    max_velocity_threshold: float = 0.002,
) -> RegimeGatingCheckResult:
    """Check velocity gating invariant."""
    checker = RegimeGatingInvariantChecker(max_velocity_threshold=max_velocity_threshold)
    return checker.check_velocity_gating(
        velocity, velocity_flag, entry_type, edge, trade_emitted
    )


def check_regime_tag_inclusion(
    trade_decision: Dict[str, Any],
    regime_tag: Optional[str],
) -> RegimeGatingCheckResult:
    """Check regime tag inclusion invariant."""
    checker = RegimeGatingInvariantChecker()
    return checker.check_regime_tag_inclusion(trade_decision, regime_tag)


# Synthetic test data generator for invariant testing

def generate_synthetic_regime_gating_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for regime gating invariants.
    
    Returns:
        List of test case dictionaries with controlled regime conditions.
    """
    test_cases = []
    
    # Valid cases
    test_cases.append({
        "volatility": 0.02,
        "volatility_flag": "normal",
        "bid_size": 50,
        "ask_size": 50,
        "volume_flag": "liquid",
        "velocity": 0.0005,
        "velocity_flag": "normal",
        "entry_type": "momentum",
        "edge": 0.05,
        "spread_cents": 5,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": False,
        "trade_emitted": True,
        "trade_decision": {"regime_tag": "normal"},
        "regime_tag": "normal",
        "expected_valid": True,
        "description": "Normal regime, all metrics healthy - valid",
    })
    
    test_cases.append({
        "volatility": 0.06,
        "volatility_flag": "high",
        "bid_size": 50,
        "ask_size": 50,
        "volume_flag": "liquid",
        "velocity": 0.0005,
        "velocity_flag": "normal",
        "entry_type": "momentum",
        "edge": 0.05,
        "spread_cents": 5,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": True,
        "trade_emitted": False,
        "trade_decision": {"regime_tag": "high_volatility"},
        "regime_tag": "high_volatility",
        "expected_valid": True,
        "description": "High volatility but strategy disabled - valid",
    })
    
    # Invalid cases (should trigger violations)
    test_cases.append({
        "volatility": 0.06,
        "volatility_flag": "halt",
        "bid_size": 50,
        "ask_size": 50,
        "volume_flag": "liquid",
        "velocity": 0.0005,
        "velocity_flag": "normal",
        "entry_type": "momentum",
        "edge": 0.05,
        "spread_cents": 5,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": False,
        "trade_emitted": True,
        "trade_decision": {"regime_tag": "halt"},
        "regime_tag": "halt",
        "expected_valid": False,
        "description": "Volatility halt but trade emitted - violation",
    })
    
    test_cases.append({
        "volatility": 0.02,
        "volatility_flag": "normal",
        "bid_size": 5,
        "ask_size": 5,
        "volume_flag": "illiquid",
        "velocity": 0.0005,
        "velocity_flag": "normal",
        "entry_type": "momentum",
        "edge": 0.05,
        "spread_cents": 5,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": False,
        "trade_emitted": True,
        "trade_decision": {"regime_tag": "illiquid"},
        "regime_tag": "illiquid",
        "expected_valid": False,
        "description": "Volume illiquid but trade emitted - violation",
    })
    
    test_cases.append({
        "volatility": 0.02,
        "volatility_flag": "normal",
        "bid_size": 50,
        "ask_size": 50,
        "volume_flag": "liquid",
        "velocity": 0.003,
        "velocity_flag": "extreme",
        "entry_type": "contrarian",
        "edge": 0.05,
        "spread_cents": 5,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": False,
        "trade_emitted": True,
        "trade_decision": {"regime_tag": "extreme_velocity"},
        "regime_tag": "extreme_velocity",
        "expected_valid": False,
        "description": "Extreme velocity with contrarian entry - violation",
    })
    
    test_cases.append({
        "volatility": 0.02,
        "volatility_flag": "normal",
        "bid_size": 50,
        "ask_size": 50,
        "volume_flag": "liquid",
        "velocity": 0.0005,
        "velocity_flag": "normal",
        "entry_type": "momentum",
        "edge": 0.05,
        "spread_cents": 35,
        "position_size": 1,
        "notional_usd": 0.50,
        "strategy_disabled": False,
        "trade_emitted": True,
        "trade_decision": {"regime_tag": "normal"},
        "regime_tag": "normal",
        "expected_valid": False,
        "description": "Spread too wide but trade emitted - violation",
    })
    
    return test_cases
