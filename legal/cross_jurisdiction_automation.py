"""
Cross-jurisdiction legal automation engine.

Maintains rule sets per jurisdiction, generates filing/checklist tasks, and
tracks completion so Swarm deployments stay compliant globally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime, timedelta


@dataclass
class JurisdictionRule:
    jurisdiction: str
    requirement: str
    frequency_days: int


@dataclass
class LegalTask:
    task_id: str
    jurisdiction: str
    requirement: str
    due_date: datetime
    completed: bool = False


class CrossJurisdictionAutomation:
    def __init__(self) -> None:
        self._rules: Dict[str, JurisdictionRule] = {}
        self._tasks: Dict[str, LegalTask] = {}

    def register_rule(self, rule: JurisdictionRule) -> None:
        self._rules[rule.jurisdiction] = rule

    def generate_task(self, jurisdiction: str) -> LegalTask:
        rule = self._rules[jurisdiction]
        task = LegalTask(
            task_id=f"{jurisdiction}_{len(self._tasks)+1}",
            jurisdiction=jurisdiction,
            requirement=rule.requirement,
            due_date=datetime.utcnow() + timedelta(days=rule.frequency_days),
        )
        self._tasks[task.task_id] = task
        return task

    def complete_task(self, task_id: str) -> LegalTask:
        task = self._tasks[task_id]
        task.completed = True
        return task

    def pending_tasks(self) -> List[LegalTask]:
        return [task for task in self._tasks.values() if not task.completed]
