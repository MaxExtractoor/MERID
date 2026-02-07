"""
Advanced behavioral profiling for agents/users.

Maintains rolling profiles of typical actions, enabling anomaly scores when
behavior deviates from historical patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class BehaviorEvent:
    actor_id: str
    action_type: str
    metadata: Dict[str, str]
    timestamp: datetime


@dataclass
class BehaviorProfile:
    actor_id: str
    action_frequencies: Dict[str, int]
    last_updated: datetime


class BehavioralProfiler:
    def __init__(self) -> None:
        self._profiles: Dict[str, BehaviorProfile] = {}

    def record_event(self, event: BehaviorEvent) -> None:
        profile = self._profiles.setdefault(
            event.actor_id, BehaviorProfile(actor_id=event.actor_id, action_frequencies={}, last_updated=datetime.utcnow())
        )
        profile.action_frequencies[event.action_type] = profile.action_frequencies.get(event.action_type, 0) + 1
        profile.last_updated = datetime.utcnow()

    def anomaly_score(self, actor_id: str, action_type: str) -> float:
        profile = self._profiles.get(actor_id)
        if not profile:
            return 0.0
        total = sum(profile.action_frequencies.values()) or 1
        freq = profile.action_frequencies.get(action_type, 0)
        expected_ratio = freq / total
        return max(0.0, 1.0 - expected_ratio)
