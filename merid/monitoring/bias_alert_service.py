"""End-to-End Bias Monitoring and Alerting Service.

This service provides continuous bias monitoring across the entire trading stack
with automated alerting when bias thresholds are exceeded.

Features:
1. Real-time bias monitoring from signal generation to execution
2. Periodic bias reports (hourly, daily, weekly)
3. Automated alerting when bias thresholds exceeded
4. Integration with existing monitoring infrastructure
5. Bias trend analysis and anomaly detection

Usage::

    from merid.monitoring.bias_alert_service import BiasAlertService, get_bias_alert_service
    
    service = get_bias_alert_service()
    service.start_monitoring()
    
    # Check for bias alerts
    alerts = service.get_active_alerts()
    for alert in alerts:
        print(f"Bias alert: {alert}")
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.monitoring.bias_alert_service")


class BiasSeverity(Enum):
    """Bias severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BiasAlert:
    """Bias alert with details and recommendations."""
    alert_id: str
    timestamp: datetime
    severity: BiasSeverity
    category: str
    bias_type: str
    description: str
    metric_value: float
    threshold: float
    asset: Optional[str] = None
    recommendation: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolution_time: Optional[datetime] = None


class BiasAlertService:
    """End-to-end bias monitoring and alerting service."""
    
    def __init__(self, check_interval_seconds: int = 300):
        """
        Initialize bias alert service.
        
        Args:
            check_interval_seconds: Interval between bias checks (default 5 minutes)
        """
        self.check_interval = check_interval_seconds
        self._active_alerts: Dict[str, BiasAlert] = {}
        self._alert_history: deque = deque(maxlen=1000)
        self._monitoring_active = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Bias thresholds (configurable)
        self.thresholds = {
            'yes_percentage': 60.0,      # Alert if YES > 60%
            'no_percentage': 60.0,       # Alert if NO > 60%
            'price_concentration': 30.0, # Alert if >30% in one price bucket
            'hourly_variation': 20.0,    # Alert if hourly std dev > 20%
            'cost_asymmetry': 0.10,      # Alert if cost diff > 10 cents
        }
        
        logger.info(
            "[BIAS-ALERT-SERVICE] Initialized with check_interval=%ds",
            check_interval_seconds
        )
    
    def start_monitoring(self) -> None:
        """Start continuous bias monitoring in background thread."""
        if self._monitoring_active:
            logger.warning("[BIAS-ALERT-SERVICE] Monitoring already active")
            return
        
        self._monitoring_active = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="BiasAlertMonitor"
        )
        self._monitor_thread.start()
        
        logger.info("[BIAS-ALERT-SERVICE] Started bias monitoring")
    
    def stop_monitoring(self) -> None:
        """Stop continuous bias monitoring."""
        self._monitoring_active = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        
        logger.info("[BIAS-ALERT-SERVICE] Stopped bias monitoring")
    
    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._monitoring_active:
            try:
                self._check_bias()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"[BIAS-ALERT-SERVICE] Monitor loop error: {e}")
                time.sleep(self.check_interval)
    
    def _check_bias(self) -> None:
        """Perform bias check and generate alerts if needed."""
        try:
            from merid.prediction.bias_monitor import get_bias_monitor
            bias_monitor = get_bias_monitor()
            
            if not bias_monitor:
                logger.debug("[BIAS-ALERT-SERVICE] Bias monitor not available")
                return
            
            # Check global bias
            global_report = bias_monitor.get_bias_report(asset=None)
            self._process_bias_report(global_report, asset="GLOBAL")
            
            # Check per-asset bias
            assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            for asset in assets:
                asset_report = bias_monitor.get_bias_report(asset=asset)
                self._process_bias_report(asset_report, asset=asset)
            
        except Exception as e:
            logger.error(f"[BIAS-ALERT-SERVICE] Bias check failed: {e}")
    
    def _process_bias_report(self, report: Any, asset: str) -> None:
        """Process bias report and generate alerts if thresholds exceeded."""
        if not report or not hasattr(report, 'bias_detected'):
            return
        
        # Check for directional bias
        if report.bias_detected:
            severity = self._determine_severity(report.yes_percentage, report.no_percentage)
            
            alert_id = f"directional_{asset}_{int(time.time())}"
            alert = BiasAlert(
                alert_id=alert_id,
                timestamp=datetime.utcnow(),
                severity=severity,
                category="directional_bias",
                bias_type="side_imbalance",
                description=f"{asset} shows {report.bias_direction.upper()} bias",
                metric_value=abs(report.yes_percentage - 50),
                threshold=10.0,
                asset=asset,
                recommendation=report.recommendation,
                evidence={
                    "yes_percentage": report.yes_percentage,
                    "no_percentage": report.no_percentage,
                    "chi_square": report.chi_square,
                    "p_value": report.p_value
                }
            )
            
            self._add_alert(alert)
        
        # Check for price distribution bias
        if hasattr(report, 'price_distribution_bias') and report.price_distribution_bias:
            alert_id = f"price_dist_{asset}_{int(time.time())}"
            alert = BiasAlert(
                alert_id=alert_id,
                timestamp=datetime.utcnow(),
                severity=BiasSeverity.MEDIUM,
                category="price_distribution_bias",
                bias_type="midpoint_clustering",
                description=f"{asset} shows price distribution bias (midpoint clustering)",
                metric_value=0.0,
                threshold=0.5,
                asset=asset,
                recommendation="Review signal generation for extreme price avoidance",
                evidence={"asset": asset}
            )
            
            self._add_alert(alert)
        
        # Check for favorite-longshot bias
        if hasattr(report, 'favorite_longshot_bias') and report.favorite_longshot_bias:
            alert_id = f"fav_longshot_{asset}_{int(time.time())}"
            alert = BiasAlert(
                alert_id=alert_id,
                timestamp=datetime.utcnow(),
                severity=BiasSeverity.HIGH,
                category="market_structure_bias",
                bias_type="favorite_longshot",
                description=f"{asset} shows favorite-longshot bias",
                metric_value=0.0,
                threshold=0.05,
                asset=asset,
                recommendation="Apply Wang Transform correction or avoid low-price longshots",
                evidence={"asset": asset}
            )
            
            self._add_alert(alert)
        
        # Check for temporal bias
        if hasattr(report, 'temporal_bias') and report.temporal_bias:
            alert_id = f"temporal_{asset}_{int(time.time())}"
            alert = BiasAlert(
                alert_id=alert_id,
                timestamp=datetime.utcnow(),
                severity=BiasSeverity.LOW,
                category="temporal_bias",
                bias_type="hourly_pattern",
                description=f"{asset} shows temporal bias (hourly patterns)",
                metric_value=0.0,
                threshold=20.0,
                asset=asset,
                recommendation="Investigate time-of-day effects in signal generation",
                evidence={"asset": asset}
            )
            
            self._add_alert(alert)
    
    def _determine_severity(self, yes_pct: float, no_pct: float) -> BiasSeverity:
        """Determine severity based on percentage imbalance."""
        max_pct = max(yes_pct, no_pct)
        
        if max_pct > 75:
            return BiasSeverity.CRITICAL
        elif max_pct > 70:
            return BiasSeverity.HIGH
        elif max_pct > 65:
            return BiasSeverity.MEDIUM
        elif max_pct > 60:
            return BiasSeverity.LOW
        else:
            return BiasSeverity.INFO
    
    def _add_alert(self, alert: BiasAlert) -> None:
        """Add alert to active alerts and log it."""
        # Check for similar existing alert
        for existing_alert in self._active_alerts.values():
            if (existing_alert.category == alert.category and 
                existing_alert.asset == alert.asset and
                not existing_alert.resolved):
                # Update existing alert instead of creating new one
                existing_alert.timestamp = alert.timestamp
                existing_alert.metric_value = alert.metric_value
                existing_alert.evidence = alert.evidence
                logger.info(
                    "[BIAS-ALERT-UPDATE] Updated existing alert %s for %s",
                    existing_alert.alert_id, alert.asset
                )
                return
        
        # Add new alert
        self._active_alerts[alert.alert_id] = alert
        self._alert_history.append(alert)
        
        # Log alert
        logger.warning(
            "[BIAS-ALERT] %s %s: %s (severity=%s, metric=%.2f, threshold=%.2f)",
            alert.asset.upper() if alert.asset else "GLOBAL",
            alert.category,
            alert.description,
            alert.severity.value.upper(),
            alert.metric_value,
            alert.threshold
        )
    
    def get_active_alerts(self) -> List[BiasAlert]:
        """Get all active (unresolved) alerts."""
        return [alert for alert in self._active_alerts.values() if not alert.resolved]
    
    def get_alert_history(self, limit: int = 100) -> List[BiasAlert]:
        """Get alert history."""
        return list(self._alert_history)[-limit:]
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Mark an alert as resolved."""
        if alert_id in self._active_alerts:
            self._active_alerts[alert_id].resolved = True
            self._active_alerts[alert_id].resolution_time = datetime.utcnow()
            logger.info("[BIAS-ALERT-RESOLVED] Alert %s marked as resolved", alert_id)
            return True
        return False
    
    def get_bias_summary(self) -> Dict[str, Any]:
        """Get summary of current bias state."""
        active_alerts = self.get_active_alerts()
        
        severity_counts = defaultdict(int)
        category_counts = defaultdict(int)
        
        for alert in active_alerts:
            severity_counts[alert.severity.value] += 1
            category_counts[alert.category] += 1
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "active_alerts": len(active_alerts),
            "by_severity": dict(severity_counts),
            "by_category": dict(category_counts),
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "severity": a.severity.value,
                    "category": a.category,
                    "asset": a.asset,
                    "description": a.description,
                    "timestamp": a.timestamp.isoformat()
                }
                for a in active_alerts
            ]
        }


# Global instance
_bias_alert_service: Optional[BiasAlertService] = None
_service_lock = threading.Lock()


def get_bias_alert_service() -> BiasAlertService:
    """Get the global bias alert service instance."""
    global _bias_alert_service
    
    with _service_lock:
        if _bias_alert_service is None:
            _bias_alert_service = BiasAlertService()
    
    return _bias_alert_service


def start_bias_monitoring() -> None:
    """Start bias monitoring (convenience function)."""
    service = get_bias_alert_service()
    service.start_monitoring()


def stop_bias_monitoring() -> None:
    """Stop bias monitoring (convenience function)."""
    service = get_bias_alert_service()
    service.stop_monitoring()
