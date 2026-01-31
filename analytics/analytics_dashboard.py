"""
Advanced Analytics Dashboard for MERID Advanced Analytics

Provides comprehensive real-time analytics dashboard with
visualization and US-compliant configuration.

Features:
- Real-time performance metrics
- Interactive visualizations
- Custom dashboard widgets
- Alert management
- US-compliant reporting
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("analytics.analytics_dashboard")

class WidgetType(Enum):
    """Dashboard widget type enumeration."""
    PERFORMANCE_CHART = "performance_chart"
    METRIC_CARD = "metric_card"
    TABLE = "table"
    HEATMAP = "heatmap"
    GAUGE = "gauge"
    ALERT_PANEL = "alert_panel"
    CORRELATION_MATRIX = "correlation_matrix"
    ATTRIBUTION_CHART = "attribution_chart"

class AlertSeverity(Enum):
    """Alert severity enumeration."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class DashboardWidget:
    """Dashboard widget definition."""
    widget_id: str
    widget_type: WidgetType
    title: str
    position: Dict[str, int]  # x, y, width, height
    data_source: str
    config: Dict[str, Any]
    last_updated: float
    data: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DashboardAlert:
    """Dashboard alert definition."""
    alert_id: str
    title: str
    message: str
    severity: AlertSeverity
    timestamp: float
    source: str
    acknowledged: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DashboardMetric:
    """Dashboard metric definition."""
    metric_id: str
    name: str
    value: float
    unit: str
    trend: str  # up, down, stable
    trend_percentage: float
    threshold: Optional[float]
    status: str  # normal, warning, critical
    last_updated: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class AnalyticsDashboard:
    """
    Comprehensive analytics dashboard system for MERID.
    
    Provides real-time analytics visualization with customizable
    widgets and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Dashboard widgets
        self.widgets: Dict[str, DashboardWidget] = {}
        
        # Dashboard metrics
        self.metrics: Dict[str, DashboardMetric] = {}
        
        # Dashboard alerts
        self.alerts: deque = deque(maxlen=1000)
        self.active_alerts: Dict[str, DashboardAlert] = {}
        
        # Data sources
        self.data_sources: Dict[str, Any] = {}
        
        # Dashboard configuration
        self.dashboard_config = config.get("dashboard", {
            "refresh_interval": 30,  # seconds
            "max_widgets": 50,
            "alert_retention": 86400 * 7,  # 7 days
            "auto_refresh": True
        })
        
        # Widget templates
        self.widget_templates = {
            WidgetType.PERFORMANCE_CHART: {
                "chart_type": "line",
                "time_range": "1M",
                "show_benchmark": True,
                "show_volume": False
            },
            WidgetType.METRIC_CARD: {
                "show_trend": True,
                "show_threshold": True,
                "format": "number",
                "precision": 2
            },
            WidgetType.TABLE: {
                "sortable": True,
                "filterable": True,
                "paginated": True,
                "page_size": 10
            },
            WidgetType.HEATMAP: {
                "color_scheme": "viridis",
                "show_values": True,
                "interpolation": "nearest"
            },
            WidgetType.GAUGE: {
                "min_value": 0,
                "max_value": 100,
                "thresholds": [33, 66, 100],
                "colors": ["green", "yellow", "red"]
            },
            WidgetType.ALERT_PANEL: {
                "max_alerts": 10,
                "group_by_severity": True,
                "auto_refresh": True
            },
            WidgetType.CORRELATION_MATRIX: {
                "color_scheme": "RdBu",
                "show_values": True,
                "precision": 3
            },
            WidgetType.ATTRIBUTION_CHART: {
                "chart_type": "waterfall",
                "show_effects": True,
                "cumulative": True
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "data_privacy": True,
            "access_logging": True,
            "report_disclosure": True,
            "audit_dashboard": True
        })
        
        # Background refresh task
        self.refresh_task: Optional[asyncio.Task] = None
        
        logger.info("AnalyticsDashboard initialized")
    
    async def create_widget(self, widget_id: str, widget_type: WidgetType, 
                          title: str, position: Dict[str, int], 
                          data_source: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """Create a dashboard widget."""
        try:
            # Validate widget configuration
            if not self._validate_widget_config(widget_type, position, data_source):
                logger.error(f"Invalid widget configuration: {widget_id}")
                return False
            
            # Merge with template
            widget_config = self.widget_templates.get(widget_type, {}).copy()
            if config:
                widget_config.update(config)
            
            # Create widget
            widget = DashboardWidget(
                widget_id=widget_id,
                widget_type=widget_type,
                title=title,
                position=position,
                data_source=data_source,
                config=widget_config,
                last_updated=time.time()
            )
            
            # Store widget
            self.widgets[widget_id] = widget
            
            # Record for compliance
            if self.us_compliance.get("audit_dashboard", True):
                await self._record_widget_creation(widget)
            
            logger.info(f"Widget created: {widget_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create widget {widget_id}: {e}")
            return False
    
    def _validate_widget_config(self, widget_type: WidgetType, 
                             position: Dict[str, int], data_source: str) -> bool:
        """Validate widget configuration."""
        try:
            # Check position
            required_position_keys = ["x", "y", "width", "height"]
            for key in required_position_keys:
                if key not in position or position[key] < 0:
                    return False
            
            # Check data source
            if not data_source or data_source not in self.data_sources:
                return False
            
            # Check widget count limit
            if len(self.widgets) >= self.dashboard_config["max_widgets"]:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Widget configuration validation error: {e}")
            return False
    
    async def update_widget_data(self, widget_id: str, data: Any) -> bool:
        """Update widget data."""
        try:
            if widget_id not in self.widgets:
                logger.error(f"Widget {widget_id} not found")
                return False
            
            widget = self.widgets[widget_id]
            widget.data = data
            widget.last_updated = time.time()
            
            logger.debug(f"Widget data updated: {widget_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update widget data {widget_id}: {e}")
            return False
    
    async def create_metric(self, metric_id: str, name: str, value: float, 
                          unit: str, threshold: Optional[float] = None) -> bool:
        """Create a dashboard metric."""
        try:
            # Calculate trend (simplified)
            previous_value = self.metrics.get(metric_id, DashboardMetric(metric_id, name, value, unit, "stable", 0.0, threshold, "normal", time.time())).value
            trend = "up" if value > previous_value else "down" if value < previous_value else "stable"
            trend_percentage = ((value - previous_value) / previous_value * 100) if previous_value != 0 else 0.0
            
            # Determine status
            status = "normal"
            if threshold:
                if abs(value) > threshold * 1.5:
                    status = "critical"
                elif abs(value) > threshold:
                    status = "warning"
            
            metric = DashboardMetric(
                metric_id=metric_id,
                name=name,
                value=value,
                unit=unit,
                trend=trend,
                trend_percentage=trend_percentage,
                threshold=threshold,
                status=status,
                last_updated=time.time()
            )
            
            self.metrics[metric_id] = metric
            
            # Check for alerts
            if status in ["warning", "critical"]:
                await self._create_metric_alert(metric)
            
            logger.debug(f"Metric created: {metric_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create metric {metric_id}: {e}")
            return False
    
    async def _create_metric_alert(self, metric: DashboardMetric):
        """Create alert for metric threshold breach."""
        try:
            alert_id = f"metric_alert_{metric.metric_id}_{int(time.time())}"
            
            severity = AlertSeverity.WARNING if metric.status == "warning" else AlertSeverity.CRITICAL
            
            alert = DashboardAlert(
                alert_id=alert_id,
                title=f"Metric Alert: {metric.name}",
                message=f"Metric {metric.name} has {metric.status} value: {metric.value} {metric.unit}",
                severity=severity,
                timestamp=time.time(),
                source="metric_monitor"
            )
            
            self.alerts.append(alert)
            self.active_alerts[alert_id] = alert
            
            logger.warning(f"Metric alert created: {metric.name}")
            
        except Exception as e:
            logger.error(f"Failed to create metric alert: {e}")
    
    async def create_alert(self, alert_id: str, title: str, message: str, 
                         severity: AlertSeverity, source: str) -> bool:
        """Create a dashboard alert."""
        try:
            alert = DashboardAlert(
                alert_id=alert_id,
                title=title,
                message=message,
                severity=severity,
                timestamp=time.time(),
                source=source
            )
            
            self.alerts.append(alert)
            self.active_alerts[alert_id] = alert
            
            # Record for compliance
            if self.us_compliance.get("audit_dashboard", True):
                await self._record_alert_creation(alert)
            
            logger.info(f"Alert created: {alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create alert {alert_id}: {e}")
            return False
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        try:
            if alert_id in self.active_alerts:
                self.active_alerts[alert_id].acknowledged = True
                logger.info(f"Alert acknowledged: {alert_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to acknowledge alert {alert_id}: {e}")
            return False
    
    def dismiss_alert(self, alert_id: str) -> bool:
        """Dismiss an alert."""
        try:
            if alert_id in self.active_alerts:
                del self.active_alerts[alert_id]
                logger.info(f"Alert dismissed: {alert_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to dismiss alert {alert_id}: {e}")
            return False
    
    async def register_data_source(self, source_id: str, source_config: Dict[str, Any]) -> bool:
        """Register a data source."""
        try:
            self.data_sources[source_id] = source_config
            logger.info(f"Data source registered: {source_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register data source {source_id}: {e}")
            return False
    
    async def refresh_dashboard(self) -> bool:
        """Refresh all dashboard widgets."""
        try:
            refresh_count = 0
            
            for widget_id, widget in self.widgets.items():
                # Check if widget needs refresh
                if self._should_refresh_widget(widget):
                    # Fetch data from source
                    data = await self._fetch_widget_data(widget)
                    if data is not None:
                        await self.update_widget_data(widget_id, data)
                        refresh_count += 1
            
            logger.info(f"Dashboard refreshed: {refresh_count} widgets updated")
            return True
            
        except Exception as e:
            logger.error(f"Failed to refresh dashboard: {e}")
            return False
    
    def _should_refresh_widget(self, widget: DashboardWidget) -> bool:
        """Check if widget should be refreshed."""
        try:
            refresh_interval = self.dashboard_config["refresh_interval"]
            time_since_update = time.time() - widget.last_updated
            
            return time_since_update >= refresh_interval
            
        except Exception as e:
            logger.error(f"Widget refresh check error: {e}")
            return False
    
    async def _fetch_widget_data(self, widget: DashboardWidget) -> Any:
        """Fetch data for a widget."""
        try:
            source_id = widget.data_source
            if source_id not in self.data_sources:
                return None
            
            source_config = self.data_sources[source_id]
            
            # Mock data fetching based on widget type
            if widget.widget_type == WidgetType.PERFORMANCE_CHART:
                return await self._fetch_performance_data(source_config)
            elif widget.widget_type == WidgetType.METRIC_CARD:
                return await self._fetch_metric_data(source_config)
            elif widget.widget_type == WidgetType.TABLE:
                return await self._fetch_table_data(source_config)
            elif widget.widget_type == WidgetType.HEATMAP:
                return await self._fetch_heatmap_data(source_config)
            elif widget.widget_type == WidgetType.GAUGE:
                return await self._fetch_gauge_data(source_config)
            elif widget.widget_type == WidgetType.ALERT_PANEL:
                return await self._fetch_alert_data(source_config)
            elif widget.widget_type == WidgetType.CORRELATION_MATRIX:
                return await self._fetch_correlation_data(source_config)
            elif widget.widget_type == WidgetType.ATTRIBUTION_CHART:
                return await self._fetch_attribution_data(source_config)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to fetch widget data: {e}")
            return None
    
    async def _fetch_performance_data(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch performance chart data."""
        try:
            # Mock performance data
            dates = pd.date_range(start='2023-01-01', periods=30, freq='D')
            portfolio_values = [1000000 * (1 + np.random.normal(0.001, 0.02)) for _ in range(30)]
            benchmark_values = [1000000 * (1 + np.random.normal(0.0005, 0.015)) for _ in range(30)]
            
            return {
                "dates": dates.tolist(),
                "portfolio_values": portfolio_values,
                "benchmark_values": benchmark_values,
                "portfolio_return": (portfolio_values[-1] - portfolio_values[0]) / portfolio_values[0],
                "benchmark_return": (benchmark_values[-1] - benchmark_values[0]) / benchmark_values[0]
            }
            
        except Exception as e:
            logger.error(f"Performance data fetch error: {e}")
            return {}
    
    async def _fetch_metric_data(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch metric data."""
        try:
            # Mock metric data
            metric_id = source_config.get("metric_id")
            if metric_id and metric_id in self.metrics:
                metric = self.metrics[metric_id]
                return {
                    "value": metric.value,
                    "unit": metric.unit,
                    "trend": metric.trend,
                    "trend_percentage": metric.trend_percentage,
                    "status": metric.status,
                    "threshold": metric.threshold
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"Metric data fetch error: {e}")
            return {}
    
    async def _fetch_table_data(self, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch table data."""
        try:
            # Mock table data
            data = []
            for i in range(10):
                data.append({
                    "symbol": f"ASSET_{i}",
                    "price": 100 + i * 10,
                    "return": np.random.normal(0.001, 0.02),
                    "volume": np.random.lognormal(15, 1),
                    "market_cap": 1000000000 * (i + 1)
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Table data fetch error: {e}")
            return []
    
    async def _fetch_heatmap_data(self, source_config: Dict[str, Any]) -> np.ndarray:
        """Fetch heatmap data."""
        try:
            # Mock correlation heatmap data
            size = source_config.get("size", 10)
            correlation_matrix = np.random.uniform(-1, 1, (size, size))
            np.fill_diagonal(correlation_matrix, 1.0)
            
            return correlation_matrix
            
        except Exception as e:
            logger.error(f"Heatmap data fetch error: {e}")
            return np.array([])
    
    async def _fetch_gauge_data(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch gauge data."""
        try:
            # Mock gauge data
            metric_id = source_config.get("metric_id")
            if metric_id and metric_id in self.metrics:
                metric = self.metrics[metric_id]
                return {
                    "value": metric.value,
                    "min_value": 0,
                    "max_value": metric.threshold * 2 if metric.threshold else 100,
                    "status": metric.status
                }
            
            return {"value": 50, "min_value": 0, "max_value": 100, "status": "normal"}
            
        except Exception as e:
            logger.error(f"Gauge data fetch error: {e}")
            return {}
    
    async def _fetch_alert_data(self, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch alert data."""
        try:
            # Get recent alerts
            recent_alerts = list(self.alerts)[-20:]
            
            alert_data = []
            for alert in recent_alerts:
                alert_data.append({
                    "alert_id": alert.alert_id,
                    "title": alert.title,
                    "message": alert.message,
                    "severity": alert.severity.value,
                    "timestamp": alert.timestamp,
                    "acknowledged": alert.acknowledged
                })
            
            return alert_data
            
        except Exception as e:
            logger.error(f"Alert data fetch error: {e}")
            return []
    
    async def _fetch_correlation_data(self, source_config: Dict[str, Any]) -> np.ndarray:
        """Fetch correlation matrix data."""
        try:
            # Mock correlation data
            symbols = source_config.get("symbols", ["AAPL", "MSFT", "GOOGL", "BTC", "ETH"])
            size = len(symbols)
            correlation_matrix = np.random.uniform(-0.5, 0.8, (size, size))
            np.fill_diagonal(correlation_matrix, 1.0)
            
            return correlation_matrix
            
        except Exception as e:
            logger.error(f"Correlation data fetch error: {e}")
            return np.array([])
    
    async def _fetch_attribution_data(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch attribution data."""
        try:
            # Mock attribution data
            factors = ["Allocation", "Selection", "Interaction", "Market", "Size", "Value"]
            contributions = np.random.uniform(-0.05, 0.05, len(factors))
            
            return {
                "factors": factors,
                "contributions": contributions.tolist(),
                "total_attribution": sum(contributions),
                "allocation_effect": contributions[0],
                "selection_effect": contributions[1],
                "interaction_effect": contributions[2]
            }
            
        except Exception as e:
            logger.error(f"Attribution data fetch error: {e}")
            return {}
    
    async def start_auto_refresh(self):
        """Start automatic dashboard refresh."""
        try:
            if self.dashboard_config["auto_refresh"]:
                self.refresh_task = asyncio.create_task(self._auto_refresh_loop())
                logger.info("Auto refresh started")
            
        except Exception as e:
            logger.error(f"Failed to start auto refresh: {e}")
    
    async def stop_auto_refresh(self):
        """Stop automatic dashboard refresh."""
        try:
            if self.refresh_task:
                self.refresh_task.cancel()
                try:
                    await self.refresh_task
                except asyncio.CancelledError:
                    pass
                logger.info("Auto refresh stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop auto refresh: {e}")
    
    async def _auto_refresh_loop(self):
        """Auto refresh loop."""
        while True:
            try:
                await self.refresh_dashboard()
                await asyncio.sleep(self.dashboard_config["refresh_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto refresh loop error: {e}")
                await asyncio.sleep(10)
    
    def get_dashboard_state(self) -> Dict[str, Any]:
        """Get current dashboard state."""
        try:
            return {
                "widgets": {
                    widget_id: {
                        "type": widget.widget_type.value,
                        "title": widget.title,
                        "position": widget.position,
                        "last_updated": widget.last_updated,
                        "has_data": widget.data is not None
                    }
                    for widget_id, widget in self.widgets.items()
                },
                "metrics": {
                    metric_id: {
                        "name": metric.name,
                        "value": metric.value,
                        "unit": metric.unit,
                        "status": metric.status,
                        "trend": metric.trend
                    }
                    for metric_id, metric in self.metrics.items()
                },
                "alerts": {
                    "total_alerts": len(self.alerts),
                    "active_alerts": len(self.active_alerts),
                    "alert_distribution": {
                        severity.value: sum(1 for a in self.active_alerts.values() if a.severity == severity)
                        for severity in AlertSeverity
                    }
                },
                "data_sources": list(self.data_sources.keys()),
                "config": self.dashboard_config,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get dashboard state: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_widget(self, widget_id: str) -> Optional[DashboardWidget]:
        """Get a specific widget."""
        return self.widgets.get(widget_id)
    
    def get_metric(self, metric_id: str) -> Optional[DashboardMetric]:
        """Get a specific metric."""
        return self.metrics.get(metric_id)
    
    def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[DashboardAlert]:
        """Get active alerts."""
        alerts = list(self.active_alerts.values())
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)
    
    def get_alert_history(self, limit: int = 100) -> List[DashboardAlert]:
        """Get alert history."""
        return list(self.alerts)[-limit:]
    
    def remove_widget(self, widget_id: str) -> bool:
        """Remove a widget."""
        try:
            if widget_id in self.widgets:
                del self.widgets[widget_id]
                logger.info(f"Widget removed: {widget_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove widget {widget_id}: {e}")
            return False
    
    def remove_metric(self, metric_id: str) -> bool:
        """Remove a metric."""
        try:
            if metric_id in self.metrics:
                del self.metrics[metric_id]
                logger.info(f"Metric removed: {metric_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove metric {metric_id}: {e}")
            return False
    
    async def _record_widget_creation(self, widget: DashboardWidget):
        """Record widget creation for compliance."""
        if not self.us_compliance.get("audit_dashboard", True):
            return
        
        audit_entry = {
            "action": "widget_creation",
            "widget_id": widget.widget_id,
            "widget_type": widget.widget_type.value,
            "title": widget.title,
            "data_source": widget.data_source,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Widget creation audit entry: {audit_entry}")
    
    async def _record_alert_creation(self, alert: DashboardAlert):
        """Record alert creation for compliance."""
        if not self.us_compliance.get("audit_dashboard", True):
            return
        
        audit_entry = {
            "action": "alert_creation",
            "alert_id": alert.alert_id,
            "title": alert.title,
            "severity": alert.severity.value,
            "source": alert.source,
            "timestamp": alert.timestamp,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Alert creation audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update dashboard configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "dashboard" in new_config:
            self.dashboard_config.update(new_config["dashboard"])
        
        logger.info("Analytics dashboard configuration updated")
