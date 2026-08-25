"""Backtesting engine for strategy evaluation.

This module provides backtesting capabilities for:
- Historical strategy performance evaluation
- PnL calculation and analysis
- Win rate and drawdown metrics
- Strategy comparison and optimization
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("merid.backtesting.backtest_engine")


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


class BacktestEngine:
    """Backtesting engine for strategy evaluation."""
    
    def __init__(self, initial_capital_usd: float = 1.00):
        """
        Initialize backtest engine.
        
        Args:
            initial_capital_usd: Starting capital in USD (default $1.00 for Kalshi)
        """
        self.initial_capital_usd = initial_capital_usd
        self.trades: List[Trade] = []
        self.current_capital_usd = initial_capital_usd
        self.peak_capital_usd = initial_capital_usd
        self.capital_history: List[Tuple[datetime, float]] = []
    
    def add_trade(
        self,
        entry_time: datetime,
        asset: str,
        side: str,
        entry_price_cents: int,
        quantity: int,
        entry_reason: str
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
            entry_reason=entry_reason
        )
        self.trades.append(trade)
        return trade
    
    def close_trade(
        self,
        trade: Trade,
        exit_time: datetime,
        exit_price_cents: int,
        exit_reason: str
    ) -> None:
        """
        Close an existing trade.
        
        Args:
            trade: Trade to close
            exit_time: Exit timestamp
            exit_price_cents: Exit price in cents
            exit_reason: Reason for exiting the trade
        """
        trade.exit_time = exit_time
        trade.exit_price_cents = exit_price_cents
        trade.exit_reason = exit_reason
        
        # Update capital
        if trade.pnl_usd is not None:
            self.current_capital_usd += trade.pnl_usd
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
            trades=completed_trades
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
    initial_capital_usd: float = 1.00
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
    
    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital_usd)
    
    for trade_data in trades_data:
        trade = engine.add_trade(
            entry_time=trade_data["entry_time"],
            asset=trade_data["asset"],
            side=trade_data["side"],
            entry_price_cents=trade_data["entry_price_cents"],
            quantity=trade_data["quantity"],
            entry_reason=trade_data["entry_reason"]
        )
        
        engine.close_trade(
            trade=trade,
            exit_time=trade_data["exit_time"],
            exit_price_cents=trade_data["exit_price_cents"],
            exit_reason=trade_data["exit_reason"]
        )
    
    return engine.calculate_results()
