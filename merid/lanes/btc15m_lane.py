"""
BTC15MLane — End-to-end orchestration for BTC 15m Kalshi trading.

Wires together:
  - Kalshi market discovery (KalshiMarketCatalog)
  - Sentiment stack (SentimentBus → SentimentBundle + Fibonacci smoothing)
  - Swarm consensus (SwarmConsensusAggregator)
  - Risk evaluation (CryptoSwarmRiskBTC15m + BTCSentimentRiskDial)
  - Order execution (KalshiExecutor, mode-guarded)
  - Observability (structured logging of every decision)

Risk clamps are data-driven via PromotionEngine — no hardcoded constants.
Phases unlock timeframes, assets, and live execution based on realised PnL
performance (equity, drawdown, Sharpe, trade count).

No execution path bypasses risk evaluation.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lane configuration
# ---------------------------------------------------------------------------

@dataclass
class BTC15MLaneConfig:
    """Runtime configuration for the BTC 15m lane."""
    # Kalshi market discovery
    series_ticker: str = "KXBTC"
    timeframe: str = "15m"
    asset: str = "BTC"
    max_markets_per_cycle: int = 5

    # Cycle timing
    cycle_interval_seconds: float = 60.0       # how often to run the main loop
    sentiment_refresh_seconds: float = 300.0   # how often to refresh sentiment
    phase_refresh_seconds: float = 86_400.0    # how often to re-evaluate promotion (1 day)

    # Starting equity — updated from realised PnL each cycle
    equity: float = 0.0

    # Base trade size is now derived from phase caps; this is the fallback floor
    base_trade_size: float = 0.10              # dollars (minimum attempt size)

    # Mode — overridden by per-lane promotion; system TradeMode is the final guard
    paper_mode: bool = True

    # Observability
    log_every_cycle: bool = True
    log_rationale: bool = True


# ---------------------------------------------------------------------------
# Lane state
# ---------------------------------------------------------------------------

@dataclass
class LaneCycleResult:
    """Result of one BTC15MLane cycle."""
    cycle_id: str
    timestamp: datetime
    markets_found: int
    sentiment_bundle: Optional[Dict[str, Any]]
    consensus: Optional[Dict[str, Any]]
    risk_decision: Optional[Dict[str, Any]]
    order_result: Optional[Dict[str, Any]]
    blocked_reason: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp_winner(risk_decision: Dict[str, Any]) -> str:
    """
    Return a short label identifying which clamp produced the smallest size.
    Used in the structured ORDER log so the audit trail shows exactly which
    rule limited the trade.
    """
    candidates = {
        "kelly":   risk_decision.get("kelly_size"),
        "vol_fg":  risk_decision.get("vol_size"),
        "dynamic": risk_decision.get("dynamic_size"),
    }
    # Filter out None / zero
    valid = {k: v for k, v in candidates.items() if v is not None and v > 0}
    if not valid:
        return "dynamic"
    return min(valid, key=lambda k: valid[k])


# ---------------------------------------------------------------------------
# BTC15MLane
# ---------------------------------------------------------------------------

class BTC15MLane:
    """
    Orchestrates one full BTC 15m trading cycle:

        fetch_market_data → update_sentiment → run_swarm →
        evaluate_risk → execute (if approved)

    Risk clamps are data-driven via PromotionEngine.  No constants are
    hardcoded in this class; change btc_promotion_config.PHASES to evolve
    behaviour.

    Per-lane live flag:
        lane_live=False  → always paper regardless of system TradeMode
        lane_live=True   → defers to system TradeMode (still requires LIVE)

    Promotion to lane_live happens automatically when PromotionEngine
    advances past PHASE_0 and performance criteria are met.
    """

    def __init__(self, config: Optional[BTC15MLaneConfig] = None):
        self.config = config or BTC15MLaneConfig()

        # ── Runtime state ────────────────────────────────────────────────
        self._running = False
        self._cycle_count = 0
        self._last_sentiment_refresh: float = 0.0
        self._last_phase_refresh: float = 0.0
        self._cached_sentiment: Optional[Dict[str, Any]] = None
        self._sentiment_history: List[float] = []
        self._price_history: List[float] = []   # strike_price per cycle for ATR

        # ── Per-lane live flag ───────────────────────────────────────────
        # Starts False; promoted automatically when phase allows live
        self.lane_live: bool = False

        # ── PnL / performance tracking (updated each cycle) ──────────────
        self._realised_pnl: float = 0.0          # cumulative realised PnL
        self._peak_equity: float = self.config.equity
        self._initial_equity: float = self.config.equity
        self._max_drawdown: float = 0.0
        self._completed_trades: int = 0
        self._consec_losses: int = 0              # consecutive losing trades
        self._pnl_history: List[float] = []       # per-trade PnL for Sharpe
        self._first_live_date: dt.date = dt.date.today()

        # ── Backtest eligibility (set once; persists for session) ─────────
        # Override by calling set_backtest_stats(StrategyStats(...))
        # or set_backtest_report(BacktestReport(...)) before start().
        self._backtest_eligibility = None
        self._backtest_report = None        # full BacktestReport if available

        # ── Loss streak tracker ───────────────────────────────────────────
        # Separate from _consec_losses counter — provides circuit-breaker
        # and size multiplier used directly in _evaluate_risk.
        self._loss_streak = None            # initialised in _init_components

        # ── Bot lifecycle state machine ───────────────────────────────────
        # BACKTEST → FORWARD_PAPER → LIVE_RESTRICTED → LIVE_NORMAL
        # get_risk_profile() drives paper_mode and base risk fraction.
        self._lifecycle = None              # initialised in _init_components
        self._forward_tracker = None        # optional; set via set_forward_tracker()

        # ── ATR volatility monitor ────────────────────────────────────────
        # Detects high_vol / low_vol regime flips and fires alerts.
        self._atr_monitor = None            # initialised in _init_components

        # ── Multi-timeframe drawdown guard ────────────────────────────────
        # Per-lane + global DD brakes; shared singleton across all lanes.
        self._dd_guard = None               # initialised in _init_components
        self._dd_key = f"{self.config.asset}:{self.config.timeframe}"

        # ── Monte Carlo metrics (set after backtest) ──────────────────────
        # Used by mc_adjust_risk_frac() to scale base_risk_frac.
        self._mc_metrics: Optional[Dict[str, float]] = None

        # ── Kalman sentiment filter ───────────────────────────────────────
        # Replaces pure Fibonacci smoothing in _update_sentiment().
        # Produces state-space filtered combined_smoothed signal.
        self._kalman = None             # initialised in _init_components

        # ── FG regime tracking (for regime-change Telegram alerts) ─────────
        self._last_fg_regime: str = "unknown"

        # ── Lane metrics ───────────────────────────────────────────────────
        # In-memory counters for Prometheus export; zero overhead in hot path.
        from merid.lanes.lane_metrics import get_lane_metrics
        self._metrics = get_lane_metrics(f"{self.config.asset}:{self.config.timeframe}")

        # ── Lazy-initialised components ──────────────────────────────────
        self._catalog = None
        self._executor = None
        self._risk_manager = None
        self._risk_dial = None
        self._consensus_agg = None
        self._promotion_engine = None

        logger.info(
            "BTC15MLane created | equity=%.2f | paper=%s | cycle=%.0fs",
            self.config.equity,
            self.config.paper_mode,
            self.config.cycle_interval_seconds,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise components and enter the main loop."""
        await self._init_components()
        self._running = True
        logger.info(
            "BTC15MLane started | phase=%s | lane_live=%s",
            self._promotion_engine.current_phase.name,
            self.lane_live,
        )
        # Start Telegram dashboard heartbeat (every 2 minutes)
        try:
            from merid.alerts.webhook_client import dashboard_loop
            self._dashboard_task = asyncio.create_task(
                dashboard_loop(self.get_status, interval_sec=120.0),
                name="btc15m-dashboard-heartbeat",
            )
        except Exception as _e:
            logger.debug("dashboard_loop_start: %s", _e)
        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("BTC15MLane cancelled")
        finally:
            self._running = False
            logger.info("BTC15MLane stopped")

    def stop(self) -> None:
        """Signal the main loop to exit."""
        self._running = False

    async def run_once(self) -> LaneCycleResult:
        """Run exactly one cycle (useful for testing / manual trigger)."""
        if self._catalog is None:
            await self._init_components()
        return await self._run_cycle()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def _init_components(self) -> None:
        """Lazy-init all sub-components."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        from merid.risk.crypto_swarm_risk_btc15m import (
            CryptoSwarmRiskBTC15m,
            RiskPhase,
        )
        from merid.risk.promotion_engine import get_promotion_engine
        from merid.sentiment.btc_risk_dial import get_btc_risk_dial
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator

        self._promotion_engine = get_promotion_engine()
        self._risk_dial = get_btc_risk_dial(
            equity=self.config.equity,
            promotion_engine=self._promotion_engine,
        )
        self._catalog = KalshiMarketCatalog()
        # Bootstrap phase from PromotionEngine so caps are correct from cycle 1
        _init_phase = RiskPhase.PHASE_0
        try:
            _phase_name = self._promotion_engine.current_phase.name
            _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
        except Exception as _e:
            logger.debug("phase_bootstrap: %s", _e)
        self._risk_manager = CryptoSwarmRiskBTC15m(
            current_equity=self.config.equity,
            phase=_init_phase,
        )
        self._consensus_agg = SwarmConsensusAggregator()

        # Executor is optional — only needed for live order submission
        try:
            from merid.execution.executors.kalshi import KalshiExecutor
            self._executor = KalshiExecutor()
        except Exception as exc:
            logger.warning("KalshiExecutor unavailable (%s) — orders will be simulated", exc)
            self._executor = None

        # Loss streak tracker
        from merid.risk.promotion_engine import LossStreakTracker
        self._loss_streak = LossStreakTracker()

        # Bot lifecycle state machine
        from merid.backtesting.bot_lifecycle import get_bot_lifecycle
        self._lifecycle = get_bot_lifecycle()

        # ForwardTracker — auto-attach so lifecycle gate accumulates paper fills
        # without requiring external set_forward_tracker() call
        if self._forward_tracker is None:
            from merid.backtesting.forward_tester import ForwardTracker
            self._forward_tracker = ForwardTracker(initial_equity=self.config.equity)
            logger.info(
                "BTC15MLane: ForwardTracker auto-attached (initial_equity=%.2f)",
                self.config.equity,
            )

        # ATR monitor
        from merid.sentiment.btc_risk_dial import ATRMonitor
        self._atr_monitor = ATRMonitor(window=14, high_thresh=2.0, low_thresh=0.5)

        # Kalman sentiment filter
        from merid.sentiment.kalman_sentiment import SentimentKalman
        self._kalman = SentimentKalman(process_var=0.01, meas_var=0.10)

        # Multi-timeframe drawdown guard (shared singleton)
        from merid.risk.multi_tf_drawdown import get_multi_tf_drawdown_guard
        self._dd_guard = get_multi_tf_drawdown_guard()

        # Initial phase refresh so caps are correct from cycle 1
        self._do_phase_refresh()

        logger.info(
            "BTC15MLane components initialised | phase=%s | lane_live=%s",
            self._promotion_engine.current_phase.name,
            self.lane_live,
        )

    # ------------------------------------------------------------------
    # Promotion helpers
    # ------------------------------------------------------------------

    def _build_perf_snapshot(self):
        """Build a PerformanceSnapshot from current lane PnL state."""
        from merid.risk.promotion_engine import PerformanceSnapshot
        import math

        # Rolling Sharpe over per-trade PnL history (simple, annualised approx)
        sharpe = 0.0
        if len(self._pnl_history) >= 5:
            n = len(self._pnl_history)
            mean = sum(self._pnl_history) / n
            variance = sum((x - mean) ** 2 for x in self._pnl_history) / n
            std = math.sqrt(variance) if variance > 0 else 1e-9
            # Annualise: ~96 15m bars/day, ~252 trading days
            sharpe = (mean / std) * math.sqrt(96 * 252)

        return PerformanceSnapshot(
            equity=self.config.equity,
            max_drawdown=self._max_drawdown,
            sharpe=sharpe,
            total_trades=self._completed_trades,
            first_live_date=self._first_live_date,
            win_rate=(
                sum(1 for p in self._pnl_history if p > 0) / len(self._pnl_history)
                if self._pnl_history else 0.0
            ),
            avg_pnl_per_trade=(
                sum(self._pnl_history) / len(self._pnl_history)
                if self._pnl_history else 0.0
            ),
        )

    def _do_phase_refresh(self) -> None:
        """Re-evaluate promotion phase, sync risk dial caps, and update lifecycle."""
        if self._promotion_engine is None or self._risk_dial is None:
            return
        perf = self._build_perf_snapshot()
        self._risk_dial.refresh_phase(perf)
        self._maybe_enable_live()
        self._last_phase_refresh = time.monotonic()

        # Sync CryptoSwarmRiskBTC15m caps from the new phase
        if self._risk_manager is not None:
            try:
                self._risk_manager.update_from_phase(self.config.equity)
            except Exception as _e:
                logger.debug("update_from_phase: %s", _e)

        # Upgrade lifecycle to LIVE_NORMAL when phase warrants it
        if self._lifecycle is not None:
            phase_name = self._promotion_engine.current_phase.name
            self._lifecycle.maybe_upgrade_to_normal(phase_name)

        phase_name = self._promotion_engine.current_phase.name
        logger.info(
            "Phase refresh: phase=%s lane_live=%s lifecycle=%s equity=%.2f dd=%.1f%% trades=%d",
            phase_name,
            self.lane_live,
            self._lifecycle.state.name if self._lifecycle else "?",
            self.config.equity,
            self._max_drawdown * 100,
            self._completed_trades,
        )
        # Telegram: promotion event
        try:
            import asyncio as _aio
            from merid.alerts.webhook_client import tg_send
            _aio.create_task(tg_send(
                f"\U0001f4c8 [Kalshi BTC15m] Phase refresh: <b>{phase_name}</b> "
                f"| lane_live={self.lane_live} "
                f"| lifecycle={self._lifecycle.state.name if self._lifecycle else '?'} "
                f"| equity=${self.config.equity:.2f} "
                f"| dd={self._max_drawdown*100:.1f}%"
            ))
        except Exception as _e:
            logger.debug("tg_phase_refresh: %s", _e)

    def set_forward_tracker(self, tracker) -> None:
        """
        Attach a ForwardTracker to this lane.

        The tracker accumulates paper fills and provides ForwardStats
        for KalshiBotLifecycle.on_forward_update().
        """
        self._forward_tracker = tracker
        logger.info("BTC15MLane: ForwardTracker attached")

    def set_mc_metrics(self, mc_metrics: Dict[str, float]) -> None:
        """
        Store Monte Carlo risk metrics for use in mc_adjust_risk_frac().

        Call this after run_backtest_2y() + monte_carlo_risk_metrics(),
        before start(), so the first cycle uses MC-adjusted sizing.
        """
        self._mc_metrics = mc_metrics
        logger.info(
            "BTC15MLane: MC metrics set — p5=%.3f prob_loss=%.1f%% median=%.3f",
            mc_metrics.get("p5", 0.0),
            mc_metrics.get("prob_loss", 0.0) * 100,
            mc_metrics.get("median", 0.0),
        )

    def set_backtest_stats(self, stats) -> None:
        """Set eligibility from a StrategyStats (lightweight backtest summary)."""
        from merid.risk.btc_promotion_config import check_backtest_eligibility
        self._backtest_eligibility = check_backtest_eligibility(stats)
        logger.info(
            "BTC15MLane: backtest eligibility set — allow_live=%s reason=%s",
            self._backtest_eligibility.allow_live,
            self._backtest_eligibility.reason,
        )

    def set_backtest_report(self, report) -> None:
        """
        Set eligibility from a full BacktestReport (from run_backtest_2y).

        validate_before_lift() is stricter than check_backtest_eligibility:
        it also requires positive expectancy (sum of returns > 0) and
        ≥100 trades instead of ≥50.
        """
        from merid.risk.btc_promotion_config import validate_before_lift, LiveEligibility
        self._backtest_report = report
        result = validate_before_lift(report)
        self._backtest_eligibility = LiveEligibility(
            allow_live=result["ok"],
            reason=result["reason"],
        )
        logger.info(
            "BTC15MLane: BacktestReport validated — allow_live=%s reason=%s "
            "(sharpe=%.2f dd=%.1f%% trades=%d years=%.1f)",
            result["ok"], result["reason"],
            report.sharpe, report.max_drawdown * 100,
            report.trades, report.years,
        )

    def _maybe_enable_live(self) -> None:
        """
        Flip lane_live=True only when BOTH gates pass:
          1. PromotionEngine phase allows live (equity/drawdown/Sharpe/trades)
          2. can_enable_live() — backtest eligibility + forward live performance
        """
        if self.lane_live:
            return  # already live — never demote mid-session
        if self._promotion_engine is None:
            return
        phase = self._promotion_engine.current_phase
        if not phase.allow_live or phase.name == "PHASE_0":
            return

        # Build forward-perf snapshot
        from merid.risk.promotion_engine import LivePerf, can_enable_live
        days_live = (dt.date.today() - self._first_live_date).days
        live_perf = LivePerf(
            equity=self.config.equity,
            max_drawdown=self._max_drawdown,
            sharpe=self._build_perf_snapshot().sharpe,
            trades=self._completed_trades,
            days_live=days_live,
        )

        # Backtest gate — prefer full BacktestReport validation if available
        if self._backtest_report is not None:
            from merid.risk.btc_promotion_config import validate_before_lift, LiveEligibility
            bt_result = validate_before_lift(self._backtest_report)
            backtest = LiveEligibility(
                allow_live=bt_result["ok"],
                reason=bt_result["reason"],
            )
        elif self._backtest_eligibility is not None:
            backtest = self._backtest_eligibility
        else:
            from merid.risk.btc_promotion_config import LiveEligibility
            backtest = LiveEligibility(allow_live=True, reason="no_backtest_provided")

        allowed, reason = can_enable_live(backtest, live_perf)
        if not allowed:
            logger.debug("BTC15MLane: can_enable_live blocked — %s", reason)
            return

        # Also advance lifecycle via ForwardTracker if available
        if self._lifecycle is not None and self._forward_tracker is not None:
            fwd_stats = self._forward_tracker.get_stats()
            lc_result = self._lifecycle.on_forward_update(fwd_stats)
            if not lc_result.get("advanced") and self._lifecycle.is_paper():
                logger.debug(
                    "BTC15MLane: lifecycle forward gate not yet met — %s",
                    lc_result.get("reason", "?"),
                )
                return

        self.lane_live = True
        logger.info(
            "\U0001f7e2 BTC15MLane: lane_live ENABLED (phase=%s lifecycle=%s equity=%.2f trades=%d days=%d)",
            phase.name,
            self._lifecycle.state.name if self._lifecycle else "?",
            self.config.equity, self._completed_trades, days_live,
        )
        # Telegram: live-enable event
        try:
            import asyncio as _aio
            from merid.alerts.webhook_client import tg_send
            _aio.create_task(tg_send(
                f"\U0001f7e2 [Kalshi BTC15m] <b>LIVE ENABLED</b> "
                f"| phase={phase.name} "
                f"| lifecycle={self._lifecycle.state.name if self._lifecycle else '?'} "
                f"| equity=${self.config.equity:.2f} "
                f"| trades={self._completed_trades} days={days_live}"
            ))
        except Exception as _e:
            logger.debug("tg_live_enabled: %s", _e)

    # ------------------------------------------------------------------
    # _compound_equity — update equity after each fill
    # ------------------------------------------------------------------

    def _compound_equity(self, trade_pnl: float) -> None:
        self.config.equity = max(0.01, self.config.equity + trade_pnl)
        self._realised_pnl += trade_pnl
        self._pnl_history.append(trade_pnl)
        if len(self._pnl_history) > 200:
            self._pnl_history = self._pnl_history[-200:]
        self._completed_trades += 1

        # Consecutive-loss counter (simple)
        if trade_pnl < 0:
            self._consec_losses += 1
        else:
            self._consec_losses = 0

        # LossStreakTracker (circuit-breaker aware)
        if self._loss_streak is not None:
            self._loss_streak.update(trade_pnl)

        # ForwardTracker — accumulates paper fills for lifecycle gate
        if self._forward_tracker is not None:
            self._forward_tracker.record_fill(trade_pnl)

        # Update peak equity and max drawdown
        if self.config.equity > self._peak_equity:
            self._peak_equity = self.config.equity
        drawdown = (self._peak_equity - self.config.equity) / max(self._peak_equity, 0.01)
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

        # Propagate updated equity to risk dial
        if self._risk_dial is not None:
            self._risk_dial.equity = self.config.equity

        # Feed PnL into global kill-switch daily loss tracker
        if trade_pnl != 0.0:
            try:
                from merid.risk.kill_switches import risk_controller as _rc
                _rc.record_pnl(trade_pnl)
            except Exception as _e:
                logger.debug("record_pnl: %s", _e)

        # Update lane metrics equity snapshot
        self._metrics.update_equity_snapshot(
            equity=self.config.equity,
            drawdown=self._max_drawdown,
            consec_losses=self._consec_losses,
        )

        # Update multi-TF drawdown guard (per-lane key + GLOBAL)
        if self._dd_guard is not None:
            self._dd_guard.update_equity(self._dd_key, self.config.equity)
            self._dd_guard.update_equity("GLOBAL", self.config.equity)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _main_loop(self) -> None:
        while self._running:
            t0 = time.monotonic()

            # Periodic phase refresh (default: daily)
            if (time.monotonic() - self._last_phase_refresh) >= self.config.phase_refresh_seconds:
                self._do_phase_refresh()

            result = await self._run_cycle()
            elapsed = (time.monotonic() - t0) * 1000

            if self.config.log_every_cycle:
                self._log_cycle_summary(result, elapsed)

            # Sleep remainder of interval
            sleep_s = max(0.0, self.config.cycle_interval_seconds - elapsed / 1000)
            await asyncio.sleep(sleep_s)

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self) -> LaneCycleResult:
        t0 = time.monotonic()
        self._cycle_count += 1
        cycle_id = f"btc15m-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{self._cycle_count:04d}"

        result = LaneCycleResult(
            cycle_id=cycle_id,
            timestamp=datetime.now(timezone.utc),
            markets_found=0,
            sentiment_bundle=None,
            consensus=None,
            risk_decision=None,
            order_result=None,
        )

        try:
            # 0a. Update sentiment staleness gauge (every cycle, not just on refresh)
            if self._last_sentiment_refresh > 0:
                age_s = time.monotonic() - self._last_sentiment_refresh
                synth = (self._cached_sentiment or {}).get("fg_is_synthetic", False)
                self._metrics.update_sentiment_snapshot(
                    sentiment_age_seconds=age_s,
                    fg_is_synthetic=bool(synth),
                )

            # 0. Global kill switch — checked before any work
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                result.blocked_reason = f"kill_switch: {risk_controller.get_kill_reason()}"
                logger.warning("[%s] Kill switch active — skipping cycle: %s",
                               cycle_id, result.blocked_reason)
                return result

            # 1. Market data
            markets = await self._fetch_market_data()
            result.markets_found = len(markets)
            if not markets:
                result.blocked_reason = "no_markets_found"
                return result

            # Track strike_price history for ATR (real price proxy, not sentiment)
            _sp = markets[0].get("strike_price") if markets else None
            if _sp is not None:
                try:
                    self._price_history.append(float(_sp))
                    if len(self._price_history) > 50:
                        self._price_history = self._price_history[-50:]
                except (TypeError, ValueError):
                    pass

            # 2. Sentiment
            sentiment = await self._update_sentiment()
            result.sentiment_bundle = sentiment

            # 3. Swarm consensus
            consensus = await self._run_swarm(markets, sentiment)
            result.consensus = consensus

            if consensus.get("status") == "conflicted":
                result.blocked_reason = "swarm_conflicted"
                logger.info("[%s] Swarm conflicted — skipping cycle", cycle_id)
                return result

            if consensus.get("direction") == "neutral":
                consensus_status = consensus.get("status", "neutral")
                result.blocked_reason = f"swarm_neutral:{consensus_status}"
                logger.info(
                    "[%s] CONSENSUS_STATUS=%s skip_size_and_execute",
                    cycle_id,
                    consensus_status.upper(),
                )
                return result

            # 3b. Loss-streak circuit breaker (5+ consecutive losses)
            if self._loss_streak is not None and self._loss_streak.should_pause_trading():
                result.blocked_reason = (
                    f"loss_streak_circuit_breaker: "
                    f"{self._loss_streak.consec_losses} consecutive losses"
                )
                logger.warning(
                    "[%s] Loss-streak circuit breaker active (%d losses) — skipping cycle",
                    cycle_id, self._loss_streak.consec_losses,
                )
                try:
                    import asyncio as _aio
                    from merid.alerts.webhook_client import send_circuit_breaker_alert
                    _aio.create_task(send_circuit_breaker_alert(
                        reason="consecutive_loss_limit",
                        consec_losses=self._loss_streak.consec_losses,
                        asset=self.config.asset,
                        timeframe=self.config.timeframe,
                    ))
                except Exception as _e:
                    logger.debug("circuit_breaker_alert: %s", _e)
                return result

            # 4. Risk evaluation
            risk_decision = await self._evaluate_risk(consensus, sentiment)
            result.risk_decision = risk_decision

            if risk_decision.get("blocked"):
                result.blocked_reason = risk_decision.get("reason", "risk_blocked")
                logger.info(
                    "[%s] Risk BLOCKED: %s", cycle_id, result.blocked_reason
                )
                return result

            # 5. Execute
            order_result = await self._execute(
                markets=markets,
                consensus=consensus,
                risk_decision=risk_decision,
                cycle_id=cycle_id,
            )
            result.order_result = order_result

        except Exception as exc:
            result.error = str(exc)
            logger.exception("[%s] Cycle error: %s", cycle_id, exc)

        result.latency_ms = (time.monotonic() - t0) * 1000

        # --- Lane metrics: record cycle outcome ---
        self._metrics.record_cycle(
            blocked_reason=result.blocked_reason,
            error=result.error,
            latency_ms=result.latency_ms,
        )

        # --- Structured BLOCKED log with full context ---
        if result.blocked_reason:
            rd = result.risk_decision or {}
            sent = result.sentiment_bundle or {}
            logger.warning(
                "[%s] BLOCKED | reason=%s | "
                "equity=%.2f dd=%.1f%% consec_losses=%d | "
                "fg=%s atr_regime=%s lifecycle=%s | "
                "kelly_sigma=%.4f vol_tax=%.2f mc_prob_loss=%s | "
                "phase=%s",
                result.cycle_id,
                result.blocked_reason,
                self.config.equity,
                self._max_drawdown * 100,
                self._consec_losses,
                sent.get("fg_index", "?"),
                rd.get("atr_regime", "?"),
                rd.get("lifecycle_state", "?"),
                rd.get("kelly_sigma", 0.0),
                rd.get("kelly_vol_tax", 1.0),
                self._mc_metrics.get("prob_loss") if self._mc_metrics else None,
                rd.get("phase", "?"),
            )

        return result

    # ------------------------------------------------------------------
    # Step 1 — Market data (phase-gated)
    # ------------------------------------------------------------------

    async def _fetch_market_data(self) -> List[Dict[str, Any]]:
        """
        Discover active Kalshi markets for the configured asset/timeframe.

        Phase gates:
          - Asset must be in phase.unlocked_assets
          - Timeframe must be in phase.unlocked_timeframes

        Returns list of normalised market dicts sorted by volume desc.
        """
        asset = self.config.asset
        timeframe = self.config.timeframe

        # Phase gate — silently return empty if not yet unlocked
        if self._promotion_engine is not None:
            if not self._promotion_engine.is_asset_unlocked(asset):
                logger.debug(
                    "_fetch_market_data: asset %s not unlocked in phase %s",
                    asset, self._promotion_engine.current_phase.name,
                )
                return []
            if not self._promotion_engine.is_timeframe_unlocked(timeframe):
                logger.debug(
                    "_fetch_market_data: timeframe %s not unlocked in phase %s",
                    timeframe, self._promotion_engine.current_phase.name,
                )
                return []

        try:
            catalog_markets = self._catalog.get_markets_by_asset(
                asset,
                timeframe=timeframe,
            )

            markets = []
            for cm in catalog_markets:
                vol = float(cm.market.volume) if cm.market.volume else 0.0
                markets.append({
                    "ticker": cm.market.market_id,
                    "market_id": cm.market.market_id,
                    "question": cm.market.question,
                    "volume": vol,
                    "timeframe": cm.timeframe,
                    "asset": cm.asset,
                    "minutes_to_expiry": cm.minutes_to_expiry,
                    "strike_price": cm.strike_price,
                    "raw": cm.market.raw_data,
                })

            markets.sort(key=lambda m: m["volume"], reverse=True)
            markets = markets[: self.config.max_markets_per_cycle]

            logger.debug(
                "Fetched %d %s %s markets (phase=%s)",
                len(markets), asset, timeframe,
                self._promotion_engine.current_phase.name if self._promotion_engine else "?",
            )
            return markets
        except Exception as exc:
            logger.error("_fetch_market_data failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Step 2 — Sentiment
    # ------------------------------------------------------------------

    async def _update_sentiment(self) -> Dict[str, Any]:
        """
        Refresh sentiment if stale, else return cached.

        Combines: Twitter, Reddit, CFGI, news via SentimentBus,
        then applies Fibonacci smoothing to the combined score.
        """
        now = time.monotonic()
        if (
            self._cached_sentiment is not None
            and (now - self._last_sentiment_refresh) < self.config.sentiment_refresh_seconds
        ):
            return self._cached_sentiment

        try:
            from merid.sentiment.sentiment_bundle import combine_sentiment
            from merid.sentiment.fibonacci_smoothing import quick_fib_smooth

            bundle = combine_sentiment(self.config.asset)

            # Rolling history for ATR proxy (used by _evaluate_risk)
            self._sentiment_history.append(bundle.combined)
            if len(self._sentiment_history) > 50:
                self._sentiment_history = self._sentiment_history[-50:]

            # Fibonacci smoothing (fallback / secondary signal)
            fib_smoothed = quick_fib_smooth(self._sentiment_history[-7:])

            # Kalman filter — primary combined_smoothed signal
            # Replaces raw Fibonacci output seen by risk engine and swarm agents.
            if self._kalman is not None:
                kalman_smoothed = self._kalman.update(bundle.combined)
            else:
                kalman_smoothed = fib_smoothed

            # Resolve FG is_synthetic from cfgi data if available
            fg_is_synthetic = False
            try:
                from merid.sentiment.cfgi_client import get_cfgi_client
                fg_data = get_cfgi_client().get_fear_greed(self.config.asset, use_cache=True)
                fg_is_synthetic = fg_data.is_synthetic
            except Exception as _e:
                logger.debug("cfgi_is_synthetic: %s", _e)

            # FG regime classification
            fg_val = bundle.fg_index
            if fg_val <= 20:
                fg_regime = "extreme_fear"
            elif fg_val <= 40:
                fg_regime = "fear"
            elif fg_val <= 60:
                fg_regime = "neutral"
            elif fg_val <= 80:
                fg_regime = "greed"
            else:
                fg_regime = "extreme_greed"

            sentiment_dict = {
                "twitter": bundle.twitter,
                "reddit": bundle.reddit,
                "fg_index": bundle.fg_index,
                "fg_regime": fg_regime,
                "fg_is_synthetic": fg_is_synthetic,
                "combined_raw": bundle.combined,
                "combined_fib": fib_smoothed,
                "combined_smoothed": kalman_smoothed,   # Kalman output is primary
                "confidence": bundle.confidence,
                "vader_signal": bundle.vader_signal,
                "kalshi_prob_adj": bundle.kalshi_adjustment,
                "kalman_gain": self._kalman.kalman_gain if self._kalman else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # NOTE: _risk_dial.update() is intentionally NOT called here.
            # _evaluate_risk() always calls it before can_trade(), which avoids
            # a second combine_sentiment() network round-trip per cycle.
            self._cached_sentiment = sentiment_dict
            self._last_sentiment_refresh = now

            # Update Prometheus sentiment staleness gauges
            self._metrics.update_sentiment_snapshot(
                sentiment_age_seconds=0.0,  # just refreshed
                fg_is_synthetic=fg_is_synthetic,
            )

            logger.debug(
                "Sentiment updated: FG=%d regime=%s synthetic=%s combined=%.3f kalman=%.3f fib=%.3f conf=%.2f",
                bundle.fg_index,
                fg_regime,
                fg_is_synthetic,
                bundle.combined,
                kalman_smoothed,
                fib_smoothed,
                bundle.confidence,
            )

            # FG regime-change Telegram alert
            if fg_regime != self._last_fg_regime and self._last_fg_regime != "unknown":
                try:
                    import asyncio as _aio
                    from merid.alerts.webhook_client import tg_send
                    synth_warn = " \u26a0\ufe0f(synthetic)" if fg_is_synthetic else ""
                    _aio.create_task(tg_send(
                        f"\U0001f4ca [Kalshi BTC15m] FG regime change: "
                        f"<b>{self._last_fg_regime}</b> \u2192 <b>{fg_regime}</b> "
                        f"(FG={bundle.fg_index}){synth_warn} "
                        f"| combined={bundle.combined:+.2f} conf={bundle.confidence:.0%}"
                    ))
                except Exception as _e:
                    logger.debug("tg_fg_regime_change: %s", _e)
            self._last_fg_regime = fg_regime

            return sentiment_dict

        except Exception as exc:
            logger.error("_update_sentiment failed: %s", exc)
            # Return stale cache or empty
            return self._cached_sentiment or {
                "twitter": 0.0,
                "reddit": 0.0,
                "fg_index": 50,
                "combined_raw": 0.0,
                "combined_smoothed": 0.0,
                "confidence": 0.0,
                "vader_signal": "neutral",
                "kalshi_prob_adj": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    # ------------------------------------------------------------------
    # Step 3 — Swarm consensus
    # ------------------------------------------------------------------

    async def _run_swarm(
        self,
        markets: List[Dict[str, Any]],
        sentiment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build agent proposals from sentiment + market data and aggregate
        into a single consensus decision via SwarmConsensusAggregator.
        """
        try:
            from merid.swarm.consensus_aggregator import AgentProposal

            proposals: List[AgentProposal] = []

            # --- Sentiment agent ---
            sent_score = sentiment.get("combined_smoothed", 0.0)
            fg = sentiment.get("fg_index", 50)
            conf = sentiment.get("confidence", 0.5)

            # Direction from smoothed sentiment
            if sent_score > 0.1:
                direction = "yes"
                prob = 0.5 + min(sent_score * 0.3, 0.25)
            elif sent_score < -0.1:
                direction = "no"
                prob = 0.5 + min(abs(sent_score) * 0.3, 0.25)
            else:
                direction = "neutral"
                prob = 0.5

            proposals.append(
                AgentProposal(
                    agent_id="sentiment_agent",
                    asset=self.config.asset,
                    timeframe=self.config.timeframe,
                    direction=direction,
                    probability=prob,
                    confidence=conf,
                    size_preference="base",
                    rationale=(
                        f"sent_smoothed={sent_score:+.3f} fg={fg} "
                        f"vader={sentiment.get('vader_signal', 'neutral')}"
                    ),
                    edge_estimate=abs(sent_score) * 5.0,
                    timestamp=datetime.now(timezone.utc),
                    agent_archetype="sentiment",
                    mode="LIVE" if self.lane_live else "SIM",
                )
            )

            # --- Fear/Greed contrarian agent ---
            if fg <= 20:
                fg_direction = "yes"   # extreme fear → contrarian long
                fg_conf = 0.65
                fg_rationale = f"Extreme fear (FG={fg}) → contrarian YES"
            elif fg >= 80:
                fg_direction = "no"    # extreme greed → contrarian short
                fg_conf = 0.65
                fg_rationale = f"Extreme greed (FG={fg}) → contrarian NO"
            else:
                fg_direction = "neutral"
                fg_conf = 0.3
                fg_rationale = f"FG={fg} neutral zone"

            proposals.append(
                AgentProposal(
                    agent_id="fg_contrarian_agent",
                    asset=self.config.asset,
                    timeframe=self.config.timeframe,
                    direction=fg_direction,
                    probability=0.5 + (fg_conf - 0.3) * 0.5,
                    confidence=fg_conf,
                    size_preference="small" if fg_direction == "neutral" else "base",
                    rationale=fg_rationale,
                    edge_estimate=fg_conf * 3.0,
                    timestamp=datetime.now(timezone.utc),
                    agent_archetype="contrarian",
                    mode="LIVE" if self.lane_live else "SIM",
                )
            )

            # Submit all proposals and get consensus
            for proposal in proposals:
                self._consensus_agg.submit_proposal(proposal)

            consensus_view = self._consensus_agg.get_consensus(self.config.asset, self.config.timeframe)

            if consensus_view is None:
                logger.info(
                    "CONSENSUS_STATUS=FORMING have=%d required=%d "
                    "sources=%s modes=%s — skip_size_and_execute",
                    len(proposals),
                    self._consensus_agg.min_agents,
                    [p.agent_id for p in proposals],
                    [p.mode for p in proposals],
                )
                return {"status": "forming", "direction": "neutral"}

            return {
                "status": consensus_view.status.value,
                "direction": consensus_view.consensus_direction,
                "probability": consensus_view.consensus_probability,
                "confidence": consensus_view.consensus_confidence,
                "size_band": consensus_view.size_band,
                "disagreement": len(consensus_view.disagreement_flags),
                "agent_count": consensus_view.total_agents,
                "rationale": consensus_view.size_rationale,
            }

        except Exception as exc:
            logger.error("_run_swarm failed: %s", exc)
            return {"status": "error", "direction": "neutral", "error": str(exc)}

    # ------------------------------------------------------------------
    # Step 4 — Risk evaluation
    # ------------------------------------------------------------------

    async def _evaluate_risk(
        self,
        consensus: Dict[str, Any],
        sentiment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run the full risk stack:
          1. BTCSentimentRiskDial — regime-based caps (clamped to phase ceiling)
          2. CryptoSwarmRiskBTC15m — per-trade / daily / exposure guardrails

        Phase caps from PromotionEngine are the hard ceiling; sentiment/Markov
        dial can only tighten within those bounds.

        Returns a dict with blocked flag, approved size, and full reasoning.
        """
        try:
            from merid.risk.crypto_swarm_risk_btc15m import TradeProposal as RiskProposal
            from merid.sentiment.btc_risk_dial import FGState, fg_clamps, vol_fg_position_size
            from merid.risk.promotion_engine import PerfState, dynamic_size

            # --- Multi-TF drawdown guard (checked first — hard block) ---
            dd_guard_ok = True
            dd_guard_reason = "ok"
            if self._dd_guard is not None:
                dd_guard_ok, dd_guard_reason = self._dd_guard.can_trade(self._dd_key)
            if not dd_guard_ok:
                return {
                    "blocked": True,
                    "reason": f"dd_guard: {dd_guard_reason}",
                    "approved_size": 0.0,
                }

            # --- Loss streak circuit breaker ---
            streak_mult = 1.0
            if self._loss_streak is not None:
                if self._loss_streak.should_pause_trading():
                    return {
                        "blocked": True,
                        "reason": f"loss_streak_circuit_breaker: {self._loss_streak.consec_losses} consecutive losses",
                        "approved_size": 0.0,
                        "consec_losses": self._loss_streak.consec_losses,
                    }
                streak_mult = self._loss_streak.get_size_multiplier()

            # Refresh dial — cheap, no I/O, ensures current regime
            self._risk_dial.update()

            # --- Dial check ---
            can_trade, dial_reason = self._risk_dial.can_trade(bar_count=0)
            if not can_trade:
                return {
                    "blocked": True,
                    "reason": f"risk_dial_blocked: {dial_reason}",
                    "approved_size": 0.0,
                }

            # Pull phase-aware caps: (per_trade_$, max_exposure_$, max_open_trades)
            pt_cap, max_exp, max_trades = self._risk_dial.get_caps()

            # --- FG clamps (additional ceiling on top of phase caps) ---
            fg_val = sentiment.get("fg_index", 50)
            fg_combined = sentiment.get("combined_smoothed", 0.0)
            fg_conf = sentiment.get("confidence", 0.5)
            fg_synthetic = sentiment.get("fg_is_synthetic", False)
            fg = FGState(
                value=int(fg_val),
                combined=fg_combined,
                confidence=fg_conf,
                is_synthetic=fg_synthetic,
            )
            from merid.sentiment.btc_risk_dial import fg_clamp_breakdown
            fg_breakdown = fg_clamp_breakdown(self.config.equity, fg)
            fg_caps = fg_breakdown  # fg_clamp_breakdown is a superset of fg_clamps

            # KalshiFGFilter directional block (side = consensus direction)
            if fg_breakdown.get("fg_filter_blocked") and consensus.get("direction") == "yes":
                return {
                    "blocked": True,
                    "reason": f"fg_filter: {fg_breakdown.get('fg_filter_reason', '?')}",
                    "approved_size": 0.0,
                    "fg_regime": fg_breakdown.get("fg_regime"),
                    "fg_value": fg_val,
                    "fg_is_synthetic": fg_synthetic,
                }

            # Take the tighter of phase cap and FG cap
            effective_pt_cap = min(pt_cap, fg_caps["per_trade_cap"])
            effective_book_cap = min(max_exp, fg_caps["max_book_cap"])

            # --- Volatility-adjusted sizing (when real price history available) ---
            # Uses strike_price history collected each cycle — not sentiment floats.
            # Falls back to dynamic_size when insufficient price history.
            vol_size: Optional[float] = None
            atr_value: float = 0.0
            if len(self._price_history) >= 15:
                from merid.sentiment.btc_risk_dial import atr as _atr
                _closes = self._price_history[-20:]
                _highs  = [c * 1.005 for c in _closes]
                _lows   = [c * 0.995 for c in _closes]
                atr_value = _atr(_highs, _lows, _closes, period=14)
                if atr_value > 0:
                    stop_dollars = max(atr_value * self.config.equity, 0.01)
                    vol_size = vol_fg_position_size(
                        equity=self.config.equity,
                        stop_dollars=stop_dollars,
                        atr_value=atr_value,
                        fg=fg,
                    )

            # --- ATRMonitor: update regime + fire alert on regime flip ---
            atr_regime = "unknown"
            if self._atr_monitor is not None and atr_value > 0:
                self._atr_monitor.update(atr_value)
                atr_regime = self._atr_monitor.regime()
                alert = self._atr_monitor.alert_needed()
                if alert:
                    logger.warning(
                        "BTC15MLane ATR REGIME FLIP: %s | atr=%.4f | %s",
                        alert, atr_value, self._atr_monitor.get_status(),
                    )
                    # Fire webhook alert (non-blocking; never raises)
                    try:
                        import asyncio
                        from merid.alerts.webhook_client import send_atr_alert
                        asyncio.create_task(send_atr_alert(
                            regime=alert,
                            atr_value=atr_value,
                            asset=self.config.asset,
                            timeframe=self.config.timeframe,
                        ))
                    except Exception as _e:
                        logger.debug("atr_alert: %s", _e)

            # --- Lifecycle risk profile (BACKTEST/FORWARD_PAPER=0%, RESTRICTED=1%, NORMAL=2%) ---
            lifecycle_frac = 0.02  # default
            if self._lifecycle is not None:
                lifecycle_frac = self._lifecycle.get_risk_profile().get("risk_frac", 0.02)

            # --- MC-adjusted risk fraction (applied before drawdown guard) ---
            mc_frac = lifecycle_frac
            if self._mc_metrics is not None:
                from merid.backtesting.monte_carlo import mc_adjust_risk_frac
                mc_frac = mc_adjust_risk_frac(
                    base_frac=lifecycle_frac,
                    mc_metrics=self._mc_metrics,
                )

            # --- Drawdown guard (tighter steps: 10%→25%, 7%→50%, 5%→75%) ---
            from merid.risk.promotion_engine import drawdown_guarded_risk_frac
            dd_frac = drawdown_guarded_risk_frac(
                equity=self.config.equity,
                peak_equity=self._peak_equity,
                base_frac=mc_frac,
            )
            # Final effective base: tightest of lifecycle → MC-adjusted → DD-guarded
            effective_base_frac = min(mc_frac, dd_frac)

            # --- Dynamic size (drawdown steps + consec-loss reduction + compounding) ---
            current_dd = self._max_drawdown
            perf_state = PerfState(
                equity=self.config.equity,
                initial_equity=self._initial_equity,
                drawdown=current_dd,
                consec_losses=self._consec_losses,
            )
            dyn_size = dynamic_size(perf_state, base_risk_frac=effective_base_frac)

            # Prefer vol-adjusted size when available; fall back to dynamic_size
            base_size = vol_size if vol_size is not None else dyn_size

            # Apply streak multiplier (0.5 at 3 losses, 1.0 otherwise)
            base_size *= streak_mult

            # --- Fractional Kelly with volatility tax (quarter-Kelly, capped at 5%) ---
            kelly_size: Optional[float] = None
            vol_tax: float = 1.0
            sigma: float = 0.0
            yes_price_cents = int(consensus.get("probability", 0.5) * 100)
            est_prob = consensus.get("probability", 0.5)
            if 0 < yes_price_cents < 100 and 0 < est_prob < 1:
                # Compute realised sigma from recent sentiment/price history
                if len(self._sentiment_history) >= 5:
                    hist = self._sentiment_history[-20:]
                    mean_h = sum(hist) / len(hist)
                    variance_h = sum((v - mean_h) ** 2 for v in hist) / len(hist)
                    sigma = math.sqrt(variance_h) if variance_h > 0 else 0.0

                from merid.sentiment.btc_risk_dial import kelly_with_vol_tax, volatility_tax_factor
                vol_tax = volatility_tax_factor(sigma)
                kelly_size = kelly_with_vol_tax(
                    equity=self.config.equity,
                    yes_price_cents=yes_price_cents,
                    est_prob=est_prob,
                    base_frac=0.25,
                    sigma=sigma,
                )
                # Take the minimum of dynamic/vol size and Kelly size
                if kelly_size > 0:
                    base_size = min(base_size, kelly_size)

            # --- Kalman sentiment nudge (±20%) applied last ---
            raw_sent = sentiment.get("combined_raw", sentiment.get("combined_smoothed", 0.0))
            kf_mult = 1.0
            if raw_sent != 0.0:
                from merid.sentiment.kalman_sentiment import kf_sentiment_adjust
                kf_adjusted = kf_sentiment_adjust(
                    risk_dollars=base_size,
                    raw_sentiment=raw_sent,
                    kalman=self._kalman,
                )
                kf_mult = kf_adjusted / max(base_size, 1e-9)
                base_size = kf_adjusted

            # Final base size: clamped to effective phase+FG ceiling, floored at config min
            raw_size = max(self.config.base_trade_size, min(base_size, effective_pt_cap))
            scaled_size = self._risk_dial.scale_position_size(raw_size)

            # Hard-clamp to effective ceiling (defence-in-depth)
            scaled_size = min(scaled_size, effective_pt_cap)

            # --- CryptoSwarmRiskBTC15m ---
            proposal = RiskProposal(
                asset=self.config.asset,
                timeframe=self.config.timeframe,
                side=consensus.get("direction", "yes"),
                price_cents=int(consensus.get("probability", 0.5) * 100),
                intent_risk=scaled_size,
                fear_greed=sentiment.get("fg_index"),
                tags=["btc15m_lane"],
            )

            decision = self._risk_manager.evaluate_proposal(proposal)

            blocked = decision.mode.value == "blocked"
            # Final size: clamped to effective (phase ∩ FG) ceiling
            final_size = min(decision.final_size, effective_pt_cap)

            return {
                "blocked": blocked,
                "mode": decision.mode.value,
                "approved_size": final_size,
                "reason": decision.reason,
                "adjustments": decision.adjustments,
                "dial_scale": self._risk_dial.config.get_scale_factor(),
                "phase": self._promotion_engine.current_phase.name if self._promotion_engine else "?",
                "lifecycle_state": self._lifecycle.state.name if self._lifecycle else "?",
                "lifecycle_frac": lifecycle_frac,
                "mc_frac": mc_frac,
                "dd_frac": dd_frac,
                "effective_base_frac": effective_base_frac,
                "atr_regime": atr_regime,
                "phase_per_trade_cap": pt_cap,
                "phase_max_exposure": max_exp,
                "phase_max_trades": max_trades,
                "fg_per_trade_cap": fg_caps["per_trade_cap"],
                "fg_book_cap": fg_caps["max_book_cap"],
                "fg_extreme": fg_caps["extreme"],
                "fg_conf_mult": fg_caps["conf_mult"],
                "fg_regime": fg_breakdown.get("fg_regime"),
                "fg_rules_fired": fg_breakdown.get("rules_fired", []),
                "fg_sizing_mult": fg_breakdown.get("sizing_multiplier"),
                "fg_filter_blocked": fg_breakdown.get("fg_filter_blocked", False),
                "fg_filter_reason": fg_breakdown.get("fg_filter_reason"),
                "fg_is_synthetic": fg_synthetic,
                "effective_pt_cap": effective_pt_cap,
                "effective_book_cap": effective_book_cap,
                "vol_size": vol_size,
                "atr_value": atr_value,
                "dynamic_size": dyn_size,
                "kelly_size": kelly_size,
                "kelly_sigma": sigma,
                "kelly_vol_tax": vol_tax,
                "kf_mult": kf_mult,
                "streak_mult": streak_mult,
                "consec_losses": self._consec_losses,
                "drawdown": current_dd,
                "dd_guard_reason": dd_guard_reason,
            }

        except Exception as exc:
            logger.error("_evaluate_risk failed: %s", exc)
            return {
                "blocked": True,
                "reason": f"risk_evaluation_error: {exc}",
                "approved_size": 0.0,
            }

    # ------------------------------------------------------------------
    # Step 5 — Execute
    # ------------------------------------------------------------------

    async def _execute(
        self,
        markets: List[Dict[str, Any]],
        consensus: Dict[str, Any],
        risk_decision: Dict[str, Any],
        cycle_id: str,
    ) -> Dict[str, Any]:
        """
        Submit order via KalshiExecutor with a two-layer mode guard:

          Layer 1 — Lane live flag (per-lane promotion):
              lane_live=False → always paper, regardless of system mode.
              lane_live=True  → defer to system TradeMode.

          Layer 2 — System TradeMode (global kill):
              Must be LIVE for any real order to leave this process.

        Size ceiling is the phase per-trade cap (no hardcoded constant).
        """
        # Phase per-trade cap is the final size ceiling
        pt_cap = risk_decision.get("effective_pt_cap", risk_decision.get("phase_per_trade_cap", float("inf")))
        approved_size = min(risk_decision.get("approved_size", 0.0), pt_cap)
        direction = consensus.get("direction", "yes")

        if risk_decision.get("blocked"):
            # Fire Telegram alert for risk-blocked cycles
            try:
                import asyncio
                from merid.alerts.webhook_client import tg_send
                asyncio.create_task(tg_send(
                    f"⚠️ [Kalshi BTC15m] RISK BLOCKED: {risk_decision.get('reason', '?')} "
                    f"| phase={risk_decision.get('phase', '?')} "
                    f"| lifecycle={risk_decision.get('lifecycle_state', '?')}"
                ))
            except Exception as _e:
                logger.debug("tg_risk_blocked: %s", _e)
            return {"submitted": False, "reason": risk_decision.get("reason", "risk_blocked")}

        if approved_size <= 0:
            logger.info("[%s] Approved size=0, skipping order submission", cycle_id)
            return {"submitted": False, "reason": "zero_size"}

        target_market = markets[0] if markets else None
        if target_market is None:
            return {"submitted": False, "reason": "no_target_market"}

        market_id = target_market.get("ticker") or target_market.get("market_id", "")

        # --- Determine effective mode (three-layer guard) ---
        # Layer 0: lifecycle state machine (BACKTEST/FORWARD_PAPER → always paper)
        if self._lifecycle is not None and self._lifecycle.is_paper():
            effective_mode = "paper"
        # Layer 1: per-lane live flag
        elif not self.lane_live or self.config.paper_mode:
            effective_mode = "paper"
        else:
            # Layer 2: system TradeMode global kill switch
            try:
                from merid.trading.trade_mode import get_trade_mode, TradeMode
                effective_mode = "live" if get_trade_mode() == TradeMode.LIVE else "paper"
            except Exception as _tm_exc:
                logger.debug("get_trade_mode failed, defaulting to paper: %s", _tm_exc)
                effective_mode = "paper"

        # --- Structured ORDER log: full risk inputs for every order attempt ---
        logger.info(
            "[%s] ORDER | lane=%s mode=%s lane_live=%s | "
            "market=%s side=%s size=%.3f price=%.3f | "
            "equity=%.2f dd=%.1f%% consec_losses=%d | "
            "phase=%s lifecycle=%s | "
            "fg=%s atr_regime=%s atr=%.4f | "
            "kelly=%.4f kelly_sigma=%.4f vol_tax=%.2f | "
            "kf_mult=%.2f mc_frac=%.4f dd_frac=%.4f | "
            "effective_base_frac=%.4f effective_pt_cap=%.4f | "
            "clamp_winner=%s | reason=%s",
            cycle_id,
            f"{self.config.asset}:{self.config.timeframe}",
            effective_mode,
            self.lane_live,
            market_id,
            direction,
            approved_size,
            consensus.get("probability", 0.5),
            self.config.equity,
            self._max_drawdown * 100,
            self._consec_losses,
            risk_decision.get("phase", "?"),
            risk_decision.get("lifecycle_state", "?"),
            risk_decision.get("fg_per_trade_cap", "?"),
            risk_decision.get("atr_regime", "?"),
            risk_decision.get("atr_value", 0.0),
            risk_decision.get("kelly_size") or 0.0,
            risk_decision.get("kelly_sigma", 0.0),
            risk_decision.get("kelly_vol_tax", 1.0),
            risk_decision.get("kf_mult", 1.0),
            risk_decision.get("mc_frac", 0.0),
            risk_decision.get("dd_frac", 0.0),
            risk_decision.get("effective_base_frac", 0.0),
            risk_decision.get("effective_pt_cap", 0.0),
            _clamp_winner(risk_decision),
            risk_decision.get("reason", ""),
        )

        # --- Paper path ---
        if effective_mode == "paper":
            # Simulate PnL using proper Kalshi binary payoff:
            #   YES bet: win  → +approved_size * (1 - price) / price  (net of cost)
            #            lose → -approved_size
            #   NO  bet: win  → +approved_size * price / (1 - price)
            #            lose → -approved_size
            # We use consensus probability as the win probability and draw a
            # Bernoulli outcome so the paper equity curve is realistic.
            import random as _rng
            prob = consensus.get("probability", 0.5)
            price = max(0.01, min(0.99, prob))  # treat prob as market price
            won = _rng.random() < prob
            if direction == "yes":
                simulated_pnl = approved_size * (1.0 - price) / price if won else -approved_size
            else:
                simulated_pnl = approved_size * price / (1.0 - price) if won else -approved_size
            self._compound_equity(simulated_pnl)
            # Feed PnL into CryptoSwarmRiskBTC15m daily tracker
            if self._risk_manager is not None:
                try:
                    from merid.risk.crypto_swarm_risk_btc15m import TradeMode as _TM
                    self._risk_manager.record_trade_result(
                        ticker=market_id,
                        realized_pnl=simulated_pnl,
                        mode=_TM.PAPER,
                    )
                except Exception as _e:
                    logger.debug("record_trade_result_paper: %s", _e)
            self._metrics.record_order(mode="paper", size=approved_size)
            return {
                "submitted": True,
                "simulated": True,
                "mode": "paper",
                "market_id": market_id,
                "side": direction,
                "size": approved_size,
                "simulated_pnl": simulated_pnl,
                "cycle_id": cycle_id,
            }

        # --- Live path ---

        if self._executor is None:
            logger.error("[%s] Live mode but executor unavailable", cycle_id)
            return {"submitted": False, "reason": "executor_unavailable"}

        try:
            limit_price = consensus.get("probability", 0.5)
            price_dollars = max(limit_price, 0.01)
            contracts = max(1, int(approved_size / price_dollars))

            order_result = await self._executor.execute_trade(
                symbol=market_id,
                side="buy",
                amount=contracts,
                order_type="limit",
                price=limit_price,
                metadata={"outcome": direction, "cycle_id": cycle_id},
            )
            # Live PnL is recorded when fill arrives via order_manager callback;
            # call _compound_equity(0) here to keep trade counter in sync
            self._compound_equity(0.0)
            self._metrics.record_order(mode="live", size=approved_size)

            # Telegram alert for live fills
            try:
                import asyncio
                from merid.alerts.webhook_client import tg_send
                asyncio.create_task(tg_send(
                    f"🟢 [Kalshi BTC15m] {direction.upper()} {contracts}x {market_id} "
                    f"@ {limit_price:.2f} size=${approved_size:.2f} "
                    f"| phase={risk_decision.get('phase', '?')} "
                    f"| equity=${self.config.equity:.2f}"
                ))
            except Exception as _e:
                logger.debug("tg_order_submitted: %s", _e)

            return {
                "submitted": True,
                "simulated": False,
                "mode": "live",
                "market_id": market_id,
                "side": direction,
                "size": approved_size,
                "contracts": contracts,
                "limit_price": limit_price,
                "order_result": order_result,
                "cycle_id": cycle_id,
            }
        except Exception as exc:
            logger.error("[%s] Order submission failed: %s", cycle_id, exc)
            self._metrics.record_order(mode=effective_mode, size=approved_size, approved=False)
            self._metrics.record_api_error("kalshi_place_order")
            # Telegram alert for submission failures
            try:
                import asyncio
                from merid.alerts.webhook_client import tg_send
                asyncio.create_task(tg_send(
                    f"🔴 [Kalshi BTC15m] ORDER FAILED: {exc} "
                    f"| {direction.upper()} {market_id} size=${approved_size:.2f}"
                ))
            except Exception as _e:
                logger.debug("tg_order_failed: %s", _e)
            return {"submitted": False, "reason": str(exc), "cycle_id": cycle_id}

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _effective_mode_str(self) -> str:
        """Return 'live' or 'paper' — the mode that _execute() would use right now."""
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                return "paper"  # kill switch overrides everything
        except Exception as _e:
            logger.debug("kill_switch_check: %s", _e)
        if self._lifecycle is not None and self._lifecycle.is_paper():
            return "paper"
        if not self.lane_live or self.config.paper_mode:
            return "paper"
        try:
            from merid.trading.trade_mode import get_trade_mode, TradeMode
            return "live" if get_trade_mode() == TradeMode.LIVE else "paper"
        except Exception as _e:
            logger.debug("get_trade_mode: %s", _e)
            return "paper"

    def _kill_switch_active(self) -> bool:
        try:
            from merid.risk.kill_switches import risk_controller
            return not risk_controller.can_trade()
        except Exception as _e:
            logger.debug("kill_switch_active: %s", _e)
            return False

    def _system_trade_mode_str(self) -> str:
        try:
            from merid.trading.trade_mode import get_trade_mode
            return get_trade_mode().value
        except Exception as _e:
            logger.debug("system_trade_mode_str: %s", _e)
            return "unknown"

    def _log_cycle_summary(self, result: LaneCycleResult, elapsed_ms: float) -> None:
        status = "BLOCKED" if result.blocked_reason else ("ERROR" if result.error else "OK")
        phase = self._promotion_engine.current_phase.name if self._promotion_engine else "?"
        logger.info(
            "BTC15MLane cycle %s | status=%s | phase=%s lane_live=%s | "
            "markets=%d | equity=%.2f | latency=%.0fms | %s",
            result.cycle_id,
            status,
            phase,
            self.lane_live,
            result.markets_found,
            self.config.equity,
            elapsed_ms,
            result.blocked_reason or result.error or "executed",
        )

    def get_status(self) -> Dict[str, Any]:
        """Return current lane status for UI / health checks."""
        phase = self._promotion_engine.current_phase if self._promotion_engine else None
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "lane_live": self.lane_live,
            "paper_mode": self.config.paper_mode,
            "asset": self.config.asset,
            "timeframe": self.config.timeframe,
            "equity": self.config.equity,
            "initial_equity": self._initial_equity,
            "realised_pnl": self._realised_pnl,
            "max_drawdown": round(self._max_drawdown, 4),
            "completed_trades": self._completed_trades,
            "consec_losses": self._consec_losses,
            "phase": phase.name if phase else None,
            "unlocked_timeframes": list(phase.unlocked_timeframes) if phase else [],
            "unlocked_assets": list(phase.unlocked_assets) if phase else [],
            "allow_live": phase.allow_live if phase else False,
            "backtest_eligibility": (
                {
                    "allow_live": self._backtest_eligibility.allow_live,
                    "reason": self._backtest_eligibility.reason,
                }
                if self._backtest_eligibility else None
            ),
            "backtest_report": (
                {
                    "sharpe": self._backtest_report.sharpe,
                    "max_drawdown": self._backtest_report.max_drawdown,
                    "trades": self._backtest_report.trades,
                    "years": self._backtest_report.years,
                }
                if self._backtest_report else None
            ),
            "loss_streak": self._loss_streak.get_status() if self._loss_streak else None,
            "lifecycle": self._lifecycle.get_status() if self._lifecycle else None,
            "forward_tracker": (
                self._forward_tracker.get_stats().__dict__
                if self._forward_tracker else None
            ),
            "atr_monitor": self._atr_monitor.get_status() if self._atr_monitor else None,
            "kalman": self._kalman.get_status() if self._kalman else None,
            "dd_guard": self._dd_guard.get_status() if self._dd_guard else None,
            "dd_key": self._dd_key,
            "mc_metrics": self._mc_metrics,
            "promotion_engine": self._promotion_engine.get_status() if self._promotion_engine else None,
            "risk_dial": self._risk_dial.get_status() if self._risk_dial else None,
            "cached_sentiment": self._cached_sentiment,
            "metrics": self._metrics.to_dict(),
            # Unambiguous mode fields for UI — never guess from flags
            "effective_mode": self._effective_mode_str(),
            "kill_switch_active": self._kill_switch_active(),
            "trade_mode": self._system_trade_mode_str(),
            # Sentiment staleness
            "sentiment_age_seconds": (
                time.monotonic() - self._last_sentiment_refresh
                if self._last_sentiment_refresh > 0 else None
            ),
            "sentiment_stale": (
                (time.monotonic() - self._last_sentiment_refresh)
                > self.config.sentiment_refresh_seconds * 2
                if self._last_sentiment_refresh > 0 else True
            ),
            "fg_is_synthetic": (
                self._cached_sentiment.get("fg_is_synthetic", False)
                if self._cached_sentiment else None
            ),
        }


# ---------------------------------------------------------------------------
# Convenience entry-point
# ---------------------------------------------------------------------------

async def run_btc15m_lane(config: Optional[BTC15MLaneConfig] = None) -> None:
    """Run the BTC 15m lane until cancelled."""
    lane = BTC15MLane(config)
    await lane.start()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_btc15m_lane: Optional[BTC15MLane] = None


def get_btc15m_lane(config: Optional[BTC15MLaneConfig] = None) -> BTC15MLane:
    """Get (or create) the singleton BTC 15m lane."""
    global _btc15m_lane
    if _btc15m_lane is None:
        _btc15m_lane = BTC15MLane(config)
    return _btc15m_lane


# ---------------------------------------------------------------------------
# LaneOrchestrator — spins additional lanes when promotion phase unlocks them
# ---------------------------------------------------------------------------

class LaneOrchestrator:
    """
    Manages a fleet of BTC15MLane instances across all supported assets and
    timeframes (BTC, ETH, SOL, XRP, DOGE × 15m, 1h, 4h, 1d).

    The primary lane (BTC 15m) starts immediately in paper mode.
    Additional lanes are spawned as background tasks only when the shared
    PromotionEngine advances to a phase that unlocks them per
    LANE_UNLOCK_REQUIREMENTS.

    Each spawned lane starts in paper mode; per-lane live promotion is
    independent and handled inside BTC15MLane._maybe_enable_live().
    """

    # Maps (asset, timeframe) → minimum phase name required to spawn.
    # Source of truth: SUPPORTED_ASSETS × SUPPORTED_TIMEFRAMES in btc_promotion_config.
    # PHASE_0: BTC 15m only (paper, always available)
    # PHASE_1: BTC adds 1h; no new assets
    # PHASE_2: ETH and BTC 4h unlock
    # PHASE_3: SOL, XRP, DOGE unlock across all timeframes; BTC/ETH gain 1d
    LANE_UNLOCK_REQUIREMENTS: Dict[Tuple[str, str], str] = {
        # ── BTC ──────────────────────────────────────────────────────
        ("BTC", "15m"):  "PHASE_0",   # always available
        ("BTC", "1h"):   "PHASE_1",
        ("BTC", "4h"):   "PHASE_2",
        ("BTC", "1d"):   "PHASE_3",
        # ── ETH ──────────────────────────────────────────────────────
        ("ETH", "15m"):  "PHASE_2",
        ("ETH", "1h"):   "PHASE_2",
        ("ETH", "4h"):   "PHASE_3",
        ("ETH", "1d"):   "PHASE_3",
        # ── SOL ──────────────────────────────────────────────────────
        ("SOL", "15m"):  "PHASE_3",
        ("SOL", "1h"):   "PHASE_3",
        ("SOL", "4h"):   "PHASE_3",
        ("SOL", "1d"):   "PHASE_3",
        # ── XRP ──────────────────────────────────────────────────────
        ("XRP", "15m"):  "PHASE_3",
        ("XRP", "1h"):   "PHASE_3",
        ("XRP", "4h"):   "PHASE_3",
        ("XRP", "1d"):   "PHASE_3",
        # ── DOGE ─────────────────────────────────────────────────────
        ("DOGE", "15m"): "PHASE_3",
        ("DOGE", "1h"):  "PHASE_3",
        ("DOGE", "4h"):  "PHASE_3",
        ("DOGE", "1d"):  "PHASE_3",
    }

    def __init__(self, base_equity: float = 0.0) -> None:
        self.base_equity = base_equity
        self._lanes: Dict[str, BTC15MLane] = {}          # "BTC:15m" → lane
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the primary lane and the phase-monitor loop."""
        if self._running:
            return
        self._running = True

        # Always start BTC 15m immediately
        await self._ensure_lane("BTC", "15m")

        # Background monitor checks for new phase unlocks every 5 minutes
        self._monitor_task = asyncio.create_task(
            self._phase_monitor_loop(), name="lane-orchestrator-monitor"
        )
        logger.info("LaneOrchestrator started (primary: BTC 15m)")

    async def stop(self) -> None:
        """Stop all lanes and the monitor."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        for key, task in list(self._tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            lane = self._lanes.get(key)
            if lane:
                lane.stop()

        self._tasks.clear()
        self._lanes.clear()
        logger.info("LaneOrchestrator stopped")

    def get_all_status(self) -> Dict[str, Any]:
        return {
            key: lane.get_status()
            for key, lane in self._lanes.items()
        }

    # ── Internal ──────────────────────────────────────────────────────────

    async def _phase_monitor_loop(self) -> None:
        """Periodically check if new lanes should be spawned."""
        from merid.risk.promotion_engine import get_promotion_engine
        from merid.risk.btc_promotion_config import PHASE_BY_NAME

        while self._running:
            try:
                engine = get_promotion_engine()
                current_phase = engine.current_phase.name

                for (asset, tf), required_phase in self.LANE_UNLOCK_REQUIREMENTS.items():
                    key = f"{asset}:{tf}"
                    if key in self._lanes:
                        continue  # already running

                    # Check if current phase >= required phase (by index in PHASES)
                    from merid.risk.btc_promotion_config import PHASES
                    current_idx = next(
                        (i for i, p in enumerate(PHASES) if p.name == current_phase), 0
                    )
                    required_idx = next(
                        (i for i, p in enumerate(PHASES) if p.name == required_phase), 999
                    )
                    if current_idx >= required_idx:
                        logger.info(
                            "LaneOrchestrator: phase %s unlocks %s %s — spawning lane",
                            current_phase, asset, tf,
                        )
                        await self._ensure_lane(asset, tf)

            except Exception as exc:
                logger.warning("LaneOrchestrator monitor error: %s", exc)

            await asyncio.sleep(300)  # check every 5 minutes

    async def _ensure_lane(self, asset: str, timeframe: str) -> None:
        """Spawn a lane for (asset, timeframe) if not already running."""
        key = f"{asset}:{timeframe}"
        if key in self._lanes:
            return

        config = BTC15MLaneConfig(
            asset=asset,
            timeframe=timeframe,
            equity=self.base_equity,
            paper_mode=True,  # always start new lanes in paper
        )
        lane = BTC15MLane(config)
        self._lanes[key] = lane

        task = asyncio.create_task(lane.start(), name=f"lane-{key}")
        self._tasks[key] = task
        logger.info("LaneOrchestrator: spawned lane %s", key)


# ---------------------------------------------------------------------------
# LaneOrchestrator singleton
# ---------------------------------------------------------------------------

_lane_orchestrator: Optional[LaneOrchestrator] = None


def get_lane_orchestrator(base_equity: float = 0.0) -> LaneOrchestrator:
    """Get (or create) the singleton LaneOrchestrator."""
    global _lane_orchestrator
    if _lane_orchestrator is None:
        _lane_orchestrator = LaneOrchestrator(base_equity=base_equity)
    return _lane_orchestrator
