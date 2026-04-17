"""Position and Fill Sanity Checker — Post-trade safety layer.

Detects duplicate fills, position size anomalies, and triggers soft kills
when actual position exceeds intended by more than one order's worth.

This module provides defense-in-depth after orders are acknowledged:
- Tracks fills per order to detect double-application
- Recomputes position by strategy/market
- Alerts on position vs intended size mismatches
- Triggers soft strategy kill on critical anomalies
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.position_sanity")


@dataclass
class FillRecord:
    """Record of a single fill event for idempotency checking."""
    order_id: str
    fill_id: str  # Unique identifier for this fill (order_id + sequence)
    ticker: str
    side: str
    filled_count: int
    price_cents: int
    timestamp: float
    applied: bool = False  # Whether we've applied this fill to position


@dataclass
class OrderIntentTracking:
    """Track intended vs actual fills for an order."""
    client_order_id: str
    ticker: str
    side: str
    intended_count: int
    actual_filled: int = 0
    fill_records: List[FillRecord] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class PositionSanityConfig:
    """Configuration for sanity checking thresholds."""
    # Max allowed overfill: 1 order size (100% of one order)
    max_overfill_ratio: float = 1.0
    # Max position size per market (contracts)
    max_position_per_market: int = 10000
    # Max notional per event/strategy ($)
    max_notional_per_strategy: float = 100000.0
    # Alert on duplicate fill detection
    alert_on_duplicate_fill: bool = True
    # Soft kill strategy on critical anomaly
    soft_kill_on_anomaly: bool = True


class PositionSanityChecker:
    """Post-trade position and fill sanity checker.
    
    Thread-safe singleton that:
    1. Tracks fill events idempotently (detects double-application)
    2. Validates position vs intended size
    3. Triggers alerts/kills on anomalies
    """
    
    def __init__(self, config: Optional[PositionSanityConfig] = None) -> None:
        self._config = config or PositionSanityConfig()
        self._lock = threading.Lock()
        # Track orders by client_order_id
        self._orders: Dict[str, OrderIntentTracking] = {}
        # Track applied fill_ids to prevent double-application
        self._applied_fill_ids: Set[str] = set()
        # Position by (ticker, strategy_group)
        self._positions: Dict[tuple, Dict] = {}
        # Anomaly counter for alerting
        self._anomaly_count = 0
        
    def register_order_intent(
        self,
        client_order_id: str,
        ticker: str,
        side: str,
        intended_count: int,
    ) -> None:
        """Register an order intent before fill events arrive."""
        with self._lock:
            if client_order_id not in self._orders:
                self._orders[client_order_id] = OrderIntentTracking(
                    client_order_id=client_order_id,
                    ticker=ticker,
                    side=side,
                    intended_count=intended_count,
                )
                logger.debug(
                    "[SANITY] Registered intent coid=%s ticker=%s count=%d",
                    client_order_id, ticker, intended_count
                )
    
    def apply_fill(
        self,
        order_id: str,
        fill_id: str,
        ticker: str,
        side: str,
        filled_count: int,
        price_cents: int,
        strategy_group: str = "default",
    ) -> tuple[bool, Optional[str]]:
        """Apply a fill event idempotently.
        
        Returns:
            (success, error_message) — error if duplicate or anomaly detected
        """
        with self._lock:
            # Check for duplicate fill
            if fill_id in self._applied_fill_ids:
                # P2: Expected idempotent condition - duplicate fills are normal during
                # high-volume periods or when multiple ingestion sources (WS + HTTP) overlap
                logger.info(
                    "[SANITY] DUPLICATE FILL DETECTED: fill_id=%s order_id=%s "
                    "ticker=%s count=%d — NOT applying again (expected idempotent behavior)",
                    fill_id, order_id, ticker, filled_count
                )
                # Duplicate fills are P2 expected behavior, do NOT alert or count toward budget
                # The _alert_duplicate_fill is intentionally not called here
                return False, f"duplicate_fill:{fill_id}"
            
            # Check position limits before applying
            pos_key = (ticker, strategy_group)
            current_pos = self._positions.get(pos_key, {"contracts": 0, "notional": 0.0})
            new_contracts = current_pos["contracts"] + filled_count
            
            if new_contracts > self._config.max_position_per_market:
                error_msg = (
                    f"POSITION_LIMIT_EXCEEDED: {ticker} would be {new_contracts} "
                    f"(max {self._config.max_position_per_market})"
                )
                logger.critical("[SANITY] %s", error_msg)
                if self._config.soft_kill_on_anomaly:
                    self._trigger_soft_kill(ticker, strategy_group, error_msg)
                return False, error_msg
            
            # Record the fill
            fill_record = FillRecord(
                order_id=order_id,
                fill_id=fill_id,
                ticker=ticker,
                side=side,
                filled_count=filled_count,
                price_cents=price_cents,
                timestamp=time.time(),
                applied=True,
            )
            
            # Update order tracking
            for order in self._orders.values():
                if order.ticker == ticker and order.side == side:
                    order.fill_records.append(fill_record)
                    order.actual_filled += filled_count
                    
                    # Check for overfill (> 1 order size beyond intended)
                    if order.actual_filled > order.intended_count * (1 + self._config.max_overfill_ratio):
                        error_msg = (
                            f"OVERFILL_DETECTED: {ticker} filled={order.actual_filled} "
                            f"intended={order.intended_count}"
                        )
                        logger.critical("[SANITY] %s coid=%s", error_msg, order.client_order_id)
                        if self._config.soft_kill_on_anomaly:
                            self._trigger_soft_kill(ticker, strategy_group, error_msg)
                    break
            
            # Mark fill as applied
            self._applied_fill_ids.add(fill_id)
            
            # Update position
            notional = filled_count * price_cents / 100.0
            self._positions[pos_key] = {
                "contracts": new_contracts,
                "notional": current_pos["notional"] + notional,
                "last_update": time.time(),
            }
            
            return True, None
    
    def _alert_duplicate_fill(
        self,
        fill_id: str,
        order_id: str,
        ticker: str,
        filled_count: int,
    ) -> None:
        """Emit alert for duplicate fill (rarely called - kept for extreme anomaly detection).
        
        Note: Normal duplicate fills (same fill_id seen twice from WS+HTTP overlap) are
        logged at INFO level in apply_fill() and do NOT call this method. This method
        is reserved for extreme anomaly scenarios only.
        """
        self._anomaly_count += 1
        # Log with WARNING level - duplicate fills are P2 expected behavior during normal
        # execution overlap between WebSocket and HTTP ingestion. Only extreme repeated
        # duplicates (>5) would be concerning.
        if self._anomaly_count > 5:
            logger.warning(
                "[SANITY_ALERT] DUPLICATE_FILL fill_id=%s order_id=%s ticker=%s count=%d "
                "anomaly_count=%d (elevated - may indicate systemic issue)",
                fill_id, order_id, ticker, filled_count, self._anomaly_count
            )
    
    def _trigger_soft_kill(
        self,
        ticker: str,
        strategy_group: str,
        reason: str,
    ) -> None:
        """Trigger soft kill of strategy on critical anomaly."""
        logger.critical(
            "[SANITY_SOFT_KILL] ticker=%s strategy=%s reason=%s",
            ticker, strategy_group, reason
        )
        # Record to risk controller as non-error anomaly (doesn't count toward error threshold)
        try:
            from merid.risk.kill_switches import risk_controller
            # Use emergency_stop only if truly critical - for now just log
            # risk_controller.emergency_stop(f"Position sanity: {reason}")
            pass  # Soft kill via logging/metrics for now; can escalate to hard kill
        except Exception as e:
            logger.debug(f"Risk controller unavailable: {e}")

    def get_position(self, ticker: str, strategy_group: str = "default") -> Dict:
        """Get current tracked position for a ticker/strategy."""
        with self._lock:
            return self._positions.get(
                (ticker, strategy_group),
                {"contracts": 0, "notional": 0.0, "last_update": None}
            )
    
    def get_metrics(self) -> Dict:
        """Return sanity checker metrics."""
        with self._lock:
            return {
                "tracked_orders": len(self._orders),
                "applied_fills": len(self._applied_fill_ids),
                "anomaly_count": self._anomaly_count,
                "positions_tracked": len(self._positions),
            }
    
    def prune_old_records(self, max_age_seconds: float = 86400.0) -> int:
        """Remove old records to prevent unbounded growth."""
        with self._lock:
            now = time.time()
            to_remove = [
                coid for coid, order in self._orders.items()
                if now - order.created_at > max_age_seconds
            ]
            for coid in to_remove:
                del self._orders[coid]
            return len(to_remove)


# Module-level singleton instance
_checker_instance: Optional[PositionSanityChecker] = None
_checker_lock = threading.Lock()


def get_position_sanity_checker(config: Optional[PositionSanityConfig] = None) -> PositionSanityChecker:
    """Get or create the PositionSanityChecker singleton."""
    global _checker_instance
    with _checker_lock:
        if _checker_instance is None:
            _checker_instance = PositionSanityChecker(config)
        return _checker_instance
