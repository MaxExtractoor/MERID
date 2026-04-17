"""
Surveillance and market abuse detection system.

Monitors for spoofing, layering, wash trading, quote stuffing, and manipulation
scenarios with thresholds, review queues, and escalation paths.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
import threading
import numpy as np

logger = get_logger(__name__)


class AbuseType(Enum):
    """Type of market abuse."""
    SPOOFING = "spoofing"
    LAYERING = "layering"
    WASH_TRADING = "wash_trading"
    QUOTE_STUFFING = "quote_stuffing"
    MANIPULATION = "manipulation"
    FRONT_RUNNING = "front_running"
    PUMP_AND_DUMP = "pump_and_dump"


class AlertSeverity(Enum):
    """Alert severity level."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewStatus(Enum):
    """Review status for alerts."""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CLEARED = "cleared"
    ESCALATED = "escalated"
    REPORTED = "reported"


@dataclass
class SurveillanceAlert:
    """Market abuse surveillance alert."""
    alert_id: str
    timestamp: datetime
    abuse_type: AbuseType
    severity: AlertSeverity
    
    agent_id: str
    strategy_id: str
    venue: str
    asset: str
    
    description: str
    evidence: Dict[str, Any]
    threshold_breached: str
    
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    
    escalated_to: Optional[str] = None
    escalated_at: Optional[datetime] = None


@dataclass
class SurveillanceThreshold:
    """Threshold for abuse detection."""
    threshold_id: str
    abuse_type: AbuseType
    metric: str
    threshold_value: float
    time_window_seconds: int
    description: str
    severity: AlertSeverity


@dataclass
class OrderPattern:
    """Order pattern for analysis."""
    agent_id: str
    timestamp: datetime
    venue: str
    asset: str
    side: str
    size: float
    price: float
    order_type: str
    cancelled: bool = False
    filled: bool = False


class SurveillanceSystem:
    """
    Market abuse surveillance and detection system.
    
    Monitors for:
    - Spoofing (large orders cancelled before execution)
    - Layering (multiple orders to create false liquidity)
    - Wash trading (self-trading)
    - Quote stuffing (excessive order/cancel rates)
    - Manipulation scenarios
    
    Provides:
    - Threshold-based detection
    - Review queues for compliance
    - Escalation paths
    - Evidence collection
    """
    
    def __init__(self):
        self._alerts: List[SurveillanceAlert] = []
        self._thresholds: Dict[str, SurveillanceThreshold] = {}
        
        self._order_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._cancel_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._trade_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        
        self._initialize_thresholds()
    
    def _initialize_thresholds(self) -> None:
        """Initialize surveillance thresholds."""
        self.register_threshold(
            threshold_id="spoofing_cancel_rate",
            abuse_type=AbuseType.SPOOFING,
            metric="cancel_rate",
            threshold_value=0.80,
            time_window_seconds=300,
            description="Cancel rate > 80% in 5 minutes suggests spoofing",
            severity=AlertSeverity.HIGH,
        )
        
        self.register_threshold(
            threshold_id="layering_order_count",
            abuse_type=AbuseType.LAYERING,
            metric="order_count",
            threshold_value=20.0,
            time_window_seconds=60,
            description="More than 20 orders in 1 minute suggests layering",
            severity=AlertSeverity.MEDIUM,
        )
        
        self.register_threshold(
            threshold_id="wash_trading_self_match",
            abuse_type=AbuseType.WASH_TRADING,
            metric="self_match_rate",
            threshold_value=0.10,
            time_window_seconds=3600,
            description="Self-match rate > 10% in 1 hour suggests wash trading",
            severity=AlertSeverity.CRITICAL,
        )
        
        self.register_threshold(
            threshold_id="quote_stuffing_rate",
            abuse_type=AbuseType.QUOTE_STUFFING,
            metric="order_cancel_rate",
            threshold_value=100.0,
            time_window_seconds=60,
            description="More than 100 order/cancel in 1 minute suggests quote stuffing",
            severity=AlertSeverity.HIGH,
        )
        
        self.register_threshold(
            threshold_id="manipulation_price_impact",
            abuse_type=AbuseType.MANIPULATION,
            metric="price_impact",
            threshold_value=0.05,
            time_window_seconds=300,
            description="Price impact > 5% in 5 minutes suggests manipulation",
            severity=AlertSeverity.CRITICAL,
        )
        
        logger.info("Initialized surveillance thresholds")
    
    def register_threshold(
        self,
        threshold_id: str,
        abuse_type: AbuseType,
        metric: str,
        threshold_value: float,
        time_window_seconds: int,
        description: str,
        severity: AlertSeverity,
    ) -> SurveillanceThreshold:
        """Register a surveillance threshold."""
        threshold = SurveillanceThreshold(
            threshold_id=threshold_id,
            abuse_type=abuse_type,
            metric=metric,
            threshold_value=threshold_value,
            time_window_seconds=time_window_seconds,
            description=description,
            severity=severity,
        )
        
        self._thresholds[threshold_id] = threshold
        
        logger.info(
            f"Registered surveillance threshold '{threshold_id}': "
            f"{abuse_type.value}, {metric} > {threshold_value}"
        )
        
        return threshold
    
    def record_order(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        side: str,
        size: float,
        price: float,
        order_type: str,
    ) -> None:
        """Record an order for surveillance."""
        pattern = OrderPattern(
            agent_id=agent_id,
            timestamp=datetime.utcnow(),
            venue=venue,
            asset=asset,
            side=side,
            size=size,
            price=price,
            order_type=order_type,
        )
        
        key = f"{agent_id}_{venue}_{asset}"
        self._order_history[key].append(pattern)
        
        self._check_surveillance(agent_id, venue, asset)
    
    def record_cancel(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        order_id: str,
    ) -> None:
        """Record an order cancellation."""
        key = f"{agent_id}_{venue}_{asset}"
        self._cancel_history[key].append({
            "timestamp": datetime.utcnow(),
            "order_id": order_id,
        })
        
        self._check_surveillance(agent_id, venue, asset)
    
    def record_trade(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        side: str,
        size: float,
        price: float,
    ) -> None:
        """Record a trade execution."""
        key = f"{agent_id}_{venue}_{asset}"
        self._trade_history[key].append({
            "timestamp": datetime.utcnow(),
            "side": side,
            "size": size,
            "price": price,
        })
        
        self._check_surveillance(agent_id, venue, asset)
    
    def _check_surveillance(
        self,
        agent_id: str,
        venue: str,
        asset: str,
    ) -> None:
        """Check surveillance thresholds."""
        key = f"{agent_id}_{venue}_{asset}"
        
        self._check_spoofing(agent_id, venue, asset, key)
        self._check_layering(agent_id, venue, asset, key)
        self._check_wash_trading(agent_id, venue, asset, key)
        self._check_quote_stuffing(agent_id, venue, asset, key)
        self._check_manipulation(agent_id, venue, asset, key)
    
    def _check_spoofing(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        key: str,
    ) -> None:
        """Check for spoofing patterns."""
        threshold = self._thresholds.get("spoofing_cancel_rate")
        if not threshold:
            return
        
        cutoff = datetime.utcnow() - timedelta(seconds=threshold.time_window_seconds)
        
        recent_orders = [
            o for o in self._order_history[key]
            if o.timestamp >= cutoff
        ]
        
        recent_cancels = [
            c for c in self._cancel_history[key]
            if c["timestamp"] >= cutoff
        ]
        
        if len(recent_orders) < 5:
            return
        
        cancel_rate = len(recent_cancels) / len(recent_orders)
        
        if cancel_rate > threshold.threshold_value:
            self._create_alert(
                abuse_type=AbuseType.SPOOFING,
                severity=threshold.severity,
                agent_id=agent_id,
                strategy_id="unknown",
                venue=venue,
                asset=asset,
                description=f"High cancel rate detected: {cancel_rate:.2%}",
                evidence={
                    "cancel_rate": cancel_rate,
                    "orders": len(recent_orders),
                    "cancels": len(recent_cancels),
                    "time_window": threshold.time_window_seconds,
                },
                threshold_breached=threshold.threshold_id,
            )
    
    def _check_layering(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        key: str,
    ) -> None:
        """Check for layering patterns."""
        threshold = self._thresholds.get("layering_order_count")
        if not threshold:
            return
        
        cutoff = datetime.utcnow() - timedelta(seconds=threshold.time_window_seconds)
        
        recent_orders = [
            o for o in self._order_history[key]
            if o.timestamp >= cutoff
        ]
        
        if len(recent_orders) > threshold.threshold_value:
            price_levels = len(set(o.price for o in recent_orders))
            
            self._create_alert(
                abuse_type=AbuseType.LAYERING,
                severity=threshold.severity,
                agent_id=agent_id,
                strategy_id="unknown",
                venue=venue,
                asset=asset,
                description=f"Excessive orders detected: {len(recent_orders)} orders",
                evidence={
                    "order_count": len(recent_orders),
                    "price_levels": price_levels,
                    "time_window": threshold.time_window_seconds,
                },
                threshold_breached=threshold.threshold_id,
            )
    
    def _check_wash_trading(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        key: str,
    ) -> None:
        """Check for wash trading patterns."""
        threshold = self._thresholds.get("wash_trading_self_match")
        if not threshold:
            return
        
        cutoff = datetime.utcnow() - timedelta(seconds=threshold.time_window_seconds)
        
        recent_trades = [
            t for t in self._trade_history[key]
            if t["timestamp"] >= cutoff
        ]
        
        if len(recent_trades) < 10:
            return
        
        buy_trades = [t for t in recent_trades if t["side"] == "buy"]
        sell_trades = [t for t in recent_trades if t["side"] == "sell"]
        
        matched_trades = 0
        for buy in buy_trades:
            for sell in sell_trades:
                if abs(buy["price"] - sell["price"]) < 0.01 and abs(buy["size"] - sell["size"]) < 0.01:
                    matched_trades += 1
        
        self_match_rate = matched_trades / len(recent_trades) if recent_trades else 0.0
        
        if self_match_rate > threshold.threshold_value:
            self._create_alert(
                abuse_type=AbuseType.WASH_TRADING,
                severity=threshold.severity,
                agent_id=agent_id,
                strategy_id="unknown",
                venue=venue,
                asset=asset,
                description=f"High self-match rate detected: {self_match_rate:.2%}",
                evidence={
                    "self_match_rate": self_match_rate,
                    "matched_trades": matched_trades,
                    "total_trades": len(recent_trades),
                    "time_window": threshold.time_window_seconds,
                },
                threshold_breached=threshold.threshold_id,
            )
    
    def _check_quote_stuffing(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        key: str,
    ) -> None:
        """Check for quote stuffing patterns."""
        threshold = self._thresholds.get("quote_stuffing_rate")
        if not threshold:
            return
        
        cutoff = datetime.utcnow() - timedelta(seconds=threshold.time_window_seconds)
        
        recent_orders = [
            o for o in self._order_history[key]
            if o.timestamp >= cutoff
        ]
        
        recent_cancels = [
            c for c in self._cancel_history[key]
            if c["timestamp"] >= cutoff
        ]
        
        order_cancel_count = len(recent_orders) + len(recent_cancels)
        
        if order_cancel_count > threshold.threshold_value:
            self._create_alert(
                abuse_type=AbuseType.QUOTE_STUFFING,
                severity=threshold.severity,
                agent_id=agent_id,
                strategy_id="unknown",
                venue=venue,
                asset=asset,
                description=f"Excessive order/cancel activity: {order_cancel_count} actions",
                evidence={
                    "order_cancel_count": order_cancel_count,
                    "orders": len(recent_orders),
                    "cancels": len(recent_cancels),
                    "time_window": threshold.time_window_seconds,
                },
                threshold_breached=threshold.threshold_id,
            )
    
    def _check_manipulation(
        self,
        agent_id: str,
        venue: str,
        asset: str,
        key: str,
    ) -> None:
        """Check for price manipulation patterns."""
        threshold = self._thresholds.get("manipulation_price_impact")
        if not threshold:
            return
        
        cutoff = datetime.utcnow() - timedelta(seconds=threshold.time_window_seconds)
        
        recent_trades = [
            t for t in self._trade_history[key]
            if t["timestamp"] >= cutoff
        ]
        
        if len(recent_trades) < 2:
            return
        
        prices = [t["price"] for t in recent_trades]
        price_change = (max(prices) - min(prices)) / min(prices)
        
        if price_change > threshold.threshold_value:
            self._create_alert(
                abuse_type=AbuseType.MANIPULATION,
                severity=threshold.severity,
                agent_id=agent_id,
                strategy_id="unknown",
                venue=venue,
                asset=asset,
                description=f"Significant price impact detected: {price_change:.2%}",
                evidence={
                    "price_impact": price_change,
                    "min_price": min(prices),
                    "max_price": max(prices),
                    "trades": len(recent_trades),
                    "time_window": threshold.time_window_seconds,
                },
                threshold_breached=threshold.threshold_id,
            )
    
    def _create_alert(
        self,
        abuse_type: AbuseType,
        severity: AlertSeverity,
        agent_id: str,
        strategy_id: str,
        venue: str,
        asset: str,
        description: str,
        evidence: Dict[str, Any],
        threshold_breached: str,
    ) -> SurveillanceAlert:
        """Create surveillance alert."""
        import hashlib
        alert_id = hashlib.md5(
            f"{agent_id}_{abuse_type.value}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        alert = SurveillanceAlert(
            alert_id=alert_id,
            timestamp=datetime.utcnow(),
            abuse_type=abuse_type,
            severity=severity,
            agent_id=agent_id,
            strategy_id=strategy_id,
            venue=venue,
            asset=asset,
            description=description,
            evidence=evidence,
            threshold_breached=threshold_breached,
        )
        
        self._alerts.append(alert)
        
        logger.warning(
            f"Surveillance alert created: {abuse_type.value} for {agent_id} "
            f"(severity={severity.value}, alert_id={alert_id})"
        )
        
        return alert
    
    def review_alert(
        self,
        alert_id: str,
        reviewer: str,
        status: ReviewStatus,
        notes: str,
    ) -> SurveillanceAlert:
        """Review a surveillance alert."""
        alert = next((a for a in self._alerts if a.alert_id == alert_id), None)
        if not alert:
            raise ValueError(f"Alert '{alert_id}' not found")
        
        alert.review_status = status
        alert.reviewed_by = reviewer
        alert.reviewed_at = datetime.utcnow()
        alert.review_notes = notes
        
        logger.info(
            f"Alert '{alert_id}' reviewed by {reviewer}: {status.value}"
        )
        
        return alert
    
    def escalate_alert(
        self,
        alert_id: str,
        escalated_to: str,
        reason: str,
    ) -> SurveillanceAlert:
        """Escalate alert to compliance."""
        alert = next((a for a in self._alerts if a.alert_id == alert_id), None)
        if not alert:
            raise ValueError(f"Alert '{alert_id}' not found")
        
        alert.review_status = ReviewStatus.ESCALATED
        alert.escalated_to = escalated_to
        alert.escalated_at = datetime.utcnow()
        alert.review_notes = (alert.review_notes or "") + f"\nEscalated: {reason}"
        
        logger.critical(
            f"Alert '{alert_id}' escalated to {escalated_to}: {reason}"
        )
        
        return alert
    
    def get_pending_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
    ) -> List[SurveillanceAlert]:
        """Get pending alerts for review."""
        alerts = [a for a in self._alerts if a.review_status == ReviewStatus.PENDING]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        alerts.sort(key=lambda a: (a.severity.value, a.timestamp), reverse=True)
        
        return alerts
    
    def get_alerts(
        self,
        agent_id: Optional[str] = None,
        abuse_type: Optional[AbuseType] = None,
        severity: Optional[AlertSeverity] = None,
        review_status: Optional[ReviewStatus] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[SurveillanceAlert]:
        """Query surveillance alerts."""
        alerts = self._alerts
        
        if agent_id:
            alerts = [a for a in alerts if a.agent_id == agent_id]
        
        if abuse_type:
            alerts = [a for a in alerts if a.abuse_type == abuse_type]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if review_status:
            alerts = [a for a in alerts if a.review_status == review_status]
        
        if since:
            alerts = [a for a in alerts if a.timestamp >= since]
        
        return alerts[-limit:]
    
    def get_surveillance_summary(self) -> Dict[str, Any]:
        """Get surveillance system summary."""
        total_alerts = len(self._alerts)
        
        by_type = {}
        by_severity = {}
        by_status = {}
        
        for alert in self._alerts:
            by_type[alert.abuse_type.value] = by_type.get(alert.abuse_type.value, 0) + 1
            by_severity[alert.severity.value] = by_severity.get(alert.severity.value, 0) + 1
            by_status[alert.review_status.value] = by_status.get(alert.review_status.value, 0) + 1
        
        return {
            "total_alerts": total_alerts,
            "by_abuse_type": by_type,
            "by_severity": by_severity,
            "by_review_status": by_status,
            "pending_review": by_status.get("pending", 0),
            "escalated": by_status.get("escalated", 0),
            "thresholds_configured": len(self._thresholds),
        }


_surveillance_system: Optional[SurveillanceSystem] = None
_surveillance_system_lock = threading.Lock()


def get_surveillance_system() -> SurveillanceSystem:
    """Get global SurveillanceSystem instance."""
    global _surveillance_system
    if _surveillance_system is None:
        with _surveillance_system_lock:
            if _surveillance_system is None:
                _surveillance_system = SurveillanceSystem()
    return _surveillance_system
