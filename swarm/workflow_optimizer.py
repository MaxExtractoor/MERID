"""
Workflow optimization engine for swarm orchestration.

Analyzes task flow graphs, detects bottlenecks, and recommends reorderings or
parallelization opportunities to improve throughput.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class WorkflowStep:
    step_id: str
    agent_role: str
    avg_latency_ms: float
    depends_on: List[str]


class WorkflowOptimizationEngine:
    def __init__(self) -> None:
        self._steps: Dict[str, WorkflowStep] = {}

    def register_step(self, step: WorkflowStep) -> None:
        self._steps[step.step_id] = step

    def critical_path_latency(self) -> float:
        memo: Dict[str, float] = {}

        def dfs(step_id: str) -> float:
            if step_id in memo:
                return memo[step_id]
            step = self._steps[step_id]
            base = step.avg_latency_ms
            if not step.depends_on:
                memo[step_id] = base
                return base
            max_dep = max(dfs(dep) for dep in step.depends_on)
            memo[step_id] = base + max_dep
            return memo[step_id]

        return max((dfs(step_id) for step_id in self._steps), default=0.0)

    def recommend_parallel_steps(self) -> List[str]:
        parallelizable = []
        for step_id, step in self._steps.items():
            if all(self._steps[d].agent_role != step.agent_role for d in step.depends_on):
                parallelizable.append(step_id)
        return parallelizable
