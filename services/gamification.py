"""Lightweight gamification engine for MERID dashboards."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List

from utils.logger import get_logger

logger = get_logger("services.gamification")


@dataclass
class XpEvent:
    user: str
    xp: int
    reason: str
    timestamp: float
    metadata: Dict[str, str]


class GamificationEngine:
    """Tracks user XP, levels, and achievement history."""

    def __init__(self, base_xp: int = 50) -> None:
        self.base_xp = base_xp
        self._xp: Dict[str, int] = {}
        self._events: List[XpEvent] = []

    def award_xp(self, user: str, multiplier: float, reason: str, metadata: Dict[str, str] | None = None) -> int:
        xp_gain = max(1, int(self.base_xp * multiplier))
        self._xp[user] = self._xp.get(user, 0) + xp_gain
        event = XpEvent(user=user, xp=xp_gain, reason=reason, timestamp=time.time(), metadata=metadata or {})
        self._events.append(event)
        logger.debug("Awarded %s XP to %s for %s", xp_gain, user, reason)
        return xp_gain

    def leaderboard(self, limit: int = 20) -> List[Dict[str, int]]:
        sorted_users = sorted(self._xp.items(), key=lambda item: item[1], reverse=True)
        return [{"user": user, "xp": xp} for user, xp in sorted_users[:limit]]

    def events(self, limit: int = 50) -> List[Dict[str, str]]:
        return self.events_for(None, limit=limit)

    def xp_for(self, user: str) -> int:
        return self._xp.get(user, 0)

    def events_for(self, user: str | None, limit: int = 50) -> List[Dict[str, str]]:
        records = self._events if user is None else [evt for evt in self._events if evt.user == user]
        return [
            {
                "user": event.user,
                "xp": event.xp,
                "reason": event.reason,
                "timestamp": event.timestamp,
                "metadata": event.metadata,
            }
            for event in records[-limit:]
        ]
