"""
MERID-OPS Cross-Domain Conflict Detector

Detects when different data domains disagree:
- News says bullish but price is falling
- Prediction markets say X but on-chain shows Y
- Social sentiment diverges from market action

These conflicts are valuable signals - they indicate either:
1. Information asymmetry (opportunity)
2. Market inefficiency (opportunity)
3. Data quality issues (risk)
4. Regime change (critical)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("ops.conflict_detector")


class Domain(Enum):
    """Data domains that can conflict."""
    PRICE = "price"
    NEWS = "news"
    SOCIAL = "social"
    PREDICTION = "prediction"
    ON_CHAIN = "on_chain"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"


class ConflictSeverity(Enum):
    """Severity of a detected conflict."""
    LOW = "low"           # Minor disagreement, informational
    MEDIUM = "medium"     # Notable divergence, worth monitoring
    HIGH = "high"         # Significant conflict, requires attention
    CRITICAL = "critical" # Major disagreement, possible regime change


@dataclass
class DomainSignal:
    """A signal from a specific domain."""
    domain: Domain
    signal_type: str
    direction: str  # bullish, bearish, neutral
    strength: float  # 0.0 to 1.0
    confidence: float
    timestamp: float
    source: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Conflict:
    """A detected conflict between domains."""
    conflict_id: str
    domain_a: Domain
    domain_b: Domain
    signal_a: DomainSignal
    signal_b: DomainSignal
    severity: ConflictSeverity
    description: str
    interpretation: str
    detected_at: float
    resolved: bool = False
    resolution: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "domain_a": self.domain_a.value,
            "domain_b": self.domain_b.value,
            "severity": self.severity.value,
            "description": self.description,
            "interpretation": self.interpretation,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "signal_a": {
                "direction": self.signal_a.direction,
                "strength": self.signal_a.strength,
                "source": self.signal_a.source,
            },
            "signal_b": {
                "direction": self.signal_b.direction,
                "strength": self.signal_b.strength,
                "source": self.signal_b.source,
            },
        }


class CrossDomainConflictDetector:
    """
    Detects conflicts between different data domains.
    
    Conflict types:
    - Direction conflict: One domain bullish, another bearish
    - Magnitude conflict: Both same direction but very different strength
    - Timing conflict: Signals out of sync
    - Narrative conflict: Story doesn't match data
    """
    
    # Conflict interpretations
    INTERPRETATIONS = {
        (Domain.NEWS, Domain.PRICE): {
            "bullish_bearish": "News positive but price falling - possible sell-the-news or delayed reaction",
            "bearish_bullish": "News negative but price rising - possible buy-the-dip or priced in",
        },
        (Domain.SOCIAL, Domain.PRICE): {
            "bullish_bearish": "Social sentiment high but price falling - retail trapped or manipulation",
            "bearish_bullish": "Social sentiment low but price rising - smart money accumulation",
        },
        (Domain.PREDICTION, Domain.PRICE): {
            "bullish_bearish": "Prediction markets bullish but price falling - information asymmetry",
            "bearish_bullish": "Prediction markets bearish but price rising - market inefficiency",
        },
        (Domain.ON_CHAIN, Domain.PRICE): {
            "bullish_bearish": "On-chain bullish but price falling - accumulation phase",
            "bearish_bullish": "On-chain bearish but price rising - distribution phase",
        },
        (Domain.TECHNICAL, Domain.FUNDAMENTAL): {
            "bullish_bearish": "Technicals bullish but fundamentals weak - momentum trade only",
            "bearish_bullish": "Technicals bearish but fundamentals strong - value opportunity",
        },
    }
    
    def __init__(self):
        self._domain_signals: Dict[Domain, List[DomainSignal]] = {d: [] for d in Domain}
        self._conflicts: List[Conflict] = []
        self._max_signals_per_domain = 100
        self._max_conflicts = 500
        self._conflict_count = 0
        
        logger.info("Cross-domain conflict detector initialized")
    
    def record_signal(
        self,
        domain: Domain,
        signal_type: str,
        direction: str,
        strength: float,
        confidence: float,
        source: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> DomainSignal:
        """Record a signal from a domain."""
        signal = DomainSignal(
            domain=domain,
            signal_type=signal_type,
            direction=direction,
            strength=min(1.0, max(0.0, strength)),
            confidence=min(1.0, max(0.0, confidence)),
            timestamp=time.time(),
            source=source,
            details=details or {},
        )
        
        self._domain_signals[domain].append(signal)
        
        # Cleanup
        if len(self._domain_signals[domain]) > self._max_signals_per_domain:
            self._domain_signals[domain] = self._domain_signals[domain][-self._max_signals_per_domain:]
        
        # Check for conflicts with other domains
        self._check_conflicts(signal)
        
        return signal
    
    def _get_latest_signal(self, domain: Domain, max_age_seconds: float = 300) -> Optional[DomainSignal]:
        """Get the latest signal from a domain within max age."""
        signals = self._domain_signals[domain]
        if not signals:
            return None
        
        latest = signals[-1]
        if time.time() - latest.timestamp > max_age_seconds:
            return None
        
        return latest
    
    def _check_conflicts(self, new_signal: DomainSignal) -> List[Conflict]:
        """Check for conflicts between new signal and other domains."""
        conflicts = []
        
        for domain in Domain:
            if domain == new_signal.domain:
                continue
            
            other_signal = self._get_latest_signal(domain)
            if not other_signal:
                continue
            
            conflict = self._detect_conflict(new_signal, other_signal)
            if conflict:
                conflicts.append(conflict)
                self._conflicts.append(conflict)
                
                # Cleanup
                if len(self._conflicts) > self._max_conflicts:
                    self._conflicts = self._conflicts[-self._max_conflicts:]
        
        return conflicts
    
    def _detect_conflict(
        self,
        signal_a: DomainSignal,
        signal_b: DomainSignal,
    ) -> Optional[Conflict]:
        """Detect if two signals conflict."""
        # Direction conflict
        if signal_a.direction != signal_b.direction:
            if signal_a.direction != "neutral" and signal_b.direction != "neutral":
                return self._create_conflict(
                    signal_a, signal_b,
                    conflict_type="direction",
                )
        
        # Magnitude conflict (same direction, very different strength)
        if signal_a.direction == signal_b.direction and signal_a.direction != "neutral":
            strength_diff = abs(signal_a.strength - signal_b.strength)
            if strength_diff > 0.5:
                return self._create_conflict(
                    signal_a, signal_b,
                    conflict_type="magnitude",
                )
        
        return None
    
    def _create_conflict(
        self,
        signal_a: DomainSignal,
        signal_b: DomainSignal,
        conflict_type: str,
    ) -> Conflict:
        """Create a conflict record."""
        self._conflict_count += 1
        
        # Determine severity
        avg_confidence = (signal_a.confidence + signal_b.confidence) / 2
        avg_strength = (signal_a.strength + signal_b.strength) / 2
        
        if avg_confidence > 0.8 and avg_strength > 0.7:
            severity = ConflictSeverity.CRITICAL
        elif avg_confidence > 0.6 and avg_strength > 0.5:
            severity = ConflictSeverity.HIGH
        elif avg_confidence > 0.4:
            severity = ConflictSeverity.MEDIUM
        else:
            severity = ConflictSeverity.LOW
        
        # Get interpretation
        key = (signal_a.domain, signal_b.domain)
        reverse_key = (signal_b.domain, signal_a.domain)
        
        direction_key = f"{signal_a.direction}_{signal_b.direction}"
        
        interpretation = "Unknown conflict pattern"
        if key in self.INTERPRETATIONS:
            interpretation = self.INTERPRETATIONS[key].get(direction_key, interpretation)
        elif reverse_key in self.INTERPRETATIONS:
            reverse_direction_key = f"{signal_b.direction}_{signal_a.direction}"
            interpretation = self.INTERPRETATIONS[reverse_key].get(reverse_direction_key, interpretation)
        
        # Create description
        description = (
            f"{signal_a.domain.value} ({signal_a.direction}, {signal_a.strength:.1%}) "
            f"conflicts with {signal_b.domain.value} ({signal_b.direction}, {signal_b.strength:.1%})"
        )
        
        conflict = Conflict(
            conflict_id=f"conf_{self._conflict_count}_{int(time.time())}",
            domain_a=signal_a.domain,
            domain_b=signal_b.domain,
            signal_a=signal_a,
            signal_b=signal_b,
            severity=severity,
            description=description,
            interpretation=interpretation,
            detected_at=time.time(),
        )
        
        logger.info(
            "CONFLICT DETECTED [%s]: %s vs %s - %s",
            severity.value, signal_a.domain.value, signal_b.domain.value, interpretation
        )
        
        return conflict
    
    def get_active_conflicts(
        self,
        min_severity: ConflictSeverity = ConflictSeverity.LOW,
        max_age_seconds: float = 3600,
    ) -> List[Conflict]:
        """Get active (unresolved) conflicts."""
        cutoff = time.time() - max_age_seconds
        severity_order = [ConflictSeverity.LOW, ConflictSeverity.MEDIUM, ConflictSeverity.HIGH, ConflictSeverity.CRITICAL]
        min_index = severity_order.index(min_severity)
        
        return [
            c for c in self._conflicts
            if not c.resolved
            and c.detected_at > cutoff
            and severity_order.index(c.severity) >= min_index
        ]
    
    def resolve_conflict(self, conflict_id: str, resolution: str) -> bool:
        """Mark a conflict as resolved."""
        for conflict in self._conflicts:
            if conflict.conflict_id == conflict_id:
                conflict.resolved = True
                conflict.resolution = resolution
                return True
        return False
    
    def get_domain_alignment(self) -> Dict[str, Any]:
        """Get alignment status across all domains."""
        directions = {}
        for domain in Domain:
            signal = self._get_latest_signal(domain)
            if signal:
                directions[domain.value] = {
                    "direction": signal.direction,
                    "strength": signal.strength,
                    "confidence": signal.confidence,
                    "age_seconds": time.time() - signal.timestamp,
                }
        
        # Calculate alignment score
        if len(directions) < 2:
            alignment_score = 1.0
        else:
            bullish = sum(1 for d in directions.values() if d["direction"] == "bullish")
            bearish = sum(1 for d in directions.values() if d["direction"] == "bearish")
            total = len(directions)
            
            # High alignment if most agree
            max_agreement = max(bullish, bearish)
            alignment_score = max_agreement / total
        
        return {
            "domains": directions,
            "alignment_score": round(alignment_score, 3),
            "is_aligned": alignment_score > 0.6,
            "dominant_direction": self._get_dominant_direction(directions),
        }
    
    def _get_dominant_direction(self, directions: Dict[str, Any]) -> str:
        """Get the dominant direction across domains."""
        if not directions:
            return "neutral"
        
        bullish_weight = sum(
            d["strength"] * d["confidence"]
            for d in directions.values()
            if d["direction"] == "bullish"
        )
        bearish_weight = sum(
            d["strength"] * d["confidence"]
            for d in directions.values()
            if d["direction"] == "bearish"
        )
        
        if bullish_weight > bearish_weight * 1.2:
            return "bullish"
        elif bearish_weight > bullish_weight * 1.2:
            return "bearish"
        return "neutral"
    
    def get_status(self) -> Dict[str, Any]:
        """Get detector status."""
        active_conflicts = self.get_active_conflicts()
        alignment = self.get_domain_alignment()
        
        return {
            "total_conflicts": len(self._conflicts),
            "active_conflicts": len(active_conflicts),
            "critical_conflicts": len([c for c in active_conflicts if c.severity == ConflictSeverity.CRITICAL]),
            "high_conflicts": len([c for c in active_conflicts if c.severity == ConflictSeverity.HIGH]),
            "alignment": alignment,
            "signals_by_domain": {
                d.value: len(self._domain_signals[d])
                for d in Domain
            },
        }
    
    def get_conflicts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent conflicts."""
        return [c.to_dict() for c in self._conflicts[-limit:]]


# Singleton
_conflict_detector: Optional[CrossDomainConflictDetector] = None


def get_conflict_detector() -> CrossDomainConflictDetector:
    """Get the singleton conflict detector."""
    global _conflict_detector
    if _conflict_detector is None:
        _conflict_detector = CrossDomainConflictDetector()
    return _conflict_detector
