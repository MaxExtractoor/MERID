"""
Notification Router for Debate Alerts
Routes alerts to Telegram and X based on severity and routing rules.
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

from web.api.notification_formatters import (
    format_telegram_alert, 
    format_x_alert, 
    format_daily_summary,
    format_x_daily_summary,
    aggregate_similar_alerts,
    AlertItem
)
from web.api.telegram_client import get_telegram_client
from web.api.x_client import get_x_client

logger = logging.getLogger(__name__)

class NotificationChannel(Enum):
    """Available notification channels."""
    TELEGRAM = "telegram"
    X_TWITTER = "x_twitter"

@dataclass
class RoutingRule:
    """Routing rule for alerts."""
    severity: str  # 'critical' or 'warning'
    channels: List[NotificationChannel]
    min_utilization: Optional[float] = None  # Optional minimum utilization threshold
    metric_ids: Optional[Set[str]] = None  # Optional specific metrics to route
    team_filter: Optional[str] = None  # Optional team filter

class NotificationRouter:
    """Routes debate alerts to appropriate notification channels."""
    
    def __init__(self):
        """Initialize the notification router with default routing rules."""
        self.telegram_client = get_telegram_client()
        self.x_client = get_x_client()
        
        # Track last sent alerts to avoid spam
        self.last_sent_alerts: Dict[str, datetime] = {}
        
        # Rate limiting
        self.telegram_rate_limit = {
            "messages_per_hour": 50,
            "last_reset": datetime.now(),
            "count": 0
        }
        
        self.x_rate_limit = {
            "tweets_per_day": 20,
            "last_reset": datetime.now().date(),
            "count": 0
        }
        
        # Default routing rules
        self.routing_rules = [
            # Critical alerts go to both Telegram and X
            RoutingRule(
                severity="critical",
                channels=[NotificationChannel.TELEGRAM, NotificationChannel.X_TWITTER]
            ),
            # High utilization warnings go to Telegram only
            RoutingRule(
                severity="warning",
                channels=[NotificationChannel.TELEGRAM],
                min_utilization=0.9,
                metric_ids={"quota-saturation"}
            ),
            # Other warnings go to Telegram only
            RoutingRule(
                severity="warning",
                channels=[NotificationChannel.TELEGRAM]
            )
        ]
    
    def should_send_alert(self, alert: AlertItem) -> bool:
        """
        Check if an alert should be sent based on deduplication rules.
        
        Args:
            alert: Alert to check
            
        Returns:
            True if alert should be sent, False if recently sent
        """
        # Create unique key for this alert
        alert_key = f"{alert['agent_id']}_{alert['metric_id']}_{alert['severity']}"
        
        # Check if we sent this alert recently (within last hour)
        if alert_key in self.last_sent_alerts:
            last_sent = self.last_sent_alerts[alert_key]
            if datetime.now() - last_sent < timedelta(hours=1):
                return False
        
        return True
    
    def get_channels_for_alert(self, alert: AlertItem) -> List[NotificationChannel]:
        """
        Determine which channels an alert should be sent to based on routing rules.
        
        Args:
            alert: Alert to route
            
        Returns:
            List of channels to send the alert to
        """
        channels = set()
        
        for rule in self.routing_rules:
            if rule.severity != alert["severity"]:
                continue
            
            # Check utilization threshold
            if rule.min_utilization is not None:
                if alert["utilization_pct"] < rule.min_utilization:
                    continue
            
            # Check metric filter
            if rule.metric_ids is not None:
                if alert["metric_id"] not in rule.metric_ids:
                    continue
            
            # Check team filter (if available)
            if rule.team_filter is not None:
                # This would require team info from the alert
                # For now, skip team filtering
                pass
            
            # Add channels from this rule
            channels.update(rule.channels)
        
        return list(channels)
    
    async def check_rate_limit(self, channel: NotificationChannel) -> bool:
        """
        Check if we're within rate limits for a channel.
        
        Args:
            channel: Channel to check
            
        Returns:
            True if we can send, False if rate limited
        """
        if channel == NotificationChannel.TELEGRAM:
            limit = self.telegram_rate_limit
            now = datetime.now()
            
            # Reset counter if it's been an hour
            if now - limit["last_reset"] > timedelta(hours=1):
                limit["count"] = 0
                limit["last_reset"] = now
            
            if limit["count"] >= limit["messages_per_hour"]:
                logger.warning("Telegram rate limit exceeded")
                return False
            
            limit["count"] += 1
            return True
            
        elif channel == NotificationChannel.X_TWITTER:
            limit = self.x_rate_limit
            today = datetime.now().date()
            
            # Reset counter if it's a new day
            if limit["last_reset"] < today:
                limit["count"] = 0
                limit["last_reset"] = today
            
            if limit["count"] >= limit["tweets_per_day"]:
                logger.warning("X rate limit exceeded")
                return False
            
            limit["count"] += 1
            return True
        
        return True
    
    async def send_alert(self, alert: AlertItem) -> bool:
        """
        Send an alert to appropriate channels based on routing rules.
        
        Args:
            alert: Alert to send
            
        Returns:
            True if sent to at least one channel successfully
        """
        # Check if we should send this alert
        if not self.should_send_alert(alert):
            return False
        
        # Get channels for this alert
        channels = self.get_channels_for_alert(alert)
        
        if not channels:
            logger.debug(f"No channels configured for alert: {alert['agent_id']} - {alert['metric_id']}")
            return False
        
        success = False
        
        for channel in channels:
            # Check rate limits
            if not await self.check_rate_limit(channel):
                continue
            
            try:
                if channel == NotificationChannel.TELEGRAM and self.telegram_client.is_configured():
                    message = format_telegram_alert(alert)
                    if await self.telegram_client.send_alert(message):
                        success = True
                        logger.info(f"Alert sent to Telegram: {alert['agent_id']} - {alert['metric_id']}")
                
                elif channel == NotificationChannel.X_TWITTER and self.x_client.is_configured():
                    message = format_x_alert(alert)
                    if await self.x_client.send_alert(message):
                        success = True
                        logger.info(f"Alert sent to X: {alert['agent_id']} - {alert['metric_id']}")
                
            except Exception as e:
                logger.error(f"Error sending alert to {channel.value}: {e}")
        
        # Mark as sent if successful
        if success:
            alert_key = f"{alert['agent_id']}_{alert['metric_id']}_{alert['severity']}"
            self.last_sent_alerts[alert_key] = datetime.now()
        
        return success
    
    async def send_aggregated_alerts(self, aggregated_alerts: List[Dict]) -> bool:
        """
        Send aggregated alerts to reduce notification spam.
        
        Args:
            aggregated_alerts: List of aggregated alerts from notification_formatters
            
        Returns:
            True if sent successfully
        """
        success = False
        
        for agg_alert in aggregated_alerts:
            if agg_alert["type"] == "single":
                # Send single alert normally
                if await self.send_alert(agg_alert["alert"]):
                    success = True
            else:
                # Send aggregated alert
                if not await self.check_rate_limit(NotificationChannel.TELEGRAM):
                    continue
                
                if self.telegram_client.is_configured():
                    severity_emoji = "🔴" if agg_alert["severity"] == "critical" else "🟡"
                    message = f"""
{severity_emoji} **Aggregated Alert**

{agg_alert["count"]} agents triggered {agg_alert["metric_id"]}: {agg_alert["message"]}

Avg utilization: {agg_alert["avg_utilization_pct"] * 100:.1f}%
                    """.strip()
                    
                    if await self.telegram_client.send_message(message):
                        success = True
                        logger.info(f"Aggregated alert sent: {agg_alert['count']} alerts for {agg_alert['metric_id']}")
        
        return success
    
    async def send_daily_summary(self, alerts: List[AlertItem], rollups: List[Dict]) -> bool:
        """
        Send a daily summary of debate activity.
        
        Args:
            alerts: List of alerts from the past 24 hours
            rollups: Rollup data showing team/strategy performance
            
        Returns:
            True if sent successfully
        """
        success = False
        
        # Send to Telegram
        if self.telegram_client.is_configured():
            telegram_message = format_daily_summary(alerts, rollups)
            if await self.telegram_client.send_daily_summary(telegram_message):
                success = True
                logger.info("Daily summary sent to Telegram")
        
        # Send to X
        if self.x_client.is_configured():
            x_message = format_x_daily_summary(alerts, rollups)
            if await self.x_client.send_daily_summary(x_message):
                success = True
                logger.info("Daily summary sent to X")
        
        return success
    
    async def process_alerts(self, alerts: List[AlertItem]) -> bool:
        """
        Process a list of alerts and route them appropriately.
        
        Args:
            alerts: List of alerts to process
            
        Returns:
            True if any alerts were sent successfully
        """
        if not alerts:
            return False
        
        # Aggregate similar alerts to reduce spam
        aggregated = aggregate_similar_alerts(alerts)
        
        # Send aggregated alerts
        return await self.send_aggregated_alerts(aggregated)

# Global instance
_notification_router: Optional[NotificationRouter] = None
_notification_router_lock = threading.Lock()

def get_notification_router() -> NotificationRouter:
    """Get or create the global notification router instance."""
    global _notification_router
    if _notification_router is None:  # E3b: double-checked locking
        with _notification_router_lock:
            if _notification_router is None:
                _notification_router = NotificationRouter()
    return _notification_router
