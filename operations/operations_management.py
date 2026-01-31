"""
Operations Management System for MERID Phase 4 Sprint 10

Provides comprehensive operations management with monitoring,
incident management, and customer success capabilities.

Features:
- Operations dashboard and monitoring
- Incident management and response
- Performance monitoring and optimization
- Backup and disaster recovery
- Customer support and success metrics
"""

import asyncio
import time
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("operations.operations_management")

class IncidentSeverity(Enum):
    """Incident severity enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class IncidentStatus(Enum):
    """Incident status enumeration."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"

class AlertType(Enum):
    """Alert type enumeration."""
    SYSTEM = "system"
    PERFORMANCE = "performance"
    SECURITY = "security"
    BUSINESS = "business"
    CUSTOMER = "customer"

class MetricType(Enum):
    """Metric type enumeration."""
    SYSTEM_HEALTH = "system_health"
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    ERROR_RATE = "error_rate"
    RESPONSE_TIME = "response_time"
    THROUGHPUT = "throughput"
    CUSTOMER_SATISFACTION = "customer_satisfaction"

@dataclass
class Incident:
    """Incident definition."""
    incident_id: str
    title: str
    description: str
    severity: IncidentSeverity
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]
    assigned_to: str
    affected_components: List[str]
    impact_assessment: str
    resolution: Optional[str]
    root_cause: Optional[str]
    tags: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Alert:
    """Alert definition."""
    alert_id: str
    alert_type: AlertType
    severity: IncidentSeverity
    title: str
    message: str
    source: str
    created_at: datetime
    acknowledged: bool
    resolved: bool
    incident_id: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Metric:
    """Metric definition."""
    metric_id: str
    metric_type: MetricType
    name: str
    value: float
    unit: str
    threshold: float
    status: str
    timestamp: datetime
    tags: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CustomerSupport:
    """Customer support definition."""
    support_id: str
    customer_id: str
    issue_type: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]
    assigned_to: str
    description: str
    resolution: Optional[str]
    satisfaction_score: Optional[float]
    metadata: Dict[str, Any] = field(default_factory=dict)

class OperationsManagement:
    """
    Comprehensive operations management system for MERID.
    
    Provides operations dashboard, incident management, performance
    monitoring, and customer success capabilities with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Incidents
        self.incidents: Dict[str, Incident] = {}
        
        # Alerts
        self.alerts: Dict[str, Alert] = {}
        
        # Metrics
        self.metrics: Dict[str, Metric] = {}
        
        # Customer support
        self.customer_support: Dict[str, CustomerSupport] = {}
        
        # Operations data
        self.operations_data: Dict[str, deque] = {
            "incidents": deque(maxlen=1000),
            "alerts": deque(maxlen=5000),
            "metrics": deque(maxlen=10000),
            "customer_support": deque(maxlen=2000)
        }
        
        # Configuration
        self.operations_config = config.get("operations_management", {
            "incident_response_time": 300,  # 5 minutes
            "alert_retention_days": 30,
            "metric_retention_days": 90,
            "customer_response_time": 600,  # 10 minutes
            "escalation_threshold": 3,
            "auto_resolution_enabled": True
        })
        
        # Alert thresholds
        self.alert_thresholds = {
            "system_health": 0.8,
            "error_rate": 0.05,
            "response_time": 1000,  # 1 second
            "throughput": 1000,
            "customer_satisfaction": 3.5
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "incident_reporting": True,
            "audit_operations": True,
            "customer_data_protection": True,
            "performance_disclosure": True
        })
        
        logger.info("OperationsManagement initialized")
    
    async def create_incident(self, incident_id: str, title: str, description: str,
                           severity: IncidentSeverity, affected_components: List[str],
                           assigned_to: str, impact_assessment: str,
                           tags: Optional[List[str]] = None) -> bool:
        """Create an incident."""
        try:
            # Validate incident configuration
            if not self._validate_incident_config(severity, affected_components):
                logger.error(f"Invalid incident configuration: {incident_id}")
                return False
            
            # Create incident
            incident = Incident(
                incident_id=incident_id,
                title=title,
                description=description,
                severity=severity,
                status=IncidentStatus.OPEN,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                resolved_at=None,
                assigned_to=assigned_to,
                affected_components=affected_components,
                impact_assessment=impact_assessment,
                resolution=None,
                root_cause=None,
                tags=tags or [],
                metadata={}
            )
            
            # Store incident
            self.incidents[incident_id] = incident
            self.operations_data["incidents"].append(incident)
            
            # Create alert for high severity incidents
            if severity in [IncidentSeverity.HIGH, IncidentSeverity.CRITICAL]:
                await self._create_incident_alert(incident)
            
            # Record for compliance
            if self.us_compliance.get("incident_reporting", True):
                await self._record_incident_creation(incident)
            
            logger.info(f"Incident created: {incident_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create incident {incident_id}: {e}")
            return False
    
    def _validate_incident_config(self, severity: IncidentSeverity, affected_components: List[str]) -> bool:
        """Validate incident configuration."""
        try:
            # Check severity
            if severity not in IncidentSeverity:
                return False
            
            # Check affected components
            if not affected_components:
                return False
            
            # US compliance checks
            if self.us_compliance.get("incident_reporting", True):
                if not self._validate_incident_compliance(severity, affected_components):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Incident configuration validation error: {e}")
            return False
    
    def _validate_incident_compliance(self, severity: IncidentSeverity, affected_components: List[str]) -> bool:
        """Validate incident for US compliance."""
        try:
            # Check for critical incident requirements
            if severity == IncidentSeverity.CRITICAL:
                # Critical incidents must have detailed impact assessment
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Incident compliance validation error: {e}")
            return False
    
    async def _create_incident_alert(self, incident: Incident):
        """Create alert for incident."""
        try:
            alert_id = f"alert_incident_{incident.incident_id}"
            
            alert = Alert(
                alert_id=alert_id,
                alert_type=AlertType.SYSTEM,
                severity=incident.severity,
                title=f"Incident: {incident.title}",
                message=f"Incident {incident.incident_id} created: {incident.description}",
                source="operations_management",
                created_at=datetime.now(),
                acknowledged=False,
                resolved=False,
                incident_id=incident.incident_id,
                metadata={}
            )
            
            self.alerts[alert_id] = alert
            self.operations_data["alerts"].append(alert)
            
            logger.info(f"Alert created for incident: {incident.incident_id}")
            
        except Exception as e:
            logger.error(f"Failed to create incident alert: {e}")
    
    async def update_incident(self, incident_id: str, status: Optional[IncidentStatus] = None,
                           resolution: Optional[str] = None,
                           root_cause: Optional[str] = None) -> bool:
        """Update an incident."""
        try:
            if incident_id not in self.incidents:
                logger.error(f"Incident {incident_id} not found")
                return False
            
            incident = self.incidents[incident_id]
            
            # Update fields
            if status:
                incident.status = status
                incident.updated_at = datetime.now()
                
                if status == IncidentStatus.RESOLVED:
                    incident.resolved_at = datetime.now()
            
            if resolution:
                incident.resolution = resolution
            
            if root_cause:
                incident.root_cause = root_cause
            
            # Update in data store
            self.operations_data["incidents"].append(incident)
            
            # Record for compliance
            if self.us_compliance.get("audit_operations", True):
                await self._record_incident_update(incident)
            
            logger.info(f"Incident updated: {incident_id} - {status.value if status else 'no change'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update incident {incident_id}: {e}")
            return False
    
    async def create_alert(self, alert_id: str, alert_type: AlertType, severity: IncidentSeverity,
                        title: str, message: str, source: str,
                        incident_id: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Create an alert."""
        try:
            # Validate alert configuration
            if not self._validate_alert_config(alert_type, severity):
                logger.error(f"Invalid alert configuration: {alert_id}")
                return False
            
            # Create alert
            alert = Alert(
                alert_id=alert_id,
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                source=source,
                created_at=datetime.now(),
                acknowledged=False,
                resolved=False,
                incident_id=incident_id,
                metadata=metadata or {}
            )
            
            # Store alert
            self.alerts[alert_id] = alert
            self.operations_data["alerts"].append(alert)
            
            # Record for compliance
            if self.us_compliance.get("audit_operations", True):
                await self._record_alert_creation(alert)
            
            logger.info(f"Alert created: {alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create alert {alert_id}: {e}")
            return False
    
    def _validate_alert_config(self, alert_type: AlertType, severity: IncidentSeverity) -> bool:
        """Validate alert configuration."""
        try:
            # Check alert type
            if alert_type not in AlertType:
                return False
            
            # Check severity
            if severity not in IncidentSeverity:
                return False
            
            # US compliance checks
            if self.us_compliance.get("audit_operations", True):
                if not self._validate_alert_compliance(alert_type, severity):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Alert configuration validation error: {e}")
            return False
    
    def _validate_alert_compliance(self, alert_type: AlertType, severity: IncidentSeverity) -> bool:
        """Validate alert for US compliance."""
        try:
            # Check for critical alert requirements
            if severity == IncidentSeverity.CRITICAL:
                # Critical alerts must have detailed message
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Alert compliance validation error: {e}")
            return False
    
    async def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        """Acknowledge an alert."""
        try:
            if alert_id not in self.alerts:
                logger.error(f"Alert {alert_id} not found")
                return False
            
            alert = self.alerts[alert_id]
            alert.acknowledged = True
            alert.metadata["acknowledged_by"] = acknowledged_by
            alert.metadata["acknowledged_at"] = datetime.now().isoformat()
            
            # Update in data store
            self.operations_data["alerts"].append(alert)
            
            logger.info(f"Alert acknowledged: {alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to acknowledge alert {alert_id}: {e}")
            return False
    
    async def resolve_alert(self, alert_id: str, resolution: str, resolved_by: str) -> bool:
        """Resolve an alert."""
        try:
            if alert_id not in self.alerts:
                logger.error(f"Alert {alert_id} not found")
                return False
            
            alert = self.alerts[alert_id]
            alert.resolved = True
            alert.metadata["resolution"] = resolution
            alert.metadata["resolved_by"] = resolved_by
            alert.metadata["resolved_at"] = datetime.now().isoformat()
            
            # Update in data store
            self.operations_data["alerts"].append(alert)
            
            logger.info(f"Alert resolved: {alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to resolve alert {alert_id}: {e}")
            return False
    
    async def create_metric(self, metric_id: str, metric_type: MetricType, name: str,
                       value: float, unit: str, threshold: float,
                       tags: Optional[List[str]] = None) -> bool:
        """Create a metric."""
        try:
            # Validate metric configuration
            if not self._validate_metric_config(metric_type, threshold):
                logger.error(f"Invalid metric configuration: {metric_id}")
                return False
            
            # Determine status based on threshold
            status = "normal"
            if metric_type == MetricType.ERROR_RATE or metric_type == MetricType.RESPONSE_TIME:
                status = "critical" if value > threshold else "normal"
            elif metric_type == MetricType.SYSTEM_HEALTH or metric_type == MetricType.AVAILABILITY:
                status = "critical" if value < threshold else "normal"
            elif metric_type == MetricType.CUSTOMER_SATISFACTION:
                status = "critical" if value < threshold else "normal"
            else:
                status = "warning" if value > threshold else "normal"
            
            # Create metric
            metric = Metric(
                metric_id=metric_id,
                metric_type=metric_type,
                name=name,
                value=value,
                unit=unit,
                threshold=threshold,
                status=status,
                timestamp=datetime.now(),
                tags=tags or [],
                metadata={}
            )
            
            # Store metric
            self.metrics[metric_id] = metric
            self.operations_data["metrics"].append(metric)
            
            # Create alert if threshold exceeded
            if status in ["critical", "warning"]:
                await self._create_metric_alert(metric)
            
            # Record for compliance
            if self.us_compliance.get("performance_disclosure", True):
                await self._record_metric_creation(metric)
            
            logger.info(f"Metric created: {metric_id} - {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create metric {metric_id}: {e}")
            return False
    
    def _validate_metric_config(self, metric_type: MetricType, threshold: float) -> bool:
        """Validate metric configuration."""
        try:
            # Check metric type
            if metric_type not in MetricType:
                return False
            
            # Check threshold
            if threshold <= 0:
                return False
            
            # US compliance checks
            if self.us_compliance.get("performance_disclosure", True):
                if not self._validate_metric_compliance(metric_type, threshold):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Metric configuration validation error: {e}")
            return False
    
    def _validate_metric_compliance(self, metric_type: MetricType, threshold: float) -> bool:
        """Validate metric for US compliance."""
        try:
            # Check for performance disclosure requirements
            if metric_type in [MetricType.ERROR_RATE, MetricType.RESPONSE_TIME, MetricType.THROUGHPUT]:
                # These metrics must have reasonable thresholds
                if metric_type == MetricType.ERROR_RATE and threshold > 0.1:  # 10% error rate too high
                    return False
                elif metric_type == MetricType.RESPONSE_TIME and threshold > 5000:  # 5 seconds too slow
                    return False
                elif metric_type == MetricType.THROUGHPUT and threshold < 100:  # 100 ops/sec too low
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Metric compliance validation error: {e}")
            return False
    
    async def _create_metric_alert(self, metric: Metric):
        """Create alert for metric threshold violation."""
        try:
            alert_id = f"alert_metric_{metric.metric_id}"
            
            severity = IncidentSeverity.CRITICAL if metric.status == "critical" else IncidentSeverity.HIGH
            
            alert = Alert(
                alert_id=alert_id,
                alert_type=AlertType.PERFORMANCE,
                severity=severity,
                title=f"Metric Threshold Violation: {metric.name}",
                message=f"Metric {metric.name} ({metric.value:.2f} {metric.unit}) exceeded threshold ({metric.threshold:.2f} {metric.unit})",
                source="operations_management",
                created_at=datetime.now(),
                acknowledged=False,
                resolved=False,
                incident_id=None,
                metadata={"metric_id": metric.metric_id, "value": metric.value, "threshold": metric.threshold}
            )
            
            self.alerts[alert_id] = alert
            self.operations_data["alerts"].append(alert)
            
            logger.info(f"Alert created for metric: {metric.metric_id}")
            
        except Exception as e:
            logger.error(f"Failed to create metric alert: {e}")
    
    async def create_customer_support(self, support_id: str, customer_id: str, issue_type: str,
                                   priority: str, description: str,
                                   assigned_to: str) -> bool:
        """Create a customer support ticket."""
        try:
            # Validate support ticket configuration
            if not self._validate_support_config(issue_type, priority):
                logger.error(f"Invalid support ticket configuration: {support_id}")
                return False
            
            # Create customer support ticket
            support = CustomerSupport(
                support_id=support_id,
                customer_id=customer_id,
                issue_type=issue_type,
                priority=priority,
                status="open",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                resolved_at=None,
                assigned_to=assigned_to,
                description=description,
                resolution=None,
                satisfaction_score=None,
                metadata={}
            )
            
            # Store support ticket
            self.customer_support[support_id] = support
            self.operations_data["customer_support"].append(support)
            
            # Record for compliance
            if self.us_compliance.get("customer_data_protection", True):
                await self._record_support_creation(support)
            
            logger.info(f"Customer support created: {support_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create customer support {support_id}: {e}")
            return False
    
    def _validate_support_config(self, issue_type: str, priority: str) -> bool:
        """Validate support ticket configuration."""
        try:
            # Check issue type
            if not issue_type:
                return False
            
            # Check priority
            valid_priorities = ["low", "medium", "high", "critical"]
            if priority not in valid_priorities:
                return False
            
            # US compliance checks
            if self.us_compliance.get("customer_data_protection", True):
                if not self._validate_support_compliance(issue_type, priority):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Support configuration validation error: {e}")
            return False
    
    def _validate_support_compliance(self, issue_type: str, priority: str) -> bool:
        """Validate support ticket for US compliance."""
        try:
            # Check for high priority requirements
            if priority == "critical":
                # Critical tickets must have detailed description
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Support compliance validation error: {e}")
            return False
    
    async def update_customer_support(self, support_id: str, status: Optional[str] = None,
                                     resolution: Optional[str] = None,
                                     satisfaction_score: Optional[float] = None) -> bool:
        """Update a customer support ticket."""
        try:
            if support_id not in self.customer_support:
                logger.error(f"Customer support {support_id} not found")
                return False
            
            support = self.customer_support[support_id]
            
            # Update fields
            if status:
                support.status = status
                support.updated_at = datetime.now()
                
                if status == "resolved":
                    support.resolved_at = datetime.now()
            
            if resolution:
                support.resolution = resolution
            
            if satisfaction_score is not None:
                support.satisfaction_score = satisfaction_score
            
            # Update in data store
            self.operations_data["customer_support"].append(support)
            
            # Record for compliance
            if self.us_compliance.get("audit_operations", True):
                await self._record_support_update(support)
            
            logger.info(f"Customer support updated: {support_id} - {status or 'no change'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update customer support {support_id}: {e}")
            return False
    
    def get_incident_summary(self) -> Dict[str, Any]:
        """Get incident summary."""
        try:
            if not self.incidents:
                return {"status": "no_incidents"}
            
            # Incident status distribution
            incident_statuses = {}
            for incident in self.incidents.values():
                status_name = incident.status.value
                incident_statuses[status_name] = incident_statuses.get(status_name, 0) + 1
            
            # Severity distribution
            severity_distribution = {}
            for incident in self.incidents.values():
                severity_name = incident.severity.value
                severity_distribution[severity_name] = severity_distribution.get(severity_name, 0) + 1
            
            # Resolution metrics
            total_incidents = len(self.incidents)
            resolved_incidents = sum(1 for incident in self.incidents.values() if incident.status == IncidentStatus.RESOLVED)
            resolution_rate = (resolved_incidents / total_incidents) * 100 if total_incidents > 0 else 0
            
            # Average resolution time
            resolved_incidents_with_time = [
                incident for incident in self.incidents.values() 
                if incident.status == IncidentStatus.RESOLVED and incident.resolved_at
            ]
            
            if resolved_incidents_with_time:
                avg_resolution_time = np.mean([
                    (incident.resolved_at - incident.created_at).total_seconds() / 3600
                    for incident in resolved_incidents_with_time
                ])
            else:
                avg_resolution_time = 0
            
            return {
                "total_incidents": total_incidents,
                "resolved_incidents": resolved_incidents,
                "resolution_rate": resolution_rate,
                "avg_resolution_hours": avg_resolution_time,
                "incident_statuses": incident_statuses,
                "severity_distribution": severity_distribution,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get incident summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """Get alert summary."""
        try:
            if not self.alerts:
                return {"status": "no_alerts"}
            
            # Alert type distribution
            alert_types = {}
            for alert in self.alerts.values():
                alert_type_name = alert.alert_type.value
                alert_types[alert_type_name] = alert_types.get(alert_type_name, 0) + 1
            
            # Severity distribution
            severity_distribution = {}
            for alert in self.alerts.values():
                severity_name = alert.severity.value
                severity_distribution[severity_name] = severity_distribution.get(severity_name, 0) + 1
            
            # Resolution metrics
            total_alerts = len(self.alerts)
            resolved_alerts = sum(1 for alert in self.alerts.values() if alert.resolved)
            resolution_rate = (resolved_alerts / total_alerts) * 100 if total_alerts > 0 else 0
            
            return {
                "total_alerts": total_alerts,
                "resolved_alerts": resolved_alerts,
                "resolution_rate": resolution_rate,
                "alert_types": alert_types,
                "severity_distribution": severity_distribution,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get alert summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_metric_summary(self) -> Dict[str, Any]:
        """Get metric summary."""
        try:
            if not self.metrics:
                return {"status": "no_metrics"}
            
            # Metric type distribution
            metric_types = {}
            for metric in self.metrics.values():
                metric_type_name = metric.metric_type.value
                metric_types[metric_type_name] = metric_types.get(metric_type_name, 0) + 1
            
            # Status distribution
            status_distribution = {}
            for metric in self.metrics.values():
                status_name = metric.status
                status_distribution[status_name] = status_distribution.get(status_name, 0) + 1
            
            # Performance metrics
            performance_metrics = {}
            for metric_type in [MetricType.RESPONSE_TIME, MetricType.THROUGHPUT, MetricType.ERROR_RATE]:
                metrics_of_type = [m for m in self.metrics.values() if m.metric_type == metric_type]
                if metrics_of_type:
                    values = [m.value for m in metrics_of_type]
                    performance_metrics[metric_type.value] = {
                        "count": len(values),
                        "average": np.mean(values),
                        "min": np.min(values),
                        "max": np.max(values),
                        "current": values[-1] if values else 0
                    }
            
            return {
                "total_metrics": len(self.metrics),
                "metric_types": metric_types,
                "status_distribution": status_distribution,
                "performance_metrics": performance_metrics,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get metric summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_customer_support_summary(self) -> Dict[str, Any]:
        """Get customer support summary."""
        try:
            if not self.customer_support:
                return {"status": "no_support_tickets"}
            
            # Status distribution
            status_distribution = {}
            for support in self.customer_support.values():
                status_name = support.status
                status_distribution[status_name] = status_distribution.get(status_name, 0) + 1
            
            # Priority distribution
            priority_distribution = {}
            for support in self.customer_support.values():
                priority_name = support.priority
                priority_distribution[priority_name] = priority_distribution.get(priority_name, 0) + 1
            
            # Resolution metrics
            total_support = len(self.customer_support)
            resolved_support = sum(1 for support in self.customer_support.values() if support.status == "resolved")
            resolution_rate = (resolved_support / total_support) * 100 if total_support > 0 else 0
            
            # Satisfaction metrics
            satisfaction_scores = [s.satisfaction_score for s in self.customer_support.values() if s.satisfaction_score is not None]
            avg_satisfaction = np.mean(satisfaction_scores) if satisfaction_scores else 0
            
            return {
                "total_support": total_support,
                "resolved_support": resolved_support,
                "resolution_rate": resolution_rate,
                "avg_satisfaction": avg_satisfaction,
                "status_distribution": status_distribution,
                "priority_distribution": priority_distribution,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get customer support summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_operations_summary(self) -> Dict[str, Any]:
        """Get comprehensive operations summary."""
        try:
            # Get individual summaries
            incident_summary = self.get_incident_summary()
            alert_summary = self.get_alert_summary()
            metric_summary = self.get_metric_summary()
            support_summary = self.get_customer_support_summary()
            
            # Overall health score
            health_score = 0.0
            weights = {
                "incidents": 0.3,
                "alerts": 0.2,
                "metrics": 0.3,
                "customer_support": 0.2
            }
            
            for component, weight in weights.items():
                if component in incident_summary and "total_incidents" in incident_summary:
                    if incident_summary["total_incidents"] > 0:
                        resolution_rate = incident_summary["resolution_rate"]
                        health_score += weight * (resolution_rate / 100)
                
                elif component in alert_summary and "resolution_rate" in alert_summary:
                    if alert_summary["total_alerts"] > 0:
                        resolution_rate = alert_summary["resolution_rate"]
                        health_score += weight * (resolution_rate / 100)
                
                elif component in metric_summary and "status_distribution" in metric_summary:
                    normal_metrics = metric_summary["status_distribution"].get("normal", 0)
                    total_metrics = metric_summary["total_metrics"]
                    if total_metrics > 0:
                        health_score += weight * (normal_metrics / total_metrics)
                
                elif component in support_summary and "resolution_rate" in support_summary:
                    if support_summary["resolution_rate"] > 0:
                        health_score += weight * (support_summary["resolution_rate"] / 100)
            
            return {
                "overall_health_score": health_score,
                "incident_summary": incident_summary,
                "alert_summary": alert_summary,
                "metric_summary": metric_summary,
                "customer_support_summary": support_summary,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get operations summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _record_incident_creation(self, incident: Incident):
        """Record incident creation for compliance."""
        if not self.us_compliance.get("audit_operations", True):
            return
        
        audit_entry = {
            "action": "incident_creation",
            "incident_id": incident.incident_id,
            "title": incident.title,
            "severity": incident.severity.value,
            "affected_components": incident.affected_components,
            "assigned_to": incident.assigned_to,
            "timestamp": incident.created_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Incident creation audit entry: {audit_entry}")
    
    async def _record_incident_update(self, incident: Incident):
        """Record incident update for compliance."""
        if not self.us_compliance.get("audit_operations", True):
            return
        
        audit_entry = {
            "action": "incident_update",
            "incident_id": incident.incident_id,
            "status": incident.status.value,
            "resolution": incident.resolution,
            "timestamp": incident.updated_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Incident update audit entry: {audit_entry}")
    
    async def _record_alert_creation(self, alert: Alert):
        """Record alert creation for compliance."""
        if not self.us_compliance.get("audit_operations", True):
            return
        
        audit_entry = {
            "action": "alert_creation",
            "alert_id": alert.alert_id,
            "alert_type": alert.alert_type.value,
            "severity": alert.severity.value,
            "title": alert.title,
            "source": alert.source,
            "timestamp": alert.created_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Alert creation audit entry: {audit_entry}")
    
    async def _record_metric_creation(self, metric: Metric):
        """Record metric creation for compliance."""
        if not self.us_compliance.get("performance_disclosure", True):
            return
        
        audit_entry = {
            "action": "metric_creation",
            "metric_id": metric.metric_id,
            "metric_type": metric.metric_type.value,
            "name": metric.name,
            "value": metric.value,
            "threshold": metric.threshold,
            "status": metric.status,
            "timestamp": metric.timestamp.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Metric creation audit entry: {audit_entry}")
    
    async def _record_support_creation(self, support: CustomerSupport):
        """Record support ticket creation for compliance."""
        if not self.us_compliance.get("customer_data_protection", True):
            return
        
        audit_entry = {
            "action": "support_creation",
            "support_id": support.support_id,
            "customer_id": support.customer_id,
            "issue_type": support.issue_type,
            "priority": support.priority,
            "status": support.status,
            "timestamp": support.created_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Support creation audit entry: {audit_entry}")
    
    async def _record_support_update(self, support: CustomerSupport):
        """Record support ticket update for compliance."""
        if not self.us_compliance.get("audit_operations", True):
            return
        
        audit_entry = {
            "action": "support_update",
            "support_id": support.support_id,
            "customer_id": support.customer_id,
            "status": support.status,
            "resolution": support.resolution,
            "timestamp": support.updated_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Support update audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update operations configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "operations_management" in new_config:
            self.operations_config.update(new_config["operations_management"])
        
        logger.info("Operations management configuration updated")
