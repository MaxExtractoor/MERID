"""Kalshi Backtesting Framework — Replay historical snapshots through strategies.

Provides a lightweight simulation engine that feeds ``MarketSnapshot`` objects
through a user-supplied strategy function, simulates fills (with optional
orderbook slippage), and tracks PnL / position state.

Usage::

    from merid.event_venues.kalshi.backtest import (
        MarketSnapshot, BacktestState, TradeDecision, backtest,
    )
    from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENT

    def my_strategy(snap: MarketSnapshot, state: BacktestState) -> list[TradeDecision]:
        ...

    snapshots = [...]  # from WS logs or historical data
    result = backtest(snapshots, initial_cash_cents=500_000, strategy_fn=my_strategy)
    print(result.pnl_history[-1])
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.backtest")


# ── Data models ──────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    """Point-in-time orderbook + last-trade for one market."""

    ts: float                          # epoch seconds
    ticker: str
    yes_book: List[List[int]]          # [[price_cents, size], ...] best→worst
    no_book: List[List[int]]           # [[price_cents, size], ...]
    last_trade_price: Optional[int] = None
    volume: int = 0


@dataclass
class TradeDecision:
    """A single order intent produced by a strategy."""

    ticker: str
    side: str       # "yes" or "no"
    action: str     # "buy" or "sell"
    price_cents: int
    count: int


@dataclass
class BacktestState:
    """Mutable portfolio state carried through the simulation."""

    cash_cents: int
    positions: Dict[str, int] = field(default_factory=dict)   # ticker → net contracts
    pnl_history: List[int] = field(default_factory=list)
    trade_log: List[Dict[str, Any]] = field(default_factory=list)
    total_fees_cents: int = 0
    total_trades: int = 0


# ── Fill simulation ──────────────────────────────────────────────────────

def simulate_fill(
    price_cents: int,
    count: int,
    book: Optional[List[List[int]]] = None,
) -> Tuple[int, int]:
    """Simulate a fill, optionally walking the orderbook for slippage.

    Args:
        price_cents: Requested limit price (cents)
        count: Number of contracts
        book: Optional orderbook levels [[price, size], ...]

    Returns:
        (avg_fill_price_cents, filled_count)
    """
    if not book:
        # Simple: fill at requested price
        return price_cents, count

    filled = 0
    total_cost = 0
    for level_price, level_size in book:
        if filled >= count:
            break
        # For a buy, we accept levels at or below our limit
        # For a sell, we accept levels at or above our limit
        # Simplified: just walk levels in order
        can_fill = min(count - filled, level_size)
        total_cost += level_price * can_fill
        filled += can_fill

    if filled == 0:
        return price_cents, 0

    avg_price = total_cost // filled
    return avg_price, filled


def _kalshi_fee_for_backtest(price_cents: int, contracts: int) -> int:
    """Inline fee calc for backtesting (avoids circular import issues)."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    payout = 100 - price_cents
    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03
    per_contract = max(2, math.ceil(payout * rate))
    return per_contract * contracts


# ── Backtest engine ──────────────────────────────────────────────────────

StrategyFn = Callable[[MarketSnapshot, BacktestState], List[TradeDecision]]


def backtest(
    snapshots: List[MarketSnapshot],
    initial_cash_cents: int,
    strategy_fn: StrategyFn,
    *,
    use_orderbook_slippage: bool = False,
    include_fees: bool = True,
) -> BacktestState:
    """Run a strategy over historical snapshots.

    Args:
        snapshots: Chronologically ordered market snapshots
        initial_cash_cents: Starting cash in cents
        strategy_fn: ``(snapshot, state) -> [TradeDecision, ...]``
        use_orderbook_slippage: Walk the orderbook for realistic fills
        include_fees: Apply Kalshi fee schedule to fills

    Returns:
        Final BacktestState with pnl_history, trade_log, etc.
    """
    state = BacktestState(cash_cents=initial_cash_cents)

    # Index latest snapshot per ticker for mark-to-market
    latest_prices: Dict[str, int] = {}

    for snap in snapshots:
        # Update latest price for this ticker
        if snap.last_trade_price is not None:
            latest_prices[snap.ticker] = snap.last_trade_price
        elif snap.yes_book:
            latest_prices[snap.ticker] = snap.yes_book[0][0]

        # Get strategy decisions
        try:
            decisions = strategy_fn(snap, state)
        except Exception as exc:
            logger.warning(f"Strategy error at ts={snap.ts}: {exc}")
            decisions = []

        # Execute decisions
        for d in decisions:
            book = None
            if use_orderbook_slippage:
                book = snap.yes_book if d.side == "yes" else snap.no_book

            fill_price, filled = simulate_fill(d.price_cents, d.count, book)
            if filled <= 0:
                continue

            notional = fill_price * filled
            fee = _kalshi_fee_for_backtest(fill_price, filled) if include_fees else 0

            if d.action == "buy":
                state.cash_cents -= notional + fee
                state.positions[d.ticker] = state.positions.get(d.ticker, 0) + filled
            else:  # sell
                state.cash_cents += notional - fee
                state.positions[d.ticker] = state.positions.get(d.ticker, 0) - filled

            state.total_fees_cents += fee
            state.total_trades += 1
            state.trade_log.append({
                "ts": snap.ts,
                "ticker": d.ticker,
                "side": d.side,
                "action": d.action,
                "price": fill_price,
                "count": filled,
                "fee": fee,
            })

        # Mark-to-market
        mtm = 0
        for ticker, pos in state.positions.items():
            price = latest_prices.get(ticker, DEFAULT_KALSHI_PRICE_CENTS)
            mtm += pos * price
        state.pnl_history.append(state.cash_cents + mtm)

    return state


def backtest_summary(state: BacktestState, initial_cash_cents: int) -> Dict[str, Any]:
    """Generate a summary dict from a completed backtest."""
    final_equity = state.pnl_history[-1] if state.pnl_history else state.cash_cents
    pnl_cents = final_equity - initial_cash_cents
    peak = max(state.pnl_history) if state.pnl_history else initial_cash_cents
    trough = min(state.pnl_history) if state.pnl_history else initial_cash_cents
    max_drawdown = peak - trough

    return {
        "initial_cash_usd": initial_cash_cents / 100,
        "final_equity_usd": final_equity / 100,
        "pnl_usd": pnl_cents / 100,
        "return_pct": round(pnl_cents / initial_cash_cents * 100, 2) if initial_cash_cents else 0,
        "total_trades": state.total_trades,
        "total_fees_usd": state.total_fees_cents / 100,
        "max_drawdown_usd": max_drawdown / 100,
        "open_positions": {k: v for k, v in state.positions.items() if v != 0},
        "snapshots_processed": len(state.pnl_history),
    }


# ── Kalman backtest strategy ─────────────────────────────────────────────

@dataclass
class PriceCandle:
    """Single price observation for Kalman backtesting."""
    ts: float           # Unix timestamp or sequential index
    price_cents: float  # Price in cents


def backtest_kalman_strategy(
    candles: List[PriceCandle],
    q: float = 0.01,
    r: float = 0.1,
    threshold_cents: float = 2.0,
) -> Dict[str, Any]:
    """Backtest a simple Kalman-based long/flat strategy.

    Enter +1 contract when Kalman fair price > current + threshold;
    exit to flat when the signal disappears.

    Args:
        candles: Time-ordered price observations
        q: Kalman process variance
        r: Kalman measurement variance
        threshold_cents: Minimum edge in cents to enter

    Returns:
        Dict with pnl_usd, total_trades, win_trades, loss_trades, hit_rate
    """
    from merid.event_venues.kalshi.volume_monitor import PriceKalman

    kf = PriceKalman(process_var=q, meas_var=r)
    position = 0
    cash = 0.0
    entry_price = 0.0
    total_trades = 0
    win_trades = 0
    loss_trades = 0

    for c in candles:
        pred = kf.x if kf.initialized else c.price_cents
        kf.update(c.price_cents)

        want_long = pred > c.price_cents + threshold_cents

        if want_long and position == 0:
            position = 1
            entry_price = c.price_cents
            cash -= c.price_cents / 100.0
        elif not want_long and position == 1:
            position = 0
            cash += c.price_cents / 100.0
            total_trades += 1
            if c.price_cents > entry_price:
                win_trades += 1
            else:
                loss_trades += 1

    # Liquidate at last price
    if position != 0 and candles:
        last_px = candles[-1].price_cents
        cash += position * (last_px / 100.0)
        total_trades += 1
        if last_px > entry_price:
            win_trades += 1
        else:
            loss_trades += 1
        position = 0

    hit_rate = win_trades / total_trades if total_trades > 0 else 0.0

    return {
        "pnl_usd": round(cash, 4),
        "total_trades": total_trades,
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "hit_rate": round(hit_rate, 4),
        "q": q,
        "r": r,
        "threshold_cents": threshold_cents,
    }
