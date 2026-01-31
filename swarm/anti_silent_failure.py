"""
Anti-silent-failure mechanisms for MERID swarm.

Implements:
- Heartbeats and liveness checks
- Data feed sanity checks
- Security scanner liveness
- Model performance monitoring
- Swarm behavior monitoring
- Explicit no-silent-failure policies
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class ComponentType(Enum):
    """Type of component."""
    AGENT = "agent"
    ENGINE = "engine"
    DATA_FEED = "data_feed"
    SECURITY_SCANNER = "security_scanner"
    MODEL = "model"
    SWARM = "swarm"


class ComponentStatus(Enum):
    """Component status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    OFFLINE = "offline"


class FailureClass(Enum):
    """Class of silent failure."""
    STRATEGY_STOPPED = "strategy_stopped"
    ENGINE_DEGRADED = "engine_degraded"
    DATA_DRIFT = "data_drift"
    SCANNER_OFFLINE = "scanner_offline"
    GOVERNANCE_NOT_PROPAGATED = "governance_not_propagated"
    MODEL_DEGRADED = "model_degraded"
    SWARM_BREAKDOWN = "swarm_breakdown"


class SafeModeAction(Enum):
    """Safe mode action."""
    PAUSE_NEW_RISK = "pause_new_risk"
    WITHDRAWALS_ONLY = "withdrawals_only"
    REDUCE_LIMITS = "reduce_limits"
    SWITCH_BACKUP = "switch_backup"
    ESCALATE_HUMAN = "escalate_human"


@dataclass
class Heartbeat:
    """Component heartbeat."""
    component_id: str
    component_type: ComponentType
    
    # Status
    status: ComponentStatus = ComponentStatus.HEALTHY
    
    # Performance
    recent_error_count: int = 0
    latency_ms: float = 0.0
    throughput: float = 0.0
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LivenessCheck:
    """Liveness check configuration."""
    component_id: str
    component_type: ComponentType
    
    # Thresholds
    heartbeat_interval_seconds: int = 60
    max_missed_heartbeats: int = 3
    
    # Last heartbeat
    last_heartbeat: Optional[datetime] = None
    missed_heartbeats: int = 0
    
    # Status
    is_alive: bool = True
    
    # Safe mode
    safe_mode_enabled: bool = False
    safe_mode_action: Optional[SafeModeAction] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DataFeedSanityCheck:
    """Data feed sanity check."""
    feed_id: str
    feed_name: str
    
    # Expected characteristics
    expected_rate_per_second: float = 1.0
    expected_fields: Set[str] = field(default_factory=set)
    
    # Ranges
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    
    # Correlation checks
    correlated_feeds: List[str] = field(default_factory=list)
    max_correlation_drift_pct: float = 5.0
    
    # Status
    is_healthy: bool = True
    last_check: Optional[datetime] = None
    
    # Issues
    detected_freeze: bool = False
    detected_lag: bool = False
    detected_drift: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecurityScannerLiveness:
    """Security scanner liveness check."""
    scanner_id: str
    scanner_name: str
    
    # Expected behavior
    expected_scan_interval_minutes: int = 60
    
    # Last activity
    last_scan_at: Optional[datetime] = None
    last_signature_update: Optional[datetime] = None
    
    # Status
    is_running: bool = True
    is_up_to_date: bool = True
    
    # Safe mode
    block_high_risk_interactions: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelPerformanceMonitor:
    """Model performance monitoring."""
    model_id: str
    model_name: str
    
    # Performance tracking
    predictions: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0
    
    # Thresholds
    min_accuracy: float = 0.7
    max_forecast_error: float = 0.2
    
    # Degradation
    is_degraded: bool = False
    degradation_detected_at: Optional[datetime] = None
    
    # Rollback
    previous_version: Optional[str] = None
    rolled_back: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SwarmBehaviorMonitor:
    """Swarm behavior monitoring."""
    swarm_id: str
    
    # Metrics
    active_agents: int = 0
    message_rate_per_second: float = 0.0
    coordination_score: float = 1.0
    error_rate: float = 0.0
    
    # Thresholds
    min_active_agents: int = 3
    max_message_rate: float = 1000.0
    min_coordination_score: float = 0.5
    max_error_rate: float = 0.1
    
    # Status
    is_healthy: bool = True
    
    # Issues
    coordination_breakdown: bool = False
    message_storm: bool = False
    high_error_rate: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Incident:
    """System incident."""
    incident_id: str
    
    # Classification
    failure_class: FailureClass
    severity: str = "medium"  # low, medium, high, critical
    
    # Details
    component_id: str = ""
    description: str = ""
    evidence: List[str] = field(default_factory=list)
    
    # Response
    safe_mode_triggered: bool = False
    safe_mode_action: Optional[SafeModeAction] = None
    escalated_to_human: bool = False
    governance_proposal_created: bool = False
    
    # Resolution
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolution_notes: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class AntiSilentFailureSystem:
    """
    Anti-silent-failure system for MERID.
    
    Ensures no critical failure can occur silently:
    - All components emit heartbeats
    - Data feeds have sanity checks
    - Security scanners prove liveness
    - Models are monitored for degradation
    - Swarm behavior is tracked
    - All failures trigger alerts and safe modes
    """
    
    def __init__(self):
        self._liveness_checks: Dict[str, LivenessCheck] = {}
        self._heartbeats: Dict[str, Heartbeat] = {}
        self._data_feed_checks: Dict[str, DataFeedSanityCheck] = {}
        self._scanner_liveness: Dict[str, SecurityScannerLiveness] = {}
        self._model_monitors: Dict[str, ModelPerformanceMonitor] = {}
        self._swarm_monitors: Dict[str, SwarmBehaviorMonitor] = {}
        self._incidents: List[Incident] = []
    
    def register_component(
        self,
        component_id: str,
        component_type: ComponentType,
        heartbeat_interval_seconds: int = 60,
        max_missed_heartbeats: int = 3,
    ) -> LivenessCheck:
        """Register component for liveness checking."""
        check = LivenessCheck(
            component_id=component_id,
            component_type=component_type,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            max_missed_heartbeats=max_missed_heartbeats,
        )
        
        self._liveness_checks[component_id] = check
        
        logger.info(
            f"Registered component '{component_id}' ({component_type.value}) "
            f"for liveness checking (interval: {heartbeat_interval_seconds}s)"
        )
        
        return check
    
    def emit_heartbeat(
        self,
        component_id: str,
        status: ComponentStatus = ComponentStatus.HEALTHY,
        recent_error_count: int = 0,
        latency_ms: float = 0.0,
        throughput: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> Heartbeat:
        """Emit component heartbeat."""
        heartbeat = Heartbeat(
            component_id=component_id,
            component_type=self._liveness_checks[component_id].component_type,
            status=status,
            recent_error_count=recent_error_count,
            latency_ms=latency_ms,
            throughput=throughput,
            details=details or {},
        )
        
        self._heartbeats[component_id] = heartbeat
        
        # Update liveness check
        check = self._liveness_checks.get(component_id)
        if check:
            check.last_heartbeat = heartbeat.timestamp
            check.missed_heartbeats = 0
            check.is_alive = True
        
        return heartbeat
    
    def check_liveness(self) -> List[str]:
        """Check liveness of all components."""
        now = datetime.utcnow()
        failed_components = []
        
        for component_id, check in self._liveness_checks.items():
            if not check.last_heartbeat:
                continue
            
            # Calculate time since last heartbeat
            time_since_heartbeat = (now - check.last_heartbeat).total_seconds()
            
            # Check if heartbeat is overdue
            if time_since_heartbeat > check.heartbeat_interval_seconds:
                check.missed_heartbeats += 1
                
                if check.missed_heartbeats >= check.max_missed_heartbeats:
                    check.is_alive = False
                    failed_components.append(component_id)
                    
                    # Create incident
                    self._create_incident(
                        failure_class=FailureClass.STRATEGY_STOPPED,
                        severity="critical",
                        component_id=component_id,
                        description=f"Component '{component_id}' missed {check.missed_heartbeats} heartbeats",
                        evidence=[f"Last heartbeat: {check.last_heartbeat.isoformat()}"],
                    )
                    
                    # Trigger safe mode
                    self._trigger_safe_mode(component_id, SafeModeAction.PAUSE_NEW_RISK)
        
        if failed_components:
            logger.error(
                f"Liveness check failed for {len(failed_components)} components: "
                f"{', '.join(failed_components)}"
            )
        
        return failed_components
    
    def register_data_feed(
        self,
        feed_id: str,
        feed_name: str,
        expected_rate_per_second: float = 1.0,
        expected_fields: Optional[Set[str]] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
    ) -> DataFeedSanityCheck:
        """Register data feed for sanity checking."""
        check = DataFeedSanityCheck(
            feed_id=feed_id,
            feed_name=feed_name,
            expected_rate_per_second=expected_rate_per_second,
            expected_fields=expected_fields or set(),
            min_price=min_price,
            max_price=max_price,
        )
        
        self._data_feed_checks[feed_id] = check
        
        logger.info(
            f"Registered data feed '{feed_id}' for sanity checking "
            f"(rate: {expected_rate_per_second}/s)"
        )
        
        return check
    
    def check_data_feed_sanity(
        self,
        feed_id: str,
        current_rate: float,
        current_price: Optional[Decimal] = None,
        fields: Optional[Set[str]] = None,
    ) -> bool:
        """Check data feed sanity."""
        check = self._data_feed_checks.get(feed_id)
        
        if not check:
            return True
        
        is_healthy = True
        issues = []
        
        # Check rate (freeze detection)
        if current_rate < check.expected_rate_per_second * 0.1:
            check.detected_freeze = True
            is_healthy = False
            issues.append(f"Feed frozen: rate={current_rate:.2f}/s")
        
        # Check lag
        if current_rate < check.expected_rate_per_second * 0.5:
            check.detected_lag = True
            is_healthy = False
            issues.append(f"Feed lagging: rate={current_rate:.2f}/s")
        
        # Check price range
        if current_price and check.min_price and current_price < check.min_price:
            is_healthy = False
            issues.append(f"Price below minimum: {current_price} < {check.min_price}")
        
        if current_price and check.max_price and current_price > check.max_price:
            is_healthy = False
            issues.append(f"Price above maximum: {current_price} > {check.max_price}")
        
        # Check fields
        if fields and check.expected_fields:
            missing_fields = check.expected_fields - fields
            if missing_fields:
                is_healthy = False
                issues.append(f"Missing fields: {missing_fields}")
        
        check.is_healthy = is_healthy
        check.last_check = datetime.utcnow()
        
        if not is_healthy:
            logger.warning(
                f"Data feed sanity check failed for '{feed_id}': {', '.join(issues)}"
            )
            
            # Create incident
            self._create_incident(
                failure_class=FailureClass.DATA_DRIFT,
                severity="high",
                component_id=feed_id,
                description=f"Data feed '{feed_id}' failed sanity checks",
                evidence=issues,
            )
            
            # Trigger safe mode (switch to backup feed)
            self._trigger_safe_mode(feed_id, SafeModeAction.SWITCH_BACKUP)
        
        return is_healthy
    
    def register_security_scanner(
        self,
        scanner_id: str,
        scanner_name: str,
        expected_scan_interval_minutes: int = 60,
    ) -> SecurityScannerLiveness:
        """Register security scanner for liveness checking."""
        liveness = SecurityScannerLiveness(
            scanner_id=scanner_id,
            scanner_name=scanner_name,
            expected_scan_interval_minutes=expected_scan_interval_minutes,
        )
        
        self._scanner_liveness[scanner_id] = liveness
        
        logger.info(
            f"Registered security scanner '{scanner_id}' for liveness checking "
            f"(interval: {expected_scan_interval_minutes}m)"
        )
        
        return liveness
    
    def record_scanner_activity(
        self,
        scanner_id: str,
        scan_completed: bool = True,
        signature_updated: bool = False,
    ) -> None:
        """Record security scanner activity."""
        liveness = self._scanner_liveness.get(scanner_id)
        
        if not liveness:
            return
        
        now = datetime.utcnow()
        
        if scan_completed:
            liveness.last_scan_at = now
            liveness.is_running = True
        
        if signature_updated:
            liveness.last_signature_update = now
            liveness.is_up_to_date = True
    
    def check_scanner_liveness(self) -> List[str]:
        """Check security scanner liveness."""
        now = datetime.utcnow()
        offline_scanners = []
        
        for scanner_id, liveness in self._scanner_liveness.items():
            if not liveness.last_scan_at:
                continue
            
            # Check if scan is overdue
            time_since_scan = (now - liveness.last_scan_at).total_seconds() / 60
            
            if time_since_scan > liveness.expected_scan_interval_minutes * 2:
                liveness.is_running = False
                offline_scanners.append(scanner_id)
                
                # Block high-risk interactions
                liveness.block_high_risk_interactions = True
                
                logger.error(
                    f"Security scanner '{scanner_id}' offline: "
                    f"last scan {time_since_scan:.0f}m ago"
                )
                
                # Create incident
                self._create_incident(
                    failure_class=FailureClass.SCANNER_OFFLINE,
                    severity="critical",
                    component_id=scanner_id,
                    description=f"Security scanner '{scanner_id}' offline",
                    evidence=[f"Last scan: {liveness.last_scan_at.isoformat()}"],
                )
        
        return offline_scanners
    
    def register_model(
        self,
        model_id: str,
        model_name: str,
        min_accuracy: float = 0.7,
    ) -> ModelPerformanceMonitor:
        """Register model for performance monitoring."""
        monitor = ModelPerformanceMonitor(
            model_id=model_id,
            model_name=model_name,
            min_accuracy=min_accuracy,
        )
        
        self._model_monitors[model_id] = monitor
        
        logger.info(
            f"Registered model '{model_id}' for performance monitoring "
            f"(min_accuracy: {min_accuracy:.1%})"
        )
        
        return monitor
    
    def record_model_prediction(
        self,
        model_id: str,
        correct: bool,
    ) -> None:
        """Record model prediction result."""
        monitor = self._model_monitors.get(model_id)
        
        if not monitor:
            return
        
        monitor.predictions += 1
        if correct:
            monitor.correct_predictions += 1
        
        # Update accuracy
        monitor.accuracy = monitor.correct_predictions / monitor.predictions
        
        # Check for degradation
        if monitor.accuracy < monitor.min_accuracy:
            if not monitor.is_degraded:
                monitor.is_degraded = True
                monitor.degradation_detected_at = datetime.utcnow()
                
                logger.warning(
                    f"Model '{model_id}' degraded: "
                    f"accuracy={monitor.accuracy:.1%} < {monitor.min_accuracy:.1%}"
                )
                
                # Create incident
                self._create_incident(
                    failure_class=FailureClass.MODEL_DEGRADED,
                    severity="high",
                    component_id=model_id,
                    description=f"Model '{model_id}' performance degraded",
                    evidence=[f"Accuracy: {monitor.accuracy:.1%}"],
                )
    
    def register_swarm(
        self,
        swarm_id: str,
        min_active_agents: int = 3,
    ) -> SwarmBehaviorMonitor:
        """Register swarm for behavior monitoring."""
        monitor = SwarmBehaviorMonitor(
            swarm_id=swarm_id,
            min_active_agents=min_active_agents,
        )
        
        self._swarm_monitors[swarm_id] = monitor
        
        logger.info(
            f"Registered swarm '{swarm_id}' for behavior monitoring "
            f"(min_agents: {min_active_agents})"
        )
        
        return monitor
    
    def update_swarm_metrics(
        self,
        swarm_id: str,
        active_agents: int,
        message_rate_per_second: float,
        coordination_score: float,
        error_rate: float,
    ) -> bool:
        """Update swarm metrics and check health."""
        monitor = self._swarm_monitors.get(swarm_id)
        
        if not monitor:
            return True
        
        monitor.active_agents = active_agents
        monitor.message_rate_per_second = message_rate_per_second
        monitor.coordination_score = coordination_score
        monitor.error_rate = error_rate
        
        is_healthy = True
        issues = []
        
        # Check active agents
        if active_agents < monitor.min_active_agents:
            monitor.coordination_breakdown = True
            is_healthy = False
            issues.append(f"Too few active agents: {active_agents}")
        
        # Check message rate (storm detection)
        if message_rate_per_second > monitor.max_message_rate:
            monitor.message_storm = True
            is_healthy = False
            issues.append(f"Message storm: {message_rate_per_second:.0f}/s")
        
        # Check coordination
        if coordination_score < monitor.min_coordination_score:
            monitor.coordination_breakdown = True
            is_healthy = False
            issues.append(f"Coordination breakdown: {coordination_score:.2f}")
        
        # Check error rate
        if error_rate > monitor.max_error_rate:
            monitor.high_error_rate = True
            is_healthy = False
            issues.append(f"High error rate: {error_rate:.1%}")
        
        monitor.is_healthy = is_healthy
        
        if not is_healthy:
            logger.warning(
                f"Swarm '{swarm_id}' unhealthy: {', '.join(issues)}"
            )
            
            # Create incident
            self._create_incident(
                failure_class=FailureClass.SWARM_BREAKDOWN,
                severity="high",
                component_id=swarm_id,
                description=f"Swarm '{swarm_id}' behavior anomaly",
                evidence=issues,
            )
        
        return is_healthy
    
    def _create_incident(
        self,
        failure_class: FailureClass,
        severity: str,
        component_id: str,
        description: str,
        evidence: List[str],
    ) -> Incident:
        """Create incident."""
        incident_id = f"incident_{int(datetime.utcnow().timestamp())}"
        
        incident = Incident(
            incident_id=incident_id,
            failure_class=failure_class,
            severity=severity,
            component_id=component_id,
            description=description,
            evidence=evidence,
        )
        
        self._incidents.append(incident)
        
        logger.error(
            f"Incident created [{severity}]: {failure_class.value} - {description}"
        )
        
        return incident
    
    def _trigger_safe_mode(
        self,
        component_id: str,
        action: SafeModeAction,
    ) -> None:
        """Trigger safe mode for component."""
        check = self._liveness_checks.get(component_id)
        
        if check:
            check.safe_mode_enabled = True
            check.safe_mode_action = action
        
        logger.warning(
            f"Safe mode triggered for '{component_id}': {action.value}"
        )
    
    def get_active_incidents(self) -> List[Incident]:
        """Get active (unresolved) incidents."""
        return [i for i in self._incidents if not i.resolved]
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report."""
        return {
            "components": {
                "total": len(self._liveness_checks),
                "alive": sum(1 for c in self._liveness_checks.values() if c.is_alive),
                "safe_mode": sum(1 for c in self._liveness_checks.values() if c.safe_mode_enabled),
            },
            "data_feeds": {
                "total": len(self._data_feed_checks),
                "healthy": sum(1 for f in self._data_feed_checks.values() if f.is_healthy),
            },
            "security_scanners": {
                "total": len(self._scanner_liveness),
                "running": sum(1 for s in self._scanner_liveness.values() if s.is_running),
            },
            "models": {
                "total": len(self._model_monitors),
                "degraded": sum(1 for m in self._model_monitors.values() if m.is_degraded),
            },
            "swarms": {
                "total": len(self._swarm_monitors),
                "healthy": sum(1 for s in self._swarm_monitors.values() if s.is_healthy),
            },
            "incidents": {
                "total": len(self._incidents),
                "active": len(self.get_active_incidents()),
                "critical": sum(1 for i in self._incidents if i.severity == "critical" and not i.resolved),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }


_anti_silent_failure_system: Optional[AntiSilentFailureSystem] = None


def get_anti_silent_failure_system() -> AntiSilentFailureSystem:
    """Get global AntiSilentFailureSystem instance."""
    global _anti_silent_failure_system
    if _anti_silent_failure_system is None:
        _anti_silent_failure_system = AntiSilentFailureSystem()
    return _anti_silent_failure_system
