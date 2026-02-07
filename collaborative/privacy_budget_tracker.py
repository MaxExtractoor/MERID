"""
Privacy budget tracking for collaborative federated learning runs.

Allows orchestrators to allocate epsilon/delta budgets per workflow, decrement
on each gradient submission, and alert when thresholds are exceeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


@dataclass
class PrivacyBudget:
    workflow_id: str
    epsilon_total: float
    delta_total: float
    epsilon_spent: float = 0.0
    delta_spent: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def epsilon_remaining(self) -> float:
        return max(0.0, self.epsilon_total - self.epsilon_spent)

    @property
    def delta_remaining(self) -> float:
        return max(0.0, self.delta_total - self.delta_spent)


class PrivacyBudgetTracker:
    def __init__(self) -> None:
        self._budgets: Dict[str, PrivacyBudget] = {}

    def register_budget(self, workflow_id: str, epsilon_total: float, delta_total: float) -> PrivacyBudget:
        budget = PrivacyBudget(workflow_id=workflow_id, epsilon_total=epsilon_total, delta_total=delta_total)
        self._budgets[workflow_id] = budget
        return budget

    def consume(self, workflow_id: str, epsilon: float, delta: float) -> PrivacyBudget:
        budget = self._budgets[workflow_id]
        budget.epsilon_spent = min(budget.epsilon_total, budget.epsilon_spent + epsilon)
        budget.delta_spent = min(budget.delta_total, budget.delta_spent + delta)
        budget.last_updated = datetime.utcnow()
        return budget

    def status(self, workflow_id: str) -> PrivacyBudget:
        return self._budgets[workflow_id]

    def needs_refresh(self, workflow_id: str) -> bool:
        budget = self._budgets[workflow_id]
        epsilon_ratio = budget.epsilon_spent / budget.epsilon_total if budget.epsilon_total else 1.0
        return epsilon_ratio >= 0.9
