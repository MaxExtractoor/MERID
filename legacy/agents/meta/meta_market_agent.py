"""
Meta-market agent that monitors competitive landscape and strategy overlap.

Aggregates public signals about competitor releases, liquidity shifts, and
macro narratives so the moat + risk layers can adjust exposures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from utils.logger import get_logger
import threading


logger = get_logger(__name__)


@dataclass
class CompetitiveEvent:
    event_id: str
    competitor: str
    description: str
    severity: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, object] = field(default_factory=dict)


class MetaMarketAgent:
    def __init__(self) -> None:
        self._events: List[CompetitiveEvent] = []

    def record_event(
        self,
        event_id: str,
        competitor: str,
        description: str,
        severity: str,
        metadata: Dict[str, object] | None = None,
    ) -> CompetitiveEvent:
        event = CompetitiveEvent(
            event_id=event_id,
            competitor=competitor,
            description=description,
            severity=severity,
            metadata=metadata or {},
        )
        self._events.append(event)
        logger.info("Meta-market event %s severity=%s", event_id, severity)
        return event

    def get_events(self, limit: int = 50) -> List[CompetitiveEvent]:
        return list(self._events[-limit:])


_meta_market_agent: Optional[MetaMarketAgent] = None
_meta_market_agent_lock = threading.Lock()


def get_meta_market_agent() -> MetaMarketAgent:
    global _meta_market_agent
    if _meta_market_agent is None:
        with _meta_market_agent_lock:
            if _meta_market_agent is None:
                _meta_market_agent = MetaMarketAgent()
    return _meta_market_agent
