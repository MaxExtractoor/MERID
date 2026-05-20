"""
15-Minute Band Strategy Agent
==============================

Kalshi trading agent using Bollinger Band "top edge" mean-reversion
for BTC, ETH, SOL, XRP, DOGE on 15m markets.

Integrates with the agent grid framework and uses the band strategy engine
to generate signals with regime filtering.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Deque
from datetime import datetime, timezone

from merid.strategies.band_strategy_15m import (
    BandStrategyEngine,
    BandStrategyConfig,
    BandSnapshot,
    TradeSetup,
    get_band_strategy_config,
)
from utils.logger import get_logger

logger = get_logger("merid.prediction.band_strategy_agent")


@dataclass
class TradeResult:
    """Result of a completed trade."""
    
    asset: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    r_multiple: float
    regime: str
    entry_time: datetime
    exit_time: datetime
    exit_reason: str  # "tp", "sl", "timeout"
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "side": self.side,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "r_multiple": round(self.r_multiple, 2),
            "regime": self.regime,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "exit_reason": self.exit_reason,
        }


@dataclass
class RollingWindowStats:
    """Rolling window statistics for trade performance monitoring."""
    
    window_size: int = 100  # Number of trades in rolling window
    
    # Trade results
    trades: Deque[TradeResult] = field(default_factory=lambda: deque(maxlen=100))
    
    # Computed metrics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_pnl_pct: float = 0.0
    avg_r_multiple: float = 0.0
    
    # Regime-segmented stats
    range_trades: int = 0
    range_wins: int = 0
    range_win_rate: float = 0.0
    trend_trades: int = 0
    trend_wins: int = 0
    trend_win_rate: float = 0.0
    
    # Exit breakdown
    tp_exits: int = 0
    sl_exits: int = 0
    timeout_exits: int = 0
    
    # Throttle status
    is_throttled: bool = False
    throttle_reason: str = ""
    
    def add_trade(self, result: TradeResult) -> None:
        """Add a trade result and update rolling statistics."""
        self.trades.append(result)
        self._recalculate()
    
    def _recalculate(self) -> None:
        """Recalculate all statistics based on current trades."""
        if not self.trades:
            return
        
        self.total_trades = len(self.trades)
        
        pnls = [t.pnl_pct for t in self.trades]
        self.wins = sum(1 for p in pnls if p > 0)
        self.losses = sum(1 for p in pnls if p <= 0)
        self.win_rate = self.wins / self.total_trades if self.total_trades > 0 else 0.0
        
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        self.avg_win_pct = sum(wins) / len(wins) if wins else 0.0
        self.avg_loss_pct = sum(losses) / len(losses) if losses else 0.0
        self.total_pnl_pct = sum(pnls)
        
        self.avg_r_multiple = sum(t.r_multiple for t in self.trades if t.r_multiple > 0) / len(self.trades) if self.trades else 0.0
        
        # Regime-segmented
        range_trades = [t for t in self.trades if t.regime == "range"]
        trend_trades = [t for t in self.trades if t.regime == "trend"]
        
        self.range_trades = len(range_trades)
        self.range_wins = sum(1 for t in range_trades if t.pnl_pct > 0)
        self.range_win_rate = self.range_wins / self.range_trades if self.range_trades > 0 else 0.0
        
        self.trend_trades = len(trend_trades)
        self.trend_wins = sum(1 for t in trend_trades if t.pnl_pct > 0)
        self.trend_win_rate = self.trend_wins / self.trend_trades if self.trend_trades > 0 else 0.0
        
        # Exit breakdown
        self.tp_exits = sum(1 for t in self.trades if t.exit_reason == "tp")
        self.sl_exits = sum(1 for t in self.trades if t.exit_reason == "sl")
        self.timeout_exits = sum(1 for t in self.trades if t.exit_reason == "timeout")
    
    def check_throttle(
        self,
        min_win_rate: float = 0.65,
        min_range_win_rate: float = 0.70,
        min_trades: int = 20,
    ) -> bool:
        """Check if throttling should be triggered based on performance.
        
        Args:
            min_win_rate: Minimum overall win rate threshold.
            min_range_win_rate: Minimum range-only win rate threshold.
            min_trades: Minimum trades required before checking.
        
        Returns:
            True if should throttle, False otherwise.
        """
        if self.total_trades < min_trades:
            self.is_throttled = False
            self.throttle_reason = ""
            return False
        
        reasons = []
        
        if self.win_rate < min_win_rate:
            reasons.append(f"Overall win rate {self.win_rate:.1%} below {min_win_rate:.1%}")
        
        if self.range_trades >= 10 and self.range_win_rate < min_range_win_rate:
            reasons.append(f"Range win rate {self.range_win_rate:.1%} below {min_range_win_rate:.1%}")
        
        if self.total_pnl_pct < 0:
            reasons.append(f"Total PnL {self.total_pnl_pct:.2%} negative")
        
        if reasons:
            self.is_throttled = True
            self.throttle_reason = "; ".join(reasons)
            logger.warning(f"Band strategy throttled: {self.throttle_reason}")
        else:
            self.is_throttled = False
            self.throttle_reason = ""
        
        return self.is_throttled
    
    def to_dict(self) -> dict:
        return {
            "window_size": self.window_size,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "avg_win_pct": round(self.avg_win_pct, 4),
            "avg_loss_pct": round(self.avg_loss_pct, 4),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "range_trades": self.range_trades,
            "range_wins": self.range_wins,
            "range_win_rate": round(self.range_win_rate, 4),
            "trend_trades": self.trend_trades,
            "trend_wins": self.trend_wins,
            "trend_win_rate": round(self.trend_win_rate, 4),
            "tp_exits": self.tp_exits,
            "sl_exits": self.sl_exits,
            "timeout_exits": self.timeout_exits,
            "is_throttled": self.is_throttled,
            "throttle_reason": self.throttle_reason,
        }


@dataclass
class BandAgentState:
    """State for a single asset's band strategy agent."""
    
    asset: str
    engine: BandStrategyEngine
    last_signal: Optional[TradeSetup] = None
    last_snapshot: Optional[BandSnapshot] = None
    signal_count: int = 0
    last_update: Optional[datetime] = None
    
    # Rolling window tracking
    rolling_stats: RollingWindowStats = field(default_factory=RollingWindowStats)
    
    # Open position tracking
    open_position: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "last_signal": self.last_signal.to_dict() if self.last_signal else None,
            "last_snapshot": self.last_snapshot.to_dict() if self.last_snapshot else None,
            "signal_count": self.signal_count,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "rolling_stats": self.rolling_stats.to_dict(),
            "has_open_position": self.open_position is not None,
        }


class BandStrategyAgent:
    """Agent for 15m band strategy on crypto majors.
    
    Maintains separate engine instances for each asset (BTC, ETH, SOL, XRP, DOGE)
    and generates signals based on Bollinger Band touches with regime filtering.
    """
    
    def __init__(
        self,
        assets: Optional[List[str]] = None,
        config_override: Optional[Dict[str, BandStrategyConfig]] = None,
    ):
        """Initialize band strategy agent.
        
        Args:
            assets: List of asset symbols (default: BTC, ETH, SOL, XRP, DOGE).
            config_override: Optional per-asset config overrides.
        """
        self.assets = assets or ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.config_override = config_override or {}
        
        # Initialize engines for each asset
        self.states: Dict[str, BandAgentState] = {}
        for asset in self.assets:
            config = self.config_override.get(asset, get_band_strategy_config(asset))
            engine = BandStrategyEngine(config)
            self.states[asset] = BandAgentState(asset=asset, engine=engine)
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(f"BandStrategyAgent initialized for {len(self.assets)} assets")
    
    async def start(self) -> None:
        """Start the agent (placeholder for async initialization)."""
        self._running = True
        logger.info("BandStrategyAgent started")
    
    async def stop(self) -> None:
        """Stop the agent."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("BandStrategyAgent stopped")
    
    def update_asset(self, asset: str, high: float, low: float, close: float) -> Optional[TradeSetup]:
        """Update a single asset with new OHLC data.
        
        Args:
            asset: Asset symbol.
            high: High price.
            low: Low price.
            close: Close price.
        
        Returns:
            TradeSetup if signal generated, None otherwise.
        """
        asset = asset.upper()
        if asset not in self.states:
            logger.warning(f"Asset {asset} not in agent states")
            return None
        
        state = self.states[asset]
        state.engine.update(high, low, close)
        state.last_update = datetime.now(timezone.utc)
        
        # Get snapshot
        snap = state.engine.snapshot()
        state.last_snapshot = snap
        
        # Check for signal
        setup = state.engine._generate_signal(snap)
        
        if setup.side != "neutral":
            state.last_signal = setup
            state.signal_count += 1
            logger.info(
                f"Band signal {asset}: {setup.side} @ {setup.entry_price:.2f}, "
                f"strength={setup.signal_strength:.2f}, reason={setup.reason}"
            )
        
        return setup if setup.side != "neutral" else None
    
    def get_signal(self, asset: str) -> Optional[TradeSetup]:
        """Get the latest signal for an asset.
        
        Args:
            asset: Asset symbol.
        
        Returns:
            Latest TradeSetup or None.
        """
        asset = asset.upper()
        state = self.states.get(asset)
        return state.last_signal if state else None
    
    def get_snapshot(self, asset: str) -> Optional[BandSnapshot]:
        """Get the latest band snapshot for an asset.
        
        Args:
            asset: Asset symbol.
        
        Returns:
            Latest BandSnapshot or None.
        """
        asset = asset.upper()
        state = self.states.get(asset)
        return state.last_snapshot if state else None
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get states for all assets.
        
        Returns:
            Dict mapping asset to state dict.
        """
        return {asset: state.to_dict() for asset, state in self.states.items()}
    
    def get_aggregate_summary(self) -> Dict[str, Any]:
        """Get aggregate summary across all assets.
        
        Returns:
            Summary dict with total signals, active regimes, etc.
        """
        total_signals = sum(state.signal_count for state in self.states.values())
        regime_counts = {"trend": 0, "range": 0}
        
        for state in self.states.values():
            if state.last_snapshot:
                regime_counts[state.last_snapshot.regime] += 1
        
        # Count current signals
        active_signals = []
        for asset, state in self.states.items():
            if state.last_signal and state.last_signal.side != "neutral":
                active_signals.append({
                    "asset": asset,
                    "side": state.last_signal.side,
                    "strength": state.last_signal.signal_strength,
                    "entry_price": state.last_signal.entry_price,
                })
        
        # Aggregate rolling stats across all assets
        total_trades = sum(state.rolling_stats.total_trades for state in self.states.values())
        total_wins = sum(state.rolling_stats.wins for state in self.states.values())
        aggregate_win_rate = total_wins / total_trades if total_trades > 0 else 0.0
        
        # Check throttling status
        throttled_assets = [
            asset for asset, state in self.states.items()
            if state.rolling_stats.is_throttled
        ]
        
        return {
            "assets_tracked": len(self.assets),
            "total_signals": total_signals,
            "regime_distribution": regime_counts,
            "active_signals": active_signals,
            "last_update": max(
                (s.last_update for s in self.states.values() if s.last_update),
                default=None,
            ),
            "rolling_stats": {
                "total_trades": total_trades,
                "total_wins": total_wins,
                "aggregate_win_rate": round(aggregate_win_rate, 4),
                "throttled_assets": throttled_assets,
                "throttled_count": len(throttled_assets),
            },
        }
    
    def record_trade_result(
        self,
        asset: str,
        side: str,
        entry_price: float,
        exit_price: float,
        regime: str,
        r_multiple: float,
        exit_reason: str = "timeout",
    ) -> None:
        """Record a completed trade result for rolling window tracking.
        
        Args:
            asset: Asset symbol.
            side: Trade side ("long" or "short").
            entry_price: Entry price.
            exit_price: Exit price.
            regime: Regime at entry ("trend" or "range").
            r_multiple: R:R ratio achieved.
            exit_reason: Exit reason ("tp", "sl", "timeout").
        """
        asset = asset.upper()
        if asset not in self.states:
            logger.warning(f"Asset {asset} not in agent states")
            return
        
        state = self.states[asset]
        
        # Calculate PnL
        if side == "long":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        result = TradeResult(
            asset=asset,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            r_multiple=r_multiple,
            regime=regime,
            entry_time=datetime.now(timezone.utc),
            exit_time=datetime.now(timezone.utc),
            exit_reason=exit_reason,
        )
        
        state.rolling_stats.add_trade(result)
        
        # Clear open position if exists
        state.open_position = None
        
        logger.info(
            f"Recorded trade result {asset}: {side} PnL={pnl_pct:.2%}, "
            f"R={r_multiple:.2f}, reason={exit_reason}"
        )
    
    def check_throttling(
        self,
        min_win_rate: float = 0.65,
        min_range_win_rate: float = 0.70,
        min_trades: int = 20,
    ) -> Dict[str, Any]:
        """Check throttling status across all assets.
        
        Args:
            min_win_rate: Minimum overall win rate threshold.
            min_range_win_rate: Minimum range-only win rate threshold.
            min_trades: Minimum trades required before checking.
        
        Returns:
            Dict with throttling status per asset and overall.
        """
        throttled_assets = {}
        any_throttled = False
        
        for asset, state in self.states.items():
            is_throttled = state.rolling_stats.check_throttle(
                min_win_rate, min_range_win_rate, min_trades
            )
            throttled_assets[asset] = {
                "is_throttled": is_throttled,
                "reason": state.rolling_stats.throttle_reason,
            }
            if is_throttled:
                any_throttled = True
        
        return {
            "any_throttled": any_throttled,
            "assets": throttled_assets,
            "thresholds": {
                "min_win_rate": min_win_rate,
                "min_range_win_rate": min_range_win_rate,
                "min_trades": min_trades,
            },
        }
    
    def get_rolling_stats(self, asset: str) -> Optional[Dict[str, Any]]:
        """Get rolling window statistics for a specific asset.
        
        Args:
            asset: Asset symbol.
        
        Returns:
            Rolling stats dict or None if asset not found.
        """
        asset = asset.upper()
        state = self.states.get(asset)
        return state.rolling_stats.to_dict() if state else None


# Singleton instance for global access
_band_agent_instance: Optional[BandStrategyAgent] = None


def get_band_agent(
    assets: Optional[List[str]] = None,
    config_override: Optional[Dict[str, BandStrategyConfig]] = None,
) -> BandStrategyAgent:
    """Get or create the global band strategy agent instance.
    
    Args:
        assets: List of asset symbols.
        config_override: Optional per-asset config overrides.
    
    Returns:
        BandStrategyAgent singleton instance.
    """
    global _band_agent_instance
    
    if _band_agent_instance is None:
        _band_agent_instance = BandStrategyAgent(assets, config_override)
    
    return _band_agent_instance
