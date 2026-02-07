"""
Real-time threat intelligence feed ingestion scaffolding.

Maintains subscriptions to multiple intel sources, normalizes alerts, and
publishes them into the security event bus so governance + defense systems can
react quickly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Callable


@dataclass
class ThreatAlert:
    alert_id: str
    source: str
    severity: str
    summary: str
    indicators: Dict[str, str]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ThreatIntelligenceFeed:
    def __init__(self) -> None:
        self._subscribers: List[Callable[[ThreatAlert], None]] = []
        self._history: List[ThreatAlert] = []

    def subscribe(self, handler: Callable[[ThreatAlert], None]) -> None:
        self._subscribers.append(handler)

    def ingest(self, alert: ThreatAlert) -> None:
        self._history.append(alert)
        for handler in self._subscribers:
            handler(alert)

    def recent_alerts(self, limit: int = 20) -> List[ThreatAlert]:
        return self._history[-limit:]
