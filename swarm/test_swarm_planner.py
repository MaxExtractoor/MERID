"""ReAct-style planner for the autonomous Test Swarm."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from swarm.dev_swarm_orchestrator import (
    DevTask,
    TaskStatus,
    TaskType,
    get_dev_swarm_orchestrator,
)


@dataclass
class DiffStat:
    """Summary of a file diff used to trigger testing tasks."""

    file_path: str
    lines_added: int
    lines_deleted: int
    risk_tier: str = "standard"


class TestSwarmPlanner:
    __test__ = False  # prevent pytest from collecting this helper class
    """Plans autonomous testing tasks across unit/integration/self-heal flows."""

    def __init__(
        self,
        *,
        coverage_report: Path | None = None,
        mutation_report: Path | None = None,
        flaky_report: Path | None = None,
    ) -> None:
        self._orchestrator = get_dev_swarm_orchestrator()
        self._coverage_report = coverage_report or Path("reports/coverage.json")
        self._mutation_report = mutation_report or Path("reports/mutation.json")
        self._flaky_report = flaky_report or Path("reports/flaky_tests.json")
        self._coverage_cache: Dict[str, Dict[str, float]] = {}
        self._mutation_cache: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan_for_diff(self, diffs: Sequence[DiffStat]) -> List[str]:
        """Generate unit/integration test tasks based on changed files."""

        self._refresh_metrics()
        task_ids: List[str] = []

        for diff in diffs:
            module = self._infer_module(diff.file_path)
            metadata = {
                "module": module,
                "file": diff.file_path,
                "lines_added": diff.lines_added,
                "lines_deleted": diff.lines_deleted,
                "risk_tier": diff.risk_tier,
            }
            coverage = self._coverage_cache.get(module, {}).get("statement_coverage")
            mutation = self._mutation_cache.get(module, {}).get("mutation_score")
            if coverage is not None:
                metadata["coverage"] = coverage
            if mutation is not None:
                metadata["mutation_score"] = mutation

            task_type = self._select_task_type(diff.file_path)
            description = self._describe_task(diff.file_path, task_type, coverage, mutation)
            priority = self._priority_from_diff(diff, coverage)

            task_ids.append(
                self._submit_task(
                    task_type=task_type,
                    description=description,
                    priority=priority,
                    metadata=metadata,
                )
            )

        return task_ids

    def plan_self_healing(self) -> List[str]:
        """Generate tasks for flaky tests captured in reports."""

        flake_entries = self._load_json(self._flaky_report, default=[])
        task_ids: List[str] = []
        for entry in flake_entries:
            test_name = entry.get("test")
            failure_rate = entry.get("failure_rate")
            module = self._infer_module(entry.get("file", test_name or "flaky"))
            metadata = {
                "test_name": test_name,
                "failure_rate": failure_rate,
                "module": module,
            }
            description = f"Self-heal flaky test {test_name} (failure rate {failure_rate})"
            task_ids.append(
                self._submit_task(
                    task_type=TaskType.TEST_SELF_HEAL,
                    description=description,
                    priority=self._priority_from_flakiness(failure_rate),
                    metadata=metadata,
                )
            )
        return task_ids

    def plan_incident_discovery(self, incidents: Sequence[Dict[str, str]]) -> List[str]:
        """Convert incident metadata into regression-test discovery tasks."""

        task_ids: List[str] = []
        for incident in incidents:
            incident_id = incident.get("id", uuid.uuid4().hex[:8])
            module = incident.get("module") or self._infer_module(incident.get("file", ""))
            description = (
                f"Capture regression scenario for incident {incident_id} impacting {module}"
            )
            metadata = {
                "incident_id": incident_id,
                "severity": incident.get("severity", "unknown"),
                "module": module,
            }
            task_ids.append(
                self._submit_task(
                    task_type=TaskType.TEST_DISCOVERY,
                    description=description,
                    priority=9 if incident.get("severity") == "critical" else 6,
                    metadata=metadata,
                )
            )
        return task_ids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _submit_task(
        self,
        *,
        task_type: TaskType,
        description: str,
        priority: int,
        metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        task = DevTask(
            task_id=f"test_{task_type.value}_{uuid.uuid4().hex[:8]}",
            task_type=task_type,
            description=description,
            priority=priority,
            status=TaskStatus.PENDING,
            metadata=metadata or {},
        )
        return self._orchestrator.submit_task(task)

    def _refresh_metrics(self) -> None:
        self._coverage_cache = self._load_json(self._coverage_report, default={})
        self._mutation_cache = self._load_json(self._mutation_report, default={})

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _select_task_type(self, file_path: str) -> TaskType:
        if file_path.startswith("api/") or file_path.startswith("core/event"):
            return TaskType.INTEGRATION_TEST
        if file_path.startswith("observability/") or file_path.startswith("core/telemetry"):
            return TaskType.INTEGRATION_TEST
        return TaskType.UNIT_TEST

    def _describe_task(
        self,
        file_path: str,
        task_type: TaskType,
        coverage: Optional[float],
        mutation: Optional[float],
    ) -> str:
        coverage_str = f" current coverage {coverage:.1f}%" if coverage is not None else ""
        mutation_str = f" mutation score {mutation:.1f}%" if mutation is not None else ""
        return (
            f"Generate {task_type.value.replace('_', ' ')} for {file_path}{coverage_str}{mutation_str}."
        )

    def _priority_from_diff(self, diff: DiffStat, coverage: Optional[float]) -> int:
        base = 5
        if diff.lines_added + diff.lines_deleted > 200:
            base += 2
        if coverage is not None and coverage < 80:
            base += 2
        if diff.risk_tier == "critical":
            base += 2
        return min(base, 10)

    def _priority_from_flakiness(self, failure_rate: Optional[float]) -> int:
        if failure_rate is None:
            return 6
        if failure_rate >= 0.5:
            return 10
        if failure_rate >= 0.25:
            return 8
        return 6

    def _infer_module(self, file_path: str) -> str:
        if not file_path:
            return "unknown"
        parts = file_path.split("/")
        return parts[0] if parts else "unknown"


def get_test_swarm_planner() -> TestSwarmPlanner:
    return TestSwarmPlanner()
