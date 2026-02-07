"""Marketing Swarm explainability contract and adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from core.explainability import (
    CounterfactualScenario,
    DecisionRationale,
    ExplanationContext,
    ExplanationType,
    FeatureAttribution,
    ModelEvidence,
    RuleEvaluation,
    ExplainabilityService,
    ExplainableResult,
    get_explainability_service,
)


@dataclass
class MarketingDecisionInputs:
    """Snapshot of marketing signals used for a decision."""

    segment_traits: Dict[str, Any]
    engagement_metrics: Dict[str, Any]
    budget_state: Dict[str, Any]
    compliance_flags: Dict[str, Any]


@dataclass
class MarketingDecisionContext:
    """Metadata required to construct ExplanationContext objects."""

    agent_id: str
    strategy: Optional[str]
    campaign_id: str
    segment_id: str
    channel: str
    tools_invoked: List[str] = field(default_factory=list)
    alternatives_considered: List[str] = field(default_factory=list)
    environment_flags: Dict[str, Any] = field(default_factory=dict)

    def to_explanation_context(
        self,
        inputs: Dict[str, Any],
        constraints: Dict[str, Any],
        expected_effect: Dict[str, Any],
    ) -> ExplanationContext:
        return ExplanationContext(
            inputs=inputs,
            agent_id=self.agent_id,
            strategy=self.strategy,
            constraints=constraints,
            expected_effect=expected_effect,
            environment_flags=self.environment_flags,
            tools_invoked=self.tools_invoked,
            alternatives_considered=self.alternatives_considered,
        )


@dataclass
class MarketingDecisionExplanation:
    """Structured explanation payload for marketing swarm actions."""

    reason: str
    inputs: MarketingDecisionInputs
    rules: Sequence[RuleEvaluation]
    features: Sequence[FeatureAttribution]
    model_evidence: Sequence[ModelEvidence]
    constraints: Dict[str, Any]
    counterfactuals: Sequence[CounterfactualScenario] = field(default_factory=list)
    telemetry_refs: List[str] = field(default_factory=list)

    def to_decision_rationale(self) -> DecisionRationale:
        return DecisionRationale(
            reason=self.reason,
            inputs={
                "segment_traits": self.inputs.segment_traits,
                "engagement_metrics": self.inputs.engagement_metrics,
                "budget_state": self.inputs.budget_state,
                "compliance_flags": self.inputs.compliance_flags,
            },
            features=list(self.features),
            rules_fired=list(self.rules),
            model_evidence=list(self.model_evidence),
            constraints=self.constraints,
            counterfactuals=list(self.counterfactuals),
            telemetry_refs=list(self.telemetry_refs),
        )


class MarketingExplainabilityAdapter:
    """High-level helper enforcing explainability for marketing swarm decisions."""

    def __init__(self, service: Optional[ExplainabilityService] = None) -> None:
        self._service = service or get_explainability_service()

    def record_decision(
        self,
        *,
        decision_id: str,
        explanation_type: ExplanationType,
        context: MarketingDecisionContext,
        explanation: MarketingDecisionExplanation,
        result_payload: Any,
        correlation_id: Optional[str] = None,
        expert_notes: Optional[str] = None,
    ) -> ExplainableResult:
        domain = "marketing_swarm"
        rationale = explanation.to_decision_rationale()
        return self._service.record_explainable_result(
            domain=domain,
            decision_id=decision_id,
            explanation_type=explanation_type,
            summary=explanation.reason,
            context=context.to_explanation_context(
                inputs=rationale.inputs,
                constraints=rationale.constraints,
                expected_effect={"campaign_id": context.campaign_id, "segment_id": context.segment_id},
            ),
            rationale=rationale,
            result=result_payload,
            correlation_id=correlation_id,
            expert_notes=expert_notes,
        )
