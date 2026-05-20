"""
Sizing Decision Types

Defines the data structures for sizing validation.
A SizingDecision captures the intended size and constraints for a trade,
allowing us to validate that sizing logic produces consistent results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class ConstraintType(Enum):
    """Type of sizing constraint."""
    RISK_LIMIT = "risk_limit"
    POSITION_LIMIT = "position_limit"
    BANKROLL_LIMIT = "bankroll_limit"
    KILL_SWITCH = "kill_switch"
    SENTIMENT_TIGHTENING = "sentiment_tightening"
    VOLATILITY_TIGHTENING = "volatility_tightening"
    TERMINAL_PHASE = "terminal_phase"
    OTHER = "other"


@dataclass(frozen=True)
class AppliedConstraint:
    """A constraint that was applied to the sizing decision."""
    constraint_type: ConstraintType
    original_size: int
    adjusted_size: int
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SizingDecision:
    """
    Intended sizing decision for a trade.
    
    Captures the full context of a sizing decision, including the base
    calculation, all constraints applied, and the final intended size.
    """
    # Identification
    decision_id: str
    timestamp: datetime
    market_id: str
    asset: str
    order_id: Optional[str] = None
    
    # Base sizing calculation
    base_kelly_size: float  # Raw Kelly fraction
    base_size: int  # Base size in contracts
    base_notional_usd: float  # Base notional in USD
    
    # Final intended size
    intended_size: int  # Final intended size in contracts
    intended_notional_usd: float  # Final intended notional in USD
    
    # Constraints applied
    constraints_applied: List[AppliedConstraint] = field(default_factory=list)
    
    # Context
    bankroll_usd: float
    max_position_usd: float
    risk_regime: str
    sentiment_regime: str
    volatility_regime: str
    
    # Version tracking
    sizing_version_hash: str  # Hash of sizing logic version
    config_hash: str  # Hash of configuration
    
    # Metadata
    correlation_id: Optional[str] = None
    agent_id: Optional[str] = None
    strategy: str = "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp.isoformat(),
            "market_id": self.market_id,
            "asset": self.asset,
            "order_id": self.order_id,
            "base_kelly_size": self.base_kelly_size,
            "base_size": self.base_size,
            "base_notional_usd": self.base_notional_usd,
            "intended_size": self.intended_size,
            "intended_notional_usd": self.intended_notional_usd,
            "constraints_applied": [
                {
                    "constraint_type": c.constraint_type.value,
                    "original_size": c.original_size,
                    "adjusted_size": c.adjusted_size,
                    "reason": c.reason,
                    "metadata": c.metadata,
                }
                for c in self.constraints_applied
            ],
            "bankroll_usd": self.bankroll_usd,
            "max_position_usd": self.max_position_usd,
            "risk_regime": self.risk_regime,
            "sentiment_regime": self.sentiment_regime,
            "volatility_regime": self.volatility_regime,
            "sizing_version_hash": self.sizing_version_hash,
            "config_hash": self.config_hash,
            "correlation_id": self.correlation_id,
            "agent_id": self.agent_id,
            "strategy": self.strategy,
        }


@dataclass
class SizingValidationResult:
    """Result of validating a sizing decision."""
    decision_id: str
    
    # Stored vs recomputed
    stored_intended_size: int
    recomputed_intended_size: int
    stored_notional: float
    recomputed_notional: float
    
    # Actual fill
    actual_fill_size: Optional[int] = None
    actual_fill_notional: Optional[float] = None
    
    # Comparison
    intended_size_match: bool
    intended_notional_match: bool
    actual_size_match: bool
    actual_notional_match: bool
    
    # Differences
    intended_size_diff: int
    intended_notional_diff: float
    actual_size_diff: Optional[int] = None
    actual_notional_diff: Optional[float] = None
    
    # Tolerance checks
    within_tolerance: bool
    tolerance_reason: Optional[str] = None
    
    # Status
    passed: bool
    failure_reason: Optional[str] = None
    
    # Metadata
    validation_timestamp: datetime = field(default_factory=lambda: datetime.now())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision_id": self.decision_id,
            "stored_intended_size": self.stored_intended_size,
            "recomputed_intended_size": self.recomputed_intended_size,
            "stored_notional": self.stored_notional,
            "recomputed_notional": self.recomputed_notional,
            "actual_fill_size": self.actual_fill_size,
            "actual_fill_notional": self.actual_fill_notional,
            "intended_size_match": self.intended_size_match,
            "intended_notional_match": self.intended_notional_match,
            "actual_size_match": self.actual_size_match,
            "actual_notional_match": self.actual_notional_match,
            "intended_size_diff": self.intended_size_diff,
            "intended_notional_diff": self.intended_notional_diff,
            "actual_size_diff": self.actual_size_diff,
            "actual_notional_diff": self.actual_notional_diff,
            "within_tolerance": self.within_tolerance,
            "tolerance_reason": self.tolerance_reason,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "validation_timestamp": self.validation_timestamp.isoformat(),
        }


@dataclass
class SizingValidationSummary:
    """Summary of sizing validation job execution."""
    total_decisions: int
    passed: int
    failed: int
    skipped: int
    
    # Mismatch breakdown
    intended_size_mismatches: int
    intended_notional_mismatches: int
    actual_size_mismatches: int
    actual_notional_mismatches: int
    
    # Metrics
    pass_rate: float
    avg_intended_size_diff: float
    avg_intended_notional_diff: float
    
    # Results
    results: List[SizingValidationResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_decisions": self.total_decisions,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "intended_size_mismatches": self.intended_size_mismatches,
            "intended_notional_mismatches": self.intended_notional_mismatches,
            "actual_size_mismatches": self.actual_size_mismatches,
            "actual_notional_mismatches": self.actual_notional_mismatches,
            "pass_rate": self.pass_rate,
            "avg_intended_size_diff": self.avg_intended_size_diff,
            "avg_intended_notional_diff": self.avg_intended_notional_diff,
            "results": [r.to_dict() for r in self.results],
        }
