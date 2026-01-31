"""
Self-healing rollback mechanisms.

Tracks deployments and state snapshots, providing automatic rollback plans when
health metrics deteriorate after a rollout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class DeploymentSnapshot:
    snapshot_id: str
    component: str
    version: str
    created_at: datetime
    metadata: Dict[str, str]


@dataclass
class RollbackPlan:
    plan_id: str
    target_snapshot: str
    reason: str
    steps: List[str]
    approved: bool = False
    executed_at: datetime | None = None


class SelfHealingRollbackManager:
    def __init__(self) -> None:
        self._snapshots: Dict[str, DeploymentSnapshot] = {}
        self._plans: Dict[str, RollbackPlan] = {}

    def register_snapshot(self, snapshot: DeploymentSnapshot) -> None:
        self._snapshots[snapshot.snapshot_id] = snapshot

    def create_plan(self, component: str, reason: str) -> RollbackPlan:
        snapshots = [snap for snap in self._snapshots.values() if snap.component == component]
        snapshots.sort(key=lambda snap: snap.created_at, reverse=True)
        if not snapshots:
            raise ValueError("No snapshots available")
        target = snapshots[0]
        plan = RollbackPlan(
            plan_id=f"rollback_{len(self._plans)+1}",
            target_snapshot=target.snapshot_id,
            reason=reason,
            steps=[
                "Pause traffic",
                f"Restore snapshot {target.snapshot_id}",
                "Run smoke tests",
                "Resume traffic",
            ],
        )
        self._plans[plan.plan_id] = plan
        return plan

    def approve_and_execute(self, plan_id: str) -> RollbackPlan:
        plan = self._plans[plan_id]
        plan.approved = True
        plan.executed_at = datetime.utcnow()
        return plan
