"""
Observability stack integrating logs, metrics, and traces.

Provides unified interface for the three pillars of observability with
integration to information-theoretic metrics and telemetry manager.
"""

from utils.logger import get_logger
import threading
import math
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from contextlib import contextmanager
import time

from core.telemetry_manager import (
    get_telemetry_manager,
    TelemetryManager,
    DataClassification,
    TraceSpan,
)
from core.info_theory_metrics import get_info_theory_metrics
from observability.clock_sync_monitor import get_clock_sync_monitor
from observability.feed_parity_checker import get_feed_parity_checker
from observability.lag_metrics import get_lag_metrics_collector
from latency_optimizer.config import DOMAIN_SLOS

logger = get_logger(__name__)


@dataclass
class SystemMetrics:
    """System-level metrics."""
    timestamp: datetime
    service_name: str
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_rate: float
    throughput_rps: float
    queue_depth: int
    cpu_usage_pct: float
    memory_usage_mb: float


@dataclass
class TradingMetrics:
    """Trading-specific metrics."""
    timestamp: datetime
    strategy_id: str
    pnl: float
    volatility: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    hit_rate: float
    win_loss_ratio: float
    var_95: float
    cvar_95: float
    slippage_bps: float
    impact_bps: float
    fill_ratio: float
    concentration: float


@dataclass
class DriftMetrics:
    """Drift and health metrics."""
    timestamp: datetime
    component: str
    kl_divergence: float
    entropy: float
    drift_flags: int
    time_in_degraded_sec: float
    time_in_safe_mode_sec: float
    fallback_activations: int
    circuit_breaker_opens: int
    governance_overrides: int


class ObservabilityStack:
    """
    Unified observability stack for MERID trading swarm.
    
    Integrates:
    - Structured logging with correlation IDs
    - Time-series metrics (system, trading, drift)
    - Distributed tracing
    - Information-theoretic metrics
    - Privacy-aware telemetry
    """
    
    def __init__(self):
        self.telemetry = get_telemetry_manager()
        self.info_metrics = get_info_theory_metrics()
        self.clock_sync = get_clock_sync_monitor()
        self.feed_parity = get_feed_parity_checker()
        self.lag_metrics = get_lag_metrics_collector()
        
        self._system_metrics: List[SystemMetrics] = []
        self._trading_metrics: List[TradingMetrics] = []
        self._drift_metrics: List[DriftMetrics] = []
        
        self._active_spans: Dict[str, TraceSpan] = {}
    
    # ==================== Logging ====================
    
    def log_trade_intent(
        self,
        agent_id: str,
        strategy_id: str,
        venue: str,
        intent: Dict[str, Any],
        scores: Dict[str, float],
        entropy: float,
        kl_divergence: Optional[float],
        regime: str,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Log trade intent with full context."""
        self.telemetry.log_structured(
            stream_name="execution",
            level="INFO",
            event_type="trade_intent",
            message=f"Trade intent from {agent_id}",
            fields={
                "intent": intent,
                "scores": scores,
                "entropy": entropy,
                "kl_divergence": kl_divergence,
                "regime": regime,
            },
            agent_id=agent_id,
            strategy_id=strategy_id,
            venue=venue,
            correlation_id=correlation_id,
            trace_id=trace_id,
            regime_tags=[regime],
        )
    
    def log_agent_decision(
        self,
        agent_id: str,
        strategy_id: str,
        inputs_summary: Dict[str, Any],
        chosen_action: str,
        candidate_actions: List[str],
        scores: Dict[str, float],
        entropy: float,
        regime: str,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Log agent decision with inputs and alternatives."""
        self.telemetry.log_structured(
            stream_name="strategy",
            level="INFO",
            event_type="agent_decision",
            message=f"Agent {agent_id} chose {chosen_action}",
            fields={
                "inputs_summary": inputs_summary,
                "chosen_action": chosen_action,
                "candidate_actions": candidate_actions,
                "scores": scores,
                "entropy": entropy,
            },
            agent_id=agent_id,
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            regime_tags=[regime],
        )
    
    def log_fallback_activation(
        self,
        component: str,
        reason: str,
        fallback_chain: List[str],
        severity: str,
    ) -> None:
        """Log fallback activation."""
        self.telemetry.log_structured(
            stream_name="risk",
            level="WARNING",
            event_type="fallback_activation",
            message=f"Fallback activated for {component}: {reason}",
            fields={
                "component": component,
                "reason": reason,
                "fallback_chain": fallback_chain,
                "severity": severity,
            },
        )
    
    def log_circuit_breaker_event(
        self,
        service: str,
        state: str,
        error_rate: float,
        threshold: float,
    ) -> None:
        """Log circuit breaker state change."""
        self.telemetry.log_structured(
            stream_name="risk",
            level="ERROR" if state == "open" else "INFO",
            event_type="circuit_breaker",
            message=f"Circuit breaker {state} for {service}",
            fields={
                "service": service,
                "state": state,
                "error_rate": error_rate,
                "threshold": threshold,
            },
        )
    
    def log_safe_mode_event(
        self,
        action: str,
        level: int,
        reason: str,
        trigger: str,
    ) -> None:
        """Log safe mode entry/exit."""
        self.telemetry.log_structured(
            stream_name="governance",
            level="CRITICAL" if action == "enter" else "INFO",
            event_type="safe_mode",
            message=f"Safe mode {action}: {reason}",
            fields={
                "action": action,
                "level": level,
                "reason": reason,
                "trigger": trigger,
            },
        )
    
    def log_governance_action(
        self,
        action_type: str,
        target: str,
        parameters: Dict[str, Any],
        approver: str,
    ) -> None:
        """Log governance action."""
        self.telemetry.log_structured(
            stream_name="governance",
            level="INFO",
            event_type="governance_action",
            message=f"Governance action: {action_type} on {target}",
            fields={
                "action_type": action_type,
                "target": target,
                "parameters": parameters,
                "approver": approver,
            },
        )
    
    # ==================== Metrics ====================
    
    def record_system_metrics(
        self,
        service_name: str,
        latency_p50_ms: float,
        latency_p95_ms: float,
        latency_p99_ms: float,
        error_rate: float,
        throughput_rps: float,
        queue_depth: int,
        cpu_usage_pct: float,
        memory_usage_mb: float,
        *,
        clock_sync_ms: Optional[float] = None,
        feed_parity_pct: Optional[float] = None,
        lag_p95_ms: Optional[float] = None,
    ) -> None:
        """Record system-level metrics and derived observability signals."""
        metrics = SystemMetrics(
            timestamp=datetime.utcnow(),
            service_name=service_name,
            latency_p50_ms=latency_p50_ms,
            latency_p95_ms=latency_p95_ms,
            latency_p99_ms=latency_p99_ms,
            error_rate=error_rate,
            throughput_rps=throughput_rps,
            queue_depth=queue_depth,
            cpu_usage_pct=cpu_usage_pct,
            memory_usage_mb=memory_usage_mb,
        )
        
        self._system_metrics.append(metrics)
        
        # Record individual metrics
        tags = {"service": service_name}
        self.telemetry.record_metric("system", f"{service_name}.latency_p95", latency_p95_ms, tags, "ms")
        self.telemetry.record_metric("system", f"{service_name}.error_rate", error_rate, tags, "pct")
        self.telemetry.record_metric("system", f"{service_name}.throughput", throughput_rps, tags, "rps")

        if clock_sync_ms is not None:
            self.telemetry.record_metric("system", f"{service_name}.clock_sync_drift", clock_sync_ms, tags, "ms")
        if feed_parity_pct is not None:
            self.telemetry.record_metric("system", f"{service_name}.feed_parity", feed_parity_pct, tags, "pct")
        if lag_p95_ms is not None:
            self.telemetry.record_metric("system", f"{service_name}.pipeline_lag_p95", lag_p95_ms, tags, "ms")
    
    def record_trading_metrics(
        self,
        strategy_id: str,
        pnl: float,
        volatility: float,
        max_drawdown: float,
        sharpe_ratio: float,
        sortino_ratio: float,
        hit_rate: float,
        win_loss_ratio: float,
        var_95: float,
        cvar_95: float,
        slippage_bps: float,
        impact_bps: float,
        fill_ratio: float,
        concentration: float,
    ) -> None:
        """Record trading metrics."""
        metrics = TradingMetrics(
            timestamp=datetime.utcnow(),
            strategy_id=strategy_id,
            pnl=pnl,
            volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            hit_rate=hit_rate,
            win_loss_ratio=win_loss_ratio,
            var_95=var_95,
            cvar_95=cvar_95,
            slippage_bps=slippage_bps,
            impact_bps=impact_bps,
            fill_ratio=fill_ratio,
            concentration=concentration,
        )
        
        self._trading_metrics.append(metrics)
        
        # Record key metrics
        tags = {"strategy": strategy_id}
        self.telemetry.record_metric("trading", f"{strategy_id}.pnl", pnl, tags, "usd")
        self.telemetry.record_metric("trading", f"{strategy_id}.sharpe", sharpe_ratio, tags)
        self.telemetry.record_metric("trading", f"{strategy_id}.drawdown", max_drawdown, tags, "pct")
    
    def record_drift_metrics(
        self,
        component: str,
        kl_divergence: float,
        entropy: float,
        drift_flags: int,
        time_in_degraded_sec: float,
        time_in_safe_mode_sec: float,
        fallback_activations: int,
        circuit_breaker_opens: int,
        governance_overrides: int,
    ) -> None:
        """Record drift and health metrics."""
        metrics = DriftMetrics(
            timestamp=datetime.utcnow(),
            component=component,
            kl_divergence=kl_divergence,
            entropy=entropy,
            drift_flags=drift_flags,
            time_in_degraded_sec=time_in_degraded_sec,
            time_in_safe_mode_sec=time_in_safe_mode_sec,
            fallback_activations=fallback_activations,
            circuit_breaker_opens=circuit_breaker_opens,
            governance_overrides=governance_overrides,
        )
        
        self._drift_metrics.append(metrics)
        
        # Record key metrics
        tags = {"component": component}
        self.telemetry.record_metric("drift", f"{component}.kl_divergence", kl_divergence, tags)
        self.telemetry.record_metric("drift", f"{component}.entropy", entropy, tags)
        self.telemetry.record_metric("drift", f"{component}.drift_flags", drift_flags, tags)
    
    # ==================== Tracing ====================
    
    @contextmanager
    def trace_operation(
        self,
        operation_name: str,
        stream_name: str = "execution",
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for tracing an operation."""
        span = self.telemetry.start_trace_span(
            stream_name=stream_name,
            operation_name=operation_name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            tags=tags,
        )
        
        self._active_spans[span.span_id] = span
        
        try:
            yield span
        except Exception as e:
            self.telemetry.add_span_log(span, {
                "event": "error",
                "error_type": type(e).__name__,
                "error_message": str(e),
            })
            raise
        finally:
            self.telemetry.end_trace_span(span)
            del self._active_spans[span.span_id]
    
    def trace_decision_flow(
        self,
        agent_id: str,
        strategy_id: str,
    ) -> str:
        """Start tracing a complete decision flow."""
        span = self.telemetry.start_trace_span(
            stream_name="execution",
            operation_name="decision_flow",
            tags={
                "agent_id": agent_id,
                "strategy_id": strategy_id,
            },
        )
        
        self._active_spans[span.span_id] = span
        
        return span.trace_id
    
    # ==================== Query & Analytics ====================
    
    def get_system_metrics(
        self,
        service_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[SystemMetrics]:
        """Query system metrics."""
        metrics = self._system_metrics
        
        if service_name:
            metrics = [m for m in metrics if m.service_name == service_name]
        
        if since:
            metrics = [m for m in metrics if m.timestamp >= since]
        
        return metrics[-limit:]
    
    def get_trading_metrics(
        self,
        strategy_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[TradingMetrics]:
        """Query trading metrics."""
        metrics = self._trading_metrics
        
        if strategy_id:
            metrics = [m for m in metrics if m.strategy_id == strategy_id]
        
        if since:
            metrics = [m for m in metrics if m.timestamp >= since]
        
        return metrics[-limit:]
    
    def get_drift_metrics(
        self,
        component: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[DriftMetrics]:
        """Query drift metrics."""
        metrics = self._drift_metrics
        
        if component:
            metrics = [m for m in metrics if m.component == component]
        
        if since:
            metrics = [m for m in metrics if m.timestamp >= since]
        
        return metrics[-limit:]
    
    def get_lag_summary(self) -> Dict[str, object]:
        """Expose lag metrics collector summary."""
        return self.lag_metrics.get_lag_summary()
    
    def get_observability_dashboards(self) -> Dict[str, Any]:
        """Return dashboard-ready payloads for UI panels."""
        latency_dashboard = self.get_latency_dashboard()
        return {
            "clock_sync": self.clock_sync.get_sync_status(),
            "feed_parity": self.feed_parity.get_parity_status(),
            "lag_metrics": self.lag_metrics.get_lag_summary(),
            "latency": latency_dashboard,
            "latency_alerts": self.evaluate_latency_alerts(latency_dashboard),
        }
    
    def get_observability_summary(self) -> Dict[str, Any]:
        """Get comprehensive observability summary."""
        latency_dashboard = self.get_latency_dashboard()
        latency_alerts = self.evaluate_latency_alerts(latency_dashboard)
        return {
            "system_metrics": {
                "total": len(self._system_metrics),
                "services": len(set(m.service_name for m in self._system_metrics)),
            },
            "trading_metrics": {
                "total": len(self._trading_metrics),
                "strategies": len(set(m.strategy_id for m in self._trading_metrics)),
            },
            "drift_metrics": {
                "total": len(self._drift_metrics),
                "components": len(set(m.component for m in self._drift_metrics)),
            },
            "telemetry": self.telemetry.get_telemetry_stats(),
            "info_theory": self.info_metrics.get_drift_summary(),
            "active_traces": len(self._active_spans),
            "dashboards": self.get_observability_dashboards(),
            "latency": {
                "dashboard": latency_dashboard,
                "alerts": latency_alerts,
            },
        }

    # ==================== Latency Dashboards & Alerts ====================

    def get_latency_dashboard(self, since: Optional[datetime] = None) -> Dict[str, Any]:
        """Aggregate latency metrics per workflow for dashboard consumption."""

        if since is None:
            since = datetime.utcnow() - timedelta(minutes=30)

        workflows: List[Dict[str, Any]] = []
        for domain, workflow_defs in DOMAIN_SLOS.items():
            for workflow, slo in workflow_defs.items():
                metric_name = f"{domain}.{workflow}"
                samples = self.telemetry.get_metrics(
                    metric_name=metric_name,
                    since=since,
                    limit=500,
                )
                values = [pt.value for pt in samples]

                count_points = self.telemetry.get_metrics(
                    metric_name=f"{metric_name}.count",
                    since=since,
                    limit=500,
                )
                total_invocations = sum(pt.value for pt in count_points)
                if total_invocations == 0 and values:
                    total_invocations = len(values)

                status_counts: Dict[str, float] = {}
                for status in (
                    "within_budget",
                    "approaching_budget",
                    "breached_slo",
                    "deadline_violation",
                ):
                    status_points = self.telemetry.get_metrics(
                        metric_name=f"{metric_name}.status.{status}",
                        since=since,
                        limit=500,
                    )
                    status_counts[status] = sum(pt.value for pt in status_points)

                fallback_points = self.telemetry.get_metrics(
                    metric_name=f"{metric_name}.fallback",
                    since=since,
                    limit=500,
                )
                fallback_count = sum(pt.value for pt in fallback_points)
                fallback_rate = (
                    fallback_count / total_invocations
                    if total_invocations
                    else 0.0
                )

                workflows.append(
                    {
                        "domain": domain,
                        "workflow": workflow,
                        "metric": metric_name,
                        "sample_count": len(values),
                        "latest_timestamp": samples[-1].timestamp.isoformat()
                        if samples
                        else None,
                        "latest_ms": values[-1] if values else None,
                        "p50_ms": self._percentile(values, 0.50),
                        "p95_ms": self._percentile(values, 0.95),
                        "p99_ms": self._percentile(values, 0.99),
                        "status_counts": status_counts,
                        "total_invocations": total_invocations,
                        "fallback_count": fallback_count,
                        "fallback_rate": fallback_rate,
                        "breach_rate": (
                            status_counts.get("breached_slo", 0.0)
                            / total_invocations
                            if total_invocations
                            else 0.0
                        ),
                        "slo": {
                            "p50_ms": slo.budget.p50_ms,
                            "p95_ms": slo.budget.p95_ms,
                            "hard_deadline_ms": slo.budget.hard_deadline_ms,
                            "fallback_chain": [
                                {
                                    "strategy_id": strat.strategy_id,
                                    "description": strat.description,
                                    "action": strat.action,
                                }
                                for strat in slo.fallback_chain
                            ],
                        },
                        "tag_heatmap": self._build_tag_heatmap(samples),
                    }
                )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "window_start": since.isoformat(),
            "workflows": workflows,
        }

    def evaluate_latency_alerts(
        self,
        dashboard: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate latency alerts based on dashboard stats."""

        if dashboard is None:
            dashboard = self.get_latency_dashboard()

        workflows = {
            (wf["domain"], wf["workflow"]): wf
            for wf in dashboard.get("workflows", [])
        }

        def get_workflow(domain: str, workflow: str) -> Optional[Dict[str, Any]]:
            return workflows.get((domain, workflow))

        alerts: List[Dict[str, Any]] = []

        def build_alert(
            name: str,
            domain: str,
            workflow: str,
            condition: str,
            action: str,
            triggered: bool,
            observed: Optional[float],
            threshold: Optional[float],
            reason: str,
            available: bool,
        ) -> Dict[str, Any]:
            status = "breach" if triggered else ("ok" if available else "insufficient_data")
            return {
                "name": name,
                "workflow": {"domain": domain, "workflow": workflow},
                "status": status,
                "condition": condition,
                "action": action,
                "observed": observed,
                "threshold": threshold,
                "reason": reason,
            }

        trading = get_workflow("trading", "tick_to_order")
        trading_available = bool(trading and trading["sample_count"])
        trading_triggered = (
            trading_available
            and trading.get("p95_ms") is not None
            and trading["p95_ms"] > trading["slo"]["p95_ms"]
        )
        alerts.append(
            build_alert(
                name="Trading SLO Breach",
                domain="trading",
                workflow="tick_to_order",
                condition="p95 latency > 12 ms over rolling window",
                action="Page trading ops (OpsGenie) and auto-create incident ticket.",
                triggered=trading_triggered,
                observed=trading.get("p95_ms") if trading else None,
                threshold=trading["slo"]["p95_ms"] if trading else 12.0,
                reason="p95 latency exceeds SLO" if trading_triggered else "Within SLO",
                available=trading_available,
            )
        )

        social = get_workflow("social", "signal_gate")
        social_available = bool(social and social["sample_count"])
        social_triggered = (
            social_available
            and (
                (social.get("p95_ms") or 0) > 80.0
                or social.get("fallback_rate", 0.0) > 0.30
            )
        )
        alerts.append(
            build_alert(
                name="Social Gate Degraded",
                domain="social",
                workflow="signal_gate",
                condition="p95 latency > 80 ms or fallback ratio > 30%",
                action="Notify social strategy lead via Slack and throttle low-priority ingestion.",
                triggered=social_triggered,
                observed=social.get("p95_ms") if social else None,
                threshold=80.0,
                reason="Latency or fallback ratio beyond targets"
                if social_triggered
                else "Within budget",
                available=social_available,
            )
        )

        dev_swarm = get_workflow("dev_swarm", "command_execution")
        dev_available = bool(dev_swarm and dev_swarm["sample_count"])
        dev_triggered = (
            dev_available
            and (
                (dev_swarm.get("p95_ms") or 0) > 750.0
                or dev_swarm.get("fallback_count", 0) >= 5
                or dev_swarm.get("fallback_rate", 0.0) > 0.20
            )
        )
        alerts.append(
            build_alert(
                name="Dev Swarm Latency Regression",
                domain="dev_swarm",
                workflow="command_execution",
                condition="p95 latency > 750 ms OR >5 fallbacks / hr",
                action="Page platform on-call and flip orchestrator into fast preset.",
                triggered=dev_triggered,
                observed=dev_swarm.get("p95_ms") if dev_swarm else None,
                threshold=750.0,
                reason="Latency slice degraded" if dev_triggered else "Within bounds",
                available=dev_available,
            )
        )

        llm = get_workflow("llm", "default_request")
        llm_available = bool(llm and llm["sample_count"])
        llm_triggered = (
            llm_available
            and (llm.get("p95_ms") or 0) > 3500.0
            and llm.get("fallback_rate", 0.0) > 0.10
        )
        alerts.append(
            build_alert(
                name="LLM Latency Exhaustion",
                domain="llm",
                workflow="default_request",
                condition="p95 latency > 3.5 s with fallback ratio > 10%",
                action="Route to model serving team; trigger automatic routing to smaller model.",
                triggered=llm_triggered,
                observed=llm.get("p95_ms") if llm else None,
                threshold=3500.0,
                reason="LLM channel saturated" if llm_triggered else "Healthy",
                available=llm_available,
            )
        )

        return alerts

    def _percentile(self, values: List[float], percentile: float) -> Optional[float]:
        if not values:
            return None
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_values[int(k)]
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return d0 + d1

    def _build_tag_heatmap(
        self,
        samples: List[Any],
        *,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        heatmap: Dict[str, Dict[str, int]] = {}
        for point in samples:
            for tag_key, tag_value in point.tags.items():
                bucket = heatmap.setdefault(tag_key, {})
                bucket[tag_value] = bucket.get(tag_value, 0) + 1

        structured: List[Dict[str, Any]] = []
        for tag, counts in heatmap.items():
            top_values = sorted(
                counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:top_n]
            structured.append(
                {
                    "tag": tag,
                    "top_values": [
                        {"value": value, "count": count}
                        for value, count in top_values
                    ],
                }
            )

        return structured


# Global singleton
_observability_stack: Optional[ObservabilityStack] = None
_observability_stack_lock = threading.Lock()


def get_observability_stack() -> ObservabilityStack:
    """Get global ObservabilityStack instance."""
    global _observability_stack
    if _observability_stack is None:
        with _observability_stack_lock:
            if _observability_stack is None:
                _observability_stack = ObservabilityStack()
    return _observability_stack
