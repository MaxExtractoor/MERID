"""
Hybrid Human/AI Decision System for MERID
Human-in-the-loop, human-on-the-loop, and bounded autonomy.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.unified_decision_layer import UnifiedDecision, get_unified_decision_layer
from core.action_handlers import register_default_actions
from core.environment import get_environment_flags
from core.explainability import (
    ExplanationContext,
    ExplanationType,
    get_explainability_service,
)
from core.function_router import get_function_router
from utils.logger import get_logger

logger = get_logger("core.human_ai_interface")
register_default_actions()


class HumanInvolvementLevel(Enum):
    """Levels of human involvement."""
    HUMAN_IN_LOOP = "human_in_loop"  # Human must approve
    HUMAN_ON_LOOP = "human_on_loop"  # Human can override
    HUMAN_OFF_LOOP = "human_off_loop"  # Fully autonomous


class EscalationReason(Enum):
    """Reasons for escalating to human."""
    HIGH_RISK = "high_risk"
    LARGE_SIZE = "large_size"
    NOVEL_SITUATION = "novel_situation"
    REGULATORY_FLAG = "regulatory_flag"
    LOW_CONFIDENCE = "low_confidence"
    AGENT_DISAGREEMENT = "agent_disagreement"
    SYSTEM_ANOMALY = "system_anomaly"


class HumanDecision(Enum):
    """Human decision on escalated item."""
    APPROVE = "approve"
    DENY = "deny"
    MODIFY = "modify"
    DEFER = "defer"


@dataclass
class EscalationTrigger:
    """Configuration for when to escalate to human."""
    reason: EscalationReason
    threshold: float
    enabled: bool
    description: str


@dataclass
class EscalationRequest:
    """Request for human decision."""
    request_id: str
    decision_id: str
    reason: EscalationReason
    ai_recommendation: str
    ai_confidence: float
    context: Dict[str, Any]
    alternatives: List[str]
    risk_assessment: Dict[str, Any]
    timestamp: float
    timeout_seconds: float


@dataclass
class HumanResponse:
    """Human response to escalation."""
    request_id: str
    decision: HumanDecision
    selected_option: Optional[str]
    rationale: str
    modifications: Dict[str, Any]
    timestamp: float
    response_time_seconds: float


class EscalationPolicy:
    """Policy for escalating decisions to humans."""
    
    def __init__(self):
        self._triggers: Dict[EscalationReason, EscalationTrigger] = {
            EscalationReason.HIGH_RISK: EscalationTrigger(
                reason=EscalationReason.HIGH_RISK,
                threshold=0.7,  # Risk score > 0.7
                enabled=True,
                description="High risk score requiring human approval"
            ),
            EscalationReason.LARGE_SIZE: EscalationTrigger(
                reason=EscalationReason.LARGE_SIZE,
                threshold=100000.0,  # Size > $100k
                enabled=True,
                description="Large transaction size requiring human approval"
            ),
            EscalationReason.NOVEL_SITUATION: EscalationTrigger(
                reason=EscalationReason.NOVEL_SITUATION,
                threshold=0.8,  # Novelty score > 0.8
                enabled=True,
                description="Novel situation not seen in training"
            ),
            EscalationReason.REGULATORY_FLAG: EscalationTrigger(
                reason=EscalationReason.REGULATORY_FLAG,
                threshold=0.0,  # Any regulatory flag
                enabled=True,
                description="Regulatory compliance flag"
            ),
            EscalationReason.LOW_CONFIDENCE: EscalationTrigger(
                reason=EscalationReason.LOW_CONFIDENCE,
                threshold=0.5,  # Confidence < 0.5
                enabled=True,
                description="AI confidence below threshold"
            ),
            EscalationReason.AGENT_DISAGREEMENT: EscalationTrigger(
                reason=EscalationReason.AGENT_DISAGREEMENT,
                threshold=0.4,  # Agreement < 0.4
                enabled=True,
                description="Significant disagreement among agents"
            )
        }
    
    def should_escalate(
        self,
        decision: UnifiedDecision,
        context: Dict[str, Any]
    ) -> Optional[EscalationReason]:
        """Determine if decision should be escalated."""
        # Check each trigger
        for reason, trigger in self._triggers.items():
            if not trigger.enabled:
                continue
            
            if reason == EscalationReason.HIGH_RISK:
                risk_score = context.get("risk_score", 0.0)
                if risk_score > trigger.threshold:
                    return reason
            
            elif reason == EscalationReason.LARGE_SIZE:
                size = context.get("size", 0.0)
                if size > trigger.threshold:
                    return reason
            
            elif reason == EscalationReason.NOVEL_SITUATION:
                novelty = context.get("novelty_score", 0.0)
                if novelty > trigger.threshold:
                    return reason
            
            elif reason == EscalationReason.REGULATORY_FLAG:
                if context.get("regulatory_flag", False):
                    return reason
            
            elif reason == EscalationReason.LOW_CONFIDENCE:
                if decision.confidence < trigger.threshold:
                    return reason
            
            elif reason == EscalationReason.AGENT_DISAGREEMENT:
                agreement = context.get("agreement_score", 1.0)
                if agreement < trigger.threshold:
                    return reason
        
        return None
    
    def update_trigger(
        self,
        reason: EscalationReason,
        threshold: Optional[float] = None,
        enabled: Optional[bool] = None
    ) -> None:
        """Update an escalation trigger."""
        if reason not in self._triggers:
            return
        
        trigger = self._triggers[reason]
        
        if threshold is not None:
            trigger.threshold = threshold
        if enabled is not None:
            trigger.enabled = enabled
        
        logger.info(f"Updated escalation trigger {reason.value}: threshold={trigger.threshold}, enabled={trigger.enabled}")


class HumanInTheLoop:
    """Human-in-the-loop decision flow."""
    
    def __init__(self, timeout_seconds: float = 300.0):
        self.timeout_seconds = timeout_seconds
        self._pending_requests: Dict[str, EscalationRequest] = {}
        self._responses: Dict[str, HumanResponse] = {}
        self._request_counter = 0
    
    async def request_approval(
        self,
        decision: UnifiedDecision,
        reason: EscalationReason,
        context: Dict[str, Any]
    ) -> HumanResponse:
        """Request human approval for a decision."""
        self._request_counter += 1
        request_id = f"hitl_{self._request_counter}_{int(time.time())}"
        
        # Create escalation request
        request = EscalationRequest(
            request_id=request_id,
            decision_id=decision.decision_id,
            reason=reason,
            ai_recommendation=decision.final_decision,
            ai_confidence=decision.confidence,
            context=context,
            alternatives=self._generate_alternatives(decision),
            risk_assessment=self._assess_risk(decision, context),
            timestamp=time.time(),
            timeout_seconds=self.timeout_seconds
        )
        
        self._pending_requests[request_id] = request
        
        logger.info(
            f"Escalated decision {decision.decision_id} to human: {reason.value} "
            f"(AI recommendation: {decision.final_decision}, confidence: {decision.confidence:.2f})"
        )
        
        # Wait for human response
        try:
            response = await asyncio.wait_for(
                self._wait_for_response(request_id),
                timeout=self.timeout_seconds
            )
            
            logger.info(
                f"Human response received for {request_id}: {response.decision.value} "
                f"(response time: {response.response_time_seconds:.1f}s)"
            )
            
            return response
            
        except asyncio.TimeoutError:
            logger.warning(f"Human response timed out for {request_id}, using default action")
            
            # Default action on timeout (deny for safety)
            response = HumanResponse(
                request_id=request_id,
                decision=HumanDecision.DENY,
                selected_option=None,
                rationale="Timeout - no human response received",
                modifications={},
                timestamp=time.time(),
                response_time_seconds=self.timeout_seconds
            )
            
            self._responses[request_id] = response
            return response
    
    def submit_response(
        self,
        request_id: str,
        decision: HumanDecision,
        selected_option: Optional[str] = None,
        rationale: str = "",
        modifications: Optional[Dict[str, Any]] = None
    ) -> None:
        """Submit human response to escalation."""
        if request_id not in self._pending_requests:
            logger.error(f"Request {request_id} not found")
            return
        
        request = self._pending_requests[request_id]
        
        response = HumanResponse(
            request_id=request_id,
            decision=decision,
            selected_option=selected_option,
            rationale=rationale,
            modifications=modifications or {},
            timestamp=time.time(),
            response_time_seconds=time.time() - request.timestamp
        )
        
        self._responses[request_id] = response
        del self._pending_requests[request_id]
    
    async def _wait_for_response(self, request_id: str) -> HumanResponse:
        """Wait for human response."""
        while request_id not in self._responses:
            await asyncio.sleep(0.5)
        
        return self._responses[request_id]
    
    def _generate_alternatives(self, decision: UnifiedDecision) -> List[str]:
        """Generate alternative options for human."""
        alternatives = [decision.final_decision]
        
        # Add other agent recommendations
        for contrib in decision.contributions:
            if contrib.recommendation != decision.final_decision:
                if contrib.recommendation not in alternatives:
                    alternatives.append(contrib.recommendation)
        
        return alternatives[:5]  # Top 5
    
    def _assess_risk(
        self,
        decision: UnifiedDecision,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Assess risk of decision."""
        return {
            "risk_score": context.get("risk_score", 0.5),
            "potential_loss": context.get("potential_loss", 0.0),
            "reversibility": context.get("reversible", True),
            "impact_scope": context.get("impact_scope", "limited")
        }
    
    def get_pending_requests(self) -> List[EscalationRequest]:
        """Get all pending requests."""
        return list(self._pending_requests.values())


class HumanOnTheLoop:
    """Human-on-the-loop monitoring and override."""
    
    def __init__(self):
        self._overrides: List[Dict[str, Any]] = []
        self._emergency_stop = False
    
    def emergency_stop(self, reason: str) -> None:
        """Trigger emergency stop."""
        self._emergency_stop = True
        
        override = {
            "type": "emergency_stop",
            "reason": reason,
            "timestamp": time.time()
        }
        
        self._overrides.append(override)
        
        logger.critical(f"EMERGENCY STOP triggered: {reason}")
    
    def override_decision(
        self,
        decision_id: str,
        new_decision: str,
        reason: str
    ) -> None:
        """Override an AI decision."""
        override = {
            "type": "decision_override",
            "decision_id": decision_id,
            "new_decision": new_decision,
            "reason": reason,
            "timestamp": time.time()
        }
        
        self._overrides.append(override)
        
        logger.warning(f"Human override: {decision_id} -> {new_decision} ({reason})")
    
    def adjust_risk_limits(
        self,
        limit_type: str,
        new_value: float,
        reason: str
    ) -> None:
        """Adjust risk limits."""
        override = {
            "type": "risk_limit_adjustment",
            "limit_type": limit_type,
            "new_value": new_value,
            "reason": reason,
            "timestamp": time.time()
        }
        
        self._overrides.append(override)
        
        logger.info(f"Risk limit adjusted: {limit_type} = {new_value} ({reason})")
    
    def pause_strategy(self, strategy_id: str, reason: str) -> None:
        """Pause a strategy."""
        override = {
            "type": "strategy_pause",
            "strategy_id": strategy_id,
            "reason": reason,
            "timestamp": time.time()
        }
        
        self._overrides.append(override)
        
        logger.warning(f"Strategy paused: {strategy_id} ({reason})")
    
    def is_emergency_stopped(self) -> bool:
        """Check if emergency stop is active."""
        return self._emergency_stop
    
    def clear_emergency_stop(self, reason: str) -> None:
        """Clear emergency stop."""
        self._emergency_stop = False
        
        logger.info(f"Emergency stop cleared: {reason}")
    
    def get_override_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get override history."""
        return self._overrides[-limit:]


class BoundedAutonomy:
    """Bounded autonomy with safety constraints."""
    
    def __init__(self):
        self._safe_zones: Dict[str, Dict[str, Any]] = {}
        self._kill_switches: Dict[str, bool] = {}
    
    def define_safe_zone(
        self,
        zone_id: str,
        constraints: Dict[str, Any]
    ) -> None:
        """Define a safe operating zone."""
        self._safe_zones[zone_id] = {
            "constraints": constraints,
            "created_at": time.time(),
            "violations": 0
        }
        
        logger.info(f"Defined safe zone: {zone_id}")
    
    def is_within_safe_zone(
        self,
        zone_id: str,
        parameters: Dict[str, Any]
    ) -> bool:
        """Check if parameters are within safe zone."""
        if zone_id not in self._safe_zones:
            return False
        
        zone = self._safe_zones[zone_id]
        constraints = zone["constraints"]
        
        for param, value in parameters.items():
            if param not in constraints:
                continue
            
            constraint = constraints[param]
            
            if "min" in constraint and value < constraint["min"]:
                zone["violations"] += 1
                return False
            
            if "max" in constraint and value > constraint["max"]:
                zone["violations"] += 1
                return False
        
        return True
    
    def register_kill_switch(self, switch_id: str) -> None:
        """Register a kill switch."""
        self._kill_switches[switch_id] = False
        logger.info(f"Registered kill switch: {switch_id}")
    
    def activate_kill_switch(self, switch_id: str, reason: str) -> None:
        """Activate a kill switch."""
        if switch_id in self._kill_switches:
            self._kill_switches[switch_id] = True
            logger.critical(f"Kill switch activated: {switch_id} ({reason})")
    
    def is_kill_switch_active(self, switch_id: str) -> bool:
        """Check if kill switch is active."""
        return self._kill_switches.get(switch_id, False)


class HumanAIInterface:
    """Main interface for hybrid human/AI decisions."""
    
    def __init__(self):
        self._escalation_policy = EscalationPolicy()
        self._human_in_loop = HumanInTheLoop()
        self._human_on_loop = HumanOnTheLoop()
        self._bounded_autonomy = BoundedAutonomy()
        self._decision_layer = get_unified_decision_layer()
        self._explainability = get_explainability_service()
        self._function_router = get_function_router()
    
    async def make_decision_with_human_oversight(
        self,
        decision_type: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make decision with appropriate human oversight."""
        # Check emergency stop
        if self._human_on_loop.is_emergency_stopped():
            return {
                "decision": "blocked",
                "reason": "emergency_stop_active",
                "confidence": 0.0
            }
        
        # Get AI decision
        decision_start = time.time()
        ai_decision = self._decision_layer.make_decision(decision_type, context)
        
        # Check if escalation needed
        escalation_reason = self._escalation_policy.should_escalate(ai_decision, context)
        
        if escalation_reason:
            # Human-in-the-loop
            human_response = await self._human_in_loop.request_approval(
                ai_decision,
                escalation_reason,
                context
            )
            
            if human_response.decision == HumanDecision.APPROVE:
                result = {
                    "decision": ai_decision.final_decision,
                    "confidence": ai_decision.confidence,
                    "human_approved": True,
                    "human_rationale": human_response.rationale
                }
                self._route_action_if_needed(decision_type, context, result)
                self._record_explanation_entry(
                    decision_type,
                    ai_decision,
                    context,
                    result,
                    decision_start,
                    human_response,
                    escalation_reason,
                )
                return result
            elif human_response.decision == HumanDecision.MODIFY:
                result = {
                    "decision": human_response.selected_option or ai_decision.final_decision,
                    "confidence": 1.0,
                    "human_modified": True,
                    "modifications": human_response.modifications,
                    "human_rationale": human_response.rationale
                }
                self._route_action_if_needed(decision_type, context, result)
                self._record_explanation_entry(
                    decision_type,
                    ai_decision,
                    context,
                    result,
                    decision_start,
                    human_response,
                    escalation_reason,
                )
                return result
            else:
                result = {
                    "decision": "denied",
                    "confidence": 0.0,
                    "human_denied": True,
                    "human_rationale": human_response.rationale
                }
                self._route_action_if_needed(decision_type, context, result)
                self._record_explanation_entry(
                    decision_type,
                    ai_decision,
                    context,
                    result,
                    decision_start,
                    human_response,
                    escalation_reason,
                )
                return result
        else:
            # Autonomous decision (human-off-the-loop)
            result = {
                "decision": ai_decision.final_decision,
                "confidence": ai_decision.confidence,
                "autonomous": True
            }
            self._route_action_if_needed(decision_type, context, result)
            self._record_explanation_entry(
                decision_type,
                ai_decision,
                context,
                result,
                decision_start,
                None,
                None,
            )
            return result
    
    def get_escalation_policy(self) -> EscalationPolicy:
        """Get escalation policy."""
        return self._escalation_policy
    
    def get_human_in_loop(self) -> HumanInTheLoop:
        """Get human-in-the-loop interface."""
        return self._human_in_loop
    
    def get_human_on_loop(self) -> HumanOnTheLoop:
        """Get human-on-the-loop interface."""
        return self._human_on_loop
    
    def get_bounded_autonomy(self) -> BoundedAutonomy:
        """Get bounded autonomy manager."""
        return self._bounded_autonomy
    
    def _route_action_if_needed(
        self,
        decision_type: str,
        context: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """Route actions through the function router if requested."""
        func_name = context.get("function_name")
        if not func_name:
            return
        payload = context.get("function_payload", {})
        caller_role = context.get("caller_role", "agent")
        router_result = self._function_router.call(
            func_name,
            payload,
            caller=f"human_ai:{decision_type}",
            role=caller_role,
        )
        result["execution_guard"] = router_result

    def _record_explanation_entry(
        self,
        decision_type: str,
        ai_decision: UnifiedDecision,
        context: Dict[str, Any],
        result: Dict[str, Any],
        start_time: float,
        human_response: Optional[HumanResponse],
        escalation_reason: Optional[EscalationReason],
    ) -> None:
        """Record explanations for human/AI interactions."""
        try:
            flags = get_environment_flags()
            env_dict = {
                "online": flags.online,
                "routing_profile": flags.enforced_routing_profile.value,
                "vpn_only": flags.vpn_only,
                "privacy_mode": flags.privacy_mode,
            }
            summary = f"{decision_type} -> {result.get('decision')}"
            constraints = {
                "priority": ai_decision.priority.value,
                "aggregation_method": ai_decision.aggregation_method,
                "escalation_reason": escalation_reason.value if escalation_reason else None,
                "human_decision": human_response.decision.value if human_response else None,
            }
            expected_effect = {
                "decision": result.get("decision"),
                "confidence": result.get("confidence"),
                "human_involved": human_response is not None,
            }
            explanation_context = ExplanationContext(
                inputs=context,
                agent_id="human_ai_interface",
                strategy=context.get("strategy"),
                constraints=constraints,
                expected_effect=expected_effect,
                environment_flags=env_dict,
            )
            exp_type = self._map_explanation_type(decision_type)
            notes_parts = [ai_decision.reasoning_summary or "no_ai_reasoning"]
            if human_response:
                notes_parts.append(f"Human: {human_response.rationale}")
            record = self._explainability.record_explanation(
                explanation_type=exp_type,
                summary=summary,
                context=explanation_context,
                expert_notes=" | ".join(notes_parts),
            )
            latency = time.time() - start_time
            self._explainability.record_latency(latency)
            logger.debug(
                "Explainability (human interface) record %s stored (latency %.3fs)",
                record.record_id,
                latency,
            )
        except Exception as exc:
            logger.error("Failed to capture human/AI explanation: %s", exc)

    def _map_explanation_type(self, decision_type: str) -> ExplanationType:
        """Map decision type to explanation type."""
        lower = decision_type.lower()
        if "order" in lower or "trade" in lower:
            return ExplanationType.ORDER
        if "cancel" in lower:
            return ExplanationType.CANCEL
        if "payment" in lower or "x402" in lower:
            return ExplanationType.X402_PAYMENT
        if "promotion" in lower:
            return ExplanationType.PROMOTION
        if "demotion" in lower:
            return ExplanationType.DEMOTION
        if "safe" in lower:
            return ExplanationType.SAFE_MODE
        return ExplanationType.PARAM_CHANGE


# Global interface
_human_ai_interface: Optional[HumanAIInterface] = None


def get_human_ai_interface() -> HumanAIInterface:
    """Get the global human/AI interface."""
    global _human_ai_interface
    if _human_ai_interface is None:
        _human_ai_interface = HumanAIInterface()
    return _human_ai_interface
