"""
Cross-domain curriculum and transfer learning planner for MERID.

Provides structured skill tracks that agents can progress through to ensure
capabilities are gained with evidence. Designed to interface with the
self-evolution loop, allowing new roles to request training plans before being
deployed into production missions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


@dataclass
class CurriculumTask:
    """Single learning step with measurable criteria."""

    task_id: str
    title: str
    domain: str
    difficulty: str
    success_criteria: Dict[str, float]
    prerequisites: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class TaskProgress:
    """Track task attempts and outcomes."""

    attempts: int = 0
    successes: int = 0
    last_attempt_at: Optional[datetime] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class CurriculumTrack:
    """Ordered set of tasks with transfer-learning hints."""

    track_id: str
    name: str
    domain: str
    tasks: List[CurriculumTask] = field(default_factory=list)
    transfer_targets: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_task(self, task: CurriculumTask) -> None:
        self.tasks.append(task)


class CurriculumPlanner:
    """Planner that assigns and evaluates curriculum tasks."""

    def __init__(self) -> None:
        self._tracks: Dict[str, CurriculumTrack] = {}
        self._progress: Dict[str, Dict[str, TaskProgress]] = {}

    def register_track(self, track: CurriculumTrack) -> None:
        logger.info("Registering curriculum track %s (%s)", track.track_id, track.name)
        self._tracks[track.track_id] = track

    def assign_track(self, agent_id: str, track_id: str) -> None:
        if track_id not in self._tracks:
            raise KeyError(f"Track '{track_id}' not found")
        self._progress.setdefault(agent_id, {})
        for task in self._tracks[track_id].tasks:
            self._progress[agent_id].setdefault(task.task_id, TaskProgress())
        logger.info("Assigned track %s to agent %s", track_id, agent_id)

    def record_result(
        self,
        agent_id: str,
        task_id: str,
        success: bool,
        note: Optional[str] = None,
    ) -> TaskProgress:
        if agent_id not in self._progress or task_id not in self._progress[agent_id]:
            raise KeyError(f"Task '{task_id}' not assigned to agent '{agent_id}'")

        progress = self._progress[agent_id][task_id]
        progress.attempts += 1
        progress.last_attempt_at = datetime.utcnow()
        if success:
            progress.successes += 1
        if note:
            progress.notes.append(note)
        logger.debug(
            "Recorded curriculum result agent=%s task=%s success=%s",
            agent_id,
            task_id,
            success,
        )
        return progress

    def suggest_next_task(self, agent_id: str, track_id: str) -> Optional[CurriculumTask]:
        track = self._tracks.get(track_id)
        if not track:
            raise KeyError(f"Track '{track_id}' not found")
        if agent_id not in self._progress:
            return track.tasks[0] if track.tasks else None

        for task in track.tasks:
            prog = self._progress[agent_id].get(task.task_id)
            if not prog or prog.successes == 0:
                unmet_prereqs = [
                    prereq
                    for prereq in task.prerequisites
                    if not self._progress[agent_id].get(prereq) or self._progress[agent_id][prereq].successes == 0
                ]
                if unmet_prereqs:
                    continue
                return task
        return None

    def get_track_summary(self, track_id: str) -> Dict[str, object]:
        track = self._tracks.get(track_id)
        if not track:
            raise KeyError(f"Track '{track_id}' not found")
        return {
            "track_id": track.track_id,
            "name": track.name,
            "domain": track.domain,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "difficulty": task.difficulty,
                    "prerequisites": task.prerequisites,
                }
                for task in track.tasks
            ],
            "transfer_targets": track.transfer_targets,
        }


_curriculum_planner: Optional[CurriculumPlanner] = None


def get_curriculum_planner() -> CurriculumPlanner:
    global _curriculum_planner
    if _curriculum_planner is None:
        _curriculum_planner = CurriculumPlanner()
    return _curriculum_planner
