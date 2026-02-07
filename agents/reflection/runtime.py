"""Runtime helpers for invoking structured reflection orchestration."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.reflection.orchestrator import (
    CriticResult,
    GuardrailStatus,
    HallucinationMetric,
    MetaDecision,
    ProducerArtifact,
    ReflectionEvidence,
    ReflectionEvent,
    ReflectionLoopType,
    ReflectionOrchestrator,
    ReflectionSeverity,
    ReflectionTrigger,
)
from agents.reflection.integration import ReflectionSystem, get_reflection_system

ProducerFn = Callable[[int, Optional[ProducerArtifact]], ProducerArtifact]
CriticFn = Callable[[ProducerArtifact], CriticResult]


class ReflectionRuntime:
    """Convenience wrapper that exposes high-level reflection operations."""

    def __init__(
        self,
        *,
        reflection_system: Optional[ReflectionSystem] = None,
        orchestrator: Optional[ReflectionOrchestrator] = None,
    ) -> None:
        self._reflection_system = reflection_system or get_reflection_system()
        self._orchestrator = orchestrator or self._reflection_system.orchestrator

    @property
    def orchestrator(self) -> ReflectionOrchestrator:
        return self._orchestrator

    def run_in_task_reflection(
        self,
        *,
        trigger_type: str,
        source_ref: str,
        severity: ReflectionSeverity,
        producer_id: str,
        critic_id: str,
        meta_id: str,
        produce_fn: ProducerFn,
        critic_fn: CriticFn,
        experience_key: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ProducerArtifact, ReflectionEvent]:
        """Execute the bounded in-task loop and log a reflection event."""

        trigger = ReflectionTrigger(
            type=trigger_type,
            source_ref=source_ref,
            severity=severity,
            metrics=metrics or {},
        )

        artifact, event = self._orchestrator.run_in_task_loop(
            producer_id=producer_id,
            critic_id=critic_id,
            meta_id=meta_id,
            trigger=trigger,
            produce_fn=produce_fn,
            critic_fn=critic_fn,
            experience_key=experience_key,
        )
        return artifact, event

    def record_post_task_reflection(
        self,
        *,
        trigger_type: str,
        source_ref: str,
        severity: ReflectionSeverity,
        producer_id: str,
        critic_id: str,
        meta_id: str,
        artifact: ProducerArtifact,
        critic_result: CriticResult,
        meta_decision: MetaDecision = MetaDecision.NONE,
        experience_key: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> ReflectionEvent:
        trigger = ReflectionTrigger(
            type=trigger_type,
            source_ref=source_ref,
            severity=severity,
            metrics=metrics or {},
        )

        return self._orchestrator.run_post_task_loop(
            producer_id=producer_id,
            critic_id=critic_id,
            meta_id=meta_id,
            trigger=trigger,
            artifact=artifact,
            critic_result=critic_result,
            meta_decision=meta_decision,
            experience_key=experience_key,
        )

    def log_hallucination_metric(self, metric: HallucinationMetric) -> None:
        self._orchestrator.log_hallucination_metrics(metric)


_runtime: Optional[ReflectionRuntime] = None


def get_reflection_runtime() -> ReflectionRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ReflectionRuntime()
    return _runtime


__all__ = ["ReflectionRuntime", "get_reflection_runtime", "ProducerFn", "CriticFn"]
