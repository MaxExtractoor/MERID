"""
Execution and infrastructure moat for MERID's competitive advantage.

Implements:
- Low-latency infrastructure tracking
- Co-location and routing optimization metrics
- GPU-accelerated analytics performance
- Industrial-grade risk controls
- HSM/MPC custody integration
- Execution edge measurement
"""

from utils.logger import get_logger
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class InfraComponent(Enum):
    """Infrastructure component types."""
    RPC_ROUTER = "rpc_router"
    INDEXER = "indexer"
    EXECUTION_ENGINE = "execution_engine"
    GPU_ANALYTICS = "gpu_analytics"
    RISK_SERVER = "risk_server"
    HSM_CUSTODY = "hsm_custody"
    MPC_CUSTODY = "mpc_custody"


class LatencyTier(Enum):
    """Latency tier classification."""
    ULTRA_LOW = "ultra_low"  # < 1ms
    LOW = "low"  # 1-10ms
    MEDIUM = "medium"  # 10-100ms
    HIGH = "high"  # > 100ms


class RiskControlType(Enum):
    """Risk control types."""
    CIRCUIT_BREAKER = "circuit_breaker"
    POSITION_LIMIT = "position_limit"
    LOSS_LIMIT = "loss_limit"
    SCANNER = "scanner"
    ANTI_SCAM = "anti_scam"
    ANTI_MEV_ABUSE = "anti_mev_abuse"
    SILENT_FAILURE_DETECTION = "silent_failure_detection"


@dataclass
class InfraMetric:
    """Infrastructure performance metric."""
    metric_id: str
    component: InfraComponent
    
    # Metric
    metric_name: str
    metric_value: float
    metric_unit: str
    
    # Benchmark
    industry_benchmark: Optional[float] = None
    advantage_ratio: Optional[float] = None
    
    # Metadata
    description: str = ""
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LatencyMeasurement:
    """Latency measurement."""
    measurement_id: str
    
    # Component
    component: InfraComponent
    operation: str
    
    # Latency
    latency_ms: float
    tier: LatencyTier
    
    # Context
    region: str = ""
    provider: str = ""
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CoLocationConfig:
    """Co-location configuration."""
    config_id: str
    
    # Location
    region: str
    datacenter: str
    
    # Components
    components: List[InfraComponent] = field(default_factory=list)
    
    # Performance
    avg_latency_ms: float = 0.0
    
    # Cost
    monthly_cost: Decimal = Decimal("0.0")
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GPUAcceleration:
    """GPU acceleration configuration."""
    acceleration_id: str
    
    # GPU
    gpu_type: str
    gpu_count: int
    
    # Workload
    workload_type: str  # zk_proofs, signature_verification, ai_inference
    
    # Performance
    throughput_per_second: float
    speedup_vs_cpu: float
    
    # Utilization
    utilization_percentage: float = 0.0
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskControl:
    """Risk control configuration."""
    control_id: str
    control_type: RiskControlType
    
    # Configuration
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Status
    enabled: bool = True
    
    # Effectiveness
    triggers_count: int = 0
    false_positives: int = 0
    true_positives: int = 0
    
    # Metadata
    description: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_triggered: Optional[datetime] = None


@dataclass
class CustodyConfig:
    """Custody configuration."""
    custody_id: str
    custody_type: str  # hsm, mpc
    
    # Provider
    provider: str
    
    # Security
    security_level: str  # institutional, enterprise, standard
    
    # Keys managed
    keys_count: int = 0
    
    # Audit
    last_audit_date: Optional[datetime] = None
    audit_score: Optional[float] = None
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionEdge:
    """Execution edge measurement."""
    edge_id: str
    
    # Edge type
    edge_type: str  # latency, throughput, accuracy, cost
    
    # Measurement
    our_performance: float
    competitor_avg: float
    edge_percentage: float  # (our - competitor) / competitor * 100
    
    # Description
    description: str = ""
    
    # Tracking
    measured_at: datetime = field(default_factory=datetime.utcnow)


class ExecutionMoat:
    """
    Execution and infrastructure moat tracker.
    
    Features:
    - Low-latency infrastructure metrics
    - Co-location optimization
    - GPU acceleration tracking
    - Risk control effectiveness
    - Custody security
    - Execution edge measurement
    """
    
    def __init__(self):
        self._infra_metrics: List[InfraMetric] = []
        self._latency_measurements: List[LatencyMeasurement] = []
        self._colocation_configs: Dict[str, CoLocationConfig] = {}
        self._gpu_accelerations: Dict[str, GPUAcceleration] = {}
        self._risk_controls: Dict[str, RiskControl] = {}
        self._custody_configs: Dict[str, CustodyConfig] = {}
        self._execution_edges: List[ExecutionEdge] = []
        
        self._initialize_infrastructure()
    
    def _initialize_infrastructure(self) -> None:
        """Initialize infrastructure components."""
        
        # Co-location configs
        self.register_colocation(
            region="us-east-1",
            datacenter="AWS us-east-1a",
            components=[
                InfraComponent.RPC_ROUTER,
                InfraComponent.EXECUTION_ENGINE,
                InfraComponent.INDEXER,
            ],
            avg_latency_ms=0.5,
            monthly_cost=Decimal("5000.0"),
        )
        
        # GPU acceleration
        self.register_gpu_acceleration(
            gpu_type="NVIDIA A100",
            gpu_count=4,
            workload_type="zk_proofs",
            throughput_per_second=10000.0,
            speedup_vs_cpu=50.0,
        )
        
        self.register_gpu_acceleration(
            gpu_type="NVIDIA A100",
            gpu_count=2,
            workload_type="ai_inference",
            throughput_per_second=5000.0,
            speedup_vs_cpu=30.0,
        )
        
        # Risk controls
        self.register_risk_control(
            control_type=RiskControlType.CIRCUIT_BREAKER,
            parameters={
                "max_loss_percentage": 5.0,
                "time_window_seconds": 60,
                "cooldown_seconds": 300,
            },
            description="Halt trading on rapid losses",
        )
        
        self.register_risk_control(
            control_type=RiskControlType.ANTI_SCAM,
            parameters={
                "honeypot_detection": True,
                "rug_pull_detection": True,
                "social_engineering_detection": True,
            },
            description="Detect and prevent scam interactions",
        )
        
        self.register_risk_control(
            control_type=RiskControlType.SILENT_FAILURE_DETECTION,
            parameters={
                "heartbeat_interval_seconds": 10,
                "timeout_seconds": 30,
                "auto_failover": True,
            },
            description="Detect silent failures and auto-failover",
        )
        
        # Custody
        self.register_custody(
            custody_type="hsm",
            provider="AWS CloudHSM",
            security_level="institutional",
            keys_count=50,
        )
        
        self.register_custody(
            custody_type="mpc",
            provider="Fireblocks",
            security_level="institutional",
            keys_count=100,
        )
        
        logger.info("Initialized execution moat infrastructure")
    
    def register_colocation(
        self,
        region: str,
        datacenter: str,
        components: List[InfraComponent],
        avg_latency_ms: float,
        monthly_cost: Decimal,
    ) -> CoLocationConfig:
        """Register co-location configuration."""
        config_id = f"coloc_{region}_{int(time.time())}"
        
        config = CoLocationConfig(
            config_id=config_id,
            region=region,
            datacenter=datacenter,
            components=components,
            avg_latency_ms=avg_latency_ms,
            monthly_cost=monthly_cost,
        )
        
        self._colocation_configs[config_id] = config
        
        logger.info(
            f"Registered co-location '{config_id}': {region} "
            f"({len(components)} components, {avg_latency_ms}ms avg latency)"
        )
        
        return config
    
    def register_gpu_acceleration(
        self,
        gpu_type: str,
        gpu_count: int,
        workload_type: str,
        throughput_per_second: float,
        speedup_vs_cpu: float,
    ) -> GPUAcceleration:
        """Register GPU acceleration."""
        acceleration_id = f"gpu_{workload_type}_{int(time.time())}"
        
        acceleration = GPUAcceleration(
            acceleration_id=acceleration_id,
            gpu_type=gpu_type,
            gpu_count=gpu_count,
            workload_type=workload_type,
            throughput_per_second=throughput_per_second,
            speedup_vs_cpu=speedup_vs_cpu,
        )
        
        self._gpu_accelerations[acceleration_id] = acceleration
        
        logger.info(
            f"Registered GPU acceleration '{acceleration_id}': "
            f"{gpu_count}x {gpu_type} for {workload_type} "
            f"({speedup_vs_cpu}x speedup)"
        )
        
        return acceleration
    
    def register_risk_control(
        self,
        control_type: RiskControlType,
        parameters: Dict[str, Any],
        description: str,
    ) -> RiskControl:
        """Register risk control."""
        control_id = f"risk_{control_type.value}_{int(time.time())}"
        
        control = RiskControl(
            control_id=control_id,
            control_type=control_type,
            parameters=parameters,
            description=description,
        )
        
        self._risk_controls[control_id] = control
        
        logger.info(
            f"Registered risk control '{control_id}': {control_type.value}"
        )
        
        return control
    
    def register_custody(
        self,
        custody_type: str,
        provider: str,
        security_level: str,
        keys_count: int,
    ) -> CustodyConfig:
        """Register custody configuration."""
        custody_id = f"custody_{custody_type}_{int(time.time())}"
        
        config = CustodyConfig(
            custody_id=custody_id,
            custody_type=custody_type,
            provider=provider,
            security_level=security_level,
            keys_count=keys_count,
        )
        
        self._custody_configs[custody_id] = config
        
        logger.info(
            f"Registered custody '{custody_id}': {custody_type} "
            f"({provider}, {keys_count} keys)"
        )
        
        return config
    
    def measure_latency(
        self,
        component: InfraComponent,
        operation: str,
        latency_ms: float,
        region: str = "",
        provider: str = "",
    ) -> LatencyMeasurement:
        """Measure component latency."""
        measurement_id = f"lat_{component.value}_{int(time.time() * 1000)}"
        
        # Classify tier
        if latency_ms < 1.0:
            tier = LatencyTier.ULTRA_LOW
        elif latency_ms < 10.0:
            tier = LatencyTier.LOW
        elif latency_ms < 100.0:
            tier = LatencyTier.MEDIUM
        else:
            tier = LatencyTier.HIGH
        
        measurement = LatencyMeasurement(
            measurement_id=measurement_id,
            component=component,
            operation=operation,
            latency_ms=latency_ms,
            tier=tier,
            region=region,
            provider=provider,
        )
        
        self._latency_measurements.append(measurement)
        
        logger.debug(
            f"Measured latency for {component.value}.{operation}: "
            f"{latency_ms:.2f}ms ({tier.value})"
        )
        
        return measurement
    
    def record_infra_metric(
        self,
        component: InfraComponent,
        metric_name: str,
        metric_value: float,
        metric_unit: str,
        industry_benchmark: Optional[float] = None,
        description: str = "",
    ) -> InfraMetric:
        """Record infrastructure metric."""
        metric_id = f"metric_{component.value}_{int(time.time())}"
        
        advantage_ratio = None
        if industry_benchmark and industry_benchmark > 0:
            advantage_ratio = metric_value / industry_benchmark
        
        metric = InfraMetric(
            metric_id=metric_id,
            component=component,
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            industry_benchmark=industry_benchmark,
            advantage_ratio=advantage_ratio,
            description=description,
        )
        
        self._infra_metrics.append(metric)
        
        logger.info(
            f"Recorded {component.value} metric '{metric_name}': "
            f"{metric_value} {metric_unit}"
        )
        
        return metric
    
    def trigger_risk_control(
        self,
        control_id: str,
        is_true_positive: bool,
    ) -> None:
        """Trigger risk control."""
        control = self._risk_controls.get(control_id)
        
        if not control:
            logger.warning(f"Risk control '{control_id}' not found")
            return
        
        control.triggers_count += 1
        control.last_triggered = datetime.utcnow()
        
        if is_true_positive:
            control.true_positives += 1
        else:
            control.false_positives += 1
        
        logger.info(
            f"Triggered risk control '{control_id}': {control.control_type.value} "
            f"(true positive: {is_true_positive})"
        )
    
    def measure_execution_edge(
        self,
        edge_type: str,
        our_performance: float,
        competitor_avg: float,
        description: str,
    ) -> ExecutionEdge:
        """Measure execution edge vs competitors."""
        edge_id = f"edge_{edge_type}_{int(time.time())}"
        
        edge_percentage = (
            (our_performance - competitor_avg) / competitor_avg * 100
            if competitor_avg > 0 else 0.0
        )
        
        edge = ExecutionEdge(
            edge_id=edge_id,
            edge_type=edge_type,
            our_performance=our_performance,
            competitor_avg=competitor_avg,
            edge_percentage=edge_percentage,
            description=description,
        )
        
        self._execution_edges.append(edge)
        
        logger.info(
            f"Measured execution edge '{edge_type}': "
            f"{edge_percentage:+.1f}% vs competitors"
        )
        
        return edge
    
    def get_execution_moat_stats(self) -> Dict[str, Any]:
        """Get execution moat statistics."""
        
        # Latency stats
        ultra_low_latency_count = sum(
            1 for m in self._latency_measurements
            if m.tier == LatencyTier.ULTRA_LOW
        )
        
        avg_latency = (
            sum(m.latency_ms for m in self._latency_measurements) /
            len(self._latency_measurements)
            if self._latency_measurements else 0.0
        )
        
        # Risk control effectiveness
        total_triggers = sum(c.triggers_count for c in self._risk_controls.values())
        total_true_positives = sum(c.true_positives for c in self._risk_controls.values())
        
        effectiveness_rate = (
            total_true_positives / total_triggers * 100
            if total_triggers > 0 else 0.0
        )
        
        # GPU acceleration
        total_gpu_speedup = (
            sum(g.speedup_vs_cpu for g in self._gpu_accelerations.values()) /
            len(self._gpu_accelerations)
            if self._gpu_accelerations else 0.0
        )
        
        # Execution edges
        avg_edge_percentage = (
            sum(e.edge_percentage for e in self._execution_edges) /
            len(self._execution_edges)
            if self._execution_edges else 0.0
        )
        
        return {
            "latency": {
                "measurements": len(self._latency_measurements),
                "ultra_low_count": ultra_low_latency_count,
                "avg_latency_ms": avg_latency,
            },
            "colocation": {
                "configs": len(self._colocation_configs),
                "total_monthly_cost": sum(
                    c.monthly_cost for c in self._colocation_configs.values()
                ),
            },
            "gpu_acceleration": {
                "configs": len(self._gpu_accelerations),
                "avg_speedup_vs_cpu": total_gpu_speedup,
            },
            "risk_controls": {
                "total": len(self._risk_controls),
                "enabled": sum(1 for c in self._risk_controls.values() if c.enabled),
                "total_triggers": total_triggers,
                "effectiveness_rate": effectiveness_rate,
            },
            "custody": {
                "configs": len(self._custody_configs),
                "total_keys": sum(c.keys_count for c in self._custody_configs.values()),
                "institutional_grade": sum(
                    1 for c in self._custody_configs.values()
                    if c.security_level == "institutional"
                ),
            },
            "execution_edges": {
                "total": len(self._execution_edges),
                "avg_edge_percentage": avg_edge_percentage,
            },
        }


_execution_moat: Optional[ExecutionMoat] = None


def get_execution_moat() -> ExecutionMoat:
    """Get global ExecutionMoat instance."""
    global _execution_moat
    if _execution_moat is None:
        _execution_moat = ExecutionMoat()
    return _execution_moat
