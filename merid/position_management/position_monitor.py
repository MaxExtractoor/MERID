"""
Position monitor for swing trading exit management.

Tracks open positions, computes PnL, and enforces TP/SL exits.
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Dict, Optional
from merid.position_management.position import Position, PositionSide, TrailingType
from merid.position_management.exit_policy import ExitAction, ExitReason
from merid.position_management.exit_policy_resolver import get_exit_policy_resolver

logger = logging.getLogger(__name__)


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
            "[POSITION-MONITOR] Added position: %s market=%s side=%s size=%d entry=%dc TP=%dc SL=%dc",
            position.position_id[:8],
            position.market_id,
            position.side,
            position.size,
            position.avg_entry_price_cents,
            position.take_profit_price_cents or 0,
            position.stop_loss_price_cents or 0,
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
    
    async def _check_position(self, position: Position, current_price_cents: int) -> None:
        """
        Check a single position for exit conditions.
        
        Args:
            position: Position to check
            current_price_cents: Current market price in cents
        """
        # Update runtime state
        position.update_runtime_state(current_price_cents)
        
        # Check TP/SL first (highest priority)
        if position.should_trigger_stop_loss(current_price_cents):
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
        if position.should_trigger_scale_out(current_price_cents):
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
        
        # CRITICAL FIX: Activate trailing stop after minimum profit threshold (not 1R)
        # For 15-minute binary options, waiting for 1R break-even is too conservative
        # Many trades never reach 1R before reversing, causing avoidable losses
        # Activate trailing after min_profit_cents from profile (default 3 cents)
        if not position.trailing_activated:
            # Check if position has minimum profit to activate trailing
            min_profit_cents = 3  # Default from profile
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    min_profit_cents = profile.trailing_stop_min_profit_cents
            except Exception as e:
                logger.debug("[POSITION-MONITOR] Could not read min_profit_cents from profile: %s", e)
            
            # Calculate current profit in cents
            if position.side == PositionSide.YES:
                profit_cents = current_price_cents - position.avg_entry_price_cents
            else:
                profit_cents = position.avg_entry_price_cents - current_price_cents
            
            # Activate trailing if minimum profit threshold reached
            if profit_cents >= min_profit_cents:
                position.trailing_activated = True
                logger.info(
                    "[POSITION-MONITOR] TRAILING activated: position=%s price=%dc profit=%dc R=%.2f threshold=%dc",
                    position.position_id[:8],
                    current_price_cents,
                    profit_cents,
                    position.r_multiple,
                    min_profit_cents,
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
        
        # Check exit policy (time stop, edge decay, risk, candle reversal)
        resolver = get_exit_policy_resolver()
        
        # Get time to expiry from market state if available
        time_to_expiry = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.minutes_to_expiry:
                time_to_expiry = state.minutes_to_expiry * 60.0
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not get time to expiry: %s", e)
        
        # Get recent candles for candle pattern detection
        candles = None
        try:
            from merid.data.unified_spot_service import get_unified_spot_service
            from merid.signals.ta_engine import TAEngine, IndicatorConfig
            
            # Get asset from market_id
            asset = None
            if "BTC" in position.market_id:
                asset = "BTC"
            elif "ETH" in position.market_id:
                asset = "ETH"
            elif "SOL" in position.market_id:
                asset = "SOL"
            elif "XRP" in position.market_id:
                asset = "XRP"
            elif "DOGE" in position.market_id:
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
            logger.debug("[POSITION-MONITOR] Could not get candles for pattern detection: %s", e)
        
        # Resolve exit policy
        policy = resolver.resolve(
            position=position,
            current_price_cents=current_price_cents,
            time_to_expiry_seconds=time_to_expiry,
            volatility_regime=None,  # TODO: add volatility regime
            candles=candles,
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
    
    def _emit_exit_intent(
        self,
        position: Position,
        exit_reason: ExitReason,
        exit_price_cents: int
    ) -> None:
        """
        Emit exit intent via callback.
        
        Args:
            position: Position to exit
            exit_reason: Exit reason
            exit_price_cents: Exit price in cents
        """
        # Mark position as exited
        position.mark_exited(exit_reason.value, exit_price_cents)
        
        # Remove from monitoring
        self.remove_position(position.position_id)
        
        # Call callback if registered
        if self._exit_intent_callback:
            try:
                self._exit_intent_callback(position, exit_reason, exit_price_cents)
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Exit intent callback failed: %s",
                    e,
                    exc_info=True
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
    
    async def _poll_loop(self) -> None:
        """
        Main polling loop.
        
        Checks all open positions for exit conditions.
        """
        while self._running:
            try:
                if not self._open_positions:
                    await asyncio.sleep(self._poll_interval)
                    continue
                
                logger.debug(
                    "[POSITION-MONITOR] Polling %d positions",
                    len(self._open_positions)
                )
                
                # Get current prices from market state store
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    
                    with self._lock:
                        positions_snapshot = list(self._open_positions.items())
                    
                    for position_id, position in positions_snapshot:
                        state = store.get(position.market_id)
                        if state and state.mid_cents:
                            current_price = state.mid_cents
                            await self._check_position(position, current_price)
                        else:
                            logger.debug(
                                "[POSITION-MONITOR] No market state for %s",
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
        """
        if self._running:
            logger.warning("[POSITION-MONITOR] Already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[POSITION-MONITOR] Started (poll_interval=%ds)",
            self._poll_interval
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
    return _monitor_instance
