"""
Protocol maintenance and health monitoring agents for MERID.

Implements:
- Protocol health monitoring (TVL, volumes, risk, errors, slippage)
- Autonomous parameter tuning (fees, caps, incentives)
- Upgrade and migration coordination
- Security maintenance (exploit pattern updates)
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class HealthMetricType(Enum):
    """Type of health metric."""
    TVL = "tvl"
    VOLUME_24H = "volume_24h"
    ERROR_RATE = "error_rate"
    SLIPPAGE = "slippage"
    ORACLE_DRIFT = "oracle_drift"
    GOVERNANCE_PARTICIPATION = "governance_participation"
    AGENT_PERFORMANCE = "agent_performance"
    LIQUIDITY_DEPTH = "liquidity_depth"
    LIQUIDATION_QUALITY = "liquidation_quality"
    RWA_COVERAGE = "rwa_coverage"


class HealthStatus(Enum):
    """Health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    OFFLINE = "offline"


class ParameterType(Enum):
    """Type of parameter."""
    FEE = "fee"
    REWARD_WEIGHT = "reward_weight"
    RISK_THRESHOLD = "risk_threshold"
    ROUTING_PREFERENCE = "routing_preference"
    SLIPPAGE_CAP = "slippage_cap"
    POSITION_LIMIT = "position_limit"


class UpgradeType(Enum):
    """Type of upgrade."""
    CONTRACT_UPGRADE = "contract_upgrade"
    VAULT_MIGRATION = "vault_migration"
    STRATEGY_ROTATION = "strategy_rotation"
    PARAMETER_UPDATE = "parameter_update"
    MODEL_UPDATE = "model_update"


@dataclass
class HealthMetric:
    """Protocol health metric."""
    metric_type: HealthMetricType
    metric_name: str
    
    # Current value
    current_value: float = 0.0
    
    # Targets
    target_value: float = 0.0
    min_threshold: float = 0.0
    max_threshold: float = 0.0
    
    # Status
    status: HealthStatus = HealthStatus.HEALTHY
    deviation_pct: float = 0.0
    
    # History
    values_24h: List[float] = field(default_factory=list)
    
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ParameterProposal:
    """Parameter tuning proposal."""
    proposal_id: str
    parameter_type: ParameterType
    parameter_name: str
    
    # Current and proposed
    current_value: Any = None
    proposed_value: Any = None
    
    # Justification
    reason: str = ""
    expected_impact: str = ""
    
    # Experiment
    is_experiment: bool = False
    experiment_duration_hours: int = 24
    
    # Bounds
    within_governance_caps: bool = True
    requires_approval: bool = False
    
    # Status
    approved: bool = False
    applied: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UpgradePlan:
    """Protocol upgrade plan."""
    plan_id: str
    upgrade_type: UpgradeType
    
    # Details
    description: str = ""
    affected_contracts: List[str] = field(default_factory=list)
    affected_vaults: List[str] = field(default_factory=list)
    
    # Simulation
    simulated: bool = False
    simulation_results: Dict[str, Any] = field(default_factory=dict)
    
    # Impact
    estimated_downtime_minutes: int = 0
    requires_liquidity_migration: bool = False
    migration_amount_usd: Decimal = Decimal("0")
    
    # Governance
    governance_proposal_id: Optional[str] = None
    governance_approved: bool = False
    
    # Execution
    executed: bool = False
    execution_date: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecurityUpdate:
    """Security maintenance update."""
    update_id: str
    
    # Type
    update_type: str = ""  # "exploit_pattern", "rug_pull_signature", "scam_domain"
    
    # Details
    description: str = ""
    new_patterns: List[str] = field(default_factory=list)
    deprecated_patterns: List[str] = field(default_factory=list)
    
    # Impact
    protocols_affected: List[str] = field(default_factory=list)
    recommended_action: str = ""  # "quarantine", "monitor", "allow"
    
    # Status
    applied: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class ProtocolHealthMonitor:
    """
    Protocol health monitoring agent for MERID.
    
    Tracks:
    - TVL, volumes, risk limits
    - Error rates, slippage, oracle drift
    - Governance participation
    - Agent performance
    
    Raises alerts and proposes parameter changes when metrics deviate.
    """
    
    def __init__(self):
        self._metrics: Dict[str, HealthMetric] = {}
        self._alerts: List[Dict[str, Any]] = []
        
        self._initialize_metrics()
    
    def _initialize_metrics(self) -> None:
        """Initialize health metrics."""
        
        # TVL metric
        self.register_metric(
            metric_type=HealthMetricType.TVL,
            metric_name="Total Value Locked",
            target_value=1000000.0,  # $1M target
            min_threshold=500000.0,  # $500k minimum
            max_threshold=10000000.0,  # $10M maximum
        )
        
        # Volume metric
        self.register_metric(
            metric_type=HealthMetricType.VOLUME_24H,
            metric_name="24h Trading Volume",
            target_value=100000.0,  # $100k target
            min_threshold=10000.0,  # $10k minimum
        )
        
        # Error rate metric
        self.register_metric(
            metric_type=HealthMetricType.ERROR_RATE,
            metric_name="System Error Rate",
            target_value=0.01,  # 1% target
            max_threshold=0.05,  # 5% maximum
        )
        
        # Slippage metric
        self.register_metric(
            metric_type=HealthMetricType.SLIPPAGE,
            metric_name="Average Slippage",
            target_value=0.001,  # 0.1% target
            max_threshold=0.01,  # 1% maximum
        )
        
        # Oracle drift metric
        self.register_metric(
            metric_type=HealthMetricType.ORACLE_DRIFT,
            metric_name="Oracle Price Drift",
            target_value=0.0,  # 0% target
            max_threshold=0.02,  # 2% maximum
        )
        
        # Governance participation metric
        self.register_metric(
            metric_type=HealthMetricType.GOVERNANCE_PARTICIPATION,
            metric_name="Governance Participation Rate",
            target_value=0.5,  # 50% target
            min_threshold=0.2,  # 20% minimum
        )
        
        logger.info("Initialized protocol health metrics")
    
    def register_metric(
        self,
        metric_type: HealthMetricType,
        metric_name: str,
        target_value: float = 0.0,
        min_threshold: float = 0.0,
        max_threshold: float = float('inf'),
    ) -> HealthMetric:
        """Register health metric."""
        metric = HealthMetric(
            metric_type=metric_type,
            metric_name=metric_name,
            target_value=target_value,
            min_threshold=min_threshold,
            max_threshold=max_threshold,
        )
        
        self._metrics[metric_type.value] = metric
        
        logger.info(f"Registered metric '{metric_name}': target={target_value}")
        
        return metric
    
    def update_metric(
        self,
        metric_type: HealthMetricType,
        value: float,
    ) -> HealthMetric:
        """Update metric value and check health."""
        metric = self._metrics.get(metric_type.value)
        
        if not metric:
            raise ValueError(f"Metric '{metric_type.value}' not registered")
        
        # Update value
        metric.current_value = value
        metric.values_24h.append(value)
        
        # Keep only last 24 hours (assuming hourly updates)
        if len(metric.values_24h) > 24:
            metric.values_24h = metric.values_24h[-24:]
        
        # Calculate deviation
        if metric.target_value > 0:
            metric.deviation_pct = (value - metric.target_value) / metric.target_value * 100
        
        # Check status
        if value < metric.min_threshold or value > metric.max_threshold:
            metric.status = HealthStatus.CRITICAL
            
            self._create_alert(
                severity="critical",
                metric_type=metric_type,
                message=f"{metric.metric_name} out of bounds: {value:.2f}",
                current_value=value,
                threshold=metric.min_threshold if value < metric.min_threshold else metric.max_threshold,
            )
        elif abs(metric.deviation_pct) > 20:
            metric.status = HealthStatus.DEGRADED
            
            self._create_alert(
                severity="warning",
                metric_type=metric_type,
                message=f"{metric.metric_name} deviating from target: {metric.deviation_pct:.1f}%",
                current_value=value,
                target=metric.target_value,
            )
        else:
            metric.status = HealthStatus.HEALTHY
        
        metric.last_updated = datetime.utcnow()
        
        logger.info(
            f"Updated metric '{metric.metric_name}': "
            f"value={value:.2f}, status={metric.status.value}"
        )
        
        return metric
    
    def get_overall_health(self) -> HealthStatus:
        """Get overall protocol health."""
        statuses = [m.status for m in self._metrics.values()]
        
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        elif HealthStatus.OFFLINE in statuses:
            return HealthStatus.OFFLINE
        else:
            return HealthStatus.HEALTHY
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report."""
        return {
            "overall_status": self.get_overall_health().value,
            "metrics": {
                metric_type: {
                    "name": metric.metric_name,
                    "current_value": metric.current_value,
                    "target_value": metric.target_value,
                    "status": metric.status.value,
                    "deviation_pct": metric.deviation_pct,
                }
                for metric_type, metric in self._metrics.items()
            },
            "recent_alerts": self._alerts[-10:],
            "generated_at": datetime.utcnow().isoformat(),
        }
    
    def _create_alert(
        self,
        severity: str,
        metric_type: HealthMetricType,
        message: str,
        **kwargs: Any,
    ) -> None:
        """Create health alert."""
        alert = {
            "alert_id": f"alert_{int(datetime.utcnow().timestamp())}",
            "severity": severity,
            "metric_type": metric_type.value,
            "message": message,
            "details": kwargs,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        self._alerts.append(alert)
        
        logger.warning(f"Health alert [{severity}]: {message}")


class ParameterTunerAgent:
    """
    Autonomous parameter tuning agent for MERID.
    
    Continuously proposes bounded adjustments to:
    - Fees
    - Reward weights
    - Risk thresholds
    - Routing preferences
    
    Runs A/B and multi-armed bandit experiments.
    """
    
    def __init__(self):
        self._proposals: List[ParameterProposal] = []
        self._experiments: Dict[str, Dict[str, Any]] = {}
    
    def propose_parameter_change(
        self,
        parameter_type: ParameterType,
        parameter_name: str,
        current_value: Any,
        proposed_value: Any,
        reason: str,
        expected_impact: str = "",
        is_experiment: bool = False,
        within_governance_caps: bool = True,
    ) -> ParameterProposal:
        """Propose parameter change."""
        proposal_id = f"param_{parameter_type.value}_{int(datetime.utcnow().timestamp())}"
        
        proposal = ParameterProposal(
            proposal_id=proposal_id,
            parameter_type=parameter_type,
            parameter_name=parameter_name,
            current_value=current_value,
            proposed_value=proposed_value,
            reason=reason,
            expected_impact=expected_impact,
            is_experiment=is_experiment,
            within_governance_caps=within_governance_caps,
            requires_approval=not within_governance_caps,
        )
        
        self._proposals.append(proposal)
        
        logger.info(
            f"Proposed parameter change: {parameter_name} "
            f"{current_value} → {proposed_value} ({reason})"
        )
        
        return proposal
    
    def approve_proposal(self, proposal_id: str) -> bool:
        """Approve parameter proposal."""
        proposal = next(
            (p for p in self._proposals if p.proposal_id == proposal_id),
            None,
        )
        
        if not proposal:
            return False
        
        proposal.approved = True
        
        logger.info(f"Approved parameter proposal: {proposal_id}")
        
        return True
    
    def apply_proposal(self, proposal_id: str) -> bool:
        """Apply approved parameter proposal."""
        proposal = next(
            (p for p in self._proposals if p.proposal_id == proposal_id),
            None,
        )
        
        if not proposal or not proposal.approved:
            return False
        
        # In real implementation, would actually apply the parameter change
        proposal.applied = True
        
        logger.info(
            f"Applied parameter change: {proposal.parameter_name} "
            f"= {proposal.proposed_value}"
        )
        
        return True
    
    def start_experiment(
        self,
        experiment_id: str,
        parameter_name: str,
        variants: List[Any],
        duration_hours: int = 24,
    ) -> Dict[str, Any]:
        """Start A/B or multi-armed bandit experiment."""
        experiment = {
            "experiment_id": experiment_id,
            "parameter_name": parameter_name,
            "variants": variants,
            "duration_hours": duration_hours,
            "started_at": datetime.utcnow(),
            "ends_at": datetime.utcnow() + timedelta(hours=duration_hours),
            "results": {variant: {"trials": 0, "successes": 0} for variant in variants},
            "winner": None,
        }
        
        self._experiments[experiment_id] = experiment
        
        logger.info(
            f"Started experiment '{experiment_id}': "
            f"{parameter_name} with {len(variants)} variants"
        )
        
        return experiment
    
    def record_experiment_result(
        self,
        experiment_id: str,
        variant: Any,
        success: bool,
    ) -> None:
        """Record experiment result."""
        experiment = self._experiments.get(experiment_id)
        
        if not experiment:
            return
        
        results = experiment["results"][variant]
        results["trials"] += 1
        if success:
            results["successes"] += 1
    
    def get_experiment_winner(self, experiment_id: str) -> Optional[Any]:
        """Get experiment winner (best performing variant)."""
        experiment = self._experiments.get(experiment_id)
        
        if not experiment:
            return None
        
        # Calculate success rates
        best_variant = None
        best_rate = 0.0
        
        for variant, results in experiment["results"].items():
            if results["trials"] > 0:
                rate = results["successes"] / results["trials"]
                if rate > best_rate:
                    best_rate = rate
                    best_variant = variant
        
        experiment["winner"] = best_variant
        
        logger.info(
            f"Experiment '{experiment_id}' winner: {best_variant} "
            f"(success rate: {best_rate:.1%})"
        )
        
        return best_variant


class UpgradeCoordinator:
    """
    Upgrade and migration coordinator agent for MERID.
    
    Drafts upgrade plans:
    - New contracts
    - Vault migrations
    - Strategy rotations
    
    Simulates impacts and prepares governance proposals.
    """
    
    def __init__(self):
        self._upgrade_plans: List[UpgradePlan] = []
    
    def create_upgrade_plan(
        self,
        upgrade_type: UpgradeType,
        description: str,
        affected_contracts: Optional[List[str]] = None,
        affected_vaults: Optional[List[str]] = None,
        estimated_downtime_minutes: int = 0,
        requires_liquidity_migration: bool = False,
    ) -> UpgradePlan:
        """Create upgrade plan."""
        plan_id = f"upgrade_{upgrade_type.value}_{int(datetime.utcnow().timestamp())}"
        
        plan = UpgradePlan(
            plan_id=plan_id,
            upgrade_type=upgrade_type,
            description=description,
            affected_contracts=affected_contracts or [],
            affected_vaults=affected_vaults or [],
            estimated_downtime_minutes=estimated_downtime_minutes,
            requires_liquidity_migration=requires_liquidity_migration,
        )
        
        self._upgrade_plans.append(plan)
        
        logger.info(
            f"Created upgrade plan '{plan_id}': {upgrade_type.value} - {description}"
        )
        
        return plan
    
    def simulate_upgrade(
        self,
        plan_id: str,
        simulation_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Simulate upgrade impact."""
        plan = next(
            (p for p in self._upgrade_plans if p.plan_id == plan_id),
            None,
        )
        
        if not plan:
            raise ValueError(f"Upgrade plan '{plan_id}' not found")
        
        # In real implementation, would run actual simulation
        simulation_results = {
            "simulated_at": datetime.utcnow().isoformat(),
            "success": True,
            "estimated_gas_cost": 500000,
            "estimated_impact": {
                "tvl_change_pct": -0.5,  # 0.5% temporary decrease
                "downtime_minutes": plan.estimated_downtime_minutes,
            },
            "risks": ["Temporary liquidity fragmentation", "Gas price volatility"],
        }
        
        plan.simulated = True
        plan.simulation_results = simulation_results
        
        logger.info(f"Simulated upgrade '{plan_id}': success={simulation_results['success']}")
        
        return simulation_results
    
    def prepare_governance_proposal(
        self,
        plan_id: str,
    ) -> str:
        """Prepare governance proposal for upgrade."""
        plan = next(
            (p for p in self._upgrade_plans if p.plan_id == plan_id),
            None,
        )
        
        if not plan:
            raise ValueError(f"Upgrade plan '{plan_id}' not found")
        
        if not plan.simulated:
            raise ValueError(f"Upgrade plan '{plan_id}' not simulated yet")
        
        # Generate proposal ID
        proposal_id = f"gov_proposal_{int(datetime.utcnow().timestamp())}"
        plan.governance_proposal_id = proposal_id
        
        logger.info(
            f"Prepared governance proposal '{proposal_id}' for upgrade '{plan_id}'"
        )
        
        return proposal_id
    
    def execute_upgrade(
        self,
        plan_id: str,
        governance_approved: bool = False,
    ) -> bool:
        """Execute approved upgrade."""
        plan = next(
            (p for p in self._upgrade_plans if p.plan_id == plan_id),
            None,
        )
        
        if not plan:
            return False
        
        if not governance_approved:
            logger.error(f"Upgrade '{plan_id}' not approved by governance")
            return False
        
        plan.governance_approved = True
        plan.executed = True
        plan.execution_date = datetime.utcnow()
        
        logger.info(f"Executed upgrade '{plan_id}'")
        
        return True


class SecurityMaintenanceAgent:
    """
    Security maintenance agent for MERID.
    
    Keeps exploit/rug-pull pattern libraries up to date.
    Applies new signatures and recommends quarantining risky protocols.
    """
    
    def __init__(self):
        self._security_updates: List[SecurityUpdate] = []
    
    def create_security_update(
        self,
        update_type: str,
        description: str,
        new_patterns: Optional[List[str]] = None,
        deprecated_patterns: Optional[List[str]] = None,
        protocols_affected: Optional[List[str]] = None,
        recommended_action: str = "monitor",
    ) -> SecurityUpdate:
        """Create security update."""
        update_id = f"security_{update_type}_{int(datetime.utcnow().timestamp())}"
        
        update = SecurityUpdate(
            update_id=update_id,
            update_type=update_type,
            description=description,
            new_patterns=new_patterns or [],
            deprecated_patterns=deprecated_patterns or [],
            protocols_affected=protocols_affected or [],
            recommended_action=recommended_action,
        )
        
        self._security_updates.append(update)
        
        logger.info(
            f"Created security update '{update_id}': {update_type} - {description}"
        )
        
        return update
    
    def apply_security_update(self, update_id: str) -> bool:
        """Apply security update."""
        update = next(
            (u for u in self._security_updates if u.update_id == update_id),
            None,
        )
        
        if not update:
            return False
        
        # In real implementation, would update exploit/scam scanners
        update.applied = True
        
        logger.info(
            f"Applied security update '{update_id}': "
            f"+{len(update.new_patterns)} patterns, -{len(update.deprecated_patterns)} patterns"
        )
        
        return True
    
    def get_pending_updates(self) -> List[SecurityUpdate]:
        """Get pending security updates."""
        return [u for u in self._security_updates if not u.applied]


_protocol_health_monitor: Optional[ProtocolHealthMonitor] = None
_parameter_tuner_agent: Optional[ParameterTunerAgent] = None
_upgrade_coordinator: Optional[UpgradeCoordinator] = None
_security_maintenance_agent: Optional[SecurityMaintenanceAgent] = None
_protocol_maintenance_lock = threading.Lock()


def get_protocol_health_monitor() -> ProtocolHealthMonitor:
    """Get global ProtocolHealthMonitor instance."""
    global _protocol_health_monitor
    if _protocol_health_monitor is None:
        with _protocol_maintenance_lock:
            if _protocol_health_monitor is None:
                _protocol_health_monitor = ProtocolHealthMonitor()
    return _protocol_health_monitor


def get_parameter_tuner_agent() -> ParameterTunerAgent:
    """Get global ParameterTunerAgent instance."""
    global _parameter_tuner_agent
    if _parameter_tuner_agent is None:
        with _protocol_maintenance_lock:
            if _parameter_tuner_agent is None:
                _parameter_tuner_agent = ParameterTunerAgent()
    return _parameter_tuner_agent


def get_upgrade_coordinator() -> UpgradeCoordinator:
    """Get global UpgradeCoordinator instance."""
    global _upgrade_coordinator
    if _upgrade_coordinator is None:
        with _protocol_maintenance_lock:
            if _upgrade_coordinator is None:
                _upgrade_coordinator = UpgradeCoordinator()
    return _upgrade_coordinator


def get_security_maintenance_agent() -> SecurityMaintenanceAgent:
    """Get global SecurityMaintenanceAgent instance."""
    global _security_maintenance_agent
    if _security_maintenance_agent is None:
        with _protocol_maintenance_lock:
            if _security_maintenance_agent is None:
                _security_maintenance_agent = SecurityMaintenanceAgent()
    return _security_maintenance_agent
