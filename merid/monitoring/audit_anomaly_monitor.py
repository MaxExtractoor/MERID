"""
Audit Anomaly Monitor for 15M Kalshi Crypto Trading System

This module provides comprehensive per-asset anomaly tracking for the contract-limit audit.
It extends the existing thesis_side_monitor and rejection_monitor with additional counters
for silent failure modes identified in the audit.

Key Features:
- Per-asset counters for all critical failure modes
- Blocked order tracking by reason (contract limit, stale data, venue unavailable, circuit-breaker, side/thesis mismatch)
- Exit vs entry blocking statistics
- Expected-to-route-but-did-not event tracking
- Exit intent to fill/failure latency tracking
- Integration with existing monitoring infrastructure
- Threshold-based alerting for anomaly detection

Usage in production code:
    from merid.monitoring.audit_anomaly_monitor import get_audit_anomaly_monitor
    
    monitor = get_audit_anomaly_monitor()
    monitor.record_blocked_order(
        asset="BTC",
        reason="contract_limit_violation",
        order_type="entry",
        market_id="KXBTC15M-...",
        additional_context={"limit": 1, "requested": 2}
    )
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, asdict
from utils.logger import get_logger

logger = get_logger("merid.monitoring.audit_anomaly_monitor")


@dataclass
class BlockedOrderEvent:
    """Structured blocked order event for audit logging."""
    timestamp: str
    asset: str
    reason: str
    order_type: str  # "entry" or "exit"
    market_id: Optional[str] = None
    thesis_side: Optional[str] = None
    order_side: Optional[str] = None
    selected_price_cents: Optional[int] = None
    limit_violation: Optional[bool] = None
    circuit_breaker_state: Optional[str] = None
    md_staleness_seconds: Optional[float] = None
    exit_liveness_state: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExitIntentEvent:
    """Structured exit intent event for latency tracking."""
    timestamp: str
    asset: str
    market_id: str
    thesis_side: str
    position_size: int
    exit_count: int
    intent_price_cents: Optional[int] = None
    additional_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExpectedRouteEvent:
    """Structured expected-to-route-but-did-not event."""
    timestamp: str
    asset: str
    market_id: str
    expected_action: str
    actual_outcome: str
    blocker: str
    additional_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class AuditAnomalyMonitor:
    """
    Comprehensive audit anomaly monitor with per-asset counters.
    
    Tracks silent failure modes identified in the contract-limit audit:
    - Contract limit violations
    - Stale market data blocks
    - Venue unavailable blocks
    - Circuit-breaker cooldown blocks
    - Side/thesis mismatch blocks
    - Exit vs entry blocking statistics
    - Expected-to-route-but-did-not events
    - Exit intent to fill/failure latency
    """
    
    # Blocked order reasons
    REASON_CONTRACT_LIMIT = "contract_limit_violation"
    REASON_STALE_DATA = "stale_market_data"
    REASON_VENUE_UNAVAILABLE = "venue_unavailable"
    REASON_CIRCUIT_BREAKER = "circuit_breaker_cooldown"
    REASON_SIDE_THESIS_MISMATCH = "side_thesis_mismatch"
    REASON_PRICE_RANGE = "price_range_violation"
    REASON_DUPLICATE_ORDER = "duplicate_order"
    REASON_OPEN_ORDER_EXISTS = "open_order_exists"
    REASON_STRIP_COOLDOWN = "strip_cooldown"
    REASON_OTHER = "other"
    
    def __init__(self, max_history_size: int = 10000):
        """Initialize the audit anomaly monitor."""
        self.max_history_size = max_history_size
        
        # Per-asset blocked order counters
        self._blocked_orders: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )  # asset -> order_type -> reason -> count
        
        # Per-asset exit intent tracking
        self._exit_intents: Dict[str, List[Dict]] = defaultdict(list)  # asset -> list of exit intents
        self._exit_intent_outcomes: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )  # asset -> outcome -> count
        
        # Expected-to-route-but-did-not events
        self._expected_route_events: List[Dict] = []
        
        # Latency tracking (exit intent to fill/failure)
        self._exit_latencies: Dict[str, List[float]] = defaultdict(list)  # asset -> latencies in seconds
        
        # History buffers
        self._blocked_order_history: List[Dict] = []
        self._exit_intent_history: List[Dict] = []
        
        # Timestamps for rate calculations
        self._start_time = datetime.now(timezone.utc)
        
        logger.info(
            "[AUDIT-ANOMALY-MONITOR-INIT] max_history_size=%d",
            max_history_size
        )
    
    def record_blocked_order(
        self,
        asset: str,
        reason: str,
        order_type: str,
        market_id: Optional[str] = None,
        thesis_side: Optional[str] = None,
        order_side: Optional[str] = None,
        selected_price_cents: Optional[int] = None,
        limit_violation: Optional[bool] = None,
        circuit_breaker_state: Optional[str] = None,
        md_staleness_seconds: Optional[float] = None,
        exit_liveness_state: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a blocked order event.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            reason: Block reason (use REASON_* constants)
            order_type: Order type ("entry" or "exit")
            market_id: Kalshi market ID
            thesis_side: Thesis side from intent
            order_side: Order side that was blocked
            selected_price_cents: Selected price in cents
            limit_violation: Whether this was a limit violation
            circuit_breaker_state: Circuit breaker state at time of block
            md_staleness_seconds: Market data staleness in seconds
            exit_liveness_state: Exit liveness state
            additional_context: Additional context dict
        """
        # Update counters
        self._blocked_orders[asset][order_type][reason] += 1
        
        # Create event
        event = BlockedOrderEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            reason=reason,
            order_type=order_type,
            market_id=market_id,
            thesis_side=thesis_side,
            order_side=order_side,
            selected_price_cents=selected_price_cents,
            limit_violation=limit_violation,
            circuit_breaker_state=circuit_breaker_state,
            md_staleness_seconds=md_staleness_seconds,
            exit_liveness_state=exit_liveness_state,
            additional_context=additional_context,
        )
        
        # Add to history
        self._blocked_order_history.append(event.to_dict())
        if len(self._blocked_order_history) > self.max_history_size:
            self._blocked_order_history = self._blocked_order_history[-self.max_history_size:]
        
        # Log structured event
        logger.info(
            "[AUDIT-BLOCKED-ORDER] asset=%s reason=%s order_type=%s market_id=%s "
            "total_blocked_asset=%d total_blocked_type=%d total_blocked_reason=%d",
            asset, reason, order_type, market_id,
            sum(self._blocked_orders[asset][order_type].values()),
            sum(self._blocked_orders[asset].values()),
            sum(self._blocked_orders[asset][order_type][reason] for asset in self._blocked_orders for order_type in self._blocked_orders[asset])
        )
    
    def record_exit_intent(
        self,
        asset: str,
        market_id: str,
        thesis_side: str,
        position_size: int,
        exit_count: int,
        intent_price_cents: Optional[int] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Record an exit intent for latency tracking.
        
        Args:
            asset: Asset symbol
            market_id: Kalshi market ID
            thesis_side: Thesis side
            position_size: Current position size
            exit_count: Exit count
            intent_price_cents: Intent price in cents
            additional_context: Additional context
            
        Returns:
            Intent ID for later outcome recording
        """
        intent_id = f"{market_id}_{int(time.time() * 1000)}"
        
        event = ExitIntentEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            market_id=market_id,
            thesis_side=thesis_side,
            position_size=position_size,
            exit_count=exit_count,
            intent_price_cents=intent_price_cents,
            additional_context=additional_context,
        )
        
        # Store with intent_id
        event_dict = event.to_dict()
        event_dict["intent_id"] = intent_id
        self._exit_intents[asset].append(event_dict)
        
        # Add to history
        self._exit_intent_history.append(event_dict)
        if len(self._exit_intent_history) > self.max_history_size:
            self._exit_intent_history = self._exit_intent_history[-self.max_history_size:]
        
        logger.debug(
            "[AUDIT-EXIT-INTENT] asset=%s market_id=%s intent_id=%s position_size=%d exit_count=%d",
            asset, market_id, intent_id, position_size, exit_count
        )
        
        return intent_id
    
    def record_exit_outcome(
        self,
        asset: str,
        intent_id: str,
        outcome: str,  # "filled", "failed", "blocked", "timeout"
        latency_seconds: Optional[float] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record the outcome of an exit intent.
        
        Args:
            asset: Asset symbol
            intent_id: Intent ID from record_exit_intent
            outcome: Outcome ("filled", "failed", "blocked", "timeout")
            latency_seconds: Time from intent to outcome in seconds
            additional_context: Additional context
        """
        # Update outcome counters
        self._exit_intent_outcomes[asset][outcome] += 1
        
        # Track latency
        if latency_seconds is not None:
            self._exit_latencies[asset].append(latency_seconds)
        
        # Find and update the intent
        for intent in self._exit_intents[asset]:
            if intent.get("intent_id") == intent_id:
                intent["outcome"] = outcome
                intent["latency_seconds"] = latency_seconds
                intent["outcome_timestamp"] = datetime.now(timezone.utc).isoformat()
                intent["outcome_additional_context"] = additional_context
                break
        
        logger.info(
            "[AUDIT-EXIT-OUTCOME] asset=%s intent_id=%s outcome=%s latency=%.3fs",
            asset, intent_id, outcome, latency_seconds or 0
        )
    
    def record_expected_route_failure(
        self,
        asset: str,
        market_id: str,
        expected_action: str,
        actual_outcome: str,
        blocker: str,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an expected-to-route-but-did-not event.
        
        Args:
            asset: Asset symbol
            market_id: Kalshi market ID
            expected_action: What was expected to happen
            actual_outcome: What actually happened
            blocker: What blocked the expected action
            additional_context: Additional context
        """
        event = ExpectedRouteEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            market_id=market_id,
            expected_action=expected_action,
            actual_outcome=actual_outcome,
            blocker=blocker,
            additional_context=additional_context,
        )
        
        self._expected_route_events.append(event.to_dict())
        if len(self._expected_route_events) > self.max_history_size:
            self._expected_route_events = self._expected_route_events[-self.max_history_size:]
        
        logger.critical(
            "[AUDIT-EXPECTED-ROUTE-FAILURE] asset=%s market_id=%s expected=%s actual=%s blocker=%s",
            asset, market_id, expected_action, actual_outcome, blocker
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive audit anomaly metrics.
        
        Returns:
            Dict with all metrics including:
            - blocked_orders: Per-asset, per-type, per-reason counts
            - exit_intents: Per-asset exit intent statistics
            - exit_latencies: Per-asset latency statistics
            - expected_route_failures: Count and recent events
            - summary: High-level summary
        """
        # Calculate blocked order totals
        blocked_totals = {}
        for asset in self._blocked_orders:
            blocked_totals[asset] = {
                "total": sum(
                    self._blocked_orders[asset][order_type][reason]
                    for order_type in self._blocked_orders[asset]
                    for reason in self._blocked_orders[asset][order_type]
                ),
                "entries": sum(
                    self._blocked_orders[asset]["entry"][reason]
                    for reason in self._blocked_orders[asset]["entry"]
                ),
                "exits": sum(
                    self._blocked_orders[asset]["exit"][reason]
                    for reason in self._blocked_orders[asset]["exit"]
                ),
                "by_reason": {
                    reason: sum(
                        self._blocked_orders[asset][order_type][reason]
                        for order_type in self._blocked_orders[asset]
                    )
                    for reason in set(
                        reason
                        for order_type in self._blocked_orders[asset]
                        for reason in self._blocked_orders[asset][order_type]
                    )
                }
            }
        
        # Calculate exit latency statistics
        latency_stats = {}
        for asset in self._exit_latencies:
            latencies = self._exit_latencies[asset]
            if latencies:
                latency_stats[asset] = {
                    "count": len(latencies),
                    "mean": sum(latencies) / len(latencies),
                    "min": min(latencies),
                    "max": max(latencies),
                    "p50": sorted(latencies)[len(latencies) // 2],
                    "p95": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else max(latencies),
                }
        
        return {
            "blocked_orders": {
                "by_asset": blocked_totals,
                "total": sum(t["total"] for t in blocked_totals.values()),
            },
            "exit_intents": {
                "by_asset": {
                    asset: dict(self._exit_intent_outcomes[asset])
                    for asset in self._exit_intent_outcomes
                },
                "total": sum(
                    sum(self._exit_intent_outcomes[asset].values())
                    for asset in self._exit_intent_outcomes
                ),
            },
            "exit_latencies": latency_stats,
            "expected_route_failures": {
                "count": len(self._expected_route_events),
                "recent": self._expected_route_events[-10:] if self._expected_route_events else [],
            },
            "summary": {
                "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds(),
                "total_blocked_orders": sum(t["total"] for t in blocked_totals.values()),
                "total_exit_intents": sum(
                    sum(self._exit_intent_outcomes[asset].values())
                    for asset in self._exit_intent_outcomes
                ),
                "total_expected_route_failures": len(self._expected_route_events),
            },
        }
    
    def get_dashboard_data(self) -> List[Dict[str, Any]]:
        """
        Get data formatted for the audit dashboard.
        
        Returns:
            List of dicts with dashboard schema fields
        """
        dashboard_rows = []
        
        # Add blocked order events
        for event in self._blocked_order_history[-1000:]:  # Last 1000 events
            dashboard_rows.append({
                "timestamp": event["timestamp"],
                "asset": event["asset"],
                "account_tier": "unknown",  # Would need to fetch from profile
                "environment": "production",  # Would need to fetch from config
                "signal_mode_profile": "momentum_fvg",  # Would need to fetch from profile
                "signal_mode_runtime": "momentum_fvg",  # Would need to fetch from runtime
                "entry_limit_contracts": 1,  # From profile
                "exit_limit_contracts": 1,  # From profile
                "exposure_cap": 1.0,  # From profile
                "thesis_side": event.get("thesis_side"),
                "candidate_side": None,  # Not available in blocked order context
                "order_side": event.get("order_side"),
                "selected_price_cents": event.get("selected_price_cents"),
                "limit_violation": event.get("limit_violation"),
                "routing_block_reason": event["reason"],
                "circuit_breaker_state": event.get("circuit_breaker_state"),
                "md_staleness_seconds": event.get("md_staleness_seconds"),
                "exit_liveness_state": event.get("exit_liveness_state"),
                "event_type": "blocked_order",
            })
        
        # Add exit intent events with outcomes
        for event in self._exit_intent_history[-1000:]:
            dashboard_rows.append({
                "timestamp": event["timestamp"],
                "asset": event["asset"],
                "account_tier": "unknown",
                "environment": "production",
                "signal_mode_profile": "momentum_fvg",
                "signal_mode_runtime": "momentum_fvg",
                "entry_limit_contracts": 1,
                "exit_limit_contracts": 1,
                "exposure_cap": 1.0,
                "thesis_side": event["thesis_side"],
                "candidate_side": None,
                "order_side": None,
                "selected_price_cents": event.get("intent_price_cents"),
                "limit_violation": None,
                "routing_block_reason": None,
                "circuit_breaker_state": None,
                "md_staleness_seconds": None,
                "exit_liveness_state": event.get("outcome"),
                "event_type": "exit_intent",
                "position_size": event["position_size"],
                "exit_count": event["exit_count"],
                "latency_seconds": event.get("latency_seconds"),
            })
        
        return dashboard_rows
    
    def check_thresholds(
        self,
        blocked_order_threshold: int = 10,
        exit_failure_threshold: int = 5,
        expected_route_failure_threshold: int = 3,
    ) -> Dict[str, Any]:
        """
        Check if metrics exceed alert thresholds.
        
        Args:
            blocked_order_threshold: Alert threshold for blocked orders per asset
            exit_failure_threshold: Alert threshold for exit failures per asset
            expected_route_failure_threshold: Alert threshold for expected route failures
            
        Returns:
            Dict with threshold check results and any alerts
        """
        alerts = []
        metrics = self.get_metrics()
        
        # Check blocked order thresholds
        for asset, totals in metrics["blocked_orders"]["by_asset"].items():
            if totals["total"] >= blocked_order_threshold:
                alerts.append({
                    "type": "blocked_order_threshold",
                    "asset": asset,
                    "count": totals["total"],
                    "threshold": blocked_order_threshold,
                    "severity": "critical" if totals["total"] >= blocked_order_threshold * 2 else "warning",
                    "details": totals,
                })
        
        # Check exit failure thresholds
        for asset, outcomes in metrics["exit_intents"]["by_asset"].items():
            failures = outcomes.get("failed", 0) + outcomes.get("blocked", 0) + outcomes.get("timeout", 0)
            if failures >= exit_failure_threshold:
                alerts.append({
                    "type": "exit_failure_threshold",
                    "asset": asset,
                    "count": failures,
                    "threshold": exit_failure_threshold,
                    "severity": "critical" if failures >= exit_failure_threshold * 2 else "warning",
                    "details": outcomes,
                })
        
        # Check expected route failure threshold
        expected_route_count = metrics["expected_route_failures"]["count"]
        if expected_route_count >= expected_route_failure_threshold:
            alerts.append({
                "type": "expected_route_failure_threshold",
                "count": expected_route_count,
                "threshold": expected_route_failure_threshold,
                "severity": "critical",
                "recent_events": metrics["expected_route_failures"]["recent"],
            })
        
        return {
            "alerts": alerts,
            "alert_count": len(alerts),
            "has_critical_alerts": any(a["severity"] == "critical" for a in alerts),
        }
    
    def reset_metrics(self) -> None:
        """Reset all metrics (use with caution, typically only after manual intervention)."""
        logger.warning("[AUDIT-ANOMALY-MONITOR] Resetting all metrics - manual intervention required")
        self._blocked_orders.clear()
        self._exit_intents.clear()
        self._exit_intent_outcomes.clear()
        self._expected_route_events.clear()
        self._exit_latencies.clear()
        self._blocked_order_history.clear()
        self._exit_intent_history.clear()
        self._start_time = datetime.now(timezone.utc)


# Global singleton instance
_monitor: Optional[AuditAnomalyMonitor] = None


def get_audit_anomaly_monitor(max_history_size: int = 10000) -> AuditAnomalyMonitor:
    """Get the global audit anomaly monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = AuditAnomalyMonitor(max_history_size=max_history_size)
    return _monitor
