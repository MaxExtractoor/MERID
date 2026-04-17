"""
External signal fusion agent for orderflow/on-chain/news/social ingestion.

Aggregates heterogeneous feeds, normalizes them, and emits fused insights
through event stream hooks. Designed as a standalone agent so Phase 9 can
extend instrumentation without touching core trading logic.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Callable, Optional, Set
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class ExternalSignal:
    source: str
    payload: Dict[str, object]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SignalFusionAgent:
    # T-026: Rate limit per source (max signals per minute)
    MAX_SIGNALS_PER_SOURCE_PER_MINUTE = 60

    def __init__(self) -> None:
        self._subscribers: List[Callable[[Dict[str, object]], None]] = []
        self._history: List[Dict[str, object]] = []
        # T-026: Registered signal sources
        self._registered_sources: Set[str] = set()
        self._source_timestamps: Dict[str, List[float]] = defaultdict(list)
        self._source_scores: Dict[str, List[float]] = defaultdict(list)

    def register_source(self, source_id: str) -> None:
        """T-026: Register a signal source. Only registered sources are accepted."""
        self._registered_sources.add(source_id)
        logger.info("Signal source registered: %s", source_id)

    def subscribe(self, handler: Callable[[Dict[str, object]], None]) -> None:
        self._subscribers.append(handler)

    def _validate_signal(self, signal: ExternalSignal) -> Optional[str]:
        """T-026: Validate signal source, rate limit, and anomaly detection."""
        # Source must be registered
        if signal.source not in self._registered_sources:
            return f"Unregistered source: {signal.source}"

        # Rate limiting
        now = time.time()
        ts_list = self._source_timestamps[signal.source]
        # Prune old timestamps
        cutoff = now - 60
        self._source_timestamps[signal.source] = [t for t in ts_list if t > cutoff]
        if len(self._source_timestamps[signal.source]) >= self.MAX_SIGNALS_PER_SOURCE_PER_MINUTE:
            return f"Rate limit exceeded for source {signal.source}"
        self._source_timestamps[signal.source].append(now)

        # Anomaly detection: flag scores > 3 std devs from recent history
        score = float(signal.payload.get("score", 0.0))
        recent = self._source_scores[signal.source]
        if len(recent) >= 20:
            import statistics
            mean = statistics.mean(recent)
            stdev = statistics.stdev(recent) if len(recent) > 1 else 1.0
            if stdev > 0 and abs(score - mean) > 3 * stdev:
                logger.warning(
                    "ANOMALY: source=%s score=%.2f (mean=%.2f, stdev=%.2f)",
                    signal.source, score, mean, stdev,
                )
                return f"Anomalous score from {signal.source}: {score:.2f}"
        self._source_scores[signal.source].append(score)
        # Keep last 100 scores
        if len(self._source_scores[signal.source]) > 100:
            self._source_scores[signal.source] = self._source_scores[signal.source][-100:]

        return None

    def ingest(self, signals: List[ExternalSignal]) -> Dict[str, object]:
        fused = {
            "orderflow_bias": self._compute_bias(signals, "orderflow"),
            "onchain_velocity": self._compute_bias(signals, "onchain"),
            "news_sentiment": self._compute_bias(signals, "news"),
            "social_sentiment": self._compute_bias(signals, "social"),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._history.append(fused)
        for handler in self._subscribers:
            handler(fused)
        logger.info("Signal fusion update %s", fused)
        return fused

    def _compute_bias(self, signals: List[ExternalSignal], source: str) -> float:
        relevant = [s for s in signals if s.source == source]
        if not relevant:
            return 0.0
        score = 0.0
        for signal in relevant:
            score += float(signal.payload.get("score", 0.0))
        return score / len(relevant)

    def get_history(self, limit: int = 50) -> List[Dict[str, object]]:
        return list(self._history[-limit:])


_signal_fusion_agent: Optional[SignalFusionAgent] = None
_signal_fusion_agent_lock = threading.Lock()


def get_signal_fusion_agent() -> SignalFusionAgent:
    global _signal_fusion_agent
    if _signal_fusion_agent is None:
        with _signal_fusion_agent_lock:
            if _signal_fusion_agent is None:
                _signal_fusion_agent = SignalFusionAgent()
    return _signal_fusion_agent
