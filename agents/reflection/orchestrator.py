"""Structured reflection orchestrator with explicit roles, triggers, and metrics."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only for static typing
    from agents.reflection.integration import ReflectionSystem

ProducerFn = Callable[[int, Optional["ProducerArtifact"]], "ProducerArtifact"]
CriticFn = Callable[["ProducerArtifact"], "CriticResult"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_payload(payload: Any) -> str:
    try:
        serialized = json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        serialized = str(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ReflectionLoopType(str, Enum):
    IN_TASK = "in_task"
    POST_TASK = "post_task"


class ReflectionSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"


class GuardrailStatus(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"


class MetaDecision(str, Enum):
    NONE = "none"
    RETRY = "retry"
    DEFER = "defer"
    ESCALATE = "escalate"
    PLAYBOOK_UPDATE = "playbook_update"


@dataclass(frozen=True)
class ReflectionTrigger:
    type: str
    source_ref: str
    severity: ReflectionSeverity
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "source_ref": self.source_ref,
            "severity": self.severity.value,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class ReflectionEvidence:
    ref_type: str
    reference: str
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {"type": self.ref_type, "reference": self.reference}
        if self.notes:
            data["notes"] = self.notes
        return data


@dataclass(frozen=True)
class CriticFinding:
    issue: str
    severity: ReflectionSeverity
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue": self.issue,
            "severity": self.severity.value,
            "details": self.details,
        }


@dataclass(frozen=True)
class CriticResult:
    passed: bool
    findings: List[CriticFinding] = field(default_factory=list)
    guardrail_status: GuardrailStatus = GuardrailStatus.ALLOW
    evidence_refs: List[ReflectionEvidence] = field(default_factory=list)
    latency_ms: Optional[float] = None


@dataclass(frozen=True)
class ProducerArtifact:
    artifact_id: str
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        payload = {"content": self.content, "metadata": self.metadata}
        return _hash_payload(payload)


@dataclass(frozen=True)
class HallucinationMetric:
    checkpoint: str
    step: int
    domain: str
    dataset: str
    hr_basic: float
    hr_weighted: float
    hr_base: float
    hr_reflection: float
    delta_hr_reflection: float
    decay_rate_b: float
    half_life_steps: int
    task_accuracy: float
    factual_claim_density: float
    avg_response_tokens: float
    timestamp: str = field(default_factory=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint": self.checkpoint,
            "step": self.step,
            "domain": self.domain,
            "dataset": self.dataset,
            "hr_basic": self.hr_basic,
            "hr_weighted": self.hr_weighted,
            "hr_base": self.hr_base,
            "hr_reflection": self.hr_reflection,
            "delta_hr_reflection": self.delta_hr_reflection,
            "decay_rate_b": self.decay_rate_b,
            "half_life_steps": self.half_life_steps,
            "task_accuracy": self.task_accuracy,
            "factual_claim_density": self.factual_claim_density,
            "avg_response_tokens": self.avg_response_tokens,
            "timestamp": self.timestamp,
        }


@dataclass
class ReflectionEvent:
    reflection_id: str
    loop_type: ReflectionLoopType
    producer_id: str
    critic_id: str
    meta_id: str
    trigger: ReflectionTrigger
    evidence_refs: List[ReflectionEvidence]
    critic_findings: List[CriticFinding]
    producer_output_hash: str
    meta_decision: MetaDecision
    actions: List[str]
    guardrail_status: GuardrailStatus
    loop_iteration: int
    experience_key: str
    outcome: str
    timestamp: str = field(default_factory=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reflection_id": self.reflection_id,
            "loop_type": self.loop_type.value,
            "producer_id": self.producer_id,
            "critic_id": self.critic_id,
            "meta_id": self.meta_id,
            "trigger": self.trigger.to_dict(),
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "critic_findings": [finding.to_dict() for finding in self.critic_findings],
            "producer_output_hash": self.producer_output_hash,
            "meta_decision": self.meta_decision.value,
            "actions": self.actions,
            "guardrail_status": self.guardrail_status.value,
            "loop_iteration": self.loop_iteration,
            "experience_key": self.experience_key,
            "outcome": self.outcome,
            "timestamp": self.timestamp,
        }


class ReflectionGuardrailViolation(RuntimeError):
    """Raised when reflection detects a guardrail denial."""


class ReflectionLoopExceeded(RuntimeError):
    """Raised when the orchestrator exhausts allowed reflection loops."""


class ReflectionOrchestrator:
    """Coordinates producer/critic/meta loops and logs structured events."""

    def __init__(
        self,
        *,
        reflection_system: Optional["ReflectionSystem"] = None,
        experience_log_path: Path = Path("logs/reflection_events.jsonl"),
        hallucination_log_path: Path = Path("logs/hallucination_metrics.jsonl"),
        max_in_task_loops: int = 1,
        max_post_task_loops: int = 1,
    ) -> None:
        if reflection_system is None:
            from agents.reflection.integration import get_reflection_system  # local import to avoid cycle

            reflection_system = get_reflection_system()

        self._reflection_system = reflection_system
        self._experience_log_path = experience_log_path
        self._experience_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._hallucination_log_path = hallucination_log_path
        self._hallucination_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_in_task_loops = max(1, max_in_task_loops)
        self._max_post_task_loops = max(1, max_post_task_loops)
        self._lock = threading.Lock()
        self._stats = {
            "triggers": {},
            "guardrail_denials": 0,
            "events_logged": 0,
        }

    def run_in_task_loop(
        self,
        *,
        producer_id: str,
        critic_id: str,
        meta_id: str,
        trigger: ReflectionTrigger,
        produce_fn: ProducerFn,
        critic_fn: CriticFn,
        experience_key: Optional[str] = None,
    ) -> Tuple[ProducerArtifact, ReflectionEvent]:
        previous_artifact: Optional[ProducerArtifact] = None

        for iteration in range(1, self._max_in_task_loops + 1):
            artifact = produce_fn(iteration, previous_artifact)
            critic_result = critic_fn(artifact)
            meta_decision = self._decide_next_step(critic_result, iteration, self._max_in_task_loops)

            event = self._record_event(
                loop_type=ReflectionLoopType.IN_TASK,
                producer_id=producer_id,
                critic_id=critic_id,
                meta_id=meta_id,
                trigger=trigger,
                artifact=artifact,
                critic_result=critic_result,
                meta_decision=meta_decision,
                loop_iteration=iteration,
                experience_key=experience_key,
                resolved=critic_result.passed,
            )

            if critic_result.passed:
                return artifact, event

            if critic_result.guardrail_status == GuardrailStatus.DENY:
                raise ReflectionGuardrailViolation(
                    f"Guardrail denial during reflection (trigger={trigger.type})"
                )

            previous_artifact = artifact

        raise ReflectionLoopExceeded(
            f"Reached max in-task reflection loops ({self._max_in_task_loops}) without resolution"
        )

    def run_post_task_loop(
        self,
        *,
        producer_id: str,
        critic_id: str,
        meta_id: str,
        trigger: ReflectionTrigger,
        artifact: ProducerArtifact,
        critic_result: CriticResult,
        meta_decision: MetaDecision,
        experience_key: Optional[str] = None,
    ) -> ReflectionEvent:
        return self._record_event(
            loop_type=ReflectionLoopType.POST_TASK,
            producer_id=producer_id,
            critic_id=critic_id,
            meta_id=meta_id,
            trigger=trigger,
            artifact=artifact,
            critic_result=critic_result,
            meta_decision=meta_decision,
            loop_iteration=1,
            experience_key=experience_key,
            resolved=True,
        )

    def log_hallucination_metrics(self, metric: HallucinationMetric) -> None:
        line = json.dumps(metric.to_dict(), sort_keys=True)
        with self._lock:
            with self._hallucination_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            triggers = dict(self._stats["triggers"])
            return {
                "events_logged": self._stats["events_logged"],
                "guardrail_denials": self._stats["guardrail_denials"],
                "triggers": triggers,
            }

    def _record_event(
        self,
        *,
        loop_type: ReflectionLoopType,
        producer_id: str,
        critic_id: str,
        meta_id: str,
        trigger: ReflectionTrigger,
        artifact: ProducerArtifact,
        critic_result: CriticResult,
        meta_decision: MetaDecision,
        loop_iteration: int,
        experience_key: Optional[str],
        resolved: bool,
    ) -> ReflectionEvent:
        evidence_refs = critic_result.evidence_refs
        experience_key = experience_key or f"{trigger.type}::{producer_id}"
        outcome = "resolved" if resolved else "pending"

        event = ReflectionEvent(
            reflection_id=str(uuid.uuid4()),
            loop_type=loop_type,
            producer_id=producer_id,
            critic_id=critic_id,
            meta_id=meta_id,
            trigger=trigger,
            evidence_refs=evidence_refs,
            critic_findings=critic_result.findings,
            producer_output_hash=artifact.content_hash(),
            meta_decision=meta_decision,
            actions=self._actions_for(meta_decision),
            guardrail_status=critic_result.guardrail_status,
            loop_iteration=loop_iteration,
            experience_key=experience_key,
            outcome=outcome,
        )

        self._persist_event(event)
        return event

    def _persist_event(self, event: ReflectionEvent) -> None:
        line = json.dumps(event.to_dict(), sort_keys=True)
        with self._lock:
            with self._experience_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._stats["events_logged"] += 1
            trigger_key = event.trigger.type
            self._stats["triggers"].setdefault(trigger_key, 0)
            self._stats["triggers"][trigger_key] += 1
            if event.guardrail_status == GuardrailStatus.DENY:
                self._stats["guardrail_denials"] += 1

    @staticmethod
    def _decide_next_step(
        critic_result: CriticResult, iteration: int, max_iterations: int
    ) -> MetaDecision:
        if critic_result.passed:
            return MetaDecision.NONE
        if critic_result.guardrail_status == GuardrailStatus.DENY:
            return MetaDecision.ESCALATE
        if iteration >= max_iterations:
            return MetaDecision.DEFER
        return MetaDecision.RETRY

    @staticmethod
    def _actions_for(meta_decision: MetaDecision) -> List[str]:
        if meta_decision == MetaDecision.RETRY:
            return ["rerun_producer"]
        if meta_decision == MetaDecision.DEFER:
            return ["defer_to_human"]
        if meta_decision == MetaDecision.ESCALATE:
            return ["escalate_guardrail"]
        if meta_decision == MetaDecision.PLAYBOOK_UPDATE:
            return ["update_playbook"]
        return []


__all__ = [
    "ReflectionOrchestrator",
    "ReflectionTrigger",
    "ReflectionEvidence",
    "ReflectionSeverity",
    "ReflectionLoopType",
    "GuardrailStatus",
    "MetaDecision",
    "CriticFinding",
    "CriticResult",
    "ProducerArtifact",
    "HallucinationMetric",
    "ReflectionEvent",
    "ReflectionGuardrailViolation",
    "ReflectionLoopExceeded",
]
