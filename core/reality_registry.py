"""
MERID Reality Registry - Constitutional Truth Ledger

This is the single source of truth for what MERID knows, how confident it is,
and whether it is allowed to be shown or influence decisions.

CONSTITUTIONAL RULES:
1. No UI element may render without ≥1 VALID RealityAssertion
2. Confidence ≠ truth
3. Expired assertions auto-suppress UI
4. Conflicted assertions must be shown as conflict, never resolved silently
5. Assertions decay even if nothing changes
"""

from __future__ import annotations

import threading
import time
import uuid
import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("core.reality_registry")


class AssertionDomain(Enum):
    """Assertion domains - what area of reality this claims to know."""
    MARKET = "market"
    ONCHAIN = "onchain"
    EXECUTION = "execution"
    GOVERNANCE = "governance"
    TREASURY = "treasury"
    SIMULATION = "simulation"
    AGENT = "agent"
    SYSTEM = "system"


class AssertionStatus(Enum):
    """Assertion status - current validity state."""
    VALID = "valid"
    DEGRADED = "degraded"
    CONFLICTED = "conflicted"
    EXPIRED = "expired"
    INVALID = "invalid"


class UIVisibility(Enum):
    """UI visibility control."""
    VISIBLE = "visible"
    WARNING = "warning"
    SUPPRESSED = "suppressed"


@dataclass
class AssertionProvenance:
    """Source of an assertion."""
    source_id: str
    module_id: str
    evidence_hash: str
    weight: float  # 0-1
    timestamp: float


@dataclass
class RealityAssertion:
    """
    A bounded claim with decay.
    
    This is NOT a fact and NOT a belief.
    It is a time-bounded claim that decays automatically.
    """
    assertion_id: str
    domain: AssertionDomain
    description: str
    
    # Truth metrics
    confidence_score: float  # 0-1, raw untrusted
    provenance_score: float  # 0-1, source trustworthiness
    regime_compatibility: float  # 0-1, fits current regime
    
    # Decay
    decay_rate: float  # lambda for exponential decay
    last_verified_at: float
    validity_window: float  # seconds
    
    # Status
    status: AssertionStatus
    ui_visibility: UIVisibility
    execution_eligibility: bool
    
    # Sources
    sources: List[AssertionProvenance] = field(default_factory=list)
    
    # Conflicts
    conflicting_assertions: Set[str] = field(default_factory=set)
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    
    def effective_confidence(self, current_time: float, regime_entropy: float) -> float:
        """
        Calculate effective confidence after decay and regime entropy.
        
        This is the ONLY confidence value that matters.
        """
        # Time decay
        time_elapsed = current_time - self.last_verified_at
        time_decay = math.exp(-self.decay_rate * time_elapsed)
        
        # Regime entropy suppression
        regime_factor = 1.0 - regime_entropy
        
        # Combine
        effective = self.confidence_score * self.provenance_score * time_decay * regime_factor
        
        return max(0.0, min(1.0, effective))
    
    def is_usable(self, current_time: float, regime_entropy: float, threshold: float = 0.5) -> bool:
        """
        Check if assertion is usable for decisions.
        
        CONSTITUTIONAL: This is the gate for all action.
        """
        if self.status in (AssertionStatus.EXPIRED, AssertionStatus.INVALID):
            return False
        
        if self.status == AssertionStatus.CONFLICTED:
            return False
        
        effective = self.effective_confidence(current_time, regime_entropy)
        
        return effective >= threshold
    
    def to_dict(self) -> Dict:
        """Serialize for API."""
        return {
            "assertion_id": self.assertion_id,
            "domain": self.domain.value,
            "description": self.description,
            "confidence_score": self.confidence_score,
            "provenance_score": self.provenance_score,
            "regime_compatibility": self.regime_compatibility,
            "decay_rate": self.decay_rate,
            "last_verified_at": self.last_verified_at,
            "validity_window": self.validity_window,
            "status": self.status.value,
            "ui_visibility": self.ui_visibility.value,
            "execution_eligibility": self.execution_eligibility,
            "sources": [asdict(s) for s in self.sources],
            "conflicting_assertions": list(self.conflicting_assertions),
            "created_at": self.created_at,
        }


class AssertionAlgebra:
    """
    Truth composition rules.
    
    FORBIDDEN OPERATIONS:
    - Averaging confidence across domains
    - Normalizing uncertainty away
    - Collapsing conflicts into consensus
    - Promoting low-confidence agreement over high-confidence dissent
    """
    
    @staticmethod
    def conjunction(a: RealityAssertion, b: RealityAssertion, current_time: float, regime_entropy: float) -> float:
        """
        AND operation - weakest truth dominates.
        
        Used when BOTH assertions must be true.
        """
        # Get effective confidences
        a_eff = a.effective_confidence(current_time, regime_entropy)
        b_eff = b.effective_confidence(current_time, regime_entropy)
        
        # Weakest dominates
        result = min(a_eff, b_eff)
        
        # Conflict contamination
        if a.status == AssertionStatus.CONFLICTED or b.status == AssertionStatus.CONFLICTED:
            return 0.0
        
        return result
    
    @staticmethod
    def disjunction(a: RealityAssertion, b: RealityAssertion, current_time: float, regime_entropy: float) -> float:
        """
        OR operation - strongest truth wins.
        
        Used ONLY for contingency awareness, NEVER for execution eligibility.
        """
        a_eff = a.effective_confidence(current_time, regime_entropy)
        b_eff = b.effective_confidence(current_time, regime_entropy)
        
        return max(a_eff, b_eff)
    
    @staticmethod
    def check_execution_eligibility(assertions: List[RealityAssertion], current_time: float, regime_entropy: float, threshold: float = 0.5) -> Tuple[bool, str]:
        """
        Check if execution is allowed.
        
        CONSTITUTIONAL: ALL required assertions must be usable.
        There is NO weighted exception.
        """
        if not assertions:
            return False, "No assertions provided"
        
        for assertion in assertions:
            if not assertion.is_usable(current_time, regime_entropy, threshold):
                return False, f"Assertion {assertion.assertion_id} not usable: {assertion.status.value}"
        
        return True, "All assertions valid"


class AuditorMode(Enum):  # FPA-05: removed duplicate UIVisibility — see line 51 for canonical definition
    """Reality auditor operating modes."""
    NORMAL = "normal"
    STRICT = "strict"
    BLINDNESS = "blindness"


class BlindnessSeverity(Enum):
    """Blindness severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BlindnessContext:
    """Context for blindness detection and management."""
    mode: AuditorMode = AuditorMode.NORMAL
    severity: BlindnessSeverity = BlindnessSeverity.LOW
    trigger_reason: str = ""
    affected_domains: List[AssertionDomain] = field(default_factory=list)
    mitigation_actions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "mode": self.mode.value,
            "severity": self.severity.value,
            "trigger_reason": self.trigger_reason,
            "affected_domains": [d.value for d in self.affected_domains],
            "mitigation_actions": self.mitigation_actions,
            "created_at": self.created_at,
        }


class AssertionPipelineHealth(Enum):
    """Assertion pipeline health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RealityRegistry:
    """
    The single source of truth for what MERID knows.
    
    CONSTITUTIONAL RULES:
    1. Nothing can delete an assertion, only invalidate it
    2. Assertions decay automatically
    3. Conflicts are detected and preserved
    4. UI cannot query engines directly - must go through registry
    """
    
    def __init__(self):
        self._assertions: Dict[str, RealityAssertion] = {}
        self._domain_index: Dict[AssertionDomain, Set[str]] = defaultdict(set)
        self._conflict_graph: Dict[str, Set[str]] = defaultdict(set)
        self._decay_events: List[Dict] = []
        
        logger.info("RealityRegistry initialized - truth ledger active")
    
    def register_assertion(
        self,
        domain: AssertionDomain,
        description: str,
        confidence: float,
        provenance_score: float,
        regime_compatibility: float,
        decay_rate: float,
        validity_window: float,
        sources: List[AssertionProvenance],
    ) -> str:
        """
        Register a new assertion.
        
        Returns assertion_id.
        """
        assertion_id = str(uuid.uuid4())
        
        assertion = RealityAssertion(
            assertion_id=assertion_id,
            domain=domain,
            description=description,
            confidence_score=confidence,
            provenance_score=provenance_score,
            regime_compatibility=regime_compatibility,
            decay_rate=decay_rate,
            last_verified_at=time.time(),
            validity_window=validity_window,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
            sources=sources,
        )
        
        self._assertions[assertion_id] = assertion
        self._domain_index[domain].add(assertion_id)
        
        logger.info(f"Assertion registered: {assertion_id} ({domain.value})")
        
        return assertion_id
    
    def get_assertion(self, assertion_id: str) -> Optional[RealityAssertion]:
        """Get assertion by ID."""
        return self._assertions.get(assertion_id)
    
    def get_assertions_by_domain(self, domain: AssertionDomain) -> List[RealityAssertion]:
        """Get all assertions for a domain."""
        assertion_ids = self._domain_index.get(domain, set())
        return [self._assertions[aid] for aid in assertion_ids if aid in self._assertions]
    
    def mark_conflict(self, assertion_id_a: str, assertion_id_b: str):
        """
        Mark two assertions as conflicting.
        
        CONSTITUTIONAL: Conflicts are preserved, never auto-resolved.
        """
        if assertion_id_a not in self._assertions or assertion_id_b not in self._assertions:
            return
        
        # Add to conflict graph
        self._conflict_graph[assertion_id_a].add(assertion_id_b)
        self._conflict_graph[assertion_id_b].add(assertion_id_a)
        
        # Update assertion status
        self._assertions[assertion_id_a].status = AssertionStatus.CONFLICTED
        self._assertions[assertion_id_b].status = AssertionStatus.CONFLICTED
        
        self._assertions[assertion_id_a].conflicting_assertions.add(assertion_id_b)
        self._assertions[assertion_id_b].conflicting_assertions.add(assertion_id_a)
        
        logger.warning(f"Conflict detected: {assertion_id_a} <-> {assertion_id_b}")
    
    def update_assertion_status(self, current_time: float, regime_entropy: float):
        """
        Update all assertion statuses based on decay and expiration.
        
        This runs automatically and cannot be disabled.
        """
        for assertion in self._assertions.values():
            # Check expiration
            time_since_verification = current_time - assertion.last_verified_at
            if time_since_verification > assertion.validity_window:
                if assertion.status != AssertionStatus.EXPIRED:
                    assertion.status = AssertionStatus.EXPIRED
                    assertion.ui_visibility = UIVisibility.SUPPRESSED
                    assertion.execution_eligibility = False
                    logger.info(f"Assertion expired: {assertion.assertion_id}")
            
            # Check effective confidence
            effective = assertion.effective_confidence(current_time, regime_entropy)
            
            # Record decay event
            if effective < assertion.confidence_score * 0.9:  # 10% decay threshold
                self._decay_events.append({
                    "assertion_id": assertion.assertion_id,
                    "old_confidence": assertion.confidence_score,
                    "new_effective": effective,
                    "timestamp": current_time,
                })
            
            # Update visibility based on effective confidence
            if effective < 0.3:
                assertion.ui_visibility = UIVisibility.SUPPRESSED
                assertion.execution_eligibility = False
            elif effective < 0.5:
                assertion.ui_visibility = UIVisibility.WARNING
                assertion.execution_eligibility = False
    
    def get_registry_status(self, current_time: float, regime_entropy: float) -> Dict:
        """
        Get overall registry health.
        
        This is what the UI Reality Status Panel displays.
        """
        total = len(self._assertions)
        if total == 0:
            return {
                "total_assertions": 0,
                "valid_pct": 0.0,
                "degraded_pct": 0.0,
                "conflicted_pct": 0.0,
                "expired_pct": 0.0,
                "regime_entropy": regime_entropy,
                "blind_spots": list(AssertionDomain),
            }
        
        status_counts = defaultdict(int)
        for assertion in self._assertions.values():
            status_counts[assertion.status] += 1
        
        # Check for blind spots (domains with no valid assertions)
        blind_spots = []
        for domain in AssertionDomain:
            domain_assertions = self.get_assertions_by_domain(domain)
            valid_count = sum(1 for a in domain_assertions if a.status == AssertionStatus.VALID)
            if valid_count == 0:
                blind_spots.append(domain.value)
        
        return {
            "total_assertions": total,
            "valid_pct": status_counts[AssertionStatus.VALID] / total * 100,
            "degraded_pct": status_counts[AssertionStatus.DEGRADED] / total * 100,
            "conflicted_pct": status_counts[AssertionStatus.CONFLICTED] / total * 100,
            "expired_pct": status_counts[AssertionStatus.EXPIRED] / total * 100,
            "regime_entropy": regime_entropy,
            "blind_spots": blind_spots,
            "active_conflicts": len(self._conflict_graph),
        }
    
    def check_blindness_condition(self, current_time: float, regime_entropy: float) -> Tuple[bool, str]:
        """
        Check if system should enter Blindness Mode.
        
        CONSTITUTIONAL: Blindness Mode is success, not failure.
        """
        total = len(self._assertions)
        if total == 0:
            return True, "No assertions registered"
        
        # Check core domains FIRST (most important)
        core_domains = [AssertionDomain.EXECUTION, AssertionDomain.TREASURY]
        for domain in core_domains:
            domain_assertions = self.get_assertions_by_domain(domain)
            valid = sum(1 for a in domain_assertions if a.status == AssertionStatus.VALID)
            if valid == 0:
                return True, f"Core domain {domain.value} has no valid assertions"
        
        # Check regime entropy
        if regime_entropy > 0.7:
            return True, f"Regime entropy {regime_entropy:.2f} > 0.7"
        
        # Check conflict rate (only among non-market assertions to avoid noise)
        non_market = [a for a in self._assertions.values() if a.domain != AssertionDomain.MARKET]
        if non_market:
            conflicted = sum(1 for a in non_market if a.status == AssertionStatus.CONFLICTED)
            conflict_pct = conflicted / len(non_market)
            if conflict_pct > 0.3:
                return True, f">{conflict_pct*100:.0f}% non-market assertions conflicted"
        
        # Only check overall expiration if it's extreme (>95%)
        # This prevents auto-generated market assertions from triggering blindness
        expired = sum(1 for a in self._assertions.values() if a.status == AssertionStatus.EXPIRED)
        expired_pct = expired / total
        if expired_pct > 0.95:
            return True, f">{expired_pct*100:.0f}% assertions expired"
        
        return False, "Reality stable"


# Singleton instance
_registry: Optional[RealityRegistry] = None
_registry_lock = threading.Lock()


def get_reality_registry() -> RealityRegistry:
    """Get the global reality registry."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = RealityRegistry()
    return _registry
