"""
Observability and Incident Maturity System for MERID Phase 4

Provides comprehensive observability, SLO tracking, and incident management
with end-to-end synthetic canary and mature incident response capabilities.

Features:
- Critical path instrumentation with tracing and correlation
- Trading SLOs with threshold-based alerting
- End-to-end synthetic canary testing
- Incident management maturity framework
- Real-time monitoring and alerting
"""

import asyncio
import time
import uuid
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque, defaultdict
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("operations.observability")

class IncidentMaturityLevel(Enum):
    """Incident management maturity levels."""
    CHAOTIC = "chaotic"          # No processes, reactive only
    REACTIVE = "reactive"        # Basic processes, ad-hoc response
    MANAGED = "managed"          # Consistent workflows, templates, postmortems
    OPTIMIZED = "optimized"      # Proactive monitoring, automated responses
    SELF_HEALING = "self_healing" # Automated detection and resolution

class MetricType(Enum):
    """Metric type enumeration."""
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    QUEUE_DEPTH = "queue_depth"
    DROPPED_MESSAGES = "dropped_messages"
    DISCONNECTED_VENUES = "disconnected_venues"
    PNL = "pnl"
    DRAWDOWN = "drawdown"
    SLIPPAGE = "slippage"

class AlertSeverity(Enum):
    """Alert severity enumeration."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

@dataclass
class TraceEvent:
    """Trace event definition."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    service_name: str
    timestamp: datetime
    duration_ms: float
    tags: Dict[str, str]
    logs: List[Dict[str, Any]]
    status: str

@dataclass
class SLO:
    """Service Level Objective definition."""
    slo_id: str
    name: str
    metric_type: MetricType
    target_value: float
    threshold_value: float
    time_window_seconds: int
    current_value: float
    status: str
    last_updated: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CanaryTest:
    """Canary test definition."""
    test_id: str
    test_name: str
    test_type: str
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: float
    success: bool
    error_message: Optional[str]
    metrics: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class IncidentTemplate:
    """Incident response template."""
    template_id: str
    incident_type: str
    severity: AlertSeverity
    description: str
    response_steps: List[str]
    escalation_rules: List[str]
    communication_template: str
    postmortem_questions: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

class Observability:
    """
    Comprehensive observability and incident maturity system for MERID.
    
    Provides critical path instrumentation, SLO tracking, synthetic canary
    testing, and mature incident management with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Trace events
        self.trace_events: Dict[str, List[TraceEvent]] = defaultdict(list)
        
        # SLOs
        self.slos: Dict[str, SLO] = {}
        
        # Canary tests
        self.canary_tests: Dict[str, CanaryTest] = {}
        
        # Incident templates
        self.incident_templates: Dict[str, IncidentTemplate] = {}
        
        # Metrics storage
        self.metrics_storage: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        
        # Configuration
        self.observability_config = config.get("observability", {
            "trace_retention_hours": 24,
            "slo_evaluation_interval": 60,  # 1 minute
            "canary_interval": 300,  # 5 minutes
            "incident_maturity_level": IncidentMaturityLevel.MANAGED.value,
            "alert_threshold_window": 300  # 5 minutes
        })
        
        # SLO definitions
        self.slo_definitions = {
            "order_latency_p99": {
                "name": "Order Submission Latency p99",
                "metric_type": MetricType.LATENCY,
                "target_value": 500.0,  # 500ms
                "threshold_value": 1000.0,  # 1s
                "time_window_seconds": 300  # 5 minutes
            },
            "order_failure_rate": {
                "name": "Order Failure Rate",
                "metric_type": MetricType.ERROR_RATE,
                "target_value": 0.01,  # 1%
                "threshold_value": 0.05,  # 5%
                "time_window_seconds": 300
            },
            "queue_depth": {
                "name": "Message Queue Depth",
                "metric_type": MetricType.QUEUE_DEPTH,
                "target_value": 100.0,
                "threshold_value": 1000.0,
                "time_window_seconds": 300
            },
            "dropped_messages": {
                "name": "Dropped Messages Rate",
                "metric_type": MetricType.DROPPED_MESSAGES,
                "target_value": 0.0,
                "threshold_value": 10.0,
                "time_window_seconds": 300
            },
            "venue_connectivity": {
                "name": "Disconnected Venues",
                "metric_type": MetricType.DISCONNECTED_VENUES,
                "target_value": 0.0,
                "threshold_value": 1.0,
                "time_window_seconds": 60
            },
            "daily_drawdown": {
                "name": "Daily Drawdown",
                "metric_type": MetricType.DRAWDOWN,
                "target_value": 0.02,  # 2%
                "threshold_value": 0.05,  # 5%
                "time_window_seconds": 86400  # 24 hours
            }
        }
        
        # Incident templates
        self.incident_template_definitions = {
            "latency_spike": IncidentTemplate(
                template_id="latency_spike",
                incident_type="Performance Degradation",
                severity=AlertSeverity.CRITICAL,
                description="Significant increase in system latency detected",
                response_steps=[
                    "Check system resource utilization",
                    "Verify database performance",
                    "Check external service dependencies",
                    "Review recent deployments",
                    "Consider circuit breaker activation"
                ],
                escalation_rules=[
                    "Escalate to engineering lead after 15 minutes",
                    "Escalate to CTO after 30 minutes"
                ],
                communication_template="LATENCY_SPIKE_ALERT",
                postmortem_questions=[
                    "What was the root cause of the latency spike?",
                    "How can we prevent this in the future?",
                    "Were monitoring thresholds appropriate?"
                ]
            ),
            "venue_downtime": IncidentTemplate(
                template_id="venue_downtime",
                incident_type="External Service Failure",
                severity=AlertSeverity.CRITICAL,
                description="Trading venue API or connectivity failure",
                response_steps=[
                    "Verify venue status page",
                    "Check network connectivity",
                    "Test venue API endpoints",
                    "Switch to backup venue if available",
                    "Notify trading desk"
                ],
                escalation_rules=[
                    "Escalate to operations lead immediately",
                    "Escalate to trading desk lead after 5 minutes"
                ],
                communication_template="VENUE_DOWNTIME_ALERT",
                postmortem_questions=[
                    "Was the venue failure predictable?",
                    "Do we need additional venue redundancy?",
                    "How quickly did we detect and respond?"
                ]
            ),
            "bad_data": IncidentTemplate(
                template_id="bad_data",
                incident_type="Data Quality Issue",
                severity=AlertSeverity.EMERGENCY,
                description="Invalid or corrupted market data detected",
                response_steps=[
                    "Stop all trading immediately",
                    "Identify data source issues",
                    "Switch to backup data feeds",
                    "Validate data quality checks",
                    "Review data validation logic"
                ],
                escalation_rules=[
                    "Escalate to engineering lead immediately",
                    "Escalate to CTO immediately"
                ],
                communication_template="BAD_DATA_ALERT",
                postmortem_questions=[
                    "How did bad data bypass validation?",
                    "Are our data quality checks sufficient?",
                    "Do we need additional data sources?"
                ]
            )
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "audit_tracing": True,
            "slo_disclosure": True,
            "incident_reporting": True,
            "data_retention": True
        })
        
        logger.info("Observability system initialized")
    
    async def trace_critical_path(self, operation_name: str, service_name: str,
                                correlation_id: str, account: str, symbol: str,
                                venue: str, order_id: Optional[str] = None,
                                metadata: Optional[Dict[str, Any]] = None) -> str:
        """Trace a critical path operation."""
        try:
            trace_id = correlation_id
            span_id = str(uuid.uuid4())
            
            # Create trace event
            trace_event = TraceEvent(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                operation_name=operation_name,
                service_name=service_name,
                timestamp=datetime.now(),
                duration_ms=0.0,  # Will be updated when operation completes
                tags={
                    "correlation_id": correlation_id,
                    "account": account,
                    "symbol": symbol,
                    "venue": venue,
                    "order_id": order_id or "none"
                },
                logs=[],
                status="started"
            )
            
            # Add metadata tags
            if metadata:
                trace_event.tags.update(metadata)
            
            # Store trace event
            self.trace_events[trace_id].append(trace_event)
            
            # Record for compliance
            if self.us_compliance.get("audit_tracing", True):
                await self._record_trace_event(trace_event)
            
            return span_id
            
        except Exception as e:
            logger.error(f"Failed to trace critical path: {e}")
            return ""
    
    async def complete_trace(self, trace_id: str, span_id: str, 
                           status: str, logs: Optional[List[Dict[str, Any]]] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Complete a trace span."""
        try:
            if trace_id not in self.trace_events:
                logger.error(f"Trace {trace_id} not found")
                return False
            
            # Find the span
            trace_event = None
            for event in self.trace_events[trace_id]:
                if event.span_id == span_id:
                    trace_event = event
                    break
            
            if not trace_event:
                logger.error(f"Span {span_id} not found in trace {trace_id}")
                return False
            
            # Update trace event
            trace_event.status = status
            trace_event.duration_ms = (datetime.now() - trace_event.timestamp).total_seconds() * 1000
            
            if logs:
                trace_event.logs.extend(logs)
            
            if metadata:
                trace_event.tags.update(metadata)
            
            # Update metrics based on operation
            await self._update_metrics_from_trace(trace_event)
            
            logger.debug(f"Trace completed: {trace_id}/{span_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete trace: {e}")
            return False
    
    async def _update_metrics_from_trace(self, trace_event: TraceEvent):
        """Update metrics from trace event."""
        try:
            # Update latency metrics
            if "latency" in trace_event.operation_name.lower():
                await self._record_metric(
                    MetricType.LATENCY,
                    trace_event.duration_ms,
                    {
                        "operation": trace_event.operation_name,
                        "service": trace_event.service_name,
                        "symbol": trace_event.tags.get("symbol", "unknown"),
                        "venue": trace_event.tags.get("venue", "unknown")
                    }
                )
            
            # Update error metrics
            if trace_event.status == "error":
                await self._record_metric(
                    MetricType.ERROR_RATE,
                    1.0,
                    {
                        "operation": trace_event.operation_name,
                        "service": trace_event.service_name,
                        "error_type": trace_event.tags.get("error_type", "unknown")
                    }
                )
            
            # Update throughput metrics
            if "order" in trace_event.operation_name.lower():
                await self._record_metric(
                    MetricType.THROUGHPUT,
                    1.0,
                    {
                        "operation": trace_event.operation_name,
                        "service": trace_event.service_name,
                        "symbol": trace_event.tags.get("symbol", "unknown"),
                        "venue": trace_event.tags.get("venue", "unknown")
                    }
                )
            
        except Exception as e:
            logger.error(f"Failed to update metrics from trace: {e}")
    
    async def _record_metric(self, metric_type: MetricType, value: float,
                           tags: Dict[str, str]):
        """Record a metric."""
        try:
            timestamp = datetime.now()
            
            # Store metric
            metric_key = f"{metric_type.value}_{hash(str(tags))}"
            self.metrics_storage[metric_key].append({
                "timestamp": timestamp,
                "value": value,
                "tags": tags
            })
            
            # Update SLOs
            await self._update_slos(metric_type, value, tags)
            
        except Exception as e:
            logger.error(f"Failed to record metric: {e}")
    
    async def _update_slos(self, metric_type: MetricType, value: float,
                          tags: Dict[str, str]):
        """Update SLOs based on metric."""
        try:
            # Find relevant SLOs
            for slo_id, slo in self.slos.items():
                if slo.metric_type == metric_type:
                    # Update current value (simplified - in production, use proper aggregation)
                    slo.current_value = value
                    slo.last_updated = datetime.now()
                    
                    # Update status
                    if slo.current_value <= slo.target_value:
                        slo.status = "healthy"
                    elif slo.current_value <= slo.threshold_value:
                        slo.status = "warning"
                    else:
                        slo.status = "critical"
                        
                        # Create alert for SLO breach
                        await self._create_slo_alert(slo, value)
            
        except Exception as e:
            logger.error(f"Failed to update SLOs: {e}")
    
    async def _create_slo_alert(self, slo: SLO, current_value: float):
        """Create alert for SLO breach."""
        try:
            alert_data = {
                "alert_id": f"slo_breach_{slo.slo_id}",
                "slo_id": slo.slo_id,
                "slo_name": slo.name,
                "current_value": current_value,
                "threshold": slo.threshold_value,
                "severity": "critical" if current_value > slo.threshold_value else "warning",
                "timestamp": datetime.now().isoformat()
            }
            
            # In production, send to alerting system
            logger.warning(f"SLO breach alert: {alert_data}")
            
        except Exception as e:
            logger.error(f"Failed to create SLO alert: {e}")
    
    async def initialize_slos(self) -> bool:
        """Initialize SLOs."""
        try:
            for slo_id, slo_def in self.slo_definitions.items():
                slo = SLO(
                    slo_id=slo_id,
                    name=slo_def["name"],
                    metric_type=slo_def["metric_type"],
                    target_value=slo_def["target_value"],
                    threshold_value=slo_def["threshold_value"],
                    time_window_seconds=slo_def["time_window_seconds"],
                    current_value=0.0,
                    status="healthy",
                    last_updated=datetime.now()
                )
                
                self.slos[slo_id] = slo
            
            logger.info(f"Initialized {len(self.slos)} SLOs")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SLOs: {e}")
            return False
    
    async def run_canary_test(self, test_type: str = "synthetic_order") -> CanaryTest:
        """Run end-to-end synthetic canary test."""
        try:
            test_id = str(uuid.uuid4())
            test_name = f"Canary Test - {test_type}"
            
            canary_test = CanaryTest(
                test_id=test_id,
                test_name=test_name,
                test_type=test_type,
                status="running",
                start_time=datetime.now(),
                end_time=None,
                duration_ms=0.0,
                success=False,
                error_message=None,
                metrics={},
                metadata={}
            )
            
            self.canary_tests[test_id] = canary_test
            
            logger.info(f"Starting canary test: {test_id}")
            
            # Run different test types
            if test_type == "synthetic_order":
                success = await self._run_synthetic_order_canary(canary_test)
            elif test_type == "health_check":
                success = await self._run_health_check_canary(canary_test)
            elif test_type == "data_flow":
                success = await self._run_data_flow_canary(canary_test)
            else:
                success = await self._run_basic_canary(canary_test)
            
            # Complete test
            canary_test.end_time = datetime.now()
            canary_test.duration_ms = (canary_test.end_time - canary_test.start_time).total_seconds() * 1000
            canary_test.success = success
            canary_test.status = "completed" if success else "failed"
            
            # Create alert if test failed
            if not success:
                await self._create_canary_alert(canary_test)
            
            logger.info(f"Canary test completed: {test_id} - {'SUCCESS' if success else 'FAILED'}")
            return canary_test
            
        except Exception as e:
            logger.error(f"Failed to run canary test: {e}")
            
            # Create failed test
            failed_test = CanaryTest(
                test_id=str(uuid.uuid4()),
                test_name="Failed Canary Test",
                test_type=test_type,
                status="failed",
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_ms=0.0,
                success=False,
                error_message=str(e),
                metrics={},
                metadata={}
            )
            
            return failed_test
    
    async def _run_synthetic_order_canary(self, canary_test: CanaryTest) -> bool:
        """Run synthetic order canary test."""
        try:
            # Mock synthetic order flow
            # In production, this would send actual test orders through the system
            
            # Step 1: Create test order
            await asyncio.sleep(0.1)  # Simulate processing time
            
            # Step 2: Submit to venue
            await asyncio.sleep(0.05)  # Simulate venue latency
            
            # Step 3: Get confirmation
            await asyncio.sleep(0.05)  # Simulate confirmation latency
            
            # Step 4: Cancel order
            await asyncio.sleep(0.05)  # Simulate cancel latency
            
            # Record metrics
            canary_test.metrics = {
                "order_creation_ms": 100,
                "venue_submission_ms": 50,
                "confirmation_ms": 50,
                "cancellation_ms": 50,
                "total_latency_ms": 250
            }
            
            # Validate metrics
            if canary_test.metrics["total_latency_ms"] > 1000:
                canary_test.error_message = "Order latency too high"
                return False
            
            return True
            
        except Exception as e:
            canary_test.error_message = str(e)
            return False
    
    async def _run_health_check_canary(self, canary_test: CanaryTest) -> bool:
        """Run health check canary test."""
        try:
            # Mock health checks
            health_checks = {
                "database": "healthy",
                "redis": "healthy",
                "message_queue": "healthy",
                "venue_apis": "healthy",
                "ai_models": "healthy"
            }
            
            # Simulate health check latency
            await asyncio.sleep(0.2)
            
            canary_test.metrics = {
                "health_check_ms": 200,
                "services_healthy": len([v for v in health_checks.values() if v == "healthy"]),
                "services_total": len(health_checks)
            }
            
            # All services should be healthy
            if canary_test.metrics["services_healthy"] != canary_test.metrics["services_total"]:
                canary_test.error_message = "Some services unhealthy"
                return False
            
            return True
            
        except Exception as e:
            canary_test.error_message = str(e)
            return False
    
    async def _run_data_flow_canary(self, canary_test: CanaryTest) -> bool:
        """Run data flow canary test."""
        try:
            # Mock data flow test
            # In production, this would test actual data flow through the system
            
            # Step 1: Ingest market data
            await asyncio.sleep(0.01)
            
            # Step 2: Process through AI models
            await asyncio.sleep(0.05)
            
            # Step 3: Generate signals
            await asyncio.sleep(0.02)
            
            # Step 4: Execute decisions
            await asyncio.sleep(0.02)
            
            canary_test.metrics = {
                "data_ingestion_ms": 10,
                "ai_processing_ms": 50,
                "signal_generation_ms": 20,
                "decision_execution_ms": 20,
                "total_flow_ms": 100
            }
            
            # Validate flow
            if canary_test.metrics["total_flow_ms"] > 500:
                canary_test.error_message = "Data flow too slow"
                return False
            
            return True
            
        except Exception as e:
            canary_test.error_message = str(e)
            return False
    
    async def _run_basic_canary(self, canary_test: CanaryTest) -> bool:
        """Run basic canary test."""
        try:
            # Basic connectivity test
            await asyncio.sleep(0.1)
            
            canary_test.metrics = {
                "connectivity_ms": 100
            }
            
            return True
            
        except Exception as e:
            canary_test.error_message = str(e)
            return False
    
    async def _create_canary_alert(self, canary_test: CanaryTest):
        """Create alert for canary test failure."""
        try:
            alert_data = {
                "alert_id": f"canary_failure_{canary_test.test_id}",
                "test_id": canary_test.test_id,
                "test_name": canary_test.test_name,
                "test_type": canary_test.test_type,
                "error_message": canary_test.error_message,
                "duration_ms": canary_test.duration_ms,
                "severity": "critical",
                "timestamp": canary_test.end_time.isoformat() if canary_test.end_time else datetime.now().isoformat()
            }
            
            # In production, send to alerting system
            logger.error(f"Canary test failure alert: {alert_data}")
            
        except Exception as e:
            logger.error(f"Failed to create canary alert: {e}")
    
    def get_incident_maturity_level(self) -> IncidentMaturityLevel:
        """Get current incident maturity level."""
        return IncidentMaturityLevel(self.observability_config.get("incident_maturity_level", IncidentMaturityLevel.MANAGED.value))
    
    def get_slo_status(self) -> Dict[str, Any]:
        """Get SLO status summary."""
        try:
            if not self.slos:
                return {"status": "no_slos"}
            
            slo_statuses = {}
            for slo_id, slo in self.slos.items():
                slo_statuses[slo_id] = {
                    "name": slo.name,
                    "current_value": slo.current_value,
                    "target_value": slo.target_value,
                    "threshold_value": slo.threshold_value,
                    "status": slo.status,
                    "last_updated": slo.last_updated.isoformat()
                }
            
            # Overall health
            healthy_slos = sum(1 for slo in self.slos.values() if slo.status == "healthy")
            total_slos = len(self.slos)
            health_percentage = (healthy_slos / total_slos) * 100 if total_slos > 0 else 0
            
            return {
                "total_slos": total_slos,
                "healthy_slos": healthy_slos,
                "health_percentage": health_percentage,
                "slo_statuses": slo_statuses,
                "maturity_level": self.get_incident_maturity_level().value,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get SLO status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_canary_status(self) -> Dict[str, Any]:
        """Get canary test status."""
        try:
            if not self.canary_tests:
                return {"status": "no_canary_tests"}
            
            # Recent tests
            recent_tests = list(self.canary_tests.values())[-10:]
            
            # Success rate
            successful_tests = sum(1 for test in recent_tests if test.success)
            total_tests = len(recent_tests)
            success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0
            
            # Latest test
            latest_test = recent_tests[-1] if recent_tests else None
            
            return {
                "total_tests": len(self.canary_tests),
                "recent_tests": total_tests,
                "successful_tests": successful_tests,
                "success_rate": success_rate,
                "latest_test": {
                    "test_id": latest_test.test_id,
                    "test_name": latest_test.test_name,
                    "status": latest_test.status,
                    "success": latest_test.success,
                    "duration_ms": latest_test.duration_ms,
                    "timestamp": latest_test.end_time.isoformat() if latest_test.end_time else None
                } if latest_test else None,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get canary status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_observability_summary(self) -> Dict[str, Any]:
        """Get comprehensive observability summary."""
        try:
            # Get individual summaries
            slo_status = self.get_slo_status()
            canary_status = self.get_canary_status()
            
            # Trace summary
            total_traces = len(self.trace_events)
            recent_traces = sum(len(events) for events in self.trace_events.values())
            
            # Metrics summary
            total_metrics = sum(len(metrics) for metrics in self.metrics_storage.values())
            
            return {
                "incident_maturity_level": self.get_incident_maturity_level().value,
                "total_traces": total_traces,
                "recent_trace_events": recent_traces,
                "total_metrics": total_metrics,
                "slo_status": slo_status,
                "canary_status": canary_status,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get observability summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _record_trace_event(self, trace_event: TraceEvent):
        """Record trace event for compliance."""
        if not self.us_compliance.get("audit_tracing", True):
            return
        
        audit_entry = {
            "action": "trace_event",
            "trace_id": trace_event.trace_id,
            "span_id": trace_event.span_id,
            "operation_name": trace_event.operation_name,
            "service_name": trace_event.service_name,
            "timestamp": trace_event.timestamp.isoformat(),
            "duration_ms": trace_event.duration_ms,
            "status": trace_event.status,
            "tags": trace_event.tags,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Trace event audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update observability configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "observability" in new_config:
            self.observability_config.update(new_config["observability"])
        
        logger.info("Observability configuration updated")
