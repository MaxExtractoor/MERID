"""Gamification Swarm scaffold: scoring, quest, reward, and coach agents."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.telemetry_manager import get_telemetry_manager


@dataclass
class GamificationEvent:
    event_type: str
    payload: Dict[str, object]
    timestamp: dt.datetime = field(default_factory=dt.datetime.utcnow)


class GamificationLedger:
    """Lightweight XP and quest storage for early rollout."""

    def __init__(self) -> None:
        self._xp: Dict[str, float] = {}
        self._quests: Dict[str, Dict[str, object]] = {}

    def add_xp(self, contributor: str, amount: float, reason: str) -> None:
        self._xp[contributor] = self._xp.get(contributor, 0.0) + amount
        self._quests.setdefault(contributor, {})  # ensure contributor entry exists

    def issue_quest(self, contributor: str, quest_payload: Dict[str, object]) -> str:
        quest_id = quest_payload.get("quest_id") or f"quest_{uuid.uuid4().hex[:8]}"
        self._quests.setdefault(contributor, {})[quest_id] = quest_payload
        return quest_id

    def complete_quest(self, contributor: str, quest_id: str) -> None:
        self._quests.get(contributor, {}).pop(quest_id, None)

    def snapshot(self) -> Dict[str, object]:
        return {"xp": dict(self._xp), "quests": {k: dict(v) for k, v in self._quests.items()}}


class GamificationSwarm:
    """Coordinates scoring, quest generation, and reward curation."""

    def __init__(self) -> None:
        self._ledger = GamificationLedger()
        self._telemetry = get_telemetry_manager()

    # ------------------------------------------------------------------
    # Scoring hooks
    # ------------------------------------------------------------------
    def record_event(self, contributor: str, event: GamificationEvent) -> None:
        """Record telemetry-backed events into the gamification ledger."""

        weights = {
            "coverage_increase": 5.0,
            "flaky_fix": 8.0,
            "incident_prevention": 15.0,
            "governance_compliance": 4.0,
        }
        xp = weights.get(event.event_type, 2.0)
        self._ledger.add_xp(contributor, xp, event.event_type)
        self._emit_telemetry("score_update", contributor, event.payload, xp)

    # ------------------------------------------------------------------
    # Quest generation hooks
    # ------------------------------------------------------------------
    def issue_quest(self, contributor: str, theme: str, objective: str, reward: float) -> str:
        quest_payload = {
            "quest_id": f"quest_{uuid.uuid4().hex[:8]}",
            "theme": theme,
            "objective": objective,
            "reward": reward,
            "status": "open",
        }
        quest_id = self._ledger.issue_quest(contributor, quest_payload)
        self._emit_telemetry("quest_issued", contributor, quest_payload, reward)
        return quest_id

    def complete_quest(self, contributor: str, quest_id: str) -> None:
        self._ledger.complete_quest(contributor, quest_id)
        self._ledger.add_xp(contributor, 10.0, "quest_completion")
        self._emit_telemetry("quest_completed", contributor, {"quest_id": quest_id}, 10.0)

    # ------------------------------------------------------------------
    # Reward summaries
    # ------------------------------------------------------------------
    def generate_weekly_report(self) -> Dict[str, object]:
        snapshot = self._ledger.snapshot()
        self._emit_telemetry("weekly_report", "swarm", snapshot, 0.0)
        return snapshot

    # ------------------------------------------------------------------
    def _emit_telemetry(
        self,
        event_type: str,
        contributor: str,
        payload: Dict[str, object],
        score_delta: float,
    ) -> None:
        if not self._telemetry:
            return
        fields = {
            "contributor": contributor,
            "score_delta": score_delta,
            **{f"payload.{k}": v for k, v in payload.items()},
        }
        self._telemetry.log_structured(
            stream_name="gamification",
            level="INFO",
            event_type=event_type,
            message=f"Gamification event {event_type}",
            fields=fields,
        )


def get_gamification_swarm() -> GamificationSwarm:
    return GamificationSwarm()
