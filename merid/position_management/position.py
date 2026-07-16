"""
Position model for swing trading exit management.

Tracks open positions with TP/SL, trailing stops, and exit policy references.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class PositionSide(str, Enum):
    """Position side for binary contracts."""
    YES = "yes"
    NO = "no"


class TrailingType(str, Enum):
    """Trailing stop type."""
    NONE = "none"
    PERCENT = "percent"
    R_MULTIPLE = "r_multiple"
    FIXED_CENTS = "fixed_cents"  # Fixed cent stop (e.g., 5 cents)


@dataclass
class Position:
    """
    Position model for swing trading exit management.
    
    Separated from orders to track PnL and exit logic independently.
    Populated from OrderIntent once a fill is confirmed via RestingOrderMonitor.
    """
    # Identity
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    market_id: str = ""
    series_ticker: str = ""  # e.g., KXBTC15M
    
    # Position details
    side: PositionSide = PositionSide.YES
    size: int = 0  # Number of contracts
    avg_entry_price_cents: int = 0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    
    # Exit targets
    take_profit_price_cents: Optional[int] = None
    take_profit_r_multiple: Optional[float] = None
    stop_loss_price_cents: Optional[int] = None
    
    # Break-even tracking (research: move SL to entry at 1R for capital preservation)
    break_even_triggered: bool = False
    break_even_price_cents: Optional[int] = None  # Entry price when break-even triggered
    
    # Partial scale-out tracking (research: close 50% at 1.5-2R, trail remainder)
    scale_out_price_cents: Optional[int] = None  # Price at which to scale out 50%
    scale_out_triggered: bool = False
    scale_out_remaining_size: int = 0  # Size after scale-out
    
    # Trailing stop configuration
    trailing_type: TrailingType = TrailingType.NONE
    trailing_param: float = 0.0  # e.g., 1.0 R or 1% trail
    max_favorable_price_cents: int = 0  # Updated as price moves favorably
    trailing_activated: bool = False  # Research: activate trailing after min_profit_cents (12¢ per 2026 research)
    trailing_profit_zone_activated: bool = False  # CRITICAL FIX: 2026-07-06 - Aggressive trailing in 80-85c zone
    
    # Policy references
    window_resolution_id: str = ""
    exit_policy_id: str = ""
    
    # Runtime state (not persisted)
    current_price_cents: int = 0
    unrealized_pnl_cents: int = 0
    r_multiple: float = 0.0
    time_since_entry_seconds: float = 0.0
    trailing_profit_threshold_reached_at: Optional[float] = None  # Timestamp when profit threshold was reached (for activation delay) - runtime only
    
    # Exit tracking
    exit_triggered: bool = False
    exit_reason: Optional[str] = None
    exit_price_cents: Optional[int] = None
    exited_at: Optional[datetime] = None
    
    # Ratchet profit floor tracking (2026-07-05)
    ratchet_activated: bool = False
    ratchet_hold_until: float = 0.0  # Timestamp until which to hold after activation
    ratchet_trimmed: bool = False  # Track if position has been trimmed
    
    # Dynamic take profit tracking (2026-07-06)
    dynamic_tp_target_cents: Optional[int] = None  # Dynamic take profit target based on entry price
    dynamic_tp_triggered: bool = False  # Track if dynamic TP has been triggered
    entry_edge_pct: float = 0.03  # Edge percentage at entry (default 3% for dynamic TP adjustment)
    
    # Staged time-based exit tracking (2026-07-07)
    staged_exit_stage_0_executed: bool = False  # Track if stage 0 has been executed
    staged_exit_stage_1_executed: bool = False  # Track if stage 1 has been executed
    staged_exit_stage_2_executed: bool = False  # Track if stage 2 has been executed
    staged_exit_stage_0_timestamp: Optional[datetime] = None  # When stage 0 was executed
    staged_exit_stage_1_timestamp: Optional[datetime] = None  # When stage 1 was executed
    staged_exit_stage_2_timestamp: Optional[datetime] = None  # When stage 2 was executed
    
    # Initial risk for R-multiple calculation
    initial_risk_cents: int = 0  # |entry_price - stop_loss_price| if stop_loss set
    
    def __post_init__(self):
        """Calculate initial risk after initialization."""
        if self.stop_loss_price_cents and self.avg_entry_price_cents:
            self.initial_risk_cents = abs(self.avg_entry_price_cents - self.stop_loss_price_cents)
    
    def update_runtime_state(
        self,
        current_price_cents: int,
        now: Optional[datetime] = None
    ) -> None:
        """
        Update runtime state (PnL, R-multiple, time since entry).
        
        Args:
            current_price_cents: Current market price in cents
            now: Current timestamp (defaults to utcnow)
        """
        if now is None:
            now = datetime.utcnow()
        
        self.current_price_cents = current_price_cents
        self.time_since_entry_seconds = (now - self.opened_at).total_seconds()
        
        # Calculate unrealized PnL
        # CRITICAL FIX (2026-07-16): SIDE-SPACE convention. Entry price (from fills ledger)
        # and current price (from _get_side_aware_price) are BOTH in the position's own
        # side space (YES cents for YES positions, NO cents for NO positions).
        # A position is always LONG its own side, so profit = own-side price rising.
        # The previous NO branch assumed YES-space current price and inverted NO PnL.
        self.unrealized_pnl_cents = (current_price_cents - self.avg_entry_price_cents) * self.size
        
        # Calculate R-multiple (PnL per unit of risk)
        if self.initial_risk_cents > 0:
            self.r_multiple = self.unrealized_pnl_cents / self.initial_risk_cents
        elif self.avg_entry_price_cents > 0:
            # If no stop loss set, use entry price as risk proxy
            self.r_multiple = self.unrealized_pnl_cents / self.avg_entry_price_cents
        else:
            # Both initial_risk_cents and avg_entry_price_cents are 0 - cannot calculate R-multiple
            self.r_multiple = 0.0
        
        # Update max favorable price for trailing stops
        # CRITICAL FIX (2026-07-16): Side-space — favorable = higher own-side price for BOTH sides
        if current_price_cents > self.max_favorable_price_cents:
            self.max_favorable_price_cents = current_price_cents
    
    def get_trail_level(self) -> Optional[int]:
        """
        Calculate current trailing stop level.
        
        Research: Apply time-based tightening as expiry approaches.
        As time to expiry decreases, reduce trail distance to lock in gains.
        
        Research: Apply volatility-based adjustment using ATR.
        Higher volatility = wider stops, lower volatility = tighter stops.
        
        Returns:
            Trailing stop price in cents, or None if trailing not active
        """
        if self.trailing_type == TrailingType.NONE:
            return None
        
        if self.max_favorable_price_cents == 0:
            return None
        
        # Research: Time-based trailing tightening
        # Reduce trail distance as expiry approaches to lock in gains
        trailing_param = self.trailing_param
        if self.time_since_entry_seconds > 0:
            # Calculate time-to-expiry factor (0.0 = expired, 1.0 = full time)
            # Default 15m window: tighten in last 5 minutes
            time_window = 900.0  # 15 minutes
            time_remaining = max(0, time_window - self.time_since_entry_seconds)
            time_factor = time_remaining / time_window
            
            # Tighten trail in last 5 minutes (time_factor < 0.33)
            if time_factor < 0.33:
                # Reduce trail distance by 50% in last 5 minutes
                trailing_param *= 0.5
            elif time_factor < 0.67:
                # Reduce trail distance by 25% in last 10 minutes
                trailing_param *= 0.75
        
        # Research: Volatility-based trailing adjustment using ATR
        # Higher volatility = wider stops, lower volatility = tighter stops
        try:
            from merid.signals.ta_engine import TAEngine, IndicatorConfig
            from merid.data.unified_spot_service import get_unified_spot_service
            
            # Get asset from market_id (e.g., "KXBTC15M-..." -> "BTC")
            asset = None
            if "BTC" in self.market_id:
                asset = "BTC"
            elif "ETH" in self.market_id:
                asset = "ETH"
            elif "SOL" in self.market_id:
                asset = "SOL"
            elif "XRP" in self.market_id:
                asset = "XRP"
            elif "DOGE" in self.market_id:
                asset = "DOGE"
            
            if asset:
                spot_service = get_unified_spot_service()
                spot_data = spot_service.get_spot_data(asset)
                if spot_data and hasattr(spot_data, 'atr_pct') and spot_data.atr_pct > 0:
                    # Baseline ATR is ~1% for crypto (adjustment factor = 1.0)
                    baseline_atr_pct = 0.01
                    atr_multiplier = spot_data.atr_pct / baseline_atr_pct
                    
                    # Apply ATR adjustment: widen stops in high vol, tighten in low vol
                    # Clamp multiplier to reasonable range [0.5, 2.0]
                    atr_multiplier = max(0.5, min(2.0, atr_multiplier))
                    trailing_param *= atr_multiplier
        except Exception as e:
            # If ATR data unavailable, use base trailing_param
            pass
        
        if self.trailing_type == TrailingType.PERCENT:
            # Percent trail: trail_level = max_favorable * (1 - trail_percent)
            # trailing_param is already a decimal (e.g., 0.10 for 10%)
            # CRITICAL FIX (2026-07-16): Side-space — trail below max favorable for BOTH sides
            trail_level = int(self.max_favorable_price_cents * (1 - trailing_param))
            return trail_level
        
        elif self.trailing_type == TrailingType.R_MULTIPLE:
            # R-multiple trail: trail_level = max_favorable - trail_r * initial_risk
            trail_r = trailing_param
            trail_level = int(self.max_favorable_price_cents - (trail_r * self.initial_risk_cents))
            return trail_level
        
        elif self.trailing_type == TrailingType.FIXED_CENTS:
            # Fixed cent trail: trail_level = max_favorable - fixed_distance
            # trailing_param is the fixed distance in cents (e.g., 5 cents)
            # CRITICAL FIX: 2026-07-06 - Use aggressive distance (2c) in 80-85c profit zone
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    if self.trailing_profit_zone_activated:
                        fixed_distance = profile.trailing_stop_trailing_distance_cents_profit_zone  # 2c in profit zone
                    else:
                        fixed_distance = profile.trailing_stop_trailing_distance_cents  # 5c normal
                else:
                    fixed_distance = int(trailing_param)  # Fallback to param
            except Exception as e:
                fixed_distance = int(trailing_param)  # Fallback to param
            
            # CRITICAL FIX (2026-07-16): Side-space — trail below max favorable for BOTH sides
            trail_level = self.max_favorable_price_cents - fixed_distance
            return trail_level
        
        return None
    
    def get_probability_adjusted_trail_level(self) -> Optional[int]:
        """
        Calculate probability-adjusted trailing stop level.
        
        Research (Prevayo): Trailing stops should account for non-linear probability
        near extremes. When probability is high (near 0.90-1.00 for YES, or 0.00-0.10 for NO),
        trailing should be tighter to lock in gains. When probability is moderate
        (around 0.50-0.70), trailing can be looser.
        
        Adjustment factor based on current price (probability):
        - For YES: 0.90+ → 0.6x tighter, 0.70-0.90 → 0.8x, 0.50-0.70 → 1.0x
        - For NO: 0.10- → 0.6x tighter, 0.10-0.30 → 0.8x, 0.30-0.50 → 1.0x
        
        Returns:
            Probability-adjusted trailing stop price in cents, or None if trailing not active
        """
        base_trail_level = self.get_trail_level()
        if base_trail_level is None:
            return None
        
        # Convert current price to probability (cents to decimal)
        # CRITICAL FIX (2026-07-16): Side-space — own-side price IS the probability of
        # this position winning, for BOTH sides (NO price = P(NO wins)).
        current_prob = self.current_price_cents / 100.0
        
        # Calculate adjustment factor: higher own-side probability = tighter trailing
        # For YES: 0.90+ → 0.6x tighter, 0.70-0.90 → 0.8x, 0.50-0.70 → 1.0x
        # For NO: 0.10- → 0.6x tighter, 0.10-0.30 → 0.8x, 0.30-0.50 → 1.0x
        if self.side == PositionSide.YES:
            if current_prob >= 0.90:
                adjustment_factor = 0.6  # 40% tighter
            elif current_prob >= 0.70:
                adjustment_factor = 0.8  # 20% tighter
            else:
                adjustment_factor = 1.0  # Normal
        else:  # NO
            if current_prob <= 0.10:
                adjustment_factor = 0.6  # 40% tighter
            elif current_prob <= 0.30:
                adjustment_factor = 0.8  # 20% tighter
            else:
                adjustment_factor = 1.0  # Normal
        
        # Apply adjustment to trail distance from max favorable (trail below for both sides)
        trail_distance = self.max_favorable_price_cents - base_trail_level
        adjusted_distance = int(trail_distance * adjustment_factor)
        adjusted_trail_level = self.max_favorable_price_cents - adjusted_distance
        
        return adjusted_trail_level
    
    def should_trigger_trail(self, current_price_cents: int) -> bool:
        """
        Check if trailing stop should trigger.
        
        CRITICAL FIX: 2026-07-16 - Side-space semantics: current_price_cents is the
        position's OWN side price. Both sides trigger when own-side price falls
        to or below the trail level (protect unrealized gains).
        
        Args:
            current_price_cents: Current market price in cents
            
        Returns:
            True if price has crossed trail level
        """
        trail_level = self.get_trail_level()
        if trail_level is None:
            return False
        
        # CRITICAL FIX (2026-07-16): Side-space — own-side price falling to/below the
        # trail level triggers for BOTH sides (both sides are long their own side)
        return current_price_cents <= trail_level
    
    def should_trigger_stop_loss(self, current_price_cents: int) -> bool:
        """
        Check if stop-loss should trigger.
        
        Args:
            current_price_cents: Current market price in cents
            
        Returns:
            True if price has crossed stop-loss level
        """
        if self.stop_loss_price_cents is None:
            return False
        
        # CRITICAL FIX (2026-07-16): Side-space — SL sits BELOW entry in own-side cents
        # for BOTH sides; trigger when own-side price falls to or below it
        return current_price_cents <= self.stop_loss_price_cents
    
    def should_trigger_take_profit(self, current_price_cents: int) -> bool:
        """
        Check if take-profit should trigger.
        
        Args:
            current_price_cents: Current market price in cents
            
        Returns:
            True if price has crossed take-profit level
        """
        if self.take_profit_price_cents is None:
            return False
        
        # CRITICAL FIX (2026-07-16): Side-space — TP sits ABOVE entry in own-side cents
        # for BOTH sides; trigger when own-side price rises to or above it
        return current_price_cents >= self.take_profit_price_cents
    
    def should_trigger_extreme_profit(self, current_price_cents: int, bid_cents: Optional[int] = None, ask_cents: Optional[int] = None) -> bool:
        """
        Check if extreme profit exit should trigger (own side at 99c+).
        
        2026 FIX: Exit when the position's OWN side reaches 99c to lock in
        guaranteed wins. At these extreme prices, the probability is near 100%
        and holding further provides minimal upside with settlement risk.
        
        CRITICAL FIX: 2026-07-16 - Side-space semantics: all prices are in the
        position's own side cents. Use own-side bid for conservative check
        (what we can actually sell at).
        
        Args:
            current_price_cents: Current own-side price in cents (mid price)
            bid_cents: Current own-side bid price in cents (optional)
            ask_cents: Current own-side ask price in cents (optional, unused)
            
        Returns:
            True if own-side price is at extreme profit level (99c+)
        """
        # Use conservative own-side bid if available (what we can actually sell at)
        check_price = current_price_cents
        if bid_cents is not None:
            check_price = bid_cents
        
        # CRITICAL FIX (2026-07-16): Side-space — a guaranteed win means the position's
        # OWN side is at 99c+ for BOTH sides (NO at 99c-NO == YES at 1c-YES).
        # Previous NO branch fired at 1c own-side price, which is a TOTAL LOSS for NO.
        return check_price >= 99
    
    def should_trigger_break_even(self, current_price_cents: int) -> bool:
        """
        Check if break-even should trigger (move SL to entry at 1R).
        
        Research: Move stop-loss to entry price when position reaches 1R profit
        for capital preservation. This eliminates risk on the trade.
        
        Args:
            current_price_cents: Current market price in cents
            
        Returns:
            True if position reached 1R and break-even not yet triggered
        """
        if self.break_even_triggered:
            return False
        
        if self.initial_risk_cents == 0:
            return False
        
        # Calculate current R-multiple
        # CRITICAL FIX (2026-07-16): Side-space — profit = own-side price rising for BOTH sides
        pnl_cents = current_price_cents - self.avg_entry_price_cents
        
        current_r = pnl_cents / self.initial_risk_cents if self.initial_risk_cents > 0 else 0
        
        # Trigger break-even at 1R
        if current_r >= 1.0:
            return True
        
        return False
    
    def trigger_break_even(self) -> None:
        """
        Trigger break-even: move stop-loss to entry price.
        
        This eliminates risk on the trade while allowing upside.
        """
        self.break_even_triggered = True
        self.break_even_price_cents = self.avg_entry_price_cents
        # Move SL to entry price
        self.stop_loss_price_cents = self.avg_entry_price_cents
    
    def should_trigger_scale_out(self, current_price_cents: int) -> bool:
        """
        Check if partial scale-out should trigger (close 50% at 1.5-2R).
        
        Research: Close 50% of position at 1.5-2R to lock profits while
        letting "runner" capture larger moves. This is the "Pay Yourself" strategy.
        
        Args:
            current_price_cents: Current market price in cents
            
        Returns:
            True if position reached scale-out target and not yet triggered
        """
        if self.scale_out_triggered or self.scale_out_price_cents is None:
            return False
        
        # CRITICAL FIX (2026-07-16): Side-space — scale-out target sits ABOVE entry in
        # own-side cents for BOTH sides; trigger when own-side price rises to it
        return current_price_cents >= self.scale_out_price_cents
    
    def trigger_scale_out(self) -> int:
        """
        Trigger partial scale-out: close 50% of position.
        
        Returns:
            Number of contracts to close (50% of current size)
        """
        self.scale_out_triggered = True
        contracts_to_close = self.size // 2  # Close 50%
        self.scale_out_remaining_size = self.size - contracts_to_close
        return contracts_to_close
    
    def mark_exited(self, reason: str, exit_price_cents: int, now: Optional[datetime] = None) -> None:
        """
        Mark position as exited.
        
        Args:
            reason: Exit reason (e.g., STOP_LOSS, TAKE_PROFIT, TRAIL, TIME_STOP)
            exit_price_cents: Exit price in cents
            now: Exit timestamp (defaults to utcnow)
        """
        if now is None:
            now = datetime.utcnow()
        
        self.exit_triggered = True
        self.exit_reason = reason
        self.exit_price_cents = exit_price_cents
        self.exited_at = now
    
    def is_open(self) -> bool:
        """Check if position is still open."""
        return not self.exit_triggered
    
    def to_dict(self) -> dict:
        """
        Convert position to dictionary for persistence.
        
        CRITICAL FIX: 2026-07-07 - Added dynamic_tp_target_cents to persistence
        to prevent loss of dynamic TP targets on system restart.
        """
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "series_ticker": self.series_ticker,
            "side": self.side.value if isinstance(self.side, PositionSide) else self.side,
            "size": self.size,
            "avg_entry_price_cents": self.avg_entry_price_cents,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "take_profit_price_cents": self.take_profit_price_cents,
            "take_profit_r_multiple": self.take_profit_r_multiple,
            "stop_loss_price_cents": self.stop_loss_price_cents,
            "break_even_triggered": self.break_even_triggered,
            "break_even_price_cents": self.break_even_price_cents,
            "scale_out_price_cents": self.scale_out_price_cents,
            "scale_out_triggered": self.scale_out_triggered,
            "scale_out_remaining_size": self.scale_out_remaining_size,
            "trailing_type": self.trailing_type.value if isinstance(self.trailing_type, TrailingType) else self.trailing_type,
            "trailing_param": self.trailing_param,
            "max_favorable_price_cents": self.max_favorable_price_cents,
            "trailing_activated": self.trailing_activated,
            "trailing_profit_zone_activated": self.trailing_profit_zone_activated,
            # trailing_profit_threshold_reached_at is runtime-only, not persisted
            "window_resolution_id": self.window_resolution_id,
            "exit_policy_id": self.exit_policy_id,
            "current_price_cents": self.current_price_cents,
            "unrealized_pnl_cents": self.unrealized_pnl_cents,
            "r_multiple": self.r_multiple,
            "time_since_entry_seconds": self.time_since_entry_seconds,
            "exit_triggered": self.exit_triggered,
            "exit_reason": self.exit_reason,
            "exit_price_cents": self.exit_price_cents,
            "exited_at": self.exited_at.isoformat() if self.exited_at else None,
            "ratchet_activated": self.ratchet_activated,
            "ratchet_hold_until": self.ratchet_hold_until,
            "ratchet_trimmed": self.ratchet_trimmed,
            "dynamic_tp_target_cents": self.dynamic_tp_target_cents,  # CRITICAL: Persist dynamic TP target
            "dynamic_tp_triggered": self.dynamic_tp_triggered,
            "entry_edge_pct": self.entry_edge_pct,
            "initial_risk_cents": self.initial_risk_cents,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        """
        Create position from dictionary (for persistence retrieval).
        
        CRITICAL FIX: 2026-07-07 - Added dynamic_tp_target_cents from persistence
        to restore dynamic TP targets after system restart.
        """
        from datetime import datetime
        
        return cls(
            position_id=data.get("position_id"),
            market_id=data.get("market_id", ""),
            series_ticker=data.get("series_ticker", ""),
            side=PositionSide(data.get("side", "yes")),
            size=data.get("size", 0),
            avg_entry_price_cents=data.get("avg_entry_price_cents", 0),
            opened_at=datetime.fromisoformat(data["opened_at"]) if data.get("opened_at") else datetime.utcnow(),
            take_profit_price_cents=data.get("take_profit_price_cents"),
            take_profit_r_multiple=data.get("take_profit_r_multiple"),
            stop_loss_price_cents=data.get("stop_loss_price_cents"),
            break_even_triggered=data.get("break_even_triggered", False),
            break_even_price_cents=data.get("break_even_price_cents"),
            scale_out_price_cents=data.get("scale_out_price_cents"),
            scale_out_triggered=data.get("scale_out_triggered", False),
            scale_out_remaining_size=data.get("scale_out_remaining_size", 0),
            trailing_type=TrailingType(data.get("trailing_type", "none")),
            trailing_param=data.get("trailing_param", 0.0),
            max_favorable_price_cents=data.get("max_favorable_price_cents", 0),
            trailing_activated=data.get("trailing_activated", False),
            trailing_profit_zone_activated=data.get("trailing_profit_zone_activated", False),
            # trailing_profit_threshold_reached_at is runtime-only, not persisted
            window_resolution_id=data.get("window_resolution_id", ""),
            exit_policy_id=data.get("exit_policy_id", ""),
            current_price_cents=data.get("current_price_cents", 0),
            unrealized_pnl_cents=data.get("unrealized_pnl_cents", 0),
            r_multiple=data.get("r_multiple", 0.0),
            time_since_entry_seconds=data.get("time_since_entry_seconds", 0.0),
            exit_triggered=data.get("exit_triggered", False),
            exit_reason=data.get("exit_reason"),
            exit_price_cents=data.get("exit_price_cents"),
            exited_at=datetime.fromisoformat(data["exited_at"]) if data.get("exited_at") else None,
            ratchet_activated=data.get("ratchet_activated", False),
            ratchet_hold_until=data.get("ratchet_hold_until", 0.0),
            ratchet_trimmed=data.get("ratchet_trimmed", False),
            dynamic_tp_target_cents=data.get("dynamic_tp_target_cents"),  # CRITICAL: Restore dynamic TP target
            dynamic_tp_triggered=data.get("dynamic_tp_triggered", False),
            entry_edge_pct=data.get("entry_edge_pct", 0.03),
            initial_risk_cents=data.get("initial_risk_cents", 0),
        )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Position(id={self.position_id[:8]}, market={self.market_id}, "
            f"side={self.side}, size={self.size}, entry={self.avg_entry_price_cents}c, "
            f"pnl={self.unrealized_pnl_cents}c, R={self.r_multiple:.2f}, "
            f"exit={self.exit_reason})"
        )
