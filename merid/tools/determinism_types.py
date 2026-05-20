"""
Determinism Bundle Types

Defines the data structures for determinism replay validation.
A determinism bundle captures the minimal inputs required to reproduce
a trading decision, allowing us to verify that the same inputs produce
the same outputs over time.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class DecisionType(Enum):
    """Type of trading decision."""
    ENTRY = "entry"
    EXIT = "exit"
    TRIM = "trim"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class DeterminismBundle:
    """
    Minimal inputs required to reproduce a trading decision.
    
    This bundle captures the essential state at decision time, excluding
    transient or non-deterministic information (timestamps, random seeds, etc.).
    """
    # Identification
    bundle_id: str
    timestamp: datetime
    market_id: str
    asset: str
    timeframe: str
    
    # Decision type
    decision_type: DecisionType
    
    # Input features (minimal set)
    feature_vector: Dict[str, float]  # Model inputs
    config_hash: str  # Hash of configuration at decision time
    model_version: str  # Model version identifier
    contract_metadata: Dict[str, Any]  # Contract specs snapshot
    
    # System state flags
    kill_switch_state: str  # "on", "off", "partial"
    risk_regime: str  # "normal", "tight", "halt"
    
    # Original output (for comparison)
    original_signal_direction: str  # "yes", "no", "both"
    original_prob_edge: float
    original_size_intent: int
    original_reason: str
    
    # Metadata
    correlation_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "bundle_id": self.bundle_id,
            "timestamp": self.timestamp.isoformat(),
            "market_id": self.market_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "decision_type": self.decision_type.value,
            "feature_vector": self.feature_vector,
            "config_hash": self.config_hash,
            "model_version": self.model_version,
            "contract_metadata": self.contract_metadata,
            "kill_switch_state": self.kill_switch_state,
            "risk_regime": self.risk_regime,
            "original_signal_direction": self.original_signal_direction,
            "original_prob_edge": self.original_prob_edge,
            "original_size_intent": self.original_size_intent,
            "original_reason": self.original_reason,
            "correlation_id": self.correlation_id,
            "agent_id": self.agent_id,
        }


@dataclass
class ReplayResult:
    """Result of replaying a determinism bundle."""
    bundle_id: str
    
    # Replay outputs
    replay_signal_direction: str
    replay_prob_edge: float
    replay_size_intent: int
    replay_reason: str
    
    # Comparison
    direction_match: bool
    prob_edge_match: bool
    size_match: bool
    reason_match: bool
    
    # Tolerance checks
    prob_edge_diff: float
    prob_edge_within_tolerance: bool
    size_diff: int
    size_within_tolerance: bool
    
    # Status
    passed: bool
    failure_reason: Optional[str] = None
    
    # Metadata
    replay_timestamp: datetime = field(default_factory=lambda: datetime.now())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "bundle_id": self.bundle_id,
            "replay_signal_direction": self.replay_signal_direction,
            "replay_prob_edge": self.replay_prob_edge,
            "replay_size_intent": self.replay_size_intent,
            "replay_reason": self.replay_reason,
            "direction_match": self.direction_match,
            "prob_edge_match": self.prob_edge_match,
            "size_match": self.size_match,
            "reason_match": self.reason_match,
            "prob_edge_diff": self.prob_edge_diff,
            "prob_edge_within_tolerance": self.prob_edge_within_tolerance,
            "size_diff": self.size_diff,
            "size_within_tolerance": self.size_within_tolerance,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "replay_timestamp": self.replay_timestamp.isoformat(),
        }


@dataclass
class ReplaySummary:
    """Summary of replay job execution."""
    total_bundles: int
    passed: int
    failed: int
    skipped: int
    
    # Mismatch breakdown
    direction_mismatches: int
    prob_edge_mismatches: int
    size_mismatches: int
    reason_mismatches: int
    
    # Metrics
    pass_rate: float
    avg_prob_edge_diff: float
    avg_size_diff: float
    
    # Results
    results: List[ReplayResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_bundles": self.total_bundles,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "direction_mismatches": self.direction_mismatches,
            "prob_edge_mismatches": self.prob_edge_mismatches,
            "size_mismatches": self.size_mismatches,
            "reason_mismatches": self.reason_mismatches,
            "pass_rate": self.pass_rate,
            "avg_prob_edge_diff": self.avg_prob_edge_diff,
            "avg_size_diff": self.avg_size_diff,
            "results": [r.to_dict() for r in self.results],
        }
