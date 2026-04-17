"""
Backtesting Engine for MERID.

Provides historical data replay and strategy performance testing.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from enum import Enum

from utils.logger import get_logger

logger = get_logger("backtesting.engine")


class BacktestStatus(Enum):
    """Backtest status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    backtest_id: str
    strategy_name: str
    symbols: List[str]
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    commission_pct: float = 0.001  # 0.1% (ignored when use_kalshi_fees=True)
    slippage_pct: float = 0.0005  # 0.05%
    timeframe: str = "1h"
    parameters: Dict[str, Any] = field(default_factory=dict)
    # When True, use the Kalshi tiered flat fee schedule instead of
    # commission_pct.  Must be set for any Kalshi prediction-market backtest
    # so that fee drag matches live execution.
    use_kalshi_fees: bool = False


@dataclass
class BacktestTrade:
    """A trade executed during backtest."""
    trade_id: str
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    commission: float


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    backtest_id: str
    strategy_name: str
    status: BacktestStatus
    
    # Time range
    start_date: datetime
    end_date: datetime
    duration_days: float
    
    # Capital
    initial_capital: float
    final_capital: float
    
    # Performance metrics
    total_return: float
    total_return_pct: float
    annualized_return: float
    
    # Risk metrics
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade_duration: float
    
    # Equity curve
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[BacktestTrade] = field(default_factory=list)
    
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "backtest_id": self.backtest_id,
            "strategy_name": self.strategy_name,
            "status": self.status.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "duration_days": self.duration_days,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return": self.total_return,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            "avg_trade_duration": self.avg_trade_duration,
            "equity_curve_points": len(self.equity_curve),
            "created_at": self.created_at,
        }


def _compute_trade_fee(
    config: "BacktestConfig",
    price_cents: float,
    contracts: int,
    capital: float,
) -> float:
    """Return the trade fee in dollars for one side (entry or exit).

    Routes to the Kalshi tiered flat-fee model when ``config.use_kalshi_fees``
    is True, otherwise falls back to the percentage commission model.
    This ensures backtests and live execution use the same fee schedule.
    """
    if config.use_kalshi_fees:
        try:
            from merid.prediction.risk import kalshi_fee_cents
            fee_c = kalshi_fee_cents(int(price_cents), contracts)
            return fee_c / 100.0  # Convert cents to dollars
        except Exception:
            pass
    return capital * config.commission_pct


class BacktestEngine:
    """
    Backtesting engine for strategy evaluation.
    
    Supports:
    - Historical data replay
    - Multiple strategies
    - Performance metrics calculation
    - Equity curve generation
    """
    
    def __init__(self):
        self._results: Dict[str, BacktestResult] = {}
        self._running_backtests: Dict[str, asyncio.Task] = {}
        self._strategies: Dict[str, Callable] = {}
        
        # Register built-in strategies
        self._register_builtin_strategies()
        
        logger.info("Backtest engine initialized")
    
    def _register_builtin_strategies(self) -> None:
        """Register built-in trading strategies."""
        self._strategies["momentum"] = self._strategy_momentum
        self._strategies["mean_reversion"] = self._strategy_mean_reversion
        self._strategies["breakout"] = self._strategy_breakout
        self._strategies["ma_crossover"] = self._strategy_ma_crossover
    
    def register_strategy(self, name: str, strategy_fn: Callable) -> None:
        """Register a custom strategy."""
        self._strategies[name] = strategy_fn
        logger.info(f"Registered strategy: {name}")
    
    def get_available_strategies(self) -> List[str]:
        """Get list of available strategies."""
        return list(self._strategies.keys())
    
    async def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        """Run a backtest with the given configuration."""
        logger.info(f"Starting backtest {config.backtest_id}: {config.strategy_name}")

        # Blind-spot fix: refuse to run backtests that hit the live price feed
        # while the system is in live trading mode to avoid unintended API load
        # and look-ahead contamination.
        import os as _os
        _live_active = (
            _os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
            or _os.getenv("MERID_TRADE_MODE", "").lower() == "live"
            or _os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live"
        )
        if _live_active:
            logger.warning(
                "Backtest %s blocked: live trading is active. "
                "Disable live mode before running backtests to prevent "
                "unintended exchange load and look-ahead contamination.",
                config.backtest_id,
            )
            raise RuntimeError(
                "Backtests cannot run while live trading is active. "
                "Set MERID_PM_TRADING_MODE=paper and MERID_PM_LIVE_ENABLED=false first."
            )

        try:
            # Fetch historical data
            ohlcv_data = await self._fetch_historical_data(
                config.symbols,
                config.start_date,
                config.end_date,
                config.timeframe
            )
            
            if not ohlcv_data:
                raise ValueError("No historical data available")
            
            # Run strategy
            strategy_fn = self._strategies.get(config.strategy_name)
            if not strategy_fn:
                raise ValueError(f"Unknown strategy: {config.strategy_name}")
            
            trades, equity_curve = await strategy_fn(config, ohlcv_data)
            
            # Calculate metrics
            result = self._calculate_metrics(config, trades, equity_curve)
            
            self._results[config.backtest_id] = result
            logger.info(f"Backtest {config.backtest_id} completed: {result.total_return_pct:.2f}% return")
            
            return result
            
        except Exception as e:
            logger.error(f"Backtest {config.backtest_id} failed: {e}")
            result = BacktestResult(
                backtest_id=config.backtest_id,
                strategy_name=config.strategy_name,
                status=BacktestStatus.FAILED,
                start_date=config.start_date,
                end_date=config.end_date,
                duration_days=0,
                initial_capital=config.initial_capital,
                final_capital=config.initial_capital,
                total_return=0,
                total_return_pct=0,
                annualized_return=0,
                max_drawdown=0,
                max_drawdown_pct=0,
                sharpe_ratio=0,
                sortino_ratio=0,
                calmar_ratio=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                profit_factor=0,
                avg_win=0,
                avg_loss=0,
                largest_win=0,
                largest_loss=0,
                avg_trade_duration=0,
            )
            self._results[config.backtest_id] = result
            return result
    
    # Candle-limit cap for historical OHLCV fetches.  Callers that request a
    # date range longer than this many candles will receive a WARNING so that
    # operators can see when backtest coverage is shorter than intended.
    _OHLCV_CANDLE_LIMIT = 500

    # Minutes per timeframe label — used to estimate the expected candle count
    # for a requested date range so we can warn when the cap is hit.
    _TF_MINUTES: Dict[str, int] = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
        "1d": 1440, "1w": 10080,
    }

    async def _fetch_historical_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str
    ) -> Dict[str, List[List]]:
        """Fetch historical OHLCV data."""
        from data.live_price_feed import get_live_price_feed

        # Warn if the requested date range would need more candles than the cap.
        tf_mins = self._TF_MINUTES.get(timeframe, 60)
        range_mins = (end_date - start_date).total_seconds() / 60.0
        expected_candles = int(range_mins / tf_mins)
        if expected_candles > self._OHLCV_CANDLE_LIMIT:
            logger.warning(
                "Backtest date range [%s, %s] at %s would need ~%d candles "
                "but fetch is capped at %d — results cover only the most "
                "recent %.0f days of the requested range.",
                start_date.date(), end_date.date(), timeframe,
                expected_candles, self._OHLCV_CANDLE_LIMIT,
                (self._OHLCV_CANDLE_LIMIT * tf_mins) / 1440,
            )

        data = {}
        feed = get_live_price_feed()
        
        for symbol in symbols:
            try:
                ohlcv = await feed.fetch_historical_ohlcv(symbol, timeframe, limit=self._OHLCV_CANDLE_LIMIT)
                if ohlcv:
                    data[symbol] = ohlcv
                    logger.debug(f"Fetched {len(ohlcv)} candles for {symbol}")
            except Exception as e:
                logger.warning(f"Failed to fetch data for {symbol}: {e}")
        
        return data
    
    async def _strategy_momentum(
        self,
        config: BacktestConfig,
        data: Dict[str, List[List]]
    ) -> tuple:
        """Simple momentum strategy."""
        trades = []
        equity_curve = []
        capital = config.initial_capital
        position = None
        
        lookback = config.parameters.get("lookback", 14)
        
        for symbol, ohlcv in data.items():
            for i in range(lookback, len(ohlcv)):
                timestamp = ohlcv[i][0]
                close = ohlcv[i][4]
                
                # Calculate momentum
                past_close = ohlcv[i - lookback][4]
                momentum = (close - past_close) / past_close
                
                # Record equity
                equity_curve.append({
                    "timestamp": timestamp,
                    "equity": capital + (position["quantity"] * (close - position["entry"]) if position else 0)
                })
                
                # Trading logic
                if position is None and momentum > 0.02:  # Enter long
                    quantity = (capital * 0.95) / close
                    position = {
                        "symbol": symbol,
                        "side": "long",
                        "entry": close,
                        "quantity": quantity,
                        "entry_time": datetime.fromtimestamp(timestamp / 1000)
                    }
                elif position and momentum < -0.01:  # Exit
                    slippage = close * config.slippage_pct * 2  # Entry + exit slippage
                    pnl = (close - position["entry"]) * position["quantity"]
                    pnl -= capital * config.commission_pct * 2  # Entry + exit commission
                    pnl -= slippage * position["quantity"]
                    
                    trade = BacktestTrade(
                        trade_id=f"bt_{len(trades)}",
                        symbol=symbol,
                        side=position["side"],
                        entry_price=position["entry"],
                        exit_price=close,
                        quantity=position["quantity"],
                        entry_time=position["entry_time"],
                        exit_time=datetime.fromtimestamp(timestamp / 1000),
                        pnl=pnl,
                        pnl_pct=(pnl / capital) * 100,
                        commission=capital * config.commission_pct * 2
                    )
                    trades.append(trade)
                    capital += pnl
                    position = None
        
        return trades, equity_curve
    
    async def _strategy_mean_reversion(
        self,
        config: BacktestConfig,
        data: Dict[str, List[List]]
    ) -> tuple:
        """Mean reversion strategy using Bollinger Bands."""
        trades = []
        equity_curve = []
        capital = config.initial_capital
        position = None
        
        period = config.parameters.get("period", 20)
        std_dev = config.parameters.get("std_dev", 2.0)
        
        for symbol, ohlcv in data.items():
            for i in range(period, len(ohlcv)):
                timestamp = ohlcv[i][0]
                close = ohlcv[i][4]
                
                # Calculate Bollinger Bands
                closes = [ohlcv[j][4] for j in range(i - period, i)]
                sma = sum(closes) / period
                variance = sum((c - sma) ** 2 for c in closes) / period
                std = variance ** 0.5
                upper = sma + std_dev * std
                lower = sma - std_dev * std
                
                equity_curve.append({
                    "timestamp": timestamp,
                    "equity": capital + (position["quantity"] * (close - position["entry"]) if position else 0)
                })
                
                # Trading logic
                if position is None and close < lower:  # Buy at lower band
                    quantity = (capital * 0.95) / close
                    position = {
                        "symbol": symbol,
                        "side": "long",
                        "entry": close,
                        "quantity": quantity,
                        "entry_time": datetime.fromtimestamp(timestamp / 1000)
                    }
                elif position and close > sma:  # Exit at mean
                    slippage = close * config.slippage_pct * 2
                    pnl = (close - position["entry"]) * position["quantity"]
                    pnl -= capital * config.commission_pct * 2
                    pnl -= slippage * position["quantity"]
                    
                    trade = BacktestTrade(
                        trade_id=f"bt_{len(trades)}",
                        symbol=symbol,
                        side=position["side"],
                        entry_price=position["entry"],
                        exit_price=close,
                        quantity=position["quantity"],
                        entry_time=position["entry_time"],
                        exit_time=datetime.fromtimestamp(timestamp / 1000),
                        pnl=pnl,
                        pnl_pct=(pnl / capital) * 100,
                        commission=capital * config.commission_pct * 2
                    )
                    trades.append(trade)
                    capital += pnl
                    position = None
        
        return trades, equity_curve
    
    async def _strategy_breakout(
        self,
        config: BacktestConfig,
        data: Dict[str, List[List]]
    ) -> tuple:
        """Breakout strategy using price channels."""
        trades = []
        equity_curve = []
        capital = config.initial_capital
        position = None
        
        period = config.parameters.get("period", 20)
        
        for symbol, ohlcv in data.items():
            for i in range(period, len(ohlcv)):
                timestamp = ohlcv[i][0]
                close = ohlcv[i][4]
                high = ohlcv[i][2]
                
                # Calculate channel
                highs = [ohlcv[j][2] for j in range(i - period, i)]
                lows = [ohlcv[j][3] for j in range(i - period, i)]
                channel_high = max(highs)
                channel_low = min(lows)
                
                equity_curve.append({
                    "timestamp": timestamp,
                    "equity": capital + (position["quantity"] * (close - position["entry"]) if position else 0)
                })
                
                # Trading logic
                if position is None and high > channel_high:  # Breakout long
                    quantity = (capital * 0.95) / close
                    position = {
                        "symbol": symbol,
                        "side": "long",
                        "entry": close,
                        "quantity": quantity,
                        "entry_time": datetime.fromtimestamp(timestamp / 1000)
                    }
                elif position and close < channel_low:  # Exit on breakdown
                    slippage = close * config.slippage_pct * 2
                    pnl = (close - position["entry"]) * position["quantity"]
                    pnl -= capital * config.commission_pct * 2
                    pnl -= slippage * position["quantity"]
                    
                    trade = BacktestTrade(
                        trade_id=f"bt_{len(trades)}",
                        symbol=symbol,
                        side=position["side"],
                        entry_price=position["entry"],
                        exit_price=close,
                        quantity=position["quantity"],
                        entry_time=position["entry_time"],
                        exit_time=datetime.fromtimestamp(timestamp / 1000),
                        pnl=pnl,
                        pnl_pct=(pnl / capital) * 100,
                        commission=capital * config.commission_pct * 2
                    )
                    trades.append(trade)
                    capital += pnl
                    position = None
        
        return trades, equity_curve
    
    async def _strategy_ma_crossover(
        self,
        config: BacktestConfig,
        data: Dict[str, List[List]]
    ) -> tuple:
        """Moving average crossover strategy."""
        trades = []
        equity_curve = []
        capital = config.initial_capital
        position = None
        
        fast_period = config.parameters.get("fast_period", 10)
        slow_period = config.parameters.get("slow_period", 30)
        
        for symbol, ohlcv in data.items():
            prev_fast = prev_slow = None
            
            for i in range(slow_period, len(ohlcv)):
                timestamp = ohlcv[i][0]
                close = ohlcv[i][4]
                
                # Calculate MAs
                fast_closes = [ohlcv[j][4] for j in range(i - fast_period, i)]
                slow_closes = [ohlcv[j][4] for j in range(i - slow_period, i)]
                fast_ma = sum(fast_closes) / fast_period
                slow_ma = sum(slow_closes) / slow_period
                
                equity_curve.append({
                    "timestamp": timestamp,
                    "equity": capital + (position["quantity"] * (close - position["entry"]) if position else 0)
                })
                
                # Trading logic - crossover
                if prev_fast is not None:
                    if position is None and prev_fast <= prev_slow and fast_ma > slow_ma:
                        # Golden cross - buy
                        quantity = (capital * 0.95) / close
                        position = {
                            "symbol": symbol,
                            "side": "long",
                            "entry": close,
                            "quantity": quantity,
                            "entry_time": datetime.fromtimestamp(timestamp / 1000)
                        }
                    elif position and prev_fast >= prev_slow and fast_ma < slow_ma:
                        # Death cross - sell
                        slippage = close * config.slippage_pct * 2
                        pnl = (close - position["entry"]) * position["quantity"]
                        pnl -= capital * config.commission_pct * 2
                        pnl -= slippage * position["quantity"]
                        
                        trade = BacktestTrade(
                            trade_id=f"bt_{len(trades)}",
                            symbol=symbol,
                            side=position["side"],
                            entry_price=position["entry"],
                            exit_price=close,
                            quantity=position["quantity"],
                            entry_time=position["entry_time"],
                            exit_time=datetime.fromtimestamp(timestamp / 1000),
                            pnl=pnl,
                            pnl_pct=(pnl / capital) * 100,
                            commission=capital * config.commission_pct * 2
                        )
                        trades.append(trade)
                        capital += pnl
                        position = None
                
                prev_fast = fast_ma
                prev_slow = slow_ma
        
        return trades, equity_curve
    
    def _calculate_metrics(
        self,
        config: BacktestConfig,
        trades: List[BacktestTrade],
        equity_curve: List[Dict]
    ) -> BacktestResult:
        """Calculate performance metrics from trades."""
        duration_days = (config.end_date - config.start_date).days or 1
        
        # Basic metrics
        total_pnl = sum(t.pnl for t in trades)
        final_capital = config.initial_capital + total_pnl
        total_return_pct = (total_pnl / config.initial_capital) * 100
        if duration_days > 0 and final_capital > 0 and config.initial_capital > 0:
            annualized_return = ((final_capital / config.initial_capital) ** (365 / duration_days) - 1) * 100
        else:
            annualized_return = ((final_capital / config.initial_capital) - 1) * 100 if config.initial_capital > 0 else 0
        
        # Trade statistics
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]
        
        win_rate = len(winning) / len(trades) * 100 if trades else 0
        avg_win = sum(t.pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.pnl for t in losing) / len(losing) if losing else 0
        
        gross_profit = sum(t.pnl for t in winning)
        gross_loss = abs(sum(t.pnl for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        largest_win = max((t.pnl for t in trades), default=0)
        largest_loss = min((t.pnl for t in trades), default=0)
        
        # Drawdown
        peak = config.initial_capital
        max_dd = 0
        for point in equity_curve:
            equity = point.get("equity", config.initial_capital)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        
        # Risk metrics (simplified)
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i-1].get("equity", config.initial_capital)
            curr = equity_curve[i].get("equity", config.initial_capital)
            if prev > 0:
                returns.append((curr - prev) / prev)
        
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1
        
        sharpe = (avg_return * 252 ** 0.5) / std_return if std_return > 0 else 0
        
        # Sortino (downside deviation)
        downside_returns = [r for r in returns if r < 0]
        downside_std = (sum(r ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5 if downside_returns else 1
        sortino = (avg_return * 252 ** 0.5) / downside_std if downside_std > 0 else 0
        
        # Calmar
        calmar = annualized_return / (max_dd * 100) if max_dd > 0 else 0
        
        # Average trade duration
        durations = [(t.exit_time - t.entry_time).total_seconds() / 3600 for t in trades]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        return BacktestResult(
            backtest_id=config.backtest_id,
            strategy_name=config.strategy_name,
            status=BacktestStatus.COMPLETED,
            start_date=config.start_date,
            end_date=config.end_date,
            duration_days=duration_days,
            initial_capital=config.initial_capital,
            final_capital=final_capital,
            total_return=total_pnl,
            total_return_pct=total_return_pct,
            annualized_return=annualized_return,
            max_drawdown=max_dd * config.initial_capital,
            max_drawdown_pct=max_dd * 100,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            profit_factor=profit_factor if profit_factor != float('inf') else 999.99,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_trade_duration=avg_duration,
            equity_curve=equity_curve,
            trades=trades,
        )
    
    def get_result(self, backtest_id: str) -> Optional[BacktestResult]:
        """Get backtest result by ID."""
        return self._results.get(backtest_id)
    
    def get_all_results(self) -> List[BacktestResult]:
        """Get all backtest results."""
        return list(self._results.values())
    
    def get_summary(self) -> Dict[str, Any]:
        """Get backtesting engine summary."""
        return {
            "total_backtests": len(self._results),
            "available_strategies": self.get_available_strategies(),
            "completed": sum(1 for r in self._results.values() if r.status == BacktestStatus.COMPLETED),
            "failed": sum(1 for r in self._results.values() if r.status == BacktestStatus.FAILED),
        }


# Singleton instance
_backtest_engine: Optional[BacktestEngine] = None


def get_backtest_engine() -> BacktestEngine:
    """Get or create backtest engine singleton."""
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine()
    return _backtest_engine
