"""Edge Calibration Tracker — Track realized vs forecast edge per cell.

Provides feedback loop for strategy calibration by comparing:
- Forecast edge (from OpinionStrategy at trade time)
- Realized edge (computed from settled trade outcomes)

This enables:
1. Detection of systematic miscalibration (over/under-confidence)
2. Per-cell performance metrics (Sharpe, Calmar, hit rate)
3. Promotion eligibility assessment
4. Alert generation when calibration degrades

Usage::

    tracker = EdgeCalibrationTracker()

    # At trade intent creation:
    tracker.record_forecast(
        ticker="KXBTC-15M-T95000",
        forecast_edge=0.03,
        confidence=0.65,
        strategy_name="spot_momentum",
        asset="BTC",
        timeframe="15m"
    )

    # At settlement:
    tracker.record_outcome(
        ticker="KXBTC-15M-T95000",
        realized_pnl_cents=120,
        fill_price_cents=50,
        settled_outcome="yes"  # "yes" or "no"
    )

    # Query calibration:
    stats = tracker.get_calibration_stats("BTC", "15m")
    # Returns: {forecast_edge_mean, realized_edge_mean, calibration_ratio, ...}
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.edge_calibration_tracker")


@dataclass
class ForecastRecord:
    """Record of a forecast at trade time."""
    ticker: str
    timestamp: float
    forecast_edge: float  # decimal fraction (e.g., 0.03 = 3%)
    confidence: float
    strategy_name: str
    asset: str
    timeframe: str
    fill_price_cents: Optional[int] = None


@dataclass
class OutcomeRecord:
    """Record of a settled trade outcome."""
    ticker: str
    timestamp: float
    realized_pnl_cents: int
    fill_price_cents: int
    settled_outcome: str  # "yes" or "no"
    realized_edge: Optional[float] = None  # computed from PnL


@dataclass
class CellPerformance:
    """Performance metrics for a (asset, timeframe) cell."""
    asset: str
    timeframe: str
    trade_count: int = 0
    forecast_edge_sum: float = 0.0
    realized_edge_sum: float = 0.0
    pnl_sum_cents: int = 0
    pnl_squared_sum: float = 0.0
    wins: int = 0
    losses: int = 0
    max_drawdown_cents: int = 0
    peak_pnl_cents: int = 0

    @property
    def forecast_edge_mean(self) -> float:
        """Average forecast edge."""
        return self.forecast_edge_sum / self.trade_count if self.trade_count > 0 else 0.0

    @property
    def realized_edge_mean(self) -> float:
        """Average realized edge."""
        return self.realized_edge_sum / self.trade_count if self.trade_count > 0 else 0.0

    @property
    def calibration_ratio(self) -> float:
        """Realized / forecast edge ratio. 1.0 = perfect calibration."""
        if self.forecast_edge_mean == 0:
            return 0.0
        return self.realized_edge_mean / self.forecast_edge_mean

    @property
    def hit_rate(self) -> float:
        """Fraction of winning trades."""
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio (assuming trades are independent)."""
        if self.trade_count < 2:
            return 0.0
        mean_pnl = self.pnl_sum_cents / self.trade_count
        variance = (self.pnl_squared_sum / self.trade_count) - (mean_pnl ** 2)
        if variance <= 0:
            return 0.0
        std_dev = variance ** 0.5
        if std_dev == 0:
            return 0.0
        # Annualize: assume ~250 trading days, adjust by sqrt(trades/year)
        return (mean_pnl / std_dev) * (250 ** 0.5)

    @property
    def calmar_ratio(self) -> float:
        """Annualized return / max drawdown."""
        if self.max_drawdown_cents == 0:
            return 0.0
        annualized_return_cents = self.pnl_sum_cents * (250 / max(1, self.trade_count))
        return annualized_return_cents / self.max_drawdown_cents

    def to_dict(self) -> Dict:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "trade_count": self.trade_count,
            "forecast_edge_mean": round(self.forecast_edge_mean, 4),
            "realized_edge_mean": round(self.realized_edge_mean, 4),
            "calibration_ratio": round(self.calibration_ratio, 3),
            "hit_rate": round(self.hit_rate, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "total_pnl_cents": self.pnl_sum_cents,
            "max_drawdown_cents": self.max_drawdown_cents,
        }


class EdgeCalibrationTracker:
    """Tracks forecast vs realized edge for all (asset, timeframe) cells.

    Thread-safe for single-process use (no async locks needed).
    """

    def __init__(self):
        # Forecasts by ticker: {ticker: ForecastRecord}
        self._forecasts: Dict[str, ForecastRecord] = {}

        # Outcomes by ticker: {ticker: OutcomeRecord}
        self._outcomes: Dict[str, OutcomeRecord] = {}

        # Per-cell performance: {(asset, timeframe): CellPerformance}
        self._cell_performance: Dict[Tuple[str, str], CellPerformance] = {}

        # Per-cell PnL history for drawdown tracking: {(asset, tf): List[pnl_cents]}
        self._cell_pnl_history: Dict[Tuple[str, str], List[int]] = defaultdict(list)

    def record_forecast(
        self,
        ticker: str,
        forecast_edge: float,
        confidence: float,
        strategy_name: str,
        asset: str,
        timeframe: str,
        fill_price_cents: Optional[int] = None,
    ) -> None:
        """Record a forecast at trade intent creation.

        Args:
            ticker: Market ticker (e.g., "KXBTC-15M-T95000")
            forecast_edge: Forecast edge as decimal (e.g., 0.03 = 3%)
            confidence: Confidence in forecast (0-1)
            strategy_name: Name of strategy that generated forecast
            asset: Asset symbol (e.g., "BTC")
            timeframe: Timeframe (e.g., "15m")
            fill_price_cents: Actual fill price if known at forecast time
        """
        self._forecasts[ticker] = ForecastRecord(
            ticker=ticker,
            timestamp=time.time(),
            forecast_edge=forecast_edge,
            confidence=confidence,
            strategy_name=strategy_name,
            asset=asset,
            timeframe=timeframe,
            fill_price_cents=fill_price_cents,
        )
        logger.debug(
            "[CALIBRATION] Forecast recorded: ticker=%s asset=%s tf=%s edge=%.4f conf=%.3f strategy=%s",
            ticker, asset, timeframe, forecast_edge, confidence, strategy_name,
        )

    def record_outcome(
        self,
        ticker: str,
        realized_pnl_cents: int,
        fill_price_cents: int,
        settled_outcome: str,
    ) -> None:
        """Record the settled outcome of a trade.

        Args:
            ticker: Market ticker
            realized_pnl_cents: Realized PnL in cents (can be negative)
            fill_price_cents: Actual fill price in cents
            settled_outcome: "yes" or "no" (the winning outcome)
        """
        forecast = self._forecasts.get(ticker)
        if forecast is None:
            logger.warning(
                "[CALIBRATION] Outcome recorded for ticker=%s but no forecast found — skipping",
                ticker,
            )
            return

        # Compute realized edge (PnL / notional risk)
        # For a YES buy at 50¢, risk is 50¢, max profit is 50¢
        # If it wins, PnL = +50¢, realized_edge = +50¢ / 50¢ = 1.0 (100%)
        # If it loses, PnL = -50¢, realized_edge = -50¢ / 50¢ = -1.0 (-100%)
        risk_cents = fill_price_cents if fill_price_cents > 0 else 50
        realized_edge = realized_pnl_cents / risk_cents

        self._outcomes[ticker] = OutcomeRecord(
            ticker=ticker,
            timestamp=time.time(),
            realized_pnl_cents=realized_pnl_cents,
            fill_price_cents=fill_price_cents,
            settled_outcome=settled_outcome,
            realized_edge=realized_edge,
        )

        # Update cell performance
        key = (forecast.asset, forecast.timeframe)
        if key not in self._cell_performance:
            self._cell_performance[key] = CellPerformance(
                asset=forecast.asset,
                timeframe=forecast.timeframe,
            )

        perf = self._cell_performance[key]
        perf.trade_count += 1
        perf.forecast_edge_sum += forecast.forecast_edge
        perf.realized_edge_sum += realized_edge
        perf.pnl_sum_cents += realized_pnl_cents
        perf.pnl_squared_sum += (realized_pnl_cents ** 2)

        if realized_pnl_cents > 0:
            perf.wins += 1
        else:
            perf.losses += 1

        # Update drawdown tracking
        self._cell_pnl_history[key].append(realized_pnl_cents)
        cumulative_pnl = sum(self._cell_pnl_history[key])
        if cumulative_pnl > perf.peak_pnl_cents:
            perf.peak_pnl_cents = cumulative_pnl
        drawdown = perf.peak_pnl_cents - cumulative_pnl
        if drawdown > perf.max_drawdown_cents:
            perf.max_drawdown_cents = drawdown

        logger.info(
            "[CALIBRATION] Outcome recorded: ticker=%s asset=%s tf=%s pnl=%d¢ "
            "realized_edge=%.3f forecast_edge=%.3f calibration_ratio=%.3f",
            ticker, forecast.asset, forecast.timeframe, realized_pnl_cents,
            realized_edge, forecast.forecast_edge, perf.calibration_ratio,
        )

    def get_calibration_stats(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Dict]:
        """Get calibration statistics for a (asset, timeframe) cell.

        Returns None if no trades recorded for this cell yet.
        """
        key = (asset, timeframe)
        perf = self._cell_performance.get(key)
        if perf is None or perf.trade_count == 0:
            return None
        return perf.to_dict()

    def get_all_cell_stats(self) -> Dict[Tuple[str, str], Dict]:
        """Get calibration stats for all cells that have trades."""
        return {
            key: perf.to_dict()
            for key, perf in self._cell_performance.items()
            if perf.trade_count > 0
        }

    def check_calibration_alert(
        self,
        asset: str,
        timeframe: str,
        min_trades: int = 50,
        min_calibration_ratio: float = 0.5,
    ) -> Tuple[bool, str]:
        """Check if calibration for a cell has degraded below threshold.

        Returns (should_alert, reason).
        """
        stats = self.get_calibration_stats(asset, timeframe)
        if stats is None or stats["trade_count"] < min_trades:
            return False, "insufficient_data"

        if stats["calibration_ratio"] < min_calibration_ratio:
            return True, (
                f"Calibration ratio {stats['calibration_ratio']:.2f} < {min_calibration_ratio} "
                f"(forecast={stats['forecast_edge_mean']:.3f}, realized={stats['realized_edge_mean']:.3f})"
            )

        return False, "ok"

    def clear_cell(self, asset: str, timeframe: str) -> None:
        """Clear all data for a specific cell (for testing or reset)."""
        key = (asset, timeframe)
        if key in self._cell_performance:
            del self._cell_performance[key]
        if key in self._cell_pnl_history:
            del self._cell_pnl_history[key]
        # Also clear forecasts/outcomes for this cell
        to_remove = [
            ticker for ticker, forecast in self._forecasts.items()
            if forecast.asset == asset and forecast.timeframe == timeframe
        ]
        for ticker in to_remove:
            if ticker in self._forecasts:
                del self._forecasts[ticker]
            if ticker in self._outcomes:
                del self._outcomes[ticker]


# Global singleton instance
_TRACKER: Optional[EdgeCalibrationTracker] = None


def get_edge_calibration_tracker() -> EdgeCalibrationTracker:
    """Get the global EdgeCalibrationTracker singleton."""
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = EdgeCalibrationTracker()
    return _TRACKER
