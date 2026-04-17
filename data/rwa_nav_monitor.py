"""
RWA NAV monitoring and alerts.

Tracks net asset value per real-world asset vault and emits warnings when NAV
deviates from expected ranges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class RWANavSnapshot:
    vault_id: str
    nav_usd: float
    expected_nav_usd: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def deviation(self) -> float:
        if self.expected_nav_usd == 0:
            return 0.0
        return (self.nav_usd - self.expected_nav_usd) / self.expected_nav_usd


class RWANavMonitor:
    def __init__(self, alert_threshold: float = 0.05) -> None:
        self.alert_threshold = alert_threshold
        self._snapshots: Dict[str, List[RWANavSnapshot]] = {}

    def record_nav(self, vault_id: str, nav_usd: float, expected_nav_usd: float) -> RWANavSnapshot:
        snapshot = RWANavSnapshot(vault_id=vault_id, nav_usd=nav_usd, expected_nav_usd=expected_nav_usd)
        history = self._snapshots.setdefault(vault_id, [])
        history.append(snapshot)
        if abs(snapshot.deviation) >= self.alert_threshold:
            logger.warning("RWA NAV alert %s deviation %.2f%%", vault_id, snapshot.deviation * 100)
        return snapshot

    def get_history(self, vault_id: str, limit: int = 50) -> List[RWANavSnapshot]:
        history = self._snapshots.get(vault_id, [])
        return history[-limit:]
