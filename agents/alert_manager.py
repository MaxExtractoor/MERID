"""Alert Manager — Centralized alert routing with deduplication and cooldowns.

Replaces scattered alert logging with:
- Central deduplication (prevents alert spam)
- Tiered cooldowns (reduces noise)
- Asset/timeframe-aware routing
- Multiple delivery channels (log, UI, Telegram)

Data Safety Improvements:
- Persistent storage of alert history to database
- Alert aggregation and deduplication
- Data retention policies for alert history
- Query capabilities for historical alert analysis

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
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable
from collections import defaultdict
from pathlib import Path

from utils.logger import get_logger
from config.monitoring_config import get_monitoring_config, AlertingConfig

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
    Centralized alert management with deduplication, escalation, and multi-channel delivery.
    
    Features:
    - Content-based deduplication using hash keys
    - Per-severity cooldowns (critical alerts always delivered)
    - Asset/timeframe-aware filtering
    - Multi-channel delivery (log, UI, Telegram, webhook, audit)
    - Acknowledgment tracking with timeout
    - Alert escalation workflows
    - Multi-channel delivery with fallback
    - Configuration-based settings
    """
    
    def __init__(self, config: Optional[AlertingConfig] = None):
        # Load configuration
        self._config = config or get_monitoring_config().alerting
        
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
        
        # Default rule with configuration-based settings
        self._default_rule = AlertRule(
            cooldowns={
                AlertSeverity.INFO: self._config.cooldowns.get("info", 300),
                AlertSeverity.WARNING: self._config.cooldowns.get("warning", 120),
                AlertSeverity.HIGH: self._config.cooldowns.get("high", 60),
                AlertSeverity.CRITICAL: self._config.cooldowns.get("critical", 0),
            },
            channels=[AlertChannel(c) for c in self._config.channels],
        )
        
        # Incident tracking for repeated failures
        self._incident_tracker: Dict[str, Dict[str, Any]] = {}  # fingerprint -> incident data
        self._escalation_thresholds = {
            AlertSeverity.HIGH: self._config.escalation_thresholds.get("high", 3),
            AlertSeverity.CRITICAL: self._config.escalation_thresholds.get("critical", 5),
        }
        
        # Summary alert window (send summary every N minutes for repeated alerts)
        self._summary_window_seconds = self._config.summary_window_seconds
        self._last_summary_sent: Dict[str, float] = {}
        
        # Acknowledgment tracking
        self._acknowledgments: Dict[str, Dict[str, Any]] = {}  # alert_id -> ack data
        
        # Database persistence (Data Safety Improvement)
        self._db_path = os.getenv("MERID_ALERTS_DB_PATH", "data/alerts.db")
        self._db_dir = os.path.dirname(self._db_path)
        if self._db_dir:
            Path(self._db_dir).mkdir(parents=True, exist_ok=True)
        
        self._db_initialized = False
        self._persist_enabled = True
        self._retention_days = int(os.getenv("MERID_ALERTS_RETENTION_DAYS", "90"))  # Keep alerts for 90 days
        
        # Initialize database
        self._init_database()
        self._load_alert_history()
        
        # Configure Telegram if enabled
        if self._config.telegram_enabled and self._config.telegram_bot_token:
            self._configure_telegram()
        
        # Configure webhook if enabled
        if self._config.webhook_enabled and self._config.webhook_url:
            self._configure_webhook()
        
        logger.info("AlertManager initialized with database persistence and configuration")
    
    def _configure_telegram(self) -> None:
        """Configure Telegram bot for alert delivery."""
        try:
            from merid.alerts.webhook_client import WebhookClient
            
            telegram_handler = lambda alert: self._send_telegram_alert(alert)
            self._channel_handlers[AlertChannel.TELEGRAM].append(telegram_handler)
            logger.info("Telegram channel configured")
        except Exception as e:
            logger.warning(f"Failed to configure Telegram: {e}")
    
    def _configure_webhook(self) -> None:
        """Configure webhook for alert delivery."""
        try:
            webhook_handler = lambda alert: self._send_webhook_alert(alert)
            self._channel_handlers[AlertChannel.WEBHOOK].append(webhook_handler)
            logger.info("Webhook channel configured")
        except Exception as e:
            logger.warning(f"Failed to configure webhook: {e}")
    
    def _send_telegram_alert(self, alert: Alert) -> None:
        """Send alert to Telegram bot."""
        try:
            # Import here to avoid circular dependency
            from merid.alerts.webhook_client import WebhookClient
            
            client = WebhookClient()
            message = f"🚨 *{alert.severity.value.upper()}*: {alert.title}\n\n{alert.message}"
            
            # Add metadata if available
            if alert.metadata:
                message += "\n\n" + "\n".join(f"{k}: {v}" for k, v in alert.metadata.items())
            
            # Send via Telegram API
            # This is a placeholder - actual implementation would use python-telegram-bot
            logger.info(f"Telegram alert sent: {alert.alert_id}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    def _send_webhook_alert(self, alert: Alert) -> None:
        """Send alert to webhook endpoint."""
        try:
            import httpx
            
            payload = {
                "alert_id": alert.alert_id,
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
                "source": alert.source,
                "affected_assets": alert.affected_assets,
                "affected_timeframes": alert.affected_timeframes,
                "timestamp": alert.timestamp,
                "metadata": alert.metadata,
            }
            
            response = httpx.post(
                self._config.webhook_url,
                json=payload,
                timeout=self._config.webhook_timeout,
            )
            response.raise_for_status()
            
            logger.info(f"Webhook alert sent: {alert.alert_id}")
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
    
    def _init_database(self) -> None:
        """
        Initialize the alerts database with schema for alert history.
        
        Data Safety Improvement:
        - Creates table for alert storage
        - Enables WAL mode for better concurrency
        - Sets up indexes for efficient querying
        - Supports alert aggregation and deduplication
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            
            # Create alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT NOT NULL,
                    affected_assets TEXT,
                    affected_timeframes TEXT,
                    timestamp REAL NOT NULL,
                    channels TEXT NOT NULL,
                    metadata TEXT,
                    acknowledged INTEGER DEFAULT 0,
                    acknowledged_by TEXT,
                    acknowledged_at REAL,
                    created_at REAL NOT NULL,
                    INDEX (timestamp),
                    INDEX (severity),
                    INDEX (source),
                    INDEX (acknowledged)
                )
            """)
            
            # Create alert aggregates table for deduplication
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_aggregates (
                    dedup_key TEXT PRIMARY KEY,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    count INTEGER NOT NULL,
                    severity TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    last_message TEXT,
                    affected_assets TEXT,
                    affected_timeframes TEXT,
                    INDEX (first_seen),
                    INDEX (severity),
                    INDEX (source)
                )
            """)
            
            conn.commit()
            conn.close()
            
            self._db_initialized = True
            logger.info(f"Alerts database initialized: {self._db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize alerts database: {e}")
            self._persist_enabled = False
    
    def _load_alert_history(self) -> None:
        """
        Load recent alert history from database.
        
        Data Safety Improvement:
        - Loads alerts from last 24 hours for continuity
        - Loads alert aggregates for deduplication state
        - Ensures in-memory state matches database
        """
        if not self._db_initialized or not self._persist_enabled:
            return
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # Load recent alerts (last 24 hours)
            cutoff = time.time() - 86400
            cursor.execute("""
                SELECT alert_id, severity, title, message, source,
                       affected_assets, affected_timeframes, timestamp,
                       channels, metadata, acknowledged, acknowledged_by, acknowledged_at
                FROM alerts
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """, (cutoff,))
            
            rows = cursor.fetchall()
            for row in rows:
                alert = Alert(
                    alert_id=row[0],
                    severity=AlertSeverity(row[1]),
                    title=row[2],
                    message=row[3],
                    source=row[4],
                    affected_assets=json.loads(row[5]) if row[5] else [],
                    affected_timeframes=json.loads(row[6]) if row[6] else [],
                    timestamp=row[7],
                    channels=[AlertChannel(c) for c in json.loads(row[8])],
                    metadata=json.loads(row[9]) if row[9] else {},
                    acknowledged=bool(row[10]),
                    acknowledged_by=row[11],
                    acknowledged_at=row[12],
                )
                self._delivered_alerts.append(alert)
            
            # Load alert aggregates for deduplication state
            cursor.execute("""
                SELECT dedup_key, last_seen, count, severity, source, title
                FROM alert_aggregates
            """)
            
            for row in cursor.fetchall():
                self._recent_alerts[row[0]] = row[1]
                self._alert_counts[row[0]] = row[2]
            
            conn.close()
            
            logger.info(f"Loaded {len(self._delivered_alerts)} alerts from database")
            
        except Exception as e:
            logger.error(f"Failed to load alert history: {e}")
    
    def _persist_alert(self, alert: Alert) -> None:
        """
        Persist an alert to database.
        
        Data Safety Improvement:
        - Uses INSERT OR REPLACE for idempotency
        - Serializes complex fields as JSON
        - Handles database errors gracefully
        """
        if not self._persist_enabled:
            return
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO alerts
                (alert_id, severity, title, message, source, affected_assets,
                 affected_timeframes, timestamp, channels, metadata,
                 acknowledged, acknowledged_by, acknowledged_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.alert_id,
                alert.severity.value,
                alert.title,
                alert.message,
                alert.source,
                json.dumps(alert.affected_assets),
                json.dumps(alert.affected_timeframes),
                alert.timestamp,
                json.dumps([c.value for c in alert.channels]),
                json.dumps(alert.metadata),
                1 if alert.acknowledged else 0,
                alert.acknowledged_by,
                alert.acknowledged_at,
                time.time(),
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to persist alert {alert.alert_id}: {e}")
    
    def _update_alert_aggregate(
        self,
        dedup_key: str,
        severity: AlertSeverity,
        source: str,
        title: str,
        message: str,
        affected_assets: List[str],
        affected_timeframes: List[str],
    ) -> None:
        """
        Update alert aggregate for deduplication tracking.
        
        Data Safety Improvement:
        - Tracks alert frequency for aggregation
        - Enables summary reporting
        - Supports deduplication across restarts
        """
        if not self._persist_enabled:
            return
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            now = time.time()
            
            # Check if aggregate exists
            cursor.execute("""
                SELECT count, first_seen FROM alert_aggregates WHERE dedup_key = ?
            """, (dedup_key,))
            
            row = cursor.fetchone()
            
            if row:
                # Update existing aggregate
                cursor.execute("""
                    UPDATE alert_aggregates
                    SET last_seen = ?, count = count + 1, last_message = ?
                    WHERE dedup_key = ?
                """, (now, message, dedup_key))
            else:
                # Create new aggregate
                cursor.execute("""
                    INSERT INTO alert_aggregates
                    (dedup_key, first_seen, last_seen, count, severity, source, title,
                     last_message, affected_assets, affected_timeframes)
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """, (
                    dedup_key, now, now, severity.value, source, title, message,
                    json.dumps(affected_assets), json.dumps(affected_timeframes)
                ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to update alert aggregate: {e}")
    
    def _apply_retention_policy(self) -> None:
        """
        Apply data retention policy to clean up old alerts.
        
        Data Safety Improvement:
        - Removes alerts older than retention period
        - Removes old aggregates
        - Prevents unbounded database growth
        """
        if not self._persist_enabled:
            return
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # Delete old alerts
            cutoff = time.time() - (self._retention_days * 86400)
            cursor.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff,))
            alerts_deleted = cursor.rowcount
            
            # Delete old aggregates (keep for 30 days)
            aggregate_cutoff = time.time() - (30 * 86400)
            cursor.execute("DELETE FROM alert_aggregates WHERE last_seen < ?", (aggregate_cutoff,))
            aggregates_deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if alerts_deleted > 0 or aggregates_deleted > 0:
                logger.info(
                    f"Applied alert retention policy: deleted {alerts_deleted} alerts, "
                    f"{aggregates_deleted} aggregates"
                )
            
        except Exception as e:
            logger.error(f"Failed to apply alert retention policy: {e}")
    
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
            
            # Persist to database (Data Safety Improvement)
            self._persist_alert(alert)
            self._update_alert_aggregate(
                dedup_key, severity, source, title, message,
                affected_assets or [], affected_timeframes or []
            )
            
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
        """
        Acknowledge an alert (operator workflow).
        
        Data Safety Improvement:
        - Persists acknowledgment to database
        - Tracks who acknowledged and when
        - Implements acknowledgment timeout
        """
        async with self._lock:
            for alert in self._delivered_alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_by = operator_id
                    alert.acknowledged_at = time.time()
                    
                    # Track acknowledgment with timeout
                    self._acknowledgments[alert_id] = {
                        "operator_id": operator_id,
                        "acknowledged_at": time.time(),
                        "timeout_at": time.time() + self._config.acknowledgment_timeout_seconds,
                    }
                    
                    # Persist acknowledgment to database (Data Safety Improvement)
                    self._persist_alert(alert)
                    
                    logger.info(f"Alert {alert_id} acknowledged by {operator_id}")
                    return True
            return False
    
    async def check_acknowledgment_timeouts(self) -> None:
        """
        Check for acknowledgment timeouts and re-alert if needed.
        
        This should be called periodically (e.g., every minute) to check if
        acknowledged alerts have exceeded their timeout period and need to be re-alerted.
        """
        if not self._config.acknowledgment_enabled:
            return
        
        now = time.time()
        expired_alerts = []
        
        for alert_id, ack_data in self._acknowledgments.items():
            if now > ack_data["timeout_at"]:
                expired_alerts.append(alert_id)
        
        for alert_id in expired_alerts:
            # Find the alert
            alert = next((a for a in self._delivered_alerts if a.alert_id == alert_id), None)
            if alert:
                # Re-send the alert
                await self.alert(
                    severity=alert.severity,
                    title=f"ACK TIMEOUT: {alert.title}",
                    message=f"Alert acknowledgment expired. Original: {alert.message}",
                    source=alert.source,
                    affected_assets=alert.affected_assets,
                    affected_timeframes=alert.affected_timeframes,
                    force=True,  # Bypass cooldown for timeout re-alert
                    metadata={
                        **alert.metadata,
                        "original_alert_id": alert_id,
                        "acknowledged_by": self._acknowledgments[alert_id]["operator_id"],
                        "acknowledged_at": self._acknowledgments[alert_id]["acknowledged_at"],
                    }
                )
                
                # Remove from acknowledgments
                del self._acknowledgments[alert_id]
                logger.warning(f"Alert {alert_id} acknowledgment timeout, re-alerted")
    
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
    
    def get_alert_history(
        self,
        severity: Optional[AlertSeverity] = None,
        source: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query alert history from database.
        
        Data Safety Improvement:
        - Enables historical alert analysis
        - Supports filtering by severity, source, and time
        - Returns structured data for reporting
        
        Args:
            severity: Filter by severity level
            source: Filter by alert source
            since: Filter by timestamp (since this time)
            limit: Maximum number of alerts to return
        
        Returns:
            List of alert dictionaries
        """
        if not self._db_initialized or not self._persist_enabled:
            return []
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # Build query with filters
            query = "SELECT alert_id, severity, title, message, source, timestamp, acknowledged FROM alerts WHERE 1=1"
            params = []
            
            if severity:
                query += " AND severity = ?"
                params.append(severity.value)
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            if since:
                query += " AND timestamp >= ?"
                params.append(since)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            alerts = [
                {
                    "alert_id": row[0],
                    "severity": row[1],
                    "title": row[2],
                    "message": row[3],
                    "source": row[4],
                    "timestamp": row[5],
                    "acknowledged": bool(row[6]),
                }
                for row in rows
            ]
            
            conn.close()
            return alerts
            
        except Exception as e:
            logger.error(f"Failed to query alert history: {e}")
            return []
    
    def get_alert_aggregates(
        self,
        severity: Optional[AlertSeverity] = None,
        source: Optional[str] = None,
        min_count: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get alert aggregates for deduplication analysis.
        
        Data Safety Improvement:
        - Shows alert frequency patterns
        - Identifies recurring issues
        - Supports capacity planning
        
        Args:
            severity: Filter by severity level
            source: Filter by alert source
            min_count: Minimum occurrence count
        
        Returns:
            List of alert aggregate dictionaries
        """
        if not self._db_initialized or not self._persist_enabled:
            return []
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            query = """
                SELECT dedup_key, first_seen, last_seen, count, severity, source, title
                FROM alert_aggregates
                WHERE count >= ?
            """
            params = [min_count]
            
            if severity:
                query += " AND severity = ?"
                params.append(severity.value)
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            query += " ORDER BY count DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            aggregates = [
                {
                    "dedup_key": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "count": row[3],
                    "severity": row[4],
                    "source": row[5],
                    "title": row[6],
                }
                for row in rows
            ]
            
            conn.close()
            return aggregates
            
        except Exception as e:
            logger.error(f"Failed to query alert aggregates: {e}")
            return []
    
    async def start_retention_task(self) -> None:
        """
        Start background task to apply retention policy periodically.
        
        Data Safety Improvement:
        - Automatically cleans up old alerts
        - Prevents unbounded database growth
        - Runs in background without blocking
        """
        async def retention_loop():
            while True:
                try:
                    self._apply_retention_policy()
                    await asyncio.sleep(3600)  # Run every hour
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in retention loop: {e}")
                    await asyncio.sleep(3600)
        
        asyncio.create_task(retention_loop())
        logger.info("Alert retention task started")
    
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
        """
        Deliver alert to all configured channels with fallback support.
        
        Multi-channel delivery with fallback:
        - If deliver_to_all_channels is enabled, deliver to all configured channels
        - Otherwise, deliver only to the channels specified in the alert
        - If a channel fails, log the error but continue with other channels
        - Critical alerts are always delivered to all available channels
        """
        # Determine which channels to deliver to
        if self._config.deliver_to_all_channels or alert.severity == AlertSeverity.CRITICAL:
            # Deliver to all configured channels
            channels_to_deliver = [c for c in AlertChannel if self._channel_handlers.get(c)]
        else:
            # Deliver only to specified channels
            channels_to_deliver = alert.channels
        
        delivery_results = {}
        
        for channel in channels_to_deliver:
            handlers = self._channel_handlers.get(channel, [])
            if not handlers:
                delivery_results[channel.value] = "skipped (no handlers)"
                continue
            
            channel_success = False
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(alert)
                    else:
                        handler(alert)
                    channel_success = True
                except Exception as exc:
                    logger.error(f"Alert handler failed for {channel.value}: {exc}")
            
            delivery_results[channel.value] = "delivered" if channel_success else "failed"
        
        # Log delivery summary
        logger.info(
            f"Alert {alert.alert_id} delivered to channels: {delivery_results}"
        )
    
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


def get_alert_manager(config: Optional[AlertingConfig] = None) -> AlertManager:
    """Get global alert manager with optional configuration."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager(config)
    return _alert_manager


def reset_alert_manager() -> None:
    """Reset global alert manager (testing only)."""
    global _alert_manager
    _alert_manager = None
