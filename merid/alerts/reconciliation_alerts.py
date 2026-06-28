"""
Reconciliation Health Alert Integration

Wires /health/reconciliation into the alert stack for real-time notifications
when reconciliation breaks, degrades, or recovers.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger("merid.alerts.reconciliation")


class ReconciliationStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    BROKEN = "broken"
    UNKNOWN = "unknown"


@dataclass
class ReconciliationAlert:
    """Alert emitted when reconciliation status changes."""
    timestamp: str
    status: ReconciliationStatus
    previous_status: Optional[ReconciliationStatus]
    message: str
    breaks: List[Dict]
    severity: str  # "info", "warning", "critical"
    
    def to_telegram_html(self) -> str:
        """Format for Telegram HTML message."""
        emoji = {
            ReconciliationStatus.OK: "✅",
            ReconciliationStatus.DEGRADED: "⚠️",
            ReconciliationStatus.BROKEN: "🚨",
            ReconciliationStatus.UNKNOWN: "❓",
        }.get(self.status, "❓")
        
        html = f"<b>{emoji} Reconciliation {self.status.upper()}</b>\n"
        html += f"<code>{self.timestamp[:19]}</code>\n\n"
        html += f"{self.message}\n"
        
        if self.breaks:
            html += f"\n<b>Active Breaks ({len(self.breaks)}):</b>\n"
            for i, break_item in enumerate(self.breaks[:5], 1):
                b_type = break_item.get("type", "unknown")
                severity = break_item.get("severity", "unknown")
                msg = break_item.get("message", "No details")
                html += f"{i}. [{severity.upper()}] {b_type}: {msg[:80]}...\n"
            if len(self.breaks) > 5:
                html += f"... and {len(self.breaks) - 5} more\n"
        
        return html
    
    def to_slack_blocks(self) -> Dict:
        """Format for Slack block kit."""
        color = {
            ReconciliationStatus.OK: "#36a64f",
            ReconciliationStatus.DEGRADED: "#daa520",
            ReconciliationStatus.BROKEN: "#ff0000",
            ReconciliationStatus.UNKNOWN: "#808080",
        }.get(self.status, "#808080")
        
        return {
            "attachments": [{
                "color": color,
                "title": f"Reconciliation {self.status.upper()}",
                "text": self.message,
                "fields": [
                    {"title": "Status", "value": self.status, "short": True},
                    {"title": "Breaks", "value": str(len(self.breaks)), "short": True},
                    {"title": "Timestamp", "value": self.timestamp[:19], "short": True},
                ],
                "footer": "MERID Reconciliation Monitor",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }]
        }


class ReconciliationAlertManager:
    """Manages reconciliation alerts and notifications."""
    
    def __init__(self):
        self._current_status: ReconciliationStatus = ReconciliationStatus.UNKNOWN
        self._last_alert_time: Optional[datetime] = None
        self._alert_handlers: List[Callable[[ReconciliationAlert], None]] = []
        self._subscribers: Set[str] = set()
        self._min_alert_interval_sec: int = 60  # Minimum seconds between alerts
        
    def add_handler(self, handler: Callable[[ReconciliationAlert], None]) -> None:
        """Add an alert handler (e.g., Telegram, Slack, webhook)."""
        self._alert_handlers.append(handler)
        
    def remove_handler(self, handler: Callable[[ReconciliationAlert], None]) -> None:
        """Remove an alert handler."""
        if handler in self._alert_handlers:
            self._alert_handlers.remove(handler)
    
    async def check_and_alert(self, reconciliation_data: Dict) -> Optional[ReconciliationAlert]:
        """
        Check reconciliation status and emit alerts on changes.
        
        Args:
            reconciliation_data: Output from /health/reconciliation endpoint
            
        Returns:
            ReconciliationAlert if alert was emitted, None otherwise
        """
        status_str = reconciliation_data.get("status", "unknown")
        new_status = ReconciliationStatus(status_str)
        
        # Determine if alert needed
        should_alert = False
        severity = "info"
        
        if new_status != self._current_status:
            # Status changed - always alert
            should_alert = True
            if new_status == ReconciliationStatus.BROKEN:
                severity = "critical"
            elif new_status == ReconciliationStatus.DEGRADED:
                severity = "warning"
            elif new_status == ReconciliationStatus.OK:
                severity = "info"  # Recovery alert
        elif new_status in (ReconciliationStatus.BROKEN, ReconciliationStatus.DEGRADED):
            # Same bad status - check if enough time passed for reminder
            if self._last_alert_time:
                elapsed = (datetime.now(timezone.utc) - self._last_alert_time).total_seconds()
                if elapsed > self._min_alert_interval_sec * 5:  # 5x interval for reminders
                    should_alert = True
                    severity = "warning" if new_status == ReconciliationStatus.DEGRADED else "critical"
        
        if not should_alert:
            return None
        
        # Build alert
        alert = ReconciliationAlert(
            timestamp=reconciliation_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            status=new_status,
            previous_status=self._current_status if self._current_status != new_status else None,
            message=reconciliation_data.get("message") or self._default_message(new_status),
            breaks=reconciliation_data.get("breaks", []),
            severity=severity,
        )
        
        # Update state
        self._current_status = new_status
        self._last_alert_time = datetime.now(timezone.utc)
        
        # Emit to all handlers
        for handler in self._alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as exc:
                logger.error(f"Reconciliation alert handler failed: {exc}")
        
        return alert
    
    def _default_message(self, status: ReconciliationStatus) -> str:
        """Get default message for status."""
        messages = {
            ReconciliationStatus.OK: "Reconciliation healthy — positions, fills, and balance are consistent.",
            ReconciliationStatus.DEGRADED: "Reconciliation degraded — minor discrepancies detected, monitoring.",
            ReconciliationStatus.BROKEN: "Reconciliation broken — significant discrepancies detected. Manual review required.",
            ReconciliationStatus.UNKNOWN: "Reconciliation status unknown — check system health.",
        }
        return messages.get(status, f"Reconciliation status: {status}")


# Global singleton
_reconciliation_alert_manager: Optional[ReconciliationAlertManager] = None


def get_reconciliation_alert_manager() -> ReconciliationAlertManager:
    """Get or create the global reconciliation alert manager."""
    global _reconciliation_alert_manager
    if _reconciliation_alert_manager is None:
        _reconciliation_alert_manager = ReconciliationAlertManager()
    return _reconciliation_alert_manager


# Pre-built handlers for common channels

async def telegram_handler(alert: ReconciliationAlert) -> None:
    """Send reconciliation alert to Telegram."""
    try:
        from merid.alerts.webhook_client import tg_send
        html = alert.to_telegram_html()
        await tg_send(html)
    except Exception as exc:
        logger.error(f"Failed to send reconciliation alert to Telegram: {exc}")


def webhook_handler(alert: ReconciliationAlert) -> None:
    """Send reconciliation alert to configured webhook."""
    try:
        from merid.alerts.webhook_client import send_alert
        import os
        import asyncio
        
        webhook_url = os.getenv("RECONCILIATION_WEBHOOK_URL")
        if not webhook_url:
            return
        
        payload = {
            "event": "reconciliation_status_change",
            "status": alert.status,
            "severity": alert.severity,
            "timestamp": alert.timestamp,
            "message": alert.message,
            "breaks_count": len(alert.breaks),
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_alert(alert.message, payload=payload))
        except RuntimeError:
            pass  # No running loop — skip
    except Exception as exc:
        logger.error(f"Failed to send reconciliation alert to webhook: {exc}")


# Convenience function to wire up standard handlers

def wire_standard_handlers() -> None:
    """Wire up standard reconciliation alert handlers (Telegram, webhook)."""
    manager = get_reconciliation_alert_manager()
    
    # Wire Telegram if configured (check settings first, then env vars)
    try:
        import os
        _has_tg = False
        try:
            from merid.settings import settings as _s
            _has_tg = bool(getattr(_s, "TELEGRAM_TOKEN", None) and getattr(_s, "TELEGRAM_CHAT_ID", None))
        except Exception as e:
            logger.debug(f"Settings lookup failed: {e}")
        if not _has_tg:
            _has_tg = bool(
                (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN"))
                and (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID"))
            )
        if _has_tg:
            manager.add_handler(telegram_handler)
            logger.info("Wired reconciliation alerts to Telegram")
    except Exception as e:
        logger.debug(f"Telegram handler wiring failed: {e}")

    # Wire webhook if configured
    if os.getenv("RECONCILIATION_WEBHOOK_URL"):
        manager.add_handler(webhook_handler)
        logger.info("Wired reconciliation alerts to webhook")


# Polling loop for continuous monitoring

async def reconciliation_alert_polling_loop(
    check_interval_sec: int = 30,
    api_endpoint: Optional[str] = None,
) -> None:
    """
    Continuous polling loop that checks reconciliation status and emits alerts.
    
    Run this as a background task:
        asyncio.create_task(reconciliation_alert_polling_loop())
    """
    import os
    import aiohttp
    
    if api_endpoint is None:
        port = os.getenv("MERID_PORT", "8011")
        import os
        api_host = os.getenv("MERID_API_HOST", "localhost")
        api_endpoint = f"http://{api_host}:{port}/api/v1/kalshi/health/reconciliation"

    manager = get_reconciliation_alert_manager()
    wire_standard_handlers()
    
    logger.info(f"Starting reconciliation alert polling loop (interval={check_interval_sec}s)")
    
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_endpoint, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        alert = await manager.check_and_alert(data)
                        if alert:
                            logger.info(f"Emitted reconciliation alert: {alert.status} ({alert.severity})")
                    else:
                        logger.warning(f"Reconciliation endpoint returned {resp.status}")
        except Exception as exc:
            logger.error(f"Reconciliation polling failed: {exc}")
        
        await asyncio.sleep(check_interval_sec)
