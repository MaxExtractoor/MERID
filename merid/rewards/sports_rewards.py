"""Sports reward engine — badges, quests, and reward computation for sports betting.

Ties gamification rewards to accurate sports predictions:
  1. SportsBadgeEngine: Awards badges for sports-specific achievements.
  2. SportsQuestDefinitions: Predefined quests for sports betting milestones.
  3. SportsRewardComputer: Computes reward scores from sports events.

Badge tiers: bronze → silver → gold (escalating thresholds).
Quests track cross-vertical progress (forecasts, bets, debates).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.rewards.sports_rewards")


# ═══════════════════════════════════════════════════════════════════════
# 1. Sports Badge Definitions
# ═══════════════════════════════════════════════════════════════════════

SPORTS_BADGE_DEFS: List[Dict[str, Any]] = [
    # Forecast badges
    {"id": "sports_forecaster_bronze", "name": "Sports Forecaster (Bronze)",
     "description": "Submit 10 sports forecasts", "tier": "bronze",
     "requirement": {"type": "forecast_count", "threshold": 10}},
    {"id": "sports_forecaster_silver", "name": "Sports Forecaster (Silver)",
     "description": "Submit 50 sports forecasts", "tier": "silver",
     "requirement": {"type": "forecast_count", "threshold": 50}},
    {"id": "sports_forecaster_gold", "name": "Sports Forecaster (Gold)",
     "description": "Submit 200 sports forecasts", "tier": "gold",
     "requirement": {"type": "forecast_count", "threshold": 200}},

    # Accuracy badges
    {"id": "sharp_eye_bronze", "name": "Sharp Eye (Bronze)",
     "description": "Achieve Brier score < 0.20 on 5 resolved sports events", "tier": "bronze",
     "requirement": {"type": "accurate_forecasts", "threshold": 5, "brier_max": 0.20}},
    {"id": "sharp_eye_silver", "name": "Sharp Eye (Silver)",
     "description": "Achieve Brier score < 0.15 on 20 resolved sports events", "tier": "silver",
     "requirement": {"type": "accurate_forecasts", "threshold": 20, "brier_max": 0.15}},
    {"id": "sharp_eye_gold", "name": "Sharp Eye (Gold)",
     "description": "Achieve Brier score < 0.10 on 50 resolved sports events", "tier": "gold",
     "requirement": {"type": "accurate_forecasts", "threshold": 50, "brier_max": 0.10}},

    # Edge finder badges
    {"id": "edge_finder_bronze", "name": "Edge Finder (Bronze)",
     "description": "Find 5 edges > 5% that resolve profitably", "tier": "bronze",
     "requirement": {"type": "profitable_edges", "threshold": 5, "min_edge": 0.05}},
    {"id": "edge_finder_silver", "name": "Edge Finder (Silver)",
     "description": "Find 20 edges > 5% that resolve profitably", "tier": "silver",
     "requirement": {"type": "profitable_edges", "threshold": 20, "min_edge": 0.05}},

    # Live betting badges
    {"id": "live_bettor_bronze", "name": "Live Bettor (Bronze)",
     "description": "Place 10 live bets with sub-500ms latency", "tier": "bronze",
     "requirement": {"type": "live_bets", "threshold": 10, "max_latency_ms": 500}},
    {"id": "live_bettor_silver", "name": "Live Bettor (Silver)",
     "description": "Place 50 live bets with sub-500ms latency", "tier": "silver",
     "requirement": {"type": "live_bets", "threshold": 50, "max_latency_ms": 500}},

    # Debate badges
    {"id": "sports_debater_bronze", "name": "Sports Debater (Bronze)",
     "description": "Participate in 5 sports debates with positive lift", "tier": "bronze",
     "requirement": {"type": "debate_lift", "threshold": 5}},
    {"id": "sports_debater_silver", "name": "Sports Debater (Silver)",
     "description": "Participate in 20 sports debates with positive lift", "tier": "silver",
     "requirement": {"type": "debate_lift", "threshold": 20}},

    # Multi-sport badge
    {"id": "multi_sport_bronze", "name": "Multi-Sport (Bronze)",
     "description": "Submit forecasts for 3 different sports", "tier": "bronze",
     "requirement": {"type": "sport_diversity", "threshold": 3}},
    {"id": "multi_sport_silver", "name": "Multi-Sport (Silver)",
     "description": "Submit forecasts for 6 different sports", "tier": "silver",
     "requirement": {"type": "sport_diversity", "threshold": 6}},
]


# ═══════════════════════════════════════════════════════════════════════
# 2. Sports Quest Definitions
# ═══════════════════════════════════════════════════════════════════════

SPORTS_QUEST_DEFS: List[Dict[str, Any]] = [
    {
        "id": "quest_first_forecast",
        "name": "First Sports Forecast",
        "description": "Submit your first sports prediction forecast",
        "xp_reward": 50,
        "steps": [{"type": "forecast_count", "target": 1}],
    },
    {
        "id": "quest_forecast_streak",
        "name": "Forecast Streak",
        "description": "Submit forecasts for 5 consecutive events",
        "xp_reward": 200,
        "steps": [{"type": "forecast_streak", "target": 5}],
    },
    {
        "id": "quest_live_edge",
        "name": "Live Edge Hunter",
        "description": "Find and bet on 3 live edges > 3%",
        "xp_reward": 300,
        "steps": [{"type": "live_edge_bets", "target": 3, "min_edge": 0.03}],
    },
    {
        "id": "quest_debate_champion",
        "name": "Debate Champion",
        "description": "Win 3 sports debates (positive lift as proposer)",
        "xp_reward": 500,
        "steps": [{"type": "debate_wins", "target": 3}],
    },
    {
        "id": "quest_sharp_beater",
        "name": "Beat the Sharps",
        "description": "Outperform sharp-book implied probability on 10 resolved events",
        "xp_reward": 750,
        "steps": [{"type": "beat_sharps", "target": 10}],
    },
    {
        "id": "quest_multi_vertical",
        "name": "Cross-Vertical Master",
        "description": "Submit forecasts in sports, prediction markets, and crypto in the same day",
        "xp_reward": 400,
        "steps": [
            {"type": "sports_forecast", "target": 1},
            {"type": "prediction_forecast", "target": 1},
            {"type": "crypto_forecast", "target": 1},
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════
# 3. Sports Badge Engine
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BadgeAward:
    """Record of a badge awarded to an agent."""
    badge_id: str = ""
    agent_id: str = ""
    badge_name: str = ""
    tier: str = "bronze"
    awarded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "badge_id": self.badge_id,
            "agent_id": self.agent_id,
            "badge_name": self.badge_name,
            "tier": self.tier,
            "awarded_at": self.awarded_at,
        }


class SportsBadgeEngine:
    """Evaluates agent stats against badge definitions and awards badges."""

    def __init__(self):
        self._lock = threading.RLock()
        self._awarded: Dict[str, List[BadgeAward]] = {}  # agent_id → awards

    def evaluate(self, agent_id: str, stats: Dict[str, Any]) -> List[BadgeAward]:
        """Evaluate an agent's stats and award any newly earned badges."""
        new_awards = []
        with self._lock:
            existing = {a.badge_id for a in self._awarded.get(agent_id, [])}

        for badge_def in SPORTS_BADGE_DEFS:
            if badge_def["id"] in existing:
                continue
            if self._check_requirement(badge_def["requirement"], stats):
                award = BadgeAward(
                    badge_id=badge_def["id"],
                    agent_id=agent_id,
                    badge_name=badge_def["name"],
                    tier=badge_def["tier"],
                )
                new_awards.append(award)
                with self._lock:
                    if agent_id not in self._awarded:
                        self._awarded[agent_id] = []
                    self._awarded[agent_id].append(award)

        return new_awards

    def _check_requirement(self, req: Dict[str, Any], stats: Dict[str, Any]) -> bool:
        """Check if stats meet a badge requirement."""
        req_type = req.get("type", "")
        threshold = req.get("threshold", 0)

        if req_type == "forecast_count":
            return stats.get("forecast_count", 0) >= threshold
        elif req_type == "accurate_forecasts":
            brier_max = req.get("brier_max", 1.0)
            accurate = stats.get("accurate_forecasts", {}).get(str(brier_max), 0)
            return accurate >= threshold
        elif req_type == "profitable_edges":
            min_edge = req.get("min_edge", 0.0)
            profitable = stats.get("profitable_edges", {}).get(str(min_edge), 0)
            return profitable >= threshold
        elif req_type == "live_bets":
            max_lat = req.get("max_latency_ms", 500)
            live = stats.get("live_bets_under_latency", {}).get(str(max_lat), 0)
            return live >= threshold
        elif req_type == "debate_lift":
            return stats.get("positive_lift_debates", 0) >= threshold
        elif req_type == "sport_diversity":
            return stats.get("unique_sports", 0) >= threshold
        return False

    def get_badges(self, agent_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._awarded.get(agent_id, [])]

    def get_all_badges(self) -> Dict[str, List[Dict[str, Any]]]:
        with self._lock:
            return {
                agent: [a.to_dict() for a in awards]
                for agent, awards in self._awarded.items()
            }


# ═══════════════════════════════════════════════════════════════════════
# 4. Sports Quest Tracker
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class QuestProgress:
    """Tracks an agent's progress on a quest."""
    quest_id: str = ""
    agent_id: str = ""
    quest_name: str = ""
    xp_reward: int = 0
    steps_completed: int = 0
    steps_total: int = 1
    completed: bool = False
    completed_at: Optional[float] = None
    started_at: float = field(default_factory=time.time)

    @property
    def progress_pct(self) -> float:
        return min(1.0, self.steps_completed / max(1, self.steps_total))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_id": self.quest_id,
            "agent_id": self.agent_id,
            "quest_name": self.quest_name,
            "xp_reward": self.xp_reward,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "progress_pct": round(self.progress_pct, 2),
            "completed": self.completed,
            "completed_at": self.completed_at,
        }


class SportsQuestTracker:
    """Tracks agent progress on sports quests."""

    def __init__(self):
        self._lock = threading.RLock()
        # agent_id → quest_id → QuestProgress
        self._progress: Dict[str, Dict[str, QuestProgress]] = {}
        self._total_xp: Dict[str, int] = {}  # agent_id → total XP earned

    def update_progress(
        self,
        agent_id: str,
        stats: Dict[str, Any],
    ) -> List[QuestProgress]:
        """Update quest progress based on agent stats. Returns newly completed quests."""
        newly_completed = []

        with self._lock:
            if agent_id not in self._progress:
                self._progress[agent_id] = {}
                self._total_xp[agent_id] = 0

            for quest_def in SPORTS_QUEST_DEFS:
                qid = quest_def["id"]
                if qid not in self._progress[agent_id]:
                    self._progress[agent_id][qid] = QuestProgress(
                        quest_id=qid,
                        agent_id=agent_id,
                        quest_name=quest_def["name"],
                        xp_reward=quest_def["xp_reward"],
                        steps_total=len(quest_def["steps"]),
                    )

                progress = self._progress[agent_id][qid]
                if progress.completed:
                    continue

                # Count completed steps
                completed = 0
                for step in quest_def["steps"]:
                    if self._check_step(step, stats):
                        completed += 1
                progress.steps_completed = completed

                if completed >= progress.steps_total and not progress.completed:
                    progress.completed = True
                    progress.completed_at = time.time()
                    self._total_xp[agent_id] += progress.xp_reward
                    newly_completed.append(progress)

        return newly_completed

    def _check_step(self, step: Dict[str, Any], stats: Dict[str, Any]) -> bool:
        """Check if a quest step is satisfied by current stats."""
        step_type = step.get("type", "")
        target = step.get("target", 0)

        if step_type == "forecast_count":
            return stats.get("forecast_count", 0) >= target
        elif step_type == "forecast_streak":
            return stats.get("forecast_streak", 0) >= target
        elif step_type == "live_edge_bets":
            min_edge = step.get("min_edge", 0.0)
            return stats.get("live_edge_bets", 0) >= target
        elif step_type == "debate_wins":
            return stats.get("debate_wins", 0) >= target
        elif step_type == "beat_sharps":
            return stats.get("beat_sharps_count", 0) >= target
        elif step_type in ("sports_forecast", "prediction_forecast", "crypto_forecast"):
            return stats.get(step_type, 0) >= target
        return False

    def get_progress(self, agent_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            quests = self._progress.get(agent_id, {})
            return [q.to_dict() for q in quests.values()]

    def get_xp(self, agent_id: str) -> int:
        with self._lock:
            return self._total_xp.get(agent_id, 0)


# ═══════════════════════════════════════════════════════════════════════
# 5. Sports Reward Computer
# ═══════════════════════════════════════════════════════════════════════

class SportsRewardComputer:
    """Computes reward scores from sports events.

    Reward formula:
      base_reward = event_type_weight × confidence
      accuracy_bonus = max(0, 1 - brier_score) × accuracy_multiplier
      edge_bonus = |edge| × edge_multiplier (if profitable)
      debate_bonus = debate_lift × debate_multiplier (if positive)
      total = base_reward + accuracy_bonus + edge_bonus + debate_bonus
    """

    # Weights per event type
    EVENT_WEIGHTS: Dict[str, float] = {
        "sports_forecast": 1.0,
        "sports_bet": 2.0,
        "sports_debate": 1.5,
    }

    def __init__(
        self,
        accuracy_multiplier: float = 5.0,
        edge_multiplier: float = 10.0,
        debate_multiplier: float = 3.0,
    ):
        self.accuracy_multiplier = accuracy_multiplier
        self.edge_multiplier = edge_multiplier
        self.debate_multiplier = debate_multiplier

    def compute(self, event_dict: Dict[str, Any]) -> float:
        """Compute reward score from a sports event dict."""
        category = event_dict.get("category", "")
        base_weight = self.EVENT_WEIGHTS.get(category, 1.0)
        confidence = event_dict.get("confidence", 0.5)

        base_reward = base_weight * confidence

        # Accuracy bonus
        brier = event_dict.get("brier_score")
        accuracy_bonus = 0.0
        if brier is not None:
            accuracy_bonus = max(0.0, 1.0 - brier) * self.accuracy_multiplier

        # Edge bonus
        edge = event_dict.get("edge", 0.0)
        pnl = event_dict.get("pnl")
        edge_bonus = 0.0
        if pnl is not None and pnl > 0 and abs(edge) > 0:
            edge_bonus = abs(edge) * self.edge_multiplier

        # Debate lift bonus
        lift = event_dict.get("debate_lift")
        debate_bonus = 0.0
        if lift is not None and lift > 0:
            debate_bonus = lift * self.debate_multiplier

        return round(base_reward + accuracy_bonus + edge_bonus + debate_bonus, 4)


# ═══════════════════════════════════════════════════════════════════════
# 6. Singletons
# ═══════════════════════════════════════════════════════════════════════

_badge_engine: Optional[SportsBadgeEngine] = None
_badge_engine_lock = threading.Lock()
_quest_tracker: Optional[SportsQuestTracker] = None
_quest_tracker_lock = threading.Lock()
_reward_computer: Optional[SportsRewardComputer] = None
_reward_computer_lock = threading.Lock()


def get_sports_badge_engine() -> SportsBadgeEngine:
    global _badge_engine
    if _badge_engine is None:
        with _badge_engine_lock:
            if _badge_engine is None:
                _badge_engine = SportsBadgeEngine()
    return _badge_engine


def get_sports_quest_tracker() -> SportsQuestTracker:
    global _quest_tracker
    if _quest_tracker is None:
        with _quest_tracker_lock:
            if _quest_tracker is None:
                _quest_tracker = SportsQuestTracker()
    return _quest_tracker


def get_sports_reward_computer() -> SportsRewardComputer:
    global _reward_computer
    if _reward_computer is None:
        with _reward_computer_lock:
            if _reward_computer is None:
                _reward_computer = SportsRewardComputer()
    return _reward_computer
