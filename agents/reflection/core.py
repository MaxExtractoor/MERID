"""
ReflectionCore - Layer 1: Decision Recording and Storage

Responsibilities:
- Record agent decisions with full context
- Validate input data
- Emit events for other layers
- Thread-safe operations
- Performance monitoring
"""

from __future__ import annotations

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from enum import Enum

from utils.logger import get_logger

logger = get_logger("reflection.core")


class DecisionOutcome(Enum):
    """Decision outcome status."""
    PENDING = "pending"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    CONFLICTED = "conflicted"


@dataclass
class Reflection:
    """
    Single reflection entry with comprehensive tracking.
    
    Enhanced from v1 with:
    - Input validation
    - Metadata tracking
    - Performance metrics
    - Conflict detection
    """
    # Core identifiers
    reflection_id: str
    agent_id: str
    energy_id: str
    
    # Decision data
    decision: str  # accept/reject/abstain
    confidence: float  # 0.0-1.0
    reasoning: str
    
    # Outcome tracking
    outcome: DecisionOutcome = DecisionOutcome.PENDING
    reality_gap: Optional[float] = None
    validation_score: Optional[float] = None
    
    # Timing
    decision_timestamp: float = field(default_factory=time.time)
    outcome_timestamp: Optional[float] = None
    
    # Learning
    learning_insight: Optional[str] = None
    pattern_tags: Set[str] = field(default_factory=set)
    
    # Context
    market_context: Dict[str, Any] = field(default_factory=dict)
    agent_state: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    version: str = "2.0"
    
    def __post_init__(self):
        """Validate reflection data."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")
        
        if self.decision not in ["accept", "reject", "abstain"]:
            raise ValueError(f"Invalid decision: {self.decision}")
        
        if not self.agent_id or not self.energy_id:
            raise ValueError("agent_id and energy_id are required")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['outcome'] = self.outcome.value
        data['pattern_tags'] = list(self.pattern_tags)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Reflection':
        """Create from dictionary."""
        data = data.copy()
        data['outcome'] = DecisionOutcome(data['outcome'])
        data['pattern_tags'] = set(data.get('pattern_tags', []))
        return cls(**data)
    
    def age_seconds(self) -> float:
        """Get age of reflection in seconds."""
        return time.time() - self.decision_timestamp
    
    def is_resolved(self) -> bool:
        """Check if outcome is resolved."""
        return self.outcome in [
            DecisionOutcome.VALIDATED,
            DecisionOutcome.INVALIDATED,
            DecisionOutcome.EXPIRED
        ]


class ReflectionCore:
    """
    Core reflection layer with robust operations.
    
    Features:
    - Thread-safe decision recording
    - Input validation
    - Event emission
    - Performance tracking
    - Memory management
    """
    
    def __init__(self, max_reflections: int = 50000):
        self.max_reflections = max_reflections
        self._reflections: Dict[str, Reflection] = {}
        self._agent_index: Dict[str, List[str]] = {}
        self._energy_index: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
        
        # Performance metrics
        self._record_count = 0
        self._update_count = 0
        self._query_count = 0
        self._start_time = time.time()
        self._started_at = time.time()
        
        logger.info("ReflectionCore initialized (max_reflections=%d)", max_reflections)
    
    def record_decision(
        self,
        agent_id: str,
        energy_id: str,
        decision: str,
        confidence: float,
        reasoning: str,
        market_context: Optional[Dict[str, Any]] = None,
        agent_state: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a new agent decision.
        
        Args:
            agent_id: Agent identifier
            energy_id: Energy packet identifier
            decision: Decision value (accept/reject/abstain)
            confidence: Confidence score (0.0-1.0)
            reasoning: Decision reasoning
            market_context: Optional market context
            agent_state: Optional agent state
        
        Returns:
            reflection_id: Unique reflection identifier
        
        Raises:
            ValueError: If input validation fails
        """
        start = time.time()
        
        try:
            reflection = Reflection(
                reflection_id=str(uuid.uuid4()),
                agent_id=agent_id,
                energy_id=energy_id,
                decision=decision,
                confidence=confidence,
                reasoning=reasoning[:1000],  # Truncate for storage
                market_context=market_context or {},
                agent_state=agent_state or {}
            )
            
            with self._lock:
                # Store reflection
                self._reflections[reflection.reflection_id] = reflection
                
                # Update indexes
                if agent_id not in self._agent_index:
                    self._agent_index[agent_id] = []
                self._agent_index[agent_id].append(reflection.reflection_id)
                
                if energy_id not in self._energy_index:
                    self._energy_index[energy_id] = []
                self._energy_index[energy_id].append(reflection.reflection_id)
                
                # Memory management
                if len(self._reflections) > self.max_reflections:
                    self._evict_oldest()
                
                self._record_count += 1
            
            duration_ms = (time.time() - start) * 1000
            logger.debug(
                "Recorded decision: agent=%s energy=%s decision=%s confidence=%.2f (%.2fms)",
                agent_id, energy_id, decision, confidence, duration_ms
            )
            
            return reflection.reflection_id
            
        except Exception as e:
            logger.error("Failed to record decision: %s", e, exc_info=True)
            raise
    
    def update_outcome(
        self,
        reflection_id: str,
        outcome: DecisionOutcome,
        reality_gap: Optional[float] = None,
        validation_score: Optional[float] = None,
        learning_insight: Optional[str] = None
    ) -> bool:
        """
        Update reflection with outcome data.
        
        Args:
            reflection_id: Reflection to update
            outcome: Outcome status
            reality_gap: Reality gap score
            validation_score: Validation confidence
            learning_insight: Learning generated from outcome
        
        Returns:
            bool: True if updated successfully
        """
        start = time.time()
        
        with self._lock:
            reflection = self._reflections.get(reflection_id)
            if not reflection:
                logger.warning("Reflection not found: %s", reflection_id)
                return False
            
            reflection.outcome = outcome
            reflection.reality_gap = reality_gap
            reflection.validation_score = validation_score
            reflection.learning_insight = learning_insight
            reflection.outcome_timestamp = time.time()
            
            self._update_count += 1
        
        duration_ms = (time.time() - start) * 1000
        logger.debug(
            "Updated outcome: reflection=%s outcome=%s gap=%.3f (%.2fms)",
            reflection_id[:8], outcome.value, reality_gap or 0, duration_ms
        )
        
        return True
    
    def get_reflection(self, reflection_id: str) -> Optional[Reflection]:
        """Get reflection by ID."""
        with self._lock:
            self._query_count += 1
            return self._reflections.get(reflection_id)
    
    def get_agent_reflections(
        self,
        agent_id: str,
        limit: Optional[int] = None,
        outcome_filter: Optional[DecisionOutcome] = None
    ) -> List[Reflection]:
        """
        Get reflections for an agent.
        
        Args:
            agent_id: Agent identifier
            limit: Maximum number to return
            outcome_filter: Filter by outcome status
        
        Returns:
            List of reflections (newest first)
        """
        with self._lock:
            self._query_count += 1
            
            reflection_ids = self._agent_index.get(agent_id, [])
            reflections = [
                self._reflections[rid]
                for rid in reflection_ids
                if rid in self._reflections
            ]
            
            if outcome_filter:
                reflections = [
                    r for r in reflections
                    if r.outcome == outcome_filter
                ]
            
            # Sort by timestamp (newest first)
            reflections.sort(key=lambda r: r.decision_timestamp, reverse=True)
            
            if limit:
                reflections = reflections[:limit]
            
            return reflections
    
    def get_energy_reflections(self, energy_id: str) -> List[Reflection]:
        """Get all reflections for an energy packet."""
        with self._lock:
            self._query_count += 1
            
            reflection_ids = self._energy_index.get(energy_id, [])
            return [
                self._reflections[rid]
                for rid in reflection_ids
                if rid in self._reflections
            ]
    
    def get_pending_reflections(self, max_age_seconds: Optional[float] = None) -> List[Reflection]:
        """
        Get pending reflections.
        
        Args:
            max_age_seconds: Only return reflections older than this
        
        Returns:
            List of pending reflections
        """
        with self._lock:
            self._query_count += 1
            
            pending = [
                r for r in self._reflections.values()
                if r.outcome == DecisionOutcome.PENDING
            ]
            
            if max_age_seconds:
                pending = [
                    r for r in pending
                    if r.age_seconds() >= max_age_seconds
                ]
            
            return pending
    
    def get_stats(self) -> Dict[str, Any]:
        """Get core layer statistics."""
        with self._lock:
            current_time = time.time()
            uptime_seconds = current_time - getattr(self, "_started_at", self._start_time)
            uptime_seconds = max(uptime_seconds, 1e-3)
            
            outcome_counts = {}
            for reflection in self._reflections.values():
                outcome = reflection.outcome.value
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            
            stats = {
                "total_reflections": len(self._reflections),
                "active_agents": len(self._agent_index),
                "unique_energies": len(self._energy_index),
                "outcome_distribution": outcome_counts,
                "operations": {
                    "records": self._record_count,
                    "updates": self._update_count,
                    "queries": self._query_count
                },
                "performance": {
                    "uptime_seconds": uptime_seconds,
                    "decisions_per_minute": self._record_count / max(uptime_seconds / 60, 1),
                    "updates_per_minute": self._update_count / max(uptime_seconds / 60, 1),
                }
            }
            return stats
    
    def _evict_oldest(self):
        """Evict oldest reflections when limit exceeded."""
        # Get all reflections sorted by age
        all_reflections = sorted(
            self._reflections.values(),
            key=lambda r: r.decision_timestamp
        )
        
        # Evict oldest 10%
        to_evict = int(len(all_reflections) * 0.1)
        for reflection in all_reflections[:to_evict]:
            rid = reflection.reflection_id
            
            # Remove from main storage
            del self._reflections[rid]
            
            # Remove from indexes
            if reflection.agent_id in self._agent_index:
                if rid in self._agent_index[reflection.agent_id]:
                    self._agent_index[reflection.agent_id].remove(rid)
            
            if reflection.energy_id in self._energy_index:
                if rid in self._energy_index[reflection.energy_id]:
                    self._energy_index[reflection.energy_id].remove(rid)
        
        logger.info("Evicted %d oldest reflections", to_evict)
    
    def clear(self):
        """Clear all reflections (for testing)."""
        with self._lock:
            self._reflections.clear()
            self._agent_index.clear()
            self._energy_index.clear()
            logger.warning("Cleared all reflections")
