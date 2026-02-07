"""
MERID Notification & Alert System.

Multi-channel notification delivery with alert rules engine
and escalation policies.

Version: 1.0.0
"""

from notifications.channels import (
    NotificationChannel,
    EmailChannel,
    SMSChannel,
    PushChannel,
    WebhookChannel,
    get_channel_manager,
)
from notifications.alert_rules import AlertRule, AlertRulesEngine, get_alert_rules_engine
from notifications.escalation import EscalationPolicy, get_escalation_manager
from notifications.notification_manager import NotificationManager, get_notification_manager

__all__ = [
    "NotificationChannel",
    "EmailChannel",
    "SMSChannel",
    "PushChannel",
    "WebhookChannel",
    "get_channel_manager",
    "AlertRule",
    "AlertRulesEngine",
    "get_alert_rules_engine",
    "EscalationPolicy",
    "get_escalation_manager",
    "NotificationManager",
    "get_notification_manager",
]
