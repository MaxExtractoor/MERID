"""
Drift Monitoring Pipeline

Comprehensive drift detection for:
- Concept/model drift (rolling error, Sharpe, drawdowns)
- LLM behavioral drift (regression tests, deviation scores)
- Strategy performance drift
- Data distribution drift

With automatic demotion, retrain triggers, and rollback capabilities.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import deque
import statistics
import math
import threading

logger = get_logger(__name__)

try:
    from prometheus_client import Gauge, Counter

    drift_score_gauge = Gauge(
        'merid_drift_score',
        'Current drift score for a monitor',
        ['monitor_id', 'drift_type']
    )
    drift_status_gauge = Gauge(
        'merid_drift_status',
        'Drift status as numeric: 0=stable, 1=warning, 2=degraded, 3=critical',
        ['monitor_id', 'drift_type']
    )
    drift_events_total = Counter(
        'merid_drift_events_total',
        'Total drift events detected',
        ['drift_type', 'status']
    )
    drift_mitigations_total = Counter(
        'merid_drift_mitigations_total',
        'Total mitigation actions taken',
        ['action']
    )
    _DRIFT_PROM_AVAILABLE = True
except ImportError:
    _DRIFT_PROM_AVAILABLE = False

_DRIFT_STATUS_MAP = {"stable": 0, "warning": 1, "degraded": 2, "critical": 3}


class DriftType(Enum):
    """Types of drift that can be detected."""
    CONCEPT = "concept"
    MODEL = "model"
    LLM_BEHAVIORAL = "llm_behavioral"
    STRATEGY = "strategy"
    DATA_DISTRIBUTION = "data_distribution"
    FEATURE = "feature"


class DriftStatus(Enum):
    """Status of drift detection."""
    STABLE = "stable"
    WARNING = "warning"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class MitigationAction(Enum):
    """Actions to take when drift is detected."""
    MONITOR = "monitor"
    REDUCE_WEIGHT = "reduce_weight"
    DEMOTE = "demote"
    RETRAIN = "retrain"
    ROLLBACK = "rollback"
    PAUSE = "pause"
    ESCALATE = "escalate"


@dataclass
class DriftThresholds:
    """Thresholds for drift detection."""
    warning: float = 0.1
    degraded: float = 0.25
    critical: float = 0.5


@dataclass
class DriftEvent:
    """A detected drift event."""
    event_id: str
    drift_type: DriftType
    source_id: str
    source_name: str
    
    status: DriftStatus
    drift_score: float
    
    baseline_value: float
    current_value: float
    deviation: float
    
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    recommended_action: MitigationAction = MitigationAction.MONITOR
    action_taken: Optional[MitigationAction] = None
    
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


@dataclass
class DriftMonitorConfig:
    """Configuration for a drift monitor."""
    monitor_id: str
    name: str
    drift_type: DriftType
    
    window_size: int = 100
    baseline_window: int = 1000
    
    thresholds: DriftThresholds = field(default_factory=DriftThresholds)
    
    check_interval_seconds: int = 60
    enabled: bool = True


@dataclass
class ModelDriftMetrics:
    """Metrics for model drift detection."""
    model_id: str
    
    rolling_error: float = 0.0
    rolling_sharpe: float = 0.0
    rolling_drawdown: float = 0.0
    
    baseline_error: float = 0.0
    baseline_sharpe: float = 0.0
    baseline_drawdown: float = 0.0
    
    error_deviation: float = 0.0
    sharpe_deviation: float = 0.0
    drawdown_deviation: float = 0.0
    
    predictions_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LLMDriftMetrics:
    """Metrics for LLM behavioral drift detection."""
    agent_id: str
    
    regression_pass_rate: float = 1.0
    deviation_score: float = 0.0
    safety_override_count: int = 0
    
    baseline_pass_rate: float = 1.0
    baseline_deviation: float = 0.0
    
    tests_run: int = 0
    tests_failed: int = 0
    
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StrategyDriftMetrics:
    """Metrics for strategy performance drift."""
    strategy_id: str
    
    rolling_return: float = 0.0
    rolling_sharpe: float = 0.0
    rolling_drawdown: float = 0.0
    rolling_win_rate: float = 0.0
    
    baseline_return: float = 0.0
    baseline_sharpe: float = 0.0
    baseline_drawdown: float = 0.0
    baseline_win_rate: float = 0.0
    
    return_deviation: float = 0.0
    sharpe_deviation: float = 0.0
    
    trades_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)


class DriftMonitoringPipeline:
    """
    Comprehensive Drift Monitoring Pipeline.
    
    Features:
    - Multi-type drift detection (concept, model, LLM, strategy, data)
    - Rolling window metrics with baseline comparison
    - Automatic mitigation actions
    - Event logging and escalation
    - Integration with explainability and audit systems
    """
    
    def __init__(self):
        self._monitors: Dict[str, DriftMonitorConfig] = {}
        self._events: List[DriftEvent] = []
        self._model_metrics: Dict[str, ModelDriftMetrics] = {}
        self._llm_metrics: Dict[str, LLMDriftMetrics] = {}
        self._strategy_metrics: Dict[str, StrategyDriftMetrics] = {}
        
        self._rolling_windows: Dict[str, deque] = {}
        self._baseline_windows: Dict[str, deque] = {}
        
        self._mitigation_callbacks: Dict[MitigationAction, List[Callable]] = {
            action: [] for action in MitigationAction
        }
        
        self._initialize_default_monitors()
    
    def _initialize_default_monitors(self) -> None:
        """Initialize default drift monitors."""
        
        # Model drift monitor
        self.register_monitor(DriftMonitorConfig(
            monitor_id="model_drift",
            name="Model Performance Drift",
            drift_type=DriftType.MODEL,
            window_size=100,
            baseline_window=1000,
            thresholds=DriftThresholds(warning=0.1, degraded=0.2, critical=0.3),
        ))
        
        # LLM behavioral drift monitor
        self.register_monitor(DriftMonitorConfig(
            monitor_id="llm_drift",
            name="LLM Behavioral Drift",
            drift_type=DriftType.LLM_BEHAVIORAL,
            window_size=50,
            baseline_window=500,
            thresholds=DriftThresholds(warning=0.05, degraded=0.1, critical=0.2),
        ))
        
        # Strategy drift monitor
        self.register_monitor(DriftMonitorConfig(
            monitor_id="strategy_drift",
            name="Strategy Performance Drift",
            drift_type=DriftType.STRATEGY,
            window_size=100,
            baseline_window=1000,
            thresholds=DriftThresholds(warning=0.15, degraded=0.25, critical=0.4),
        ))
        
        # Data distribution drift monitor
        self.register_monitor(DriftMonitorConfig(
            monitor_id="data_drift",
            name="Data Distribution Drift",
            drift_type=DriftType.DATA_DISTRIBUTION,
            window_size=1000,
            baseline_window=10000,
            thresholds=DriftThresholds(warning=0.1, degraded=0.2, critical=0.35),
        ))
        
        logger.info(f"Initialized {len(self._monitors)} default drift monitors")
    
    def register_monitor(self, config: DriftMonitorConfig) -> None:
        """Register a drift monitor."""
        self._monitors[config.monitor_id] = config
        self._rolling_windows[config.monitor_id] = deque(maxlen=config.window_size)
        self._baseline_windows[config.monitor_id] = deque(maxlen=config.baseline_window)
        logger.debug(f"Registered monitor '{config.monitor_id}'")
    
    def register_mitigation_callback(
        self,
        action: MitigationAction,
        callback: Callable[[DriftEvent], None],
    ) -> None:
        """Register a callback for a mitigation action."""
        self._mitigation_callbacks[action].append(callback)
    
    def record_model_prediction(
        self,
        model_id: str,
        predicted: float,
        actual: float,
        return_value: float = 0.0,
    ) -> Optional[DriftEvent]:
        """Record a model prediction and check for drift."""
        
        # Initialize metrics if needed
        if model_id not in self._model_metrics:
            self._model_metrics[model_id] = ModelDriftMetrics(model_id=model_id)
        
        metrics = self._model_metrics[model_id]
        
        # Calculate error
        error = abs(predicted - actual)
        
        # Update rolling window
        window_key = f"model_{model_id}"
        if window_key not in self._rolling_windows:
            self._rolling_windows[window_key] = deque(maxlen=100)
            self._baseline_windows[window_key] = deque(maxlen=1000)
        
        self._rolling_windows[window_key].append({
            "error": error,
            "return": return_value,
            "timestamp": datetime.utcnow(),
        })
        self._baseline_windows[window_key].append({
            "error": error,
            "return": return_value,
            "timestamp": datetime.utcnow(),
        })
        
        metrics.predictions_count += 1
        metrics.last_updated = datetime.utcnow()
        
        # Calculate rolling metrics
        if len(self._rolling_windows[window_key]) >= 10:
            rolling_errors = [d["error"] for d in self._rolling_windows[window_key]]
            rolling_returns = [d["return"] for d in self._rolling_windows[window_key]]
            
            metrics.rolling_error = statistics.mean(rolling_errors)
            
            if len(rolling_returns) > 1 and statistics.stdev(rolling_returns) > 0:
                metrics.rolling_sharpe = (
                    statistics.mean(rolling_returns) / statistics.stdev(rolling_returns)
                )
            
            # Calculate baseline if enough data
            if len(self._baseline_windows[window_key]) >= 100:
                baseline_errors = [d["error"] for d in self._baseline_windows[window_key]]
                baseline_returns = [d["return"] for d in self._baseline_windows[window_key]]
                
                metrics.baseline_error = statistics.mean(baseline_errors)
                
                if len(baseline_returns) > 1 and statistics.stdev(baseline_returns) > 0:
                    metrics.baseline_sharpe = (
                        statistics.mean(baseline_returns) / statistics.stdev(baseline_returns)
                    )
                
                # Calculate deviations
                if metrics.baseline_error > 0:
                    metrics.error_deviation = (
                        (metrics.rolling_error - metrics.baseline_error) / metrics.baseline_error
                    )
                
                if metrics.baseline_sharpe != 0:
                    metrics.sharpe_deviation = (
                        (metrics.baseline_sharpe - metrics.rolling_sharpe) / abs(metrics.baseline_sharpe)
                    )
                
                # Check for drift
                return self._check_model_drift(model_id, metrics)
        
        return None
    
    def _check_model_drift(
        self,
        model_id: str,
        metrics: ModelDriftMetrics,
    ) -> Optional[DriftEvent]:
        """Check for model drift and create event if detected."""
        
        monitor = self._monitors.get("model_drift")
        if not monitor or not monitor.enabled:
            return None
        
        # Use error deviation as primary drift indicator
        drift_score = abs(metrics.error_deviation)
        
        # Determine status
        if drift_score >= monitor.thresholds.critical:
            status = DriftStatus.CRITICAL
            action = MitigationAction.ROLLBACK
        elif drift_score >= monitor.thresholds.degraded:
            status = DriftStatus.DEGRADED
            action = MitigationAction.DEMOTE
        elif drift_score >= monitor.thresholds.warning:
            status = DriftStatus.WARNING
            action = MitigationAction.REDUCE_WEIGHT
        else:
            return None
        
        event = DriftEvent(
            event_id=f"model_drift_{model_id}_{int(datetime.utcnow().timestamp())}",
            drift_type=DriftType.MODEL,
            source_id=model_id,
            source_name=f"Model {model_id}",
            status=status,
            drift_score=drift_score,
            baseline_value=metrics.baseline_error,
            current_value=metrics.rolling_error,
            deviation=metrics.error_deviation,
            description=f"Model {model_id} error deviation: {metrics.error_deviation:.2%}",
            evidence={
                "rolling_error": metrics.rolling_error,
                "baseline_error": metrics.baseline_error,
                "rolling_sharpe": metrics.rolling_sharpe,
                "baseline_sharpe": metrics.baseline_sharpe,
                "predictions_count": metrics.predictions_count,
            },
            recommended_action=action,
        )
        
        self._events.append(event)
        self._execute_mitigation(event)
        
        logger.warning(
            f"Model drift detected for '{model_id}': "
            f"status={status.value}, score={drift_score:.3f}, action={action.value}"
        )
        
        return event
    
    def record_llm_regression_result(
        self,
        agent_id: str,
        tests_run: int,
        tests_passed: int,
        deviation_score: float,
        safety_overrides: int = 0,
    ) -> Optional[DriftEvent]:
        """Record LLM regression test results and check for drift."""
        
        if agent_id not in self._llm_metrics:
            self._llm_metrics[agent_id] = LLMDriftMetrics(agent_id=agent_id)
        
        metrics = self._llm_metrics[agent_id]
        
        # Update metrics
        pass_rate = tests_passed / tests_run if tests_run > 0 else 1.0
        
        metrics.regression_pass_rate = pass_rate
        metrics.deviation_score = deviation_score
        metrics.safety_override_count += safety_overrides
        metrics.tests_run += tests_run
        metrics.tests_failed += (tests_run - tests_passed)
        metrics.last_updated = datetime.utcnow()
        
        # Update baseline (exponential moving average)
        alpha = 0.1
        metrics.baseline_pass_rate = (
            alpha * pass_rate + (1 - alpha) * metrics.baseline_pass_rate
        )
        metrics.baseline_deviation = (
            alpha * deviation_score + (1 - alpha) * metrics.baseline_deviation
        )
        
        # Check for drift
        return self._check_llm_drift(agent_id, metrics)
    
    def _check_llm_drift(
        self,
        agent_id: str,
        metrics: LLMDriftMetrics,
    ) -> Optional[DriftEvent]:
        """Check for LLM behavioral drift."""
        
        monitor = self._monitors.get("llm_drift")
        if not monitor or not monitor.enabled:
            return None
        
        # Calculate drift score from pass rate and deviation
        pass_rate_drift = 1.0 - metrics.regression_pass_rate
        drift_score = max(pass_rate_drift, metrics.deviation_score)
        
        # Determine status
        if drift_score >= monitor.thresholds.critical:
            status = DriftStatus.CRITICAL
            action = MitigationAction.PAUSE
        elif drift_score >= monitor.thresholds.degraded:
            status = DriftStatus.DEGRADED
            action = MitigationAction.ESCALATE
        elif drift_score >= monitor.thresholds.warning:
            status = DriftStatus.WARNING
            action = MitigationAction.MONITOR
        else:
            return None
        
        event = DriftEvent(
            event_id=f"llm_drift_{agent_id}_{int(datetime.utcnow().timestamp())}",
            drift_type=DriftType.LLM_BEHAVIORAL,
            source_id=agent_id,
            source_name=f"LLM Agent {agent_id}",
            status=status,
            drift_score=drift_score,
            baseline_value=metrics.baseline_pass_rate,
            current_value=metrics.regression_pass_rate,
            deviation=1.0 - metrics.regression_pass_rate,
            description=f"LLM Agent {agent_id} behavioral drift: pass_rate={metrics.regression_pass_rate:.2%}",
            evidence={
                "pass_rate": metrics.regression_pass_rate,
                "deviation_score": metrics.deviation_score,
                "safety_overrides": metrics.safety_override_count,
                "tests_run": metrics.tests_run,
                "tests_failed": metrics.tests_failed,
            },
            recommended_action=action,
        )
        
        self._events.append(event)
        self._execute_mitigation(event)
        
        logger.warning(
            f"LLM drift detected for '{agent_id}': "
            f"status={status.value}, score={drift_score:.3f}, action={action.value}"
        )
        
        return event
    
    def record_strategy_performance(
        self,
        strategy_id: str,
        return_value: float,
        is_win: bool,
    ) -> Optional[DriftEvent]:
        """Record strategy performance and check for drift."""
        
        if strategy_id not in self._strategy_metrics:
            self._strategy_metrics[strategy_id] = StrategyDriftMetrics(
                strategy_id=strategy_id
            )
        
        metrics = self._strategy_metrics[strategy_id]
        
        # Update rolling window
        window_key = f"strategy_{strategy_id}"
        if window_key not in self._rolling_windows:
            self._rolling_windows[window_key] = deque(maxlen=100)
            self._baseline_windows[window_key] = deque(maxlen=1000)
        
        self._rolling_windows[window_key].append({
            "return": return_value,
            "win": is_win,
            "timestamp": datetime.utcnow(),
        })
        self._baseline_windows[window_key].append({
            "return": return_value,
            "win": is_win,
            "timestamp": datetime.utcnow(),
        })
        
        metrics.trades_count += 1
        metrics.last_updated = datetime.utcnow()
        
        # Calculate rolling metrics
        if len(self._rolling_windows[window_key]) >= 10:
            rolling_returns = [d["return"] for d in self._rolling_windows[window_key]]
            rolling_wins = [d["win"] for d in self._rolling_windows[window_key]]
            
            metrics.rolling_return = statistics.mean(rolling_returns)
            metrics.rolling_win_rate = sum(rolling_wins) / len(rolling_wins)
            
            if len(rolling_returns) > 1 and statistics.stdev(rolling_returns) > 0:
                metrics.rolling_sharpe = (
                    statistics.mean(rolling_returns) / statistics.stdev(rolling_returns)
                )
            
            # Calculate baseline
            if len(self._baseline_windows[window_key]) >= 100:
                baseline_returns = [d["return"] for d in self._baseline_windows[window_key]]
                baseline_wins = [d["win"] for d in self._baseline_windows[window_key]]
                
                metrics.baseline_return = statistics.mean(baseline_returns)
                metrics.baseline_win_rate = sum(baseline_wins) / len(baseline_wins)
                
                if len(baseline_returns) > 1 and statistics.stdev(baseline_returns) > 0:
                    metrics.baseline_sharpe = (
                        statistics.mean(baseline_returns) / statistics.stdev(baseline_returns)
                    )
                
                # Calculate deviations
                if metrics.baseline_sharpe != 0:
                    metrics.sharpe_deviation = (
                        (metrics.baseline_sharpe - metrics.rolling_sharpe) / 
                        abs(metrics.baseline_sharpe)
                    )
                
                return self._check_strategy_drift(strategy_id, metrics)
        
        return None
    
    def _check_strategy_drift(
        self,
        strategy_id: str,
        metrics: StrategyDriftMetrics,
    ) -> Optional[DriftEvent]:
        """Check for strategy performance drift."""
        
        monitor = self._monitors.get("strategy_drift")
        if not monitor or not monitor.enabled:
            return None
        
        drift_score = abs(metrics.sharpe_deviation)
        
        if drift_score >= monitor.thresholds.critical:
            status = DriftStatus.CRITICAL
            action = MitigationAction.PAUSE
        elif drift_score >= monitor.thresholds.degraded:
            status = DriftStatus.DEGRADED
            action = MitigationAction.DEMOTE
        elif drift_score >= monitor.thresholds.warning:
            status = DriftStatus.WARNING
            action = MitigationAction.REDUCE_WEIGHT
        else:
            return None
        
        event = DriftEvent(
            event_id=f"strategy_drift_{strategy_id}_{int(datetime.utcnow().timestamp())}",
            drift_type=DriftType.STRATEGY,
            source_id=strategy_id,
            source_name=f"Strategy {strategy_id}",
            status=status,
            drift_score=drift_score,
            baseline_value=metrics.baseline_sharpe,
            current_value=metrics.rolling_sharpe,
            deviation=metrics.sharpe_deviation,
            description=f"Strategy {strategy_id} Sharpe deviation: {metrics.sharpe_deviation:.2%}",
            evidence={
                "rolling_sharpe": metrics.rolling_sharpe,
                "baseline_sharpe": metrics.baseline_sharpe,
                "rolling_return": metrics.rolling_return,
                "rolling_win_rate": metrics.rolling_win_rate,
                "trades_count": metrics.trades_count,
            },
            recommended_action=action,
        )
        
        self._events.append(event)
        self._execute_mitigation(event)
        
        logger.warning(
            f"Strategy drift detected for '{strategy_id}': "
            f"status={status.value}, score={drift_score:.3f}, action={action.value}"
        )
        
        return event
    
    def _execute_mitigation(self, event: DriftEvent) -> None:
        """Execute mitigation action for a drift event."""
        action = event.recommended_action

        # Emit Prometheus metrics
        if _DRIFT_PROM_AVAILABLE:
            drift_score_gauge.labels(
                monitor_id=event.source_id,
                drift_type=event.drift_type.value,
            ).set(event.drift_score)
            drift_status_gauge.labels(
                monitor_id=event.source_id,
                drift_type=event.drift_type.value,
            ).set(_DRIFT_STATUS_MAP.get(event.status.value, 0))
            drift_events_total.labels(
                drift_type=event.drift_type.value,
                status=event.status.value,
            ).inc()
            drift_mitigations_total.labels(action=action.value).inc()

        for callback in self._mitigation_callbacks.get(action, []):
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Mitigation callback failed: {e}")
        
        event.action_taken = action
        
        logger.info(
            f"Executed mitigation '{action.value}' for drift event '{event.event_id}'"
        )
    
    def resolve_event(self, event_id: str) -> bool:
        """Mark a drift event as resolved."""
        for event in self._events:
            if event.event_id == event_id:
                event.resolved_at = datetime.utcnow()
                logger.info(f"Resolved drift event '{event_id}'")
                return True
        return False
    
    def get_active_events(self) -> List[DriftEvent]:
        """Get all unresolved drift events."""
        return [e for e in self._events if e.resolved_at is None]
    
    def get_drift_summary(self) -> Dict[str, Any]:
        """Get summary of drift monitoring status."""
        active_events = self.get_active_events()
        
        by_type = {}
        for drift_type in DriftType:
            count = sum(1 for e in active_events if e.drift_type == drift_type)
            by_type[drift_type.value] = count
        
        by_status = {}
        for status in DriftStatus:
            count = sum(1 for e in active_events if e.status == status)
            by_status[status.value] = count
        
        return {
            "total_events": len(self._events),
            "active_events": len(active_events),
            "resolved_events": len(self._events) - len(active_events),
            "by_type": by_type,
            "by_status": by_status,
            "critical_count": by_status.get("critical", 0),
            "models_monitored": len(self._model_metrics),
            "llm_agents_monitored": len(self._llm_metrics),
            "strategies_monitored": len(self._strategy_metrics),
            "monitors_active": sum(1 for m in self._monitors.values() if m.enabled),
        }
    
    def pipe_to_explainability(
        self,
        event: DriftEvent,
        explainability_service: Any,
    ) -> None:
        """Pipe drift event to explainability service."""
        explanation = {
            "event_type": "drift_detected",
            "drift_type": event.drift_type.value,
            "source": event.source_name,
            "status": event.status.value,
            "drift_score": event.drift_score,
            "description": event.description,
            "evidence": event.evidence,
            "recommended_action": event.recommended_action.value,
            "action_taken": event.action_taken.value if event.action_taken else None,
            "timestamp": event.detected_at.isoformat(),
        }
        
        if hasattr(explainability_service, "record_explanation"):
            explainability_service.record_explanation(
                action_type="drift_mitigation",
                explanation=explanation,
            )


_pipeline: Optional[DriftMonitoringPipeline] = None
_pipeline_lock = threading.Lock()


def get_drift_monitoring_pipeline() -> DriftMonitoringPipeline:
    """Get global DriftMonitoringPipeline instance."""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = DriftMonitoringPipeline()
    return _pipeline
