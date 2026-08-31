"""Kalshi Continuous Trader — async server module.

This is the canonical wiring module referenced by the web API and the
continuous-trader UI.  It intentionally does **not** contain a direct HTTP
bypass to Kalshi; the standalone ``scripts/kalshi_continuous_trader.py`` is
disabled in production and must not be used for live order flow.

Exports:
  - ``TraderConfig``: dataclass of CT tunables.
  - ``BankrollManager``: cycle-history + drawdown tracking helper.
  - ``KalshiContinuousTrader``: long-running trader container with ``status_snapshot``.
  - ``get_continuous_trader`` / ``reset_continuous_trader``: singleton accessors.
"""

from __future__ import annotations

import collections
import logging
import math
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TraderConfig:
    """All tunable knobs for the continuous trader."""

    # Cycle
    interval_seconds: int = 60
    max_cycles: int = 0
    dry_run: bool = False

    # Bankroll management
    initial_bankroll_cents: int = 100000
    max_risk_per_trade_pct: float = 0.02
    kelly_fraction: float = 0.25
    max_contract_price_cents: int = 35
    min_contract_price_cents: int = 2
    max_position_per_market: int = 3
    max_open_positions: int = 5
    max_total_exposure_pct: float = 0.20

    # Drawdown protection
    drawdown_halt_pct: float = 0.20
    drawdown_reduce_pct: float = 0.10
    min_balance_cents: int = 200

    # Edge requirements
    min_edge: Decimal = Decimal("0.08")
    fee_per_contract: Decimal = Decimal("0.02")
    slippage: Decimal = Decimal("0.01")

    # Market selection
    series_tickers: List[str] = field(default_factory=lambda: ["KXBTUPDOWN-15M", "KXBTC", "KXBTCD"])
    max_markets_to_scan: int = 10
    max_strike_distance_pct: float = 0.25

    # Fee-aware edge scaling
    fee_edge_multiplier_midcurve: float = 1.5
    fee_edge_multiplier_penny: float = 2.0

    # Anti-churn hysteresis
    churn_cooldown_cycles: int = 3
    churn_edge_improvement: float = 0.05

    # Fee drag monitoring
    max_fee_drag_pct: float = 0.30
    fee_drag_lookback: int = 30

    # Volatility-adaptive fee-drag window
    vol_lookback_bars: int = 20
    vol_low_threshold: float = 0.40
    vol_high_threshold: float = 0.80
    fee_window_low_vol: int = 50
    fee_window_mid_vol: int = 30
    fee_window_high_vol: int = 20

    # Order management
    stale_order_seconds: int = 120
    max_orders_per_cycle: int = 1


class BankrollManager:
    """Capital-preservation-first bankroll manager.

    Tracks peak, drawdown, fee drag, volatility band and a rolling
    ``_cycle_history`` deque used by the frontend sparklines.
    """

    def __init__(self, config: TraderConfig):
        self.config = config
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import (
                get_equity_for_risk_calc_sync,
            )

            live_equity = get_equity_for_risk_calc_sync()
            if live_equity is not None and live_equity > 0:
                self._peak_balance_cents = int(live_equity * 100)
            else:
                self._peak_balance_cents = config.initial_bankroll_cents
        except Exception:
            self._peak_balance_cents = config.initial_bankroll_cents

        self._halted = False
        self._halt_reason = ""
        self._total_trades = 0
        self._total_wins = 0
        self._total_losses = 0
        self._total_pnl_cents = 0
        self._total_fees_cents = 0
        self._current_cycle = 0
        self._fee_drag_tightening = False
        self._current_vol_band = "mid"
        self._annualized_vol = 0.0
        self._fee_history: collections.deque = collections.deque(
            maxlen=config.fee_drag_lookback,
        )
        self._spot_history: collections.deque = collections.deque(
            maxlen=config.vol_lookback_bars + 1,
        )
        self._last_trade: Dict[str, Tuple[str, float, int]] = {}
        self._cycle_history: collections.deque = collections.deque(maxlen=60)

    def advance_cycle(self) -> None:
        self._current_cycle += 1

    def record_cycle_snapshot(self, balance_cents: int) -> None:
        """Append a per-cycle data point for sparkline rendering."""
        self._cycle_history.append({
            "cycle": self._current_cycle,
            "drawdown_pct": round(self.get_drawdown_pct(balance_cents) * 100, 2),
            "fee_drag_pct": round(self.get_fee_drag_pct() * 100, 1),
            "pnl_cents": self._total_pnl_cents,
            "balance_cents": balance_cents,
            "vol_pct": round(self._annualized_vol * 100, 1),
        })

    def update_peak(self, balance_cents: int) -> None:
        if balance_cents > self._peak_balance_cents:
            self._peak_balance_cents = balance_cents

    def get_drawdown_pct(self, balance_cents: int) -> float:
        if self._peak_balance_cents <= 0:
            return 0.0
        return 1.0 - (balance_cents / self._peak_balance_cents)

    def record_fee(self, fee_cents: int, gross_edge_cents: int) -> None:
        self._fee_history.append((fee_cents, max(1, gross_edge_cents)))
        self._total_fees_cents += fee_cents
        self._update_fee_drag_state()

    def _update_fee_drag_state(self) -> None:
        if len(self._fee_history) < 5:
            return
        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)
        if total_edge <= 0:
            return
        fee_drag = total_fees / total_edge
        self._fee_drag_tightening = fee_drag > self.config.max_fee_drag_pct

    def get_fee_drag_pct(self) -> float:
        if len(self._fee_history) < 2:
            return 0.0
        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)
        if total_edge <= 0:
            return 0.0
        return total_fees / total_edge

    def record_spot(self, spot: float) -> None:
        if spot <= 0:
            return
        self._spot_history.append(spot)
        if len(self._spot_history) >= 3:
            self._compute_vol()
            self._update_vol_band()

    def _compute_vol(self) -> None:
        spots = list(self._spot_history)
        if len(spots) < 3:
            return
        log_returns = [
            math.log(spots[i] / spots[i - 1])
            for i in range(1, len(spots))
            if spots[i - 1] > 0
        ]
        if len(log_returns) < 2:
            return
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        bar_vol = math.sqrt(var)
        bars_per_year = 365.25 * 24 * 3600 / max(1, self.config.interval_seconds)
        self._annualized_vol = bar_vol * math.sqrt(bars_per_year)

    def _update_vol_band(self) -> None:
        cfg = self.config
        vol = self._annualized_vol
        if vol < cfg.vol_low_threshold:
            new_band = "low"
            new_window = cfg.fee_window_low_vol
        elif vol > cfg.vol_high_threshold:
            new_band = "high"
            new_window = cfg.fee_window_high_vol
        else:
            new_band = "mid"
            new_window = cfg.fee_window_mid_vol

        if new_band != self._current_vol_band:
            self._current_vol_band = new_band
            old_data = list(self._fee_history)
            self._fee_history = collections.deque(old_data[-new_window:], maxlen=new_window)

    @property
    def vol_band(self) -> str:
        return self._current_vol_band

    @property
    def annualized_vol(self) -> float:
        return self._annualized_vol

    @property
    def is_halted(self) -> bool:
        return self._halted

    def effective_max_orders_per_cycle(self) -> int:
        base = self.config.max_orders_per_cycle
        if self._fee_drag_tightening:
            return max(1, base // 2)
        return base

    def effective_max_exposure_pct(self) -> float:
        base = self.config.max_total_exposure_pct
        if self._fee_drag_tightening:
            return base * 0.75
        return base

    def record_trade_result(self, pnl_cents: int) -> None:
        self._total_trades += 1
        self._total_pnl_cents += pnl_cents
        if pnl_cents >= 0:
            self._total_wins += 1
        else:
            self._total_losses += 1

    def check_drawdown(self, balance_cents: int) -> bool:
        if self._peak_balance_cents <= 0:
            return False
        drawdown = 1.0 - (balance_cents / self._peak_balance_cents)
        if drawdown >= self.config.drawdown_halt_pct:
            self._halted = True
            self._halt_reason = (
                f"Drawdown {drawdown:.1%} >= halt threshold "
                f"{self.config.drawdown_halt_pct:.0%}"
            )
            return False
        return True

    def win_rate_pct(self) -> float:
        if self._total_trades == 0:
            return 0.0
        return (self._total_wins / self._total_trades) * 100.0


class KalshiContinuousTrader:
    """Long-running continuous trader container.

    The actual 15m production loop lives in ``merid.loop_15m``.  This class
    exists to satisfy the legacy continuous-trader UI wiring and provide a
    stable ``status_snapshot`` surface.
    """

    def __init__(self, config: Optional[TraderConfig] = None):
        self.config = config or TraderConfig()
        self.bankroll = BankrollManager(self.config)
        self._running = False
        self._shutdown = False
        self._orders_placed = 0
        self._orders_filled = 0
        self._orders_cancelled = 0
        self._resting_orders: List[Dict] = []
        self._active_assets: List[str] = []
        self._asset_series_map: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._running

    def _balance_cents(self) -> int:
        """Best-effort current balance in cents."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import (
                get_equity_for_risk_calc_sync,
            )

            equity = get_equity_for_risk_calc_sync()
            if equity is not None and equity > 0:
                return int(equity * 100)
        except Exception:
            pass
        return self.config.initial_bankroll_cents

    def status_snapshot(self) -> Dict:
        """Return a full snapshot for the UI and API."""
        with self._lock:
            balance_cents = self._balance_cents()
            bm = self.bankroll
            bm.update_peak(balance_cents)
            bm.record_cycle_snapshot(balance_cents)

            cfg = self.config
            win_rate = bm.win_rate_pct()
            drawdown = bm.get_drawdown_pct(balance_cents)
            fee_drag = bm.get_fee_drag_pct()

            return {
                "running": self._running,
                "cycle": bm._current_cycle,
                "dry_run": cfg.dry_run,
                "interval_seconds": cfg.interval_seconds,
                "balance_cents": balance_cents,
                "portfolio_cents": 0,
                "total_value_cents": balance_cents,
                "peak_balance_cents": bm._peak_balance_cents,
                "drawdown_pct": round(drawdown * 100, 2),
                "halted": bm.is_halted,
                "halt_reason": bm._halt_reason or "",
                "total_trades": bm._total_trades,
                "total_wins": bm._total_wins,
                "total_losses": bm._total_losses,
                "win_rate_pct": round(win_rate, 1),
                "total_pnl_cents": bm._total_pnl_cents,
                "total_fees_cents": bm._total_fees_cents,
                "fee_drag_pct": round(fee_drag * 100, 1),
                "fee_drag_tightening": bm._fee_drag_tightening,
                "fee_drag_window": len(bm._fee_history),
                "vol_band": bm.vol_band,
                "annualized_vol_pct": round(bm.annualized_vol * 100, 1),
                "eff_max_orders_per_cycle": bm.effective_max_orders_per_cycle(),
                "eff_max_exposure_pct": bm.effective_max_exposure_pct(),
                "config": {
                    "interval_seconds": cfg.interval_seconds,
                    "dry_run": cfg.dry_run,
                    "initial_bankroll_cents": cfg.initial_bankroll_cents,
                    "max_risk_per_trade_pct": cfg.max_risk_per_trade_pct,
                    "drawdown_halt_pct": cfg.drawdown_halt_pct,
                    "drawdown_reduce_pct": cfg.drawdown_reduce_pct,
                    "max_fee_drag_pct": cfg.max_fee_drag_pct,
                    "fee_window_low_vol": cfg.fee_window_low_vol,
                    "fee_window_mid_vol": cfg.fee_window_mid_vol,
                    "fee_window_high_vol": cfg.fee_window_high_vol,
                },
                "orders_placed": self._orders_placed,
                "orders_filled": self._orders_filled,
                "orders_cancelled": self._orders_cancelled,
                "resting_orders": list(self._resting_orders),
                "cycle_history": list(bm._cycle_history),
                "active_assets": list(self._active_assets),
                "asset_series_map": dict(self._asset_series_map),
            }

    async def run(self) -> None:
        """No-op run loop; production trading is handled by the 15m loop."""
        self._running = True
        self._shutdown = False
        try:
            while self._running and not self._shutdown:
                # The canonical 15m loop is the only live trading path.
                # This stub simply idles and serves status snapshots.
                try:
                    import asyncio
                    await asyncio.sleep(max(1, self.config.interval_seconds))
                except Exception:
                    break
        finally:
            self._running = False

    def stop(self) -> None:
        """Request graceful stop."""
        self._running = False
        self._shutdown = True


# Singleton
_ct: Optional[KalshiContinuousTrader] = None
_ct_lock = threading.Lock()


def get_continuous_trader() -> Optional[KalshiContinuousTrader]:
    """Return the module-level continuous trader singleton."""
    global _ct
    if _ct is None:
        with _ct_lock:
            if _ct is None:
                _ct = KalshiContinuousTrader()
    return _ct


def reset_continuous_trader() -> None:
    """Reset the module-level singleton."""
    global _ct
    with _ct_lock:
        if _ct is not None:
            _ct.stop()
        _ct = None
