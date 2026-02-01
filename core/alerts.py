"""
Alert System for MERID.

Manages price alerts, system health alerts, and notifications.
"""

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from collections import deque

from utils.logger import get_logger

logger = get_logger("core.alerts")


class AlertType(Enum):
    """Types of alerts."""
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PRICE_CHANGE = "price_change"
    VOLUME_SPIKE = "volume_spike"
    SYSTEM_ERROR = "system_error"
    SYSTEM_WARNING = "system_warning"
    AGENT_SIGNAL = "agent_signal"
    CONSENSUS_REACHED = "consensus_reached"
    POSITION_ALERT = "position_alert"
    RISK_ALERT = "risk_alert"


class AlertPriority(Enum):
    """Alert priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(Enum):
    """Alert status."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


@dataclass
class Alert:
    """An alert configuration."""
    alert_id: str
    alert_type: AlertType
    priority: AlertPriority
    symbol: Optional[str] = None
    condition_value: Optional[float] = None
    message: str = ""
    created_at: float = field(default_factory=time.time)
    triggered_at: Optional[float] = None
    expires_at: Optional[float] = None
    status: AlertStatus = AlertStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "priority": self.priority.value,
            "symbol": self.symbol,
            "condition_value": self.condition_value,
            "message": self.message,
            "created_at": self.created_at,
            "triggered_at": self.triggered_at,
            "status": self.status.value,
        }


@dataclass
class AlertNotification:
    """A triggered alert notification."""
    notification_id: str
    alert_id: str
    alert_type: AlertType
    priority: AlertPriority
    message: str
    timestamp: float = field(default_factory=time.time)
    read: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "priority": self.priority.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "read": self.read,
            "data": self.data,
        }


class AlertManager:
    """
    Manages alerts and notifications.
    """
    
    def __init__(self, max_notifications: int = 100):
        self._alerts: Dict[str, Alert] = {}
        self._notifications: deque = deque(maxlen=max_notifications)
        self._callbacks: List[Callable[[AlertNotification], None]] = []
        self._last_prices: Dict[str, float] = {}
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        
        logger.info("Alert manager initialized")
    
    async def start(self) -> None:
        """Start alert monitoring."""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._monitor_loop())
        logger.info("Alert manager started")
    
    async def stop(self) -> None:
        """Stop alert monitoring."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Alert manager stopped")
    
    def create_price_alert(
        self,
        symbol: str,
        alert_type: AlertType,
        target_price: float,
        priority: AlertPriority = AlertPriority.MEDIUM,
        message: Optional[str] = None,
    ) -> Alert:
        """Create a price alert."""
        import uuid
        
        alert_id = f"alert-{uuid.uuid4().hex[:8]}"
        
        if not message:
            direction = "above" if alert_type == AlertType.PRICE_ABOVE else "below"
            message = f"{symbol} price {direction} ${target_price:,.2f}"
        
        alert = Alert(
            alert_id=alert_id,
            alert_type=alert_type,
            priority=priority,
            symbol=symbol,
            condition_value=target_price,
            message=message,
        )
        
        self._alerts[alert_id] = alert
        logger.info(f"Created price alert: {alert_id} - {message}")
        
        return alert
    
    def create_system_alert(
        self,
        alert_type: AlertType,
        message: str,
        priority: AlertPriority = AlertPriority.HIGH,
        data: Optional[Dict[str, Any]] = None,
    ) -> Alert:
        """Create a system alert (triggers immediately)."""
        import uuid
        
        alert_id = f"sys-{uuid.uuid4().hex[:8]}"
        
        alert = Alert(
            alert_id=alert_id,
            alert_type=alert_type,
            priority=priority,
            message=message,
            metadata=data or {},
        )
        
        self._alerts[alert_id] = alert
        
        # System alerts trigger immediately
        self._trigger_alert(alert, data)
        
        return alert
    
    def dismiss_alert(self, alert_id: str) -> bool:
        """Dismiss an alert."""
        if alert_id in self._alerts:
            self._alerts[alert_id].status = AlertStatus.DISMISSED
            return True
        return False
    
    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert."""
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            return True
        return False
    
    def get_alerts(self, status: Optional[AlertStatus] = None) -> List[Alert]:
        """Get all alerts, optionally filtered by status."""
        alerts = list(self._alerts.values())
        if status:
            alerts = [a for a in alerts if a.status == status]
        return alerts
    
    def get_notifications(self, unread_only: bool = False) -> List[AlertNotification]:
        """Get notifications."""
        notifications = list(self._notifications)
        if unread_only:
            notifications = [n for n in notifications if not n.read]
        return notifications
    
    def mark_notification_read(self, notification_id: str) -> bool:
        """Mark a notification as read."""
        for notification in self._notifications:
            if notification.notification_id == notification_id:
                notification.read = True
                return True
        return False
    
    def mark_all_read(self) -> int:
        """Mark all notifications as read."""
        count = 0
        for notification in self._notifications:
            if not notification.read:
                notification.read = True
                count += 1
        return count
    
    def update_price(self, symbol: str, price: float) -> None:
        """Update price and check alerts."""
        self._last_prices[symbol] = price
        self._check_price_alerts(symbol, price)
    
    def register_callback(self, callback: Callable[[AlertNotification], None]) -> None:
        """Register callback for new notifications."""
        self._callbacks.append(callback)
    
    def _check_price_alerts(self, symbol: str, price: float) -> None:
        """Check if any price alerts should trigger."""
        for alert in self._alerts.values():
            if alert.status != AlertStatus.ACTIVE:
                continue
            if alert.symbol != symbol:
                continue
            if alert.condition_value is None:
                continue
            
            triggered = False
            
            if alert.alert_type == AlertType.PRICE_ABOVE:
                triggered = price >= alert.condition_value
            elif alert.alert_type == AlertType.PRICE_BELOW:
                triggered = price <= alert.condition_value
            
            if triggered:
                self._trigger_alert(alert, {"price": price})
    
    def _trigger_alert(self, alert: Alert, data: Optional[Dict[str, Any]] = None) -> None:
        """Trigger an alert and create notification."""
        import uuid
        
        alert.status = AlertStatus.TRIGGERED
        alert.triggered_at = time.time()
        
        notification = AlertNotification(
            notification_id=f"notif-{uuid.uuid4().hex[:8]}",
            alert_id=alert.alert_id,
            alert_type=alert.alert_type,
            priority=alert.priority,
            message=alert.message,
            data=data or {},
        )
        
        self._notifications.append(notification)
        
        logger.info(f"Alert triggered: {alert.alert_id} - {alert.message}")
        
        # Call registered callbacks
        for callback in self._callbacks:
            try:
                callback(notification)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error(f"Alert callback error: {e}")
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                # Check for expired alerts
                now = time.time()
                for alert in self._alerts.values():
                    if alert.expires_at and now > alert.expires_at:
                        alert.status = AlertStatus.EXPIRED
                
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except (RuntimeError, ConnectionError) as e:
                logger.error(f"Alert monitor error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"Unexpected alert monitor error: {e}")
                await asyncio.sleep(5)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get alert system summary."""
        active = sum(1 for a in self._alerts.values() if a.status == AlertStatus.ACTIVE)
        triggered = sum(1 for a in self._alerts.values() if a.status == AlertStatus.TRIGGERED)
        unread = sum(1 for n in self._notifications if not n.read)
        
        return {
            "running": self._running,
            "total_alerts": len(self._alerts),
            "active_alerts": active,
            "triggered_alerts": triggered,
            "total_notifications": len(self._notifications),
            "unread_notifications": unread,
        }


# Singleton instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get or create alert manager singleton."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
