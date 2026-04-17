"""
Invariants and variants enforcement system for MERID.

Implements:
- Core invariants (must never be violated)
- Core variants (allowed to change/evolve)
- Meta-invariants (how evolution must behave)
- Continuous validation and enforcement
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = get_logger(__name__)


class InvariantDomain(Enum):
    """Invariant domain."""
    CUSTODY = "custody"
    GOVERNANCE = "governance"
    AI_SWARM = "ai_swarm"
    SECURITY = "security"
    DATA_OBSERVABILITY = "data_observability"
    ETHICS_MEV = "ethics_mev"


class VariantDomain(Enum):
    """Variant domain."""
    MODELS_STRATEGIES = "models_strategies"
    PRODUCTS_MARKETS = "products_markets"
    INFRASTRUCTURE = "infrastructure"
    GOVERNANCE_PARAMS = "governance_params"
    SWARM_LAB_UI = "swarm_lab_ui"


class ViolationSeverity(Enum):
    """Violation severity."""
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Invariant:
    """Core invariant."""
    invariant_id: str
    domain: InvariantDomain
    
    # Rule
    rule: str
    description: str
    
    # Validation
    validation_function: str  # Name of validation function
    
    # Status
    enabled: bool = True
    violations: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Variant:
    """Core variant."""
    variant_id: str
    domain: VariantDomain
    
    # Rule
    rule: str
    description: str
    
    # Constraints
    constraints: List[str] = field(default_factory=list)
    
    # Status
    enabled: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class InvariantViolation:
    """Invariant violation."""
    violation_id: str
    invariant_id: str
    
    # Details
    severity: ViolationSeverity
    description: str
    evidence: List[str] = field(default_factory=list)
    
    # Context
    component: str = ""
    change_id: Optional[str] = None
    
    # Response
    blocked: bool = False
    escalated: bool = False
    
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EvolutionCheck:
    """Evolution meta-invariant check."""
    check_id: str
    
    # Change
    change_type: str
    change_description: str
    
    # Checks
    tested: bool = False
    governed: bool = False
    observable: bool = False
    safe_degradation: bool = False
    
    # Result
    passed: bool = False
    failures: List[str] = field(default_factory=list)
    
    executed_at: datetime = field(default_factory=datetime.utcnow)


class InvariantsEnforcementSystem:
    """
    Invariants and variants enforcement system.
    
    Ensures MERID evolution respects:
    - Core invariants (custody, governance, security, etc.)
    - Core variants (what can change)
    - Meta-invariants (how evolution must behave)
    """
    
    def __init__(self):
        self._invariants: Dict[str, Invariant] = {}
        self._variants: Dict[str, Variant] = {}
        self._violations: List[InvariantViolation] = []
        self._evolution_checks: List[EvolutionCheck] = []
        
        self._initialize_invariants()
        self._initialize_variants()
    
    def _initialize_invariants(self) -> None:
        """Initialize core invariants."""
        
        # CUSTODY invariants
        self.add_invariant(
            domain=InvariantDomain.CUSTODY,
            rule="Assets remain non-custodial",
            description="User and protocol funds controlled only by keys or smart contracts, never by opaque off-chain systems or agent wallets",
            validation_function="validate_non_custodial",
        )
        
        self.add_invariant(
            domain=InvariantDomain.CUSTODY,
            rule="Critical risk rules enforced in deterministic code",
            description="Position limits, leverage caps, kill switches, withdrawal rights enforced in code, not LLM judgment",
            validation_function="validate_deterministic_risk_rules",
        )
        
        self.add_invariant(
            domain=InvariantDomain.CUSTODY,
            rule="Respect geo and regulatory constraints",
            description="AI and proxies cannot bypass venue or jurisdiction blocks",
            validation_function="validate_geo_compliance",
        )
        
        # GOVERNANCE invariants
        self.add_invariant(
            domain=InvariantDomain.GOVERNANCE,
            rule="No single point of control",
            description="No single company, multisig, LLM vendor, or cloud provider can unilaterally halt trading, seize funds, or change core rules",
            validation_function="validate_decentralized_control",
        )
        
        self.add_invariant(
            domain=InvariantDomain.GOVERNANCE,
            rule="High-impact changes require governance",
            description="Risk logic, tokenomics, agent powers go through on-chain, auditable processes with time to react",
            validation_function="validate_governance_required",
        )
        
        self.add_invariant(
            domain=InvariantDomain.GOVERNANCE,
            rule="System must remain forkable",
            description="Code, config, and on-chain state structured so community can exit and continue independently",
            validation_function="validate_forkable",
        )
        
        # AI_SWARM invariants
        self.add_invariant(
            domain=InvariantDomain.AI_SWARM,
            rule="LLMs and AI agents are untrusted tools",
            description="Always treated with constrained permissions and capability boundaries",
            validation_function="validate_ai_untrusted",
        )
        
        self.add_invariant(
            domain=InvariantDomain.AI_SWARM,
            rule="Agents never see raw private keys",
            description="All signing via HSM/MPC/smart-wallets under policy",
            validation_function="validate_no_raw_keys",
        )
        
        self.add_invariant(
            domain=InvariantDomain.AI_SWARM,
            rule="No agent bypass of hard limits",
            description="Agents cannot bypass risk limits, custody rules, or governance constraints",
            validation_function="validate_no_agent_bypass",
        )
        
        self.add_invariant(
            domain=InvariantDomain.AI_SWARM,
            rule="All agent actions fully logged",
            description="Intents and transactions logged with identity, rationale, parameters, TX hashes",
            validation_function="validate_agent_logging",
        )
        
        # SECURITY invariants
        self.add_invariant(
            domain=InvariantDomain.SECURITY,
            rule="Baseline security scanning required",
            description="New contracts/tokens/protocols must pass security scanning",
            validation_function="validate_security_scanning",
        )
        
        self.add_invariant(
            domain=InvariantDomain.SECURITY,
            rule="Scam protection always active",
            description="Social-engineering defenses active for untrusted inputs",
            validation_function="validate_scam_protection",
        )
        
        self.add_invariant(
            domain=InvariantDomain.SECURITY,
            rule="Degraded scanners block risky interactions",
            description="When scanners degraded, new risky interactions blocked or limited",
            validation_function="validate_scanner_liveness",
        )
        
        # DATA_OBSERVABILITY invariants
        self.add_invariant(
            domain=InvariantDomain.DATA_OBSERVABILITY,
            rule="Heartbeats and liveness checks required",
            description="Every critical subsystem has heartbeats and liveness checks",
            validation_function="validate_heartbeats",
        )
        
        self.add_invariant(
            domain=InvariantDomain.DATA_OBSERVABILITY,
            rule="No silent failures",
            description="If health cannot be confirmed, default to safe-mode and emit loud alerts",
            validation_function="validate_no_silent_failures",
        )
        
        self.add_invariant(
            domain=InvariantDomain.DATA_OBSERVABILITY,
            rule="Sufficient telemetry for root cause analysis",
            description="Metrics, logs, traces exist to answer 'what happened and why'",
            validation_function="validate_telemetry",
        )
        
        # ETHICS_MEV invariants
        self.add_invariant(
            domain=InvariantDomain.ETHICS_MEV,
            rule="No intentional market abuse",
            description="Must not perform spoofing, wash trading, toxic MEV against users",
            validation_function="validate_no_market_abuse",
        )
        
        self.add_invariant(
            domain=InvariantDomain.ETHICS_MEV,
            rule="MEV constrained to policy-approved categories",
            description="MEV strategies limited to benign arbitrage, avoid sandwich/front-run of users",
            validation_function="validate_mev_policy",
        )
        
        logger.info(f"Initialized {len(self._invariants)} core invariants")
    
    def _initialize_variants(self) -> None:
        """Initialize core variants."""
        
        # MODELS_STRATEGIES variants
        self.add_variant(
            domain=VariantDomain.MODELS_STRATEGIES,
            rule="Model choices can change",
            description="LLMs, RL policies, quant models can change as long as they respect interfaces and invariants",
            constraints=["Must respect model-agnostic interfaces", "Must pass validation"],
        )
        
        self.add_variant(
            domain=VariantDomain.MODELS_STRATEGIES,
            rule="Agent roster can evolve",
            description="New agent roles can be added, underperforming agents retired",
            constraints=["Must maintain coverage", "Must pass governance for high-impact roles"],
        )
        
        self.add_variant(
            domain=VariantDomain.MODELS_STRATEGIES,
            rule="Strategies and parameters can evolve",
            description="Trading/DeFi/HFT strategies, risk thresholds, routing preferences expected to evolve",
            constraints=["Must stay within governance bounds", "Must pass testing"],
        )
        
        # PRODUCTS_MARKETS variants
        self.add_variant(
            domain=VariantDomain.PRODUCTS_MARKETS,
            rule="Supported markets can change",
            description="New assets and venues can be added or removed as risk and regulation evolve",
            constraints=["Must pass security scanning", "Must respect geo-compliance"],
        )
        
        self.add_variant(
            domain=VariantDomain.PRODUCTS_MARKETS,
            rule="Vaults and products can evolve",
            description="New vault types, structured products, yield strategies can be launched or deprecated",
            constraints=["Must pass security audit", "Must have governance approval for high-risk"],
        )
        
        # INFRASTRUCTURE variants
        self.add_variant(
            domain=VariantDomain.INFRASTRUCTURE,
            rule="Frameworks and stacks can change",
            description="Agent orchestration, message buses, DBs, UI libraries can be swapped",
            constraints=["Must preserve interfaces", "Must maintain invariants"],
        )
        
        self.add_variant(
            domain=VariantDomain.INFRASTRUCTURE,
            rule="Deployment topology can change",
            description="Mix of local vs cloud, chains/rollups, RPC providers may change",
            constraints=["Must maintain redundancy", "Must preserve sovereignty"],
        )
        
        # GOVERNANCE_PARAMS variants
        self.add_variant(
            domain=VariantDomain.GOVERNANCE_PARAMS,
            rule="Governance parameters can evolve",
            description="Quorum, voting windows, delegation can evolve",
            constraints=["Must not worsen decentralization without consent"],
        )
        
        self.add_variant(
            domain=VariantDomain.GOVERNANCE_PARAMS,
            rule="Incentive schemes can be tuned",
            description="Fee splits, staking rewards, gamified quests, reputation rules can be tuned",
            constraints=["Must pass impact analysis", "Must have governance approval"],
        )
        
        # SWARM_LAB_UI variants
        self.add_variant(
            domain=VariantDomain.SWARM_LAB_UI,
            rule="Features and tools can evolve",
            description="Swarm Lab can add/remove/refactor tools and UI elements",
            constraints=["Must pass testing", "Must maintain usability"],
        )
        
        self.add_variant(
            domain=VariantDomain.SWARM_LAB_UI,
            rule="UI flows can change",
            description="Layouts, screens, onboarding flows may change to reduce friction",
            constraints=["Must maintain accessibility", "Must not break critical paths"],
        )
        
        logger.info(f"Initialized {len(self._variants)} core variants")
    
    def add_invariant(
        self,
        domain: InvariantDomain,
        rule: str,
        description: str,
        validation_function: str,
    ) -> Invariant:
        """Add core invariant."""
        invariant_id = f"inv_{domain.value}_{len(self._invariants)}"
        
        invariant = Invariant(
            invariant_id=invariant_id,
            domain=domain,
            rule=rule,
            description=description,
            validation_function=validation_function,
        )
        
        self._invariants[invariant_id] = invariant
        
        return invariant
    
    def add_variant(
        self,
        domain: VariantDomain,
        rule: str,
        description: str,
        constraints: Optional[List[str]] = None,
    ) -> Variant:
        """Add core variant."""
        variant_id = f"var_{domain.value}_{len(self._variants)}"
        
        variant = Variant(
            variant_id=variant_id,
            domain=domain,
            rule=rule,
            description=description,
            constraints=constraints or [],
        )
        
        self._variants[variant_id] = variant
        
        return variant
    
    def validate_change(
        self,
        change_type: str,
        change_description: str,
        component: str,
        change_data: Optional[Dict[str, Any]] = None,
    ) -> List[InvariantViolation]:
        """Validate change against all invariants."""
        violations = []
        
        for invariant in self._invariants.values():
            if not invariant.enabled:
                continue
            
            # Call validation function
            is_valid = self._call_validation_function(
                invariant.validation_function,
                change_type,
                change_data or {},
            )
            
            if not is_valid:
                violation = self._create_violation(
                    invariant=invariant,
                    severity=ViolationSeverity.CRITICAL,
                    description=f"Change violates invariant: {invariant.rule}",
                    component=component,
                    evidence=[change_description],
                )
                violations.append(violation)
        
        if violations:
            logger.error(
                f"Change validation failed: {len(violations)} invariant violations"
            )
        
        return violations
    
    def _call_validation_function(
        self,
        function_name: str,
        change_type: str,
        change_data: Dict[str, Any],
    ) -> bool:
        """Call validation function (simplified)."""
        
        # In real implementation, would call actual validation functions
        # For now, implement basic checks
        
        if function_name == "validate_non_custodial":
            # Check if change involves custodial control
            return not change_data.get("custodial", False)
        
        elif function_name == "validate_no_raw_keys":
            # Check if agents get raw keys
            return not change_data.get("agents_have_keys", False)
        
        elif function_name == "validate_governance_required":
            # Check if high-impact change has governance approval
            if change_data.get("high_impact", False):
                return change_data.get("governance_approved", False)
            return True
        
        elif function_name == "validate_security_scanning":
            # Check if new contracts scanned
            if change_type == "new_contract":
                return change_data.get("security_scanned", False)
            return True
        
        elif function_name == "validate_no_silent_failures":
            # Check if component has heartbeats
            return change_data.get("has_heartbeat", True)
        
        # Default: pass
        return True
    
    def _create_violation(
        self,
        invariant: Invariant,
        severity: ViolationSeverity,
        description: str,
        component: str,
        evidence: List[str],
    ) -> InvariantViolation:
        """Create invariant violation."""
        violation_id = f"viol_{int(datetime.utcnow().timestamp())}"
        
        violation = InvariantViolation(
            violation_id=violation_id,
            invariant_id=invariant.invariant_id,
            severity=severity,
            description=description,
            component=component,
            evidence=evidence,
            blocked=severity == ViolationSeverity.CRITICAL,
        )
        
        self._violations.append(violation)
        invariant.violations += 1
        
        logger.error(
            f"Invariant violation [{severity.value}]: {invariant.rule} - {description}"
        )
        
        return violation
    
    def check_evolution_meta_invariants(
        self,
        change_type: str,
        change_description: str,
        has_tests: bool = False,
        has_governance: bool = False,
        has_telemetry: bool = False,
        has_rollback: bool = False,
    ) -> EvolutionCheck:
        """Check evolution meta-invariants."""
        check_id = f"evo_check_{int(datetime.utcnow().timestamp())}"
        
        check = EvolutionCheck(
            check_id=check_id,
            change_type=change_type,
            change_description=change_description,
        )
        
        failures = []
        
        # Meta-invariant 1: Tested evolution
        check.tested = has_tests
        if not has_tests:
            failures.append("Change lacks testing (sim → paper → canary → production)")
        
        # Meta-invariant 2: Governed evolution
        check.governed = has_governance
        if not has_governance and change_type in ["risk_model", "mev_policy", "ai_powers"]:
            failures.append("High-impact change lacks governance approval")
        
        # Meta-invariant 3: Observable evolution
        check.observable = has_telemetry
        if not has_telemetry:
            failures.append("Change lacks observability (logs, metrics, traces)")
        
        # Meta-invariant 4: Safe degradation
        check.safe_degradation = has_rollback
        if not has_rollback:
            failures.append("Change lacks rollback capability")
        
        check.failures = failures
        check.passed = len(failures) == 0
        
        self._evolution_checks.append(check)
        
        if not check.passed:
            logger.warning(
                f"Evolution meta-invariants check failed: {len(failures)} failures"
            )
        
        return check
    
    def get_invariant_status(self) -> Dict[str, Any]:
        """Get invariant enforcement status."""
        return {
            "invariants": {
                "total": len(self._invariants),
                "enabled": sum(1 for i in self._invariants.values() if i.enabled),
                "by_domain": {
                    domain.value: sum(
                        1 for i in self._invariants.values()
                        if i.domain == domain and i.enabled
                    )
                    for domain in InvariantDomain
                },
            },
            "variants": {
                "total": len(self._variants),
                "enabled": sum(1 for v in self._variants.values() if v.enabled),
                "by_domain": {
                    domain.value: sum(
                        1 for v in self._variants.values()
                        if v.domain == domain and v.enabled
                    )
                    for domain in VariantDomain
                },
            },
            "violations": {
                "total": len(self._violations),
                "by_severity": {
                    severity.value: sum(
                        1 for v in self._violations
                        if v.severity == severity
                    )
                    for severity in ViolationSeverity
                },
                "blocked": sum(1 for v in self._violations if v.blocked),
            },
            "evolution_checks": {
                "total": len(self._evolution_checks),
                "passed": sum(1 for c in self._evolution_checks if c.passed),
                "failed": sum(1 for c in self._evolution_checks if not c.passed),
            },
        }
    
    def get_invariants_by_domain(
        self,
        domain: InvariantDomain,
    ) -> List[Invariant]:
        """Get invariants by domain."""
        return [
            i for i in self._invariants.values()
            if i.domain == domain and i.enabled
        ]
    
    def get_variants_by_domain(
        self,
        domain: VariantDomain,
    ) -> List[Variant]:
        """Get variants by domain."""
        return [
            v for v in self._variants.values()
            if v.domain == domain and v.enabled
        ]


_invariants_enforcement_system: Optional[InvariantsEnforcementSystem] = None
_invariants_enforcement_system_lock = threading.Lock()


def get_invariants_enforcement_system() -> InvariantsEnforcementSystem:
    """Get global InvariantsEnforcementSystem instance."""
    global _invariants_enforcement_system
    if _invariants_enforcement_system is None:
        with _invariants_enforcement_system_lock:
            if _invariants_enforcement_system is None:
                _invariants_enforcement_system = InvariantsEnforcementSystem()
    return _invariants_enforcement_system
