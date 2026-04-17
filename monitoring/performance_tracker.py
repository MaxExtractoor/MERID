"""
Performance Tracker.

Tracks trading and system performance metrics.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import deque

from monitoring.metrics_collector import get_metrics_collector
from utils.logger import get_logger

logger = get_logger("monitoring.performance")


@dataclass
class TradePerformance:
    """Performance metrics for a trade."""
    trade_id: str
    symbol: str
    side: str
    
    # Execution
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    
    # P&L
    pnl_usd: float = 0.0
    pnl_percent: float = 0.0
    
    # Timing
    entry_time: float = 0.0
    exit_time: float = 0.0
    hold_time_seconds: float = 0.0
    
    # Execution quality
    slippage_bps: float = 0.0
    execution_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "pnl_usd": self.pnl_usd,
            "pnl_percent": self.pnl_percent,
            "hold_time_seconds": self.hold_time_seconds,
            "slippage_bps": self.slippage_bps,
            "execution_latency_ms": self.execution_latency_ms,
        }


@dataclass
class PerformanceSummary:
    """Summary of performance metrics."""
    period: str  # daily, weekly, monthly
    start_time: float
    end_time: float
    
    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # P&L
    total_pnl_usd: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    
    # Ratios
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    
    # Risk metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    
    # Execution
    avg_slippage_bps: float = 0.0
    avg_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_pnl_usd": self.total_pnl_usd,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "avg_slippage_bps": self.avg_slippage_bps,
            "avg_latency_ms": self.avg_latency_ms,
        }


class PerformanceTracker:
    """
    Tracks trading and system performance.
    
    Features:
    - Trade-level performance tracking
    - Period summaries (daily, weekly, monthly)
    - Risk metrics calculation
    - Execution quality metrics
    """
    
    def __init__(self):
        self.logger = get_logger("monitoring.performance")
        self._metrics = get_metrics_collector()
        
        # Trade history
        self._trades: deque = deque(maxlen=10000)
        
        # Equity curve
        self._equity_curve: List[Dict[str, float]] = []
        self._initial_equity: float = 100000.0
        self._current_equity: float = 100000.0
        self._peak_equity: float = 100000.0
        
        # Period summaries
        self._daily_summaries: Dict[str, PerformanceSummary] = {}
        
        # Running stats
        self._total_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
    
    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        entry_time: float,
        exit_time: float,
        slippage_bps: float = 0.0,
        execution_latency_ms: float = 0.0,
    ) -> TradePerformance:
        """Record a completed trade."""
        # Calculate P&L
        if side == "buy":
            pnl_usd = (exit_price - entry_price) * quantity
        else:
            pnl_usd = (entry_price - exit_price) * quantity
        
        pnl_percent = (pnl_usd / (entry_price * quantity)) * 100 if entry_price > 0 else 0
        
        trade = TradePerformance(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl_usd=pnl_usd,
            pnl_percent=pnl_percent,
            entry_time=entry_time,
            exit_time=exit_time,
            hold_time_seconds=exit_time - entry_time,
            slippage_bps=slippage_bps,
            execution_latency_ms=execution_latency_ms,
        )
        
        self._trades.append(trade)
        
        # Update running stats
        self._total_pnl += pnl_usd
        self._total_trades += 1
        if pnl_usd > 0:
            self._winning_trades += 1
        
        # Update equity
        self._current_equity += pnl_usd
        self._peak_equity = max(self._peak_equity, self._current_equity)
        
        self._equity_curve.append({
            "timestamp": time.time(),
            "equity": self._current_equity,
            "pnl": pnl_usd,
        })
        
        # Update metrics
        self._metrics.increment("trades_total")
        self._metrics.increment("trade_volume_usd", abs(entry_price * quantity))
        self._metrics.record("trade_latency", execution_latency_ms)
        
        self.logger.info(f"Trade recorded: {trade_id} - P&L: ${pnl_usd:.2f}")
        
        return trade
    
    def get_summary(self, period: str = "all") -> PerformanceSummary:
        """Get performance summary for a period."""
        now = time.time()
        
        if period == "daily":
            start_time = now - 86400
        elif period == "weekly":
            start_time = now - (7 * 86400)
        elif period == "monthly":
            start_time = now - (30 * 86400)
        else:
            start_time = 0
        
        # Filter trades
        trades = [t for t in self._trades if t.exit_time >= start_time]
        
        if not trades:
            return PerformanceSummary(period=period, start_time=start_time, end_time=now)
        
        # Calculate stats
        winning = [t for t in trades if t.pnl_usd > 0]
        losing = [t for t in trades if t.pnl_usd < 0]
        
        gross_profit = sum(t.pnl_usd for t in winning)
        gross_loss = abs(sum(t.pnl_usd for t in losing))
        
        summary = PerformanceSummary(
            period=period,
            start_time=start_time,
            end_time=now,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            total_pnl_usd=sum(t.pnl_usd for t in trades),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            win_rate=len(winning) / len(trades) * 100 if trades else 0,
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            avg_win=gross_profit / len(winning) if winning else 0,
            avg_loss=gross_loss / len(losing) if losing else 0,
            max_drawdown_pct=self._calculate_max_drawdown(),
            sharpe_ratio=self._calculate_sharpe_ratio(trades),
            avg_slippage_bps=sum(t.slippage_bps for t in trades) / len(trades) if trades else 0,
            avg_latency_ms=sum(t.execution_latency_ms for t in trades) / len(trades) if trades else 0,
        )
        
        return summary
    
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage."""
        if self._peak_equity <= 0:
            return 0.0
        
        drawdown = (self._peak_equity - self._current_equity) / self._peak_equity * 100
        return max(drawdown, 0)
    
    def _calculate_sharpe_ratio(self, trades: List[TradePerformance], risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio."""
        if len(trades) < 2:
            return 0.0
        
        returns = [t.pnl_percent for t in trades]
        avg_return = sum(returns) / len(returns)
        
        # Calculate standard deviation
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return 0.0
        
        # Annualize (assuming daily returns)
        sharpe = (avg_return - risk_free_rate / 365) / std_dev * (365 ** 0.5)
        return sharpe
    
    def get_equity_curve(self, limit: int = 1000) -> List[Dict[str, float]]:
        """Get equity curve data."""
        return self._equity_curve[-limit:]
    
    def get_recent_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades."""
        trades = list(self._trades)[-limit:]
        return [t.to_dict() for t in trades]
    
    def get_trades_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Get trades for a specific symbol."""
        trades = [t for t in self._trades if t.symbol == symbol]
        return [t.to_dict() for t in trades]
    
    def get_symbol_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get performance breakdown by symbol."""
        by_symbol: Dict[str, List[TradePerformance]] = {}
        
        for trade in self._trades:
            if trade.symbol not in by_symbol:
                by_symbol[trade.symbol] = []
            by_symbol[trade.symbol].append(trade)
        
        result = {}
        for symbol, trades in by_symbol.items():
            winning = [t for t in trades if t.pnl_usd > 0]
            result[symbol] = {
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "win_rate": len(winning) / len(trades) * 100 if trades else 0,
                "total_pnl": sum(t.pnl_usd for t in trades),
                "avg_pnl": sum(t.pnl_usd for t in trades) / len(trades) if trades else 0,
            }
        
        return result
    
    def set_initial_equity(self, equity: float) -> None:
        """Set initial equity."""
        self._initial_equity = equity
        self._current_equity = equity
        self._peak_equity = equity
    
    def get_status(self) -> Dict[str, Any]:
        """Get tracker status."""
        return {
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": self._winning_trades / self._total_trades * 100 if self._total_trades > 0 else 0,
            "total_pnl": self._total_pnl,
            "current_equity": self._current_equity,
            "peak_equity": self._peak_equity,
            "max_drawdown_pct": self._calculate_max_drawdown(),
            "summary": self.get_summary("all").to_dict(),
        }


# Singleton
_performance_tracker: Optional[PerformanceTracker] = None
_performance_tracker_lock = threading.Lock()


def get_performance_tracker() -> PerformanceTracker:
    """Get or create the Performance Tracker singleton."""
    global _performance_tracker
    if _performance_tracker is None:
        with _performance_tracker_lock:
            if _performance_tracker is None:
                _performance_tracker = PerformanceTracker()
    return _performance_tracker
