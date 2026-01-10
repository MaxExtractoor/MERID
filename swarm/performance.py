from __future__ import annotations

# Stage 3 Swarm Evolution: performance ledger with decay-weighted scoring.

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

from core.time_authority import current_time

LOG_PATH = Path("logs/swarm_performance.json")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _coerce_dt(value: str) -> datetime:
    try:
        if value.endswith("Z"):
            value = value[:-1]
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.utcnow()


@dataclass
class AgentPerformance:
    agent_id: str
    accuracy_window: Deque[int] = field(default_factory=lambda: deque(maxlen=50))
    total_votes: int = 0
    correct_votes: int = 0
    incorrect_votes: int = 0
    last_active: str = ""
    streak: int = 0
    decay_weight: float = 1.0

    def base_accuracy(self) -> float:
        if not self.total_votes:
            return 0.0
        return self.correct_votes / self.total_votes

    def rolling_accuracy(self) -> float:
        if not self.accuracy_window:
            return self.base_accuracy()
        return sum(self.accuracy_window) / len(self.accuracy_window)

    def score(self) -> float:
        base = self.base_accuracy()
        rolling = self.rolling_accuracy()
        streak_factor = 1.0 + (self.streak * 0.02)
        return (0.6 * rolling + 0.4 * base) * self.decay_weight * streak_factor

    def to_dict(self) -> Dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "accuracy_window": list(self.accuracy_window),
            "total_votes": self.total_votes,
            "correct_votes": self.correct_votes,
            "incorrect_votes": self.incorrect_votes,
            "last_active": self.last_active,
            "streak": self.streak,
            "decay_weight": self.decay_weight,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> AgentPerformance:
        record = cls(agent_id=payload["agent_id"])
        record.accuracy_window.extend(payload.get("accuracy_window", []))
        record.total_votes = int(payload.get("total_votes", 0))
        record.correct_votes = int(payload.get("correct_votes", 0))
        record.incorrect_votes = int(payload.get("incorrect_votes", 0))
        record.last_active = payload.get("last_active", "") or ""
        record.streak = int(payload.get("streak", 0))
        record.decay_weight = float(payload.get("decay_weight", 1.0))
        return record


class SwarmPerformanceLedger:
    """Tracks agent accuracy, decay, and leaderboard state for spawning decisions."""

    def __init__(
        self,
        *,
        decay_window_hours: int = 6,
        decay_rate: float = 0.92,
        min_decay_weight: float = 0.25,
    ) -> None:
        self._decay_window_hours = decay_window_hours
        self._decay_rate = decay_rate
        self._min_decay_weight = min_decay_weight
        self._agents: Dict[str, AgentPerformance] = {}
        self._lock = threading.Lock()
        self._load()

    def record_cycle(self, votes: List[Dict[str, object]], approved: bool) -> None:
        now = current_time()["utc_iso"]
        with self._lock:
            for vote in votes:
                agent_id = vote.get("agent_id")
                if not agent_id:
                    continue
                entry = self._agents.setdefault(agent_id, AgentPerformance(agent_id=agent_id))
                self._apply_decay(entry, now)
                entry.total_votes += 1
                decision = str(vote.get("vote", "abstain")).lower()
                correct = (decision == "accept" and approved) or (decision == "reject" and not approved)
                if correct:
                    entry.correct_votes += 1
                    entry.streak = entry.streak + 1 if entry.streak >= 0 else 1
                    entry.accuracy_window.append(1)
                elif decision != "abstain":
                    entry.incorrect_votes += 1
                    entry.streak = -1
                    entry.accuracy_window.append(0)
                else:
                    entry.streak = 0
                    entry.accuracy_window.append(0)
                entry.last_active = now
            self._persist()

    def leaderboard(self, limit: int = 10) -> List[Dict[str, object]]:
        with self._lock:
            rows = [
                {
                    "agent_id": entry.agent_id,
                    "score": round(entry.score(), 4),
                    "accuracy": round(entry.base_accuracy(), 4),
                    "rolling_accuracy": round(entry.rolling_accuracy(), 4),
                    "votes": entry.total_votes,
                    "streak": entry.streak,
                    "last_active": entry.last_active,
                    "decay_weight": round(entry.decay_weight, 4),
                }
                for entry in self._agents.values()
            ]
        return sorted(rows, key=lambda row: row["score"], reverse=True)[:limit]

    def best_parent(self, *, min_score: float = 0.55, min_votes: int = 5) -> Optional[Dict[str, object]]:
        for record in self.leaderboard(limit=20):
            if record["score"] >= min_score and record["votes"] >= min_votes:
                return record
        return None

    def _apply_decay(self, entry: AgentPerformance, now_iso: str) -> None:
        if not entry.last_active:
            return
        last = _coerce_dt(entry.last_active)
        now = _coerce_dt(now_iso)
        hours = max((now - last).total_seconds() / 3600.0, 0.0)
        if hours < self._decay_window_hours:
            return
        steps = int(hours // self._decay_window_hours)
        entry.decay_weight *= self._decay_rate ** steps
        if entry.decay_weight < self._min_decay_weight:
            entry.decay_weight = self._min_decay_weight

    def _persist(self) -> None:
        payload = {agent_id: entry.to_dict() for agent_id, entry in self._agents.items()}
        LOG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not LOG_PATH.exists():
            return
        try:
            data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for agent_id, payload in data.items():
            payload["agent_id"] = agent_id
            self._agents[agent_id] = AgentPerformance.from_dict(payload)


performance_ledger = SwarmPerformanceLedger()
