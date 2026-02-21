"""Quests & Challenges — time-bound objectives with reward multipliers.

Quests are composable, theme-bound tasks that encourage experimentation
in new venues, strategies, and debugging tools.  They prevent stagnation
by creating cycles of renewal.

Examples:
  - "Regime Shift Week": improve calibration on 5 instruments during a regime change
  - "Fed Cycle Challenge": best Brier on macro instruments during FOMC week
  - "Debug Three Mispriced Markets": find and correct 3 markets with >10% edge
  - "Reduce Alert Noise by 20%": cut firing alerts this month

Quests define:
  - Objective criteria (what events count, what thresholds apply)
  - Time bounds (start/end)
  - Reward multiplier (bonus on top of normal mechanism rewards)
  - Completion conditions
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from merid.rewards.events import RewardEvent, EventCategory
from utils.logger import get_logger

logger = get_logger("merid.rewards.quests")


class QuestStatus(str, Enum):
    """Quest lifecycle states."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class QuestObjective:
    """A single measurable objective within a quest."""
    id: str = field(default_factory=lambda: f"qobj-{uuid.uuid4().hex[:8]}")
    description: str = ""
    target_category: str = ""            # EventCategory to match
    target_venue: str = ""               # optional venue filter
    metric: str = ""                     # what to measure (e.g. "event_count", "total_lift")
    threshold: float = 0.0               # value to reach
    current_value: float = 0.0           # progress so far
    completed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "target_category": self.target_category,
            "metric": self.metric,
            "threshold": self.threshold,
            "current_value": round(self.current_value, 2),
            "completed": self.completed,
            "progress_pct": round(
                min(self.current_value / self.threshold * 100, 100.0)
                if self.threshold > 0 else 0.0, 1
            ),
        }


@dataclass
class Quest:
    """A time-bound challenge with objectives and reward multiplier."""
    id: str = field(default_factory=lambda: f"quest-{uuid.uuid4().hex[:10]}")
    name: str = ""
    description: str = ""
    status: str = QuestStatus.DRAFT.value
    creator_id: str = ""                 # who created this quest
    venue: str = ""                      # optional venue scope
    reward_multiplier: float = 1.5       # bonus multiplier on normal rewards
    objectives: List[QuestObjective] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)  # agent_ids
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    tags: List[str] = field(default_factory=list)  # e.g. ["regime_shift", "macro"]

    def is_active(self) -> bool:
        if self.status != QuestStatus.ACTIVE.value:
            return False
        now = time.time()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True

    def is_expired(self) -> bool:
        if self.end_time and time.time() > self.end_time:
            return True
        return False

    def all_objectives_complete(self) -> bool:
        return all(obj.completed for obj in self.objectives) if self.objectives else False

    def progress_pct(self) -> float:
        if not self.objectives:
            return 0.0
        completed = sum(1 for o in self.objectives if o.completed)
        return round(completed / len(self.objectives) * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "creator_id": self.creator_id,
            "venue": self.venue,
            "reward_multiplier": self.reward_multiplier,
            "objectives": [o.to_dict() for o in self.objectives],
            "participants": self.participants,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "progress_pct": self.progress_pct(),
            "tags": self.tags,
        }


# ── Quest templates (built-in challenges) ─────────────────────────────

def create_regime_shift_quest(
    start_time: Optional[float] = None,
    duration_days: float = 7.0,
) -> Quest:
    """Create a 'Regime Shift Week' quest."""
    start = start_time or time.time()
    return Quest(
        name="Regime Shift Week",
        description="Improve calibration on 5 instruments during a regime change",
        status=QuestStatus.ACTIVE.value,
        reward_multiplier=2.0,
        objectives=[
            QuestObjective(
                description="Submit forecasts on 5 different instruments",
                target_category=EventCategory.FORECAST.value,
                metric="event_count",
                threshold=5.0,
            ),
            QuestObjective(
                description="Achieve positive Brier improvement on at least 3",
                target_category=EventCategory.FORECAST.value,
                metric="improvement_count",
                threshold=3.0,
            ),
            QuestObjective(
                description="Update at least 1 hypothesis after contradiction",
                target_category=EventCategory.COGNITIVE.value,
                metric="contradiction_update_count",
                threshold=1.0,
            ),
        ],
        start_time=start,
        end_time=start + duration_days * 86400,
        tags=["regime_shift", "calibration"],
    )


def create_alert_reduction_quest(
    target_reduction: int = 3,
    duration_days: float = 30.0,
) -> Quest:
    """Create a 'Reduce Alert Noise' quest."""
    start = time.time()
    return Quest(
        name="Reduce Alert Noise",
        description=f"Reduce firing alerts by {target_reduction} this month",
        status=QuestStatus.ACTIVE.value,
        venue="infra",
        reward_multiplier=1.5,
        objectives=[
            QuestObjective(
                description=f"Reduce {target_reduction} alerts",
                target_category=EventCategory.CODE_QUALITY.value,
                metric="alerts_reduced_total",
                threshold=float(target_reduction),
            ),
        ],
        start_time=start,
        end_time=start + duration_days * 86400,
        tags=["reliability", "observability"],
    )


def create_debate_mastery_quest(duration_days: float = 14.0) -> Quest:
    """Create a 'Debate Mastery' quest."""
    start = time.time()
    return Quest(
        name="Debate Mastery",
        description="Participate in 10 debates with positive lift",
        status=QuestStatus.ACTIVE.value,
        reward_multiplier=1.75,
        objectives=[
            QuestObjective(
                description="Participate in 10 debates",
                target_category=EventCategory.DEBATE.value,
                metric="event_count",
                threshold=10.0,
            ),
            QuestObjective(
                description="Achieve positive debate lift in at least 7",
                target_category=EventCategory.DEBATE.value,
                metric="positive_lift_count",
                threshold=7.0,
            ),
        ],
        start_time=start,
        end_time=start + duration_days * 86400,
        tags=["debate", "accuracy"],
    )


# ── Quest store ───────────────────────────────────────────────────────

class QuestStore:
    """In-memory quest store with evaluation logic.

    Quests are lightweight enough to keep in memory.  For persistence,
    the RewardEngine DB can be extended later.
    """

    def __init__(self) -> None:
        self._quests: Dict[str, Quest] = {}

    def add_quest(self, quest: Quest) -> Quest:
        self._quests[quest.id] = quest
        return quest

    def get_quest(self, quest_id: str) -> Optional[Quest]:
        return self._quests.get(quest_id)

    def list_quests(
        self,
        status: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Quest]:
        quests = list(self._quests.values())
        if status:
            quests = [q for q in quests if q.status == status]
        if tag:
            quests = [q for q in quests if tag in q.tags]
        return quests

    def join_quest(self, quest_id: str, agent_id: str) -> bool:
        quest = self._quests.get(quest_id)
        if not quest or not quest.is_active():
            return False
        if agent_id not in quest.participants:
            quest.participants.append(agent_id)
        return True

    def update_quest_progress(
        self, quest_id: str, event: RewardEvent,
    ) -> Optional[Quest]:
        """Update quest objectives based on an incoming event.

        Returns the quest if progress was made, None otherwise.
        """
        quest = self._quests.get(quest_id)
        if not quest or not quest.is_active():
            return None

        # Check if agent is a participant
        if event.agent_id not in quest.participants:
            return None

        progress_made = False
        for obj in quest.objectives:
            if obj.completed:
                continue

            # Match category
            if obj.target_category and obj.target_category != event.category:
                continue

            # Match venue
            if obj.target_venue and obj.target_venue != event.venue:
                continue

            # Update metric based on type
            if obj.metric == "event_count":
                obj.current_value += 1.0
                progress_made = True
            elif obj.metric == "improvement_count":
                prior = getattr(event, "prior_brier", None)
                brier = getattr(event, "brier_score", None)
                if prior is not None and brier is not None and brier < prior:
                    obj.current_value += 1.0
                    progress_made = True
            elif obj.metric == "contradiction_update_count":
                if getattr(event, "was_contradicted", False):
                    obj.current_value += 1.0
                    progress_made = True
            elif obj.metric == "positive_lift_count":
                lift = getattr(event, "debate_lift", None) or getattr(event, "design_lift", None)
                if lift is not None and lift > 0:
                    obj.current_value += 1.0
                    progress_made = True
            elif obj.metric == "alerts_reduced_total":
                reduced = getattr(event, "alerts_reduced", 0)
                if reduced > 0:
                    obj.current_value += reduced
                    progress_made = True

            # Check completion
            if obj.current_value >= obj.threshold:
                obj.completed = True

        # Check if all objectives are complete
        if quest.all_objectives_complete() and quest.status == QuestStatus.ACTIVE.value:
            quest.status = QuestStatus.COMPLETED.value
            quest.completed_at = time.time()
            logger.info("Quest %s (%s) completed!", quest.id, quest.name)

        return quest if progress_made else None

    def expire_quests(self) -> List[Quest]:
        """Mark expired quests. Call periodically."""
        expired: List[Quest] = []
        for quest in self._quests.values():
            if quest.status == QuestStatus.ACTIVE.value and quest.is_expired():
                quest.status = QuestStatus.EXPIRED.value
                expired.append(quest)
        return expired

    def get_agent_quests(self, agent_id: str) -> List[Quest]:
        """Get all quests an agent is participating in."""
        return [
            q for q in self._quests.values()
            if agent_id in q.participants
        ]

    def get_quest_metrics(self) -> Dict[str, Any]:
        """Get quest system metrics."""
        quests = list(self._quests.values())
        return {
            "total_quests": len(quests),
            "active": sum(1 for q in quests if q.status == QuestStatus.ACTIVE.value),
            "completed": sum(1 for q in quests if q.status == QuestStatus.COMPLETED.value),
            "expired": sum(1 for q in quests if q.status == QuestStatus.EXPIRED.value),
            "total_participants": len(set(
                p for q in quests for p in q.participants
            )),
            "avg_progress_pct": round(
                sum(q.progress_pct() for q in quests) / len(quests), 1
            ) if quests else 0.0,
        }
