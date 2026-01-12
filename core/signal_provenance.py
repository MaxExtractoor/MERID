"""
MERID Signal Synthesis Provenance System
Constitutional requirement: All signal synthesis must be traceable
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json

from utils.logger import get_logger

logger = get_logger("core.signal_provenance")


class SignalSource(Enum):
    """Sources of signals in the system"""
    PRICE_FEED = "price_feed"
    NEWS_AGENT = "news_agent"
    SENTIMENT_AGENT = "sentiment_agent"
    TECHNICAL_AGENT = "technical_agent"
    FUNDAMENTAL_AGENT = "fundamental_agent"
    RISK_AGENT = "risk_agent"
    SYNTHESIZER = "synthesizer"
    CONSENSUS = "consensus"
    EXTERNAL_API = "external_api"


class ConflictResolution(Enum):
    """How conflicts between signals were resolved"""
    TRUST_WEIGHTED = "trust_weighted"
    CONFIDENCE_WEIGHTED = "confidence_weighted"
    MAJORITY_VOTE = "majority_vote"
    HIGHEST_CONFIDENCE = "highest_confidence"
    MANUAL_OVERRIDE = "manual_override"
    VETO_APPLIED = "veto_applied"


@dataclass
class SourceSignal:
    """Individual signal from a source"""
    source_id: str
    source_type: SignalSource
    signal_value: Any
    confidence: float
    timestamp: float
    
    # Metadata
    raw_data: Dict[str, Any] = field(default_factory=dict)
    trust_score: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "signal_value": str(self.signal_value),
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
            "trust_score": round(self.trust_score, 4)
        }


@dataclass
class SignalConflict:
    """Record of conflicting signals"""
    conflict_id: str
    conflicting_signals: List[SourceSignal]
    resolution_method: ConflictResolution
    resolution_reasoning: str
    final_signal: Any
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflicting_signals": [s.to_dict() for s in self.conflicting_signals],
            "resolution_method": self.resolution_method.value,
            "resolution_reasoning": self.resolution_reasoning,
            "final_signal": str(self.final_signal),
            "timestamp": self.timestamp
        }


@dataclass
class SynthesisProvenance:
    """Complete provenance chain for a synthesized signal"""
    synthesis_id: str
    final_signal: Any
    final_confidence: float
    timestamp: float
    
    # Source tracking
    input_signals: List[SourceSignal] = field(default_factory=list)
    conflicts: List[SignalConflict] = field(default_factory=list)
    
    # Weighting logic
    weighting_formula: str = ""
    weight_distribution: Dict[str, float] = field(default_factory=dict)
    
    # Synthesis process
    synthesis_steps: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "synthesis_id": self.synthesis_id,
            "final_signal": str(self.final_signal),
            "final_confidence": round(self.final_confidence, 4),
            "timestamp": self.timestamp,
            "input_signals": [s.to_dict() for s in self.input_signals],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "weighting_formula": self.weighting_formula,
            "weight_distribution": {
                k: round(v, 4) for k, v in self.weight_distribution.items()
            },
            "synthesis_steps": self.synthesis_steps,
            "processing_time_ms": round(self.processing_time_ms, 2)
        }
    
    def to_human_readable(self) -> str:
        """Convert to human-readable provenance chain"""
        lines = [
            f"Signal Synthesis: {self.synthesis_id}",
            f"Final Signal: {self.final_signal} (Confidence: {self.final_confidence:.1%})",
            f"",
            f"Input Signals ({len(self.input_signals)}):",
        ]
        
        for signal in self.input_signals:
            lines.append(
                f"  {signal.source_id} ({signal.source_type.value}): "
                f"{signal.signal_value} (confidence: {signal.confidence:.1%}, "
                f"trust: {signal.trust_score:.2f})"
            )
        
        if self.conflicts:
            lines.append("")
            lines.append(f"Conflicts Resolved ({len(self.conflicts)}):")
            for conflict in self.conflicts:
                lines.append(f"  Conflict {conflict.conflict_id}:")
                lines.append(f"    Resolution: {conflict.resolution_method.value}")
                lines.append(f"    Reasoning: {conflict.resolution_reasoning}")
                lines.append(f"    Final: {conflict.final_signal}")
        
        lines.append("")
        lines.append("Weighting Formula:")
        lines.append(f"  {self.weighting_formula}")
        
        if self.weight_distribution:
            lines.append("")
            lines.append("Weight Distribution:")
            for source, weight in self.weight_distribution.items():
                lines.append(f"  {source}: {weight:.1%}")
        
        lines.append("")
        lines.append("Synthesis Steps:")
        for i, step in enumerate(self.synthesis_steps, 1):
            lines.append(f"  {i}. {step}")
        
        lines.append("")
        lines.append(f"Processing Time: {self.processing_time_ms:.2f}ms")
        
        return "\n".join(lines)


class SignalProvenanceTracker:
    """Tracks signal synthesis provenance"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.syntheses: List[SynthesisProvenance] = []
        self._syntheses_by_id: Dict[str, SynthesisProvenance] = {}
        
        logger.info("Signal provenance tracker initialized")
    
    def start_synthesis(self) -> str:
        """Start tracking a new synthesis"""
        synthesis_id = str(uuid.uuid4())
        return synthesis_id
    
    def record_synthesis(self, provenance: SynthesisProvenance) -> None:
        """Record a completed synthesis"""
        self.syntheses.append(provenance)
        self._syntheses_by_id[provenance.synthesis_id] = provenance
        
        # Trim history
        if len(self.syntheses) > self.max_history:
            oldest = self.syntheses.pop(0)
            if oldest.synthesis_id in self._syntheses_by_id:
                del self._syntheses_by_id[oldest.synthesis_id]
        
        logger.debug(
            f"Recorded synthesis: {provenance.synthesis_id} -> {provenance.final_signal} "
            f"(confidence: {provenance.final_confidence:.2f}, inputs: {len(provenance.input_signals)})"
        )
    
    def get_synthesis(self, synthesis_id: str) -> Optional[SynthesisProvenance]:
        """Get synthesis by ID"""
        return self._syntheses_by_id.get(synthesis_id)
    
    def get_recent_syntheses(self, limit: int = 50) -> List[SynthesisProvenance]:
        """Get recent syntheses"""
        return self.syntheses[-limit:]
    
    def get_synthesis_stats(self) -> Dict[str, Any]:
        """Get synthesis statistics"""
        total = len(self.syntheses)
        
        if total == 0:
            return {
                "total_syntheses": 0,
                "avg_confidence": 0.0,
                "avg_input_count": 0.0,
                "avg_processing_time_ms": 0.0
            }
        
        avg_confidence = sum(s.final_confidence for s in self.syntheses) / total
        avg_inputs = sum(len(s.input_signals) for s in self.syntheses) / total
        avg_processing = sum(s.processing_time_ms for s in self.syntheses) / total
        
        total_conflicts = sum(len(s.conflicts) for s in self.syntheses)
        
        # Count resolution methods
        resolution_methods = {}
        for s in self.syntheses:
            for conflict in s.conflicts:
                method = conflict.resolution_method.value
                resolution_methods[method] = resolution_methods.get(method, 0) + 1
        
        return {
            "total_syntheses": total,
            "avg_confidence": round(avg_confidence, 4),
            "avg_input_count": round(avg_inputs, 2),
            "avg_processing_time_ms": round(avg_processing, 2),
            "total_conflicts": total_conflicts,
            "resolution_methods": resolution_methods,
            "recent_syntheses": [s.to_dict() for s in self.syntheses[-10:]]
        }


class ProvenanceBuilder:
    """Helper to build synthesis provenance"""
    
    def __init__(self, synthesis_id: str):
        self.synthesis_id = synthesis_id
        self.start_time = time.time()
        
        self.final_signal: Optional[Any] = None
        self.final_confidence: float = 0.0
        self.input_signals: List[SourceSignal] = []
        self.conflicts: List[SignalConflict] = []
        self.weighting_formula: str = ""
        self.weight_distribution: Dict[str, float] = {}
        self.synthesis_steps: List[str] = []
    
    def add_input_signal(
        self,
        source_id: str,
        source_type: SignalSource,
        signal_value: Any,
        confidence: float,
        trust_score: float = 1.0,
        raw_data: Optional[Dict[str, Any]] = None
    ) -> 'ProvenanceBuilder':
        """Add an input signal"""
        signal = SourceSignal(
            source_id=source_id,
            source_type=source_type,
            signal_value=signal_value,
            confidence=confidence,
            timestamp=time.time(),
            raw_data=raw_data or {},
            trust_score=trust_score
        )
        self.input_signals.append(signal)
        return self
    
    def add_conflict(
        self,
        conflicting_signals: List[SourceSignal],
        resolution_method: ConflictResolution,
        resolution_reasoning: str,
        final_signal: Any
    ) -> 'ProvenanceBuilder':
        """Add a conflict resolution"""
        conflict = SignalConflict(
            conflict_id=str(uuid.uuid4()),
            conflicting_signals=conflicting_signals,
            resolution_method=resolution_method,
            resolution_reasoning=resolution_reasoning,
            final_signal=final_signal,
            timestamp=time.time()
        )
        self.conflicts.append(conflict)
        return self
    
    def set_weighting(
        self,
        formula: str,
        distribution: Dict[str, float]
    ) -> 'ProvenanceBuilder':
        """Set weighting logic"""
        self.weighting_formula = formula
        self.weight_distribution = distribution
        return self
    
    def add_step(self, step: str) -> 'ProvenanceBuilder':
        """Add a synthesis step"""
        self.synthesis_steps.append(step)
        return self
    
    def set_final_signal(
        self,
        signal: Any,
        confidence: float
    ) -> 'ProvenanceBuilder':
        """Set final synthesized signal"""
        self.final_signal = signal
        self.final_confidence = confidence
        return self
    
    def build(self) -> SynthesisProvenance:
        """Build the provenance object"""
        if self.final_signal is None:
            raise ValueError("Final signal must be set")
        
        processing_time = (time.time() - self.start_time) * 1000
        
        return SynthesisProvenance(
            synthesis_id=self.synthesis_id,
            final_signal=self.final_signal,
            final_confidence=self.final_confidence,
            timestamp=time.time(),
            input_signals=self.input_signals,
            conflicts=self.conflicts,
            weighting_formula=self.weighting_formula,
            weight_distribution=self.weight_distribution,
            synthesis_steps=self.synthesis_steps,
            processing_time_ms=processing_time
        )


# Global provenance tracker
_provenance_tracker: Optional[SignalProvenanceTracker] = None


def get_provenance_tracker() -> SignalProvenanceTracker:
    """Get global provenance tracker"""
    global _provenance_tracker
    if _provenance_tracker is None:
        _provenance_tracker = SignalProvenanceTracker()
    return _provenance_tracker


def create_provenance_builder(synthesis_id: Optional[str] = None) -> ProvenanceBuilder:
    """Create a new provenance builder"""
    if synthesis_id is None:
        synthesis_id = str(uuid.uuid4())
    return ProvenanceBuilder(synthesis_id)
