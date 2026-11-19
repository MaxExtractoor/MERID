"""Backtesting engine for strategy evaluation.

This module provides backtesting capabilities for:
- Historical strategy performance evaluation
- PnL calculation and analysis
- Win rate and drawdown metrics
- Strategy comparison and optimization

Fee modeling (2026-11-19): pass ``fee_model="kalshi"`` to
``BacktestEngine``/``run_simple_backtest`` to deduct canonical Kalshi
trading fees from every trade.  Fees follow the venue's parabolic schedule
``rate * C * P * (1-P)`` (taker 0.07 / maker 0.0175, see
``merid.event_venues.kalshi.parabolic_fees``) and are charged on the entry
order always and on the exit order only when the exit is an actual trade
(0 < exit_price_cents < 100).  Settlement at expiry (0c/100c) carries no
trading fee, matching the venue.  ``Trade.pnl_usd`` remains gross;
``Trade.net_pnl_usd`` and the ``BacktestResult`` ``net_*``/``total_fees_usd``
fields carry the fee-adjusted numbers.  Note: return-series backtests
(``walk_forward``, ``kalshi_backtest``) cannot model fees — they have no
per-trade notionals — and remain unsuitable for edge gating on their own.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("merid.backtesting.backtest_engine")


def _kalshi_fee_usd(price_cents: int, contracts: int, role: str) -> float:
    """Canonical Kalshi trading fee in USD for one order leg.

    Delegates to the venue-verified parabolic model (6dp model ceil,
    balance-precision alignment is a conservative bound handled upstream).
    Returns 0.0 on any resolution failure so backtests degrade to gross.
    """
    try:
        from merid.event_venues.kalshi.parabolic_fees import model_trade_fee_dollars

        return float(
            model_trade_fee_dollars(
                price_dollars=float(price_cents) / 100.0,
                contracts=contracts,
                role="maker" if str(role).lower() == "maker" else "taker",
            )
        )
    except Exception:
        return 0.0


@dataclass
class Trade:
    """A single trade in the backtest."""
    entry_time: datetime
    exit_time: Optional[datetime]
    asset: str
    side: str  # "BUY" or "SELL"
    entry_price_cents: int
    exit_price_cents: Optional[int]
    quantity: int
    entry_reason: str
    exit_reason: Optional[str] = None
    entry_role: str = "taker"   # "taker" | "maker" — venue fee role for the entry order
    exit_role: str = "taker"    # venue fee role for the exit order
    entry_fee_usd: float = 0.0  # populated when BacktestEngine fee_model="kalshi"
    exit_fee_usd: float = 0.0

    @property
    def entry_price_usd(self) -> float:
        return self.entry_price_cents / 100.0
    
    @property
    def exit_price_usd(self) -> Optional[float]:
        if self.exit_price_cents is None:
            return None
        return self.exit_price_cents / 100.0
    
    @property
    def pnl_usd(self) -> Optional[float]:
        """Calculate PnL in USD."""
        if self.exit_price_cents is None:
            return None
        
        price_diff = (self.exit_price_cents - self.entry_price_cents) / 100.0
        if self.side == "BUY":
            return price_diff * self.quantity
        else:  # SELL
            return -price_diff * self.quantity
    
    @property
    def pnl_pct(self) -> Optional[float]:
        """Calculate PnL as percentage."""
        if self.exit_price_cents is None or self.entry_price_cents == 0:
            return None
        
        price_diff = self.exit_price_cents - self.entry_price_cents
        if self.side == "BUY":
            return (price_diff / self.entry_price_cents) * 100
        else:  # SELL
            return (-price_diff / self.entry_price_cents) * 100
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Trade duration in seconds."""
        if self.exit_time is None:
            return None
        return (self.exit_time - self.entry_time).total_seconds()

    @property
    def fees_usd(self) -> float:
        """Total Kalshi trading fees for this trade (0 when fee model off)."""
        return float(self.entry_fee_usd or 0.0) + float(self.exit_fee_usd or 0.0)

    @property
    def net_pnl_usd(self) -> Optional[float]:
        """PnL net of trading fees; None while the trade is open."""
        pnl = self.pnl_usd
        if pnl is None:
            return None
        return pnl - self.fees_usd


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl_usd: float
    total_pnl_pct: float
    avg_win_usd: float
    avg_loss_usd: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_trade_duration_seconds: float
    trades: List[Trade] = field(default_factory=list)
    total_fees_usd: float = 0.0
    net_total_pnl_usd: float = 0.0
    net_total_pnl_pct: float = 0.0


class BacktestEngine:
    """Backtesting engine for strategy evaluation."""

    def __init__(self, initial_capital_usd: float = 1.00, fee_model: str = "none"):
        """
        Initialize backtest engine.

        Args:
            initial_capital_usd: Starting capital in USD (default $1.00 for Kalshi)
            fee_model: "none" (gross PnL, legacy) or "kalshi" (deduct canonical
                Kalshi trading fees on entry and on non-settlement exits).
        """
        self.initial_capital_usd = initial_capital_usd
        self.fee_model = str(fee_model or "none").lower()
        self.trades: List[Trade] = []
        self.current_capital_usd = initial_capital_usd
        self.peak_capital_usd = initial_capital_usd
        self.capital_history: List[Tuple[datetime, float]] = []

    def _fees_enabled(self) -> bool:
        return self.fee_model == "kalshi"
    
    def add_trade(
        self,
        entry_time: datetime,
        asset: str,
        side: str,
        entry_price_cents: int,
        quantity: int,
        entry_reason: str,
        entry_role: str = "taker",
    ) -> Trade:
        """
        Add a new trade to the backtest.

        Args:
            entry_time: Entry timestamp
            asset: Asset symbol
            side: "BUY" or "SELL"
            entry_price_cents: Entry price in cents
            quantity: Number of contracts
            entry_reason: Reason for entering the trade
            entry_role: Venue fee role for the entry order ("taker"/"maker")

        Returns:
            Trade object
        """
        trade = Trade(
            entry_time=entry_time,
            exit_time=None,
            asset=asset,
            side=side,
            entry_price_cents=entry_price_cents,
            exit_price_cents=None,
            quantity=quantity,
            entry_reason=entry_reason,
            entry_role=entry_role,
        )
        if self._fees_enabled():
            trade.entry_fee_usd = _kalshi_fee_usd(entry_price_cents, quantity, entry_role)
        self.trades.append(trade)
        return trade

    def close_trade(
        self,
        trade: Trade,
        exit_time: datetime,
        exit_price_cents: int,
        exit_reason: str,
        exit_role: Optional[str] = None,
    ) -> None:
        """
        Close an existing trade.

        Args:
            trade: Trade to close
            exit_time: Exit timestamp
            exit_price_cents: Exit price in cents
            exit_reason: Reason for exiting the trade
            exit_role: Venue fee role for the exit order ("taker"/"maker");
                defaults to the trade's exit_role ("taker")
        """
        trade.exit_time = exit_time
        trade.exit_price_cents = exit_price_cents
        trade.exit_reason = exit_reason
        if exit_role is not None:
            trade.exit_role = exit_role

        # Kalshi charges trading fees on orders, not on expiry settlement.
        # A 0c/100c exit is the settlement payoff; only real sell prices pay.
        if self._fees_enabled() and 0 < int(exit_price_cents) < 100:
            trade.exit_fee_usd = _kalshi_fee_usd(
                int(exit_price_cents), int(trade.quantity), trade.exit_role
            )

        # Update capital (net of fees when the Kalshi fee model is enabled)
        if trade.pnl_usd is not None:
            self.current_capital_usd += trade.net_pnl_usd if trade.net_pnl_usd is not None else trade.pnl_usd
            self.capital_history.append((exit_time, self.current_capital_usd))

            # Track peak capital
            if self.current_capital_usd > self.peak_capital_usd:
                self.peak_capital_usd = self.current_capital_usd
    
    def calculate_results(self) -> BacktestResult:
        """
        Calculate backtest results.
        
        Returns:
            BacktestResult with performance metrics
        """
        completed_trades = [t for t in self.trades if t.exit_time is not None]
        
        if not completed_trades:
            return BacktestResult(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl_usd=0.0,
                total_pnl_pct=0.0,
                avg_win_usd=0.0,
                avg_loss_usd=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
                avg_trade_duration_seconds=0.0
            )
        
        total_trades = len(completed_trades)
        winning_trades = [t for t in completed_trades if (t.pnl_usd or 0) > 0]
        losing_trades = [t for t in completed_trades if (t.pnl_usd or 0) < 0]
        
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        
        total_pnl_usd = sum(t.pnl_usd or 0 for t in completed_trades)
        total_pnl_pct = (total_pnl_usd / self.initial_capital_usd) * 100
        
        avg_win_usd = np.mean([t.pnl_usd for t in winning_trades]) if winning_trades else 0.0
        avg_loss_usd = np.mean([t.pnl_usd for t in losing_trades]) if losing_trades else 0.0
        
        # Calculate max drawdown
        max_drawdown_usd = 0.0
        running_capital = self.initial_capital_usd
        peak_capital = self.initial_capital_usd
        
        for trade in sorted(completed_trades, key=lambda t: t.exit_time or t.entry_time):
            if trade.pnl_usd is not None:
                running_capital += trade.pnl_usd
                if running_capital > peak_capital:
                    peak_capital = running_capital
                drawdown = peak_capital - running_capital
                if drawdown > max_drawdown_usd:
                    max_drawdown_usd = drawdown
        
        max_drawdown_pct = (max_drawdown_usd / self.initial_capital_usd) * 100
        
        # Calculate Sharpe ratio (simplified, assuming 0% risk-free rate)
        if completed_trades:
            returns = [t.pnl_pct or 0 for t in completed_trades]
            sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Calculate profit factor
        total_wins = sum(t.pnl_usd or 0 for t in winning_trades)
        total_losses = abs(sum(t.pnl_usd or 0 for t in losing_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        # Calculate average trade duration
        durations = [t.duration_seconds for t in completed_trades if t.duration_seconds is not None]
        avg_trade_duration_seconds = np.mean(durations) if durations else 0.0

        total_fees_usd = sum(t.fees_usd for t in completed_trades)
        net_total_pnl_usd = total_pnl_usd - total_fees_usd
        net_total_pnl_pct = (net_total_pnl_usd / self.initial_capital_usd) * 100

        result = BacktestResult(
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            total_pnl_usd=total_pnl_usd,
            total_pnl_pct=total_pnl_pct,
            avg_win_usd=avg_win_usd,
            avg_loss_usd=avg_loss_usd,
            max_drawdown_usd=max_drawdown_usd,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            avg_trade_duration_seconds=avg_trade_duration_seconds,
            trades=completed_trades,
            total_fees_usd=total_fees_usd,
            net_total_pnl_usd=net_total_pnl_usd,
            net_total_pnl_pct=net_total_pnl_pct,
        )
        
        logger.info(
            "[BACKTEST] Results: %d trades, win_rate=%.1f%%, pnl=%.2f%%, "
            "max_dd=%.2f%%, sharpe=%.2f, profit_factor=%.2f",
            total_trades, win_rate * 100, total_pnl_pct, max_drawdown_pct,
            sharpe_ratio, profit_factor
        )
        
        return result
    
    def reset(self) -> None:
        """Reset the backtest engine."""
        self.trades = []
        self.current_capital_usd = self.initial_capital_usd
        self.peak_capital_usd = self.initial_capital_usd
        self.capital_history = []


def run_simple_backtest(
    trades_data: List[Dict],
    initial_capital_usd: float = 1.00,
    fee_model: str = "none",
    entry_role: str = "taker",
    exit_role: str = "taker",
) -> BacktestResult:
    """
    Run a simple backtest from trade data.

    Args:
        trades_data: List of trade dicts with keys:
            - entry_time: datetime
            - exit_time: datetime
            - asset: str
            - side: str
            - entry_price_cents: int
            - exit_price_cents: int
            - quantity: int
            - entry_reason: str
            - exit_reason: str
        initial_capital_usd: Starting capital
        fee_model: "none" (gross) or "kalshi" (canonical Kalshi trading fees)
        entry_role: Venue fee role for entries ("taker"/"maker")
        exit_role: Venue fee role for non-settlement exits ("taker"/"maker")

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital_usd, fee_model=fee_model)

    for trade_data in trades_data:
        trade = engine.add_trade(
            entry_time=trade_data["entry_time"],
            asset=trade_data["asset"],
            side=trade_data["side"],
            entry_price_cents=trade_data["entry_price_cents"],
            quantity=trade_data["quantity"],
            entry_reason=trade_data["entry_reason"],
            entry_role=trade_data.get("entry_role", entry_role),
        )

        engine.close_trade(
            trade=trade,
            exit_time=trade_data["exit_time"],
            exit_price_cents=trade_data["exit_price_cents"],
            exit_reason=trade_data["exit_reason"],
            exit_role=trade_data.get("exit_role", exit_role),
        )
    
    return engine.calculate_results()
