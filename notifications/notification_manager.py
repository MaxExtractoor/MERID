"""
Notification Manager.

Central coordinator for all notification functionality.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import asyncio
import time
from typing import Dict, List, Optional, Any

from notifications.channels import ChannelManager, get_channel_manager, ChannelType
from notifications.alert_rules import AlertRulesEngine, get_alert_rules_engine, AlertRule
from notifications.escalation import EscalationManager, get_escalation_manager
from utils.logger import get_logger

logger = get_logger("notifications.manager")


class NotificationManager:
    """
    Central notification management system.
    
    Coordinates:
    - Multi-channel delivery
    - Alert rules evaluation
    - Escalation management
    - Notification preferences
    """
    
    def __init__(self):
        self.logger = get_logger("notifications.manager")

        # Sub-managers
        self._channels = get_channel_manager()
        self._rules = get_alert_rules_engine()
        self._escalation = get_escalation_manager()

        # User preferences — seeded from settings on construction
        self._preferences: Dict[str, Dict[str, Any]] = {}
        self._load_recipients_from_settings()

        # Quiet hours
        self._quiet_hours_enabled: bool = False
        self._quiet_hours_start: int = 22  # 10 PM UTC
        self._quiet_hours_end: int = 8     # 8 AM UTC
        self._quiet_hours_exceptions: List[str] = ["critical"]

        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

        # Wire up callbacks
        self._setup_callbacks()

    def _load_recipients_from_settings(self) -> None:
        """Seed default channel recipients from application settings."""
        try:
            from merid.settings import settings
            defaults: Dict[str, Any] = {}
            if getattr(settings, "RECEIVER_EMAIL", None):
                defaults["email"] = settings.RECEIVER_EMAIL
            elif getattr(settings, "MY_EMAIL", None):
                defaults["email"] = settings.MY_EMAIL
            if getattr(settings, "TWILIO_PHONE", None):
                defaults["phone"] = settings.TWILIO_PHONE
            if defaults:
                self._preferences["default"] = defaults
                self.logger.info(
                    "NotificationManager: loaded %d default recipient(s) from settings",
                    len(defaults),
                )
            else:
                self.logger.warning(
                    "NotificationManager: no default recipients configured — "
                    "email/SMS notifications will not be delivered. "
                    "Set RECEIVER_EMAIL and/or TWILIO_PHONE."
                )
        except Exception as _e:
            self.logger.warning("NotificationManager: could not load settings: %s", _e)
    
    def _setup_callbacks(self) -> None:
        """Setup internal callbacks."""
        # When a rule triggers, send notifications
        self._rules.on_trigger(self._on_rule_triggered)
    
    def _on_rule_triggered(self, rule: AlertRule, data: Dict[str, Any]) -> None:
        """Handle rule trigger."""
        # Format message
        message = self._format_message(rule.notification_template, data)
        
        # Send to configured channels
        for channel_name in rule.notification_channels:
            try:
                channel_type = ChannelType(channel_name)
                # Queue notification (async)
                asyncio.create_task(self._send_notification(
                    channel_type=channel_type,
                    subject=f"[{rule.severity.value.upper()}] {rule.name}",
                    body=message,
                    priority=rule.severity.value,
                    metadata={"rule_id": rule.rule_id, "data": data},
                ))
            except ValueError:
                self.logger.warning(f"Unknown channel: {channel_name}")
        
        # Start escalation if needed
        if rule.severity.value in ["error", "critical"]:
            self._escalation.start_escalation(
                alert_id=rule.rule_id,
                severity=rule.severity.value,
                alert_data={"rule": rule.to_dict(), "data": data},
            )
    
    def _format_message(self, template: str, data: Dict[str, Any]) -> str:
        """Format message template with data."""
        try:
            # Simple placeholder replacement
            message = template
            for key, value in self._flatten_dict(data).items():
                placeholder = "{" + key + "}"
                if placeholder in message:
                    message = message.replace(placeholder, str(value))
            return message
        except Exception:
            return template
    
    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
        """Flatten nested dict for template formatting."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    async def start(self) -> None:
        """Start notification manager."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        self.logger.info("Notification manager started")
    
    async def stop(self) -> None:
        """Stop notification manager."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Notification manager stopped")
    
    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                # Process escalations
                actions = self._escalation.process_escalations()
                
                for action in actions:
                    if action.get("action") == "notify":
                        await self._process_escalation_notification(action)
                    elif action.get("action") == "pause_trading":
                        self.logger.critical("AUTO-ACTION: Pause trading triggered")
                    elif action.get("action") == "emergency_lockdown":
                        self.logger.critical("AUTO-ACTION: Emergency lockdown triggered")
                    elif action.get("action") == "reduce_exposure":
                        self.logger.warning("AUTO-ACTION: Reduce exposure triggered")
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Process loop error: {e}")
                await asyncio.sleep(60)
    
    async def _process_escalation_notification(self, action: Dict[str, Any]) -> None:
        """Process escalation notification action."""
        channels = action.get("channels", [])
        alert_data = action.get("alert_data", {})
        
        subject = f"[ESCALATION] Alert requires attention"
        body = f"Escalation ID: {action.get('escalation_id')}\n\n{alert_data}"
        
        for channel_name in channels:
            try:
                channel_type = ChannelType(channel_name)
                await self._send_notification(
                    channel_type=channel_type,
                    subject=subject,
                    body=str(body),
                    priority="critical",
                )
            except ValueError:
                logger.debug("Unknown notification channel: %s", channel_name)
    
    async def _send_notification(
        self,
        channel_type: ChannelType,
        subject: str,
        body: str,
        priority: str = "normal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Send a notification with quiet hours check."""
        # Check quiet hours
        if self._is_quiet_hours() and priority not in self._quiet_hours_exceptions:
            self.logger.debug(f"Notification suppressed during quiet hours: {subject}")
            return None
        
        # Get recipient from preferences
        recipient = self._get_default_recipient(channel_type)
        if not recipient:
            self.logger.warning(f"No recipient configured for {channel_type.value}")
            return None
        
        return await self._channels.send(
            channel_type=channel_type,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
            metadata=metadata,
        )
    
    def _is_quiet_hours(self) -> bool:
        """Check if currently in quiet hours."""
        if not self._quiet_hours_enabled:
            return False
        
        current_hour = time.localtime().tm_hour
        
        if self._quiet_hours_start > self._quiet_hours_end:
            # Spans midnight
            return current_hour >= self._quiet_hours_start or current_hour < self._quiet_hours_end
        else:
            return self._quiet_hours_start <= current_hour < self._quiet_hours_end
    
    def _get_default_recipient(self, channel_type: ChannelType) -> str:
        """Get default recipient for channel type."""
        defaults = self._preferences.get("default", {})
        
        if channel_type == ChannelType.EMAIL:
            email = defaults.get("email", "")
            if not email:
                self.logger.warning("No email recipient configured — notification will be dropped")
            return email
        elif channel_type == ChannelType.SMS:
            return defaults.get("phone", "")
        elif channel_type == ChannelType.PUSH:
            return defaults.get("device_token", "default_device")
        elif channel_type == ChannelType.WEBHOOK:
            return defaults.get("webhook_url", "")
        
        return ""
    
    # ==========================================
    # PUBLIC API
    # ==========================================
    
    async def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        priority: str = "normal",
    ) -> Optional[str]:
        """Send a notification directly."""
        try:
            channel_type = ChannelType(channel)
        except ValueError:
            self.logger.error(f"Invalid channel: {channel}")
            return None
        
        return await self._channels.send(
            channel_type=channel_type,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
        )
    
    def evaluate_data(self, source: str, data: Dict[str, Any]) -> List[str]:
        """Evaluate data against alert rules."""
        triggered = self._rules.evaluate(source, data)
        return [r.rule_id for r in triggered]
    
    def create_price_alert(
        self,
        symbol: str,
        target_price: float,
        direction: str = "above",
    ) -> str:
        """Create a price alert."""
        return self._rules.create_price_alert(symbol, target_price, direction)
    
    def acknowledge_escalation(self, escalation_id: str, by: str = "user") -> bool:
        """Acknowledge an escalation."""
        return self._escalation.acknowledge(escalation_id, by)
    
    def resolve_escalation(self, escalation_id: str, by: str = "user") -> bool:
        """Resolve an escalation."""
        return self._escalation.resolve(escalation_id, by)
    
    def set_preferences(self, user_id: str, preferences: Dict[str, Any]) -> None:
        """Set notification preferences for a user."""
        self._preferences[user_id] = preferences
    
    def set_quiet_hours(
        self,
        enabled: bool,
        start_hour: int = 22,
        end_hour: int = 8,
        exceptions: Optional[List[str]] = None,
    ) -> None:
        """Configure quiet hours."""
        self._quiet_hours_enabled = enabled
        self._quiet_hours_start = start_hour
        self._quiet_hours_end = end_hour
        if exceptions:
            self._quiet_hours_exceptions = exceptions
    
    def get_active_escalations(self) -> List[Dict[str, Any]]:
        """Get active escalations."""
        return [e.to_dict() for e in self._escalation.get_active_escalations()]
    
    def get_notification_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get notification history."""
        return self._channels.get_history(limit)
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive notification status."""
        return {
            "running": self._running,
            "quiet_hours": {
                "enabled": self._quiet_hours_enabled,
                "start": self._quiet_hours_start,
                "end": self._quiet_hours_end,
                "currently_quiet": self._is_quiet_hours(),
            },
            "channels": self._channels.get_status(),
            "rules": self._rules.get_status(),
            "escalation": self._escalation.get_status(),
        }


# Singleton
_notification_manager: Optional[NotificationManager] = None
_notification_manager_lock = threading.Lock()


def get_notification_manager() -> NotificationManager:
    """Get or create the Notification Manager singleton."""
    global _notification_manager
    if _notification_manager is None:
        with _notification_manager_lock:
            if _notification_manager is None:
                _notification_manager = NotificationManager()
    return _notification_manager
