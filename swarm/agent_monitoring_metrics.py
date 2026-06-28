"""
Comprehensive monitoring and observability metrics for multi-agent systems.

Tracks agent-level, workflow-level, swarm-level, and security/compliance metrics
with rich telemetry for "why did the swarm do X at time T?" analysis.
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
import numpy as np

logger = get_logger(__name__)


class MetricCategory(Enum):
    """Category of monitoring metric."""
    AGENT_LEVEL = "agent_level"
    WORKFLOW_LEVEL = "workflow_level"
    SWARM_LEVEL = "swarm_level"
    SECURITY_COMPLIANCE = "security_compliance"


@dataclass
class SwarmAgentMetrics:
    """Agent-level metrics for swarm monitoring (renamed from AgentMetrics to avoid conflict with risk.agent_metrics)."""
    agent_id: str
    timestamp: datetime
    
    # Performance
    success_rate: float
    failure_rate: float
    error_codes: Dict[str, int]
    retry_count: int
    
    # Latency
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    
    # Resource usage
    token_usage: int
    llm_calls: int
    tool_calls: int
    
    # Trading performance
    pnl_contribution: float
    sharpe_contribution: float
    
    # Alignment
    alignment_score: float
    reputation_score: float
    
    # Drift
    decision_entropy: float
    kl_divergence: float
    drift_detected: bool


@dataclass
class WorkflowMetrics:
    """Workflow-level metrics."""
    workflow_id: str
    timestamp: datetime
    
    # End-to-end
    total_latency_ms: float
    agent_count: int
    
    # Fan-out/in
    max_fan_out: int
    max_fan_in: int
    
    # Completion
    timeout_rate: float
    cancellation_rate: float
    
    # Escalations
    escalation_count: int
    override_count: int
    safe_mode_activations: int
    
    # Coordination
    coordination_events: int
    deconfliction_events: int


@dataclass
class SwarmMetrics:
    """Swarm-level metrics."""
    timestamp: datetime
    
    # Concurrency
    active_agents: int
    active_workflows: int
    
    # Resource usage
    llm_calls_per_second: float
    tool_calls_per_second: float
    total_token_usage: int
    
    # Cost
    cost_per_scenario: float
    total_cost_usd: float
    
    # Correlation
    cross_agent_correlation: float
    systemic_risk_score: float
    
    # Capital
    total_capital_deployed: float
    capital_per_regime: Dict[str, float]
    
    # Health
    overall_health_score: float
    degraded_agents: int


@dataclass
class SecurityComplianceMetrics:
    """Security and compliance metrics."""
    timestamp: datetime
    
    # Security
    auth_failures: int
    suspicious_patterns: int
    abnormal_access_count: int
    data_egress_volume_mb: float
    
    # Compliance
    regulator_mode_completeness: float
    audit_trail_gaps: int
    decision_reconstruction_time_ms: float
    
    # Incidents
    security_incidents: int
    compliance_violations: int


@dataclass
class TimeSeriesMetric:
    """Time series metric with history."""
    metric_name: str
    category: MetricCategory
    values: deque = field(default_factory=lambda: deque(maxlen=10000))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=10000))


class AgentMonitoringMetrics:
    """
    Comprehensive monitoring and observability metrics system.
    
    Tracks:
    - Agent-level: success/failure, latency, tokens, PnL, alignment, drift
    - Workflow-level: end-to-end latency, fan-out/in, timeouts, escalations
    - Swarm-level: concurrency, LLM/tool calls, cost, correlation, capital
    - Security/compliance: auth failures, suspicious patterns, audit completeness
    
    Supports "why did the swarm do X at time T?" analysis.
    """
    
    def __init__(self):
        self._agent_metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._workflow_metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._swarm_metrics: deque = deque(maxlen=10000)
        self._security_metrics: deque = deque(maxlen=10000)
        
        self._time_series: Dict[str, TimeSeriesMetric] = {}
        
        self._alert_thresholds = self._define_alert_thresholds()
        self._alerts: List[Dict[str, Any]] = []
    
    def _define_alert_thresholds(self) -> Dict[str, Any]:
        """Define alert thresholds."""
        return {
            "agent_failure_rate": 0.1,
            "agent_latency_p99_ms": 5000,
            "workflow_timeout_rate": 0.05,
            "swarm_correlation": 0.85,
            "security_incidents_per_hour": 5,
            "auth_failures_per_hour": 10,
        }
    
    def record_agent_metrics(
        self,
        agent_id: str,
        success_rate: float,
        failure_rate: float,
        error_codes: Dict[str, int],
        retry_count: int,
        latency_samples: List[float],
        token_usage: int,
        llm_calls: int,
        tool_calls: int,
        pnl_contribution: float,
        sharpe_contribution: float,
        alignment_score: float,
        reputation_score: float,
        decision_entropy: float,
        kl_divergence: float,
        drift_detected: bool,
    ) -> SwarmAgentMetrics:
        """Record agent-level metrics."""
        latency_array = np.array(latency_samples) if latency_samples else np.array([0])
        
        metrics = SwarmAgentMetrics(
            agent_id=agent_id,
            timestamp=datetime.utcnow(),
            success_rate=success_rate,
            failure_rate=failure_rate,
            error_codes=error_codes,
            retry_count=retry_count,
            avg_latency_ms=float(np.mean(latency_array)),
            p50_latency_ms=float(np.percentile(latency_array, 50)),
            p95_latency_ms=float(np.percentile(latency_array, 95)),
            p99_latency_ms=float(np.percentile(latency_array, 99)),
            token_usage=token_usage,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            pnl_contribution=pnl_contribution,
            sharpe_contribution=sharpe_contribution,
            alignment_score=alignment_score,
            reputation_score=reputation_score,
            decision_entropy=decision_entropy,
            kl_divergence=kl_divergence,
            drift_detected=drift_detected,
        )
        
        self._agent_metrics[agent_id].append(metrics)
        
        # Record time series
        self._record_time_series(f"agent_{agent_id}_success_rate", MetricCategory.AGENT_LEVEL, success_rate)
        self._record_time_series(f"agent_{agent_id}_latency_p99", MetricCategory.AGENT_LEVEL, metrics.p99_latency_ms)
        
        # Check alerts
        self._check_agent_alerts(metrics)
        
        return metrics
    
    def record_workflow_metrics(
        self,
        workflow_id: str,
        total_latency_ms: float,
        agent_count: int,
        max_fan_out: int,
        max_fan_in: int,
        timeout_rate: float,
        cancellation_rate: float,
        escalation_count: int,
        override_count: int,
        safe_mode_activations: int,
        coordination_events: int,
        deconfliction_events: int,
    ) -> WorkflowMetrics:
        """Record workflow-level metrics."""
        metrics = WorkflowMetrics(
            workflow_id=workflow_id,
            timestamp=datetime.utcnow(),
            total_latency_ms=total_latency_ms,
            agent_count=agent_count,
            max_fan_out=max_fan_out,
            max_fan_in=max_fan_in,
            timeout_rate=timeout_rate,
            cancellation_rate=cancellation_rate,
            escalation_count=escalation_count,
            override_count=override_count,
            safe_mode_activations=safe_mode_activations,
            coordination_events=coordination_events,
            deconfliction_events=deconfliction_events,
        )
        
        self._workflow_metrics[workflow_id].append(metrics)
        
        # Record time series
        self._record_time_series(f"workflow_{workflow_id}_latency", MetricCategory.WORKFLOW_LEVEL, total_latency_ms)
        self._record_time_series(f"workflow_{workflow_id}_timeout_rate", MetricCategory.WORKFLOW_LEVEL, timeout_rate)
        
        # Check alerts
        self._check_workflow_alerts(metrics)
        
        return metrics
    
    def record_swarm_metrics(
        self,
        active_agents: int,
        active_workflows: int,
        llm_calls_per_second: float,
        tool_calls_per_second: float,
        total_token_usage: int,
        cost_per_scenario: float,
        total_cost_usd: float,
        cross_agent_correlation: float,
        systemic_risk_score: float,
        total_capital_deployed: float,
        capital_per_regime: Dict[str, float],
        overall_health_score: float,
        degraded_agents: int,
    ) -> SwarmMetrics:
        """Record swarm-level metrics."""
        metrics = SwarmMetrics(
            timestamp=datetime.utcnow(),
            active_agents=active_agents,
            active_workflows=active_workflows,
            llm_calls_per_second=llm_calls_per_second,
            tool_calls_per_second=tool_calls_per_second,
            total_token_usage=total_token_usage,
            cost_per_scenario=cost_per_scenario,
            total_cost_usd=total_cost_usd,
            cross_agent_correlation=cross_agent_correlation,
            systemic_risk_score=systemic_risk_score,
            total_capital_deployed=total_capital_deployed,
            capital_per_regime=capital_per_regime,
            overall_health_score=overall_health_score,
            degraded_agents=degraded_agents,
        )
        
        self._swarm_metrics.append(metrics)
        
        # Record time series
        self._record_time_series("swarm_correlation", MetricCategory.SWARM_LEVEL, cross_agent_correlation)
        self._record_time_series("swarm_cost_usd", MetricCategory.SWARM_LEVEL, total_cost_usd)
        
        # Check alerts
        self._check_swarm_alerts(metrics)
        
        return metrics
    
    def record_security_compliance_metrics(
        self,
        auth_failures: int,
        suspicious_patterns: int,
        abnormal_access_count: int,
        data_egress_volume_mb: float,
        regulator_mode_completeness: float,
        audit_trail_gaps: int,
        decision_reconstruction_time_ms: float,
        security_incidents: int,
        compliance_violations: int,
    ) -> SecurityComplianceMetrics:
        """Record security and compliance metrics."""
        metrics = SecurityComplianceMetrics(
            timestamp=datetime.utcnow(),
            auth_failures=auth_failures,
            suspicious_patterns=suspicious_patterns,
            abnormal_access_count=abnormal_access_count,
            data_egress_volume_mb=data_egress_volume_mb,
            regulator_mode_completeness=regulator_mode_completeness,
            audit_trail_gaps=audit_trail_gaps,
            decision_reconstruction_time_ms=decision_reconstruction_time_ms,
            security_incidents=security_incidents,
            compliance_violations=compliance_violations,
        )
        
        self._security_metrics.append(metrics)
        
        # Record time series
        self._record_time_series("security_incidents", MetricCategory.SECURITY_COMPLIANCE, security_incidents)
        self._record_time_series("auth_failures", MetricCategory.SECURITY_COMPLIANCE, auth_failures)
        
        # Check alerts
        self._check_security_alerts(metrics)
        
        return metrics
    
    def _record_time_series(
        self,
        metric_name: str,
        category: MetricCategory,
        value: float,
    ) -> None:
        """Record time series metric."""
        if metric_name not in self._time_series:
            self._time_series[metric_name] = TimeSeriesMetric(
                metric_name=metric_name,
                category=category,
            )
        
        ts = self._time_series[metric_name]
        ts.values.append(value)
        ts.timestamps.append(datetime.utcnow())
    
    def _check_agent_alerts(self, metrics: SwarmAgentMetrics) -> None:
        """Check agent metrics for alerts."""
        if metrics.failure_rate > self._alert_thresholds["agent_failure_rate"]:
            self._create_alert(
                alert_type="agent_high_failure_rate",
                severity="HIGH",
                description=f"Agent {metrics.agent_id} failure rate {metrics.failure_rate:.2%}",
                metrics={"agent_id": metrics.agent_id, "failure_rate": metrics.failure_rate},
            )
        
        if metrics.p99_latency_ms > self._alert_thresholds["agent_latency_p99_ms"]:
            self._create_alert(
                alert_type="agent_high_latency",
                severity="MEDIUM",
                description=f"Agent {metrics.agent_id} p99 latency {metrics.p99_latency_ms:.0f}ms",
                metrics={"agent_id": metrics.agent_id, "p99_latency_ms": metrics.p99_latency_ms},
            )
        
        if metrics.drift_detected:
            self._create_alert(
                alert_type="agent_drift_detected",
                severity="HIGH",
                description=f"Agent {metrics.agent_id} drift detected (KL={metrics.kl_divergence:.3f})",
                metrics={"agent_id": metrics.agent_id, "kl_divergence": metrics.kl_divergence},
            )
    
    def _check_workflow_alerts(self, metrics: WorkflowMetrics) -> None:
        """Check workflow metrics for alerts."""
        if metrics.timeout_rate > self._alert_thresholds["workflow_timeout_rate"]:
            self._create_alert(
                alert_type="workflow_high_timeout_rate",
                severity="HIGH",
                description=f"Workflow {metrics.workflow_id} timeout rate {metrics.timeout_rate:.2%}",
                metrics={"workflow_id": metrics.workflow_id, "timeout_rate": metrics.timeout_rate},
            )
        
        if metrics.safe_mode_activations > 0:
            self._create_alert(
                alert_type="workflow_safe_mode_activated",
                severity="CRITICAL",
                description=f"Workflow {metrics.workflow_id} safe mode activated {metrics.safe_mode_activations} times",
                metrics={"workflow_id": metrics.workflow_id, "activations": metrics.safe_mode_activations},
            )
    
    def _check_swarm_alerts(self, metrics: SwarmMetrics) -> None:
        """Check swarm metrics for alerts."""
        if metrics.cross_agent_correlation > self._alert_thresholds["swarm_correlation"]:
            self._create_alert(
                alert_type="swarm_high_correlation",
                severity="HIGH",
                description=f"Swarm correlation {metrics.cross_agent_correlation:.2%}",
                metrics={"correlation": metrics.cross_agent_correlation},
            )
        
        if metrics.degraded_agents > 0:
            self._create_alert(
                alert_type="swarm_degraded_agents",
                severity="MEDIUM",
                description=f"{metrics.degraded_agents} agents degraded",
                metrics={"degraded_agents": metrics.degraded_agents},
            )
    
    def _check_security_alerts(self, metrics: SecurityComplianceMetrics) -> None:
        """Check security metrics for alerts."""
        # Check hourly rates
        cutoff = datetime.utcnow() - timedelta(hours=1)
        recent_metrics = [m for m in self._security_metrics if m.timestamp >= cutoff]
        
        if recent_metrics:
            total_incidents = sum(m.security_incidents for m in recent_metrics)
            total_auth_failures = sum(m.auth_failures for m in recent_metrics)
            
            if total_incidents > self._alert_thresholds["security_incidents_per_hour"]:
                self._create_alert(
                    alert_type="security_high_incident_rate",
                    severity="CRITICAL",
                    description=f"{total_incidents} security incidents in last hour",
                    metrics={"incidents_per_hour": total_incidents},
                )
            
            if total_auth_failures > self._alert_thresholds["auth_failures_per_hour"]:
                self._create_alert(
                    alert_type="security_high_auth_failure_rate",
                    severity="HIGH",
                    description=f"{total_auth_failures} auth failures in last hour",
                    metrics={"auth_failures_per_hour": total_auth_failures},
                )
    
    def _create_alert(
        self,
        alert_type: str,
        severity: str,
        description: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Create monitoring alert."""
        alert = {
            "alert_id": f"{alert_type}_{datetime.utcnow().isoformat()}",
            "timestamp": datetime.utcnow(),
            "alert_type": alert_type,
            "severity": severity,
            "description": description,
            "metrics": metrics,
        }
        
        self._alerts.append(alert)
        
        logger.warning(f"Monitoring alert: {alert_type} - {description}")
    
    def analyze_swarm_decision(
        self,
        timestamp: datetime,
        decision_id: str,
    ) -> Dict[str, Any]:
        """
        Analyze "why did the swarm do X at time T?"
        
        Correlates: agent metrics, workflow metrics, swarm state, security events.
        """
        window_start = timestamp - timedelta(minutes=5)
        window_end = timestamp + timedelta(minutes=5)
        
        # Get agent metrics in window
        relevant_agent_metrics = {}
        for agent_id, metrics_list in self._agent_metrics.items():
            relevant = [
                m for m in metrics_list
                if window_start <= m.timestamp <= window_end
            ]
            if relevant:
                relevant_agent_metrics[agent_id] = relevant
        
        # Get workflow metrics in window
        relevant_workflow_metrics = {}
        for workflow_id, metrics_list in self._workflow_metrics.items():
            relevant = [
                m for m in metrics_list
                if window_start <= m.timestamp <= window_end
            ]
            if relevant:
                relevant_workflow_metrics[workflow_id] = relevant
        
        # Get swarm metrics in window
        relevant_swarm_metrics = [
            m for m in self._swarm_metrics
            if window_start <= m.timestamp <= window_end
        ]
        
        # Get security events in window
        relevant_security_metrics = [
            m for m in self._security_metrics
            if window_start <= m.timestamp <= window_end
        ]
        
        # Get alerts in window
        relevant_alerts = [
            a for a in self._alerts
            if window_start <= a["timestamp"] <= window_end
        ]
        
        return {
            "decision_id": decision_id,
            "timestamp": timestamp.isoformat(),
            "analysis_window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "agent_metrics": {
                agent_id: [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "success_rate": m.success_rate,
                        "latency_p99": m.p99_latency_ms,
                        "drift_detected": m.drift_detected,
                        "kl_divergence": m.kl_divergence,
                    }
                    for m in metrics
                ]
                for agent_id, metrics in relevant_agent_metrics.items()
            },
            "workflow_metrics": {
                workflow_id: [
                    {
                        "timestamp": m.timestamp.isoformat(),
                        "total_latency_ms": m.total_latency_ms,
                        "escalation_count": m.escalation_count,
                        "safe_mode_activations": m.safe_mode_activations,
                    }
                    for m in metrics
                ]
                for workflow_id, metrics in relevant_workflow_metrics.items()
            },
            "swarm_state": [
                {
                    "timestamp": m.timestamp.isoformat(),
                    "active_agents": m.active_agents,
                    "cross_agent_correlation": m.cross_agent_correlation,
                    "systemic_risk_score": m.systemic_risk_score,
                }
                for m in relevant_swarm_metrics
            ],
            "security_events": [
                {
                    "timestamp": m.timestamp.isoformat(),
                    "security_incidents": m.security_incidents,
                    "auth_failures": m.auth_failures,
                }
                for m in relevant_security_metrics
            ],
            "alerts": relevant_alerts,
        }
    
    def get_monitoring_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive monitoring dashboard."""
        # Get latest metrics
        latest_swarm = self._swarm_metrics[-1] if self._swarm_metrics else None
        latest_security = self._security_metrics[-1] if self._security_metrics else None
        
        # Aggregate agent metrics
        agent_summary = {}
        for agent_id, metrics_list in self._agent_metrics.items():
            if metrics_list:
                latest = metrics_list[-1]
                agent_summary[agent_id] = {
                    "success_rate": latest.success_rate,
                    "p99_latency_ms": latest.p99_latency_ms,
                    "reputation_score": latest.reputation_score,
                    "drift_detected": latest.drift_detected,
                }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "swarm": {
                "active_agents": latest_swarm.active_agents if latest_swarm else 0,
                "cross_agent_correlation": latest_swarm.cross_agent_correlation if latest_swarm else 0,
                "systemic_risk_score": latest_swarm.systemic_risk_score if latest_swarm else 0,
                "total_cost_usd": latest_swarm.total_cost_usd if latest_swarm else 0,
            },
            "agents": agent_summary,
            "security": {
                "security_incidents": latest_security.security_incidents if latest_security else 0,
                "auth_failures": latest_security.auth_failures if latest_security else 0,
                "regulator_mode_completeness": latest_security.regulator_mode_completeness if latest_security else 0,
            },
            "alerts": {
                "total": len(self._alerts),
                "last_hour": len([
                    a for a in self._alerts
                    if datetime.utcnow() - a["timestamp"] < timedelta(hours=1)
                ]),
            },
        }


_agent_monitoring_metrics: Optional[AgentMonitoringMetrics] = None
_agent_monitoring_metrics_lock = threading.Lock()


def get_agent_monitoring_metrics() -> AgentMonitoringMetrics:
    """Get global AgentMonitoringMetrics instance."""
    global _agent_monitoring_metrics
    if _agent_monitoring_metrics is None:
        with _agent_monitoring_metrics_lock:
            if _agent_monitoring_metrics is None:
                _agent_monitoring_metrics = AgentMonitoringMetrics()
    return _agent_monitoring_metrics
