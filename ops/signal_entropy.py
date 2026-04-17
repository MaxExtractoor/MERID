"""
MERID-OPS Signal Entropy Tracking

Detects when signals become too correlated (echo chambers) or too noisy.
Healthy signal entropy indicates diverse, independent information sources.

Low entropy = echo chamber (all signals agree too much)
High entropy = noise (signals are random/contradictory)
Optimal entropy = diverse but coherent signals
"""

from __future__ import annotations

import threading
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("ops.signal_entropy")


@dataclass
class Signal:
    """A signal from the intelligence layer."""
    signal_id: str
    signal_type: str
    source: str
    direction: str  # bullish, bearish, neutral
    strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    timestamp: float
    symbols: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntropyWindow:
    """Entropy calculation for a time window."""
    window_id: str
    start_time: float
    end_time: float
    signal_count: int
    direction_entropy: float  # Entropy of bullish/bearish/neutral
    source_entropy: float  # Entropy of signal sources
    type_entropy: float  # Entropy of signal types
    combined_entropy: float
    is_echo_chamber: bool
    is_noise: bool
    is_healthy: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_id": self.window_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "signal_count": self.signal_count,
            "direction_entropy": round(self.direction_entropy, 4),
            "source_entropy": round(self.source_entropy, 4),
            "type_entropy": round(self.type_entropy, 4),
            "combined_entropy": round(self.combined_entropy, 4),
            "is_echo_chamber": self.is_echo_chamber,
            "is_noise": self.is_noise,
            "is_healthy": self.is_healthy,
        }


class SignalEntropyTracker:
    """
    Tracks signal entropy to detect overfitting and echo chambers.
    
    Uses Shannon entropy to measure signal diversity:
    H = -Σ p(x) * log2(p(x))
    
    Thresholds:
    - Echo chamber: entropy < 0.3 (too much agreement)
    - Noise: entropy > 0.9 (too much disagreement)
    - Healthy: 0.3 <= entropy <= 0.9
    """
    
    ECHO_CHAMBER_THRESHOLD = 0.3
    NOISE_THRESHOLD = 0.9
    
    def __init__(self, window_seconds: float = 300):
        self._signals: List[Signal] = []
        self._max_signals = 5000
        self._window_seconds = window_seconds
        self._entropy_history: List[EntropyWindow] = []
        self._max_history = 1000
        
        logger.info("Signal entropy tracker initialized (window: %ds)", window_seconds)
    
    def record_signal(
        self,
        signal_type: str,
        source: str,
        direction: str,
        strength: float,
        confidence: float,
        symbols: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Signal:
        """Record a new signal."""
        signal = Signal(
            signal_id=f"sig_{int(time.time() * 1000)}_{len(self._signals)}",
            signal_type=signal_type,
            source=source,
            direction=direction,
            strength=min(1.0, max(0.0, strength)),
            confidence=min(1.0, max(0.0, confidence)),
            timestamp=time.time(),
            symbols=symbols or [],
            metadata=metadata or {},
        )
        
        self._signals.append(signal)
        
        # Cleanup old signals
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals:]
        
        return signal
    
    def _calculate_entropy(self, values: List[str]) -> float:
        """Calculate Shannon entropy for a list of categorical values."""
        if not values:
            return 0.0
        
        # Count occurrences
        counts = defaultdict(int)
        for v in values:
            counts[v] += 1
        
        # Calculate probabilities
        total = len(values)
        probabilities = [count / total for count in counts.values()]
        
        # Calculate entropy
        entropy = 0.0
        for p in probabilities:
            if p > 0:
                entropy -= p * math.log2(p)
        
        # Normalize to 0-1 range based on max possible entropy
        max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
        normalized = entropy / max_entropy if max_entropy > 0 else 0.0
        
        return normalized
    
    def calculate_current_entropy(self) -> EntropyWindow:
        """Calculate entropy for the current time window."""
        cutoff = time.time() - self._window_seconds
        recent = [s for s in self._signals if s.timestamp > cutoff]
        
        if not recent:
            return EntropyWindow(
                window_id=f"win_{int(time.time())}",
                start_time=cutoff,
                end_time=time.time(),
                signal_count=0,
                direction_entropy=0.5,
                source_entropy=0.5,
                type_entropy=0.5,
                combined_entropy=0.5,
                is_echo_chamber=False,
                is_noise=False,
                is_healthy=True,
            )
        
        # Calculate entropies
        direction_entropy = self._calculate_entropy([s.direction for s in recent])
        source_entropy = self._calculate_entropy([s.source for s in recent])
        type_entropy = self._calculate_entropy([s.signal_type for s in recent])
        
        # Combined entropy (weighted average)
        combined = 0.5 * direction_entropy + 0.3 * source_entropy + 0.2 * type_entropy
        
        # Classify
        is_echo_chamber = combined < self.ECHO_CHAMBER_THRESHOLD
        is_noise = combined > self.NOISE_THRESHOLD
        is_healthy = not is_echo_chamber and not is_noise
        
        window = EntropyWindow(
            window_id=f"win_{int(time.time())}",
            start_time=cutoff,
            end_time=time.time(),
            signal_count=len(recent),
            direction_entropy=direction_entropy,
            source_entropy=source_entropy,
            type_entropy=type_entropy,
            combined_entropy=combined,
            is_echo_chamber=is_echo_chamber,
            is_noise=is_noise,
            is_healthy=is_healthy,
        )
        
        # Store in history
        self._entropy_history.append(window)
        if len(self._entropy_history) > self._max_history:
            self._entropy_history = self._entropy_history[-self._max_history:]
        
        # Log warnings
        if is_echo_chamber:
            logger.warning(
                "ECHO CHAMBER DETECTED: entropy %.3f < %.3f (signals too correlated)",
                combined, self.ECHO_CHAMBER_THRESHOLD
            )
        elif is_noise:
            logger.warning(
                "NOISE DETECTED: entropy %.3f > %.3f (signals too random)",
                combined, self.NOISE_THRESHOLD
            )
        
        return window
    
    def get_direction_consensus(self) -> Dict[str, Any]:
        """Get consensus on signal direction."""
        cutoff = time.time() - self._window_seconds
        recent = [s for s in self._signals if s.timestamp > cutoff]
        
        if not recent:
            return {"consensus": "neutral", "confidence": 0.0, "signal_count": 0}
        
        # Weight by confidence
        direction_weights = defaultdict(float)
        for s in recent:
            direction_weights[s.direction] += s.confidence * s.strength
        
        total_weight = sum(direction_weights.values())
        if total_weight == 0:
            return {"consensus": "neutral", "confidence": 0.0, "signal_count": len(recent)}
        
        # Find dominant direction
        dominant = max(direction_weights.items(), key=lambda x: x[1])
        confidence = dominant[1] / total_weight
        
        return {
            "consensus": dominant[0],
            "confidence": round(confidence, 3),
            "signal_count": len(recent),
            "weights": {k: round(v / total_weight, 3) for k, v in direction_weights.items()},
        }
    
    def get_source_diversity(self) -> Dict[str, Any]:
        """Get diversity of signal sources."""
        cutoff = time.time() - self._window_seconds
        recent = [s for s in self._signals if s.timestamp > cutoff]
        
        if not recent:
            return {"unique_sources": 0, "diversity_score": 0.0}
        
        sources = set(s.source for s in recent)
        source_counts = defaultdict(int)
        for s in recent:
            source_counts[s.source] += 1
        
        return {
            "unique_sources": len(sources),
            "diversity_score": self._calculate_entropy([s.source for s in recent]),
            "source_distribution": dict(source_counts),
        }
    
    def detect_echo_chamber(self) -> Tuple[bool, Optional[str]]:
        """
        Detect if we're in an echo chamber.
        
        Returns (is_echo_chamber, reason).
        """
        window = self.calculate_current_entropy()
        
        if window.is_echo_chamber:
            if window.direction_entropy < 0.2:
                return True, "All signals pointing same direction"
            if window.source_entropy < 0.2:
                return True, "Signals from too few sources"
            return True, "Signal diversity too low"
        
        return False, None
    
    def get_entropy_trend(self, periods: int = 10) -> Dict[str, Any]:
        """Get entropy trend over recent periods."""
        if len(self._entropy_history) < 2:
            return {"trend": "stable", "change": 0.0}
        
        recent = self._entropy_history[-periods:]
        if len(recent) < 2:
            return {"trend": "stable", "change": 0.0}
        
        # Calculate trend
        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]
        
        avg_first = sum(w.combined_entropy for w in first_half) / len(first_half)
        avg_second = sum(w.combined_entropy for w in second_half) / len(second_half)
        
        change = avg_second - avg_first
        
        if change > 0.1:
            trend = "increasing"
        elif change < -0.1:
            trend = "decreasing"
        else:
            trend = "stable"
        
        return {
            "trend": trend,
            "change": round(change, 4),
            "current": round(avg_second, 4),
            "previous": round(avg_first, 4),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get tracker status."""
        window = self.calculate_current_entropy()
        consensus = self.get_direction_consensus()
        diversity = self.get_source_diversity()
        trend = self.get_entropy_trend()
        
        return {
            "current_window": window.to_dict(),
            "consensus": consensus,
            "source_diversity": diversity,
            "entropy_trend": trend,
            "total_signals": len(self._signals),
            "history_length": len(self._entropy_history),
        }
    
    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent signals."""
        return [
            {
                "signal_id": s.signal_id,
                "signal_type": s.signal_type,
                "source": s.source,
                "direction": s.direction,
                "strength": s.strength,
                "confidence": s.confidence,
                "timestamp": s.timestamp,
                "symbols": s.symbols,
            }
            for s in self._signals[-limit:]
        ]


# Singleton
_entropy_tracker: Optional[SignalEntropyTracker] = None
_entropy_tracker_lock = threading.Lock()


def get_entropy_tracker() -> SignalEntropyTracker:
    """Get the singleton entropy tracker."""
    global _entropy_tracker
    if _entropy_tracker is None:
        with _entropy_tracker_lock:
            if _entropy_tracker is None:
                _entropy_tracker = SignalEntropyTracker()
    return _entropy_tracker
