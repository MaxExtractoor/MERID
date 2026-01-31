"""
Measurable sovereignty goals and metrics for MERID.

Defines concrete, measurable sovereignty goals for custody, governance,
infrastructure independence, forkability, and offline robustness.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class SovereigntyDomain(Enum):
    """Sovereignty domain."""
    CUSTODY = "custody"
    GOVERNANCE = "governance"
    INFRASTRUCTURE = "infrastructure"
    FORKABILITY = "forkability"
    OFFLINE_ROBUSTNESS = "offline_robustness"


class ComplianceStatus(Enum):
    """Compliance status."""
    COMPLIANT = "compliant"
    PARTIAL = "partial"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class SovereigntyGoal:
    """Sovereignty goal definition."""
    goal_id: str
    domain: SovereigntyDomain
    name: str
    description: str
    
    # Measurable target
    target_metric: str
    target_value: Any
    target_operator: str  # >=, <=, ==
    
    # Current state
    current_value: Optional[Any] = None
    compliance_status: ComplianceStatus = ComplianceStatus.NOT_APPLICABLE
    
    # Metadata
    priority: str = "high"  # critical, high, medium, low
    deadline: Optional[datetime] = None
    owner: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_measured: Optional[datetime] = None


@dataclass
class SovereigntyViolation:
    """Sovereignty violation record."""
    violation_id: str
    goal_id: str
    domain: SovereigntyDomain
    
    description: str
    severity: str  # critical, high, medium, low
    
    # Impact
    custody_risk: bool = False
    governance_risk: bool = False
    censorship_risk: bool = False
    seizure_risk: bool = False
    
    # Remediation
    remediation_plan: Optional[str] = None
    remediation_deadline: Optional[datetime] = None
    
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class SovereigntyGoalsMetrics:
    """
    Measurable sovereignty goals and metrics for MERID.
    
    Tracks progress toward sovereignty across custody, governance,
    infrastructure independence, forkability, and offline robustness.
    """
    
    def __init__(self):
        self._goals: Dict[str, SovereigntyGoal] = {}
        self._violations: List[SovereigntyViolation] = []
        
        self._initialize_goals()
    
    def _initialize_goals(self) -> None:
        """Initialize sovereignty goals."""
        
        # === CUSTODY SOVEREIGNTY ===
        
        self.register_goal(
            goal_id="custody_non_custodial_funds",
            domain=SovereigntyDomain.CUSTODY,
            name="100% Non-Custodial Funds",
            description="All user funds and protocol treasuries held in non-custodial wallets or smart-contract vaults",
            target_metric="percentage_non_custodial",
            target_value=Decimal("100.0"),
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="custody_on_chain_authorization",
            domain=SovereigntyDomain.CUSTODY,
            name="100% On-Chain Authorization",
            description="Every asset move authorized on-chain by user keys or DAO contracts",
            target_metric="percentage_on_chain_auth",
            target_value=Decimal("100.0"),
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="custody_zero_cex_custody",
            domain=SovereigntyDomain.CUSTODY,
            name="Zero CEX Custodial Accounts",
            description="No custodial accounts on centralized exchanges",
            target_metric="cex_custodial_accounts",
            target_value=0,
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="custody_hardware_wallet_support",
            domain=SovereigntyDomain.CUSTODY,
            name="Hardware Wallet Support",
            description="Support for major hardware wallets (Ledger, Trezor, etc.)",
            target_metric="hardware_wallet_types_supported",
            target_value=3,
            target_operator=">=",
            priority="high",
        )
        
        self.register_goal(
            goal_id="custody_multisig_treasury",
            domain=SovereigntyDomain.CUSTODY,
            name="Multi-Sig DAO Treasury",
            description="DAO treasury protected by multi-sig or MPC",
            target_metric="treasury_multisig_enabled",
            target_value=True,
            target_operator="==",
            priority="critical",
        )
        
        # === GOVERNANCE SOVEREIGNTY ===
        
        self.register_goal(
            goal_id="governance_dao_controlled_params",
            domain=SovereigntyDomain.GOVERNANCE,
            name="80%+ DAO-Controlled Parameters",
            description="Protocol-critical parameters changeable only via DAO votes",
            target_metric="percentage_dao_controlled_params",
            target_value=Decimal("80.0"),
            target_operator=">=",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="governance_emergency_multisig_limited",
            domain=SovereigntyDomain.GOVERNANCE,
            name="Limited Emergency Multisig Powers",
            description="Emergency multisig powers narrowly scoped and time-locked",
            target_metric="emergency_multisig_scope_limited",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        self.register_goal(
            goal_id="governance_multisig_sunset_timeline",
            domain=SovereigntyDomain.GOVERNANCE,
            name="Multisig Sunset Timeline",
            description="Clear timeline to reduce emergency multisig powers",
            target_metric="multisig_sunset_timeline_defined",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        self.register_goal(
            goal_id="governance_token_distribution",
            domain=SovereigntyDomain.GOVERNANCE,
            name="Decentralized Token Distribution",
            description="No single entity controls >20% of governance tokens",
            target_metric="max_single_entity_token_percentage",
            target_value=Decimal("20.0"),
            target_operator="<=",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="governance_ai_policy_dao_controlled",
            domain=SovereigntyDomain.GOVERNANCE,
            name="AI Policy DAO-Controlled",
            description="AI agent policies, whitelists, and capital limits controlled by DAO",
            target_metric="ai_policy_dao_controlled",
            target_value=True,
            target_operator="==",
            priority="critical",
        )
        
        # === INFRASTRUCTURE INDEPENDENCE ===
        
        self.register_goal(
            goal_id="infra_rpc_redundancy",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="RPC Provider Redundancy",
            description="At least 2 independent RPC providers, 1 community-run",
            target_metric="rpc_providers_count",
            target_value=2,
            target_operator=">=",
            priority="high",
        )
        
        self.register_goal(
            goal_id="infra_oracle_redundancy",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="Oracle Provider Redundancy",
            description="At least 2 independent oracle providers",
            target_metric="oracle_providers_count",
            target_value=2,
            target_operator=">=",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="infra_ai_vendor_independence",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="AI Vendor Independence",
            description="At least 2 independent AI/LLM vendors",
            target_metric="ai_vendors_count",
            target_value=2,
            target_operator=">=",
            priority="high",
        )
        
        self.register_goal(
            goal_id="infra_cloud_independence",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="Cloud Provider Independence",
            description="No single cloud provider whose failure halts protocol",
            target_metric="cloud_providers_count",
            target_value=2,
            target_operator=">=",
            priority="high",
        )
        
        self.register_goal(
            goal_id="infra_community_run_nodes",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="Community-Run Infrastructure",
            description="At least 1 community-run option for each critical service",
            target_metric="community_run_services_count",
            target_value=1,
            target_operator=">=",
            priority="high",
        )
        
        self.register_goal(
            goal_id="infra_frontend_decentralized",
            domain=SovereigntyDomain.INFRASTRUCTURE,
            name="Decentralized Frontend Hosting",
            description="Frontend hosted on IPFS/Arweave with ENS/UNS naming",
            target_metric="frontend_decentralized",
            target_value=True,
            target_operator="==",
            priority="medium",
        )
        
        # === FORKABILITY ===
        
        self.register_goal(
            goal_id="fork_open_source_contracts",
            domain=SovereigntyDomain.FORKABILITY,
            name="Open Source Smart Contracts",
            description="All smart contracts open source and verified",
            target_metric="percentage_contracts_open_source",
            target_value=Decimal("100.0"),
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="fork_open_source_ai",
            domain=SovereigntyDomain.FORKABILITY,
            name="Open Source AI Orchestration",
            description="AI orchestration code open source and forkable",
            target_metric="ai_orchestration_open_source",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        self.register_goal(
            goal_id="fork_state_exportable",
            domain=SovereigntyDomain.FORKABILITY,
            name="Exportable On-Chain State",
            description="On-chain state structured for easy export and migration",
            target_metric="state_exportable",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        self.register_goal(
            goal_id="fork_minimal_friction",
            domain=SovereigntyDomain.FORKABILITY,
            name="Minimal Fork Friction",
            description="Community can fork with <1 week setup time",
            target_metric="fork_setup_time_days",
            target_value=7,
            target_operator="<=",
            priority="medium",
        )
        
        # === OFFLINE ROBUSTNESS ===
        
        self.register_goal(
            goal_id="offline_withdraw_direct",
            domain=SovereigntyDomain.OFFLINE_ROBUSTNESS,
            name="Direct Withdrawal Without Frontend",
            description="Users can withdraw using only RPC + wallet (no MERID frontend)",
            target_metric="direct_withdrawal_supported",
            target_value=True,
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="offline_pause_direct",
            domain=SovereigntyDomain.OFFLINE_ROBUSTNESS,
            name="Direct Pause Without Frontend",
            description="Guardians/DAO can pause via direct contract interaction",
            target_metric="direct_pause_supported",
            target_value=True,
            target_operator="==",
            priority="critical",
        )
        
        self.register_goal(
            goal_id="offline_air_gapped_signing",
            domain=SovereigntyDomain.OFFLINE_ROBUSTNESS,
            name="Air-Gapped Signing Support",
            description="Support for air-gapped signing for critical actions",
            target_metric="air_gapped_signing_supported",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        self.register_goal(
            goal_id="offline_social_recovery",
            domain=SovereigntyDomain.OFFLINE_ROBUSTNESS,
            name="Social Recovery Wallets",
            description="Support for social recovery smart-contract wallets",
            target_metric="social_recovery_supported",
            target_value=True,
            target_operator="==",
            priority="medium",
        )
        
        self.register_goal(
            goal_id="offline_cli_tools",
            domain=SovereigntyDomain.OFFLINE_ROBUSTNESS,
            name="CLI Tools for Critical Actions",
            description="CLI tools available for all safety-critical actions",
            target_metric="cli_tools_available",
            target_value=True,
            target_operator="==",
            priority="high",
        )
        
        logger.info(f"Initialized {len(self._goals)} sovereignty goals")
    
    def register_goal(
        self,
        goal_id: str,
        domain: SovereigntyDomain,
        name: str,
        description: str,
        target_metric: str,
        target_value: Any,
        target_operator: str,
        priority: str = "high",
        deadline: Optional[datetime] = None,
        owner: Optional[str] = None,
    ) -> SovereigntyGoal:
        """Register sovereignty goal."""
        goal = SovereigntyGoal(
            goal_id=goal_id,
            domain=domain,
            name=name,
            description=description,
            target_metric=target_metric,
            target_value=target_value,
            target_operator=target_operator,
            priority=priority,
            deadline=deadline,
            owner=owner,
        )
        
        self._goals[goal_id] = goal
        
        return goal
    
    def update_goal_measurement(
        self,
        goal_id: str,
        current_value: Any,
    ) -> ComplianceStatus:
        """Update goal measurement and determine compliance status."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found")
        
        goal.current_value = current_value
        goal.last_measured = datetime.utcnow()
        
        # Determine compliance
        if goal.target_operator == ">=":
            compliant = current_value >= goal.target_value
        elif goal.target_operator == "<=":
            compliant = current_value <= goal.target_value
        elif goal.target_operator == "==":
            compliant = current_value == goal.target_value
        else:
            raise ValueError(f"Unknown operator: {goal.target_operator}")
        
        if compliant:
            goal.compliance_status = ComplianceStatus.COMPLIANT
        else:
            # Check if partially compliant (>50% of target)
            if isinstance(current_value, (int, float, Decimal)) and isinstance(goal.target_value, (int, float, Decimal)):
                if goal.target_operator == ">=":
                    partial = current_value >= goal.target_value * Decimal("0.5")
                elif goal.target_operator == "<=":
                    partial = current_value <= goal.target_value * Decimal("1.5")
                else:
                    partial = False
                
                goal.compliance_status = ComplianceStatus.PARTIAL if partial else ComplianceStatus.NON_COMPLIANT
            else:
                goal.compliance_status = ComplianceStatus.NON_COMPLIANT
        
        # Record violation if non-compliant
        if goal.compliance_status == ComplianceStatus.NON_COMPLIANT:
            self._record_violation(goal)
        
        return goal.compliance_status
    
    def _record_violation(self, goal: SovereigntyGoal) -> None:
        """Record sovereignty violation."""
        violation = SovereigntyViolation(
            violation_id=f"violation_{goal.goal_id}_{int(datetime.utcnow().timestamp())}",
            goal_id=goal.goal_id,
            domain=goal.domain,
            description=f"Goal '{goal.name}' not met: {goal.current_value} {goal.target_operator} {goal.target_value}",
            severity=goal.priority,
            custody_risk=goal.domain == SovereigntyDomain.CUSTODY,
            governance_risk=goal.domain == SovereigntyDomain.GOVERNANCE,
            censorship_risk=goal.domain in [SovereigntyDomain.INFRASTRUCTURE, SovereigntyDomain.OFFLINE_ROBUSTNESS],
            seizure_risk=goal.domain == SovereigntyDomain.CUSTODY,
        )
        
        self._violations.append(violation)
        
        logger.warning(
            f"Sovereignty violation: {violation.description} (severity: {violation.severity})"
        )
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """Get compliance report across all domains."""
        report = {
            "overall_compliance": self._calculate_overall_compliance(),
            "by_domain": {},
            "critical_violations": [],
            "goals": {},
        }
        
        # By domain
        for domain in SovereigntyDomain:
            domain_goals = [g for g in self._goals.values() if g.domain == domain]
            compliant = sum(1 for g in domain_goals if g.compliance_status == ComplianceStatus.COMPLIANT)
            total = len(domain_goals)
            
            report["by_domain"][domain.value] = {
                "compliant": compliant,
                "total": total,
                "percentage": (compliant / total * 100) if total > 0 else 0,
            }
        
        # Critical violations
        report["critical_violations"] = [
            {
                "violation_id": v.violation_id,
                "goal_id": v.goal_id,
                "description": v.description,
                "severity": v.severity,
                "custody_risk": v.custody_risk,
                "governance_risk": v.governance_risk,
                "censorship_risk": v.censorship_risk,
                "seizure_risk": v.seizure_risk,
            }
            for v in self._violations
            if v.severity in ["critical", "high"] and v.resolved_at is None
        ]
        
        # All goals
        for goal_id, goal in self._goals.items():
            report["goals"][goal_id] = {
                "name": goal.name,
                "domain": goal.domain.value,
                "target": f"{goal.target_metric} {goal.target_operator} {goal.target_value}",
                "current": goal.current_value,
                "status": goal.compliance_status.value,
                "priority": goal.priority,
            }
        
        return report
    
    def _calculate_overall_compliance(self) -> float:
        """Calculate overall compliance percentage."""
        if not self._goals:
            return 0.0
        
        # Weight by priority
        weights = {"critical": 3, "high": 2, "medium": 1, "low": 0.5}
        
        total_weight = 0
        compliant_weight = 0
        
        for goal in self._goals.values():
            weight = weights.get(goal.priority, 1)
            total_weight += weight
            
            if goal.compliance_status == ComplianceStatus.COMPLIANT:
                compliant_weight += weight
            elif goal.compliance_status == ComplianceStatus.PARTIAL:
                compliant_weight += weight * 0.5
        
        return (compliant_weight / total_weight * 100) if total_weight > 0 else 0.0
    
    def get_goals_by_domain(self, domain: SovereigntyDomain) -> List[SovereigntyGoal]:
        """Get goals by domain."""
        return [g for g in self._goals.values() if g.domain == domain]
    
    def get_critical_goals(self) -> List[SovereigntyGoal]:
        """Get critical priority goals."""
        return [g for g in self._goals.values() if g.priority == "critical"]
    
    def get_non_compliant_goals(self) -> List[SovereigntyGoal]:
        """Get non-compliant goals."""
        return [
            g for g in self._goals.values()
            if g.compliance_status == ComplianceStatus.NON_COMPLIANT
        ]
    
    def resolve_violation(self, violation_id: str) -> None:
        """Mark violation as resolved."""
        for violation in self._violations:
            if violation.violation_id == violation_id:
                violation.resolved_at = datetime.utcnow()
                logger.info(f"Resolved violation: {violation_id}")
                return
        
        raise ValueError(f"Violation '{violation_id}' not found")


_sovereignty_goals_metrics: Optional[SovereigntyGoalsMetrics] = None


def get_sovereignty_goals_metrics() -> SovereigntyGoalsMetrics:
    """Get global SovereigntyGoalsMetrics instance."""
    global _sovereignty_goals_metrics
    if _sovereignty_goals_metrics is None:
        _sovereignty_goals_metrics = SovereigntyGoalsMetrics()
    return _sovereignty_goals_metrics
