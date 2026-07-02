"""Alerting infrastructure for MERID system.

Provides unified interface for sending alerts to multiple channels:
- Slack webhooks (immediate visibility)
- PagerDuty (critical incident response)
- SMS (backup for critical alerts)
- Email (backup for warnings)

Usage::
    from utils.alerting import send_alert, AlertSeverity
    
    send_alert(
        condition="total_risk_cap",
        severity=AlertSeverity.CRITICAL,
        message="Global risk cap exceeded",
        context={"current_value": 8500, "threshold_value": 8000},
        correlation_id="abc-123-xyz",
    )
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

import httpx

from utils.logger import get_logger

logger = get_logger("utils.alerting")


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class AlertContext:
    """Context information for an alert."""
    correlation_id: Optional[str] = None
    agent_id: Optional[str] = None
    market_id: Optional[str] = None
    current_value: Optional[float] = None
    threshold_value: Optional[float] = None
    source: Optional[str] = None
    additional_fields: Dict[str, Any] = field(default_factory=dict)


class AlertChannel(str, Enum):
    """Alert delivery channels."""
    SLACK_CRITICAL = "slack_critical"
    SLACK_WARNINGS = "slack_warnings"
    SLACK_INFO = "slack_info"
    PAGERDUTY = "pagerduty"
    SMS = "sms"
    EMAIL = "email"


# ── Rate limiting ─────────────────────────────────────────────────────────────

class AlertRateLimiter:
    """Simple in-memory rate limiter for alerts."""
    
    def __init__(self):
        self._alert_history: Dict[str, List[datetime]] = {}
    
    def should_allow(self, condition: str, severity: AlertSeverity) -> bool:
        """Check if alert should be allowed based on rate limits.
        
        Rate limits:
        - Same alert: 1 per 5 minutes
        - CRITICAL: 5 per minute
        - WARNING: 10 per minute
        - INFO: 20 per minute
        """
        now = datetime.now(timezone.utc)
        key = f"{severity.value}:{condition}"
        
        # Get history for this alert
        history = self._alert_history.get(key, [])
        
        # Clean up old entries (older than 5 minutes)
        history = [t for t in history if (now - t).total_seconds() < 300]
        
        # Check rate limits
        if severity == AlertSeverity.CRITICAL:
            if len(history) >= 5:
                return False
        elif severity == AlertSeverity.WARNING:
            if len(history) >= 10:
                return False
        else:  # INFO
            if len(history) >= 20:
                return False
        
        # Check same alert rate limit (1 per 5 minutes)
        if history and (now - history[-1]).total_seconds() < 300:
            return False
        
        # Add current time to history
        history.append(now)
        self._alert_history[key] = history
        return True


_rate_limiter = AlertRateLimiter()


# ── Slack Webhook Sender ─────────────────────────────────────────────────────

async def _send_slack_alert(
    webhook_url: str,
    severity: AlertSeverity,
    condition: str,
    message: str,
    context: AlertContext,
) -> bool:
    """Send alert to Slack webhook."""
    try:
        # Build Slack message
        emoji = "🚨" if severity == AlertSeverity.CRITICAL else "⚠️" if severity == AlertSeverity.WARNING else "ℹ️"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {severity.value.upper()}: {condition}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Severity:* {severity.value.upper()}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Condition:* {condition}"
                    },
                ]
            }
        ]
        
        # Add context fields
        if context.current_value is not None:
            blocks[1]["fields"].append({
                "type": "mrkdwn",
                "text": f"*Current:* {context.current_value}"
            })
        if context.threshold_value is not None:
            blocks[1]["fields"].append({
                "type": "mrkdwn",
                "text": f"*Limit:* {context.threshold_value}"
            })
        if context.source:
            blocks[1]["fields"].append({
                "type": "mrkdwn",
                "text": f"*Source:* {context.source}"
            })
        if context.agent_id:
            blocks[1]["fields"].append({
                "type": "mrkdwn",
                "text": f"*Agent:* {context.agent_id}"
            })
        
        # Add message section
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Message:* {message}"
            }
        })
        
        # Add correlation ID if present
        if context.correlation_id:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Correlation ID:* {context.correlation_id}"
                }
            })
        
        payload = {
            "text": f"{severity.value.upper()}: {condition}",
            "blocks": blocks
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
        
        logger.info(f"Slack alert sent: {condition} (severity: {severity.value})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


# ── PagerDuty Sender ───────────────────────────────────────────────────────

async def _send_pagerduty_alert(
    api_key: str,
    severity: AlertSeverity,
    condition: str,
    message: str,
    context: AlertContext,
) -> bool:
    """Send alert to PagerDuty via Events API v2."""
    try:
        if not api_key:
            logger.warning("PagerDuty API key not configured, skipping PagerDuty alert")
            return False
        
        # Build PagerDuty event
        payload = {
            "routing_key": api_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"{condition}: {message}",
                "severity": severity.value,
                "source": context.source or "merid",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "custom_details": {
                    "condition": condition,
                    "message": message,
                }
            }
        }
        
        # Add context to custom details
        if context.current_value is not None:
            payload["payload"]["custom_details"]["current_value"] = context.current_value
        if context.threshold_value is not None:
            payload["payload"]["custom_details"]["threshold_value"] = context.threshold_value
        if context.correlation_id:
            payload["payload"]["custom_details"]["correlation_id"] = context.correlation_id
        if context.agent_id:
            payload["payload"]["custom_details"]["agent_id"] = context.agent_id
        if context.market_id:
            payload["payload"]["custom_details"]["market_id"] = context.market_id
        
        # Add additional fields
        payload["payload"]["custom_details"].update(context.additional_fields)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
        
        logger.info(f"PagerDuty alert sent: {condition} (severity: {severity.value})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send PagerDuty alert: {e}")
        return False


# ── SMS Sender (Twilio) ───────────────────────────────────────────────────────

async def _send_sms_alert(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_numbers: List[str],
    severity: AlertSeverity,
    condition: str,
    message: str,
    context: AlertContext,
) -> bool:
    """Send SMS alert via Twilio."""
    try:
        if not account_sid or not auth_token or not from_number or not to_numbers:
            logger.warning("Twilio not configured, skipping SMS alert")
            return False
        
        # Build SMS message
        emoji = "🚨" if severity == AlertSeverity.CRITICAL else "⚠️"
        sms_body = f"{emoji} {severity.value.upper()}: {condition}\n"
        sms_body += f"{message}\n"
        if context.current_value is not None and context.threshold_value is not None:
            sms_body += f"Current: {context.current_value}, Limit: {context.threshold_value}\n"
        if context.correlation_id:
            sms_body += f"Correlation: {context.correlation_id}"
        
        # Send to each recipient
        async with httpx.AsyncClient(timeout=10.0) as client:
            for to_number in to_numbers:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
                auth = (account_sid, auth_token)
                data = {
                    "From": from_number,
                    "To": to_number,
                    "Body": sms_body
                }
                
                response = await client.post(url, data=data, auth=auth)
                response.raise_for_status()
        
        logger.info(f"SMS alert sent: {condition} (severity: {severity.value})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMS alert: {e}")
        return False


# ── Main Alert Function ───────────────────────────────────────────────────────

async def send_alert(
    condition: str,
    severity: AlertSeverity = AlertSeverity.WARNING,
    message: str = "",
    context: Optional[AlertContext] = None,
) -> bool:
    """Send alert to configured channels.
    
    Args:
        condition: Alert condition identifier (e.g., "total_risk_cap")
        severity: Alert severity level
        message: Human-readable message
        context: Additional context information
        
    Returns:
        True if alert sent successfully to at least one channel
    """
    if context is None:
        context = AlertContext()
    
    # Rate limiting
    if not _rate_limiter.should_allow(condition, severity):
        logger.debug(f"Alert rate-limited: {condition} (severity: {severity.value})")
        return False
    
    # Determine channels based on severity
    channels: List[AlertChannel] = []
    
    if severity == AlertSeverity.CRITICAL:
        channels = [
            AlertChannel.SLACK_CRITICAL,
            AlertChannel.PAGERDUTY,
            AlertChannel.SMS,
        ]
    elif severity == AlertSeverity.WARNING:
        channels = [
            AlertChannel.SLACK_WARNINGS,
            AlertChannel.EMAIL,
        ]
    else:  # INFO
        channels = [
            AlertChannel.SLACK_INFO,
        ]
    
    # Send to each channel
    success = False
    
    for channel in channels:
        try:
            if channel == AlertChannel.SLACK_CRITICAL:
                webhook_url = os.getenv("SLACK_WEBHOOK_CRITICAL")
                if webhook_url:
                    success = await _send_slack_alert(webhook_url, severity, condition, message, context) or success
            
            elif channel == AlertChannel.SLACK_WARNINGS:
                webhook_url = os.getenv("SLACK_WEBHOOK_WARNINGS")
                if webhook_url:
                    success = await _send_slack_alert(webhook_url, severity, condition, message, context) or success
            
            elif channel == AlertChannel.SLACK_INFO:
                webhook_url = os.getenv("SLACK_WEBHOOK_INFO")
                if webhook_url:
                    success = await _send_slack_alert(webhook_url, severity, condition, message, context) or success
            
            elif channel == AlertChannel.PAGERDUTY:
                api_key = os.getenv("PAGERDUTY_API_KEY")
                if api_key:
                    success = await _send_pagerduty_alert(api_key, severity, condition, message, context) or success
            
            elif channel == AlertChannel.SMS:
                account_sid = os.getenv("TWILIO_ACCOUNT_SID")
                auth_token = os.getenv("TWILIO_AUTH_TOKEN")
                from_number = os.getenv("TWILIO_PHONE_NUMBER")
                recipients_str = os.getenv("ALERT_SMS_RECIPIENTS", "")
                to_numbers = [n.strip() for n in recipients_str.split(",") if n.strip()]
                
                if account_sid and auth_token and from_number and to_numbers:
                    success = await _send_sms_alert(
                        account_sid, auth_token, from_number, to_numbers,
                        severity, condition, message, context
                    ) or success
            
            elif channel == AlertChannel.EMAIL:
                # Email implementation deferred
                logger.debug("Email alert channel not yet implemented")
        
        except Exception as e:
            logger.error(f"Error sending alert to {channel}: {e}")
    
    return success


# ── Synchronous Wrapper ─────────────────────────────────────────────────────

def send_alert_sync(
    condition: str,
    severity: AlertSeverity = AlertSeverity.WARNING,
    message: str = "",
    context: Optional[AlertContext] = None,
) -> bool:
    """Synchronous wrapper for send_alert.
    
    Use this in non-async contexts. Runs the async function in a new event loop.
    If already in an async context, try to use the running loop.
    """
    import asyncio
    
    try:
        try:
            # Try to get running loop (if in async context)
            loop = asyncio.get_running_loop()
            # We're in an async context but called from sync code
            # Use asyncio.create_task if we can, otherwise just log and return
            logger.warning(f"send_alert_sync called from async context, alert may be delayed: {condition}")
            # Can't await here, so just return False
            return False
        except RuntimeError:
            # No running loop, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(send_alert(condition, severity, message, context))
            loop.close()
            return result
    except Exception as e:
        logger.error(f"Error in send_alert_sync: {e}")
        return False
