"""
Performance Analytics Module for MERID.

Tracks and analyzes:
- Trade history and statistics
- P&L over time
- Agent performance metrics
- Win/loss ratios
- Sharpe ratio and risk metrics
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("analytics.performance")


@dataclass
class TradeRecord:
    """Record of a completed trade."""
    trade_id: str
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    entry_time: float
    exit_time: float
    duration_seconds: float
    agent_source: Optional[str] = None
    consensus_round_id: Optional[str] = None


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance snapshot."""
    timestamp: float
    equity: float
    balance: float
    unrealized_pnl: float
    realized_pnl: float
    open_positions: int
    total_trades: int


class PerformanceTracker:
    """
    Tracks and analyzes trading performance over time.
    """
    
    def __init__(self):
        self._trades: List[TradeRecord] = []
        self._snapshots: List[PerformanceSnapshot] = []
        self._agent_trades: Dict[str, List[TradeRecord]] = defaultdict(list)
        
        # Running metrics
        self._total_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._largest_win: float = 0.0
        self._largest_loss: float = 0.0
        self._peak_equity: float = 100000.0
        self._max_drawdown: float = 0.0
        
        self._start_time = time.time()
        
        logger.info("Performance tracker initialized")
    
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
        agent_source: Optional[str] = None,
        consensus_round_id: Optional[str] = None,
    ) -> TradeRecord:
        """Record a completed trade."""
        # Calculate P&L
        if side == 'long':
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity
        
        pnl_pct = (pnl / (entry_price * quantity)) * 100 if entry_price > 0 else 0
        
        trade = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            entry_time=entry_time,
            exit_time=exit_time,
            duration_seconds=exit_time - entry_time,
            agent_source=agent_source,
            consensus_round_id=consensus_round_id,
        )
        
        self._trades.append(trade)
        self._total_trades += 1
        self._total_pnl += pnl
        
        if pnl > 0:
            self._winning_trades += 1
            self._largest_win = max(self._largest_win, pnl)
        else:
            self._losing_trades += 1
            self._largest_loss = min(self._largest_loss, pnl)
        
        # Track by agent
        if agent_source:
            self._agent_trades[agent_source].append(trade)
        
        logger.info(
            "Trade recorded: %s %s %.4f %s P&L: $%.2f (%.2f%%)",
            trade_id[:8], side, quantity, symbol, pnl, pnl_pct
        )
        
        return trade
    
    def record_snapshot(
        self,
        equity: float,
        balance: float,
        unrealized_pnl: float,
        realized_pnl: float,
        open_positions: int,
    ) -> None:
        """Record a performance snapshot."""
        snapshot = PerformanceSnapshot(
            timestamp=time.time(),
            equity=equity,
            balance=balance,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            open_positions=open_positions,
            total_trades=self._total_trades,
        )
        
        self._snapshots.append(snapshot)
        
        # Update peak and drawdown
        if equity > self._peak_equity:
            self._peak_equity = equity
        
        drawdown = (self._peak_equity - equity) / self._peak_equity
        self._max_drawdown = max(self._max_drawdown, drawdown)
        
        # Keep only last 24 hours of snapshots (at 1 min intervals = 1440)
        if len(self._snapshots) > 1440:
            self._snapshots = self._snapshots[-1440:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        win_rate = (
            self._winning_trades / self._total_trades * 100
            if self._total_trades > 0 else 0
        )
        
        avg_win = (
            sum(t.pnl for t in self._trades if t.pnl > 0) / self._winning_trades
            if self._winning_trades > 0 else 0
        )
        
        avg_loss = (
            sum(t.pnl for t in self._trades if t.pnl < 0) / self._losing_trades
            if self._losing_trades > 0 else 0
        )
        
        profit_factor = (
            abs(sum(t.pnl for t in self._trades if t.pnl > 0)) /
            abs(sum(t.pnl for t in self._trades if t.pnl < 0))
            if self._losing_trades > 0 and sum(t.pnl for t in self._trades if t.pnl < 0) != 0
            else float('inf') if self._winning_trades > 0 else 0
        )
        
        return {
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._losing_trades,
            "win_rate": win_rate,
            "total_pnl": self._total_pnl,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "largest_win": self._largest_win,
            "largest_loss": self._largest_loss,
            "profit_factor": profit_factor if profit_factor != float('inf') else 999.99,
            "max_drawdown": self._max_drawdown * 100,
            "peak_equity": self._peak_equity,
            "runtime_hours": (time.time() - self._start_time) / 3600,
        }
    
    def get_recent_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent trades."""
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "duration_seconds": t.duration_seconds,
                "exit_time": t.exit_time,
            }
            for t in reversed(self._trades[-limit:])
        ]
    
    def get_equity_curve(self, points: int = 100) -> List[Dict[str, Any]]:
        """Get equity curve data points."""
        if not self._snapshots:
            return []
        
        # Sample snapshots evenly
        step = max(1, len(self._snapshots) // points)
        sampled = self._snapshots[::step]
        
        return [
            {
                "timestamp": s.timestamp,
                "equity": s.equity,
                "balance": s.balance,
            }
            for s in sampled
        ]
    
    def get_agent_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get performance breakdown by agent."""
        result = {}
        
        for agent_id, trades in self._agent_trades.items():
            wins = sum(1 for t in trades if t.pnl > 0)
            total = len(trades)
            total_pnl = sum(t.pnl for t in trades)
            
            result[agent_id] = {
                "total_trades": total,
                "winning_trades": wins,
                "win_rate": wins / total * 100 if total > 0 else 0,
                "total_pnl": total_pnl,
                "avg_pnl": total_pnl / total if total > 0 else 0,
            }
        
        return result
    
    def get_daily_pnl(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get daily P&L for the last N days."""
        daily = defaultdict(float)
        
        cutoff = time.time() - (days * 86400)
        
        for trade in self._trades:
            if trade.exit_time >= cutoff:
                day = datetime.fromtimestamp(trade.exit_time).strftime('%Y-%m-%d')
                daily[day] += trade.pnl
        
        return [
            {"date": day, "pnl": pnl}
            for day, pnl in sorted(daily.items())
        ]


# Singleton instance
_performance_tracker: Optional[PerformanceTracker] = None


def get_performance_tracker() -> PerformanceTracker:
    """Get or create performance tracker singleton."""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker
