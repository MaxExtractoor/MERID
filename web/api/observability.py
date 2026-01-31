"""
Observability API Endpoints
REST API for accessing logs, metrics, alerts, and system health
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging

from core.observability_manager import (
    get_observability_manager, 
    LogLevel, 
    AlertSeverity, 
    MetricType
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/observability", tags=["observability"])

# Pydantic models for API requests/responses
class MetricQuery(BaseModel):
    name: Optional[str] = None
    since: Optional[datetime] = None
    metric_type: Optional[str] = None

class LogQuery(BaseModel):
    level: Optional[str] = None
    component: Optional[str] = None
    since: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)

class AlertQuery(BaseModel):
    severity: Optional[str] = None
    resolved: Optional[bool] = None
    since: Optional[datetime] = None

class AlertResolution(BaseModel):
    alert_name: str
    resolved_by: Optional[str] = None

class MetricCreation(BaseModel):
    name: str
    value: float
    metric_type: str
    labels: Dict[str, str] = {}
    unit: str = ""

@router.get("/health")
async def get_system_health():
    """Get system health overview"""
    try:
        obs_manager = get_observability_manager()
        health = obs_manager.get_system_health()
        
        return {
            "status": "success",
            "data": health
        }
    except Exception as e:
        logger.error(f"Failed to get system health: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system health")

@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None, description="Log level filter"),
    component: Optional[str] = Query(None, description="Component filter"),
    since: Optional[datetime] = Query(None, description="Since timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs")
):
    """Get log entries with filtering"""
    try:
        obs_manager = get_observability_manager()
        
        # Convert level string to enum
        log_level = None
        if level:
            try:
                log_level = LogLevel[level.upper()]
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Invalid log level: {level}")
        
        logs = obs_manager.get_logs(
            level=log_level,
            component=component,
            since=since,
            limit=limit
        )
        
        # Convert to serializable format
        log_data = []
        for log in logs:
            log_entry = {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level.name,
                "component": log.component,
                "message": log.message,
                "metadata": log.metadata,
                "trace_id": log.trace_id,
                "span_id": log.span_id,
                "user_id": log.user_id,
                "session_id": log.session_id
            }
            log_data.append(log_entry)
        
        return {
            "status": "success",
            "data": {
                "logs": log_data,
                "total": len(log_data),
                "filters": {
                    "level": level,
                    "component": component,
                    "since": since.isoformat() if since else None,
                    "limit": limit
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get logs")

@router.get("/metrics")
async def get_metrics(
    name: Optional[str] = Query(None, description="Metric name filter"),
    since: Optional[datetime] = Query(None, description="Since timestamp"),
    metric_type: Optional[str] = Query(None, description="Metric type filter")
):
    """Get metrics with filtering"""
    try:
        obs_manager = get_observability_manager()
        
        # Convert metric type string to enum
        type_filter = None
        if metric_type:
            try:
                type_filter = MetricType(metric_type.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid metric type: {metric_type}")
        
        metrics = obs_manager.get_metrics(name=name, since=since)
        
        # Filter by type if specified
        if type_filter:
            metrics = [m for m in metrics if m.metric_type == type_filter]
        
        # Convert to serializable format
        metric_data = []
        for metric in metrics:
            metric_entry = {
                "name": metric.name,
                "value": metric.value,
                "metric_type": metric.metric_type.value,
                "timestamp": metric.timestamp.isoformat(),
                "labels": metric.labels,
                "unit": metric.unit
            }
            metric_data.append(metric_entry)
        
        return {
            "status": "success",
            "data": {
                "metrics": metric_data,
                "total": len(metric_data),
                "filters": {
                    "name": name,
                    "since": since.isoformat() if since else None,
                    "metric_type": metric_type
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics")

@router.get("/metrics/summary")
async def get_metrics_summary():
    """Get metrics summary statistics"""
    try:
        obs_manager = get_observability_manager()
        
        # Get recent metrics (last hour)
        since = datetime.now() - timedelta(hours=1)
        recent_metrics = obs_manager.get_metrics(since=since)
        
        # Group by name and calculate statistics
        summary = {}
        for metric in recent_metrics:
            if metric.name not in summary:
                summary[metric.name] = {
                    "metric_type": metric.metric_type.value,
                    "count": 0,
                    "latest_value": 0,
                    "min_value": float('inf'),
                    "max_value": float('-inf'),
                    "avg_value": 0,
                    "unit": metric.unit
                }
            
            stat = summary[metric.name]
            stat["count"] += 1
            stat["latest_value"] = metric.value
            stat["min_value"] = min(stat["min_value"], metric.value)
            stat["max_value"] = max(stat["max_value"], metric.value)
        
        # Calculate averages
        for name, stat in summary.items():
            if stat["count"] > 0:
                values = [m.value for m in recent_metrics if m.name == name]
                stat["avg_value"] = sum(values) / len(values)
            else:
                stat["min_value"] = 0
                stat["max_value"] = 0
        
        return {
            "status": "success",
            "data": {
                "summary": summary,
                "total_metrics": len(recent_metrics),
                "time_range": {
                    "since": since.isoformat(),
                    "until": datetime.now().isoformat()
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics summary")

@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = Query(None, description="Alert severity filter"),
    resolved: Optional[bool] = Query(None, description="Resolved status filter"),
    since: Optional[datetime] = Query(None, description="Since timestamp")
):
    """Get alerts with filtering"""
    try:
        obs_manager = get_observability_manager()
        
        # Convert severity string to enum
        severity_filter = None
        if severity:
            try:
                severity_filter = AlertSeverity(severity.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid alert severity: {severity}")
        
        alerts = obs_manager.get_alerts(
            severity=severity_filter,
            resolved=resolved,
            since=since
        )
        
        # Convert to serializable format
        alert_data = []
        for alert in alerts:
            alert_entry = {
                "name": alert.name,
                "severity": alert.severity.value,
                "message": alert.message,
                "timestamp": alert.timestamp.isoformat(),
                "metadata": alert.metadata,
                "resolved": alert.resolved,
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None
            }
            alert_data.append(alert_entry)
        
        return {
            "status": "success",
            "data": {
                "alerts": alert_data,
                "total": len(alert_data),
                "filters": {
                    "severity": severity,
                    "resolved": resolved,
                    "since": since.isoformat() if since else None
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alerts")

@router.post("/alerts/{alert_name}/resolve")
async def resolve_alert(alert_name: str, request: AlertResolution):
    """Resolve an alert"""
    try:
        obs_manager = get_observability_manager()
        
        obs_manager.resolve_alert(alert_name, request.resolved_by)
        
        return {
            "status": "success",
            "message": f"Alert '{alert_name}' resolved successfully",
            "data": {
                "alert_name": alert_name,
                "resolved_by": request.resolved_by,
                "resolved_at": datetime.now().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Failed to resolve alert: {e}")
        raise HTTPException(status_code=500, detail="Failed to resolve alert")

@router.post("/metrics")
async def create_metric(request: MetricCreation):
    """Create a new metric"""
    try:
        obs_manager = get_observability_manager()
        
        # Convert metric type string to enum
        try:
            metric_type = MetricType(request.metric_type.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid metric type: {request.metric_type}")
        
        # Create metric based on type
        if metric_type == MetricType.COUNTER:
            obs_manager.increment_counter(request.name, request.value, request.labels)
        elif metric_type == MetricType.GAUGE:
            obs_manager.set_gauge(request.name, request.value, request.labels)
        elif metric_type == MetricType.HISTOGRAM:
            obs_manager.record_histogram(request.name, request.value, request.labels)
        elif metric_type == MetricType.TIMER:
            obs_manager.record_timer(request.name, request.value, request.labels)
        
        return {
            "status": "success",
            "message": f"Metric '{request.name}' created successfully",
            "data": {
                "name": request.name,
                "value": request.value,
                "metric_type": request.metric_type,
                "labels": request.labels,
                "unit": request.unit
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create metric: {e}")
        raise HTTPException(status_code=500, detail="Failed to create metric")

@router.get("/counters")
async def get_counters():
    """Get all counter metrics"""
    try:
        obs_manager = get_observability_manager()
        
        return {
            "status": "success",
            "data": {
                "counters": dict(obs_manager.counters)
            }
        }
    except Exception as e:
        logger.error(f"Failed to get counters: {e}")
        raise HTTPException(status_code=500, detail="Failed to get counters")

@router.get("/gauges")
async def get_gauges():
    """Get all gauge metrics"""
    try:
        obs_manager = get_observability_manager()
        
        return {
            "status": "success",
            "data": {
                "gauges": dict(obs_manager.gauges)
            }
        }
    except Exception as e:
        logger.error(f"Failed to get gauges: {e}")
        raise HTTPException(status_code=500, detail="Failed to get gauges")

@router.get("/statistics")
async def get_statistics():
    """Get comprehensive observability statistics"""
    try:
        obs_manager = get_observability_manager()
        
        now = datetime.now()
        last_hour = now - timedelta(hours=1)
        last_24h = now - timedelta(hours=24)
        
        # Log statistics
        recent_logs = obs_manager.get_logs(since=last_hour)
        log_stats = {}
        for level in LogLevel:
            log_stats[level.name] = len([l for l in recent_logs if l.level == level])
        
        # Alert statistics
        recent_alerts = obs_manager.get_alerts(since=last_24h)
        alert_stats = {}
        for severity in AlertSeverity:
            alert_stats[severity.value] = len([a for a in recent_alerts if a.severity == severity])
        
        # Component statistics
        component_stats = {}
        for log in recent_logs:
            component_stats[log.component] = component_stats.get(log.component, 0) + 1
        
        # Metric statistics
        all_metrics = obs_manager.get_metrics(since=last_hour)
        metric_stats = {}
        for metric_type in MetricType:
            metric_stats[metric_type.value] = len([m for m in all_metrics if m.metric_type == metric_type])
        
        return {
            "status": "success",
            "data": {
                "timestamp": now.isoformat(),
                "time_ranges": {
                    "last_hour": last_hour.isoformat(),
                    "last_24h": last_24h.isoformat()
                },
                "logs": {
                    "total": len(recent_logs),
                    "by_level": log_stats,
                    "by_component": component_stats
                },
                "alerts": {
                    "total": len(recent_alerts),
                    "by_severity": alert_stats,
                    "unresolved": len([a for a in recent_alerts if not a.resolved])
                },
                "metrics": {
                    "total": len(all_metrics),
                    "by_type": metric_stats,
                    "unique_names": len(set(m.name for m in all_metrics))
                },
                "system": {
                    "total_log_entries": len(obs_manager.log_entries),
                    "total_alerts": len(obs_manager.alerts),
                    "active_alerts": len([a for a in obs_manager.alerts if not a.resolved]),
                    "total_metrics": sum(len(metrics) for metrics in obs_manager.metrics.values())
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

@router.get("/dashboard")
async def get_dashboard_data():
    """Get dashboard data for observability UI"""
    try:
        obs_manager = get_observability_manager()
        
        # Get system health
        health = obs_manager.get_system_health()
        
        # Get recent logs
        recent_logs = obs_manager.get_logs(limit=50)
        log_data = []
        for log in recent_logs:
            log_data.append({
                "timestamp": log.timestamp.isoformat(),
                "level": log.level.name,
                "component": log.component,
                "message": log.message,
                "metadata": log.metadata
            })
        
        # Get recent alerts
        recent_alerts = obs_manager.get_alerts(resolved=False, limit=20)
        alert_data = []
        for alert in recent_alerts:
            alert_data.append({
                "name": alert.name,
                "severity": alert.severity.value,
                "message": alert.message,
                "timestamp": alert.timestamp.isoformat(),
                "metadata": alert.metadata
            })
        
        # Get top metrics
        top_metrics = []
        for name, values in obs_manager.counters.items():
            top_metrics.append({
                "name": name,
                "value": values,
                "type": "counter"
            })
        for name, values in obs_manager.gauges.items():
            top_metrics.append({
                "name": name,
                "value": values,
                "type": "gauge"
            })
        
        # Sort by value and take top 10
        top_metrics.sort(key=lambda x: x["value"], reverse=True)
        top_metrics = top_metrics[:10]
        
        return {
            "status": "success",
            "data": {
                "health": health,
                "recent_logs": log_data,
                "recent_alerts": alert_data,
                "top_metrics": top_metrics,
                "summary": {
                    "total_logs": len(recent_logs),
                    "total_alerts": len(recent_alerts),
                    "error_rate": health.get("error_rate", 0),
                    "system_status": health.get("status", "unknown")
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard data")
