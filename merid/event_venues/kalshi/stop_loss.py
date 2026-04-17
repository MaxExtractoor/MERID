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

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    _SL_DROP = 20
    _SL_FLOOR = 8
    _SL_TRADE_PCT = 2.0
    _SL_SESSION_PCT = 5.0
    _SL_LOSING_PCT = 0.75


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
    # Driven by MERID_SL_SESSION_LOSS_CAP_PCT (default 5.0).
    session_loss_cap_pct: float = _SL_SESSION_PCT

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

        # 1. Price floor
        if pos.current_price_cents > 0 and pos.current_price_cents <= cfg.price_floor_cents:
            return StopAction(
                should_close=True,
                reason=f"Price {pos.current_price_cents}c <= floor {cfg.price_floor_cents}c",
                rule="price_floor",
                urgency="high",
            )

        # 2. Price invalidation (drop from entry)
        if pos.current_price_cents > 0 and cfg.price_invalidation_drop_cents > 0:
            if pos.side == "yes":
                drop = pos.entry_price_cents - pos.current_price_cents
            else:
                drop = pos.current_price_cents - pos.entry_price_cents
            if drop >= cfg.price_invalidation_drop_cents:
                return StopAction(
                    should_close=True,
                    reason=(
                        f"Price dropped {drop}c from entry "
                        f"(invalidation threshold: {cfg.price_invalidation_drop_cents}c)"
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

        # 4a. B7: percentage-based take-profit (takes precedence when set)
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
