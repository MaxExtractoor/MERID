"""Round-trip monitor for coherent risk contract enforcement.

This module tracks round trips (open→close per market/asset) and ensures:
- Entry and exit are linked to the same risk contract
- Realized losses don't exceed planned SL
- Exit reasons match the original policy (SL/TP/trailing/time vs manual)
- Round-trip frequency doesn't indicate excessive churning

Key features:
- Logs each entry and exit with risk contract metadata
- Computes per-asset and per-tier metrics
- Raises alerts for manual overrides, SL violations, excessive round trips
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Set
from collections import defaultdict
import time

logger = logging.getLogger(__name__)


@dataclass
class RoundTripRecord:
    """Record of a complete round trip (entry → exit)."""
    asset: str
    ticker: str
    entry_intent_id: str
    exit_intent_id: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price_cents: int
    exit_price_cents: int
    count: int
    action: str  # "buy" or "sell"
    risk_tier: str
    window_resolution_id: str
    exit_policy_id: str
    planned_sl_price_cents: Optional[int] = None
    planned_tp_price_cents: Optional[int] = None
    max_hold_seconds: int = 600
    actual_exit_reason: str = "unknown"  # "sl", "tp", "trailing", "time", "manual"
    realized_pnl_cents: int = 0
    realized_hold_seconds: float = 0.0
    
    # INTENT VERIFICATION: Full hash chain for end-to-end audit trail
    source_signal_id: Optional[str] = None  # Signal ID from AgentSignal/SignalSnapshot
    source_signal_hash: Optional[str] = None  # Hash of original signal from SignalSnapshot
    entry_intent_hash: Optional[str] = None  # Hash of entry intent's core executable fields
    exit_intent_hash: Optional[str] = None  # Hash of exit intent's core executable fields
    fill_chain_hash: Optional[str] = None  # Hash linking signal_hash -> intent_hash -> execution_report_hash
    
    def to_dict(self) -> Dict:
        """Convert to dict for logging/serialization."""
        return {
            "asset": self.asset,
            "ticker": self.ticker,
            "entry_intent_id": self.entry_intent_id,
            "exit_intent_id": self.exit_intent_id,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "exit_timestamp": self.exit_timestamp.isoformat(),
            "entry_price_cents": self.entry_price_cents,
            "exit_price_cents": self.exit_price_cents,
            "count": self.count,
            "action": self.action,
            "risk_tier": self.risk_tier,
            "window_resolution_id": self.window_resolution_id,
            "exit_policy_id": self.exit_policy_id,
            "planned_sl_price_cents": self.planned_sl_price_cents,
            "planned_tp_price_cents": self.planned_tp_price_cents,
            "max_hold_seconds": self.max_hold_seconds,
            "actual_exit_reason": self.actual_exit_reason,
            "realized_pnl_cents": self.realized_pnl_cents,
            "realized_hold_seconds": self.realized_hold_seconds,
            # INTENT VERIFICATION: Hash chain fields
            "source_signal_id": self.source_signal_id,
            "source_signal_hash": self.source_signal_hash,
            "entry_intent_hash": self.entry_intent_hash,
            "exit_intent_hash": self.exit_intent_hash,
            "fill_chain_hash": self.fill_chain_hash,
        }


@dataclass
class EntryRecord:
    """Record of an entry order waiting for its exit."""
    intent_id: str
    ticker: str
    asset: str
    timestamp: datetime
    price_cents: int
    count: int
    action: str
    risk_tier: str
    window_resolution_id: str
    exit_policy_id: str
    planned_sl_price_cents: Optional[int] = None
    planned_tp_price_cents: Optional[int] = None
    max_hold_seconds: int = 600
    # Phase 5.4: Raw logit for probability calibration
    raw_logit: Optional[float] = None
    # Phase 5.4: Agent ID for outcome recording
    agent_id: Optional[str] = None


@dataclass
class AssetMetrics:
    """Metrics per asset for round-trip analysis."""
    total_round_trips: int = 0
    total_pnl_cents: int = 0
    avg_pnl_cents: float = 0.0
    avg_hold_seconds: float = 0.0
    max_drawdown_cents: int = 0
    sl_hit_count: int = 0
    tp_hit_count: int = 0
    time_exit_count: int = 0
    manual_exit_count: int = 0
    trailing_exit_count: int = 0
    sl_violation_count: int = 0  # Loss > planned SL
    round_trips_today: int = 0
    round_trips_per_day: Dict[str, int] = field(default_factory=dict)


@dataclass
class Alert:
    """Alert for risk contract violations."""
    timestamp: datetime
    alert_type: str  # "manual_override", "sl_violation", "excessive_round_trips", "churn"
    asset: str
    ticker: Optional[str] = None
    details: Dict = field(default_factory=dict)
    severity: str = "warning"  # "info", "warning", "critical"


class RoundTripMonitor:
    """Monitors round trips and enforces risk contract compliance."""
    
    def __init__(self, max_round_trips_per_day: int = 20, sl_violation_threshold_cents: int = 5):
        """Initialize the round-trip monitor.
        
        Args:
            max_round_trips_per_day: Alert if round trips exceed this per asset per day
            sl_violation_threshold_cents: Alert if loss exceeds SL by this many cents
        """
        self.max_round_trips_per_day = max_round_trips_per_day
        self.sl_violation_threshold = sl_violation_threshold_cents
        
        self._entries: Dict[str, EntryRecord] = {}  # intent_id -> EntryRecord
        self._round_trips: List[RoundTripRecord] = []
        self._asset_metrics: Dict[str, AssetMetrics] = defaultdict(AssetMetrics)
        self._alerts: List[Alert] = []
        
        # Phase 5.4: Callback for outcome recording
        self._outcome_callback: Optional[callable] = None
    
    def set_outcome_callback(self, callback: callable) -> None:
        """Set callback for recording calibration outcomes.
        
        Args:
            callback: Function with signature (agent_id: str, logit: float, outcome: int) -> None
        """
        self._outcome_callback = callback
        
    def record_entry(self, record: EntryRecord) -> None:
        """Record an entry order.
        
        Args:
            record: EntryRecord with order details and risk contract
        """
        self._entries[record.intent_id] = record
        logger.info(
            f"[ROUND_TRIP] Entry recorded: intent_id={record.intent_id} "
            f"ticker={record.ticker} asset={record.asset} risk_tier={record.risk_tier}"
        )
    
    def record_exit(
        self,
        exit_intent_id: str,
        entry_intent_id: str,
        exit_price_cents: int,
        exit_reason: str,
        exit_timestamp: Optional[datetime] = None,
    ) -> Optional[RoundTripRecord]:
        """Record an exit and complete the round trip.
        
        Args:
            exit_intent_id: Intent ID of the exit order
            entry_intent_id: Intent ID of the matching entry order
            exit_price_cents: Price at which position was closed
            exit_reason: Reason for exit ("sl", "tp", "trailing", "time", "manual")
            exit_timestamp: Timestamp of exit (defaults to now)
        
        Returns:
            RoundTripRecord if entry found, None otherwise
        """
        if entry_intent_id not in self._entries:
            logger.warning(f"[ROUND_TRIP] Entry not found for exit: {entry_intent_id}")
            return None
        
        entry = self._entries[entry_intent_id]
        if exit_timestamp is None:
            exit_timestamp = datetime.utcnow()
        
        # Calculate PnL
        if entry.action == "buy":
            pnl_cents = (exit_price_cents - entry.price_cents) * entry.count
        else:
            pnl_cents = (entry.price_cents - exit_price_cents) * entry.count
        
        hold_seconds = (exit_timestamp - entry.timestamp).total_seconds()
        
        # Check for SL violation
        sl_violation = False
        if entry.planned_sl_price_cents is not None:
            if entry.action == "buy":
                # For long: SL is below entry, violation if exit below SL
                sl_violation = exit_price_cents < (entry.planned_sl_price_cents - self.sl_violation_threshold)
            else:
                # For short: SL is above entry, violation if exit above SL
                sl_violation = exit_price_cents > (entry.planned_sl_price_cents + self.sl_violation_threshold)
        
        # Create round trip record
        round_trip = RoundTripRecord(
            asset=entry.asset,
            ticker=entry.ticker,
            entry_intent_id=entry.intent_id,
            exit_intent_id=exit_intent_id,
            entry_timestamp=entry.timestamp,
            exit_timestamp=exit_timestamp,
            entry_price_cents=entry.price_cents,
            exit_price_cents=exit_price_cents,
            count=entry.count,
            action=entry.action,
            risk_tier=entry.risk_tier,
            window_resolution_id=entry.window_resolution_id,
            exit_policy_id=entry.exit_policy_id,
            planned_sl_price_cents=entry.planned_sl_price_cents,
            planned_tp_price_cents=entry.planned_tp_price_cents,
            max_hold_seconds=entry.max_hold_seconds,
            actual_exit_reason=exit_reason,
            realized_pnl_cents=pnl_cents,
            realized_hold_seconds=hold_seconds,
        )
        
        # Update metrics
        self._round_trips.append(round_trip)
        self._update_metrics(round_trip, sl_violation)
        
        # Phase 5.4: Record outcome for probability calibration
        if entry.raw_logit is not None and entry.agent_id and self._outcome_callback:
            try:
                # Determine binary outcome: 1 if profitable, 0 if loss
                outcome = 1 if pnl_cents > 0 else 0
                
                # Call the callback to record outcome
                self._outcome_callback(entry.agent_id, entry.raw_logit, outcome)
                logger.info(
                    "[CALIBRATION-OUTCOME] asset=%s agent=%s logit=%.4f outcome=%d pnl=%dc",
                    entry.asset, entry.agent_id, entry.raw_logit, outcome, pnl_cents
                )
            except Exception as cal_err:
                logger.warning("[CALIBRATION-OUTCOME] Failed to record outcome for %s: %s", entry.asset, cal_err)
        
        # Generate alerts
        self._check_alerts(round_trip, sl_violation)
        
        # Remove entry
        del self._entries[entry_intent_id]
        
        logger.info(
            f"[ROUND_TRIP] Exit recorded: ticker={entry.ticker} "
            f"entry_id={entry_intent_id} exit_id={exit_intent_id} "
            f"pnl={pnl_cents}c reason={exit_reason} hold={hold_seconds:.1f}s"
        )
        
        return round_trip
    
    def _update_metrics(self, round_trip: RoundTripRecord, sl_violation: bool) -> None:
        """Update asset metrics for a round trip.
        
        Args:
            round_trip: RoundTripRecord to update metrics with
            sl_violation: Whether this was an SL violation
        """
        asset = round_trip.asset
        metrics = self._asset_metrics[asset]
        
        metrics.total_round_trips += 1
        metrics.total_pnl_cents += round_trip.realized_pnl_cents
        metrics.avg_pnl_cents = metrics.total_pnl_cents / metrics.total_round_trips
        
        # Update average hold time
        total_hold = metrics.avg_hold_seconds * (metrics.total_round_trips - 1)
        metrics.avg_hold_seconds = (total_hold + round_trip.realized_hold_seconds) / metrics.total_round_trips
        
        # Update max drawdown (worst loss)
        if round_trip.realized_pnl_cents < 0:
            abs_loss = abs(round_trip.realized_pnl_cents)
            if abs_loss > metrics.max_drawdown_cents:
                metrics.max_drawdown_cents = abs_loss
        
        # Update exit reason counts
        if round_trip.actual_exit_reason == "sl":
            metrics.sl_hit_count += 1
        elif round_trip.actual_exit_reason == "tp":
            metrics.tp_hit_count += 1
        elif round_trip.actual_exit_reason == "time":
            metrics.time_exit_count += 1
        elif round_trip.actual_exit_reason == "manual":
            metrics.manual_exit_count += 1
        elif round_trip.actual_exit_reason == "trailing":
            metrics.trailing_exit_count += 1
        
        # Update SL violation count
        if sl_violation:
            metrics.sl_violation_count += 1
        
        # Update daily round trip count
        date_str = round_trip.entry_timestamp.strftime("%Y-%m-%d")
        metrics.round_trips_per_day[date_str] = metrics.round_trips_per_day.get(date_str, 0) + 1
        if date_str == datetime.utcnow().strftime("%Y-%m-%d"):
            metrics.round_trips_today = metrics.round_trips_per_day[date_str]
    
    def _check_alerts(self, round_trip: RoundTripRecord, sl_violation: bool) -> None:
        """Check for risk contract violations and generate alerts.
        
        Args:
            round_trip: RoundTripRecord to check
            sl_violation: Whether this was an SL violation
        """
        # Alert 1: Manual exit override
        if round_trip.actual_exit_reason == "manual":
            self._alerts.append(Alert(
                timestamp=datetime.utcnow(),
                alert_type="manual_override",
                asset=round_trip.asset,
                ticker=round_trip.ticker,
                details={
                    "entry_intent_id": round_trip.entry_intent_id,
                    "exit_intent_id": round_trip.exit_intent_id,
                    "risk_tier": round_trip.risk_tier,
                    "planned_exit": "sl/tp/trailing/time",
                    "actual_exit": "manual",
                },
                severity="warning",
            ))
            logger.warning(
                f"[ROUND_TRIP_ALERT] Manual override: ticker={round_trip.ticker} "
                f"risk_tier={round_trip.risk_tier}"
            )
        
        # Alert 2: SL violation
        if sl_violation:
            self._alerts.append(Alert(
                timestamp=datetime.utcnow(),
                alert_type="sl_violation",
                asset=round_trip.asset,
                ticker=round_trip.ticker,
                details={
                    "entry_intent_id": round_trip.entry_intent_id,
                    "exit_intent_id": round_trip.exit_intent_id,
                    "planned_sl": round_trip.planned_sl_price_cents,
                    "actual_exit": round_trip.exit_price_cents,
                    "violation_cents": abs(round_trip.exit_price_cents - round_trip.planned_sl_price_cents),
                },
                severity="critical",
            ))
            logger.error(
                f"[ROUND_TRIP_ALERT] SL violation: ticker={round_trip.ticker} "
                f"planned={round_trip.planned_sl_price_cents}c actual={round_trip.exit_price_cents}c"
            )
        
        # Alert 3: Excessive round trips
        metrics = self._asset_metrics[round_trip.asset]
        if metrics.round_trips_today > self.max_round_trips_per_day:
            self._alerts.append(Alert(
                timestamp=datetime.utcnow(),
                alert_type="excessive_round_trips",
                asset=round_trip.asset,
                details={
                    "round_trips_today": metrics.round_trips_today,
                    "max_allowed": self.max_round_trips_per_day,
                    "date": datetime.utcnow().strftime("%Y-%m-%d"),
                },
                severity="warning",
            ))
            logger.warning(
                f"[ROUND_TRIP_ALERT] Excessive round trips: asset={round_trip.asset} "
                f"count={metrics.round_trips_today} max={self.max_round_trips_per_day}"
            )
        
        # Alert 4: Churn detection (high manual exit rate)
        if metrics.total_round_trips > 10:
            manual_rate = metrics.manual_exit_count / metrics.total_round_trips
            if manual_rate > 0.5:  # More than 50% manual exits
                self._alerts.append(Alert(
                    timestamp=datetime.utcnow(),
                    alert_type="churn",
                    asset=round_trip.asset,
                    details={
                        "manual_exit_rate": manual_rate,
                        "manual_count": metrics.manual_exit_count,
                        "total_round_trips": metrics.total_round_trips,
                    },
                    severity="warning",
                ))
                logger.warning(
                    f"[ROUND_TRIP_ALERT] Churn detected: asset={round_trip.asset} "
                    f"manual_exit_rate={manual_rate:.2%}"
                )
    
    def get_asset_metrics(self, asset: str) -> Optional[AssetMetrics]:
        """Get metrics for a specific asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
        
        Returns:
            AssetMetrics or None if no data
        """
        return self._asset_metrics.get(asset)
    
    def get_all_metrics(self) -> Dict[str, AssetMetrics]:
        """Get metrics for all assets.
        
        Returns:
            Dict mapping asset to AssetMetrics
        """
        return dict(self._asset_metrics)
    
    def get_recent_round_trips(self, limit: int = 100) -> List[RoundTripRecord]:
        """Get recent round trips.
        
        Args:
            limit: Maximum number of round trips to return
        
        Returns:
            List of RoundTripRecord (most recent first)
        """
        return sorted(self._round_trips, key=lambda r: r.exit_timestamp, reverse=True)[:limit]
    
    def get_recent_alerts(self, limit: int = 50) -> List[Alert]:
        """Get recent alerts.
        
        Args:
            limit: Maximum number of alerts to return
        
        Returns:
            List of Alert (most recent first)
        """
        return sorted(self._alerts, key=lambda a: a.timestamp, reverse=True)[:limit]
    
    def get_summary(self) -> Dict:
        """Get summary statistics.
        
        Returns:
            Dict with summary stats
        """
        total_round_trips = len(self._round_trips)
        total_pnl_cents = sum(rt.realized_pnl_cents for rt in self._round_trips)
        total_alerts = len(self._alerts)
        
        return {
            "total_round_trips": total_round_trips,
            "total_pnl_cents": total_pnl_cents,
            "avg_pnl_cents": total_pnl_cents / total_round_trips if total_round_trips > 0 else 0,
            "pending_entries": len(self._entries),
            "total_alerts": total_alerts,
            "assets_tracked": len(self._asset_metrics),
        }


# Global singleton instance
_monitor_instance: Optional[RoundTripMonitor] = None


def get_round_trip_monitor() -> RoundTripMonitor:
    """Get the global round-trip monitor singleton.
    
    Returns:
        RoundTripMonitor instance
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = RoundTripMonitor()
    return _monitor_instance
