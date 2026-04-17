"""
PromotionEngine — reads realised performance and advances the phase ladder.

Call `maybe_promote(perf)` periodically (e.g. once per day or once per lane
cycle) to let the engine unlock higher phases when criteria are met.

Demotion is intentionally conservative: the engine never drops more than one
phase per evaluation to avoid thrashing during short drawdown spikes.
"""

from __future__ import annotations

import threading
import datetime
from utils.logger import get_logger
import math
from dataclasses import dataclass, field
from typing import List, Optional

from merid.risk.btc_promotion_config import (
    PHASES,
    PromotionPhase,
    LiveEligibility,
    check_backtest_eligibility,
    StrategyStats,
    BacktestReport,
    validate_before_lift,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Performance snapshot (caller fills this from PnL / trade history)
# ---------------------------------------------------------------------------

@dataclass
class PerformanceSnapshot:
    """Live performance metrics used to evaluate promotion eligibility."""

    equity: float                       # current account equity ($)
    max_drawdown: float                 # worst peak-to-trough drawdown (0..1)
    sharpe: float                       # rolling Sharpe ratio
    total_trades: int                   # completed trades (fills, not orders)
    first_live_date: datetime.date      # date of first live (non-paper) trade

    # Optional extras — used for richer logging; not gating criteria
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    open_positions: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# Dynamic position sizing
# ---------------------------------------------------------------------------

@dataclass
class PerfState:
    """
    Lightweight snapshot used by dynamic_size().

    Separate from PerformanceSnapshot so callers can pass just the fields
    needed for intra-cycle sizing without the full promotion context.
    """
    equity: float
    initial_equity: float
    drawdown: float         # current peak-to-trough drawdown (0..1)
    consec_losses: int      # consecutive losing trades


def dynamic_size(
    perf: PerfState,
    base_risk_frac: float = 0.02,
) -> float:
    """
    Dynamic risk $ per trade, always capped at 5% equity.

    Reduction schedule:
      - drawdown ≥ 10% → 30% of base
      - drawdown ≥  8% → 50% of base
      - drawdown ≥  5% → 70% of base
      - 3+ consecutive losses → additional 50% reduction

    Compounding:
      - equity > 5% above initial → scale up proportionally
        (absolute size grows; relative risk stays bounded by 5% cap)
    """
    risk_frac = base_risk_frac

    # Drawdown steps
    if perf.drawdown >= 0.10:
        risk_frac *= 0.30
    elif perf.drawdown >= 0.08:
        risk_frac *= 0.50
    elif perf.drawdown >= 0.05:
        risk_frac *= 0.70

    # Consecutive-loss reduction
    if perf.consec_losses >= 3:
        risk_frac *= 0.50

    # Compound up only at new equity highs (> 5% above initial)
    if perf.equity > perf.initial_equity * 1.05:
        risk_frac *= perf.equity / perf.initial_equity

    # Hard 5% cap
    risk_frac = min(risk_frac, 0.05)
    return perf.equity * max(risk_frac, 0.0)


def drawdown_guarded_risk_frac(
    equity: float,
    peak_equity: float,
    base_frac: float = 0.02,
) -> float:
    """
    Return a risk fraction per trade that shrinks as drawdown deepens.

    Reduction schedule (tighter than dynamic_size):
      - drawdown ≥ 10% → 25% of base
      - drawdown ≥  7% → 50% of base
      - drawdown ≥  5% → 75% of base

    Hard ceiling: 5% equity.  Returns 0.0 if peak_equity ≤ 0.
    """
    if peak_equity <= 0:
        return base_frac

    dd = (peak_equity - equity) / peak_equity  # 0..1

    frac = base_frac
    if dd >= 0.10:
        frac *= 0.25
    elif dd >= 0.07:
        frac *= 0.50
    elif dd >= 0.05:
        frac *= 0.75

    frac = min(frac, 0.05)
    return max(frac, 0.0)


# ---------------------------------------------------------------------------
# Loss streak tracker
# ---------------------------------------------------------------------------

class LossStreakTracker:
    """
    Tracks consecutive losing trades and returns a size multiplier.

    Thresholds:
      - 3+ consecutive losses → 50% risk
      - 5+ consecutive losses → 0% risk (circuit breaker / pause)

    Reset on any winning trade.
    """

    def __init__(self) -> None:
        self.consec_losses: int = 0
        self.max_consec_losses: int = 0

    def update(self, trade_pnl: float) -> None:
        """Call after each completed trade fill."""
        if trade_pnl < 0:
            self.consec_losses += 1
            self.max_consec_losses = max(self.max_consec_losses, self.consec_losses)
        elif trade_pnl > 0:
            self.consec_losses = 0
        # pnl == 0 (scratch) leaves streak unchanged

    def get_size_multiplier(self) -> float:
        """
        Returns fraction of normal risk to apply.
          5+ losses → 0.0  (full circuit breaker)
          3-4 losses → 0.5  (half risk)
          <3 losses  → 1.0  (normal)
        """
        if self.consec_losses >= 5:
            return 0.0
        if self.consec_losses >= 3:
            return 0.5
        return 1.0

    def should_pause_trading(self) -> bool:
        """True when circuit breaker is active (5+ consecutive losses)."""
        return self.consec_losses >= 5

    def get_status(self) -> dict:
        return {
            "consec_losses": self.consec_losses,
            "max_consec_losses": self.max_consec_losses,
            "size_multiplier": self.get_size_multiplier(),
            "paused": self.should_pause_trading(),
        }

    def reset(self) -> None:
        """Manual reset — call after a deliberate trading pause."""
        self.consec_losses = 0


# ---------------------------------------------------------------------------
# Live-enable gate (backtest + forward performance)
# ---------------------------------------------------------------------------

@dataclass
class LivePerf:
    """Forward (live/paper) performance used to gate lane_live promotion."""
    equity: float
    max_drawdown: float     # 0..1
    sharpe: float
    trades: int
    days_live: int


def can_enable_live(
    backtest: LiveEligibility,
    live: LivePerf,
) -> tuple[bool, str]:
    """
    Returns (allowed, reason).

    Both backtest eligibility AND forward live performance must pass.
    Backtest gate ensures the strategy has a credible edge before any
    real capital is committed; forward gate ensures it is holding up.
    """
    if not backtest.allow_live:
        return False, f"backtest_gate: {backtest.reason}"
    if live.days_live < 7:
        return False, f"forward_gate: only {live.days_live} days live (need 7)"
    if live.trades < 30:
        return False, f"forward_gate: only {live.trades} trades (need 30)"
    if live.max_drawdown > 0.25:
        return False, f"forward_gate: drawdown {live.max_drawdown:.1%} > 25%"
    if live.sharpe < 0.4:
        return False, f"forward_gate: sharpe {live.sharpe:.2f} < 0.4"
    return True, "ok"


# ---------------------------------------------------------------------------
# Promotion result
# ---------------------------------------------------------------------------

@dataclass
class PromotionResult:
    previous_phase: str
    current_phase: str
    promoted: bool
    demoted: bool
    criteria_met: dict[str, bool] = field(default_factory=dict)
    reason: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PromotionEngine:
    """
    Evaluates PerformanceSnapshot against PHASES and updates current_phase.

    Rules:
    - Promotion: advance to the highest phase whose ALL criteria are satisfied.
    - Demotion: if current phase criteria are no longer met, drop exactly one
      phase (never free-fall multiple levels in one evaluation).
    - Phase 0 is the floor — never demoted below it.
    """

    def __init__(self) -> None:
        self.current_phase: PromotionPhase = PHASES[0]
        self._history: List[PromotionResult] = []
        self._last_eval: Optional[datetime.datetime] = None

    # ── Public API ────────────────────────────────────────────────────────

    def maybe_promote(self, perf: PerformanceSnapshot) -> PromotionResult:
        """
        Evaluate perf against the phase ladder and update current_phase.

        Returns a PromotionResult describing what changed (if anything).
        """
        self._last_eval = datetime.datetime.now(datetime.timezone.utc)
        days_live = (datetime.date.today() - perf.first_live_date).days
        prev_name = self.current_phase.name

        # Find the highest phase whose criteria are all satisfied
        best = PHASES[0]
        criteria_log: dict[str, bool] = {}

        for phase in PHASES:
            ok, details = self._check_criteria(phase, perf, days_live)
            criteria_log[phase.name] = ok
            if ok:
                best = phase

        # Demotion guard: never drop more than one phase per evaluation
        current_idx = self._phase_index(self.current_phase)
        best_idx = self._phase_index(best)
        if best_idx < current_idx - 1:
            best = PHASES[current_idx - 1]
            logger.warning(
                "PromotionEngine: demotion clamped to one step (%s → %s)",
                prev_name, best.name,
            )

        promoted = best_idx > current_idx
        demoted = best_idx < current_idx
        self.current_phase = best

        result = PromotionResult(
            previous_phase=prev_name,
            current_phase=best.name,
            promoted=promoted,
            demoted=demoted,
            criteria_met=criteria_log,
            reason=self._build_reason(perf, days_live, promoted, demoted),
        )
        self._history.append(result)

        if promoted:
            logger.info(
                "🚀 PromotionEngine: PROMOTED %s → %s | equity=%.2f trades=%d sharpe=%.2f",
                prev_name, best.name, perf.equity, perf.total_trades, perf.sharpe,
            )
        elif demoted:
            logger.warning(
                "⬇️  PromotionEngine: DEMOTED %s → %s | drawdown=%.1f%% equity=%.2f",
                prev_name, best.name, perf.max_drawdown * 100, perf.equity,
            )

        return result

    def get_caps(self, equity: float) -> dict:
        """
        Return the effective risk caps for the current phase, applying the
        per_trade_pct clamp so absolute size scales with equity but never
        exceeds the phase's hard per_trade_cap.
        """
        phase = self.current_phase
        pct_cap = phase.per_trade_pct * equity
        per_trade = min(phase.per_trade_cap, pct_cap)
        max_exposure_dollars = phase.max_exposure * equity
        return {
            "phase": phase.name,
            "per_trade": per_trade,
            "max_exposure": max_exposure_dollars,
            "max_open_trades": phase.max_open_trades,
            "unlocked_timeframes": list(phase.unlocked_timeframes),
            "unlocked_assets": list(phase.unlocked_assets),
            "allow_live": phase.allow_live,
        }

    def is_asset_unlocked(self, asset: str) -> bool:
        return asset in self.current_phase.unlocked_assets

    def is_timeframe_unlocked(self, timeframe: str) -> bool:
        return timeframe in self.current_phase.unlocked_timeframes

    def can_go_live(self) -> bool:
        return self.current_phase.allow_live

    def get_status(self) -> dict:
        return {
            "current_phase": self.current_phase.name,
            "last_eval": self._last_eval.isoformat() if self._last_eval else None,
            "history_count": len(self._history),
            "last_result": (
                {
                    "promoted": self._history[-1].promoted,
                    "demoted": self._history[-1].demoted,
                    "reason": self._history[-1].reason,
                }
                if self._history else None
            ),
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _check_criteria(
        self,
        phase: PromotionPhase,
        perf: PerformanceSnapshot,
        days_live: int,
    ) -> tuple[bool, dict]:
        checks = {
            "equity": perf.equity >= phase.min_equity,
            "days_live": days_live >= phase.min_days_live,
            "drawdown": perf.max_drawdown <= phase.max_drawdown,
            "trades": perf.total_trades >= phase.min_trades,
            "sharpe": (
                phase.sharpe_threshold <= -900
                or (not math.isnan(perf.sharpe) and perf.sharpe >= phase.sharpe_threshold)
            ),
        }
        return all(checks.values()), checks

    @staticmethod
    def _phase_index(phase: PromotionPhase) -> int:
        for i, p in enumerate(PHASES):
            if p.name == phase.name:
                return i
        return 0

    @staticmethod
    def _build_reason(
        perf: PerformanceSnapshot,
        days_live: int,
        promoted: bool,
        demoted: bool,
    ) -> str:
        tag = "PROMOTED" if promoted else ("DEMOTED" if demoted else "UNCHANGED")
        return (
            f"{tag} | equity={perf.equity:.2f} days={days_live} "
            f"trades={perf.total_trades} dd={perf.max_drawdown:.1%} "
            f"sharpe={perf.sharpe:.2f}"
        )


# ---------------------------------------------------------------------------
# Per-agent registry  (BUG-m1 fix: no more shared singleton)
# ---------------------------------------------------------------------------

_engines: dict[str, "PromotionEngine"] = {}
_engines_lock = threading.Lock()

_GLOBAL_AGENT_KEY = "__global__"


def get_promotion_engine(agent_id: str = _GLOBAL_AGENT_KEY) -> PromotionEngine:
    """Return the PromotionEngine for *agent_id*.

    Each agent cell gets its own independent engine so that BTC_15M and
    BTC_HOURLY (for example) do not share a single phase state.  The legacy
    no-argument call still works via the ``__global__`` sentinel key, but
    callers should prefer passing an explicit agent_id.
    """
    if agent_id not in _engines:
        with _engines_lock:
            if agent_id not in _engines:
                _engines[agent_id] = PromotionEngine()
                if agent_id != _GLOBAL_AGENT_KEY:
                    logger.info(
                        "[promotion_engine] created per-agent engine for '%s'", agent_id
                    )
    return _engines[agent_id]


def reset_promotion_engine(agent_id: str = _GLOBAL_AGENT_KEY) -> None:
    """Remove the engine for *agent_id* from the registry (test / redeploy use)."""
    with _engines_lock:
        _engines.pop(agent_id, None)


def all_engine_statuses() -> dict:
    """Return a dict of {agent_id: engine.get_status()} for monitoring."""
    return {aid: eng.get_status() for aid, eng in _engines.items()}
