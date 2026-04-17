"""
BTC Lane Promotion Config — data-driven phase ladder.

All risk clamps, timeframe unlocks, and asset unlocks live here.
Nothing is hardcoded in lane or risk-dial logic; change this file to
evolve system behaviour across phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class PromotionPhase:
    """Defines one promotion tier and its unlock criteria + risk caps."""

    name: str

    # ── Unlock criteria (all must be satisfied to enter this phase) ──────
    min_equity: float           # absolute equity floor ($)
    min_days_live: int          # calendar days since first live trade
    max_drawdown: float         # max tolerated realised drawdown (0..1)
    min_trades: int             # minimum completed trades
    sharpe_threshold: float     # minimum rolling Sharpe (use -999 to skip)

    # ── Risk caps (ceilings; sentiment dial may tighten further) ─────────
    per_trade_cap: float        # max $ per trade (hard ceiling)
    per_trade_pct: float        # max fraction of equity per trade (e.g. 0.03)
    max_exposure: float         # max total open exposure as fraction of equity
    max_open_trades: int        # max simultaneous open positions

    # ── Unlocked capabilities ─────────────────────────────────────────────
    unlocked_timeframes: List[str] = field(default_factory=list)
    unlocked_assets: List[str] = field(default_factory=list)

    # ── Compounding behaviour ─────────────────────────────────────────────
    allow_live: bool = False    # whether this phase permits live execution
    compound_equity: bool = True  # whether to update equity from realised PnL


# ---------------------------------------------------------------------------
# Phase ladder — ordered from most restrictive to most permissive.
# PromotionEngine walks this list and selects the highest phase whose
# criteria are ALL satisfied.
# ---------------------------------------------------------------------------

PHASES: List[PromotionPhase] = [
    PromotionPhase(
        name="PHASE_0",
        # Criteria
        min_equity=10.0,
        min_days_live=0,
        max_drawdown=0.30,
        min_trades=0,
        sharpe_threshold=-999.0,
        # Caps
        per_trade_cap=0.25,
        per_trade_pct=0.025,        # 2.5% equity
        max_exposure=0.50,
        max_open_trades=1,
        # Unlocks
        unlocked_timeframes=["15m"],
        unlocked_assets=["BTC"],
        allow_live=False,           # paper-only until promoted
        compound_equity=True,
    ),
    PromotionPhase(
        name="PHASE_1",
        # Criteria
        min_equity=20.0,
        min_days_live=7,
        max_drawdown=0.25,
        min_trades=50,
        sharpe_threshold=0.5,
        # Caps
        per_trade_cap=0.40,
        per_trade_pct=0.030,        # 3% equity
        max_exposure=0.75,
        max_open_trades=2,
        # Unlocks
        unlocked_timeframes=["15m", "1h"],
        unlocked_assets=["BTC"],
        allow_live=True,
        compound_equity=True,
    ),
    PromotionPhase(
        name="PHASE_2",
        # Criteria
        min_equity=35.0,
        min_days_live=14,
        max_drawdown=0.25,
        min_trades=120,
        sharpe_threshold=0.7,
        # Caps
        per_trade_cap=0.60,
        per_trade_pct=0.030,        # still 3% — absolute size grows with equity
        max_exposure=1.00,
        max_open_trades=3,
        # Unlocks
        unlocked_timeframes=["15m", "1h", "4h"],
        unlocked_assets=["BTC", "ETH"],
        allow_live=True,
        compound_equity=True,
    ),
    PromotionPhase(
        name="PHASE_3",
        # Criteria
        min_equity=75.0,
        min_days_live=30,
        max_drawdown=0.20,
        min_trades=300,
        sharpe_threshold=1.0,
        # Caps
        per_trade_cap=1.50,
        per_trade_pct=0.030,
        max_exposure=1.50,
        max_open_trades=5,
        # Unlocks
        unlocked_timeframes=["15m", "1h", "4h", "1d"],
        unlocked_assets=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        allow_live=True,
        compound_equity=True,
    ),
]

# Convenience lookup
PHASE_BY_NAME: dict[str, PromotionPhase] = {p.name: p for p in PHASES}


# ---------------------------------------------------------------------------
# Backtest eligibility gate
# ---------------------------------------------------------------------------

@dataclass
class StrategyStats:
    """Backtest metrics for a (symbol, timeframe) strategy."""
    symbol: str
    timeframe: str
    sharpe: float
    max_drawdown: float     # 0..1
    trades: int
    years_tested: float


@dataclass
class LiveEligibility:
    allow_live: bool
    reason: str


def check_backtest_eligibility(s: StrategyStats) -> LiveEligibility:
    """
    Gate a strategy for live execution based on backtest quality.

    All thresholds are intentionally conservative; relax them in this
    file only when you have evidence from additional out-of-sample data.
    """
    if s.years_tested < 1.0:
        return LiveEligibility(False, "too_little_history")
    if s.trades < 50:
        return LiveEligibility(False, "too_few_trades")
    if s.max_drawdown > 0.30:
        return LiveEligibility(False, "drawdown_too_high")
    if s.sharpe < 0.7:
        return LiveEligibility(False, "sharpe_too_low")
    return LiveEligibility(True, "ok")


# ---------------------------------------------------------------------------
# Backtest report + stricter pre-lift validator
# ---------------------------------------------------------------------------

@dataclass
class BacktestReport:
    """
    Full backtest result used by validate_before_lift().

    Richer than StrategyStats: includes equity_curve and raw returns so
    positive-expectancy can be verified directly from the run output.
    Produced by merid/backtesting/kalshi_backtest.run_backtest_2y().
    """
    equity_curve: List[float]
    returns: List[float]
    max_drawdown: float     # 0..1
    sharpe: float
    trades: int
    years: float


def validate_before_lift(bt: BacktestReport) -> dict:
    """
    Stricter gate used immediately before relaxing per-trade caps or
    enabling live execution.  All checks must pass.

    Returns {"ok": bool, "reason": str}.
    """
    if bt.years < 1.0:
        return {"ok": False, "reason": "history_lt_1y"}
    if bt.trades < 100:
        return {"ok": False, "reason": "too_few_trades"}
    if bt.max_drawdown > 0.30:
        return {"ok": False, "reason": "max_dd_gt_30pct"}
    if bt.sharpe < 0.7:
        return {"ok": False, "reason": "sharpe_lt_0p7"}
    if sum(bt.returns) <= 0:
        return {"ok": False, "reason": "non_positive_pnl"}
    return {"ok": True, "reason": "ok"}
