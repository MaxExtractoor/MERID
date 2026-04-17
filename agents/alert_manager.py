"""Alert Manager — Centralized alert routing with deduplication and cooldowns.

Replaces scattered alert logging with:
- Central deduplication (prevents alert spam)
- Tiered cooldowns (reduces noise)
- Asset/timeframe-aware routing
- Multiple delivery channels (log, UI, Telegram)

Usage:
    from agents.alert_manager import get_alert_manager, AlertSeverity
    
    alert_id = await get_alert_manager().alert(
        severity=AlertSeverity.CRITICAL,
        title="Quorum Failure",
        message="Only 2/3 agents available for BTC-15m",
        affected_assets=["BTC"],
        affected_timeframes=["15m"],
        source="unified_decision_layer",
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("agents.alert_manager")


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class AlertChannel(Enum):
    """Alert delivery channels."""
    LOG = "log"           # Application logs
    UI = "ui"             # Web UI notifications
    TELEGRAM = "telegram" # Telegram bot
    WEBHOOK = "webhook"   # External webhook
    AUDIT = "audit"       # Immutable audit log


@dataclass
class Alert:
    """Alert record."""
    alert_id: str
    severity: AlertSeverity
    title: str
    message: str
    source: str
    affected_assets: List[str]
    affected_timeframes: List[str]
    timestamp: float
    channels: List[AlertChannel]
    metadata: Dict[str, Any]
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[float] = None


@dataclass
class AlertRule:
    """Deduplication and routing rule."""
    # Deduplication key pattern (e.g., "{source}:{title}")
    dedup_key_pattern: str = "{source}:{severity}:{title}"
    
    # Cooldown seconds per severity
    cooldowns: Dict[AlertSeverity, float] = field(default_factory=lambda: {
        AlertSeverity.INFO: 300,      # 5 min
        AlertSeverity.WARNING: 120,   # 2 min
        AlertSeverity.HIGH: 60,       # 1 min
        AlertSeverity.CRITICAL: 0,    # No cooldown
    })
    
    # Channels to deliver to
    channels: List[AlertChannel] = field(default_factory=lambda: [
        AlertChannel.LOG, AlertChannel.UI, AlertChannel.AUDIT
    ])
    
    # Auto-escalation settings
    escalate_after_count: int = 3
    escalate_severity: Optional[AlertSeverity] = None


class AlertManager:
    """
    Centralized alert management with deduplication and routing.
    
    Features:
    - Content-based deduplication using hash keys
    - Per-severity cooldowns (critical alerts always delivered)
    - Asset/timeframe-aware filtering
    - Multi-channel delivery (log, UI, Telegram, webhook)
    - Acknowledgment tracking for operator workflows
    """
    
    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}  # source -> rule
        self._recent_alerts: Dict[str, float] = {}  # dedup_key -> last_sent_time
        self._alert_counts: Dict[str, int] = defaultdict(int)  # dedup_key -> count
        self._pending_alerts: List[Alert] = []
        self._delivered_alerts: List[Alert] = []
        self._max_history = 10000
        self._lock = asyncio.Lock()
        
        # Channel handlers
        self._channel_handlers: Dict[AlertChannel, List[Callable[[Alert], None]]] = {
            AlertChannel.LOG: [self._log_handler],
            AlertChannel.UI: [],
            AlertChannel.TELEGRAM: [],
            AlertChannel.WEBHOOK: [],
            AlertChannel.AUDIT: [self._audit_handler],
        }
        
        # Default rule
        self._default_rule = AlertRule()
        
        # Incident tracking for repeated failures (Finding 3.5, 3.6)
        self._incident_tracker: Dict[str, Dict[str, Any]] = {}  # fingerprint -> incident data
        self._escalation_thresholds = {
            AlertSeverity.HIGH: 3,      # Escalate to CRITICAL after 3 occurrences
            AlertSeverity.CRITICAL: 5,   # Escalate to meta-alert after 5 occurrences
        }
        
        # Summary alert window (send summary every N minutes for repeated alerts)
        self._summary_window_seconds = 300  # 5 minutes
        self._last_summary_sent: Dict[str, float] = {}
        
        logger.info("AlertManager initialized")
    
    def register_channel_handler(
        self,
        channel: AlertChannel,
        handler: Callable[[Alert], None]
    ) -> None:
        """Register a handler for a delivery channel."""
        self._channel_handlers[channel].append(handler)
        logger.info(f"Handler registered for {channel.value}")
    
    def set_rule(self, source: str, rule: AlertRule) -> None:
        """Set custom rule for a specific alert source."""
        self._rules[source] = rule
        logger.info(f"Alert rule set for {source}")
    
    async def alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        source: str,
        affected_assets: Optional[List[str]] = None,
        affected_timeframes: Optional[List[str]] = None,
        channels: Optional[List[AlertChannel]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Optional[str]:
        """
        Send an alert through configured channels.
        
        Args:
            severity: Alert severity
            title: Short alert title
            message: Detailed message
            source: Component generating the alert
            affected_assets: Crypto assets affected
            affected_timeframes: Timeframes affected
            channels: Override default channels
            metadata: Additional structured data
            force: Bypass deduplication/cooldown
        
        Returns:
            alert_id if delivered, None if deduplicated
        """
        async with self._lock:
            # Get rule for this source
            rule = self._rules.get(source, self._default_rule)
            
            # Build deduplication key
            dedup_key = self._build_dedup_key(
                rule.dedup_key_pattern,
                source,
                severity,
                title,
                affected_assets or [],
                affected_timeframes or []
            )
            
            # Check cooldown
            now = time.time()
            last_sent = self._recent_alerts.get(dedup_key, 0)
            cooldown = rule.cooldowns.get(severity, 60)
            
            if not force and (now - last_sent) < cooldown:
                # Still in cooldown - track incident but don't alert
                self._alert_counts[dedup_key] += 1
                count = self._alert_counts[dedup_key]
                
                # Track incident for summary reporting (Finding 3.6)
                self._track_incident(dedup_key, severity, affected_assets, affected_timeframes, metadata)
                
                # Check for escalation based on repeated critical failures (Finding 3.5)
                incident = self._incident_tracker.get(dedup_key, {})
                occurrence_count = incident.get("count", 0)
                
                # Escalate on threshold breach
                if severity in self._escalation_thresholds:
                    threshold = self._escalation_thresholds[severity]
                    
                    if occurrence_count >= threshold:
                        # Send summary alert with escalation
                        return await self._send_escalated_summary(
                            dedup_key, severity, title, message, source,
                            affected_assets, affected_timeframes, channels, metadata,
                            occurrence_count
                        )
                
                # Standard escalation after rule-defined count
                if count >= rule.escalate_after_count and rule.escalate_severity:
                    if severity.value != rule.escalate_severity.value:
                        logger.warning(
                            f"Escalating alert {dedup_key} after {count} occurrences"
                        )
                        return await self.alert(
                            severity=rule.escalate_severity,
                            title=f"[ESCALATED] {title}",
                            message=message,
                            source=source,
                            affected_assets=affected_assets,
                            affected_timeframes=affected_timeframes,
                            channels=channels,
                            metadata={**metadata, "escalated_from": severity.value, "occurrence_count": count},
                            force=True,
                        )
                
                return None
            
            # Build alert
            alert_id = f"alert_{int(now)}_{hashlib.md5(dedup_key.encode()).hexdigest()[:8]}"
            alert = Alert(
                alert_id=alert_id,
                severity=severity,
                title=title,
                message=message,
                source=source,
                affected_assets=affected_assets or [],
                affected_timeframes=affected_timeframes or [],
                timestamp=now,
                channels=channels or rule.channels,
                metadata=metadata or {},
            )
            
            # Record delivery
            self._recent_alerts[dedup_key] = now
            self._alert_counts[dedup_key] = 1
            self._pending_alerts.append(alert)
            
            # Deliver to channels
            await self._deliver_alert(alert)
            
            # Move to history
            self._delivered_alerts.append(alert)
            if len(self._delivered_alerts) > self._max_history:
                self._delivered_alerts = self._delivered_alerts[-(self._max_history // 2):]
            
            return alert_id
    
    async def alert_quorum_failure(
        self,
        required: int,
        actual: int,
        decision_type: str,
        affected_assets: List[str],
        affected_timeframes: List[str],
        contributing_agents: List[str],
        missing_roles: List[str],
    ) -> Optional[str]:
        """Helper for quorum failure alerts."""
        severity = AlertSeverity.CRITICAL if actual == 0 else AlertSeverity.HIGH
        
        assets_str = ", ".join(affected_assets) if affected_assets else "unknown"
        timeframes_str = ", ".join(affected_timeframes) if affected_timeframes else "unknown"
        
        title = f"Quorum Failure: {decision_type}"
        message = (
            f"Required {required} agents, only {actual} available.\n"
            f"Assets: {assets_str}\n"
            f"Timeframes: {timeframes_str}\n"
            f"Contributing: {', '.join(contributing_agents) or 'none'}\n"
            f"Missing roles: {', '.join(missing_roles) or 'none'}"
        )
        
        return await self.alert(
            severity=severity,
            title=title,
            message=message,
            source="unified_decision_layer",
            affected_assets=affected_assets,
            affected_timeframes=affected_timeframes,
            channels=[AlertChannel.LOG, AlertChannel.UI, AlertChannel.AUDIT],
            metadata={
                "required": required,
                "actual": actual,
                "decision_type": decision_type,
                "contributing_agents": contributing_agents,
                "missing_roles": missing_roles,
            }
        )
    
    async def alert_governance_action(
        self,
        action: str,
        agent_id: str,
        reason: str,
        affected_assets: List[str],
        affected_timeframes: List[str],
        quorum_approved: bool,
    ) -> Optional[str]:
        """Helper for governance action alerts."""
        severity = AlertSeverity.HIGH if action in ["retire", "emergency_exit"] else AlertSeverity.WARNING
        
        return await self.alert(
            severity=severity,
            title=f"Governance Action: {action} on {agent_id}",
            message=reason,
            source="governor_agent",
            affected_assets=affected_assets,
            affected_timeframes=affected_timeframes,
            channels=[AlertChannel.LOG, AlertChannel.AUDIT, AlertChannel.TELEGRAM],
            metadata={
                "action": action,
                "target_agent": agent_id,
                "quorum_approved": quorum_approved,
            }
        )
    
    async def acknowledge_alert(
        self,
        alert_id: str,
        operator_id: str,
    ) -> bool:
        """Acknowledge an alert (operator workflow)."""
        async with self._lock:
            for alert in self._delivered_alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_by = operator_id
                    alert.acknowledged_at = time.time()
                    logger.info(f"Alert {alert_id} acknowledged by {operator_id}")
                    return True
            return False
    
    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[Alert]:
        """Get active (non-acknowledged) alerts with optional filtering."""
        alerts = [a for a in self._delivered_alerts if not a.acknowledged]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if asset:
            alerts = [a for a in alerts if asset in a.affected_assets]
        if timeframe:
            alerts = [a for a in alerts if timeframe in a.affected_timeframes]
        
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """Get summary of alert state."""
        active = self.get_active_alerts()
        
        by_severity = defaultdict(int)
        by_asset = defaultdict(int)
        by_timeframe = defaultdict(int)
        
        for alert in active:
            by_severity[alert.severity.value] += 1
            for asset in alert.affected_assets:
                by_asset[asset] += 1
            for tf in alert.affected_timeframes:
                by_timeframe[tf] += 1
        
        # Count by asset/timeframe combination
        asset_timeframe_matrix = defaultdict(int)
        for alert in active:
            for asset in alert.affected_assets:
                for tf in alert.affected_timeframes:
                    asset_timeframe_matrix[f"{asset}-{tf}"] += 1
        
        return {
            "total_active": len(active),
            "by_severity": dict(by_severity),
            "by_asset": dict(by_asset),
            "by_timeframe": dict(by_timeframe),
            "asset_timeframe_matrix": dict(asset_timeframe_matrix),
            "critical_unacknowledged": len([a for a in active if a.severity == AlertSeverity.CRITICAL and not a.acknowledged]),
            "recent_acknowledged": len([a for a in self._delivered_alerts[-100:] if a.acknowledged]),
        }
    
    def _track_incident(
        self,
        dedup_key: str,
        severity: AlertSeverity,
        assets: Optional[List[str]],
        timeframes: Optional[List[str]],
        metadata: Optional[Dict]
    ) -> None:
        """Track an incident occurrence for summary reporting."""
        now = time.time()
        
        if dedup_key not in self._incident_tracker:
            self._incident_tracker[dedup_key] = {
                "count": 0,
                "first_seen": now,
                "last_seen": now,
                "severity": severity,
                "assets": assets or [],
                "timeframes": timeframes or [],
                "metadata_samples": [],
            }
        
        incident = self._incident_tracker[dedup_key]
        incident["count"] += 1
        incident["last_seen"] = now
        
        # Keep last 5 metadata samples for context
        if metadata:
            incident["metadata_samples"].append({
                "timestamp": now,
                "data": metadata
            })
            incident["metadata_samples"] = incident["metadata_samples"][-5:]
    
    async def _send_escalated_summary(
        self,
        dedup_key: str,
        original_severity: AlertSeverity,
        title: str,
        message: str,
        source: str,
        affected_assets: Optional[List[str]],
        affected_timeframes: Optional[List[str]],
        channels: Optional[List[AlertChannel]],
        metadata: Optional[Dict],
        occurrence_count: int
    ) -> str:
        """Send an escalated summary alert for repeated failures."""
        incident = self._incident_tracker.get(dedup_key, {})
        first_seen = incident.get("first_seen", time.time())
        duration_minutes = (time.time() - first_seen) / 60
        
        # Escalate severity
        if original_severity == AlertSeverity.HIGH:
            new_severity = AlertSeverity.CRITICAL
        else:
            new_severity = AlertSeverity.CRITICAL  # Already critical, stay there
        
        summary_message = (
            f"[REPEATED {occurrence_count}x over {duration_minutes:.1f}min]\n"
            f"Original: {message}\n"
            f"This alert has fired {occurrence_count} times. "
            f"Manual intervention may be required."
        )
        
        # Reset the incident counter after sending summary
        incident["count"] = 0
        incident["first_seen"] = time.time()
        self._last_summary_sent[dedup_key] = time.time()
        
        return await self.alert(
            severity=new_severity,
            title=f"[SUMMARY] {title}",
            message=summary_message,
            source=source,
            affected_assets=affected_assets,
            affected_timeframes=affected_timeframes,
            channels=channels,
            metadata={
                **(metadata or {}),
                "summary_type": "repeated_alert_escalation",
                "original_severity": original_severity.value,
                "occurrence_count": occurrence_count,
                "duration_minutes": duration_minutes,
            },
            force=True,
        )
    
    def get_incident_report(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        window_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """
        Get incident statistics for asset/timeframe (Finding 3.6).
        
        Returns:
            Dict with incident counts, patterns, and recent alerts
        """
        now = time.time()
        incidents = []
        
        for dedup_key, incident in self._incident_tracker.items():
            # Filter by asset/timeframe
            if asset and asset not in incident.get("assets", []):
                continue
            if timeframe and timeframe not in incident.get("timeframes", []):
                continue
            
            # Filter by window
            if now - incident.get("last_seen", 0) > window_seconds:
                continue
            
            incidents.append({
                "key": dedup_key,
                **incident,
                "duration_seconds": now - incident.get("first_seen", now),
            })
        
        # Group by severity
        by_severity = {}
        for inc in incidents:
            sev = inc.get("severity", "unknown")
            by_severity[sev.value if hasattr(sev, "value") else str(sev)] = \
                by_severity.get(sev.value if hasattr(sev, "value") else str(sev), 0) + inc.get("count", 0)
        
        # Find top offending asset/timeframe combinations
        asset_timeframe_counts = {}
        for inc in incidents:
            for a in inc.get("assets", []):
                for tf in inc.get("timeframes", []):
                    key = f"{a}-{tf}"
                    asset_timeframe_counts[key] = asset_timeframe_counts.get(key, 0) + inc.get("count", 0)
        
        return {
            "generated_at": now,
            "window_seconds": window_seconds,
            "asset_filter": asset,
            "timeframe_filter": timeframe,
            "total_incidents": len(incidents),
            "total_occurrences": sum(i.get("count", 0) for i in incidents),
            "by_severity": by_severity,
            "top_asset_timeframe": sorted(
                asset_timeframe_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
            "recent_incidents": sorted(
                incidents,
                key=lambda x: x.get("last_seen", 0),
                reverse=True
            )[:10],
        }
    
    def _build_dedup_key(
        self,
        pattern: str,
        source: str,
        severity: AlertSeverity,
        title: str,
        assets: List[str],
        timeframes: List[str],
    ) -> str:
        """Build deduplication key from pattern."""
        # Default pattern includes source, severity, and title
        assets_hash = "".join(sorted(assets)) if assets else "none"
        timeframes_hash = "".join(sorted(timeframes)) if timeframes else "none"
        
        return pattern.format(
            source=source,
            severity=severity.value,
            title=title,
            assets=assets_hash,
            timeframes=timeframes_hash,
        )
    
    async def _deliver_alert(self, alert: Alert) -> None:
        """Deliver alert to all configured channels."""
        for channel in alert.channels:
            handlers = self._channel_handlers.get(channel, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(alert)
                    else:
                        handler(alert)
                except Exception as exc:
                    logger.error(f"Alert handler failed for {channel.value}: {exc}")
    
    def _log_handler(self, alert: Alert) -> None:
        """Log alert to application logs."""
        log_msg = f"[{alert.severity.value.upper()}] {alert.title}: {alert.message}"
        
        if alert.severity == AlertSeverity.CRITICAL:
            logger.critical(log_msg)
        elif alert.severity == AlertSeverity.HIGH:
            logger.error(log_msg)
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
    
    def _audit_handler(self, alert: Alert) -> None:
        """Record alert to immutable audit log."""
        # This could write to a persistent store
        logger.info(f"[AUDIT] Alert {alert.alert_id} recorded: {alert.title}")


# Global instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get global alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


def reset_alert_manager() -> None:
    """Reset global alert manager (testing only)."""
    global _alert_manager
    _alert_manager = None
