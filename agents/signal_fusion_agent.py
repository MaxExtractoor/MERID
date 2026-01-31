"""
External signal fusion agent for orderflow/on-chain/news/social ingestion.

Aggregates heterogeneous feeds, normalizes them, and emits fused insights
through event stream hooks. Designed as a standalone agent so Phase 9 can
extend instrumentation without touching core trading logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Callable
import logging


logger = logging.getLogger(__name__)


@dataclass
class ExternalSignal:
    source: str
    payload: Dict[str, object]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SignalFusionAgent:
    def __init__(self) -> None:
        self._subscribers: List[Callable[[Dict[str, object]], None]] = []
        self._history: List[Dict[str, object]] = []

    def subscribe(self, handler: Callable[[Dict[str, object]], None]) -> None:
        self._subscribers.append(handler)

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


def get_signal_fusion_agent() -> SignalFusionAgent:
    global _signal_fusion_agent
    if _signal_fusion_agent is None:
        _signal_fusion_agent = SignalFusionAgent()
    return _signal_fusion_agent
