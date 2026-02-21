"""Kalshi Historical Simulator — Trade-interleaved simulation for BTC hourlies.

Unlike the snapshot-based ``backtest()`` engine (which replays orderbook
snapshots), this simulator interleaves strategy orders with a historical
*trade stream* and matches them using a simple market-taker model.

This mirrors the S&P simulator pattern: orders are matched against the
next historical trade on the correct side, with fees applied.

Usage::

    from merid.event_venues.kalshi.historical_sim import (
        HistoricalTrade, SimOrder, KalshiHistoricalSimulator,
    )

    trades = [...]  # from DB or archiver
    sim = KalshiHistoricalSimulator(trades, fee_bps=50)
    fills = sim.run(my_strategy)
    print(sim.summary())

Integration with PaperSession::

    sim = KalshiHistoricalSimulator(trades)
    fills = sim.run(strategy)
    sim.replay_into_paper_session(session, "BTC_HOURLY")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.historical_sim")


# ── Data models ──────────────────────────────────────────────────────────

@dataclass
class HistoricalTrade:
    """A single historical trade from the Kalshi trade stream."""
    ts: int              # epoch seconds
    price: Decimal       # contract price 0–1 (e.g. Decimal("0.55"))
    size: int            # contracts
    side: str            # "buy" or "sell" (taker side)
    ticker: str = ""     # market ticker (optional, for multi-market sims)


@dataclass
class SimOrder:
    """An order intent produced by a strategy during simulation."""
    ts: int
    price: Decimal       # limit price 0–1
    size: int            # contracts
    side: str            # "buy" = lifting asks, "sell" = hitting bids
    ticker: str = ""


@dataclass
class SimFill:
    """A simulated fill resulting from order matching."""
    ts: int
    price: Decimal
    size: int
    side: str
    fee: Decimal
    pnl_cents: float = 0.0  # set at settlement or close
    ticker: str = ""


@dataclass
class SimState:
    """Mutable portfolio state during simulation."""
    position: int = 0
    cash: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    fills: List[SimFill] = field(default_factory=list)
    entry_prices: List[Decimal] = field(default_factory=list)
    high_water_mark: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    consecutive_losers: int = 0
    max_consecutive_losers: int = 0


# ── Strategy type ────────────────────────────────────────────────────────

StrategyFn = Callable[[HistoricalTrade, SimState], Iterable[SimOrder]]


# ── Fee calculation ──────────────────────────────────────────────────────

def _sim_fee(price: Decimal, size: int, fee_bps: int) -> Decimal:
    """Compute fee for a simulated fill.

    Args:
        price: Contract price (0–1 decimal)
        size: Number of contracts
        fee_bps: Fee in basis points of notional

    Returns:
        Fee as Decimal
    """
    notional = price * size
    return notional * Decimal(fee_bps) / Decimal(10_000)


# ── Simulator ────────────────────────────────────────────────────────────

class KalshiHistoricalSimulator:
    """Trade-interleaved historical simulator for Kalshi markets.

    For each historical trade tick, the strategy produces zero or more
    orders.  Orders are matched against the tick using a simple
    market-taker model:

    - A ``buy`` order fills if the tick's taker side is ``sell``
      (i.e. someone is selling into the book, providing liquidity).
    - A ``sell`` order fills if the tick's taker side is ``buy``.

    Fills are executed at the historical trade price with fees applied.
    """

    def __init__(
        self,
        trades: List[HistoricalTrade],
        fee_bps: int = 50,
        *,
        max_consecutive_losers: int = 0,
    ) -> None:
        """
        Args:
            trades: Historical trade stream (will be sorted by ts).
            fee_bps: Fee in basis points of notional (default 50 = 0.5%).
            max_consecutive_losers: Auto-halt after N consecutive losing
                round-trips (0 = disabled).
        """
        self.trades = sorted(trades, key=lambda t: t.ts)
        self.fee_bps = fee_bps
        self.max_consecutive_losers = max_consecutive_losers
        self._state = SimState()
        self._halted = False
        self._halt_reason: Optional[str] = None

    @property
    def state(self) -> SimState:
        return self._state

    @property
    def halted(self) -> bool:
        return self._halted

    def run(self, strategy: StrategyFn) -> List[SimFill]:
        """Run the simulation over the full trade stream.

        Args:
            strategy: ``(trade, state) -> Iterable[SimOrder]``

        Returns:
            List of all fills produced during the simulation.
        """
        for tick in self.trades:
            if self._halted:
                break

            try:
                orders = strategy(tick, self._state)
            except Exception as exc:
                logger.warning(f"Strategy error at ts={tick.ts}: {exc}")
                continue

            for order in orders:
                if self._halted:
                    break
                fill = self._match(order, tick)
                if fill:
                    self._state.fills.append(fill)

        return list(self._state.fills)

    def _match(self, order: SimOrder, tick: HistoricalTrade) -> Optional[SimFill]:
        """Try to match an order against a historical trade tick."""
        # Market-taker model: buy fills against sell ticks, sell against buy ticks
        if order.side == "buy" and tick.side == "sell":
            return self._execute(order, tick.price, tick.ts, +1, tick.ticker)
        if order.side == "sell" and tick.side == "buy":
            return self._execute(order, tick.price, tick.ts, -1, tick.ticker)
        return None

    def _execute(
        self,
        order: SimOrder,
        price: Decimal,
        ts: int,
        dir_sign: int,
        ticker: str,
    ) -> SimFill:
        """Execute a fill and update portfolio state."""
        notional = price * order.size
        fee = _sim_fee(price, order.size, self.fee_bps)

        old_position = self._state.position
        self._state.position += dir_sign * order.size
        self._state.cash -= dir_sign * notional
        self._state.cash -= fee
        self._state.total_fees += fee
        self._state.total_trades += 1

        # Track entry prices for PnL on close
        pnl_cents = 0.0
        if dir_sign > 0:
            # Opening long
            self._state.entry_prices.extend([price] * order.size)
        elif dir_sign < 0 and self._state.entry_prices:
            # Closing long — compute PnL
            closed = min(order.size, len(self._state.entry_prices))
            for _ in range(closed):
                entry = self._state.entry_prices.pop(0)
                trade_pnl = float((price - entry) * 100)  # cents
                pnl_cents += trade_pnl
            pnl_cents -= float(fee * 100)

            if pnl_cents > 0:
                self._state.winning_trades += 1
                self._state.consecutive_losers = 0
            elif pnl_cents < 0:
                self._state.losing_trades += 1
                self._state.consecutive_losers += 1
                if self._state.consecutive_losers > self._state.max_consecutive_losers:
                    self._state.max_consecutive_losers = self._state.consecutive_losers

            # Check consecutive loser kill-switch
            if (
                self.max_consecutive_losers > 0
                and self._state.consecutive_losers >= self.max_consecutive_losers
            ):
                self._halted = True
                self._halt_reason = (
                    f"Consecutive losers: {self._state.consecutive_losers} "
                    f">= {self.max_consecutive_losers}"
                )
                logger.warning(f"[sim] HALTED: {self._halt_reason}")

        # Update HWM / drawdown
        equity = self._state.cash
        if equity > self._state.high_water_mark:
            self._state.high_water_mark = equity
        dd = self._state.high_water_mark - equity
        if dd > self._state.max_drawdown:
            self._state.max_drawdown = dd

        return SimFill(
            ts=ts,
            price=price,
            size=order.size,
            side=order.side,
            fee=fee,
            pnl_cents=pnl_cents,
            ticker=ticker or order.ticker,
        )

    # ── PaperSession integration ─────────────────────────────────────

    def replay_into_paper_session(
        self,
        session: Any,
        agent_name: str,
    ) -> Dict[str, Any]:
        """Replay all fills into a PaperSession for unified tracking.

        Args:
            session: A ``PaperSession`` instance
            agent_name: Cell name (e.g. "BTC_HOURLY")

        Returns:
            Summary dict with counts and any risk actions triggered.
        """
        risk_actions: List[Dict[str, Any]] = []
        accepted = 0
        rejected = 0

        for fill in self._state.fills:
            won = fill.pnl_cents > 0 if fill.side == "sell" else None
            result = session.record_fill(
                agent_name,
                pnl_cents=fill.pnl_cents,
                fees_cents=float(fill.fee * 100),
                won=won,
            )
            if result.get("accepted"):
                accepted += 1
                actions = result.get("risk_actions", [])
                risk_actions.extend(actions)
            else:
                rejected += 1

        return {
            "agent": agent_name,
            "total_fills": len(self._state.fills),
            "accepted": accepted,
            "rejected": rejected,
            "risk_actions": risk_actions,
        }

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Generate a summary of the simulation run."""
        total = self._state.total_trades
        wins = self._state.winning_trades
        losses = self._state.losing_trades

        win_rate = wins / total * 100 if total > 0 else 0.0
        total_pnl = sum(f.pnl_cents for f in self._state.fills)

        return {
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_cents": round(total_pnl, 2),
            "total_pnl_usd": round(total_pnl / 100, 4),
            "total_fees_usd": round(float(self._state.total_fees), 4),
            "cash": round(float(self._state.cash), 4),
            "position": self._state.position,
            "max_drawdown_usd": round(float(self._state.max_drawdown), 4),
            "max_consecutive_losers": self._state.max_consecutive_losers,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "fill_count": len(self._state.fills),
        }
