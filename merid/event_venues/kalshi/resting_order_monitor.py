"""Dynamic resting order monitor for coherent risk contract enforcement.

This module periodically re-checks resting/limit orders against current
market signals (regime, volatility, model quality) and cancels or adjusts
orders that no longer satisfy the original risk contract.

Key features:
- Re-evaluates WindowResolution for each resting order
- Cancels orders when regime flips to defensive/halt
- Cancels orders when model quality degrades below threshold
- Cancels orders near expiry (pre-expiry cancel rule)
- Logs all dynamic cancellations for audit trail
- Health monitoring for loop liveness and data quality
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set

logger = logging.getLogger(__name__)

# Pre-expiry cancel rule: cancel resting orders when time to expiry below threshold
PRE_EXPIRY_CANCEL_THRESHOLD_MIN = 2  # 2 minutes before settlement

# Max hold time for 15m markets: cancel unfilled limit orders after 2-3 minutes
# This prevents stale orders from resting too long in fast-moving 15m markets
MAX_HOLD_SECONDS_15M = 180  # 3 minutes for 15m markets

# Status constants for Kalshi portfolio endpoint normalization
TERMINAL_STATUSES = {"filled", "canceled", "expired", "rejected", "executed"}
RESTING_STATUSES = {"resting", "open", "partially_filled"}


def _normalize_status(raw_status: str) -> str:
    """Normalize Kalshi API status to internal vocabulary.
    
    Args:
        raw_status: Status string from Kalshi portfolio endpoint
        
    Returns:
        Normalized status string
    """
    status = (raw_status or "").lower()
    
    # Map known Kalshi statuses to internal vocabulary
    status_mapping = {
        "resting": "resting",
        "open": "open",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "executed": "filled",  # Kalshi may use "executed" synonymously with "filled"
        "canceled": "canceled",
        "cancelled": "canceled",  # Handle both spellings
        "expired": "expired",
        "rejected": "rejected",
    }
    
    return status_mapping.get(status, status)


@dataclass
class RestingOrderRecord:
    """Record of a resting order with its original risk contract.
    
    Primary key is (venue, kalshi_order_id) - intent_id is only for diagnostics.
    All state transitions come from Kalshi's portfolio view, not intent inference.
    """
    kalshi_order_id: str  # Server-side order ID from Kalshi (canonical handle)
    venue: str = "kalshi"
    ticker: str = ""
    side: str = ""
    action: str = ""
    original_size: int = 0
    remaining_size: int = 0  # Tracked from portfolio endpoint, not calculated
    filled_size: int = 0  # Cumulative filled size (original_size - remaining_size)
    price_cents: int = 0
    created_at: datetime = None
    asset: str = ""
    
    # Risk contract linkage
    window_resolution_id: str = ""
    exit_policy_id: str = ""
    risk_tier: str = ""
    max_hold_seconds: int = 600
    
    # Kalshi API fields for enforcement
    time_in_force: str = "gtc"  # Only "good_till_canceled" orders can rest
    order_expiration_ts: Optional[int] = None  # Unix timestamp from Kalshi
    stp: str = "taker_at_cross"  # Self-trade prevention: "taker_at_cross" or "maker"
    
    # Diagnostic fields (not primary keys)
    intent_id: str = ""  # For reconciling with original OrderIntent
    client_order_id: Optional[str] = None  # For idempotency checks
    
    # Original signal context
    original_minutes_to_expiry: Optional[float] = None
    original_edge_pct: Optional[float] = None
    
    # Status tracking (from portfolio endpoint)
    status: str = ""  # Set at registration time, not as default
    last_sync_at: Optional[datetime] = None
    missing_data_count: int = 0  # Count consecutive "no data" responses
    
    # Health monitoring
    last_heartbeat: Optional[datetime] = None  # Last successful poll/sync
    consecutive_sync_failures: int = 0  # Count consecutive sync failures
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.remaining_size == 0:
            self.remaining_size = self.original_size


@dataclass
class RecheckResult:
    """Result of re-checking a resting order."""
    intent_id: str
    ticker: str
    action: str  # "keep", "cancel", "adjust"
    reason: str
    current_regime: Optional[str] = None
    current_vol_tier: Optional[str] = None
    model_quality_good: Optional[bool] = None


class RestingOrderMonitor:
    """Monitors and dynamically re-checks resting orders against current signals.
    
    Primary key is (venue, kalshi_order_id) - all state comes from Kalshi portfolio view.
    """
    
    def __init__(self, recheck_interval_seconds: int = 60, poll_interval_seconds: int = 30):
        """Initialize the resting order monitor.
        
        Args:
            recheck_interval_seconds: How often to re-check resting orders against signals (default 60s)
            poll_interval_seconds: How often to poll Kalshi portfolio for status (default 30s)
        """
        self.recheck_interval = recheck_interval_seconds
        self.poll_interval = poll_interval_seconds
        # Primary key is (venue, kalshi_order_id)
        self._resting_orders: Dict[str, RestingOrderRecord] = {}  # kalshi_order_id -> record
        # Secondary index for intent_id lookup
        self._intent_to_order_id: Dict[str, str] = {}  # intent_id -> kalshi_order_id
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._cancel_count = 0
        self._keep_count = 0
        self._poll_count = 0
        self._last_poll_time: Optional[datetime] = None  # Health monitoring
        
    def register_order(self, record: RestingOrderRecord) -> None:
        """Register a resting order for monitoring.
        
        Only registers if:
        - type == "limit"
        - time_in_force == "good_till_canceled"
        
        Args:
            record: RestingOrderRecord with kalshi_order_id and risk contract
        """
        # IOC/FOK filtering: only GTC orders can rest
        tif_lower = (record.time_in_force or "").lower()
        if tif_lower in ("ioc", "immediate_or_cancel", "fok", "fill_or_kill"):
            logger.debug(
                f"[RESTING_ORDER_MONITOR] Skipping IOC/FOK order: kalshi_order_id={record.kalshi_order_id} "
                f"time_in_force={record.time_in_force} - these orders never rest"
            )
            return
        
        # Assert we have the required server-side ID
        if not record.kalshi_order_id:
            logger.warning(
                f"[RESTING_ORDER_MONITOR] Cannot register order without kalshi_order_id: intent_id={record.intent_id}"
            )
            return
        
        # Detect 15m markets and set appropriate max hold time
        # 15m markets have ticker patterns like "KXBTC-15M" or contain "15M"
        if "15M" in record.ticker.upper() or "-15M" in record.ticker.upper():
            record.max_hold_seconds = MAX_HOLD_SECONDS_15M
            logger.info(
                f"[RESTING_ORDER_MONITOR] Set max_hold_seconds={MAX_HOLD_SECONDS_15M}s for 15m market: ticker={record.ticker}"
            )
        
        # Store with kalshi_order_id as primary key
        # Set initial status to "open" at registration time
        if not record.status:
            record.status = "open"
        
        self._resting_orders[record.kalshi_order_id] = record
        if record.intent_id:
            self._intent_to_order_id[record.intent_id] = record.kalshi_order_id
        
        logger.info(
            f"[RESTING_ORDER_MONITOR] Registered order: kalshi_order_id={record.kalshi_order_id} "
            f"intent_id={record.intent_id} ticker={record.ticker} risk_tier={record.risk_tier} "
            f"original_size={record.original_size} remaining_size={record.remaining_size} status={record.status} "
            f"max_hold_seconds={record.max_hold_seconds}"
        )
    
    def unregister_order(self, kalshi_order_id: str) -> None:
        """Unregister an order by server-side order_id.
        
        Args:
            kalshi_order_id: Kalshi server-side order ID to unregister
        """
        if kalshi_order_id in self._resting_orders:
            record = self._resting_orders[kalshi_order_id]
            del self._resting_orders[kalshi_order_id]
            if record.intent_id and record.intent_id in self._intent_to_order_id:
                del self._intent_to_order_id[record.intent_id]
            logger.debug(f"[RESTING_ORDER_MONITOR] Unregistered order: kalshi_order_id={kalshi_order_id}")
    
    def unregister_by_intent_id(self, intent_id: str) -> None:
        """Unregister an order by intent_id (fallback for legacy code).
        
        Args:
            intent_id: Intent ID to unregister
        """
        if intent_id in self._intent_to_order_id:
            kalshi_order_id = self._intent_to_order_id[intent_id]
            self.unregister_order(kalshi_order_id)
    
    async def _recheck_order(self, record: RestingOrderRecord) -> RecheckResult:
        """Re-check a single resting order against current signals.
        
        Args:
            record: RestingOrderRecord to re-check
        
        Returns:
            RecheckResult with action and reason
        """
        try:
            from merid.prediction.dynamic_entry_window import resolve_entry_window
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            
            # Get current regime
            regime = "normal"  # Default fallback
            try:
                from merid.signals.unified_regime_classifier import get_unified_regime_classifier
                classifier = get_unified_regime_classifier()
                state = classifier.get_current_state()
                if state:
                    regime = state.regime.value
            except Exception as e:
                logger.debug(f"[RESTING_ORDER_MONITOR] Could not get regime: {e}")
            
            # Get model quality
            model_quality_good = False
            try:
                from merid.metrics.calibration import get_calibration_store
                from merid.metrics.hit_ratio import get_hit_ratio_tracker
                
                cal_store = get_calibration_store()
                hit_tracker = get_hit_ratio_tracker()
                
                brier = cal_store.get_brier("edge_model_v1", "crypto")
                hit_stats = hit_tracker.stats
                hit_ratio = hit_stats.get("hit_ratio", 0.5)
                
                model_quality_good = (brier < 0.20 and hit_ratio > 0.55)
            except Exception as e:
                logger.debug(f"[RESTING_ORDER_MONITOR] Could not get model quality: {e}")
            
            # Re-resolve entry window
            now = datetime.utcnow()
            minutes_to_expiry = None
            if record.original_minutes_to_expiry:
                # Update based on elapsed time
                elapsed_minutes = (now - record.created_at).total_seconds() / 60.0
                minutes_to_expiry = max(0, record.original_minutes_to_expiry - elapsed_minutes)
            
            window_res = resolve_entry_window(
                asset=record.asset,
                minutes_to_expiry=minutes_to_expiry,
                edge_pct=record.original_edge_pct,
                ticker=record.ticker
            )
            
            # Check if order should be cancelled
            # 1. Defensive regime or halt
            if regime in ("defensive", "halt"):
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"regime_{regime}",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 2. Entry window no longer allowed
            if not window_res.allowed:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"window_not_allowed:{window_res.reason.value}",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 3. Model quality degraded and order was Tier A
            if record.risk_tier == "A" and not model_quality_good:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason="model_quality_degraded",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 4. Pre-expiry cancel rule: cancel resting orders near settlement
            if minutes_to_expiry is not None and minutes_to_expiry < PRE_EXPIRY_CANCEL_THRESHOLD_MIN:
                logger.warning(
                    "[RESTING-CANCEL-BEFORE-EXPIRY] ticker=%s kalshi_order_id=%s tte=%.1fmin < %dmin - cancelling resting order",
                    record.ticker, record.kalshi_order_id, minutes_to_expiry, PRE_EXPIRY_CANCEL_THRESHOLD_MIN
                )
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"pre_expiry_cancel:{minutes_to_expiry:.1f}min",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 4. Max hold time exceeded
            elapsed_seconds = (now - record.created_at).total_seconds()
            if elapsed_seconds > record.max_hold_seconds:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason="max_hold_time_exceeded",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # Keep the order
            return RecheckResult(
                intent_id=record.intent_id,
                ticker=record.ticker,
                action="keep",
                reason="still_valid",
                current_regime=regime,
                current_vol_tier=window_res.volatility_tier,
                model_quality_good=model_quality_good,
            )
            
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Re-check failed for {record.intent_id}: {e}")
            # On error, keep order to avoid spurious cancellations
            return RecheckResult(
                intent_id=record.intent_id,
                ticker=record.ticker,
                action="keep",
                reason="recheck_error",
            )
    
    async def _sync_order_status(self, record: RestingOrderRecord) -> bool:
        """Sync order status from Kalshi portfolio endpoint.
        
        This is the source of truth for order state - no state is inferred from intents.
        
        Args:
            record: RestingOrderRecord to sync
        
        Returns:
            True if order should be removed (terminal status), False otherwise
        """
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            
            client = get_kalshi_client()
            result = await client.get_order_result(record.kalshi_order_id, record.ticker)
            
            # Handle "no data" case - order may be gone or never existed
            if not result.data:
                record.missing_data_count += 1
                logger.warning(
                    f"[RESTING_ORDER_MONITOR] No order data for {record.kalshi_order_id} "
                    f"(missing_count={record.missing_data_count}) - treating as non-terminal for now"
                )
                # After 3 consecutive "no data" responses, treat as terminal
                if record.missing_data_count >= 3:
                    logger.error(
                        f"[RESTING_ORDER_MONITOR] Order {record.kalshi_order_id} has {record.missing_data_count} "
                        f"consecutive missing data responses - treating as unknown terminal, manual reconciliation needed"
                    )
                    return True
                return False
            
            # Reset missing data counter on successful data fetch
            record.missing_data_count = 0
            
            order_data = result.data
            raw_status = order_data.get("status", "")
            remaining_size = order_data.get("remaining_size", order_data.get("remaining_quantity", 0))
            
            # Normalize status to internal vocabulary
            status = _normalize_status(raw_status)
            
            old_status = record.status
            record.status = status
            record.last_sync_at = datetime.utcnow()
            
            # Always keep remaining_size in sync (even for all-at-once fills)
            record_remaining_before = record.remaining_size
            record.remaining_size = remaining_size
            
            # Update filled_size (cumulative filled amount)
            record.filled_size = record.original_size - remaining_size
            
            # Partial fill detection
            if remaining_size > 0 and record_remaining_before > remaining_size:
                fill_amount = record_remaining_before - remaining_size
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Partial fill: kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} filled={fill_amount} remaining={remaining_size} "
                    f"total_filled={record.filled_size}/{record.original_size}"
                )
                # Emit resting_order_partially_filled event to venue event stream
                logger.info(
                    f"[EVENT] resting_order_partially_filled | kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} fill_amount={fill_amount} remaining={remaining_size} "
                    f"total_filled={record.filled_size}/{record.original_size}"
                )
            
            # Terminal handling - use terminal status as primary signal
            # remaining_size == 0 is a sanity check
            if status in TERMINAL_STATUSES or remaining_size == 0:
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Order terminal: kalshi_order_id={record.kalshi_order_id} "
                    f"status={status} remaining_size={remaining_size} - removing from monitor"
                )
                # Emit filled/canceled/expired/rejected event based on status
                if status == "filled":
                    logger.info(
                        f"[EVENT] resting_order_filled | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "canceled":
                    logger.info(
                        f"[EVENT] resting_order_canceled | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "expired":
                    logger.info(
                        f"[EVENT] resting_order_expired | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "rejected":
                    logger.info(
                        f"[EVENT] resting_order_rejected | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                return True
            
            # Check expiration discrepancy - check all resting statuses, not just "open"
            if record.order_expiration_ts:
                now = int(datetime.utcnow().timestamp())
                if now >= record.order_expiration_ts and status in RESTING_STATUSES:
                    logger.error(
                        f"[RESTING_ORDER_MONITOR] EXPIRATION DISCREPANCY: kalshi_order_id={record.kalshi_order_id} "
                        f"should be expired but status={status} - manual reconciliation needed"
                    )
                    # Trigger manual reconciliation alert
                    logger.warning(
                        f"[ALERT] manual_reconciliation_needed | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} status={status} expiration_ts={record.order_expiration_ts} "
                        f"now={now} - expiration discrepancy detected"
                    )
            
            self._poll_count += 1
            return False
            
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Failed to sync order status for {record.kalshi_order_id}: {e}")
            return False
    
    async def _poll_all_orders(self) -> None:
        """Poll all resting orders from Kalshi portfolio endpoint.
        
        Uses round-robin polling with backpressure to avoid rate limits.
        """
        if not self._resting_orders:
            logger.debug("[RESTING_ORDER_MONITOR] No orders to poll")
            return
        
        logger.info(f"[RESTING_ORDER_MONITOR] Polling {len(self._resting_orders)} orders from portfolio")
        
        orders_to_remove = []
        for kalshi_order_id, record in list(self._resting_orders.items()):
            should_remove = await self._sync_order_status(record)
            if should_remove:
                orders_to_remove.append(kalshi_order_id)
        
        # Remove terminal orders
        for kalshi_order_id in orders_to_remove:
            self.unregister_order(kalshi_order_id)
        
        logger.info(
            f"[RESTING_ORDER_MONITOR] Poll complete: {len(orders_to_remove)} removed, "
            f"{len(self._resting_orders)} still resting (total_polls={self._poll_count})"
        )
    
    async def _recheck_all_orders(self) -> List[RecheckResult]:
        """Re-check all registered resting orders against current signals.
        
        This is separate from portfolio polling - it checks if orders should be
        dynamically cancelled based on regime/volatility/model quality changes.
        
        Returns:
            List of RecheckResult for each order
        """
        results = []
        for record in list(self._resting_orders.values()):
            result = await self._recheck_order(record)
            results.append(result)
            
            if result.action == "cancel":
                self._cancel_count += 1
                logger.warning(
                    f"[RESTING_ORDER_MONITOR] Cancelling order: kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} reason={result.reason}"
                )
                # Cancel the order on Kalshi
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client
                    client = get_kalshi_client()
                    await client.cancel_order(record.kalshi_order_id, record.ticker)
                except Exception as e:
                    logger.error(f"[RESTING_ORDER_MONITOR] Failed to cancel order {record.kalshi_order_id}: {e}")
                
                # Unregister cancelled order
                self.unregister_order(record.kalshi_order_id)
            else:
                self._keep_count += 1
        
        return results
    
    async def _run_loop(self) -> None:
        """Main monitoring loop for signal-based re-checks.
        
        This is separate from portfolio polling - it checks if orders should be
        dynamically cancelled based on regime/volatility/model quality changes.
        """
        while self._running:
            try:
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Re-checking {len(self._resting_orders)} orders against signals"
                )
                results = await self._recheck_all_orders()
                
                cancel_count = sum(1 for r in results if r.action == "cancel")
                keep_count = sum(1 for r in results if r.action == "keep")
                
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Re-check complete: {cancel_count} cancelled, "
                    f"{keep_count} kept (total_cancelled={self._cancel_count}, total_kept={self._keep_count})"
                )
                
            except Exception as e:
                logger.error(f"[RESTING_ORDER_MONITOR] Re-check loop error: {e}")
            
            await asyncio.sleep(self.recheck_interval)
    
    async def _poll_loop(self) -> None:
        """Portfolio polling loop for status sync.
        
        This is the source of truth for order state - polls Kalshi's portfolio
        endpoints to detect fills, cancels, expirations, and partial fills.
        """
        while self._running:
            try:
                self._last_poll_time = datetime.utcnow()
                await self._poll_all_orders()
                self._poll_count += 1
            except Exception as e:
                logger.error(f"[RESTING_ORDER_MONITOR] Poll loop error: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    async def start(self) -> None:
        """Start the resting order monitor.
        
        Starts both the portfolio polling loop and the signal re-check loop.
        """
        if self._running:
            logger.warning("[RESTING_ORDER_MONITOR] Already running")
            return
        
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[RESTING_ORDER_MONITOR] Started (poll_interval={self.poll_interval}s, "
            f"recheck_interval={self.recheck_interval}s)"
        )
    
    async def stop(self) -> None:
        """Stop the resting order monitor."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel both tasks
        for task in [self._task, self._poll_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._task = None
        self._poll_task = None
        
        logger.info("[RESTING_ORDER_MONITOR] Stopped")
    
    def get_stats(self) -> Dict:
        """Get monitor statistics.
        
        Returns:
            Dict with current stats
        """
        return {
            "running": self._running,
            "resting_orders_count": len(self._resting_orders),
            "cancel_count": self._cancel_count,
            "keep_count": self._keep_count,
            "poll_count": self._poll_count,
            "recheck_interval_seconds": self.recheck_interval,
            "poll_interval_seconds": self.poll_interval,
            "last_poll_time": self._last_poll_time,
            "orders_with_missing_data": self._count_orders_with_missing_data(),
        }
    
    def _count_orders_with_missing_data(self) -> int:
        """Count orders with missing_data_count exceeding threshold."""
        MISSING_DATA_THRESHOLD = 3  # Alert after 3 consecutive failures
        return sum(
            1 for order in self._resting_orders.values()
            if order.missing_data_count >= MISSING_DATA_THRESHOLD
        )
    
    def check_health(self) -> Dict:
        """Check health of the resting order monitor.
        
        Returns:
            Dict with health status and any issues found
        """
        issues = []
        
        # Check if poll loop is running
        if self._running:
            if self._last_poll_time:
                time_since_last_poll = (datetime.utcnow() - self._last_poll_time).total_seconds()
                # Alert if no poll in 2x the poll interval
                if time_since_last_poll > self.poll_interval * 2:
                    issues.append(
                        f"Poll loop stale: last poll {time_since_last_poll:.0f}s ago "
                        f">(threshold: {self.poll_interval * 2:.0f}s)"
                    )
            else:
                issues.append("Poll loop running but no polls recorded yet")
        else:
            issues.append("Poll loop not running")
        
        # Check for orders with excessive missing data
        missing_data_orders = self._count_orders_with_missing_data()
        if missing_data_orders > 0:
            issues.append(
                f"{missing_data_orders} orders with missing_data_count >= 3 "
                f"(portfolio polling failures)"
            )
        
        # Check for orders with consecutive sync failures
        sync_failure_orders = sum(
            1 for order in self._resting_orders.values()
            if order.consecutive_sync_failures >= 3
        )
        if sync_failure_orders > 0:
            issues.append(
                f"{sync_failure_orders} orders with consecutive_sync_failures >= 3"
            )
        
        healthy = len(issues) == 0
        
        if not healthy:
            for issue in issues:
                logger.error(f"[RESTING_ORDER_MONITOR_HEALTH] {issue}")
        
        return {
            "healthy": healthy,
            "issues": issues,
            "running": self._running,
            "resting_orders_count": len(self._resting_orders),
            "last_poll_time": self._last_poll_time,
        }


# Global singleton instance
_monitor_instance: Optional[RestingOrderMonitor] = None


def get_resting_order_monitor() -> RestingOrderMonitor:
    """Get the global resting order monitor singleton.
    
    Returns:
        RestingOrderMonitor instance
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = RestingOrderMonitor()
    return _monitor_instance
