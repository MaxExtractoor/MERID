"""
Explainability & Audit service for MERID.
Gemma-led explanations with Llama technical augmentation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from core.data_permissions import (
    DataAccessPolicy,
    DataClassification,
    get_data_access_controller,
)
from core.telemetry_manager import get_telemetry_manager
from utils.logger import get_logger

logger = get_logger("core.explainability")


class ExplanationType(str, Enum):
    """Types of explainable events."""

    ORDER = "order"
    CANCEL = "cancel"
    PARAM_CHANGE = "parameter_change"
    PROMOTION = "promotion"
    DEMOTION = "demotion"
    SIM_TO_PAPER = "sim_to_paper"
    PAPER_TO_LIVE = "paper_to_live"
    X402_PAYMENT = "x402_payment"
    SAFE_MODE = "safe_mode"
    DRIFT_EVENT = "drift_event"
    DEV_COMMAND = "dev_command"


class ExplainabilityViolation(RuntimeError):
    """Raised when a decision is missing the required rationale."""


@dataclass
class FeatureAttribution:
    """Single feature contribution inside a rationale."""

    name: str
    value: Any
    importance: Optional[float] = None


@dataclass
class RuleEvaluation:
    """Represents a guardrail/rule that fired during the decision."""

    rule_name: str
    threshold: Any
    observed_value: Any
    passed: bool
    notes: Optional[str] = None


@dataclass
class ModelEvidence:
    """Model-level evidence backing a decision."""

    model_id: str
    version: str
    score: float
    confidence: Optional[float] = None
    uncertainty: Optional[str] = None


@dataclass
class CounterfactualScenario:
    """Alternative action that was considered but rejected."""

    option_id: str
    summary: str
    expected_outcome: Dict[str, Any]
    reason_rejected: str


@dataclass
class DecisionRationale:
    """Standard explanation payload shared across MERID domains."""

    reason: str
    inputs: Dict[str, Any]
    features: List[FeatureAttribution] = field(default_factory=list)
    rules_fired: List[RuleEvaluation] = field(default_factory=list)
    model_evidence: List[ModelEvidence] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    counterfactuals: List[CounterfactualScenario] = field(default_factory=list)
    telemetry_refs: List[str] = field(default_factory=list)


@dataclass
class ExplanationContext:
    """Context included in an explanation."""

    inputs: Dict[str, Any]
    agent_id: str
    strategy: Optional[str]
    constraints: Dict[str, Any]
    expected_effect: Dict[str, Any]
    environment_flags: Dict[str, Any]
    tools_invoked: List[str] = field(default_factory=list)
    alternatives_considered: List[str] = field(default_factory=list)


@dataclass
class ExplanationRecord:
    """Stored explanation entry."""

    record_id: str
    explanation_type: ExplanationType
    summary: str
    expert_notes: Optional[str]
    context: ExplanationContext
    domain: str = "unspecified"
    decision_id: Optional[str] = None
    correlation_id: Optional[str] = None
    rationale: Optional[DecisionRationale] = None
    guardrail_id: Optional[str] = None
    guardrail_decision: Optional[str] = None
    guardrail_rationale: Optional[str] = None
    latency_domain: Optional[str] = None
    latency_workflow: Optional[str] = None
    latency_status: Optional[str] = None
    latency_observed_ms: Optional[float] = None
    latency_fallback_strategy: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExplainableResult:
    """Wrapper pairing a result payload with the recorded explanation."""

    result: Any
    explanation_record: ExplanationRecord


class ExplainabilityService:
    """Central service capturing explanations."""

    def __init__(self) -> None:
        self._records: List[ExplanationRecord] = []
        self._coverage_counts: Dict[str, int] = {}
        self._latency_stats: List[float] = []
        self._data_controller = get_data_access_controller()
        self._register_default_policy()
        self._telemetry = get_telemetry_manager()

    def record_explanation(
        self,
        explanation_type: ExplanationType,
        summary: str,
        context: ExplanationContext,
        expert_notes: Optional[str] = None,
        *,
        domain: str = "unspecified",
        decision_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        rationale: Optional[DecisionRationale] = None,
        guardrail_id: Optional[str] = None,
        guardrail_decision: Optional[str] = None,
        guardrail_rationale: Optional[str] = None,
        latency_domain: Optional[str] = None,
        latency_workflow: Optional[str] = None,
        latency_status: Optional[str] = None,
        latency_observed_ms: Optional[float] = None,
        latency_fallback_strategy: Optional[str] = None,
    ) -> ExplanationRecord:
        if rationale is not None:
            self._validate_rationale(rationale)
        context.inputs = self._sanitize_inputs(context.inputs)
        record = ExplanationRecord(
            record_id=f"expl_{len(self._records) + 1:08d}",
            explanation_type=explanation_type,
            summary=summary,
            expert_notes=expert_notes,
            context=context,
            domain=domain,
            decision_id=decision_id,
            correlation_id=correlation_id,
            rationale=rationale,
            guardrail_id=guardrail_id,
            guardrail_decision=guardrail_decision,
            guardrail_rationale=guardrail_rationale,
            latency_domain=latency_domain,
            latency_workflow=latency_workflow,
            latency_status=latency_status,
            latency_observed_ms=latency_observed_ms,
            latency_fallback_strategy=latency_fallback_strategy,
        )
        self._records.append(record)
        self._coverage_counts[explanation_type.value] = (
            self._coverage_counts.get(explanation_type.value, 0) + 1
        )
        logger.info(
            "Explainability captured type=%s agent=%s summary=%s",
            explanation_type.value,
            context.agent_id,
            summary,
        )
        self._emit_structured_log(record)
        return record

    def record_explainable_result(
        self,
        *,
        domain: str,
        decision_id: str,
        explanation_type: ExplanationType,
        summary: str,
        context: ExplanationContext,
        rationale: DecisionRationale,
        result: Any,
        correlation_id: Optional[str] = None,
        expert_notes: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_decision: Optional[str] = None,
        guardrail_rationale: Optional[str] = None,
        latency_domain: Optional[str] = None,
        latency_workflow: Optional[str] = None,
        latency_status: Optional[str] = None,
        latency_observed_ms: Optional[float] = None,
        latency_fallback_strategy: Optional[str] = None,
    ) -> ExplainableResult:
        self.require_explanation(domain, decision_id, rationale)
        record = self.record_explanation(
            explanation_type,
            summary,
            context,
            expert_notes,
            domain=domain,
            decision_id=decision_id,
            correlation_id=correlation_id,
            rationale=rationale,
            guardrail_id=guardrail_id,
            guardrail_decision=guardrail_decision,
            guardrail_rationale=guardrail_rationale,
            latency_domain=latency_domain,
            latency_workflow=latency_workflow,
            latency_status=latency_status,
            latency_observed_ms=latency_observed_ms,
            latency_fallback_strategy=latency_fallback_strategy,
        )
        return ExplainableResult(result=result, explanation_record=record)

    def require_explanation(
        self,
        domain: str,
        decision_id: str,
        rationale: DecisionRationale,
    ) -> None:
        """Enforce that high-stakes actions ship with a rationale."""

        self._validate_rationale(rationale)
        if not rationale.rules_fired and not rationale.model_evidence:
            raise ExplainabilityViolation(
                f"{domain}:{decision_id} missing rule/model evidence"
            )
        if not rationale.reason:
            raise ExplainabilityViolation(
                f"{domain}:{decision_id} missing human-readable reason"
            )

    def _validate_rationale(self, rationale: DecisionRationale) -> None:
        if not rationale.inputs:
            raise ExplainabilityViolation("Rationale must include inputs snapshot")
        if not rationale.features and not rationale.rules_fired:
            raise ExplainabilityViolation(
                "Rationale must include features or rule evaluations"
            )

    def record_latency(self, latency_seconds: float) -> None:
        self._latency_stats.append(latency_seconds)

    def get_metrics(self) -> Dict[str, Any]:
        if self._latency_stats:
            avg_latency = sum(self._latency_stats) / len(self._latency_stats)
        else:
            avg_latency = 0.0
        return {
            "total_records": len(self._records),
            "coverage": self._coverage_counts.copy(),
            "average_latency_seconds": avg_latency,
        }

    def fetch_recent(self, limit: int = 20) -> List[ExplanationRecord]:
        return self._records[-limit:]

    def _register_default_policy(self) -> None:
        try:
            self._data_controller.register_policy(
                DataAccessPolicy(
                    dataset="explainability_inputs",
                    classification=DataClassification.SENSITIVE,
                    allowed_roles={"explainability"},
                    mask_function=_mask_sensitive_inputs,
                )
            )
        except Exception:
            # If already registered, ignore.
            pass

    def _sanitize_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._data_controller.access(
                "explainability_inputs", "explainability", inputs
            )
        except PermissionError:
            return {}

    def _emit_structured_log(self, record: ExplanationRecord) -> None:
        try:
            self._telemetry.log_structured(
                stream_name="governance",
                level="INFO",
                event_type="explainability_recorded",
                message=record.summary,
                agent_id=record.context.agent_id,
                strategy_id=record.context.strategy,
                correlation_id=record.correlation_id,
                fields={
                    "domain": record.domain,
                    "decision_id": record.decision_id,
                    "explanation_type": record.explanation_type.value,
                    "features": [fa.name for fa in (record.rationale.features if record.rationale else [])],
                    "rules_fired": [rule.rule_name for rule in (record.rationale.rules_fired if record.rationale else [])],
                    "constraints": record.context.constraints,
                    "expected_effect": record.context.expected_effect,
                    "guardrail_id": record.guardrail_id,
                    "guardrail_decision": record.guardrail_decision,
                    "latency": {
                        "domain": record.latency_domain,
                        "workflow": record.latency_workflow,
                        "status": record.latency_status,
                        "observed_ms": record.latency_observed_ms,
                        "fallback_strategy": record.latency_fallback_strategy,
                    },
                },
            )
        except Exception:
            logger.exception("Failed to emit telemetry for explanation %s", record.record_id)


def _mask_sensitive_inputs(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    masked: Dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "secret", "token", "password")):
            masked[key] = "***redacted***"
        else:
            masked[key] = value
    return masked


_service: Optional[ExplainabilityService] = None


def get_explainability_service() -> ExplainabilityService:
    global _service
    if _service is None:
        _service = ExplainabilityService()
    return _service
