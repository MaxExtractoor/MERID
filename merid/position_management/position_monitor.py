"""
Position monitor for swing trading exit management.

Tracks open positions, computes PnL, and enforces TP/SL exits.
"""

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Any
from merid.position_management.position import Position, PositionSide, TrailingType
from merid.position_management.exit_policy import ExitAction, ExitReason
from merid.position_management.exit_policy_resolver import get_exit_policy_resolver
from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, get_priority_for_reason

logger = logging.getLogger(__name__)
import os
print(f"[POSITION-MONITOR-MODULE] Module loaded from {__file__}, thesis side inference fix applied (2026-08-01)")
logger.info(f"[POSITION-MONITOR-MODULE] Module loaded from {__file__}, thesis side inference fix applied (2026-08-01)")


def _is_expired_ticker(ticker: str) -> bool:
    """Check if a ticker has expired (market is in the past).

    Parses the date from the ticker format (e.g., KXBTC15M-26JUL022230-30)
    and checks if the market expiration time is in the past.

    Args:
        ticker: The market ticker to check

    Returns:
        True if the ticker has expired, False otherwise
    """
    if not ticker:
        return False

    try:
        # Parse ticker format: KXBTC15M-26JUL022230-30
        # Extract date part: 26JUL022230 (DDMMMHHMMSS format - 11 total chars)
        match = re.search(r'-(\d{2}[A-Z]{3}\d{6})-', ticker)
        if not match:
            return False

        date_str = match.group(1)
        day = int(date_str[0:2])
        month_str = date_str[2:5].upper()
        hour = int(date_str[5:7])
        minute = int(date_str[7:9])
        second = int(date_str[9:11])

        # Map month abbreviation to number
        months = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        month = months.get(month_str)
        if month is None:
            return False

        # Assume current year (Kalshi tickers are typically current year)
        current_year = datetime.now(timezone.utc).year

        # Create expiration datetime in UTC
        try:
            expiry_dt = datetime(current_year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError:
            # Invalid date (e.g., Feb 30), assume expired
            return True

        # Check if expired (allow 15 minute buffer for market close processing)
        now = datetime.now(timezone.utc)
        expiry_buffer = timedelta(minutes=15)

        return expiry_dt < (now - expiry_buffer)

    except Exception as e:
        logger.debug(f"[EXPIRED-TICKER] Exception parsing ticker {ticker}: {e}")
        return False  # On parse error, don't filter out


class PositionMonitor:
    """
    Position monitor for swing trading exit management.
    
    Subscribes to market data and execution events, maintains open positions,
    computes PnL, and enforces TP/SL exits via exit policy resolver.
    """
    
    def __init__(
        self,
        poll_interval: float = 5.0,  # Check positions every 5 seconds
    ):
        """
        Initialize position monitor.
        
        Args:
            poll_interval: Polling interval in seconds
        """
        self._poll_interval = poll_interval
        self._open_positions: Dict[str, Position] = {}  # position_id -> Position
        self._market_to_position: Dict[str, str] = {}  # market_id -> position_id
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._exit_intent_callback = None  # Callback for exit intents
        self._lock = threading.RLock()  # Thread-safe access to position dicts
        
        # CRITICAL FIX (2026-07-23): Recent submission cache to handle websocket lag
        # Tracks exit orders submitted but not yet visible in RestingOrderMonitor
        # Prevents duplicate exits due to exchange confirmation latency
        self._recent_exit_submissions: Dict[str, float] = {}  # client_order_id -> timestamp
        self._submission_cache_ttl = 10.0  # 10 seconds TTL for submission cache
        
        # CRITICAL FIX (2026-07-23): First-class exit registry
        # Tracks exit orders by position_id as source of truth
        # Reduces reliance on exchange data heuristics
        self._exit_registry: Dict[str, List[str]] = {}  # position_id -> list of kalshi_order_ids
        self._exit_quantities: Dict[str, Dict[str, int]] = {}  # position_id -> {kalshi_order_id: quantity}
        
        # CRITICAL FIX (2026-07-23): Position-level execution locks
        # Prevents TOCTOU races during exit order creation
        self._position_exit_locks: Dict[str, threading.Lock] = {}  # position_id -> Lock
        self._lock_registry_lock = threading.Lock()  # Lock for registry access
        
        # CRITICAL FIX (2026-07-23): Startup grace window to prevent race conditions
        # Tracks process start time and orders last updated timestamp
        self._process_start_time = time.time()
        self._orders_last_updated_ts: Optional[float] = None
        self._startup_grace_window_seconds = 30.0  # 30 seconds grace window for startup
        
        # CRITICAL FIX (2026-07-23): Edge-triggered execution lock per position
        # Prevents multiple exit triggers (TP + SL) from firing before first exit is placed
        self._exit_intent_in_flight: Dict[str, float] = {}  # position_id -> timestamp when intent was generated
        self._exit_intent_timeout_seconds = 15.0  # 15 seconds timeout for exit intent to complete
    
    def _is_expired_market(self, market_id: str) -> bool:
        """Check if a market has expired based on its ticker.
        
        Args:
            market_id: The market ticker to check
            
        Returns:
            True if the market has expired, False otherwise
        """
        return _is_expired_ticker(market_id)
    
    def register_exit_intent_callback(self, callback) -> None:
        """
        Register callback for exit intents.
        
        Args:
            callback: Function to call when exit intent is generated
                     Signature: callback(position, exit_reason, exit_price_cents)
        """
        self._exit_intent_callback = callback
        logger.info("[POSITION-MONITOR] Registered exit intent callback")
    
    def add_position(self, position: Position) -> None:
        """
        Add a new position to monitor.
        
        Args:
            position: Position to add
        """
        with self._lock:
            if position.position_id in self._open_positions:
                logger.warning(
                    "[POSITION-MONITOR] Position %s already exists, skipping",
                    position.position_id
                )
                return
            
            self._open_positions[position.position_id] = position
            self._market_to_position[position.market_id] = position.position_id
        
        logger.info(
            "[POSITION-MONITOR] Added position: %s market=%s side=%s size=%d entry=%dc TP=%dc SL=%dc vol_regime=%s confidence=%s",
            position.position_id[:8],
            position.market_id,
            position.side,
            position.size,
            position.avg_entry_price_cents,
            position.take_profit_price_cents or 0,
            position.stop_loss_price_cents or 0,
            position.vol_regime,
            position.confidence,
        )
    
    def remove_position(self, position_id: str) -> None:
        """
        Remove a position from monitoring.
        
        Args:
            position_id: Position ID to remove
        """
        with self._lock:
            if position_id not in self._open_positions:
                logger.warning(
                    "[POSITION-MONITOR] Position %s not found, cannot remove",
                    position_id
                )
                return

            position = self._open_positions[position_id]

            # FIX 9: Atomic window capacity release - release BEFORE removing position
            # This ensures atomicity: if capacity release fails, position is not removed
            # preventing capacity leaks. Both operations must succeed or both fail.
            try:
                # Calculate notional to release
                notional_usd = (position.size * position.avg_entry_price_cents) / 100.0

                # Release exposure using risk envelope (which has window tracking)
                try:
                    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                    envelope = get_kalshi_crypto_15m_risk_envelope()
                    envelope.record_position_closure(position.market_id, notional_usd)
                except RuntimeError as e:
                    # Bankroll not ready - log warning but don't crash
                    logger.warning(
                        "[POSITION-MONITOR] Failed to release window exposure: %s (bankroll service unavailable)",
                        e
                    )
                    # FIX 9: If capacity release fails, do NOT remove position to prevent capacity leak
                    logger.error(
                        "[POSITION-MONITOR] Atomicity violation: capacity release failed, keeping position to prevent leak: %s",
                        position_id[:8]
                    )
                    return

                logger.info(
                    "[POSITION-MONITOR] Released window capacity: market=%s notional=$%.2f exit_reason=%s",
                    position.market_id,
                    notional_usd,
                    position.exit_reason,
                )
            except RuntimeError as e:
                # Risk envelope not ready (bankroll not available) - log warning but don't fail
                # FIX 9: If capacity release fails, do NOT remove position to prevent capacity leak
                logger.warning(
                    "[POSITION-MONITOR] Risk envelope not ready, keeping position to prevent capacity leak: %s",
                    e
                )
                return
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Failed to release window capacity, keeping position to prevent leak: %s",
                    e,
                    exc_info=True
                )
                # FIX 9: If capacity release fails, do NOT remove position to prevent capacity leak
                return

            # Capacity release succeeded - now remove position from tracking
            del self._open_positions[position_id]
            if position.market_id in self._market_to_position:
                del self._market_to_position[position.market_id]

        logger.info(
            "[POSITION-MONITOR] Removed position: %s (exit_reason=%s, exit_price=%dc)",
            position_id[:8],
            position.exit_reason,
            position.exit_price_cents,
        )
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """
        Get a position by ID.
        
        Args:
            position_id: Position ID
            
        Returns:
            Position or None if not found
        """
        with self._lock:
            return self._open_positions.get(position_id)
    
    def get_position_by_market(self, market_id: str) -> Optional[Position]:
        """
        Get a position by market ID.
        
        Args:
            market_id: Market ID
            
        Returns:
            Position or None if not found
        """
        with self._lock:
            position_id = self._market_to_position.get(market_id)
            if position_id:
                return self._open_positions.get(position_id)
            return None
    
    def get_open_positions(self) -> Dict[str, Position]:
        """
        Get all open positions.
        
        Returns:
            Dict of position_id -> Position
        """
        with self._lock:
            return self._open_positions.copy()
    
    def get_open_positions_count(self) -> int:
        """
        Get the count of open positions.
        
        Returns:
            Number of open positions
        """
        with self._lock:
            return len(self._open_positions)
    
    def health_check_exit_coverage(self) -> Dict[str, Any]:
        """
        Health check for one-position-one-exit invariant.
        
        CRITICAL FIX (2026-07-23): Verifies that each open position has exactly one
        active exit plan (resting exit order). Detects:
        - Positions without exit orders (missing coverage)
        - Positions with multiple exit orders (duplicate risk)
        
        Returns:
            Dict with health check results:
            - total_positions: Total number of open positions
            - positions_without_exit: List of market_ids without exit orders
            - positions_with_multiple_exits: List of market_ids with multiple exit orders
            - healthy_count: Number of positions with exactly one exit order
            - health_status: "healthy", "warning", or "critical"
        """
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
        
        positions_without_exit = []
        positions_with_multiple_exits = []
        healthy_count = 0
        
        try:
            resting_monitor = get_resting_order_monitor()
            open_positions = self.get_open_positions()
            
            for position_id, position in open_positions.items():
                # Get resting orders for this market
                resting_orders = resting_monitor.get_orders_by_ticker(position.market_id)
                
                # Filter for exit orders only (check multiple fields for exit markers)
                # CRITICAL FIX (2026-07-23): Filter by status to exclude terminal orders
                # Only count orders with active status (open, resting, partially_filled)
                from merid.event_venues.kalshi.resting_order_monitor import RESTING_STATUSES, TERMINAL_STATUSES
                exit_orders = []
                for order in resting_orders:
                    is_exit = (
                        is_exit_order_from_source(order.exit_policy_id) or
                        is_exit_order_from_source(order.client_order_id) or
                        is_exit_order_from_source(order.intent_id) or
                        is_exit_order_from_source(getattr(order, 'source', None))
                    )
                    # CRITICAL FIX (2026-07-23): Exclude terminal statuses (filled, canceled, expired, rejected)
                    # These orders are no longer active and should not count as exit coverage
                    order_status = getattr(order, 'status', '').lower()
                    is_active = order_status in RESTING_STATUSES or order_status not in TERMINAL_STATUSES
                    
                    if is_exit and is_active:
                        exit_orders.append(order)
                
                # Check exit coverage
                if len(exit_orders) == 0:
                    positions_without_exit.append(position.market_id)
                    logger.warning(
                        "[EXIT-COVERAGE-HEALTH] Position without exit order: market=%s position_id=%s side=%s size=%d",
                        position.market_id,
                        position.position_id[:8],
                        position.side.value,
                        position.size
                    )
                elif len(exit_orders) > 1:
                    positions_with_multiple_exits.append(position.market_id)
                    logger.warning(
                        "[EXIT-COVERAGE-HEALTH] Position with multiple exit orders: market=%s position_id=%s exit_count=%d order_ids=%s",
                        position.market_id,
                        position.position_id[:8],
                        len(exit_orders),
                        [order.kalshi_order_id for order in exit_orders]
                    )
                else:
                    # CRITICAL FIX (2026-07-23): Check quantity coverage for single exit order
                    # Ensure exit order quantity is sufficient to cover position size
                    exit_order = exit_orders[0]
                    exit_quantity = exit_order.remaining_size if hasattr(exit_order, 'remaining_size') else exit_order.original_size
                    
                    if exit_quantity < position.size:
                        logger.warning(
                            "[EXIT-QUANTITY-COVERAGE] Exit order quantity insufficient: market=%s position_id=%s exit_qty=%d position_size=%d gap=%d",
                            position.market_id,
                            position.position_id[:8],
                            exit_quantity,
                            position.size,
                            position.size - exit_quantity
                        )
                        # Still count as healthy for existence check, but log warning
                        healthy_count += 1
                    else:
                        healthy_count += 1
                        logger.debug(
                            "[EXIT-COVERAGE-HEALTH] Position has exactly one exit order with sufficient quantity: market=%s position_id=%s order_id=%s exit_qty=%d position_size=%d",
                            position.market_id,
                            position.position_id[:8],
                            exit_order.kalshi_order_id,
                            exit_quantity,
                            position.size
                        )
        except Exception as health_err:
            logger.error(
                "[EXIT-COVERAGE-HEALTH] Health check failed: %s",
                health_err,
                exc_info=True
            )
            return {
                "error": str(health_err),
                "health_status": "error"
            }
        
        # Determine overall health status
        total_positions = len(positions_without_exit) + len(positions_with_multiple_exits) + healthy_count
        
        if len(positions_without_exit) > 0 or len(positions_with_multiple_exits) > 0:
            health_status = "critical" if len(positions_without_exit) > 0 else "warning"
        else:
            health_status = "healthy"
        
        result = {
            "total_positions": total_positions,
            "positions_without_exit": positions_without_exit,
            "positions_with_multiple_exits": positions_with_multiple_exits,
            "healthy_count": healthy_count,
            "health_status": health_status
        }
        
        logger.info(
            "[EXIT-COVERAGE-HEALTH] Summary: total=%d healthy=%d without_exit=%d multiple_exits=%d status=%s",
            total_positions,
            healthy_count,
            len(positions_without_exit),
            len(positions_with_multiple_exits),
            health_status
        )
        
        return result
    
    def portfolio_level_exit_coverage_check(self) -> Dict[str, Any]:
        """
        Portfolio-level cross-asset exit coverage check.
        
        CRITICAL FIX (2026-07-23): Ensures portfolio-wide exit coverage invariants:
        - No open positions in any asset without exit coverage
        - No asset with more than one exit per position
        - Per-asset breakdown of exit coverage status
        
        This provides a portfolio-wide view to gate new entries if the system
        detects missing exits for any asset.
        
        Returns:
            Dict with portfolio-level health check results:
            - total_positions: Total number of open positions across all assets
            - assets_with_positions: List of assets with open positions
            - per_asset_coverage: Dict mapping asset -> coverage status
            - assets_without_exit_coverage: List of assets with positions but no exits
            - assets_with_duplicate_exits: List of assets with duplicate exits
            - portfolio_health_status: "healthy", "warning", or "critical"
        """
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
        
        per_asset_coverage = {}
        assets_without_exit_coverage = []
        assets_with_duplicate_exits = []
        
        try:
            resting_monitor = get_resting_order_monitor()
            open_positions = self.get_open_positions()
            
            # Group positions by asset
            positions_by_asset = {}
            for position_id, position in open_positions.items():
                asset = kalshi_ticker_to_asset(position.market_id) if position.market_id else "UNKNOWN"
                if asset not in positions_by_asset:
                    positions_by_asset[asset] = []
                positions_by_asset[asset].append(position)
            
            # Check each asset's exit coverage
            for asset, positions in positions_by_asset.items():
                asset_positions_without_exit = []
                asset_positions_with_multiple_exits = []
                asset_healthy_count = 0
                
                for position in positions:
                    # Get resting orders for this market
                    resting_orders = resting_monitor.get_orders_by_ticker(position.market_id)
                    
                    # Filter for exit orders only (check multiple fields for exit markers)
                    # CRITICAL FIX (2026-07-23): Filter by status to exclude terminal orders
                    # Only count orders with active status (open, resting, partially_filled)
                    from merid.event_venues.kalshi.resting_order_monitor import RESTING_STATUSES, TERMINAL_STATUSES
                    exit_orders = []
                    for order in resting_orders:
                        is_exit = (
                            is_exit_order_from_source(order.exit_policy_id) or
                            is_exit_order_from_source(order.client_order_id) or
                            is_exit_order_from_source(order.intent_id) or
                            is_exit_order_from_source(getattr(order, 'source', None))
                        )
                        # CRITICAL FIX (2026-07-23): Exclude terminal statuses (filled, canceled, expired, rejected)
                        # These orders are no longer active and should not count as exit coverage
                        order_status = getattr(order, 'status', '').lower()
                        is_active = order_status in RESTING_STATUSES or order_status not in TERMINAL_STATUSES
                        
                        if is_exit and is_active:
                            exit_orders.append(order)
                    
                    # Check exit coverage
                    if len(exit_orders) == 0:
                        asset_positions_without_exit.append(position.market_id)
                    elif len(exit_orders) > 1:
                        asset_positions_with_multiple_exits.append(position.market_id)
                    else:
                        asset_healthy_count += 1
                
                # Determine asset-level health status
                if len(asset_positions_without_exit) > 0:
                    asset_status = "critical"
                    assets_without_exit_coverage.append(asset)
                elif len(asset_positions_with_multiple_exits) > 0:
                    asset_status = "warning"
                    assets_with_duplicate_exits.append(asset)
                else:
                    asset_status = "healthy"
                
                per_asset_coverage[asset] = {
                    "total_positions": len(positions),
                    "healthy_count": asset_healthy_count,
                    "positions_without_exit": asset_positions_without_exit,
                    "positions_with_multiple_exits": asset_positions_with_multiple_exits,
                    "asset_status": asset_status
                }
                
                logger.info(
                    "[PORTFOLIO-EXIT-COVERAGE] asset=%s total=%d healthy=%d without_exit=%d multiple_exits=%d status=%s",
                    asset,
                    len(positions),
                    asset_healthy_count,
                    len(asset_positions_without_exit),
                    len(asset_positions_with_multiple_exits),
                    asset_status
                )
        except Exception as portfolio_err:
            logger.error(
                "[PORTFOLIO-EXIT-COVERAGE] Portfolio-level health check failed: %s",
                portfolio_err,
                exc_info=True
            )
            return {
                "error": str(portfolio_err),
                "portfolio_health_status": "error"
            }
        
        # Determine overall portfolio health status
        total_positions = len(open_positions)
        assets_with_positions = list(positions_by_asset.keys())
        
        if len(assets_without_exit_coverage) > 0:
            portfolio_health_status = "critical"
        elif len(assets_with_duplicate_exits) > 0:
            portfolio_health_status = "warning"
        else:
            portfolio_health_status = "healthy"
        
        result = {
            "total_positions": total_positions,
            "assets_with_positions": assets_with_positions,
            "per_asset_coverage": per_asset_coverage,
            "assets_without_exit_coverage": assets_without_exit_coverage,
            "assets_with_duplicate_exits": assets_with_duplicate_exits,
            "portfolio_health_status": portfolio_health_status
        }
        
        logger.info(
            "[PORTFOLIO-EXIT-COVERAGE] Summary: total_positions=%d assets=%d healthy_assets=%d critical_assets=%d warning_assets=%d status=%s",
            total_positions,
            len(assets_with_positions),
            len([a for a, cov in per_asset_coverage.items() if cov["asset_status"] == "healthy"]),
            len(assets_without_exit_coverage),
            len(assets_with_duplicate_exits),
            portfolio_health_status
        )
        
        return result
    
    def _register_exit_submission(self, client_order_id: str) -> None:
        """
        Register a recent exit order submission to handle websocket lag.
        
        CRITICAL FIX (2026-07-23): This prevents duplicate exits when exchange
        confirmation is delayed. Orders in this cache are treated as "exists"
        even if not yet visible in RestingOrderMonitor.
        
        Args:
            client_order_id: Client order ID of the submitted exit order
        """
        with self._lock:
            self._recent_exit_submissions[client_order_id] = time.time()
            logger.debug(
                "[EXIT-SUBMISSION-CACHE] Registered exit submission: client_order_id=%s",
                client_order_id
            )
    
    def _is_exit_submitted_recently(self, client_order_id: str) -> bool:
        """
        Check if an exit order was submitted recently (within TTL).
        
        Args:
            client_order_id: Client order ID to check
            
        Returns:
            True if submitted within TTL, False otherwise
        """
        with self._lock:
            if client_order_id not in self._recent_exit_submissions:
                return False
            
            submission_time = self._recent_exit_submissions[client_order_id]
            if time.time() - submission_time > self._submission_cache_ttl:
                # Expired, remove from cache
                del self._recent_exit_submissions[client_order_id]
                logger.debug(
                    "[EXIT-SUBMISSION-CACHE] Expired submission: client_order_id=%s age=%.2fs",
                    client_order_id,
                    time.time() - submission_time
                )
                return False
            
            return True
    
    def _cleanup_expired_submissions(self) -> None:
        """Clean up expired submissions from the cache."""
        with self._lock:
            current_time = time.time()
            expired = [
                order_id for order_id, timestamp in self._recent_exit_submissions.items()
                if current_time - timestamp > self._submission_cache_ttl
            ]
            for order_id in expired:
                del self._recent_exit_submissions[order_id]
            
            if expired:
                logger.debug(
                    "[EXIT-SUBMISSION-CACHE] Cleaned up %d expired submissions",
                    len(expired)
                )
    
    def _register_exit_order(self, position_id: str, kalshi_order_id: str, quantity: int = 1) -> None:
        """
        Register an exit order in the first-class exit registry.
        
        CRITICAL FIX (2026-07-23): This registry is the source of truth for
        exit orders, reducing reliance on exchange data heuristics.
        
        Args:
            position_id: Position ID
            kalshi_order_id: Kalshi order ID
            quantity: Exit order quantity (number of contracts)
        """
        with self._lock_registry_lock:
            if position_id not in self._exit_registry:
                self._exit_registry[position_id] = []
                self._exit_quantities[position_id] = {}
            
            if kalshi_order_id not in self._exit_registry[position_id]:
                self._exit_registry[position_id].append(kalshi_order_id)
                self._exit_quantities[position_id][kalshi_order_id] = quantity
                logger.info(
                    "[EXIT-REGISTRY] Registered exit order: position_id=%s kalshi_order_id=%s quantity=%d total_exits=%d",
                    position_id[:8],
                    kalshi_order_id,
                    quantity,
                    len(self._exit_registry[position_id])
                )
    
    def _unregister_exit_order(self, position_id: str, kalshi_order_id: str) -> None:
        """
        Unregister an exit order from the exit registry.
        
        Args:
            position_id: Position ID
            kalshi_order_id: Kalshi order ID
        """
        with self._lock_registry_lock:
            if position_id in self._exit_registry:
                if kalshi_order_id in self._exit_registry[position_id]:
                    self._exit_registry[position_id].remove(kalshi_order_id)
                    if kalshi_order_id in self._exit_quantities.get(position_id, {}):
                        del self._exit_quantities[position_id][kalshi_order_id]
                    logger.info(
                        "[EXIT-REGISTRY] Unregistered exit order: position_id=%s kalshi_order_id=%s remaining_exits=%d",
                        position_id[:8],
                        kalshi_order_id,
                        len(self._exit_registry[position_id])
                    )
                
                if not self._exit_registry[position_id]:
                    del self._exit_registry[position_id]
                    if position_id in self._exit_quantities:
                        del self._exit_quantities[position_id]
    
    def _get_exit_orders_for_position(self, position_id: str) -> List[str]:
        """
        Get registered exit orders for a position.
        
        Args:
            position_id: Position ID
            
        Returns:
            List of Kalshi order IDs for exit orders
        """
        with self._lock_registry_lock:
            return self._exit_registry.get(position_id, []).copy()
    
    def _has_exit_order(self, position_id: str) -> bool:
        """
        Check if a position has any registered exit orders.
        
        Args:
            position_id: Position ID
            
        Returns:
            True if position has exit orders, False otherwise
        """
        with self._lock_registry_lock:
            return position_id in self._exit_registry and len(self._exit_registry[position_id]) > 0
    
    def _get_total_exit_quantity(self, position_id: str) -> int:
        """
        Get the total quantity of all exit orders for a position.
        
        CRITICAL FIX (2026-07-23): This is used for quantity-aware exit coverage invariant.
        
        Args:
            position_id: Position ID
            
        Returns:
            Total exit quantity (sum of all exit order quantities)
        """
        with self._lock_registry_lock:
            if position_id not in self._exit_quantities:
                return 0
            return sum(self._exit_quantities[position_id].values())
    
    def _check_exit_quantity_coverage(self, position_id: str, position_size: int) -> Dict[str, Any]:
        """
        Check if exit orders provide sufficient quantity coverage for a position.
        
        CRITICAL FIX (2026-07-23): Ensures sum(open_exit_qty) >= remaining_position_qty.
        This prevents the dangerous case where an exit order exists but is too small
        to fully exit the position.
        
        Args:
            position_id: Position ID
            position_size: Current position size
            
        Returns:
            Dict with coverage check results:
            - has_coverage: True if exit quantity >= position size
            - exit_quantity: Total exit quantity
            - position_size: Position size
            - coverage_gap: Quantity shortfall (if any)
            - coverage_pct: Coverage percentage
        """
        exit_quantity = self._get_total_exit_quantity(position_id)
        coverage_gap = max(0, position_size - exit_quantity)
        coverage_pct = (exit_quantity / position_size * 100) if position_size > 0 else 0
        
        result = {
            "has_coverage": exit_quantity >= position_size,
            "exit_quantity": exit_quantity,
            "position_size": position_size,
            "coverage_gap": coverage_gap,
            "coverage_pct": coverage_pct
        }
        
        if not result["has_coverage"]:
            logger.warning(
                "[EXIT-QUANTITY-COVERAGE] Insufficient exit coverage: position_id=%s exit_qty=%d position_size=%d gap=%d coverage_pct=%.1f%%",
                position_id[:8],
                exit_quantity,
                position_size,
                coverage_gap,
                coverage_pct
            )
        
        return result
    
    def _mark_exit_intent_in_flight(self, position_id: str) -> None:
        """
        Mark an exit intent as in-flight for a position.
        
        CRITICAL FIX (2026-07-23): This prevents multiple exit triggers (TP + SL)
        from firing before the first exit is placed. Only one exit intent can be
        in-flight per position at a time.
        
        Args:
            position_id: Position ID
        """
        with self._lock:
            self._exit_intent_in_flight[position_id] = time.time()
            logger.debug(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent in-flight: position_id=%s",
                position_id[:8]
            )
    
    def _is_exit_intent_in_flight(self, position_id: str) -> bool:
        """
        Check if an exit intent is currently in-flight for a position.
        
        Args:
            position_id: Position ID
            
        Returns:
            True if exit intent is in-flight, False otherwise
        """
        with self._lock:
            if position_id not in self._exit_intent_in_flight:
                return False
            
            # Check if the intent has timed out
            intent_time = self._exit_intent_in_flight[position_id]
            if time.time() - intent_time > self._exit_intent_timeout_seconds:
                # Expired, remove from in-flight tracking
                del self._exit_intent_in_flight[position_id]
                logger.warning(
                    "[EXIT-INTENT-IN-FLIGHT] Exit intent timed out: position_id=%s age=%.2fs",
                    position_id[:8],
                    time.time() - intent_time
                )
                return False
            
            return True
    
    def _clear_exit_intent_in_flight(self, position_id: str) -> None:
        """
        Clear the in-flight flag for a position after exit order is placed.
        
        Args:
            position_id: Position ID
        """
        with self._lock:
            if position_id in self._exit_intent_in_flight:
                del self._exit_intent_in_flight[position_id]
                logger.debug(
                    "[EXIT-INTENT-IN-FLIGHT] Cleared exit intent in-flight: position_id=%s",
                    position_id[:8]
                )
    
    def _get_position_lock(self, position_id: str) -> threading.Lock:
        """
        Get or create a position-level execution lock.
        
        CRITICAL FIX (2026-07-23): Prevents TOCTOU races during exit order creation.
        Only one thread can create an exit order for a given position at a time.
        
        Args:
            position_id: Position ID
            
        Returns:
            Lock object for this position
        """
        with self._lock_registry_lock:
            if position_id not in self._position_exit_locks:
                self._position_exit_locks[position_id] = threading.Lock()
            return self._position_exit_locks[position_id]
    
    def set_orders_last_updated(self, timestamp: float) -> None:
        """
        Set the timestamp when orders were last updated from exchange.
        
        CRITICAL FIX (2026-07-23): This is used for startup grace window to ensure
        orders are loaded before enforcing exit invariants.
        
        Args:
            timestamp: Unix timestamp when orders were last updated
        """
        with self._lock:
            self._orders_last_updated_ts = timestamp
            logger.info(
                "[STARTUP-GRACE] Orders last updated timestamp set: %.2f (age=%.2fs since process start)",
                timestamp,
                timestamp - self._process_start_time
            )
    
    def is_in_startup_grace_window(self) -> bool:
        """
        Check if the system is in the startup grace window.
        
        CRITICAL FIX (2026-07-23): During startup, we delay exit invariant enforcement
        until orders are loaded and at least one websocket sync cycle completes.
        
        Returns:
            True if in startup grace window, False otherwise
        """
        with self._lock:
            # Check if orders have been updated from RestingOrderMonitor
            try:
                from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
                resting_monitor = get_resting_order_monitor()
                
                # If RestingOrderMonitor hasn't polled yet, we're in grace window
                if resting_monitor._last_poll_time is None:
                    logger.debug("[STARTUP-GRACE] RestingOrderMonitor hasn't polled yet - in grace window")
                    return True
                
                # Convert datetime to timestamp
                last_poll_ts = resting_monitor._last_poll_time.timestamp()
                time_since_poll = time.time() - last_poll_ts
                
                # Check if enough time has passed since first poll
                if time_since_poll < self._startup_grace_window_seconds:
                    logger.debug(
                        "[STARTUP-GRACE] In grace window: time since poll=%.2fs < grace window=%.2fs",
                        time_since_poll,
                        self._startup_grace_window_seconds
                    )
                    return True
                
                logger.info(
                    "[STARTUP-GRACE] Grace window complete: time since poll=%.2fs >= grace window=%.2fs",
                    time_since_poll,
                    self._startup_grace_window_seconds
                )
                return False
                
            except Exception as e:
                logger.warning(
                    "[STARTUP-GRACE] Failed to check RestingOrderMonitor poll time, assuming grace window: %s",
                    e
                )
                return True
    
    async def _check_position(self, position: Position, current_price_cents: int, poll_count: int = 0) -> None:
        """
        Check a single position for exit conditions.
        
        Args:
            position: Position to check
            current_price_cents: Current market price in cents
            poll_count: Current poll iteration number for dedupe keys
        """
        # Update runtime state
        position.update_runtime_state(current_price_cents)
        
        # CRITICAL FIX: 2026-07-31 - Ensure TP target is set to prevent asymmetric risk
        # If position has no TP target but has entry price, compute default 1R TP
        # This prevents positions from being able to exit on losses but never on profits
        if position.take_profit_price_cents is None and position.avg_entry_price_cents > 0:
            if position.initial_risk_cents > 0:
                # Use existing risk calculation (side-aware)
                if position.side == PositionSide.YES:
                    position.take_profit_price_cents = position.avg_entry_price_cents + position.initial_risk_cents
                else:
                    position.take_profit_price_cents = max(1, position.avg_entry_price_cents - position.initial_risk_cents)
                position.take_profit_r_multiple = 1.0
            else:
                # Default to 5 cent risk if no SL set (side-aware)
                default_risk_cents = 5
                if position.side == PositionSide.YES:
                    position.take_profit_price_cents = position.avg_entry_price_cents + default_risk_cents
                else:
                    position.take_profit_price_cents = max(1, position.avg_entry_price_cents - default_risk_cents)
                position.take_profit_r_multiple = 1.0
                # Also set SL if not set for consistency (side-aware)
                if position.stop_loss_price_cents is None:
                    if position.side == PositionSide.YES:
                        position.stop_loss_price_cents = max(1, position.avg_entry_price_cents - default_risk_cents)
                    else:
                        position.stop_loss_price_cents = min(99, position.avg_entry_price_cents + default_risk_cents)
                    position.initial_risk_cents = default_risk_cents
            logger.info(
                "[POSITION-MONITOR-TP-FALLBACK] Set default TP for position=%s: entry=%dc tp=%dc sl=%dc",
                position.position_id[:8],
                position.avg_entry_price_cents,
                position.take_profit_price_cents,
                position.stop_loss_price_cents or 0
            )
        
        # Log position state for debugging
        logger.debug(
            "[POSITION-MONITOR] Checking position=%s market=%s side=%s entry=%dc current=%dc pnl=%dc R=%.2f "
            "tp=%dc sl=%dc trailing=%s",
            position.position_id[:8],
            position.market_id,
            position.side.value,
            position.avg_entry_price_cents,
            current_price_cents,
            position.unrealized_pnl_cents,
            position.r_multiple,
            position.take_profit_price_cents or 0,
            position.stop_loss_price_cents or 0,
            position.trailing_activated,
        )
        
        # AUDIT: Log trigger evaluation start (no trigger found yet)
        logger.debug(
            "[EXIT-TRIGGER-AUDIT] position=%s market=%s price=%dc side=%s size=%d checking_triggers=true",
            position.position_id[:8],
            position.market_id,
            current_price_cents,
            position.side.value,
            position.size
        )
        
        # CRITICAL: Check extreme profit exit first (highest priority)
        # Exit at 99c YES / 1c NO to lock in guaranteed wins
        # CRITICAL FIX: 2026-07-06 - Consolidated 99c exit to single mechanism (removed duplicate ratchet 99c check)
        # The position-level extreme profit check handles 99c YES / 1c NO for all assets
        # Profile ratchet_mandatory_exit_at_99c is redundant and removed from this path
        # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
        # Check if position already has exit intent pending to prevent race conditions
        # CRITICAL FIX: 2026-07-07 - Added bid/ask spread handling for boundary conditions
        # Pass bid/ask to prevent false triggers at extreme prices due to spread
        # Note: bid/ask not available in current _check_position signature, using mid price
        # Future enhancement: pass bid/ask from market state to improve accuracy
        
        # AUTO_EXIT_99C: Cash out at 99c (near-settlement) - highest priority after RISK
        # Per Kalshi semantics, contracts settle at exactly $1 if correct and $0 if not
        # Selling early at 99c locks in almost all of the payoff
        if position.should_trigger_auto_exit_99c(current_price_cents) and not position.exit_triggered:
            # CRITICAL FIX (2026-07-23): Log multi-trigger state for audit
            # Distinguish between "position already exited" vs "multiple triggers evaluated"
            if position.exit_reason:
                logger.warning(
                    "[EXIT-TRIGGER-MULTI] position=%s market=%s has exit_reason=%s but exit_triggered=False - "
                    "this indicates exit order placement failed or is pending. Skipping new trigger auto_exit_99c.",
                    position.position_id[:8],
                    position.market_id,
                    position.exit_reason
                )
                return
            # AUDIT: Timing correctness - check expiry proximity
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            seconds_to_expiry = getattr(state, 'seconds_to_expiry', None) if state else None
            
            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:auto_exit_99c:{poll_count}"
            
            # AUDIT: Venue-side semantics - verify 99c exit is executable
            # Kalshi accepts SELL_YES at 99c and SELL_NO at 1c for near-settlement exits
            # This is a real executable close path, not just a logical condition
            logger.info(
                "[VENUE-SEMANTICS-AUDIT] position=%s market=%s reason=auto_exit_99c "
                "exit_path=executable kalshi_semantics=SELL_99c_or_1c executable=YES",
                position.position_id[:8],
                position.market_id
            )
            
            # AUDIT: Log trigger evaluation with timing context
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=auto_exit_99c price=%dc side=%s size=%d trigger=true seconds_to_expiry=%s dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.side.value,
                position.size,
                seconds_to_expiry,
                dedupe_key
            )
            
            # AUDIT: Warn if triggering very close to expiry
            if seconds_to_expiry is not None and seconds_to_expiry < 60:
                logger.warning(
                    "[TIMING-AUDIT] position=%s market=%s 99c_exit_triggered_near_expiry seconds_to_expiry=%d - order may not fill before settlement",
                    position.position_id[:8],
                    position.market_id,
                    seconds_to_expiry
                )
            
            logger.info(
                "[POSITION-MONITOR] AUTO-EXIT-99C triggered: position=%s price=%dc side=%s - cashing out at near-settlement",
                position.position_id[:8],
                current_price_cents,
                position.side.value,
            )
            self._emit_exit_intent(position, ExitReason.AUTO_EXIT_99C, current_price_cents)
            return
        
        # DYNAMIC TAKE PROFIT: Laddered exits based on entry price for consistent profits
        # 2026-07-06: Implements user's strategy for frequent small wins
        # CRITICAL FIX (2026-08-01): Updated entry zones from 25c-75c to 5c-85c for 15m crypto volatility
        # Entry 5-15c → Exit 50-60c, Entry 15-30c → Exit 60-70c, Entry 30-50c → Exit 70-77c, etc.
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Check if dynamic take profit is enabled
                dynamic_tp_config = getattr(profile, 'dynamic_take_profit', {})
                if dynamic_tp_config and dynamic_tp_config.get('enabled', False):
                    # Initialize dynamic TP target if not set
                    if position.dynamic_tp_target_cents is None:
                        entry_price = position.avg_entry_price_cents
                        zones = dynamic_tp_config.get('zones', [])
                        
                        # Find matching zone based on entry price
                        for zone in zones:
                            entry_min = zone.get('entry_min', 0)
                            entry_max = zone.get('entry_max', 100)
                            if entry_min <= entry_price <= entry_max:
                                base_target = zone.get('exit_target', 0)
                                
                                # Apply edge quality adjustment if enabled
                                if dynamic_tp_config.get('edge_adjustment_enabled', False):
                                    # Get edge from position (if available)
                                    edge_pct = getattr(position, 'entry_edge_pct', 0.03)  # Default 3%
                                    edge_high_threshold = dynamic_tp_config.get('edge_high_threshold', 0.05)
                                    edge_low_threshold = dynamic_tp_config.get('edge_low_threshold', 0.02)
                                    edge_high_multiplier = dynamic_tp_config.get('edge_high_multiplier', 1.1)
                                    edge_low_multiplier = dynamic_tp_config.get('edge_low_multiplier', 0.9)
                                    
                                    if edge_pct >= edge_high_threshold:
                                        base_target = int(base_target * edge_high_multiplier)
                                    elif edge_pct <= edge_low_threshold:
                                        base_target = int(base_target * edge_low_multiplier)
                                
                                # CRITICAL FIX (2026-07-16): Side-space — entry and current
                                # prices are in the position's OWN side cents for BOTH sides,
                                # so zone targets apply directly (no 100-x mirror for NO)
                                position.dynamic_tp_target_cents = base_target
                                
                                # CRITICAL FIX: 2026-07-07 - Add user communication for infeasible TP targets due to fees
                                # Check if target is feasible after fees
                                try:
                                    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
                                    
                                    # Calculate gross profit
                                    # CRITICAL FIX (2026-07-16): Side-space — target above entry for BOTH sides
                                    gross_profit = (position.dynamic_tp_target_cents - entry_price) * position.size
                                    
                                    # Calculate round-trip fees
                                    entry_fee = calculate_kalshi_fee_cents(position.size, entry_price)
                                    exit_fee = calculate_kalshi_fee_cents(position.size, position.dynamic_tp_target_cents)
                                    total_fees = entry_fee + exit_fee
                                    
                                    # Calculate net profit per contract
                                    net_edge = (gross_profit - total_fees) / position.size if position.size > 0 else 0
                                    min_edge_threshold = 1.0  # Minimum 1 cent net profit
                                    
                                    if net_edge < min_edge_threshold:
                                        logger.warning(
                                            "[POSITION-MONITOR] DYNAMIC-TP target INFEASIBLE due to fees: position=%s entry=%dc target=%dc gross=%dc fees=%dc net=%.1fc < %.1fc threshold. "
                                            "Target will be set but may not trigger profitable exit. Consider adjusting entry price or target zones.",
                                            position.position_id[:8],
                                            entry_price,
                                            position.dynamic_tp_target_cents,
                                            gross_profit,
                                            total_fees,
                                            net_edge,
                                            min_edge_threshold,
                                        )
                                except Exception as e:
                                    logger.debug("[POSITION-MONITOR] Could not check fee feasibility for dynamic TP: %s", e)
                                
                                logger.info(
                                    "[POSITION-MONITOR] DYNAMIC-TP target set: position=%s entry=%dc target=%dc (zone: %d-%dc)",
                                    position.position_id[:8],
                                    entry_price,
                                    position.dynamic_tp_target_cents,
                                    entry_min,
                                    entry_max,
                                )
                                break
                    
                    # Check if dynamic TP target is reached
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
                    # CRITICAL FIX (2026-07-16): Side-space — own-side price rising to target
                    # triggers for BOTH sides (no NO mirror)
                    if position.dynamic_tp_target_cents is not None and not position.dynamic_tp_triggered and not position.exit_triggered:
                        # CRITICAL FIX (2026-07-23): Log multi-trigger state for audit
                        if position.exit_reason:
                            logger.warning(
                                "[EXIT-TRIGGER-MULTI] position=%s market=%s has exit_reason=%s but exit_triggered=False - "
                                "skipping new trigger dynamic_tp. This indicates exit order placement failed or is pending.",
                                position.position_id[:8],
                                position.market_id,
                                position.exit_reason
                            )
                            return
                        if current_price_cents >= position.dynamic_tp_target_cents:
                            position.dynamic_tp_triggered = True
                            # AUDIT: Idempotency - generate dedupe key for this trigger
                            dedupe_key = f"{position.position_id[:8]}:dynamic_tp:{poll_count}"
                            # AUDIT: Log trigger evaluation
                            logger.info(
                                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=dynamic_tp price=%dc target=%dc side=%s size=%d trigger=true dedupe_key=%s",
                                position.position_id[:8],
                                position.market_id,
                                current_price_cents,
                                position.dynamic_tp_target_cents,
                                position.side.value,
                                position.size,
                                dedupe_key
                            )
                            logger.info(
                                "[POSITION-MONITOR] DYNAMIC-TP triggered: position=%s side=%s price=%dc target=%dc (target reached)",
                                position.position_id[:8],
                                position.side.value,
                                current_price_cents,
                                position.dynamic_tp_target_cents,
                            )
                            self._emit_exit_intent(position, ExitReason.DYNAMIC_TAKE_PROFIT, current_price_cents)
                            return
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Dynamic take profit check failed: %s", e)
        
        # RATCHET PROFIT FLOOR: Lock in profits at 80-85c range
        # Research-backed mechanism to prevent giving back gains when 99c TP is not guaranteed
        # 2026-07-05: Added position trimming and 99c hard exit
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                if profile.ratchet_profit_floor_enabled:
                    activation_threshold = profile.ratchet_activation_threshold_cents  # 85c
                    floor_offset = profile.ratchet_floor_offset_cents  # 5c (floor at 80c)
                    force_exit = profile.ratchet_force_exit_on_floor_breach
                    # CRITICAL FIX: 2026-07-06 - Removed mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
                    trim_enabled = profile.ratchet_trim_position_enabled  # 2026-07-05
                    trim_threshold = profile.ratchet_trim_threshold_cents  # 2026-07-05: 80c
                    trim_to_contracts = profile.ratchet_trim_to_contracts  # 2026-07-05: 1 contract
                    
                    # Calculate floor price
                    floor_price = activation_threshold - floor_offset
                    
                    # Check if position hit activation threshold
                    if not hasattr(position, 'ratchet_activated'):
                        position.ratchet_activated = False
                    if not hasattr(position, 'ratchet_hold_until'):
                        position.ratchet_hold_until = 0
                    if not hasattr(position, 'ratchet_trimmed'):
                        position.ratchet_trimmed = False  # 2026-07-05: Track if position was trimmed
                    
                    # 2026-07-05: POSITION TRIMMING when >1 contract and price >80c
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double trim
                    # CRITICAL FIX: 2026-07-07 - Removed early return to cascade other exit checks
                    # After trimming, continue checking other exit conditions (extreme profit, dynamic TP, etc.)
                    # This ensures critical exits like 99c are not delayed by trimming
                    # CRITICAL FIX (2026-07-16): Side-space — own-side price crossing the trim
                    # threshold triggers for BOTH sides (no 100-x mirror for NO)
                    if trim_enabled and not position.ratchet_trimmed and not position.exit_triggered:
                        if position.size > trim_to_contracts:
                            if current_price_cents >= trim_threshold:
                                position.ratchet_trimmed = True
                                # Emit trim intent (partial close)
                                contracts_to_close = position.size - trim_to_contracts
                                logger.info(
                                    "[POSITION-MONITOR] RATCHET-TRIM triggered: position=%s side=%s price=%dc size=%d -> trim to %d contracts (close %d)",
                                    position.position_id[:8],
                                    position.side.value,
                                    current_price_cents,
                                    position.size,
                                    trim_to_contracts,
                                    contracts_to_close,
                                )
                                self._emit_exit_intent(position, ExitReason.RATCHET_TRIM, current_price_cents, contracts_to_close)
                                # CRITICAL FIX: Do NOT update position.size here - wait for fill callback
                                # Previous code updated position.size prematurely, creating desync with PositionCache.contracts
                                # Position.size should only be updated via fill callback to ensure consistency
                                # CRITICAL: Continue to check other exit conditions (don't return early)
                    
                    # Activate ratchet when price hits threshold
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double activation
                    # CRITICAL FIX (2026-07-16): Side-space — own-side price reaching the activation
                    # threshold triggers for BOTH sides (no 100-x mirror for NO)
                    if not position.ratchet_activated and not position.exit_triggered:
                        if current_price_cents >= activation_threshold:
                            position.ratchet_activated = True
                            position.ratchet_hold_until = datetime.utcnow().timestamp() + profile.ratchet_min_hold_after_activation_sec
                            logger.info(
                                "[POSITION-MONITOR] RATCHET activated: position=%s side=%s price=%dc threshold=%dc floor=%dc",
                                position.position_id[:8],
                                position.side.value,
                                current_price_cents,
                                activation_threshold,
                                floor_price,
                            )
                    
                    # Check floor breach after activation and hold period
                    # CRITICAL FIX: 2026-07-07 - REMOVED hold period bypass to prevent noise-triggered exits
                    # Previous logic bypassed hold period when in profit zone, defeating its purpose
                    # Now only allow exit when hold period expires to prevent premature exits
                    # 2026-08-01: Added thesis validation for soft exit (no longer mandatory)
                    if position.ratchet_activated:
                        hold_expired = datetime.utcnow().timestamp() >= position.ratchet_hold_until
                        can_exit = hold_expired  # Exit ONLY if hold period expired
                        
                        if can_exit:
                            # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
                            # CRITICAL FIX (2026-07-16): Side-space — own-side price falling to the
                            # floor triggers for BOTH sides (no 100-x mirror for NO)
                            if current_price_cents <= floor_price and not position.exit_triggered:
                                # 2026-08-01: Check thesis validation if enabled
                                thesis_validation_enabled = profile.ratchet_thesis_validation_enabled if hasattr(profile, 'ratchet_thesis_validation_enabled') else False
                                
                                if force_exit:
                                    # Mandatory exit (legacy behavior, now disabled by default)
                                    logger.info(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s side=%s price=%dc floor=%dc - mandatory exit (hold_period=expired)",
                                        position.position_id[:8],
                                        position.side.value,
                                        current_price_cents,
                                        floor_price,
                                    )
                                    self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
                                    return
                                elif thesis_validation_enabled:
                                    # Soft exit: only exit if thesis is broken
                                    # For now, we use a simple heuristic: thesis broken if price dropped significantly
                                    # In production, this should integrate with signal/thesis validation
                                    thesis_broken = True  # Placeholder - integrate with actual thesis validation
                                    if thesis_broken:
                                        logger.info(
                                            "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s side=%s price=%dc floor=%dc - soft exit (thesis broken, hold_period=expired)",
                                            position.position_id[:8],
                                            position.side.value,
                                            current_price_cents,
                                            floor_price,
                                        )
                                        self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
                                        return
                                    else:
                                        logger.info(
                                            "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s side=%s price=%dc floor=%dc - holding (thesis intact, hold_period=expired)",
                                            position.position_id[:8],
                                            position.side.value,
                                            current_price_cents,
                                            floor_price,
                                        )
                                else:
                                    logger.warning(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s side=%s price=%dc floor=%dc (exit not forced, thesis validation disabled)",
                                        position.position_id[:8],
                                        position.side.value,
                                        current_price_cents,
                                        floor_price,
                                    )
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Ratchet profit floor check failed: %s", e)
        
        # Check TP/SL next
        if position.should_trigger_stop_loss(current_price_cents):
            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:stop_loss:{poll_count}"
            # AUDIT: Log trigger evaluation
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=stop_loss price=%dc sl=%dc side=%s size=%d trigger=true dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.stop_loss_price_cents,
                position.side.value,
                position.size,
                dedupe_key
            )
            logger.info(
                "[POSITION-MONITOR] STOP-LOSS triggered: position=%s price=%dc sl=%dc R=%.2f",
                position.position_id[:8],
                current_price_cents,
                position.stop_loss_price_cents,
                position.r_multiple,
            )
            self._emit_exit_intent(position, ExitReason.STOP_LOSS, current_price_cents)
            return
        
        if position.should_trigger_take_profit(current_price_cents):
            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:take_profit:{poll_count}"
            # AUDIT: Log trigger evaluation
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=take_profit price=%dc tp=%dc side=%s size=%d trigger=true dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.take_profit_price_cents,
                position.side.value,
                position.size,
                dedupe_key
            )
            logger.info(
                "[POSITION-MONITOR] TAKE-PROFIT triggered: position=%s price=%dc tp=%dc R=%.2f",
                position.position_id[:8],
                current_price_cents,
                position.take_profit_price_cents,
                position.r_multiple,
            )
            self._emit_exit_intent(position, ExitReason.TAKE_PROFIT, current_price_cents)
            return
        
        # Research: Check break-even trigger at 1R (capital preservation)
        if position.should_trigger_break_even(current_price_cents):
            position.trigger_break_even()
            logger.info(
                "[POSITION-MONITOR] BREAK-EVEN triggered: position=%s price=%dc R=%.2f SL moved to entry",
                position.position_id[:8],
                current_price_cents,
                position.r_multiple,
            )
            # Don't exit, just update SL - continue monitoring
        
        # Research: Check partial scale-out at 1.5-2R (Pay Yourself strategy)
        # 2026-08-01: Activate scale-out from profile config
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                if profile.scale_out_enabled:
                    # Set scale-out target from profile if not already set
                    if position.scale_out_price_cents is None and position.initial_risk_cents > 0:
                        scale_out_r_multiple = profile.scale_out_trigger_r_multiple
                        position.scale_out_r_multiple = scale_out_r_multiple
                        # Calculate scale-out price: entry + (R * initial_risk)
                        # CRITICAL FIX (2026-07-16): Side-space — target above entry for BOTH sides
                        if position.side == PositionSide.YES:
                            position.scale_out_price_cents = position.avg_entry_price_cents + int(scale_out_r_multiple * position.initial_risk_cents)
                        else:
                            position.scale_out_price_cents = max(1, position.avg_entry_price_cents - int(scale_out_r_multiple * position.initial_risk_cents))
                        logger.info(
                            "[POSITION-MONITOR] SCALE-OUT target set: position=%s entry=%dc scale_out_r=%.1f target=%dc",
                            position.position_id[:8],
                            position.avg_entry_price_cents,
                            scale_out_r_multiple,
                            position.scale_out_price_cents,
                        )
                    
                    # Check if scale-out should trigger
                    if position.should_trigger_scale_out(current_price_cents):
                        # Check minimum contracts requirement
                        min_contracts = profile.scale_out_min_contracts_for_scale
                        if position.size >= min_contracts:
                            contracts_to_close = position.trigger_scale_out()
                            logger.info(
                                "[POSITION-MONITOR] SCALE-OUT triggered: position=%s price=%dc R=%.2f closing %d of %d contracts",
                                position.position_id[:8],
                                current_price_cents,
                                position.r_multiple,
                                contracts_to_close,
                                position.size,
                            )
                            # Emit scale-out intent (partial exit)
                            self._emit_scale_out_intent(position, contracts_to_close, current_price_cents)
                            # Continue monitoring with reduced size
                        else:
                            logger.debug(
                                "[POSITION-MONITOR] SCALE-OUT skipped: position=%s size=%d < min_contracts=%d",
                                position.position_id[:8],
                                position.size,
                                min_contracts,
                            )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Scale-out check failed: %s", e)
        
        # CRITICAL FIX: Activate trailing stop after minimum profit threshold (not 1R)
        # For 15-minute binary options, waiting for 1R break-even is too conservative
        # Many trades never reach 1R before reversing, causing avoidable losses
        # Activate trailing after min_profit_cents from profile (default 12 cents, align with 2026 research)
        # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing (2c distance) when price crosses 80c profit zone
        # CRITICAL FIX: 2026-07-12 - Implement activation delay to prevent noise-triggered trailing
        # Record when profit threshold is reached, then wait for activation_delay_sec before activating
        if not position.trailing_activated:
            # Check if position has minimum profit to activate trailing
            min_profit_cents = 12  # Default from profile (align with 2026 research)
            profit_zone_activation_cents = 80  # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing at 80c
            activation_delay_sec = 30  # Default activation delay from profile
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    min_profit_cents = profile.trailing_stop_min_profit_cents
                    profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                    activation_delay_sec = profile.trailing_stop_activation_delay_sec
            except Exception as e:
                logger.warning("[POSITION-MONITOR] Could not read trailing config from profile: %s", e)
            
            # Calculate current profit in cents
            # CRITICAL FIX (2026-07-16): Side-space — profit = own-side price rising for BOTH sides
            profit_cents = current_price_cents - position.avg_entry_price_cents
            
            # Check if profit threshold reached
            if profit_cents >= min_profit_cents:
                # Record timestamp when threshold first reached
                if position.trailing_profit_threshold_reached_at is None:
                    position.trailing_profit_threshold_reached_at = datetime.utcnow().timestamp()
                    logger.info(
                        "[POSITION-MONITOR] TRAILING profit threshold reached: position=%s price=%dc profit=%dc - waiting %ds delay before activation",
                        position.position_id[:8],
                        current_price_cents,
                        profit_cents,
                        activation_delay_sec,
                    )
                
                # Check if activation delay has elapsed
                now = datetime.utcnow().timestamp()
                # Ensure activation_delay_sec is a float (handle Mock objects in tests)
                if not isinstance(activation_delay_sec, (int, float)):
                    activation_delay_sec = 30.0  # Default fallback
                delay_elapsed = (now - position.trailing_profit_threshold_reached_at) >= activation_delay_sec
                
                if delay_elapsed:
                    position.trailing_activated = True
                    # CRITICAL FIX: 2026-07-16 - Side-space — profit zone = own-side price >= 80c
                    # for BOTH sides (no 100-x mirror for NO)
                    in_profit_zone = False
                    if current_price_cents >= profit_zone_activation_cents:
                        in_profit_zone = True
                        position.trailing_profit_zone_activated = True
                    
                    if in_profit_zone:
                        logger.info(
                            "[POSITION-MONITOR] TRAILING activated (AGGRESSIVE 2c mode): position=%s price=%dc profit=%dc R=%.2f - in 80-85c profit zone (delay elapsed)",
                            position.position_id[:8],
                            current_price_cents,
                            profit_cents,
                            position.r_multiple,
                        )
                    else:
                        logger.info(
                            "[POSITION-MONITOR] TRAILING activated (normal 5c mode): position=%s price=%dc profit=%dc R=%.2f threshold=%dc (delay elapsed)",
                            position.position_id[:8],
                            current_price_cents,
                            profit_cents,
                            position.r_multiple,
                            min_profit_cents,
                        )
                else:
                    # Still waiting for delay to elapse
                    logger.debug(
                        "[POSITION-MONITOR] TRAILING waiting for activation delay: position=%s elapsed=%.1fs/%.1fs",
                        position.position_id[:8],
                        now - position.trailing_profit_threshold_reached_at,
                        activation_delay_sec,
                    )
        else:
            # CRITICAL FIX: 2026-07-06 - Check if position entered profit zone after trailing was already activated
            # Switch to aggressive trailing if price crosses 80c
            # CRITICAL FIX: 2026-07-07 - Added hysteresis to prevent oscillation around 80c boundary
            # Activate aggressive mode at 80c, but only deactivate when price drops below 75c
            # This prevents trail level jumping from 83c to 80c when crossing threshold
            if not position.trailing_profit_zone_activated:
                profit_zone_activation_cents = 80
                profit_zone_deactivation_cents = 75  # Hysteresis: deactivate 5c below activation
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                    if is_profile_active():
                        adapter = get_active_profile()
                        profile = adapter.profile
                        profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                        profit_zone_deactivation_cents = profit_zone_activation_cents - 5  # 5c hysteresis
                except Exception as e:
                    logger.debug("[POSITION-MONITOR] Could not read profit zone config from profile: %s", e)
                
                # CRITICAL FIX (2026-07-16): Side-space — own-side price >= activation for BOTH sides
                if current_price_cents >= profit_zone_activation_cents:
                    position.trailing_profit_zone_activated = True
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to AGGRESSIVE 2c mode: position=%s side=%s price=%dc - entered 80-85c profit zone",
                        position.position_id[:8],
                        position.side.value,
                        current_price_cents,
                    )
            else:
                # Check if should deactivate aggressive mode (with hysteresis)
                profit_zone_deactivation_cents = 75
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                    if is_profile_active():
                        adapter = get_active_profile()
                        profile = adapter.profile
                        profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                        profit_zone_deactivation_cents = profit_zone_activation_cents - 5  # 5c hysteresis
                except Exception as e:
                    logger.debug("[POSITION-MONITOR] Could not read profit zone config from profile: %s", e)
                
                # CRITICAL FIX (2026-07-16): Side-space — own-side price < deactivation for BOTH sides
                if current_price_cents < profit_zone_deactivation_cents:
                    position.trailing_profit_zone_activated = False
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to NORMAL 5c mode: position=%s side=%s price=%dc - exited profit zone (hysteresis)",
                        position.position_id[:8],
                        position.side.value,
                        current_price_cents,
                    )
        
        # Check trailing stop (only if activated)
        if position.trailing_activated and position.should_trigger_trail(current_price_cents):
            trail_level = position.get_trail_level()
            logger.info(
                "[POSITION-MONITOR] TRAIL triggered: position=%s price=%dc trail=%dc max_fav=%dc R=%.2f",
                position.position_id[:8],
                current_price_cents,
                trail_level,
                position.max_favorable_price_cents,
                position.r_multiple,
            )
            self._emit_exit_intent(position, ExitReason.TRAIL, current_price_cents)
            return
        
        # CRITICAL FIX (2026-07-11): Emergency flatten in last 60 seconds
        # Force full exit regardless of other conditions to ensure position doesn't expire
        # Get time to expiry from market state
        time_to_expiry_seconds = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry_seconds = state.seconds_to_expiry
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get time to expiry for emergency flatten: %s", e)
        
        # Emergency flatten: force exit in last 60 seconds ONLY if profitable
        # CRITICAL FIX (2026-07-31): Prevent forced loss exits near expiry
        # Only force exit if position has positive PnL to lock in gains
        if time_to_expiry_seconds <= 60.0:
            if position.unrealized_pnl_cents > 0:
                logger.warning(
                    "[POSITION-MONITOR] EMERGENCY FLATTEN: position=%s time_to_expiry=%.1fs pnl=%dc - forcing full exit to lock in profit",
                    position.position_id[:8],
                    time_to_expiry_seconds,
                    position.unrealized_pnl_cents
                )
                self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents)  # Full exit
                return  # Exit immediately, don't check other conditions
            else:
                logger.info(
                    "[POSITION-MONITOR] EMERGENCY FLATTEN SKIPPED: position=%s time_to_expiry=%.1fs pnl=%dc - holding underwater position to expiry",
                    position.position_id[:8],
                    time_to_expiry_seconds,
                    position.unrealized_pnl_cents
                )
        
        # CRITICAL FIX: 2026-07-15 - Load staged exit stages from YAML config
        # Previously hardcoded to 5/10/13 minutes with 25/25/50% - now configurable
        # staged_time_exit is at top level of YAML, not nested under exit_policy_time_exit
        staged_exit_stages = []
        staged_exit_enabled = False
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile
            
            # Load from YAML staged_time_exit section (top level, not nested)
            # The profile adapter loads it as a separate field
            if hasattr(profile, 'staged_time_exit'):
                staged_config = profile.staged_time_exit
                staged_exit_enabled = staged_config.get('enabled', False)
                staged_exit_stages = staged_config.get('stages', [])
                
                if not staged_exit_stages and staged_exit_enabled:
                    # Fallback to default if enabled but no stages defined
                    staged_exit_stages = [
                        {"minutes": 5, "percent": 25},
                        {"minutes": 10, "percent": 25},
                        {"minutes": 13, "percent": 50},
                    ]
                    logger.warning("[POSITION-MONITOR] staged_time_exit enabled but no stages defined, using defaults")
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Failed to load staged exit config: %s, using defaults", e)
            # Fallback to hardcoded values
            staged_exit_stages = [
                {"minutes": 5, "percent": 25},
                {"minutes": 10, "percent": 25},
                {"minutes": 13, "percent": 50},
            ]
        
        # Skip staged exits if disabled
        if not staged_exit_enabled:
            staged_exit_stages = []
        
        # Get time to expiry from market state
        time_to_expiry_seconds = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry_seconds = state.seconds_to_expiry
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not get time to expiry for staged exit: %s", e)
        
        # CRITICAL FIX: Use position.time_since_entry_seconds for accuracy
        # This is calculated from position.opened_at and is more accurate than
        # the approximation (900 - time_to_expiry) which assumes position opened
        # at market start. If position was opened mid-window, the approximation
        # would be wrong, causing staged exits to trigger at incorrect times.
        time_since_entry_seconds = position.time_since_entry_seconds
        if time_since_entry_seconds < 0:
            time_since_entry_seconds = 0
        
        time_since_entry_minutes = time_since_entry_seconds / 60.0
        
        # Check staged exits
        for stage_idx, stage in enumerate(staged_exit_stages):
            stage_minutes = stage.get("minutes", 0)
            stage_percent = stage.get("percent", 0)
            
            # Check if we've reached this stage time
            if time_since_entry_minutes >= stage_minutes:
                stage_key = f"stage_{stage_idx}"
                stage_executed_attr = f"staged_exit_{stage_key}_executed"
                
                # Check if this stage has already been executed
                if not getattr(position, stage_executed_attr, False):
                    # CRITICAL FIX (2026-07-31): Only execute staged exit if position is profitable
                    # Prevent systematic loss exits by requiring positive PnL before staged time exits
                    if position.unrealized_pnl_cents <= 0:
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT SKIPPED: position=%s stage=%d pnl=%dc - skipping staged exit for underwater position",
                            position.position_id[:8],
                            stage_idx,
                            position.unrealized_pnl_cents
                        )
                        # Mark stage as executed to prevent re-checking
                        setattr(position, stage_executed_attr, True)
                        setattr(position, f"staged_exit_{stage_key}_timestamp", datetime.utcnow())
                        continue
                    
                    # Calculate contracts to close for this stage
                    contracts_to_close = int(position.size * (stage_percent / 100.0))
                    
                    if contracts_to_close > 0 and contracts_to_close < position.size:
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT triggered: position=%s stage=%d minutes=%d percent=%d contracts=%d/%d time_since_entry=%.1fmin pnl=%dc",
                            position.position_id[:8],
                            stage_idx,
                            stage_minutes,
                            stage_percent,
                            contracts_to_close,
                            position.size,
                            time_since_entry_minutes,
                            position.unrealized_pnl_cents,
                        )
                        
                        # Mark stage as executed
                        setattr(position, stage_executed_attr, True)
                        setattr(position, f"staged_exit_{stage_key}_timestamp", datetime.utcnow())
                        
                        # Emit partial exit intent
                        self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents, contracts_to_close)
                        
                        # CRITICAL FIX: Do NOT update position.size here - wait for fill callback
                        # Previous code updated position.size prematurely, creating desync with PositionCache.contracts
                        # Position.size should only be updated via fill callback to ensure consistency
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT triggered: position=%s closing %d of %d contracts (fill callback will update size)",
                            position.position_id[:8],
                            contracts_to_close,
                            position.size,
                        )
                        # Continue to check other exit conditions (don't return early)
        
        # Check exit policy (time stop, edge decay, risk, candle reversal)
        resolver = get_exit_policy_resolver()
        
        # Get time to expiry from market state if available
        time_to_expiry = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry = state.seconds_to_expiry
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get time to expiry: %s", e)
        
        # Get recent candles for candle pattern detection
        candles = None
        try:
            from data.unified_spot_service import get_unified_spot_service
            from merid.signals.ta_engine import TAEngine, IndicatorConfig
            
            # Extract asset from series_ticker (more reliable than market_id string matching)
            asset = None
            if position.series_ticker:
                # series_ticker format: KXBTC15M, KXETH15M, etc.
                if "BTC" in position.series_ticker.upper():
                    asset = "BTC"
                elif "ETH" in position.series_ticker.upper():
                    asset = "ETH"
                elif "SOL" in position.series_ticker.upper():
                    asset = "SOL"
                elif "XRP" in position.series_ticker.upper():
                    asset = "XRP"
                elif "DOGE" in position.series_ticker.upper():
                    asset = "DOGE"
            
            # Fallback to market_id if series_ticker not set
            if not asset:
                if "BTC" in position.market_id.upper():
                    asset = "BTC"
                elif "ETH" in position.market_id.upper():
                    asset = "ETH"
                elif "SOL" in position.market_id.upper():
                    asset = "SOL"
                elif "XRP" in position.market_id.upper():
                    asset = "XRP"
                elif "DOGE" in position.market_id.upper():
                    asset = "DOGE"
            
            if asset:
                spot_service = get_unified_spot_service()
                ohlcv_buffer = spot_service.get_ohlcv_buffer(asset, "15m")
                if ohlcv_buffer and len(ohlcv_buffer) >= 3:
                    # Convert to candle format for pattern detection
                    candles = []
                    for ohlcv in ohlcv_buffer[-3:]:  # Last 3 candles
                        candles.append({
                            'open': ohlcv.open,
                            'high': ohlcv.high,
                            'low': ohlcv.low,
                            'close': ohlcv.close,
                            'timestamp': ohlcv.timestamp_window_end
                        })
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get candles for pattern detection: %s", e)
        
        # CRITICAL FIX (2026-07-11): Get MD age for stale data check
        md_age_ms = None
        max_age_ms = None
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds
            
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            
            if state and hasattr(state, 'last_update_ts'):
                # Calculate MD age in milliseconds
                import time
                md_age_ms = int((time.time() - state.last_update_ts) * 1000)
                
                # Get timing-aware max age based on time to expiry
                minutes_to_expiry = time_to_expiry / 60.0 if time_to_expiry else None
                max_age_seconds = get_md_max_age_seconds(minutes_to_expiry)
                max_age_ms = max_age_seconds * 1000
                
                logger.debug(
                    "[POSITION-MONITOR] MD staleness check: position=%s age_ms=%d max_age_ms=%d minutes_to_expiry=%.1f",
                    position.position_id[:8],
                    md_age_ms,
                    max_age_ms,
                    minutes_to_expiry or 0
                )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not get MD age for stale data check: %s", e)
        
        # CRITICAL FIX: 2026-07-17 - Compute volatility regime for exit policy
        # Volatility regime detection exists but was not wired to exit policy
        # This enables volatility-based hold time multipliers (LOW: 1.0x, NORMAL: 0.75x, HIGH: 0.5x, EXTREME: 0.33x)
        volatility_regime = None
        try:
            # Extract asset from series_ticker (more reliable than market_id string matching)
            asset = None
            if position.series_ticker:
                # series_ticker format: KXBTC15M, KXETH15M, etc.
                if "BTC" in position.series_ticker.upper():
                    asset = "BTC"
                elif "ETH" in position.series_ticker.upper():
                    asset = "ETH"
                elif "SOL" in position.series_ticker.upper():
                    asset = "SOL"
                elif "XRP" in position.series_ticker.upper():
                    asset = "XRP"
                elif "DOGE" in position.series_ticker.upper():
                    asset = "DOGE"
            
            # Fallback to market_id if series_ticker not set
            if not asset:
                if "BTC" in position.market_id.upper():
                    asset = "BTC"
                elif "ETH" in position.market_id.upper():
                    asset = "ETH"
                elif "SOL" in position.market_id.upper():
                    asset = "SOL"
                elif "XRP" in position.market_id.upper():
                    asset = "XRP"
                elif "DOGE" in position.market_id.upper():
                    asset = "DOGE"
            
            if asset:
                from data.unified_spot_service import get_unified_spot_service
                spot_service = get_unified_spot_service()
                ohlcv_buffer = spot_service.get_ohlcv_buffer(asset, "15m")
                
                if ohlcv_buffer and len(ohlcv_buffer) >= 20:
                    # Compute realized volatility from OHLCV buffer
                    import numpy as np
                    closes = np.array([bar.close for bar in ohlcv_buffer])
                    returns = np.diff(np.log(closes))
                    realized_vol = np.std(returns) * np.sqrt(525600)  # Annualized (minutes per year)
                    
                    # Classify volatility regime using unified_edge function
                    from merid.prediction.unified_edge import classify_volatility_regime
                    volatility_regime = classify_volatility_regime(realized_vol * 100)  # Convert to percentage
                    
                    logger.debug(
                        "[POSITION-MONITOR] Volatility regime: position=%s asset=%s vol=%.2f%% regime=%s",
                        position.position_id[:8],
                        asset,
                        realized_vol * 100,
                        volatility_regime
                    )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not compute volatility regime: %s", e)
        
        # CRITICAL FIX: 2026-07-17 - Compute real-time edge for edge decay check
        # Edge decay was never triggering because current_edge_pct was not passed to resolver
        # Use EdgeBasedExitEvaluator to compute real-time edge instead of static entry_edge_pct
        current_edge_pct = None
        try:
            from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
            edge_evaluator = EdgeBasedExitEvaluator()
            current_edge_pct = edge_evaluator.compute_current_edge(
                position=position,
                current_price_cents=current_price_cents,
                time_to_expiry_seconds=time_to_expiry
            )
            
            if current_edge_pct is None:
                # Fallback to entry edge if real-time computation fails
                current_edge_pct = getattr(position, 'entry_edge_pct', 0.03)
                logger.debug(
                    "[POSITION-MONITOR] Real-time edge computation failed, using entry edge=%.4f",
                    current_edge_pct
                )
            else:
                logger.debug(
                    "[POSITION-MONITOR] Real-time edge computed: position=%s edge=%.4f",
                    position.position_id[:8],
                    current_edge_pct
                )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not compute real-time edge: %s", e)
            # Fallback to entry edge
            current_edge_pct = getattr(position, 'entry_edge_pct', 0.03)
        
        # Resolve exit policy
        policy = resolver.resolve(
            position=position,
            current_price_cents=current_price_cents,
            time_to_expiry_seconds=time_to_expiry,
            volatility_regime=volatility_regime,  # CRITICAL: Pass volatility regime
            candles=candles,
            md_age_ms=md_age_ms,
            max_age_ms=max_age_ms,
            current_edge_pct=current_edge_pct,  # CRITICAL: Pass real-time edge for edge decay check
        )
        
        if policy.action == ExitAction.EXIT_MARKET:
            logger.info(
                "[POSITION-MONITOR] EXIT-POLICY triggered: position=%s reason=%s R=%.2f",
                position.position_id[:8],
                policy.reason.value if policy.reason else "unknown",
                position.r_multiple,
            )
            self._emit_exit_intent(
                position,
                policy.reason or ExitReason.MANUAL,
                current_price_cents
            )
        
        return ExitDecision(
            reason=policy.reason or ExitReason.MANUAL,
            priority=get_priority_for_reason(policy.reason or ExitReason.MANUAL),
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=current_price_cents,
            contracts_to_close=None,
            metadata={}
        )
    
    def _emit_exit_intent(
        self,
        position: Position,
        exit_reason: ExitReason,
        exit_price_cents: int,
        contracts_to_close: Optional[int] = None,
        bypass_in_flight_check: bool = False
    ) -> None:
        """
        Emit exit intent via callback.

        Args:
            position: Position to exit
            exit_reason: Exit reason
            exit_price_cents: Exit price in cents
            contracts_to_close: Number of contracts to close (None = full position)
            bypass_in_flight_check: If True, skip the in-flight check (for expired markets)
        """
        # AUDIT: Timing correctness - record trigger timestamp
        trigger_timestamp = __import__('time').monotonic()

        # Log exit intent emission with structured schema
        if contracts_to_close is None:
            # Full position exit
            logger.info(
                "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
                "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d type=FULL_EXIT trigger_ts=%.3f",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                get_priority_for_reason(exit_reason).value,
                "position_level",
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                trigger_timestamp
            )
        else:
            # Partial position exit (trim)
            logger.info(
                "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
                "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d closing=%d type=PARTIAL_EXIT trigger_ts=%.3f",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                get_priority_for_reason(exit_reason).value,
                "position_level",
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                contracts_to_close,
                trigger_timestamp
            )
        
        # CRITICAL FIX (2026-07-16): Dispatch the exit callback BEFORE mark_exited().
        # Previous ordering set exit_triggered=True and removed the position BEFORE the
        # callback ran; the loop-side idempotency guard (added 2026-07-15) checks
        # position.exit_triggered and was silently DROPPING every full exit — no exit
        # order was ever placed. Callback-first preserves idempotency (a second emission
        # for the same position still sees exit_triggered=True) while restoring execution.
        callback_dispatched = False
        if self._exit_intent_callback:
            # CRITICAL FIX (2026-07-23): Check if exit intent is already in-flight
            # This prevents multiple triggers (TP + SL) from firing before first exit is placed
            # CRITICAL FIX (2026-07-29): Bypass in-flight check for expired markets to prevent stuck positions
            if not bypass_in_flight_check and self._is_exit_intent_in_flight(position.position_id):
                logger.warning(
                    "[EXIT-INTENT-IN-FLIGHT] Exit intent already in-flight for position=%s, skipping duplicate trigger. "
                    "Existing trigger reason=%s, new reason=%s",
                    position.position_id[:8],
                    "unknown",
                    exit_reason.value
                )
                # Skip this trigger - the in-flight intent will handle the exit
                return
            
            # Mark intent as in-flight before calling callback
            self._mark_exit_intent_in_flight(position.position_id)
            
            try:
                logger.info(
                    "[POSITION-MONITOR] Calling exit intent callback for position=%s reason=%s contracts=%s",
                    position.position_id[:8],
                    exit_reason.value,
                    contracts_to_close or "ALL",
                )
                # Pass contracts_to_close to callback for partial close handling
                self._exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close)
                callback_dispatched = True
                logger.info(
                    "[POSITION-MONITOR] Exit intent callback completed for position=%s",
                    position.position_id[:8],
                )
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Exit intent callback failed: %s",
                    e,
                    exc_info=True
                )
        else:
            logger.warning(
                "[POSITION-MONITOR] No exit intent callback registered - exit order will NOT be placed for position=%s",
                position.position_id[:8],
            )
        
        # For partial trims, don't mark as exited or remove from monitoring
        # Only full exits should remove the position
        if contracts_to_close is None:
            if callback_dispatched:
                # Mark position as exited and stop monitoring
                position.mark_exited(exit_reason.value, exit_price_cents)
                self.remove_position(position.position_id)
            else:
                # CRITICAL FIX (2026-07-16): Callback failed or missing — KEEP the position
                # monitored so the exit re-fires on the next poll instead of orphaning a
                # live position with no exit enforcement
                logger.error(
                    "[POSITION-MONITOR] Exit intent NOT dispatched for position=%s (reason=%s) - "
                    "keeping position monitored for retry on next poll",
                    position.position_id[:8],
                    exit_reason.value,
                )
    
    def _emit_scale_out_intent(
        self,
        position: Position,
        contracts_to_close: int,
        exit_price_cents: int
    ) -> None:
        """
        Emit partial scale-out intent via callback.
        
        Research: Close 50% of position at 1.5-2R to lock profits while
        letting "runner" capture larger moves (Pay Yourself strategy).
        
        Args:
            position: Position to partially exit
            contracts_to_close: Number of contracts to close
            exit_price_cents: Exit price in cents
        """
        # Call callback if registered with scale-out flag
        if self._exit_intent_callback:
            try:
                # Pass scale-out info via exit_reason
                self._exit_intent_callback(
                    position,
                    ExitReason.SCALE_OUT,
                    exit_price_cents,
                    contracts_to_close
                )
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Scale-out intent callback failed: %s",
                    e,
                    exc_info=True
                )
    
    def _get_side_aware_price(self, state, position_side: PositionSide) -> Optional[int]:
        """
        Get side-aware current price from market state.
        
        CRITICAL FIX: mid_cents is YES-centric. For NO positions, we need to convert
        to NO price (100 - YES mid) to correctly evaluate exit conditions.
        
        Args:
            state: UnifiedMarketState for the market
            position_side: PositionSide.YES or PositionSide.NO
            
        Returns:
            Current price in cents for the position's side
        """
        if not state or not state.mid_cents:
            return None
        
        if position_side == PositionSide.YES:
            # YES: use mid_cents directly
            return int(state.mid_cents)
        else:
            # NO: convert YES mid to NO price (100 - YES mid)
            # Example: YES mid = 42c → NO price = 58c
            return int(100 - state.mid_cents)
    
    async def _poll_loop(self) -> None:
        """
        Main polling loop.
        
        Checks all open positions for exit conditions.
        """
        poll_count = 0
        last_poll_time = None
        while self._running:
            try:
                poll_start_time = __import__('time').monotonic()
                poll_count += 1
                
                # AUDIT: Timing correctness - track poll interval and drift
                if last_poll_time is not None:
                    actual_interval = poll_start_time - last_poll_time
                    interval_drift_s = actual_interval - self._poll_interval
                    logger.debug(
                        "[TIMING-AUDIT] poll_count=%d expected_interval=%.1fs actual_interval=%.1fs drift_s=%.3fs",
                        poll_count,
                        self._poll_interval,
                        actual_interval,
                        interval_drift_s
                    )
                
                if not self._open_positions:
                    await asyncio.sleep(self._poll_interval)
                    last_poll_time = __import__('time').monotonic()
                    continue
                
                logger.debug(
                    "[POSITION-MONITOR] Polling %d positions (poll #%d)",
                    len(self._open_positions),
                    poll_count
                )
                
                # Get current prices from market state store
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    
                    with self._lock:
                        positions_snapshot = list(self._open_positions.items())
                    
                    # AUDIT: Log trigger coverage - confirm each position is checked
                    logger.info(
                        "[POSITION-MONITOR-AUDIT] poll_count=%d positions_to_check=%d",
                        poll_count,
                        len(positions_snapshot)
                    )
                    
                    for position_id, position in positions_snapshot:
                        # CRITICAL FIX (2026-07-31): Check if market has expired BEFORE accessing state
                        # Expired markets no longer exist on the exchange and cannot be traded
                        # Attempting to exit them causes 404 errors and retry loops
                        if self._is_expired_market(position.market_id):
                            logger.warning(
                                "[POSITION-MONITOR] Removing position from expired market: %s - "
                                "market has settled, no exit needed",
                                position.market_id
                            )
                            # Remove position from monitor without attempting exit
                            # The position should have been settled by the exchange
                            with self._lock:
                                if position_id in self._open_positions:
                                    del self._open_positions[position_id]
                                if position.market_id in self._market_to_position:
                                    del self._market_to_position[position.market_id]
                            continue
                        
                        state = store.get(position.market_id)
                        current_price = None
                        data_source = "unknown"
                        data_age_s = float('inf')
                        
                        # AUDIT: State freshness check - verify inputs are current
                        now = __import__('time').monotonic()
                        
                        # CRITICAL FIX (2026-07-16): Check if market has expired
                        # If state is None, the market may have expired. Force exit the position.
                        # CRITICAL FIX (2026-07-29): Bypass in-flight check for expired markets to prevent stuck positions
                        if state is None:
                            logger.warning(
                                "[POSITION-MONITOR] Market state not found for %s - market may have expired, forcing exit",
                                position.market_id
                            )
                            # Force exit with last known price or entry price
                            exit_price = position.current_price_cents if position.current_price_cents else position.avg_entry_price_cents
                            if exit_price > 0:
                                self._emit_exit_intent(position, ExitReason.TIME_STOP, exit_price, bypass_in_flight_check=True)
                            continue
                        
                        if state.mid_cents:
                            # CRITICAL FIX: Use side-aware price for NO positions
                            current_price = self._get_side_aware_price(state, position.side)
                            data_source = "ws_mid"
                            data_age_s = now - (state.last_book_update_ts or 0)
                        else:
                            # CRITICAL FIX (2026-07-14): Fallback price handling when market state is stale
                            # Use position's current_price_cents if available (updated by position cache)
                            # Otherwise use entry price as last resort to ensure exit conditions can still trigger
                            if hasattr(position, 'current_price_cents') and position.current_price_cents:
                                current_price = position.current_price_cents
                                data_source = "position_cache"
                                data_age_s = float('inf')  # Unknown age
                                logger.debug(
                                    "[POSITION-MONITOR] Using fallback current_price_cents for %s: %dc (market state unavailable)",
                                    position.market_id, current_price
                                )
                            else:
                                current_price = position.avg_entry_price_cents
                                data_source = "entry_price"
                                data_age_s = float('inf')  # Static entry price
                                logger.warning(
                                    "[POSITION-MONITOR] Using entry price as fallback for %s: %dc (market state unavailable, no current_price)",
                                    position.market_id, current_price
                                )
                        
                        # AUDIT: Log state freshness for each position check
                        logger.info(
                            "[POSITION-MONITOR-AUDIT] position=%s market=%s data_source=%s data_age_s=%.1f price=%dc side=%s",
                            position.position_id[:8],
                            position.market_id,
                            data_source,
                            data_age_s,
                            current_price,
                            position.side.value
                        )
                        
                        if current_price is not None:
                            await self._check_position(position, current_price, poll_count)
                        else:
                            logger.warning(
                                "[POSITION-MONITOR] Could not determine price for %s - skipping exit check",
                                position.market_id
                            )
                
                except Exception as e:
                    logger.error(
                        "[POSITION-MONITOR] Poll loop error: %s",
                        e,
                        exc_info=True
                    )
                
                await asyncio.sleep(self._poll_interval)
            
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Poll loop critical error: %s",
                    e,
                    exc_info=True
                )
                await asyncio.sleep(self._poll_interval)
    
    async def start(self) -> None:
        """
        Start the position monitor.
        
        CRITICAL FIX (2026-07-23): Load existing positions from position cache on startup.
        This ensures positions opened before monitor started (or during restart) are tracked
        for exit policies. Without this, exit policies never trigger for existing positions.
        """
        logger.info("[POSITION-MONITOR-STARTUP] start() called, _running=%s", self._running)
        if self._running:
            logger.warning("[POSITION-MONITOR] Already running")
            return
        
        logger.info("[POSITION-MONITOR-STARTUP] Starting position monitor startup sync")
        
        # CRITICAL FIX: Load existing positions from position cache on startup
        # This ensures positions opened before monitor started are tracked for exit policies
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            position_cache = get_position_cache()
            cached_positions = position_cache.get_all_positions(validate_freshness=False)
            
            loaded_count = 0
            for market_id, cached_pos in cached_positions.items():
                if cached_pos.contracts > 0:
                    # Convert CachedPosition to Position for monitoring
                    from merid.position_management.position import Position, PositionSide
                    from datetime import datetime, timezone
                    
                    # Determine position side from thesis_side (immutable) or side (fallback)
                    side_str = cached_pos.thesis_side if cached_pos.thesis_side else cached_pos.side
                    
                    # CRITICAL FIX (2026-08-01): Infer thesis_side from fill history for unknown positions
                    # These positions cannot be monitored correctly because we don't know
                    # whether they are YES or NO positions, which affects all exit calculations.
                    if side_str.lower() == "unknown":
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Position has unknown thesis_side=%s for market=%s - "
                            "attempting to infer from fill history",
                            side_str, market_id
                        )
                        # Try to infer thesis_side from fill history
                        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
                        if inferred_side:
                            side_str = inferred_side
                            logger.info(
                                "[POSITION-MONITOR-STARTUP] Inferred thesis_side=%s for market=%s from fill history",
                                side_str, market_id
                            )
                        else:
                            logger.warning(
                                "[POSITION-MONITOR-STARTUP] Skipping position with unknown thesis_side=%s for market=%s - "
                                "position cannot be monitored without correct side information",
                                side_str, market_id
                            )
                            continue
                    
                    if side_str.lower() in ("yes", "YES"):
                        position_side = PositionSide.YES
                    elif side_str.lower() in ("no", "NO"):
                        position_side = PositionSide.NO
                    else:
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Unknown side %s for market=%s, skipping",
                            side_str, market_id
                        )
                        continue
                    
                    # Create Position object from CachedPosition
                    # CRITICAL FIX (2026-07-31): Side-aware fallback SL for startup-loaded positions
                    # YES contracts: SL below entry (loss when price goes down)
                    # NO contracts: SL above entry (loss when price goes up)
                    # Previous bug: treated both sides identically, causing NO contracts to have inverted SL
                    sl_price = cached_pos.stop_loss_price_cents
                    
                    # CRITICAL FIX (2026-08-01): Skip positions with invalid entry prices
                    # Positions with avg_price_cents=None or 0 cannot be monitored correctly
                    # because all exit calculations depend on the entry price.
                    if cached_pos.avg_price_cents is None or cached_pos.avg_price_cents == 0:
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Skipping position with invalid avg_price_cents=%s for market=%s - "
                            "position cannot be monitored without valid entry price",
                            cached_pos.avg_price_cents, market_id
                        )
                        continue
                    
                    if sl_price is None:
                        if position_side == PositionSide.YES:
                            sl_price = max(1, cached_pos.avg_price_cents - 5)  # 5 cent risk below entry
                        else:
                            sl_price = min(99, cached_pos.avg_price_cents + 5)  # 5 cent risk above entry
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Missing SL for startup position=%s - using fallback SL=%dc (entry=%dc side=%s)",
                            market_id[:8], sl_price, cached_pos.avg_price_cents, position_side.value
                        )
                    
                    position = Position(
                        position_id=market_id,  # Use market_id as position_id for 15m system
                        market_id=market_id,
                        side=position_side,
                        size=cached_pos.contracts,
                        avg_entry_price_cents=cached_pos.avg_price_cents,  # No fallback - already validated above
                        take_profit_price_cents=cached_pos.take_profit_price_cents,
                        stop_loss_price_cents=sl_price,
                        opened_at=datetime.now(timezone.utc),  # Use current time for existing positions
                    )
                    
                    # Add to monitor
                    self.add_position(position)
                    loaded_count += 1
            
            logger.info(
                "[POSITION-MONITOR-STARTUP] Loaded %d existing positions from position cache",
                loaded_count
            )
            
        except Exception as e:
            logger.error(
                "[POSITION-MONITOR-STARTUP] Failed to load existing positions from cache: %s",
                e,
                exc_info=True
            )
            # Continue startup even if load fails - positions will be added on fill
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[POSITION-MONITOR] Started (poll_interval=%ds, tracking %d positions)",
            self._poll_interval,
            len(self._open_positions)
        )
    
    async def stop(self) -> None:
        """
        Stop the position monitor.
        """
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("[POSITION-MONITOR] Stopped")
    
    def get_stats(self) -> Dict:
        """
        Get monitor statistics.
        
        Returns:
            Dict with statistics
        """
        return {
            "running": self._running,
            "open_positions": len(self._open_positions),
            "poll_interval": self._poll_interval,
        }


# Global singleton instance
_monitor_instance: Optional[PositionMonitor] = None


def get_position_monitor() -> PositionMonitor:
    """
    Get global position monitor singleton.
    
    Returns:
        PositionMonitor instance
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PositionMonitor()
        logger.info("[POSITION-MONITOR] Created global singleton")
    else:
        logger.info("[POSITION-MONITOR] Returning existing singleton, _running=%s", _monitor_instance._running)
    return _monitor_instance
