"""
Multi-season quest campaign service.

Manages quests with seasons, reward multipliers, and progress tracking to keep
community engagement high across protocol maintenance initiatives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class Quest:
    quest_id: str
    title: str
    description: str
    season: int
    reward_points: int
    requirements: Dict[str, str]


@dataclass
class QuestProgress:
    quest_id: str
    user_id: str
    completed: bool = False
    completion_timestamp: datetime | None = None


class QuestCampaignService:
    def __init__(self) -> None:
        self._quests: Dict[str, Quest] = {}
        self._progress: Dict[str, QuestProgress] = {}

    def register_quest(self, quest: Quest) -> None:
        self._quests[quest.quest_id] = quest

    def record_progress(self, quest_id: str, user_id: str, completed: bool) -> QuestProgress:
        progress_id = f"{quest_id}:{user_id}"
        progress = self._progress.get(progress_id) or QuestProgress(quest_id=quest_id, user_id=user_id)
        progress.completed = completed
        if completed:
            progress.completion_timestamp = datetime.utcnow()
        self._progress[progress_id] = progress
        return progress

    def season_leaderboard(self, season: int) -> List[Dict[str, int]]:
        leaderboard: Dict[str, int] = {}
        for progress in self._progress.values():
            if progress.completed:
                quest = self._quests[progress.quest_id]
                if quest.season == season:
                    leaderboard[progress.user_id] = leaderboard.get(progress.user_id, 0) + quest.reward_points
        return sorted([{"user_id": user_id, "points": points} for user_id, points in leaderboard.items()], key=lambda entry: entry["points"], reverse=True)
