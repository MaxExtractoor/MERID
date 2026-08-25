"""
Live Error Taxonomy Logging

This module provides a structured error taxonomy for logging trade skips and
invariant violations with standardized reason codes.

Error Codes:
- EDGE_TOO_SMALL: Edge below threshold for trading
- VOL_TOO_HIGH: Volatility exceeds allowed range
- CONFIG_MISMATCH: Configuration mismatch between components
- VOLUME_ILLIQUID: Volume below minimum threshold
- SPREAD_TOO_WIDE: Spread exceeds maximum allowed
- VELOCITY_EXTREME: Velocity exceeds allowed range
- POSITION_SIZE_MISMATCH: Position size calculation error
- PNL_CALCULATION_MISMATCH: PnL calculation inconsistency
- ORPHAN_ORDER: Order without corresponding episode
- ORPHAN_FILL: Fill without corresponding order
- NEGATIVE_BALANCE: Account balance went negative
- LEVERAGE_EXCEEDED: Leverage exceeded risk limits
- ILLEGAL_SEMANTIC_COMBINATION: Invalid semantic combination in mapping
- DEEP_OTM_WITHOUT_EXTREME_EDGE: Deep OTM trade without sufficient edge
- SIDE_PROBABILITY_MISMATCH: Side and probability mismatch
- CONFIDENCE_NOT_MONOTONIC: Confidence not monotonic with edge/probability

Usage::

    from merid.validation.error_taxonomy import (
        log_trade_skip,
        log_invariant_violation,
        ErrorTaxonomy,
        TradeSkipReason,
        InvariantViolationReason
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime, timedelta
from utils.logger import get_logger

logger = get_logger("merid.validation.error_taxonomy")


class TradeSkipReason(str, Enum):
    """Standardized reason codes for trade skips."""
    EDGE_TOO_SMALL = "EDGE_TOO_SMALL"
    VOL_TOO_HIGH = "VOL_TOO_HIGH"
    CONFIG_MISMATCH = "CONFIG_MISMATCH"
    VOLUME_ILLIQUID = "VOLUME_ILLIQUID"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    VELOCITY_EXTREME = "VELOCITY_EXTREME"
    POSITION_LIMIT_REACHED = "POSITION_LIMIT_REACHED"
    RISK_CAP_EXCEEDED = "RISK_CAP_EXCEEDED"
    MARKET_CLOSED = "MARKET_CLOSED"
    INFRASTRUCTURE_HALT = "INFRASTRUCTURE_HALT"
    UNKNOWN = "UNKNOWN"


class InvariantViolationReason(str, Enum):
    """Standardized reason codes for invariant violations."""
    EDGE_SIGN_MISMATCH = "EDGE_SIGN_MISMATCH"
    SIDE_PROBABILITY_MISMATCH = "SIDE_PROBABILITY_MISMATCH"
    CONFIDENCE_NOT_MONOTONIC = "CONFIDENCE_NOT_MONOTONIC"
    LOW_EDGE_HIGH_CONFIDENCE = "LOW_EDGE_HIGH_CONFIDENCE"
    INVALID_PROBABILITY_RANGE = "INVALID_PROBABILITY_RANGE"
    INVALID_EDGE_RANGE = "INVALID_EDGE_RANGE"
    VOLATILITY_HALT_TRADE = "VOLATILITY_HALT_TRADE"
    VOLUME_ILLIQUID_TRADE = "VOLUME_ILLIQUID_TRADE"
    VELOCITY_EXTREME_CONTRARIAN = "VELOCITY_EXTREME_CONTRARIAN"
    POSITION_SIZE_NOT_SHRUNK = "POSITION_SIZE_NOT_SHRUNK"
    MAX_NOTIONAL_EXCEEDED = "MAX_NOTIONAL_EXCEEDED"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    REGIME_TAG_MISSING = "REGIME_TAG_MISSING"
    DISTANCE_EXCEEDED = "DISTANCE_EXCEEDED"
    DEEP_OTM_WITHOUT_EXTREME_EDGE = "DEEP_OTM_WITHOUT_EXTREME_EDGE"
    CONTRACT_SELECTION_MISMATCH = "CONTRACT_SELECTION_MISMATCH"
    INVALID_SPOT_PRICE = "INVALID_SPOT_PRICE"
    INVALID_STRIKE_PRICE = "INVALID_STRIKE_PRICE"
    ILLEGAL_SEMANTIC_COMBINATION = "ILLEGAL_SEMANTIC_COMBINATION"
    THESIS_SIDE_MISMATCH = "THESIS_SIDE_MISMATCH"
    CONTRACT_TYPE_MISMATCH = "CONTRACT_TYPE_MISMATCH"
    ORDER_ACTION_MISMATCH = "ORDER_ACTION_MISMATCH"
    ENTRY_EXIT_INVERSION = "ENTRY_EXIT_INVERSION"
    POSITION_SIZE_MISMATCH = "POSITION_SIZE_MISMATCH"
    PNL_CALCULATION_MISMATCH = "PNL_CALCULATION_MISMATCH"
    ORPHAN_ORDER = "ORPHAN_ORDER"
    ORPHAN_FILL = "ORPHAN_FILL"
    PNL_WITHOUT_POSITION = "PNL_WITHOUT_POSITION"
    NEGATIVE_BALANCE = "NEGATIVE_BALANCE"
    LEVERAGE_EXCEEDED = "LEVERAGE_EXCEEDED"
    EPISODE_ID_MISSING = "EPISODE_ID_MISSING"
    EDGE_ATTRIBUTION_MISMATCH = "EDGE_ATTRIBUTION_MISMATCH"
    MISSING_TRADE = "MISSING_TRADE"
    PHANTOM_TRADE = "PHANTOM_TRADE"
    STALE_CONFIG = "STALE_CONFIG"
    BROKEN_RISK_CONTROL = "BROKEN_RISK_CONTROL"
    FILTER_MISMATCH = "FILTER_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    RISK_LIMIT_MISMATCH = "RISK_LIMIT_MISMATCH"
    PRICE_RANGE_MISMATCH = "PRICE_RANGE_MISMATCH"
    ASSET_UNIVERSE_MISMATCH = "ASSET_UNIVERSE_MISMATCH"
    EXPOSURE_CAP_MISMATCH = "EXPOSURE_CAP_MISMATCH"
    HARDCODED_VALUE_MISMATCH = "HARDCODED_VALUE_MISMATCH"


@dataclass
class TradeSkipEvent:
    """Record of a trade skip event."""
    timestamp: datetime
    asset: str
    ticker: str
    reason: TradeSkipReason
    edge: Optional[float] = None
    volatility: Optional[float] = None
    volume: Optional[int] = None
    spread_cents: Optional[int] = None
    velocity: Optional[float] = None
    context: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "asset": self.asset,
            "ticker": self.ticker,
            "reason": self.reason.value,
            "edge": self.edge,
            "volatility": self.volatility,
            "volume": self.volume,
            "spread_cents": self.spread_cents,
            "velocity": self.velocity,
            "context": self.context,
        }


@dataclass
class InvariantViolationEvent:
    """Record of an invariant violation event."""
    timestamp: datetime
    invariant_name: str
    reason: InvariantViolationReason
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    message: str
    context: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "invariant_name": self.invariant_name,
            "reason": self.reason.value,
            "severity": self.severity,
            "message": self.message,
            "context": self.context,
        }


class ErrorTaxonomy:
    """Centralized error taxonomy logging for MERID."""
    
    def __init__(self):
        self.trade_skips: List[TradeSkipEvent] = []
        self.invariant_violations: List[InvariantViolationEvent] = []
        self._skip_counts: Dict[TradeSkipReason, int] = {}
        self._violation_counts: Dict[InvariantViolationReason, int] = {}
    
    def log_trade_skip(
        self,
        asset: str,
        ticker: str,
        reason: TradeSkipReason,
        edge: Optional[float] = None,
        volatility: Optional[float] = None,
        volume: Optional[int] = None,
        spread_cents: Optional[int] = None,
        velocity: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> TradeSkipEvent:
        """Log a trade skip event."""
        event = TradeSkipEvent(
            timestamp=datetime.now(),
            asset=asset,
            ticker=ticker,
            reason=reason,
            edge=edge,
            volatility=volatility,
            volume=volume,
            spread_cents=spread_cents,
            velocity=velocity,
            context=context or {},
        )
        
        self.trade_skips.append(event)
        self._skip_counts[reason] = self._skip_counts.get(reason, 0) + 1
        
        # Log to system logger
        logger.warning(
            f"[TRADE-SKIP] {reason.value} | asset={asset} ticker={ticker} "
            f"edge={edge} volatility={volatility} volume={volume} spread={spread_cents} velocity={velocity}"
        )
        
        return event
    
    def log_invariant_violation(
        self,
        invariant_name: str,
        reason: InvariantViolationReason,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> InvariantViolationEvent:
        """Log an invariant violation event."""
        event = InvariantViolationEvent(
            timestamp=datetime.now(),
            invariant_name=invariant_name,
            reason=reason,
            severity=severity,
            message=message,
            context=context or {},
        )
        
        self.invariant_violations.append(event)
        self._violation_counts[reason] = self._violation_counts.get(reason, 0) + 1
        
        # Log to system logger
        log_level = logger.error if severity == "CRITICAL" else logger.warning
        log_level(
            f"[INVARIANT-VIOLATION] {invariant_name} | {reason.value} | {severity} | {message}"
        )
        
        return event
    
    def get_skip_statistics(self) -> Dict[str, int]:
        """Get statistics on trade skips by reason."""
        return {reason.value: count for reason, count in self._skip_counts.items()}
    
    def get_violation_statistics(self) -> Dict[str, int]:
        """Get statistics on invariant violations by reason."""
        return {reason.value: count for reason, count in self._violation_counts.items()}
    
    def get_recent_skips(
        self,
        limit: int = 100,
        reason_filter: Optional[TradeSkipReason] = None,
    ) -> List[TradeSkipEvent]:
        """Get recent trade skips, optionally filtered by reason."""
        skips = self.trade_skips[-limit:]
        if reason_filter:
            skips = [s for s in skips if s.reason == reason_filter]
        return skips
    
    def get_recent_violations(
        self,
        limit: int = 100,
        reason_filter: Optional[InvariantViolationReason] = None,
    ) -> List[InvariantViolationEvent]:
        """Get recent invariant violations, optionally filtered by reason."""
        violations = self.invariant_violations[-limit:]
        if reason_filter:
            violations = [v for v in violations if v.reason == reason_filter]
        return violations
    
    def clear_old_events(self, hours: int = 24):
        """Clear events older than specified hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        self.trade_skips = [s for s in self.trade_skips if s.timestamp > cutoff]
        self.invariant_violations = [v for v in self.invariant_violations if v.timestamp > cutoff]
        
        # Recount
        self._skip_counts = {}
        for skip in self.trade_skips:
            self._skip_counts[skip.reason] = self._skip_counts.get(skip.reason, 0) + 1
        
        self._violation_counts = {}
        for violation in self.invariant_violations:
            self._violation_counts[violation.reason] = self._violation_counts.get(violation.reason, 0) + 1


# Singleton instance
_error_taxonomy: Optional[ErrorTaxonomy] = None


def get_error_taxonomy() -> ErrorTaxonomy:
    """Get the singleton error taxonomy instance."""
    global _error_taxonomy
    if _error_taxonomy is None:
        _error_taxonomy = ErrorTaxonomy()
    return _error_taxonomy


# Convenience functions for direct use

def log_trade_skip(
    asset: str,
    ticker: str,
    reason: TradeSkipReason,
    edge: Optional[float] = None,
    volatility: Optional[float] = None,
    volume: Optional[int] = None,
    spread_cents: Optional[int] = None,
    velocity: Optional[float] = None,
    context: Optional[Dict[str, Any]] = None,
) -> TradeSkipEvent:
    """Log a trade skip event (convenience function)."""
    taxonomy = get_error_taxonomy()
    return taxonomy.log_trade_skip(
        asset, ticker, reason, edge, volatility, volume, spread_cents, velocity, context
    )


def log_invariant_violation(
    invariant_name: str,
    reason: InvariantViolationReason,
    severity: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> InvariantViolationEvent:
    """Log an invariant violation event (convenience function)."""
    taxonomy = get_error_taxonomy()
    return taxonomy.log_invariant_violation(
        invariant_name, reason, severity, message, context
    )


# Integration with existing invariant modules

def log_edge_probability_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "HIGH",
):
    """Log edge-probability invariant violation."""
    reason_map = {
        "edge_sign_mismatch": InvariantViolationReason.EDGE_SIGN_MISMATCH,
        "side_probability_mismatch": InvariantViolationReason.SIDE_PROBABILITY_MISMATCH,
        "confidence_not_monotonic": InvariantViolationReason.CONFIDENCE_NOT_MONOTONIC,
        "low_edge_high_confidence": InvariantViolationReason.LOW_EDGE_HIGH_CONFIDENCE,
        "invalid_probability_range": InvariantViolationReason.INVALID_PROBABILITY_RANGE,
        "invalid_edge_range": InvariantViolationReason.INVALID_EDGE_RANGE,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Edge Probability Consistency", reason, severity, message, context)


def log_regime_gating_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "HIGH",
):
    """Log regime gating invariant violation."""
    reason_map = {
        "volatility_halt_trade": InvariantViolationReason.VOLATILITY_HALT_TRADE,
        "volume_illiquid_trade": InvariantViolationReason.VOLUME_ILLIQUID_TRADE,
        "velocity_extreme_contrainrian": InvariantViolationReason.VELOCITY_EXTREME_CONTRARIAN,
        "position_size_not_shrunk": InvariantViolationReason.POSITION_SIZE_NOT_SHRUNK,
        "max_notional_exceeded": InvariantViolationReason.MAX_NOTIONAL_EXCEEDED,
        "spread_too_wide": InvariantViolationReason.SPREAD_TOO_WIDE,
        "regime_tag_missing": InvariantViolationReason.REGIME_TAG_MISSING,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Regime Gating", reason, severity, message, context)


def log_spot_strike_distance_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "HIGH",
):
    """Log spot-strike distance invariant violation."""
    reason_map = {
        "distance_exceeded": InvariantViolationReason.DISTANCE_EXCEEDED,
        "deep_otm_without_extreme_edge": InvariantViolationReason.DEEP_OTM_WITHOUT_EXTREME_EDGE,
        "contract_selection_mismatch": InvariantViolationReason.CONTRACT_SELECTION_MISMATCH,
        "invalid_spot_price": InvariantViolationReason.INVALID_SPOT_PRICE,
        "invalid_strike_price": InvariantViolationReason.INVALID_STRIKE_PRICE,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Spot-Strike Distance", reason, severity, message, context)


def log_canonical_mapping_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "CRITICAL",
):
    """Log canonical mapping invariant violation."""
    reason_map = {
        "illegal_semantic_combination": InvariantViolationReason.ILLEGAL_SEMANTIC_COMBINATION,
        "thesis_side_mismatch": InvariantViolationReason.THESIS_SIDE_MISMATCH,
        "contract_type_mismatch": InvariantViolationReason.CONTRACT_TYPE_MISMATCH,
        "order_action_mismatch": InvariantViolationReason.ORDER_ACTION_MISMATCH,
        "entry_exit_inversion": InvariantViolationReason.ENTRY_EXIT_INVERSION,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Canonical Mapping", reason, severity, message, context)


def log_reconciliation_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "CRITICAL",
):
    """Log reconciliation invariant violation."""
    reason_map = {
        "position_size_mismatch": InvariantViolationReason.POSITION_SIZE_MISMATCH,
        "pnl_calculation_mismatch": InvariantViolationReason.PNL_CALCULATION_MISMATCH,
        "orphan_order": InvariantViolationReason.ORPHAN_ORDER,
        "orphan_fill": InvariantViolationReason.ORPHAN_FILL,
        "pnl_without_position": InvariantViolationReason.PNL_WITHOUT_POSITION,
        "negative_balance": InvariantViolationReason.NEGATIVE_BALANCE,
        "leverage_exceeded": InvariantViolationReason.LEVERAGE_EXCEEDED,
        "episode_id_missing": InvariantViolationReason.EPISODE_ID_MISSING,
        "edge_attribution_mismatch": InvariantViolationReason.EDGE_ATTRIBUTION_MISMATCH,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Reconciliation", reason, severity, message, context)


def log_config_violation(
    violation_type: str,
    message: str,
    context: Dict[str, Any],
    severity: str = "HIGH",
):
    """Log configuration invariant violation."""
    reason_map = {
        "profile_mismatch": InvariantViolationReason.PROFILE_MISMATCH,
        "risk_limit_mismatch": InvariantViolationReason.RISK_LIMIT_MISMATCH,
        "price_range_mismatch": InvariantViolationReason.PRICE_RANGE_MISMATCH,
        "asset_universe_mismatch": InvariantViolationReason.ASSET_UNIVERSE_MISMATCH,
        "exposure_cap_mismatch": InvariantViolationReason.EXPOSURE_CAP_MISMATCH,
        "hardcoded_value_mismatch": InvariantViolationReason.HARDCODED_VALUE_MISMATCH,
    }
    
    reason = reason_map.get(violation_type, InvariantViolationReason.UNKNOWN)
    log_invariant_violation("Configuration", reason, severity, message, context)


# Trade skip convenience functions

def log_edge_too_small(
    asset: str,
    ticker: str,
    edge: float,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to edge being too small."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.EDGE_TOO_SMALL, edge=edge, context=context
    )


def log_vol_too_high(
    asset: str,
    ticker: str,
    volatility: float,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to volatility being too high."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.VOL_TOO_HIGH, volatility=volatility, context=context
    )


def log_config_mismatch(
    asset: str,
    ticker: str,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to configuration mismatch."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.CONFIG_MISMATCH, context=context
    )


def log_volume_illiquid(
    asset: str,
    ticker: str,
    volume: int,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to insufficient volume."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.VOLUME_ILLIQUID, volume=volume, context=context
    )


def log_spread_too_wide(
    asset: str,
    ticker: str,
    spread_cents: int,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to spread being too wide."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.SPREAD_TOO_WIDE, spread_cents=spread_cents, context=context
    )


def log_velocity_extreme(
    asset: str,
    ticker: str,
    velocity: float,
    context: Optional[Dict[str, Any]] = None,
):
    """Log trade skip due to extreme velocity."""
    return log_trade_skip(
        asset, ticker, TradeSkipReason.VELOCITY_EXTREME, velocity=velocity, context=context
    )
