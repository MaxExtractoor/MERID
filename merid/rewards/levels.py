"""Levels & Reputation — long-term accumulation with influence weights.

Reputation is a time-decayed but non-zero-history measure of an agent's
contributions.  Higher reputation unlocks permissions and influence:
  - Whose opinions get more weight in consensus aggregation
  - Who can propose strategy changes
  - Who can approve hypothesis shifts

Levels are discrete milestones derived from cumulative reputation.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ReputationLevel(str, Enum):
    """Discrete reputation tiers with escalating thresholds."""
    NOVICE = "novice"            # 0–99 points
    CONTRIBUTOR = "contributor"  # 100–499
    EXPERT = "expert"            # 500–1999
    MASTER = "master"            # 2000–4999
    LEGEND = "legend"            # 5000+


# Thresholds for each level (minimum cumulative points)
LEVEL_THRESHOLDS: List[Tuple[ReputationLevel, float]] = [
    (ReputationLevel.LEGEND, 5000.0),
    (ReputationLevel.MASTER, 2000.0),
    (ReputationLevel.EXPERT, 500.0),
    (ReputationLevel.CONTRIBUTOR, 100.0),
    (ReputationLevel.NOVICE, 0.0),
]

# Influence weight multipliers per level (used in consensus aggregation)
LEVEL_INFLUENCE: Dict[str, float] = {
    ReputationLevel.NOVICE.value: 1.0,
    ReputationLevel.CONTRIBUTOR.value: 1.2,
    ReputationLevel.EXPERT.value: 1.5,
    ReputationLevel.MASTER.value: 1.8,
    ReputationLevel.LEGEND.value: 2.0,
}

# Permissions unlocked at each level
LEVEL_PERMISSIONS: Dict[str, List[str]] = {
    ReputationLevel.NOVICE.value: ["submit_forecast", "participate_debate"],
    ReputationLevel.CONTRIBUTOR.value: [
        "submit_forecast", "participate_debate", "create_team",
    ],
    ReputationLevel.EXPERT.value: [
        "submit_forecast", "participate_debate", "create_team",
        "propose_strategy", "create_quest",
    ],
    ReputationLevel.MASTER.value: [
        "submit_forecast", "participate_debate", "create_team",
        "propose_strategy", "create_quest", "approve_hypothesis",
        "edit_slo",
    ],
    ReputationLevel.LEGEND.value: [
        "submit_forecast", "participate_debate", "create_team",
        "propose_strategy", "create_quest", "approve_hypothesis",
        "edit_slo", "modify_reward_mechanisms",
    ],
}


def level_from_points(total_points: float) -> ReputationLevel:
    """Determine reputation level from cumulative points."""
    for level, threshold in LEVEL_THRESHOLDS:
        if total_points >= threshold:
            return level
    return ReputationLevel.NOVICE


def points_to_next_level(total_points: float) -> Tuple[ReputationLevel, float]:
    """Return the next level and how many points are needed to reach it."""
    current = level_from_points(total_points)
    for level, threshold in LEVEL_THRESHOLDS:
        if threshold > total_points:
            continue
        # Find the level above current
        break

    # Find next level threshold
    for level, threshold in reversed(LEVEL_THRESHOLDS):
        if threshold > total_points:
            return level, round(threshold - total_points, 2)

    return ReputationLevel.LEGEND, 0.0


@dataclass
class ReputationSnapshot:
    """Point-in-time reputation state for an agent."""
    agent_id: str = ""
    total_points: float = 0.0
    decayed_points: float = 0.0
    level: str = ReputationLevel.NOVICE.value
    influence_weight: float = 1.0
    permissions: List[str] = field(default_factory=list)
    next_level: str = ""
    points_to_next: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_points": round(self.total_points, 2),
            "decayed_points": round(self.decayed_points, 2),
            "level": self.level,
            "influence_weight": self.influence_weight,
            "permissions": self.permissions,
            "next_level": self.next_level,
            "points_to_next": round(self.points_to_next, 2),
        }


class ReputationTracker:
    """Computes reputation snapshots from RewardEngine data.

    This is a read-only view layer — it queries the engine's outcome
    store and computes levels, influence, and permissions.
    """

    def __init__(self, decay_lambda: float = 0.0):
        self.decay_lambda = decay_lambda

    def compute_snapshot(
        self,
        agent_id: str,
        outcomes: List[Dict[str, Any]],
    ) -> ReputationSnapshot:
        """Compute reputation snapshot from a list of reward outcomes.

        Args:
            agent_id: the agent to compute for
            outcomes: list of outcome dicts with 'total_points' and 'created_at'
        """
        now = time.time()
        total = 0.0
        decayed = 0.0

        for o in outcomes:
            pts = o.get("total_points", 0.0)
            total += pts
            if self.decay_lambda > 0:
                age_days = (now - o.get("created_at", now)) / 86400.0
                pts *= math.exp(-self.decay_lambda * age_days)
            decayed += pts

        # Use decayed points for level computation (rewards recent work)
        effective = decayed if self.decay_lambda > 0 else total
        level = level_from_points(effective)
        next_lvl, pts_needed = points_to_next_level(effective)

        return ReputationSnapshot(
            agent_id=agent_id,
            total_points=round(total, 2),
            decayed_points=round(decayed, 2),
            level=level.value,
            influence_weight=LEVEL_INFLUENCE.get(level.value, 1.0),
            permissions=LEVEL_PERMISSIONS.get(level.value, []),
            next_level=next_lvl.value,
            points_to_next=pts_needed,
        )
