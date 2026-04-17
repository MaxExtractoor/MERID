"""Comprehensive tests for core/alerts.py."""

import pytest
import time
import asyncio
from unittest.mock import Mock, patch
from dataclasses import asdict

from core.alerts import (
    AlertType,
    AlertPriority,
    AlertStatus,
    Alert,
    AlertNotification,
    AlertManager,
    get_alert_manager,
)


class TestAlertType:
    """Test AlertType enum."""

    def test_alert_type_values(self):
        """Test AlertType enum values."""
        assert AlertType.PRICE_ABOVE.value == "price_above"
        assert AlertType.PRICE_BELOW.value == "price_below"
        assert AlertType.PRICE_CHANGE.value == "price_change"
        assert AlertType.VOLUME_SPIKE.value == "volume_spike"
        assert AlertType.SYSTEM_ERROR.value == "system_error"
        assert AlertType.SYSTEM_WARNING.value == "system_warning"
        assert AlertType.AGENT_SIGNAL.value == "agent_signal"
        assert AlertType.CONSENSUS_REACHED.value == "consensus_reached"
        assert AlertType.POSITION_ALERT.value == "position_alert"
        assert AlertType.RISK_ALERT.value == "risk_alert"


class TestAlertPriority:
    """Test AlertPriority enum."""

    def test_priority_values(self):
        """Test AlertPriority enum values."""
        assert AlertPriority.LOW.value == "low"
        assert AlertPriority.MEDIUM.value == "medium"
        assert AlertPriority.HIGH.value == "high"
        assert AlertPriority.CRITICAL.value == "critical"


class TestAlertStatus:
    """Test AlertStatus enum."""

    def test_status_values(self):
        """Test AlertStatus enum values."""
        assert AlertStatus.ACTIVE.value == "active"
        assert AlertStatus.TRIGGERED.value == "triggered"
        assert AlertStatus.DISMISSED.value == "dismissed"
        assert AlertStatus.EXPIRED.value == "expired"


class TestAlert:
    """Test Alert dataclass."""

    def test_alert_creation(self):
        """Test Alert creation with default values."""
        alert = Alert(
            alert_id="alert-123",
            alert_type=AlertType.PRICE_ABOVE,
            priority=AlertPriority.HIGH,
            symbol="BTC",
            condition_value=50000.0,
            message="BTC above $50,000"
        )
        
        assert alert.alert_id == "alert-123"
        assert alert.alert_type == AlertType.PRICE_ABOVE
        assert alert.priority == AlertPriority.HIGH
        assert alert.symbol == "BTC"
        assert alert.condition_value == 50000.0
        assert alert.message == "BTC above $50,000"
        assert alert.status == AlertStatus.ACTIVE
        assert alert.triggered_at is None
        assert isinstance(alert.created_at, float)

    def test_alert_to_dict(self):
        """Test Alert to_dict method."""
        alert = Alert(
            alert_id="alert-123",
            alert_type=AlertType.PRICE_BELOW,
            priority=AlertPriority.MEDIUM,
            symbol="ETH",
            condition_value=3000.0,
            message="ETH below $3,000",
            triggered_at=1234567890.0
        )
        
        d = alert.to_dict()
        
        assert d["alert_id"] == "alert-123"
        assert d["alert_type"] == "price_below"
        assert d["priority"] == "medium"
        assert d["symbol"] == "ETH"
        assert d["condition_value"] == 3000.0
        assert d["triggered_at"] == 1234567890.0
        assert d["status"] == "active"


class TestAlertNotification:
    """Test AlertNotification dataclass."""

    def test_notification_creation(self):
        """Test AlertNotification creation."""
        notification = AlertNotification(
            notification_id="notif-123",
            alert_id="alert-456",
            alert_type=AlertType.SYSTEM_ERROR,
            priority=AlertPriority.CRITICAL,
            message="System error occurred",
            data={"error_code": 500}
        )
        
        assert notification.notification_id == "notif-123"
        assert notification.alert_id == "alert-456"
        assert notification.alert_type == AlertType.SYSTEM_ERROR
        assert notification.priority == AlertPriority.CRITICAL
        assert notification.message == "System error occurred"
        assert notification.data == {"error_code": 500}
        assert notification.read is False

    def test_notification_to_dict(self):
        """Test AlertNotification to_dict method."""
        notification = AlertNotification(
            notification_id="notif-123",
            alert_id="alert-456",
            alert_type=AlertType.PRICE_ABOVE,
            priority=AlertPriority.HIGH,
            message="Price alert triggered",
            read=True,
            data={"price": 55000.0}
        )
        
        d = notification.to_dict()
        
        assert d["notification_id"] == "notif-123"
        assert d["alert_type"] == "price_above"
        assert d["priority"] == "high"
        assert d["read"] is True
        assert d["data"] == {"price": 55000.0}


class TestAlertManagerInitialization:
    """Test AlertManager initialization."""

    def test_default_initialization(self):
        """Test default AlertManager initialization."""
        manager = AlertManager()
        
        assert manager._alerts == {}
        assert len(manager._notifications) == 0
        assert manager._callbacks == []
        assert manager._last_prices == {}
        assert manager._running is False
        assert manager._check_task is None

    def test_custom_max_notifications(self):
        """Test AlertManager with custom max notifications."""
        manager = AlertManager(max_notifications=50)
        
        assert manager._notifications.maxlen == 50


class TestAlertManagerPriceAlerts:
    """Test price alert creation and management."""

    def test_create_price_alert_above(self):
        """Test creating price above alert."""
        manager = AlertManager()
        
        alert = manager.create_price_alert(
            symbol="BTC",
            alert_type=AlertType.PRICE_ABOVE,
            target_price=50000.0,
            priority=AlertPriority.HIGH
        )
        
        assert alert.alert_id.startswith("alert-")
        assert alert.alert_type == AlertType.PRICE_ABOVE
        assert alert.symbol == "BTC"
        assert alert.condition_value == 50000.0
        assert alert.priority == AlertPriority.HIGH
        assert "above" in alert.message
        assert alert.alert_id in manager._alerts

    def test_create_price_alert_below(self):
        """Test creating price below alert."""
        manager = AlertManager()
        
        alert = manager.create_price_alert(
            symbol="ETH",
            alert_type=AlertType.PRICE_BELOW,
            target_price=3000.0,
            priority=AlertPriority.MEDIUM,
            message="ETH price below $3,000.00"
        )
        
        assert alert.alert_type == AlertType.PRICE_BELOW
        assert "below" in alert.message
        assert alert.message == "ETH price below $3,000.00"

    def test_create_price_alert_default_message(self):
        """Test creating alert with default message."""
        manager = AlertManager()
        
        alert = manager.create_price_alert(
            symbol="BTC",
            alert_type=AlertType.PRICE_ABOVE,
            target_price=50000.0
        )
        
        assert alert.message == "BTC price above $50,000.00"


class TestAlertManagerSystemAlerts:
    """Test system alert creation."""

    def test_create_system_alert(self):
        """Test creating system alert triggers immediately."""
        manager = AlertManager()
        
        alert = manager.create_system_alert(
            alert_type=AlertType.SYSTEM_ERROR,
            message="Connection failed",
            priority=AlertPriority.CRITICAL,
            data={"service": "database"}
        )
        
        assert alert.alert_id.startswith("sys-")
        assert alert.alert_type == AlertType.SYSTEM_ERROR
        assert alert.priority == AlertPriority.CRITICAL
        assert alert.status == AlertStatus.TRIGGERED
        assert alert.triggered_at is not None
        assert len(manager._notifications) == 1

    def test_create_system_alert_default_priority(self):
        """Test creating system alert with default priority."""
        manager = AlertManager()
        
        alert = manager.create_system_alert(
            alert_type=AlertType.SYSTEM_WARNING,
            message="High memory usage"
        )
        
        assert alert.priority == AlertPriority.HIGH


class TestAlertManagerDismissAndDelete:
    """Test dismissing and deleting alerts."""

    def test_dismiss_alert(self):
        """Test dismissing an active alert."""
        manager = AlertManager()
        alert = manager.create_price_alert(
            symbol="BTC", alert_type=AlertType.PRICE_ABOVE, target_price=50000.0
        )
        
        result = manager.dismiss_alert(alert.alert_id)
        
        assert result is True
        assert manager._alerts[alert.alert_id].status == AlertStatus.DISMISSED

    def test_dismiss_nonexistent_alert(self):
        """Test dismissing nonexistent alert returns False."""
        manager = AlertManager()
        
        result = manager.dismiss_alert("nonexistent")
        
        assert result is False

    def test_delete_alert(self):
        """Test deleting an alert."""
        manager = AlertManager()
        alert = manager.create_price_alert(
            symbol="BTC", alert_type=AlertType.PRICE_ABOVE, target_price=50000.0
        )
        alert_id = alert.alert_id
        
        result = manager.delete_alert(alert_id)
        
        assert result is True
        assert alert_id not in manager._alerts

    def test_delete_nonexistent_alert(self):
        """Test deleting nonexistent alert returns False."""
        manager = AlertManager()
        
        result = manager.delete_alert("nonexistent")
        
        assert result is False


class TestAlertManagerGetAlerts:
    """Test getting alerts."""

    def test_get_all_alerts(self):
        """Test getting all alerts."""
        manager = AlertManager()
        alert1 = manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        alert2 = manager.create_price_alert("ETH", AlertType.PRICE_BELOW, 3000.0)
        
        alerts = manager.get_alerts()
        
        assert len(alerts) == 2
        alert_ids = {a.alert_id for a in alerts}
        assert alert1.alert_id in alert_ids
        assert alert2.alert_id in alert_ids

    def test_get_alerts_by_status(self):
        """Test getting alerts filtered by status."""
        manager = AlertManager()
        alert1 = manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        alert2 = manager.create_price_alert("ETH", AlertType.PRICE_BELOW, 3000.0)
        manager.dismiss_alert(alert1.alert_id)
        
        active_alerts = manager.get_alerts(status=AlertStatus.ACTIVE)
        dismissed_alerts = manager.get_alerts(status=AlertStatus.DISMISSED)
        
        assert len(active_alerts) == 1
        assert active_alerts[0].alert_id == alert2.alert_id
        assert len(dismissed_alerts) == 1
        assert dismissed_alerts[0].alert_id == alert1.alert_id


class TestAlertManagerPriceUpdates:
    """Test price updates and alert triggering."""

    def test_update_price_triggers_above_alert(self):
        """Test price update triggers above alert."""
        manager = AlertManager()
        manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        
        manager.update_price("BTC", 51000.0)
        
        alert = list(manager._alerts.values())[0]
        assert alert.status == AlertStatus.TRIGGERED
        assert len(manager._notifications) == 1

    def test_update_price_triggers_below_alert(self):
        """Test price update triggers below alert."""
        manager = AlertManager()
        manager.create_price_alert("ETH", AlertType.PRICE_BELOW, 3000.0)
        
        manager.update_price("ETH", 2900.0)
        
        alert = list(manager._alerts.values())[0]
        assert alert.status == AlertStatus.TRIGGERED

    def test_update_price_no_trigger(self):
        """Test price update doesn't trigger when condition not met."""
        manager = AlertManager()
        manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        
        manager.update_price("BTC", 49000.0)
        
        alert = list(manager._alerts.values())[0]
        assert alert.status == AlertStatus.ACTIVE
        assert len(manager._notifications) == 0

    def test_price_stored_in_last_prices(self):
        """Test price is stored in _last_prices."""
        manager = AlertManager()
        
        manager.update_price("BTC", 50000.0)
        
        assert manager._last_prices["BTC"] == 50000.0


class TestAlertManagerNotifications:
    """Test notification management."""

    def test_get_all_notifications(self):
        """Test getting all notifications."""
        manager = AlertManager()
        manager.create_system_alert(AlertType.SYSTEM_ERROR, "Error 1")
        manager.create_system_alert(AlertType.SYSTEM_WARNING, "Warning 1")
        
        notifications = manager.get_notifications()
        
        assert len(notifications) == 2

    def test_get_unread_notifications(self):
        """Test getting only unread notifications."""
        manager = AlertManager()
        manager.create_system_alert(AlertType.SYSTEM_ERROR, "Error 1")
        manager.create_system_alert(AlertType.SYSTEM_WARNING, "Warning 1")
        notifs = manager.get_notifications()
        manager.mark_notification_read(notifs[0].notification_id)
        
        unread = manager.get_notifications(unread_only=True)
        
        assert len(unread) == 1
        assert unread[0].message == "Warning 1"

    def test_mark_notification_read(self):
        """Test marking notification as read."""
        manager = AlertManager()
        manager.create_system_alert(AlertType.SYSTEM_ERROR, "Error 1")
        notif = manager.get_notifications()[0]
        
        result = manager.mark_notification_read(notif.notification_id)
        
        assert result is True
        assert manager.get_notifications()[0].read is True

    def test_mark_notification_read_nonexistent(self):
        """Test marking nonexistent notification returns False."""
        manager = AlertManager()
        
        result = manager.mark_notification_read("nonexistent")
        
        assert result is False

    def test_mark_all_read(self):
        """Test marking all notifications as read."""
        manager = AlertManager()
        manager.create_system_alert(AlertType.SYSTEM_ERROR, "Error 1")
        manager.create_system_alert(AlertType.SYSTEM_WARNING, "Warning 1")
        
        count = manager.mark_all_read()
        
        assert count == 2
        assert all(n.read for n in manager.get_notifications())

    def test_notifications_maxlen(self):
        """Test notifications respect maxlen."""
        manager = AlertManager(max_notifications=3)
        
        for i in range(5):
            manager.create_system_alert(AlertType.SYSTEM_ERROR, f"Error {i}")
        
        assert len(manager._notifications) == 3


class TestAlertManagerCallbacks:
    """Test callback registration and execution."""

    def test_register_callback(self):
        """Test registering callback."""
        manager = AlertManager()
        callback = Mock()
        
        manager.register_callback(callback)
        
        assert callback in manager._callbacks

    def test_callback_executed_on_trigger(self):
        """Test callback is executed when alert triggers."""
        manager = AlertManager()
        callback = Mock()
        manager.register_callback(callback)
        
        manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        manager.update_price("BTC", 51000.0)
        
        callback.assert_called_once()
        assert isinstance(callback.call_args[0][0], AlertNotification)

    def test_callback_error_handled(self):
        """Test callback errors are handled gracefully."""
        manager = AlertManager()
        bad_callback = Mock(side_effect=RuntimeError("Callback error"))
        good_callback = Mock()
        manager.register_callback(bad_callback)
        manager.register_callback(good_callback)
        
        manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        manager.update_price("BTC", 51000.0)
        
        # Both should be called, but error in first doesn't stop second
        bad_callback.assert_called_once()
        good_callback.assert_called_once()


class TestAlertManagerAsync:
    """Test async operations."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping alert manager."""
        manager = AlertManager()
        
        await manager.start()
        
        assert manager._running is True
        assert manager._check_task is not None
        
        await manager.stop()
        
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_start_when_already_running(self):
        """Test starting when already running."""
        manager = AlertManager()
        
        await manager.start()
        first_task = manager._check_task
        
        await manager.start()  # Should be no-op
        
        assert manager._check_task == first_task
        
        await manager.stop()


class TestAlertManagerSummary:
    """Test summary method."""

    def test_get_summary(self):
        """Test getting alert system summary."""
        manager = AlertManager()
        manager.create_price_alert("BTC", AlertType.PRICE_ABOVE, 50000.0)
        manager.create_price_alert("ETH", AlertType.PRICE_BELOW, 3000.0)
        manager.update_price("BTC", 51000.0)  # Triggers first alert
        manager.create_system_alert(AlertType.SYSTEM_ERROR, "Error")
        
        summary = manager.get_summary()
        
        assert summary["running"] is False
        assert summary["total_alerts"] == 3
        assert summary["active_alerts"] == 1  # ETH alert still active
        assert summary["triggered_alerts"] == 2  # BTC price + system
        assert summary["total_notifications"] == 2
        assert summary["unread_notifications"] == 2


class TestGetAlertManager:
    """Test get_alert_manager singleton."""

    def test_singleton_instance(self):
        """Test get_alert_manager returns singleton."""
        manager1 = get_alert_manager()
        manager2 = get_alert_manager()
        
        assert manager1 is manager2

    def test_singleton_is_alert_manager(self):
        """Test singleton is AlertManager instance."""
        manager = get_alert_manager()
        
        assert isinstance(manager, AlertManager)
