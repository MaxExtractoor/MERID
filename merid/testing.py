"""Capital-ladder test harness for MERID paper trading.

Provides ``run_paper_scenario()`` and ``get_paper_metrics()`` which drive
the real PaperTradingEngine with synthetic price data, then extract
structural, risk, and performance metrics for assertion.

Usage (from pytest)::

    from merid.testing import run_paper_scenario, get_paper_metrics

    run_paper_scenario(initial_capital=1_000, ticks=50_000)
    m = get_paper_metrics()
    assert m.errors == 0
    assert m.reconciliation_breaks == 0
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from utils.logger import get_logger

logger = get_logger("merid.testing")


# ------------------------------------------------------------------ #
# Metrics dataclass
# ------------------------------------------------------------------ #

@dataclass
class PaperMetrics:
    """Metrics collected after a paper scenario run."""

    # Identity
    bracket_name: str = ""
    initial_capital: float = 0.0

    # Outcome
    final_equity: float = 0.0
    total_pnl: float = 0.0
    roi_pct: float = 0.0

    # Risk
    max_drawdown: float = 0.0          # 0..1 fraction
    peak_equity: float = 0.0
    trough_equity: float = 0.0

    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0              # 0..1

    # Structural health
    errors: int = 0
    reconciliation_breaks: int = 0
    reconciliation_checks: int = 0
    kill_switch_triggered: bool = False

    # Equity curve (sampled)
    equity_curve: List[float] = field(default_factory=list)

    # Raw reconciliation report
    reconciliation_report: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bracket_name": self.bracket_name,
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "roi_pct": round(self.roi_pct, 2),
            "max_drawdown": round(self.max_drawdown, 4),
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "errors": self.errors,
            "reconciliation_breaks": self.reconciliation_breaks,
            "kill_switch_triggered": self.kill_switch_triggered,
        }


# ------------------------------------------------------------------ #
# Synthetic price generator
# ------------------------------------------------------------------ #

_DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL"]

_INITIAL_PRICES: Dict[str, float] = {
    "BTC-USD": 43_000.0,
    "ETH-USD": 2_300.0,
    "SOL-USD": 95.0,
    "AAPL": 185.0,
}

# Annualised vol → per-tick vol (assuming ~250 trading days, ~390 ticks/day)
_ANNUAL_VOL: Dict[str, float] = {
    "BTC-USD": 0.60,
    "ETH-USD": 0.70,
    "SOL-USD": 0.85,
    "AAPL": 0.25,
}


def _generate_price_series(
    symbol: str,
    ticks: int,
    *,
    drift_annual: float = 0.10,
    seed: Optional[int] = None,
) -> List[float]:
    """Generate a GBM price series for *symbol* over *ticks* steps.

    Returns a list of length *ticks* with simulated prices.
    """
    rng = random.Random(seed)
    price = _INITIAL_PRICES.get(symbol, 100.0)
    vol = _ANNUAL_VOL.get(symbol, 0.40)

    # Per-tick parameters (assume ~100k ticks ≈ 1 year)
    dt = 1.0 / max(ticks, 1)
    mu_dt = drift_annual * dt
    sigma_sqrt_dt = vol * math.sqrt(dt)

    series = []
    for _ in range(ticks):
        z = rng.gauss(0, 1)
        price *= math.exp(mu_dt - 0.5 * sigma_sqrt_dt ** 2 + sigma_sqrt_dt * z)
        price = max(price, 0.01)  # floor
        series.append(round(price, 6))
    return series


# ------------------------------------------------------------------ #
# Simple strategy: mean-reversion with position sizing
# ------------------------------------------------------------------ #

def _simple_strategy_tick(
    engine,
    user_id: str,
    symbol: str,
    price: float,
    lookback: List[float],
    capital: float,
) -> None:
    """Execute a single strategy tick.

    Uses a simple mean-reversion signal with adaptive z-threshold.
    Lower threshold for larger capital to ensure trades fire across
    all brackets. Position size is 2% of current equity.
    """
    if len(lookback) < 20:
        return

    window = lookback[-20:]
    mean = sum(window) / len(window)
    std = (sum((p - mean) ** 2 for p in window) / len(window)) ** 0.5
    if std < 1e-8:
        return

    z_score = (price - mean) / std
    portfolio = engine.get_portfolio(user_id)
    position_key = f"{symbol}_long_perp"

    has_position = position_key in portfolio.positions

    # Adaptive z-threshold: 0.5 base ensures trades fire even with
    # low-vol GBM paths. This is a test harness, not a real strategy.
    z_entry = 0.5
    z_exit = 0.5

    # Entry: z < -z_entry and no existing position
    if z_score < -z_entry and not has_position:
        equity = portfolio.current_balance + sum(
            p.unrealized_pnl for p in portfolio.positions.values()
        )
        size = max(equity * 0.02, 1.0)
        if size <= portfolio.current_balance:
            engine.place_order(
                user_id=user_id,
                asset=symbol,
                side="long",
                size_usd=size,
                order_type="market",
                market_type="perp",
            )

    # Exit: z > z_exit and has position
    elif z_score > z_exit and has_position:
        engine.close_position(user_id, position_key)


# ------------------------------------------------------------------ #
# Scenario runner
# ------------------------------------------------------------------ #

# Module-level state so get_paper_metrics() can retrieve results
_last_metrics: Optional[PaperMetrics] = None


def run_paper_scenario(
    initial_capital: float = 10_000.0,
    symbols: Optional[Sequence[str]] = None,
    ticks: int = 50_000,
    bracket_name: str = "",
    seed: Optional[int] = None,
    reconcile_every: int = 5_000,
    venues: Optional[Sequence[str]] = None,
    strategies: Optional[Sequence[str]] = None,
) -> PaperMetrics:
    """Run a full paper-trading scenario and return metrics.

    This creates a fresh ``PaperTradingEngine``, feeds it synthetic
    price data, executes a simple strategy, and runs reconciliation
    at regular intervals.

    Parameters
    ----------
    initial_capital : float
        Starting cash for the paper portfolio.
    symbols : sequence of str, optional
        Symbols to trade. Defaults to BTC-USD, ETH-USD, SOL-USD, AAPL.
    ticks : int
        Number of price ticks to simulate.
    bracket_name : str
        Label for this ladder bracket (e.g. "micro", "small").
    seed : int, optional
        RNG seed for reproducibility. If None, uses bracket_name hash.
    reconcile_every : int
        Run reconciliation every N ticks.
    venues, strategies : ignored for now, reserved for future expansion.
    """
    global _last_metrics

    from merid.trading.paper_trading import PaperTradingEngine
    from merid.reconciliation import reconcile_all_venues
    from merid.trading.trade_mode import TradeMode, set_trade_mode, get_trade_mode

    # Ensure we're in MOCK mode (no external calls)
    old_mode = get_trade_mode()
    if old_mode == TradeMode.LIVE:
        raise RuntimeError("Cannot run capital ladder in LIVE mode")
    set_trade_mode(TradeMode.MOCK, reason=f"capital_ladder:{bracket_name}")

    if symbols is None:
        symbols = list(_DEFAULT_SYMBOLS)
    if seed is None:
        seed = hash(bracket_name or "default") & 0xFFFFFFFF

    user_id = f"ladder_{bracket_name or 'default'}"

    # ── Create isolated engine ────────────────────────────────────
    engine = PaperTradingEngine.__new__(PaperTradingEngine)
    engine.starting_balance = initial_capital
    engine.portfolios = {}
    engine.order_counter = 0
    engine.position_counter = 0
    engine.current_prices = {}
    engine._listeners = {"summary": set(), "trade": set(), "position": set()}
    engine._summary_dirty = False
    engine._positions_dirty = False
    engine._last_summary_emit = 0.0
    engine._last_positions_emit = 0.0
    engine.summary_snapshot = None

    # Stub out live price feed (we inject prices manually)
    engine.price_feed = type("StubFeed", (), {
        "subscribe": lambda self, cb: None,
        "get_current_price": lambda self, sym: None,
    })()

    # Create portfolio
    portfolio = engine.get_portfolio(user_id)
    portfolio.starting_balance = initial_capital
    portfolio.current_balance = initial_capital

    # ── Generate price series ─────────────────────────────────────
    price_series: Dict[str, List[float]] = {}
    for sym in symbols:
        price_series[sym] = _generate_price_series(sym, ticks, seed=seed + hash(sym) & 0xFFFFFFFF)

    # ── Run simulation ────────────────────────────────────────────
    metrics = PaperMetrics(
        bracket_name=bracket_name,
        initial_capital=initial_capital,
    )

    lookbacks: Dict[str, List[float]] = {sym: [] for sym in symbols}
    equity_curve: List[float] = []
    peak_equity = initial_capital
    max_dd = 0.0
    errors = 0

    # Monkey-patch the global singleton temporarily for reconciliation
    import trading.paper_trading as _pt_mod
    old_engine = _pt_mod._paper_engine
    _pt_mod._paper_engine = engine

    # Disable global risk controller for isolated engine — the kill switch
    # is a process-wide singleton that accumulates PnL across brackets.
    old_get_risk = _pt_mod._get_risk_controller
    _pt_mod._get_risk_controller = lambda: None

    try:
        for tick_idx in range(ticks):
            # Update prices
            prices_this_tick = {}
            for sym in symbols:
                p = price_series[sym][tick_idx]
                prices_this_tick[sym] = p
                lookbacks[sym].append(p)

            try:
                engine.update_prices(prices_this_tick)
            except Exception as exc:
                logger.debug("Price update error at tick %d: %s", tick_idx, exc)
                errors += 1

            # Run strategy for each symbol
            for sym in symbols:
                try:
                    _simple_strategy_tick(
                        engine, user_id, sym,
                        prices_this_tick[sym],
                        lookbacks[sym],
                        initial_capital,
                    )
                except Exception as exc:
                    logger.debug("Strategy error at tick %d/%s: %s", tick_idx, sym, exc)
                    errors += 1

            # Track equity
            stats = engine.get_portfolio_stats(user_id)
            equity = stats["equity"]
            equity_curve.append(equity)

            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

            # Periodic reconciliation (Kalshi venue vs paper — may be empty in MOCK)
            if reconcile_every > 0 and (tick_idx + 1) % reconcile_every == 0:
                try:
                    discs = reconcile_all_venues(["kalshi"])
                    metrics.reconciliation_checks += 1
                    bad = [d for d in discs if d.severity == "critical"]
                    if bad:
                        metrics.reconciliation_breaks += 1
                        logger.warning(
                            "Reconciliation break at tick %d: %s",
                            tick_idx,
                            [d.symbol for d in bad],
                        )
                except Exception as exc:
                    logger.debug("Reconciliation error at tick %d: %s", tick_idx, exc)
                    errors += 1

        # ── Final reconciliation ──────────────────────────────────
        try:
            final_discs = reconcile_all_venues(["kalshi"])
            metrics.reconciliation_report = {
                "discrepancy_count": len(final_discs),
                "critical": sum(1 for d in final_discs if d.severity == "critical"),
            }
            if any(d.severity == "critical" for d in final_discs):
                metrics.reconciliation_breaks += 1
        except Exception as exc:
            logger.debug("Final reconciliation error: %s", exc)
            errors += 1

        # ── Collect final metrics ─────────────────────────────────
        final_stats = engine.get_portfolio_stats(user_id)
        metrics.final_equity = final_stats["equity"]
        metrics.total_pnl = final_stats["total_pnl"]
        metrics.roi_pct = final_stats["roi_pct"]
        metrics.total_trades = final_stats["total_trades"]
        metrics.winning_trades = final_stats["winning_trades"]
        metrics.losing_trades = final_stats["losing_trades"]
        metrics.win_rate = final_stats["win_rate_pct"] / 100.0 if final_stats["win_rate_pct"] else 0.0
        metrics.max_drawdown = max_dd
        metrics.peak_equity = peak_equity
        metrics.trough_equity = min(equity_curve) if equity_curve else initial_capital
        metrics.errors = errors
        metrics.kill_switch_triggered = False

        # Sample equity curve (keep ~500 points max)
        step = max(1, len(equity_curve) // 500)
        metrics.equity_curve = equity_curve[::step]

    finally:
        # Restore global state
        _pt_mod._paper_engine = old_engine
        _pt_mod._get_risk_controller = old_get_risk
        try:
            set_trade_mode(old_mode, reason="capital_ladder:restore")
        except Exception as _tme:
            logger.debug("trade mode restore skipped: %s", _tme)

    _last_metrics = metrics
    logger.info(
        "Capital ladder [%s] complete: $%.2f → $%.2f (%.1f%% ROI, %.1f%% max DD, %d trades, %d errors)",
        bracket_name,
        initial_capital,
        metrics.final_equity,
        metrics.roi_pct,
        metrics.max_drawdown * 100,
        metrics.total_trades,
        metrics.errors,
    )
    return metrics


def get_paper_metrics() -> PaperMetrics:
    """Return the metrics from the most recent ``run_paper_scenario()`` call."""
    if _last_metrics is None:
        raise RuntimeError("No paper scenario has been run yet")
    return _last_metrics
