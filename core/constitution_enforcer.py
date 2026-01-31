"""
Constitution and Contract Enforcer for MERID

Validates that all agent actions comply with the Global Agent Constitution
and governance contracts. Integrates with ExecutionGuard and provides
compliance monitoring and violation handling.
"""
from __future__ import annotations

import time
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.environment_flags import get_environment_flags
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from utils.logger import get_logger

logger = get_logger("core.constitution_enforcer")


class ViolationType(str, Enum):
    """Types of constitution violations."""
    BYPASS_GUARD = "bypass_guard"
    SECRET_ACCESS = "secret_access"
    OFFLINE_VIOLATION = "offline_violation"
    SAFE_MODE_VIOLATION = "safe_mode_violation"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    UNAUTHORIZED_ACTION = "unauthorized_action"
    CONTRACT_BREACH = "contract_breach"


class ViolationSeverity(str, Enum):
    """Severity levels for violations."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Violation:
    """Record of a constitution or contract violation."""
    violation_id: str
    violation_type: ViolationType
    severity: ViolationSeverity
    agent_id: str
    action_type: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    handled: bool = False
    handler_response: Optional[str] = None


@dataclass
class AgentCharter:
    """Charter defining an agent's role and constraints."""
    agent_id: str
    role: str
    purpose: str
    allowed_actions: List[str]
    prohibited_actions: List[str]
    constraints: Dict[str, Any]
    swarm_type: str  # "research" or "production"


class ConstitutionEnforcer:
    """
    Enforces the Global Agent Constitution and governance contracts.
    
    Responsibilities:
    - Validate agent actions against constitution
    - Check compliance with governance contracts
    - Monitor and log violations
    - Trigger safe mode on critical violations
    - Integrate with ExecutionGuard
    """
    
    def __init__(self, contracts_dir: str = "contracts"):
        self._contracts_dir = Path(contracts_dir)
        self._env_flags = get_environment_flags()
        self._explainability = get_explainability_service()
        
        # Load contracts
        self._risk_contract: Dict[str, Any] = {}
        self._model_contract: Dict[str, Any] = {}
        self._slo_contract: Dict[str, Any] = {}
        self._safe_mode_contract: Dict[str, Any] = {}
        
        self._load_contracts()
        
        # Agent charters
        self._agent_charters: Dict[str, AgentCharter] = {}
        self._register_default_charters()
        
        # Violation tracking
        self._violations: List[Violation] = []
        self._violation_counter = 0
        
        # Safe mode state
        self._safe_mode_active = False
        self._safe_mode_level = 0
        
        logger.info("ConstitutionEnforcer initialized")
    
    def _load_contracts(self) -> None:
        """Load governance contracts from YAML files."""
        try:
            risk_path = self._contracts_dir / "risk_capital_contract.yaml"
            if risk_path.exists():
                with open(risk_path, 'r') as f:
                    self._risk_contract = yaml.safe_load(f)
                logger.info("Loaded risk & capital contract")
            
            model_path = self._contracts_dir / "model_deployment_contract.yaml"
            if model_path.exists():
                with open(model_path, 'r') as f:
                    self._model_contract = yaml.safe_load(f)
                logger.info("Loaded model & deployment contract")
            
            slo_path = self._contracts_dir / "operational_slo_contract.yaml"
            if slo_path.exists():
                with open(slo_path, 'r') as f:
                    self._slo_contract = yaml.safe_load(f)
                logger.info("Loaded operational SLO contract")
            
            safe_mode_path = self._contracts_dir / "safe_mode_contract.yaml"
            if safe_mode_path.exists():
                with open(safe_mode_path, 'r') as f:
                    self._safe_mode_contract = yaml.safe_load(f)
                logger.info("Loaded safe mode contract")
        
        except Exception as e:
            logger.error("Failed to load contracts: %s", e)
    
    def _register_default_charters(self) -> None:
        """Register default agent charters."""
        # Strategy agents
        self.register_charter(AgentCharter(
            agent_id="strategy_*",
            role="strategy",
            purpose="Propose trades within risk limits",
            allowed_actions=["propose_order", "analyze_market", "generate_signal"],
            prohibited_actions=["execute_order", "access_secrets", "modify_limits"],
            constraints={
                "must_check_risk_limits": True,
                "must_provide_explanation": True,
                "must_respect_offline": True,
            },
            swarm_type="production",
        ))
        
        # Risk agents
        self.register_charter(AgentCharter(
            agent_id="risk_*",
            role="risk",
            purpose="Monitor and enforce risk limits",
            allowed_actions=["veto_trade", "adjust_limits", "trigger_safe_mode"],
            prohibited_actions=["initiate_trade", "access_secrets"],
            constraints={
                "can_veto_any_trade": True,
                "must_maintain_global_caps": True,
            },
            swarm_type="production",
        ))
        
        # Execution agents
        self.register_charter(AgentCharter(
            agent_id="execution_*",
            role="execution",
            purpose="Execute approved trade intents",
            allowed_actions=["place_order", "route_order", "report_fill"],
            prohibited_actions=["bypass_guard", "access_secrets_directly"],
            constraints={
                "requires_guard_approval": True,
                "must_use_network_client": True,
            },
            swarm_type="production",
        ))
        
        # Observer agents
        self.register_charter(AgentCharter(
            agent_id="observer_*",
            role="observer",
            purpose="Log and annotate (read-only)",
            allowed_actions=["read_data", "log_event", "annotate"],
            prohibited_actions=["execute_order", "modify_state", "influence_trades"],
            constraints={
                "strictly_read_only": True,
            },
            swarm_type="production",
        ))
        
        # UI/Explainer agents
        self.register_charter(AgentCharter(
            agent_id="explainer_*",
            role="explainer",
            purpose="Provide explanations and summaries",
            allowed_actions=["generate_explanation", "summarize", "visualize"],
            prohibited_actions=["initiate_trade", "change_parameters", "access_secrets"],
            constraints={
                "read_only_access": True,
            },
            swarm_type="production",
        ))
    
    def register_charter(self, charter: AgentCharter) -> None:
        """Register an agent charter."""
        self._agent_charters[charter.agent_id] = charter
        logger.info("Registered charter for %s", charter.agent_id)
    
    def _get_charter(self, agent_id: str) -> Optional[AgentCharter]:
        """Get charter for agent, supporting wildcards."""
        # Exact match
        if agent_id in self._agent_charters:
            return self._agent_charters[agent_id]
        
        # Wildcard match
        for charter_id, charter in self._agent_charters.items():
            if charter_id.endswith("*"):
                prefix = charter_id[:-1]
                if agent_id.startswith(prefix):
                    return charter
        
        return None
    
    def validate_action(
        self,
        agent_id: str,
        action_type: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate an agent action against constitution and contracts.
        
        Returns:
            Dict with 'approved', 'reason', 'violations'
        """
        violations = []
        
        # Article I.1: Never bypass Execution Guard
        if action_type in ["execute_order", "send_transaction"] and not parameters.get("guard_approved"):
            violations.append(self._record_violation(
                ViolationType.BYPASS_GUARD,
                ViolationSeverity.CRITICAL,
                agent_id,
                action_type,
                {"reason": "Attempted to bypass Execution Guard"},
            ))
        
        # Article I.2: Never access raw secrets
        if any(key in parameters for key in ["private_key", "seed_phrase", "api_secret"]):
            violations.append(self._record_violation(
                ViolationType.SECRET_ACCESS,
                ViolationSeverity.CRITICAL,
                agent_id,
                action_type,
                {"reason": "Attempted to access raw secrets"},
            ))
        
        # Article I.3: Respect offline/VPN flags
        if self._env_flags.offline_mode and parameters.get("requires_network", False):
            violations.append(self._record_violation(
                ViolationType.OFFLINE_VIOLATION,
                ViolationSeverity.ERROR,
                agent_id,
                action_type,
                {"reason": "Attempted network call in offline mode"},
            ))
        
        # Article I.3: Respect safe-mode status
        if self._safe_mode_active:
            if not self._is_action_allowed_in_safe_mode(action_type):
                violations.append(self._record_violation(
                    ViolationType.SAFE_MODE_VIOLATION,
                    ViolationSeverity.CRITICAL,
                    agent_id,
                    action_type,
                    {"reason": f"Action not allowed in safe mode level {self._safe_mode_level}"},
                ))
        
        # Check agent charter
        charter = self._get_charter(agent_id)
        if charter:
            if action_type in charter.prohibited_actions:
                violations.append(self._record_violation(
                    ViolationType.UNAUTHORIZED_ACTION,
                    ViolationSeverity.ERROR,
                    agent_id,
                    action_type,
                    {"reason": f"Action prohibited by charter for role {charter.role}"},
                ))
            
            if charter.allowed_actions and action_type not in charter.allowed_actions:
                violations.append(self._record_violation(
                    ViolationType.UNAUTHORIZED_ACTION,
                    ViolationSeverity.WARNING,
                    agent_id,
                    action_type,
                    {"reason": f"Action not in allowed list for role {charter.role}"},
                ))
        
        # Check risk limits
        if action_type == "propose_order":
            risk_violations = self._check_risk_limits(agent_id, parameters)
            violations.extend(risk_violations)
        
        # Determine approval
        critical_violations = [v for v in violations if v.severity == ViolationSeverity.CRITICAL]
        error_violations = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        
        approved = len(critical_violations) == 0 and len(error_violations) == 0
        
        if not approved:
            reason = "; ".join([
                f"{v.violation_type.value}: {v.details.get('reason', '')}"
                for v in (critical_violations + error_violations)
            ])
        else:
            reason = "Compliant with constitution and contracts"
        
        # Trigger safe mode on critical violations
        if critical_violations:
            self._trigger_safe_mode_on_violation(critical_violations[0])
        
        return {
            "approved": approved,
            "reason": reason,
            "violations": [
                {
                    "type": v.violation_type.value,
                    "severity": v.severity.value,
                    "details": v.details,
                }
                for v in violations
            ],
        }
    
    def _check_risk_limits(
        self,
        agent_id: str,
        parameters: Dict[str, Any],
    ) -> List[Violation]:
        """Check if action complies with risk & capital contract."""
        violations = []
        
        if not self._risk_contract:
            return violations
        
        size = parameters.get("size", 0.0)
        asset = parameters.get("asset", "")
        
        # Check global limits
        global_limits = self._risk_contract.get("global_limits", {})
        max_order_size = self._risk_contract.get("execution_limits", {}).get("max_order_size_usd", float('inf'))
        
        if size > max_order_size:
            violations.append(self._record_violation(
                ViolationType.RISK_LIMIT_EXCEEDED,
                ViolationSeverity.ERROR,
                agent_id,
                "propose_order",
                {
                    "reason": f"Order size {size} exceeds max {max_order_size}",
                    "limit_type": "max_order_size",
                },
            ))
        
        # Check allowed assets
        allowed_assets = self._risk_contract.get("allowed_assets", {})
        all_allowed = (
            allowed_assets.get("crypto_majors", []) +
            allowed_assets.get("stablecoins", []) +
            allowed_assets.get("defi_tokens", []) +
            allowed_assets.get("xstocks", [])
        )
        
        if asset and asset not in all_allowed:
            violations.append(self._record_violation(
                ViolationType.RISK_LIMIT_EXCEEDED,
                ViolationSeverity.WARNING,
                agent_id,
                "propose_order",
                {
                    "reason": f"Asset {asset} not in allowed universe",
                    "limit_type": "allowed_assets",
                },
            ))
        
        return violations
    
    def _is_action_allowed_in_safe_mode(self, action_type: str) -> bool:
        """Check if action is allowed in current safe mode."""
        if not self._safe_mode_contract:
            return True
        
        allowed = self._safe_mode_contract.get("allowed_actions", {})
        prohibited = self._safe_mode_contract.get("prohibited_actions", {})
        
        # Check allowed actions
        for category, actions in allowed.items():
            if action_type in actions:
                return True
        
        # Check prohibited actions
        for category, actions in prohibited.items():
            if action_type in actions:
                return False
        
        # Default: allow monitoring/read-only, deny trading
        if action_type in ["read_data", "log_event", "generate_report"]:
            return True
        
        return False
    
    def _record_violation(
        self,
        violation_type: ViolationType,
        severity: ViolationSeverity,
        agent_id: str,
        action_type: str,
        details: Dict[str, Any],
    ) -> Violation:
        """Record a constitution or contract violation."""
        self._violation_counter += 1
        violation_id = f"viol_{self._violation_counter:08d}_{int(time.time())}"
        
        violation = Violation(
            violation_id=violation_id,
            violation_type=violation_type,
            severity=severity,
            agent_id=agent_id,
            action_type=action_type,
            details=details,
        )
        
        self._violations.append(violation)
        
        # Log violation
        logger.warning(
            "Constitution violation: %s by %s - %s",
            violation_type.value,
            agent_id,
            details.get("reason", ""),
        )
        
        # Record explanation
        self._explainability.record_explanation(
            explanation_type=ExplanationType.GOVERNANCE_DECISION,
            summary=f"Constitution violation: {violation_type.value}",
            context=ExplanationContext(
                inputs={
                    "agent_id": agent_id,
                    "action_type": action_type,
                    "violation_type": violation_type.value,
                },
                agent_id=agent_id,
                strategy=None,
                constraints=details,
                expected_effect={"violation_recorded": True},
                environment_flags={},
            ),
            expert_notes=details.get("reason", ""),
        )
        
        return violation
    
    def _trigger_safe_mode_on_violation(self, violation: Violation) -> None:
        """Trigger safe mode due to critical violation."""
        if not self._safe_mode_active:
            self._safe_mode_active = True
            self._safe_mode_level = 2  # Defensive
            
            logger.critical(
                "Safe mode triggered by violation: %s",
                violation.violation_type.value,
            )
            
            # Record explanation
            self._explainability.record_explanation(
                explanation_type=ExplanationType.GOVERNANCE_DECISION,
                summary=f"Safe mode triggered by {violation.violation_type.value}",
                context=ExplanationContext(
                    inputs={
                        "violation_id": violation.violation_id,
                        "agent_id": violation.agent_id,
                    },
                    agent_id="constitution_enforcer",
                    strategy=None,
                    constraints={"safe_mode_level": self._safe_mode_level},
                    expected_effect={"safe_mode_active": True},
                    environment_flags={},
                ),
                expert_notes=f"Triggered by: {violation.details.get('reason', '')}",
            )
    
    def activate_safe_mode(self, level: int, reason: str) -> None:
        """Manually activate safe mode."""
        self._safe_mode_active = True
        self._safe_mode_level = level
        
        logger.warning("Safe mode activated: level %d - %s", level, reason)
    
    def deactivate_safe_mode(self, approver: str) -> Dict[str, Any]:
        """Deactivate safe mode (requires approval)."""
        if not self._safe_mode_active:
            return {"success": False, "reason": "Safe mode not active"}
        
        # Check exit conditions from contract
        # In production, would verify all conditions
        
        self._safe_mode_active = False
        self._safe_mode_level = 0
        
        logger.info("Safe mode deactivated by %s", approver)
        
        return {"success": True, "deactivated_by": approver}
    
    def get_violations(
        self,
        limit: int = 50,
        severity: Optional[ViolationSeverity] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent violations."""
        violations = self._violations
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        return [
            {
                "violation_id": v.violation_id,
                "type": v.violation_type.value,
                "severity": v.severity.value,
                "agent_id": v.agent_id,
                "action_type": v.action_type,
                "details": v.details,
                "timestamp": v.timestamp,
                "handled": v.handled,
            }
            for v in violations[-limit:]
        ]
    
    def get_compliance_stats(self) -> Dict[str, Any]:
        """Get compliance statistics."""
        total = len(self._violations)
        
        by_type = {}
        by_severity = {}
        by_agent = {}
        
        for v in self._violations:
            by_type[v.violation_type.value] = by_type.get(v.violation_type.value, 0) + 1
            by_severity[v.severity.value] = by_severity.get(v.severity.value, 0) + 1
            by_agent[v.agent_id] = by_agent.get(v.agent_id, 0) + 1
        
        return {
            "total_violations": total,
            "by_type": by_type,
            "by_severity": by_severity,
            "by_agent": by_agent,
            "safe_mode_active": self._safe_mode_active,
            "safe_mode_level": self._safe_mode_level,
            "charters_registered": len(self._agent_charters),
        }


# Singleton instance
_constitution_enforcer: Optional[ConstitutionEnforcer] = None


def get_constitution_enforcer() -> ConstitutionEnforcer:
    """Get the singleton constitution enforcer."""
    global _constitution_enforcer
    if _constitution_enforcer is None:
        _constitution_enforcer = ConstitutionEnforcer()
    return _constitution_enforcer
