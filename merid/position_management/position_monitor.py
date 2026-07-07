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
        if position.should_trigger_extreme_profit(current_price_cents) and not position.exit_triggered:
            logger.info(
                "[POSITION-MONITOR] EXTREME-PROFIT triggered: position=%s price=%dc (99c YES / 1c NO) - locking guaranteed win",
                position.position_id[:8],
                current_price_cents,
            )
            self._emit_exit_intent(position, ExitReason.EXTREME_PROFIT, current_price_cents)
            return
        
        # DYNAMIC TAKE PROFIT: Laddered exits based on entry price for consistent profits
        # 2026-07-06: Implements user's strategy for frequent small wins
        # Entry 25-30c → Exit 50-60c, Entry 30-40c → Exit 60-70c, etc.
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
                                
                                # Adjust for NO positions (mirror logic)
                                if position.side == PositionSide.NO:
                                    position.dynamic_tp_target_cents = 100 - base_target
                                else:
                                    position.dynamic_tp_target_cents = base_target
                                
                                # CRITICAL FIX: 2026-07-07 - Add user communication for infeasible TP targets due to fees
                                # Check if target is feasible after fees
                                try:
                                    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
                                    
                                    # Calculate gross profit
                                    if position.side == PositionSide.YES:
                                        gross_profit = (position.dynamic_tp_target_cents - entry_price) * position.size
                                    else:
                                        gross_profit = (entry_price - position.dynamic_tp_target_cents) * position.size
                                    
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
                    if position.dynamic_tp_target_cents is not None and not position.dynamic_tp_triggered and not position.exit_triggered:
                        if position.side == PositionSide.YES and current_price_cents >= position.dynamic_tp_target_cents:
                            position.dynamic_tp_triggered = True
                            logger.info(
                                "[POSITION-MONITOR] DYNAMIC-TP triggered: position=%s price=%dc target=%dc (YES target reached)",
                                position.position_id[:8],
                                current_price_cents,
                                position.dynamic_tp_target_cents,
                            )
                            self._emit_exit_intent(position, ExitReason.DYNAMIC_TAKE_PROFIT, current_price_cents)
                            return
                        elif position.side == PositionSide.NO and current_price_cents <= position.dynamic_tp_target_cents:
                            position.dynamic_tp_triggered = True
                            logger.info(
                                "[POSITION-MONITOR] DYNAMIC-TP triggered: position=%s price=%dc target=%dc (NO target reached)",
                                position.position_id[:8],
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
                    if trim_enabled and not position.ratchet_trimmed and not position.exit_triggered:
                        if position.size > trim_to_contracts:
                            if position.side == PositionSide.YES and current_price_cents >= trim_threshold:
                                position.ratchet_trimmed = True
                                # Emit trim intent (partial close)
                                contracts_to_close = position.size - trim_to_contracts
                                logger.info(
                                    "[POSITION-MONITOR] RATCHET-TRIM triggered: position=%s price=%dc size=%d -> trim to %d contracts (close %d)",
                                    position.position_id[:8],
                                    current_price_cents,
                                    position.size,
                                    trim_to_contracts,
                                    contracts_to_close,
                                )
                                self._emit_exit_intent(position, ExitReason.RATCHET_TRIM, current_price_cents, contracts_to_close)
                                # Update position size after trim (don't remove from monitoring)
                                position.size = trim_to_contracts
                                # CRITICAL: Continue to check other exit conditions (don't return early)
                            elif position.side == PositionSide.NO and current_price_cents <= (100 - trim_threshold):
                                position.ratchet_trimmed = True
                                contracts_to_close = position.size - trim_to_contracts
                                logger.info(
                                    "[POSITION-MONITOR] RATCHET-TRIM triggered: position=%s price=%dc size=%d -> trim to %d contracts (close %d)",
                                    position.position_id[:8],
                                    current_price_cents,
                                    position.size,
                                    trim_to_contracts,
                                    contracts_to_close,
                                )
                                self._emit_exit_intent(position, ExitReason.RATCHET_TRIM, current_price_cents, contracts_to_close)
                                # Update position size after trim (don't remove from monitoring)
                                position.size = trim_to_contracts
                                # CRITICAL: Continue to check other exit conditions (don't return early)
                    
                    # Activate ratchet when price hits threshold
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double activation
                    if not position.ratchet_activated and not position.exit_triggered:
                        if position.side == PositionSide.YES and current_price_cents >= activation_threshold:
                            position.ratchet_activated = True
                            position.ratchet_hold_until = datetime.utcnow().timestamp() + profile.ratchet_min_hold_after_activation_sec
                            logger.info(
                                "[POSITION-MONITOR] RATCHET activated: position=%s price=%dc threshold=%dc floor=%dc",
                                position.position_id[:8],
                                current_price_cents,
                                activation_threshold,
                                floor_price,
                            )
                        elif position.side == PositionSide.NO and current_price_cents <= (100 - activation_threshold):
                            position.ratchet_activated = True
                            position.ratchet_hold_until = datetime.utcnow().timestamp() + profile.ratchet_min_hold_after_activation_sec
                            logger.info(
                                "[POSITION-MONITOR] RATCHET activated: position=%s price=%dc threshold=%dc floor=%dc",
                                position.position_id[:8],
                                current_price_cents,
                                100 - activation_threshold,
                                100 - floor_price,
                            )
                    
                    # Check floor breach after activation and hold period
                    # CRITICAL FIX: 2026-07-07 - REMOVED hold period bypass to prevent noise-triggered exits
                    # Previous logic bypassed hold period when in profit zone, defeating its purpose
                    # Now only allow exit when hold period expires to prevent premature exits
                    if position.ratchet_activated:
                        hold_expired = datetime.utcnow().timestamp() >= position.ratchet_hold_until
                        can_exit = hold_expired  # Exit ONLY if hold period expired
                        
                        if can_exit:
                            # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
                            if position.side == PositionSide.YES and current_price_cents <= floor_price and not position.exit_triggered:
                                if force_exit:
                                    logger.info(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s price=%dc floor=%dc - mandatory exit (hold_period=expired)",
                                        position.position_id[:8],
                                        current_price_cents,
                                        floor_price,
                                    )
                                    self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
                                    return
                                else:
                                    logger.warning(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s price=%dc floor=%dc (exit not forced)",
                                        position.position_id[:8],
                                        current_price_cents,
                                        floor_price,
                                    )
                            elif position.side == PositionSide.NO and current_price_cents >= (100 - floor_price) and not position.exit_triggered:
                                if force_exit:
                                    logger.info(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s price=%dc floor=%dc - mandatory exit (hold_period=expired)",
                                        position.position_id[:8],
                                        current_price_cents,
                                        100 - floor_price,
                                    )
                                    self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
                                    return
                                else:
                                    logger.warning(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s price=%dc floor=%dc (exit not forced)",
                                        position.position_id[:8],
                                        current_price_cents,
                                        100 - floor_price,
                                    )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Ratchet profit floor check failed: %s", e)
        
        # Check TP/SL next
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
        # Activate trailing after min_profit_cents from profile (default 12 cents, align with 2026 research)
        # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing (2c distance) when price crosses 80c profit zone
        if not position.trailing_activated:
            # Check if position has minimum profit to activate trailing
            min_profit_cents = 12  # Default from profile (align with 2026 research)
            profit_zone_activation_cents = 80  # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing at 80c
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    min_profit_cents = profile.trailing_stop_min_profit_cents
                    profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
            except Exception as e:
                logger.debug("[POSITION-MONITOR] Could not read trailing config from profile: %s", e)
            
            # Calculate current profit in cents
            if position.side == PositionSide.YES:
                profit_cents = current_price_cents - position.avg_entry_price_cents
            else:
                profit_cents = position.avg_entry_price_cents - current_price_cents
            
            # Activate trailing if minimum profit threshold reached
            if profit_cents >= min_profit_cents:
                position.trailing_activated = True
                # CRITICAL FIX: 2026-07-06 - Check if in profit zone (80c for YES, 20c for NO)
                in_profit_zone = False
                if position.side == PositionSide.YES and current_price_cents >= profit_zone_activation_cents:
                    in_profit_zone = True
                    position.trailing_profit_zone_activated = True
                elif position.side == PositionSide.NO and current_price_cents <= (100 - profit_zone_activation_cents):
                    in_profit_zone = True
                    position.trailing_profit_zone_activated = True
                
                if in_profit_zone:
                    logger.info(
                        "[POSITION-MONITOR] TRAILING activated (AGGRESSIVE 2c mode): position=%s price=%dc profit=%dc R=%.2f - in 80-85c profit zone",
                        position.position_id[:8],
                        current_price_cents,
                        profit_cents,
                        position.r_multiple,
                    )
                else:
                    logger.info(
                        "[POSITION-MONITOR] TRAILING activated (normal 5c mode): position=%s price=%dc profit=%dc R=%.2f threshold=%dc",
                        position.position_id[:8],
                        current_price_cents,
                        profit_cents,
                        position.r_multiple,
                        min_profit_cents,
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
                
                if position.side == PositionSide.YES and current_price_cents >= profit_zone_activation_cents:
                    position.trailing_profit_zone_activated = True
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to AGGRESSIVE 2c mode: position=%s price=%dc - entered 80-85c profit zone",
                        position.position_id[:8],
                        current_price_cents,
                    )
                elif position.side == PositionSide.NO and current_price_cents <= (100 - profit_zone_activation_cents):
                    position.trailing_profit_zone_activated = True
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to AGGRESSIVE 2c mode: position=%s price=%dc - entered 80-85c profit zone",
                        position.position_id[:8],
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
                
                if position.side == PositionSide.YES and current_price_cents < profit_zone_deactivation_cents:
                    position.trailing_profit_zone_activated = False
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to NORMAL 5c mode: position=%s price=%dc - exited profit zone (hysteresis)",
                        position.position_id[:8],
                        current_price_cents,
                    )
                elif position.side == PositionSide.NO and current_price_cents > (100 - profit_zone_deactivation_cents):
                    position.trailing_profit_zone_activated = False
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to NORMAL 5c mode: position=%s price=%dc - exited profit zone (hysteresis)",
                        position.position_id[:8],
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
        
        # CRITICAL FIX: 2026-07-07 - Staged time-based exits
        # Re-implemented from position_cache with proper callback routing
        # This ensures proper agent_id, swing mode logic, and exit intent callback error handling
        # Staged exits close partial positions at predefined time intervals
        staged_exit_stages = [
            {"minutes": 5, "percent": 25},   # Close 25% at 5 minutes
            {"minutes": 10, "percent": 25},  # Close another 25% at 10 minutes
            {"minutes": 13, "percent": 50},  # Close remaining 50% at 13 minutes
        ]
        
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
        
        # Calculate time since entry (approximate for 15m window)
        time_since_entry_seconds = 900.0 - time_to_expiry_seconds
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
                    # Calculate contracts to close for this stage
                    contracts_to_close = int(position.size * (stage_percent / 100.0))
                    
                    if contracts_to_close > 0 and contracts_to_close < position.size:
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT triggered: position=%s stage=%d minutes=%d percent=%d contracts=%d/%d time_since_entry=%.1fmin",
                            position.position_id[:8],
                            stage_idx,
                            stage_minutes,
                            stage_percent,
                            contracts_to_close,
                            position.size,
                            time_since_entry_minutes,
                        )
                        
                        # Mark stage as executed
                        setattr(position, stage_executed_attr, True)
                        setattr(position, f"staged_exit_{stage_key}_timestamp", datetime.utcnow())
                        
                        # Emit partial exit intent
                        self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents, contracts_to_close)
                        
                        # Update position size after trim (don't remove from monitoring)
                        position.size -= contracts_to_close
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT trimmed position: position=%s new_size=%d closed=%d",
                            position.position_id[:8],
                            position.size,
                            contracts_to_close,
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
        exit_price_cents: int,
        contracts_to_close: Optional[int] = None
    ) -> None:
        """
        Emit exit intent via callback.
        
        Args:
            position: Position to exit
            exit_reason: Exit reason
            exit_price_cents: Exit price in cents
            contracts_to_close: Number of contracts to close (None = full position)
        """
        # Log exit intent emission
        if contracts_to_close is None:
            # Full position exit
            logger.info(
                "[POSITION-MONITOR] EMITTING EXIT INTENT: position=%s market=%s side=%s reason=%s exit_price=%dc "
                "entry_price=%dc pnl=%dc R=%.2f size=%d (FULL EXIT)",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
            )
        else:
            # Partial position exit (trim)
            logger.info(
                "[POSITION-MONITOR] EMITTING EXIT INTENT: position=%s market=%s side=%s reason=%s exit_price=%dc "
                "entry_price=%dc pnl=%dc R=%.2f size=%d -> close %d (PARTIAL TRIM)",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                contracts_to_close,
            )
        
        # For partial trims, don't mark as exited or remove from monitoring
        # Only full exits should remove the position
        if contracts_to_close is None:
            # Mark position as exited
            position.mark_exited(exit_reason.value, exit_price_cents)
            
            # Remove from monitoring
            self.remove_position(position.position_id)
        
        # Call callback if registered
        if self._exit_intent_callback:
            try:
                logger.info(
                    "[POSITION-MONITOR] Calling exit intent callback for position=%s reason=%s contracts=%s",
                    position.position_id[:8],
                    exit_reason.value,
                    contracts_to_close or "ALL",
                )
                # Pass contracts_to_close to callback for partial close handling
                self._exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close)
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
                            # CRITICAL FIX: Use side-aware price for NO positions
                            current_price = self._get_side_aware_price(state, position.side)
                            if current_price is not None:
                                await self._check_position(position, current_price)
                            else:
                                logger.debug(
                                    "[POSITION-MONITOR] Could not get side-aware price for %s",
                                    position.market_id
                                )
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
