"""Stop-Loss Rules for Kalshi Binary Contracts.

Classic exchange stop orders don't apply to fixed-payout binaries, but
equivalent risk controls can be implemented as rules:

1. **Price invalidation**: If a YES contract drops below a threshold
   (e.g. entry 60c → invalidation at 35c), signal to close at market.
2. **Time-based stops**: Exit early if thesis hasn't materialized by a
   deadline, even though the contract could be held to expiry.
3. **Per-trade loss cap**: Max loss per position as % of bankroll.
4. **Session loss cap**: Stop trading when cumulative daily loss hits a
   threshold (e.g. 3-5% of equity).

Usage::

    rules = StopLossRules(config)
    action = rules.check_position(position)
    if action.should_close:
        # close the position
        rules.record_close(position.position_id, action)
    rules.summary()
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.risk_parameters import (
    SL_INVALIDATION_DROP_CENTS,
    SL_CLOSE_LOSING_AFTER_PCT,
    PM_MICROSCALP_PROFIT_TARGET_PCT,
    EDGE_DECAY_THRESHOLD,
    PM_MIN_PROFIT_CENTS,
    PM_LOW_VOLATILITY_TARGET,
    PM_NORMAL_VOLATILITY_TARGET,
    PM_HIGH_VOLATILITY_TARGET,
    PM_LOW_VOL_THRESHOLD,
    PM_HIGH_VOL_THRESHOLD,
    PM_STRONG_MOMENTUM_THRESHOLD,
    PM_WEAK_MOMENTUM_THRESHOLD,
    PM_MOMENTUM_BOOST_FACTOR,
    PM_MOMENTUM_REDUCE_FACTOR,
    PM_TRAILING_STOP_DISTANCE_PCT,
    PM_TRAILING_ACTIVATION_PCT,
    PM_MAX_PROFIT_TARGET_PCT,
    PM_MIN_PROFIT_TARGET_PCT,
    PM_ANALYTICS_WINDOW,
    PM_MIN_EXITS_FOR_OPTIMIZATION,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.stop_loss")

# Import canonical SL constants so all defaults are env-driven from one place.
try:
    from config.trading_constants import (
        SL_PRICE_INVALIDATION_DROP_CENTS as _SL_DROP,
        SL_PRICE_FLOOR_CENTS as _SL_FLOOR,
        SL_MAX_LOSS_PER_TRADE_PCT as _SL_TRADE_PCT,
        SL_SESSION_LOSS_CAP_PCT as _SL_SESSION_PCT,
        SL_CLOSE_IF_LOSING_AFTER_PCT as _SL_LOSING_PCT,
    )
except Exception:
    _SL_DROP = SL_INVALIDATION_DROP_CENTS
    _SL_FLOOR = 8
    _SL_TRADE_PCT = 2.0
    _SL_SESSION_PCT = 5.0
    _SL_LOSING_PCT = SL_CLOSE_LOSING_AFTER_PCT


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class StopLossConfig:
    """Configuration for binary contract stop-loss rules.

    All defaults are driven by config.trading_constants (env-overridable).
    Use ``MERID_SL_*`` environment variables for ops tuning without code changes.
    """

    # Price invalidation: close if current price drops this many cents
    # below entry price.  Driven by MERID_SL_INVALIDATION_DROP_CENTS (default 20).
    price_invalidation_drop_cents: int = _SL_DROP

    # Absolute floor: close if price drops to or below this (cents).
    # Driven by MERID_SL_PRICE_FLOOR_CENTS (default 8).
    price_floor_cents: int = _SL_FLOOR

    # Per-asset multipliers for ``price_invalidation_drop_cents`` so volatile
    # assets (DOGE, XRP) tolerate larger swings before triggering and stable
    # ones (BTC, ETH) trigger at baseline. Calibrated from YAML hedging config:
    #   BTC/ETH stop_loss=1.5% → 1.0x;  SOL/XRP=2.0% → 1.33x;  DOGE=3.0% → 2.0x
    per_asset_sl_multipliers: Dict[str, float] = field(
        default_factory=lambda: {
            "BTC": 1.00,
            "ETH": 1.00,
            "SOL": 1.33,
            "XRP": 1.33,
            "DOGE": 2.00,
        }
    )

    # Per-asset price floors (cents). DOGE markets can legitimately trade
    # below 8¢ while still being recoverable; BTC/ETH at 8¢ usually means
    # the trade is invalidated.
    per_asset_floor_cents: Dict[str, int] = field(
        default_factory=lambda: {
            "BTC": 8,
            "ETH": 8,
            "SOL": 6,
            "XRP": 6,
            "DOGE": 4,
        }
    )

    # Time-based stop: close if position has been open longer than this
    # (seconds). 0 = disabled.
    max_hold_seconds: int = 0

    # Time-based stop: close if less than this fraction of contract
    # duration remains and position is losing.
    # Driven by MERID_SL_CLOSE_LOSING_AFTER_PCT (default 0.75).
    close_if_losing_after_pct: float = _SL_LOSING_PCT

    # Per-trade loss cap: max loss per position as % of session equity.
    # Driven by MERID_SL_MAX_LOSS_PER_TRADE_PCT (default 2.0).
    max_loss_per_trade_pct: float = _SL_TRADE_PCT

    # Session loss cap: stop all trading when daily loss exceeds this %.
    # TIGHTENED: Driven by MERID_SL_SESSION_LOSS_CAP_PCT (default 5.0).
    # Reduced default from 5.0 to 3.0 for more aggressive loss protection.
    session_loss_cap_pct: float = 3.0

    # Take-profit: close if current price rises this many cents above entry
    # 0 = disabled (hold to settlement)
    take_profit_gain_cents: int = 0

    # B7: Take-profit by percentage gain relative to entry price.
    # e.g. 0.40 = close when price is >= 40% above entry (entry 50c -> close at 70c).
    # 0.0 = disabled. Takes precedence over take_profit_gain_cents when both > 0.
    profit_target_pct: float = 0.0


DEFAULT_STOP_LOSS_CONFIG = StopLossConfig()


# ── Position ─────────────────────────────────────────────────────────────

@dataclass
class TrackedPosition:
    """A position being monitored by stop-loss rules."""
    position_id: str
    ticker: str
    side: str               # "yes" or "no"
    entry_price_cents: int
    contracts: int
    entry_ts: float
    contract_expiry_ts: float = 0.0  # 0 = unknown
    current_price_cents: int = 0
    session_equity_cents: float = 0.0  # Must be set via StopLossRules.set_session_equity()
    # BUG-05: track consecutive close failures for escalation
    close_fail_count: int = 0
    # Take-profit: last bid/ask seen this cycle (set by price-refresh loop in trading_agent)
    last_bid_cents: int = 0
    last_ask_cents: int = 0
    # IOC escalation safety: track original client_order_id to prevent double fills
    # This is set when the original close order is submitted and reused for IOC escalation
    close_client_order_id: str = ""  # Empty if no close order in flight
    # PRODUCTION FIX: TP targets from dynamic R-multiple computation
    take_profit_price_cents: Optional[int] = None  # TP price level from OrderIntent
    take_profit_r_multiple: Optional[float] = None  # R-multiple target (e.g., 1.5R)
    stop_loss_price_cents: Optional[int] = None  # Protective stop from OrderIntent
    # Trading mode this position was entered in ("paper" / "live" / "mock").
    # Used so exits route through the same path (prevents paper position
    # being exited via live API which fails with 404 for unknown tickers).
    entry_mode: Optional[str] = None

    @property
    def unrealized_pnl_cents(self) -> float:
        """Unrealized PnL per contract in cents."""
        if self.side == "yes":
            return (self.current_price_cents - self.entry_price_cents) * self.contracts
        else:
            return (self.entry_price_cents - self.current_price_cents) * self.contracts

    @property
    def loss_pct_of_equity(self) -> float:
        """Current loss as % of session equity (positive = losing).

        Fail-closed: when session equity is unknown and position is losing,
        returns 100% to ensure equity-based stops can trigger.
        """
        pnl = self.unrealized_pnl_cents
        if pnl >= 0:
            return 0.0
        if not self.session_equity_cents or self.session_equity_cents <= 0:
            return 100.0
        return abs(pnl) / self.session_equity_cents * 100

    @property
    def hold_duration_seconds(self) -> float:
        return time.time() - self.entry_ts

    @property
    def time_elapsed_pct(self) -> float:
        """Fraction of contract duration elapsed (0-1)."""
        if self.contract_expiry_ts <= self.entry_ts:
            return 0.0
        total = self.contract_expiry_ts - self.entry_ts
        elapsed = time.time() - self.entry_ts
        return min(1.0, elapsed / total)


# ── Stop action ──────────────────────────────────────────────────────────

@dataclass
class StopAction:
    """Result of checking a position against stop-loss rules."""
    should_close: bool = False
    reason: str = ""
    rule: str = ""          # which rule triggered
    urgency: str = "normal"  # "normal", "high", "critical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_close": self.should_close,
            "reason": self.reason,
            "rule": self.rule,
            "urgency": self.urgency,
        }


# ── Stop-loss rules engine ───────────────────────────────────────────────

class StopLossRules:
    """Evaluates stop-loss rules against open binary contract positions."""

    def __init__(self, config: Optional[StopLossConfig] = None) -> None:
        self._config = config or DEFAULT_STOP_LOSS_CONFIG
        self._session_loss_cents: float = 0.0
        self._session_equity_cents: float = 0.0  # Set via set_session_equity() before use
        self._session_halted: bool = False
        self._halt_reason: Optional[str] = None
        self._close_log: List[Dict[str, Any]] = []
        self._positions_checked: int = 0
        self._stops_triggered: int = 0

    @property
    def config(self) -> StopLossConfig:
        return self._config

    @property
    def session_halted(self) -> bool:
        return self._session_halted

    def set_session_equity(self, equity_cents: float) -> None:
        self._session_equity_cents = equity_cents

    def set_session_equity_from_ladder(self, portfolio_id: Optional[str] = None) -> None:
        """Pull current equity from PaperLadder and update the session equity.

        If portfolio_id is None, uses the highest-equity portfolio available.
        Falls back silently if the ladder is not available.
        """
        try:
            from merid.paper_ladder import get_paper_ladder
            ladder = get_paper_ladder()
            all_progress = ladder.get_all_progress()
            if not all_progress:
                return
            if portfolio_id and portfolio_id in all_progress:
                equity_usd = all_progress[portfolio_id].current_equity
            else:
                equity_usd = max(p.current_equity for p in all_progress.values())
            self._session_equity_cents = equity_usd * 100.0
        except Exception as _e:
            logger.debug("set_session_equity_from_ladder: %s", _e)

    def record_session_loss(self, loss_cents: float) -> None:
        """Record a realized loss (positive value = loss)."""
        self._session_loss_cents += loss_cents
        self._check_session_cap()

    # ── Check position ───────────────────────────────────────────────

    def check_position(self, pos: TrackedPosition) -> StopAction:
        """Evaluate all stop-loss rules for a position.

        Returns the first triggered rule (highest priority first).
        """
        self._positions_checked += 1
        cfg = self._config

        # 0. Session halted → close everything
        if self._session_halted:
            return StopAction(
                should_close=True,
                reason=f"Session halted: {self._halt_reason}",
                rule="session_halt",
                urgency="critical",
            )

        # Resolve per-asset thresholds (P1 Task 5): DOGE / XRP have wider
        # bands than BTC / ETH because their underlying volatility is much higher.
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            _asset = kalshi_ticker_to_asset(pos.ticker) or ""
        except Exception:
            _asset = ""
        _sl_mult = cfg.per_asset_sl_multipliers.get(_asset, 1.0) if _asset else 1.0
        _floor_cents = cfg.per_asset_floor_cents.get(_asset, cfg.price_floor_cents) if _asset else cfg.price_floor_cents
        _drop_threshold = int(round(cfg.price_invalidation_drop_cents * _sl_mult))

        # 1. Price floor (per-asset)
        if pos.current_price_cents > 0 and pos.current_price_cents <= _floor_cents:
            return StopAction(
                should_close=True,
                reason=(
                    f"Price {pos.current_price_cents}c <= floor {_floor_cents}c "
                    f"(asset={_asset or 'unknown'})"
                ),
                rule="price_floor",
                urgency="high",
            )

        # 2. Price invalidation (drop from entry, per-asset multiplier)
        if pos.current_price_cents > 0 and _drop_threshold > 0:
            if pos.side == "yes":
                drop = pos.entry_price_cents - pos.current_price_cents
            else:
                drop = pos.current_price_cents - pos.entry_price_cents
            if drop >= _drop_threshold:
                return StopAction(
                    should_close=True,
                    reason=(
                        f"Price dropped {drop}c from entry "
                        f"(asset={_asset or 'unknown'} threshold={_drop_threshold}c, "
                        f"base={cfg.price_invalidation_drop_cents}c x{_sl_mult:.2f})"
                    ),
                    rule="price_invalidation",
                    urgency="high",
                )

        # 3. Per-trade loss cap
        if cfg.max_loss_per_trade_pct > 0 and pos.loss_pct_of_equity > cfg.max_loss_per_trade_pct:
            return StopAction(
                should_close=True,
                reason=(
                    f"Position loss {pos.loss_pct_of_equity:.1f}% of equity "
                    f"exceeds cap {cfg.max_loss_per_trade_pct}%"
                ),
                rule="per_trade_loss_cap",
                urgency="high",
            )

        # 4a. FVG-based exit: Close if opposing FVG creates strong resistance/support
        try:
            from merid.prediction.fvg_integration import get_fvg_entry_exit_timing, is_fvg_enabled
            if is_fvg_enabled():
                fvg_timing = get_fvg_entry_exit_timing(
                    ticker=pos.ticker,
                    bid=pos.current_price_cents / 100.0,
                    ask=pos.current_price_cents / 100.0,
                )
                if fvg_timing and fvg_timing.should_exit and fvg_timing.exit_urgency >= 0.9:
                    # Critical FVG exit signal - treat as stop
                    return StopAction(
                        should_close=True,
                        reason=(
                            f"FVG stop: exit_urgency={fvg_timing.exit_urgency:.2f} "
                            f"target={fvg_timing.target_price_cents or 0:.1f}c reason={fvg_timing.reason}"
                        ),
                        rule="fvg_exit_signal",
                        urgency="high",
                    )
        except Exception as e:
            logger.debug("FVG stop loss check skipped for %s: %s", pos.ticker, e)

        # 4b. B7: percentage-based take-profit (takes precedence when set)
        if cfg.profit_target_pct > 0.0 and pos.current_price_cents > 0 and pos.entry_price_cents > 0:
            if pos.side == "yes":
                gain_pct = (pos.current_price_cents - pos.entry_price_cents) / pos.entry_price_cents
            else:
                gain_pct = (pos.entry_price_cents - pos.current_price_cents) / pos.entry_price_cents
            if gain_pct >= cfg.profit_target_pct:
                return StopAction(
                    should_close=True,
                    reason=(
                        f"Take-profit: +{gain_pct:.1%} gain >= target {cfg.profit_target_pct:.1%} "
                        f"(entry {pos.entry_price_cents}c → current {pos.current_price_cents}c)"
                    ),
                    rule="take_profit_pct",
                    urgency="normal",
                )

        # 4b. Absolute-cents take-profit
        if cfg.take_profit_gain_cents > 0 and pos.current_price_cents > 0:
            if pos.side == "yes":
                gain = pos.current_price_cents - pos.entry_price_cents
            else:
                gain = pos.entry_price_cents - pos.current_price_cents
            if gain >= cfg.take_profit_gain_cents:
                return StopAction(
                    should_close=True,
                    reason=f"Take-profit: gained {gain}c (target: {cfg.take_profit_gain_cents}c)",
                    rule="take_profit",
                    urgency="normal",
                )

        # 5. Max hold time
        if cfg.max_hold_seconds > 0:
            held = pos.hold_duration_seconds
            if held >= cfg.max_hold_seconds:
                return StopAction(
                    should_close=True,
                    reason=f"Held {held:.0f}s >= max {cfg.max_hold_seconds}s",
                    rule="max_hold_time",
                    urgency="normal",
                )

        # 6. Time-based losing stop
        if cfg.close_if_losing_after_pct > 0 and pos.contract_expiry_ts > 0:
            if pos.time_elapsed_pct >= cfg.close_if_losing_after_pct and pos.unrealized_pnl_cents < 0:
                return StopAction(
                    should_close=True,
                    reason=(
                        f"Losing position with {pos.time_elapsed_pct:.0%} of duration elapsed "
                        f"(threshold: {cfg.close_if_losing_after_pct:.0%})"
                    ),
                    rule="time_based_losing",
                    urgency="normal",
                )

        return StopAction(should_close=False)

    # ── Record close ─────────────────────────────────────────────────

    def record_close(self, position_id: str, action: StopAction, pnl_cents: float = 0.0) -> None:
        """Record that a position was closed by a stop rule."""
        self._stops_triggered += 1
        if pnl_cents < 0:
            self.record_session_loss(abs(pnl_cents))

        entry = {
            "ts": time.time(),
            "position_id": position_id,
            "rule": action.rule,
            "reason": action.reason,
            "pnl_cents": pnl_cents,
        }
        self._close_log.append(entry)
        if len(self._close_log) > 200:
            self._close_log = self._close_log[-200:]

        logger.info(f"[stop-loss] Closed {position_id}: {action.rule} — {action.reason}")

    # ── Session cap ──────────────────────────────────────────────────

    def _check_session_cap(self) -> None:
        cfg = self._config
        if cfg.session_loss_cap_pct <= 0 or self._session_equity_cents <= 0:
            return
        loss_pct = self._session_loss_cents / self._session_equity_cents * 100
        if loss_pct >= cfg.session_loss_cap_pct:
            self._session_halted = True
            self._halt_reason = (
                f"Session loss {loss_pct:.1f}% >= cap {cfg.session_loss_cap_pct}%"
            )
            logger.warning(f"[stop-loss] SESSION HALTED: {self._halt_reason}")

    def reset_session(self, equity_cents: float = 500_000.0) -> None:
        """Reset session loss tracking (e.g. at start of new day)."""
        self._session_loss_cents = 0.0
        self._session_equity_cents = equity_cents
        self._session_halted = False
        self._halt_reason = None

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        loss_pct = 0.0
        if self._session_equity_cents > 0:
            loss_pct = self._session_loss_cents / self._session_equity_cents * 100

        return {
            "session_halted": self._session_halted,
            "halt_reason": self._halt_reason,
            "session_loss_cents": round(self._session_loss_cents, 2),
            "session_loss_pct": round(loss_pct, 2),
            "session_equity_cents": round(self._session_equity_cents, 2),
            "positions_checked": self._positions_checked,
            "stops_triggered": self._stops_triggered,
            "recent_closes": self._close_log[-5:],
            "config": {
                "price_invalidation_drop_cents": self._config.price_invalidation_drop_cents,
                "price_floor_cents": self._config.price_floor_cents,
                "max_hold_seconds": self._config.max_hold_seconds,
                "close_if_losing_after_pct": self._config.close_if_losing_after_pct,
                "max_loss_per_trade_pct": self._config.max_loss_per_trade_pct,
                "session_loss_cap_pct": self._config.session_loss_cap_pct,
                "take_profit_gain_cents": self._config.take_profit_gain_cents,
            },
        }


# ── Micro-Scalping Exit Manager ─────────────────────────────────────────

@dataclass
class MicroScalpExitConfig:
    """Configuration for micro-scalping fast exits.
    
    Optimized for $44.35 micro bankrolls with rapid capital turnover.
    Targets 70-80% win rate with 2-5 tick profit captures.
    """
    # Profit target: exit at 3% price movement (e.g., 50c -> 51.5c)
    profit_target_pct: float = PM_MICROSCALP_PROFIT_TARGET_PCT
    
    # Max hold time: 180 seconds (3 minutes) - allows more time for positions to develop
    max_hold_seconds: int = int(os.getenv("MERID_PM_MICROSCALP_MAX_HOLD_SECONDS", "180"))  # REVERTED from 120s to restore profitable trades
    
    # Edge decay: exit if edge drops 50% from entry
    edge_decay_threshold: float = EDGE_DECAY_THRESHOLD
    
    # Order book flip detection: exit if bid/ask pressure reverses
    book_flip_detection: bool = True
    
    # Minimum profit in cents to justify transaction fees
    min_profit_cents: int = PM_MIN_PROFIT_CENTS


@dataclass
class MicroScalpPosition:
    """Position tracking for micro-scalping exits."""
    position_id: str
    ticker: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    entry_edge: float  # Edge at entry time
    contracts: int
    entry_ts: float
    current_price_cents: int = 0
    current_edge: float = 0.0
    last_bid_cents: int = 0
    last_ask_cents: int = 0


@dataclass
class MicroScalpExitAction:
    """Exit decision from micro-scalping rules."""
    should_exit: bool
    reason: str = ""
    profit_pct: float = 0.0
    hold_seconds: float = 0.0
    target_used: float = 0.0  # The actual profit target that was applied


@dataclass
class DynamicTPConfig:
    """Configuration for dynamic take-profit calculator."""
    # Base target ranges by volatility
    low_volatility_target: float = PM_LOW_VOLATILITY_TARGET
    normal_volatility_target: float = PM_NORMAL_VOLATILITY_TARGET
    high_volatility_target: float = PM_HIGH_VOLATILITY_TARGET

    # Volatility thresholds for regime detection
    low_vol_threshold: float = PM_LOW_VOL_THRESHOLD
    high_vol_threshold: float = PM_HIGH_VOL_THRESHOLD

    # Momentum thresholds for boost/reduce
    strong_momentum_threshold: float = PM_STRONG_MOMENTUM_THRESHOLD
    weak_momentum_threshold: float = PM_WEAK_MOMENTUM_THRESHOLD
    momentum_boost_factor: float = PM_MOMENTUM_BOOST_FACTOR
    momentum_reduce_factor: float = PM_MOMENTUM_REDUCE_FACTOR

    # Trailing stop settings
    trailing_stop_distance_pct: float = PM_TRAILING_STOP_DISTANCE_PCT
    trailing_activation_pct: float = PM_TRAILING_ACTIVATION_PCT

    # Profit target bounds
    max_profit_target_pct: float = PM_MAX_PROFIT_TARGET_PCT
    min_profit_target_pct: float = PM_MIN_PROFIT_TARGET_PCT


class DynamicTPCalculator:
    """Dynamic take-profit calculator for adaptive profit targets.
    
    Adjusts profit targets based on:
    - Volatility (ATR-based): Wider targets in high volatility, tighter in low
    - Momentum strength: Higher targets when trend accelerates
    - Trailing stops: Locks in profits as price moves favorably
    
    Usage::
        calculator = DynamicTPCalculator(config)
        target = calculator.get_target(
            entry_price=50,
            current_price=52,
            volatility=0.03,  # 3% ATR
            momentum=0.12,   # 12% edge
        )
        # Returns adaptive target, e.g., 0.06 (6%)
    """
    
    def __init__(self, config: Optional[DynamicTPConfig] = None) -> None:
        self._config = config or DynamicTPConfig()
        self._position_highs: Dict[str, float] = {}  # Track highest price per position
        self._logger = logger
    
    def get_target(
        self,
        entry_price: float,
        current_price: float,
        volatility: float = 0.03,
        momentum: float = 0.10,
        position_id: str = "",
    ) -> float:
        """Calculate adaptive profit target based on market conditions.
        
        Args:
            entry_price: Position entry price (cents or dollars)
            current_price: Current market price
            volatility: ATR as percentage of price (e.g., 0.03 = 3%)
            momentum: Edge strength (0.0 to 1.0)
            position_id: Optional position ID for tracking highs
            
        Returns:
            float: Target profit percentage (e.g., 0.06 for 6%)
        """
        # Track position high for trailing stop
        if position_id:
            if position_id not in self._position_highs:
                self._position_highs[position_id] = entry_price
            self._position_highs[position_id] = max(
                self._position_highs.get(position_id, entry_price),
                current_price
            )
        
        # Base target by volatility
        if volatility < self._config.low_vol_threshold:
            base_target = self._config.low_volatility_target
        elif volatility > self._config.high_vol_threshold:
            base_target = self._config.high_volatility_target
        else:
            base_target = self._config.normal_volatility_target
        
        # Adjust by momentum strength
        if momentum > self._config.strong_momentum_threshold:
            target = base_target * self._config.momentum_boost_factor
        elif momentum < self._config.weak_momentum_threshold:
            target = base_target * self._config.momentum_reduce_factor
        else:
            target = base_target
        
        # Apply hard caps for micro-scalping
        target = max(self._config.min_profit_target_pct,
                    min(target, self._config.max_profit_target_pct))
        
        return target
    
    def check_trailing_stop(
        self,
        position_id: str,
        entry_price: float,
        current_price: float,
    ) -> tuple[bool, str, float]:
        """Check if trailing stop should trigger.
        
        Args:
            position_id: Position identifier
            entry_price: Entry price
            current_price: Current price
            
        Returns:
            Tuple of (triggered, reason, high_price_reached)
        """
        if not self._config.trailing_stop_enabled:
            return False, "", 0.0
        
        if position_id not in self._position_highs:
            self._position_highs[position_id] = entry_price
        
        # Update high
        self._position_highs[position_id] = max(
            self._position_highs[position_id], current_price
        )
        high_price = self._position_highs[position_id]
        
        # Calculate unrealized PnL
        unrealized_pct = (current_price - entry_price) / entry_price
        
        # Only trail if we're profitable enough
        if unrealized_pct < self._config.trailing_activation_pct:
            return False, "", high_price
        
        # Calculate trailing stop level
        trailing_level = high_price * (1 - self._config.trailing_stop_distance_pct)
        
        if current_price < trailing_level:
            return True, f"trailing_stop_{self._config.trailing_stop_distance_pct:.1%}", high_price
        
        return False, "", high_price
    
    def on_position_closed(self, position_id: str) -> None:
        """Clean up position tracking when position closes."""
        if position_id in self._position_highs:
            del self._position_highs[position_id]
    
    def adjust_parameters(
        self,
        time_exit_rate: float,
        tp_hit_rate: float,
    ) -> None:
        """Self-tune parameters based on performance metrics.
        
        Args:
            time_exit_rate: % of exits that hit time limit (0-1)
            tp_hit_rate: % of exits that hit profit target (0-1)
        """
        if time_exit_rate > 0.50:  # >50% hitting time limit
            # Targets too ambitious - reduce
            self._config.high_volatility_target *= 0.9
            self._config.normal_volatility_target *= 0.9
            self._config.low_volatility_target *= 0.9
            self._logger.info(
                "[TP_OPTIMIZE] Reducing targets: time_exit_rate=%.1f%%",
                time_exit_rate * 100
            )
        elif time_exit_rate < 0.20 and tp_hit_rate > 0.65:
            # Targets too conservative - increase slightly
            self._config.high_volatility_target = min(
                self._config.max_profit_target_pct,
                self._config.high_volatility_target * 1.05
            )
            self._config.normal_volatility_target = min(
                self._config.max_profit_target_pct,
                self._config.normal_volatility_target * 1.05
            )
            self._logger.info(
                "[TP_OPTIMIZE] Increasing targets: time_exit_rate=%.1f%%, tp_hit_rate=%.1f%%",
                time_exit_rate * 100, tp_hit_rate * 100
            )
    
    def summary(self) -> Dict[str, Any]:
        """Return configuration summary."""
        return {
            "low_vol_target": self._config.low_volatility_target,
            "normal_vol_target": self._config.normal_volatility_target,
            "high_vol_target": self._config.high_volatility_target,
            "trailing_enabled": self._config.trailing_stop_enabled,
            "trailing_distance": self._config.trailing_stop_distance_pct,
            "tracked_positions": len(self._position_highs),
        }


class MicroScalpExitManager:
    """Fast exit manager for micro-scalping strategy with dynamic TP integration.
    
    Implements aggressive profit-taking for micro bankrolls:
    - Dynamic profit targets (3-10% based on volatility + momentum)
    - 90-second max hold (override for capital turnover)
    - Edge decay detection
    - Order book flip detection
    - Trailing stops for momentum captures
    
    Usage::
        calculator = DynamicTPCalculator()
        manager = MicroScalpExitManager(config, dynamic_tp_calculator=calculator)
        action = manager.check_exit(position, volatility=0.03, momentum=0.12)
        if action.should_exit:
            # Execute exit at market
            pass
    """
    
    def __init__(
        self,
        config: Optional[MicroScalpExitConfig] = None,
        dynamic_tp_calculator: Optional[DynamicTPCalculator] = None,
    ) -> None:
        self._config = config or MicroScalpExitConfig()
        self._dynamic_tp = dynamic_tp_calculator
        self._use_dynamic_tp = dynamic_tp_calculator is not None
        
        # Exit statistics
        self._exits_triggered: int = 0
        self._profit_exits: int = 0
        self._time_exits: int = 0
        self._edge_exits: int = 0
        self._flip_exits: int = 0
        self._trailing_exits: int = 0
        self._dynamic_tp_exits: int = 0
        
        # Exit analytics for optimization
        self._exit_analytics: List[Dict[str, Any]] = []
        
        self._logger = logger
    
    def check_exit(
        self,
        position: MicroScalpPosition,
        current_bid: int = 0,
        current_ask: int = 0,
        volatility: float = 0.03,
        momentum: float = 0.10,
    ) -> MicroScalpExitAction:
        """Check if position should be exited per micro-scalping rules.
        
        Exit conditions (first condition met):
        1. Dynamic profit target hit (adaptive 3-10% based on vol/momentum)
        2. Trailing stop triggered (for winning positions)
        3. Max hold time exceeded (90 seconds - capital turnover)
        4. Edge decayed 50% from entry
        5. Order book flipped (bid/ask pressure reversal)
        
        Args:
            position: Current position state
            current_bid: Current best bid in cents
            current_ask: Current best ask in cents
            volatility: ATR as % of price (default 3%)
            momentum: Edge strength (default 10%)
            
        Returns:
            MicroScalpExitAction with should_exit flag and reason
        """
        now = time.time()
        hold_seconds = now - position.entry_ts
        
        # Calculate current profit percentage
        if position.side == "yes":
            profit_cents = position.current_price_cents - position.entry_price_cents
        else:  # "no"
            profit_cents = position.entry_price_cents - position.current_price_cents
        
        profit_pct = profit_cents / position.entry_price_cents if position.entry_price_cents > 0 else 0.0
        
        # Get dynamic profit target
        if self._use_dynamic_tp:
            dynamic_target = self._dynamic_tp.get_target(
                entry_price=position.entry_price_cents,
                current_price=position.current_price_cents,
                volatility=volatility,
                momentum=momentum,
                position_id=position.position_id,
            )
        else:
            dynamic_target = self._config.profit_target_pct  # Fallback to base config
        
        # Exit condition 1: Dynamic profit target hit
        if profit_pct >= dynamic_target:
            self._exits_triggered += 1
            self._profit_exits += 1
            if self._use_dynamic_tp and dynamic_target != self._config.profit_target_pct:
                self._dynamic_tp_exits += 1
            
            exit_reason = (
                f"dynamic_profit_target_{dynamic_target:.1%}"
                if self._use_dynamic_tp and dynamic_target != self._config.profit_target_pct
                else "profit_target"
            )
            
            self._logger.info(
                f"[MICRO-SCALP] {exit_reason.upper()} exit {position.position_id}: "
                f"{profit_pct:.1%} >= {dynamic_target:.1%} target"
            )
            
            # Record for analytics
            self._record_exit(
                position_id=position.position_id,
                exit_type=exit_reason,
                hold_time=hold_seconds,
                pnl_pct=profit_pct,
                target_used=dynamic_target,
            )
            
            return MicroScalpExitAction(
                should_exit=True,
                reason=exit_reason,
                profit_pct=profit_pct,
                hold_seconds=hold_seconds,
                target_used=dynamic_target,
            )
        
        # Exit condition 2: Trailing stop (if enabled and using dynamic TP)
        if self._use_dynamic_tp:
            trailing_triggered, trailing_reason, high_price = self._dynamic_tp.check_trailing_stop(
                position_id=position.position_id,
                entry_price=position.entry_price_cents,
                current_price=position.current_price_cents,
            )
            if trailing_triggered:
                self._exits_triggered += 1
                self._trailing_exits += 1
                
                self._logger.info(
                    f"[MICRO-SCALP] {trailing_reason.upper()} exit {position.position_id}: "
                    f"price={position.current_price_cents}c high={high_price:.0f}c "
                    f"pnl={profit_pct:.1%}"
                )
                
                self._record_exit(
                    position_id=position.position_id,
                    exit_type=trailing_reason,
                    hold_time=hold_seconds,
                    pnl_pct=profit_pct,
                    target_used=dynamic_target,
                )
                
                return MicroScalpExitAction(
                    should_exit=True,
                    reason=trailing_reason,
                    profit_pct=profit_pct,
                    hold_seconds=hold_seconds,
                    target_used=dynamic_target,
                )
        
        # Exit condition 3: Hold time exceeded (max_hold_seconds from env var, default 180s - micro-scalp override)
        if hold_seconds >= self._config.max_hold_seconds:
            self._exits_triggered += 1
            self._time_exits += 1
            self._logger.info(
                f"[MICRO-SCALP] Time exit {position.position_id}: "
                f"{hold_seconds:.0f}s >= {self._config.max_hold_seconds}s max | "
                f"target={dynamic_target:.1%} achieved={profit_pct:.1%}"
            )
            
            self._record_exit(
                position_id=position.position_id,
                exit_type="max_hold_time",
                hold_time=hold_seconds,
                pnl_pct=profit_pct,
                target_used=dynamic_target,
            )
            
            return MicroScalpExitAction(
                should_exit=True,
                reason="max_hold_time",
                profit_pct=profit_pct,
                hold_seconds=hold_seconds,
                target_used=dynamic_target,
            )
        
        # Exit condition 4: Edge deterioration (50% decay)
        if position.current_edge < (position.entry_edge * self._config.edge_decay_threshold):
            self._exits_triggered += 1
            self._edge_exits += 1
            self._logger.info(
                f"[MICRO-SCALP] Edge decay exit {position.position_id}: "
                f"{position.current_edge:.2%} < {position.entry_edge * self._config.edge_decay_threshold:.2%} threshold"
            )
            return MicroScalpExitAction(
                should_exit=True,
                reason="edge_decay",
                profit_pct=profit_pct,
                hold_seconds=hold_seconds,
                target_used=dynamic_target,
            )
        
        # Exit condition 5: Order book flip (bid/ask pressure reversal)
        if self._config.book_flip_detection and self._detect_book_flip(
            position, current_bid, current_ask
        ):
            self._exits_triggered += 1
            self._flip_exits += 1
            self._logger.info(
                f"[MICRO-SCALP] Book flip exit {position.position_id}: "
                f"pressure reversed against position"
            )
            return MicroScalpExitAction(
                should_exit=True,
                reason="book_flip",
                profit_pct=profit_pct,
                hold_seconds=hold_seconds,
                target_used=dynamic_target,
            )
        
        # No exit condition met
        return MicroScalpExitAction(
            should_exit=False,
            reason="",
            profit_pct=profit_pct,
            hold_seconds=hold_seconds,
            target_used=dynamic_target,
        )
    
    def _record_exit(
        self,
        position_id: str,
        exit_type: str,
        hold_time: float,
        pnl_pct: float,
        target_used: float,
    ) -> None:
        """Record exit for analytics and optimization."""
        self._exit_analytics.append({
            "ts": time.time(),
            "position_id": position_id,
            "exit_type": exit_type,
            "hold_time": hold_time,
            "pnl_pct": pnl_pct,
            "target_used": target_used,
            "target_achieved": pnl_pct >= target_used,
        })
        
        # Keep last 100 entries
        if len(self._exit_analytics) > 100:
            self._exit_analytics = self._exit_analytics[-100:]
    
    def get_exit_analytics(self, window: int = PM_ANALYTICS_WINDOW) -> Dict[str, Any]:
        """Get exit analytics for parameter optimization.
        
        Args:
            window: Number of recent exits to analyze
            
        Returns:
            Dict with time_exit_rate, tp_hit_rate, avg_hold_time, etc.
        """
        recent = self._exit_analytics[-window:] if len(self._exit_analytics) > window else self._exit_analytics
        
        if not recent:
            return {}
        
        total = len(recent)
        time_exits = sum(1 for e in recent if "max_hold_time" in e["exit_type"])
        tp_hits = sum(1 for e in recent if "profit_target" in e["exit_type"] or "dynamic" in e["exit_type"])
        trailing_exits = sum(1 for e in recent if "trailing" in e["exit_type"])
        
        return {
            "total_exits": total,
            "time_exit_rate": time_exits / total if total > 0 else 0,
            "tp_hit_rate": tp_hits / total if total > 0 else 0,
            "trailing_exit_rate": trailing_exits / total if total > 0 else 0,
            "avg_hold_time": sum(e["hold_time"] for e in recent) / total if total > 0 else 0,
            "avg_pnl_pct": sum(e["pnl_pct"] for e in recent) / total if total > 0 else 0,
            "target_achievement_rate": sum(1 for e in recent if e["target_achieved"]) / total if total > 0 else 0,
        }
    
    def optimize_parameters(self) -> None:
        """Optimize dynamic TP parameters based on exit analytics."""
        if not self._use_dynamic_tp or not self._dynamic_tp:
            return
        
        analytics = self.get_exit_analytics(window=PM_ANALYTICS_WINDOW)
        if not analytics or analytics["total_exits"] < PM_MIN_EXITS_FOR_OPTIMIZATION:
            return  # Not enough data
        
        self._logger.info(
            "[TP_OPTIMIZE] Analytics: time_exit_rate=%.1f%%, tp_hit_rate=%.1f%%, "
            "trailing_rate=%.1f%%, avg_hold=%.0fs",
            analytics["time_exit_rate"] * 100,
            analytics["tp_hit_rate"] * 100,
            analytics["trailing_exit_rate"] * 100,
            analytics["avg_hold_time"],
        )
        
        # Adjust dynamic TP parameters
        self._dynamic_tp.adjust_parameters(
            time_exit_rate=analytics["time_exit_rate"],
            tp_hit_rate=analytics["tp_hit_rate"],
        )
    
    def on_position_closed(self, position_id: str) -> None:
        """Clean up when position closes."""
        if self._use_dynamic_tp and self._dynamic_tp:
            self._dynamic_tp.on_position_closed(position_id)
        
        # Trigger optimization every 50 exits
        if self._exits_triggered % PM_ANALYTICS_WINDOW == 0 and self._exits_triggered > 0:
            self.optimize_parameters()
    
    def _detect_book_flip(
        self,
        position: MicroScalpPosition,
        current_bid: int,
        current_ask: int,
    ) -> bool:
        """Detect if order book pressure has flipped against position.
        
        Simple heuristic: for YES positions, exit if bid drops significantly
        below entry. For NO positions, exit if ask rises significantly.
        
        Args:
            position: Current position
            current_bid: Current best bid in cents
            current_ask: Current best ask in cents
            
        Returns:
            True if book flip detected
        """
        if position.side == "yes":
            # For YES positions, we're long - exit if bid drops below entry
            # by more than 3 cents (indicates selling pressure)
            flip_threshold = position.entry_price_cents - 3
            if current_bid > 0 and current_bid < flip_threshold:
                return True
        else:  # "no"
            # For NO positions, we're short - exit if ask rises above entry
            # by more than 3 cents (indicates buying pressure against short)
            flip_threshold = position.entry_price_cents + 3
            if current_ask > 0 and current_ask > flip_threshold:
                return True
        
        return False
    
    def summary(self) -> Dict[str, Any]:
        """Return summary statistics for micro-scalping exits."""
        return {
            "total_exits": self._exits_triggered,
            "profit_exits": self._profit_exits,
            "time_exits": self._time_exits,
            "edge_exits": self._edge_exits,
            "flip_exits": self._flip_exits,
            "config": {
                "profit_target_pct": self._config.profit_target_pct,
                "max_hold_seconds": self._config.max_hold_seconds,
                "edge_decay_threshold": self._config.edge_decay_threshold,
                "book_flip_detection": self._config.book_flip_detection,
                "min_profit_cents": self._config.min_profit_cents,
            },
        }
