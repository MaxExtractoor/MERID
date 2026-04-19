"""§3 MERID Main Loop — persistent async orchestrator.

Drives the full swarm cycle on a configurable cadence:

  1. Refresh features (news/macro/onchain/social) with decay
  2. Run agent cycles per domain
  3. Run consensus aggregation (decay-aware)
  4. Run arb/dislocation scans
  5. Generate plans → risk checks → pass to execution
  6. Update CQI / drift metrics
  7. Reconcile positions with venues
  8. Push events to subscribers

Usage:
    # Run the loop
    python -m merid.loop

    # Test one iteration
    from merid.loop import MeridLoop
    loop = MeridLoop()
    await loop.tick()
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

import uuid as _uuid
from utils.logger import get_logger, set_task_context

logger = get_logger("merid.loop")

# Per-step “slow action” warning threshold (ms). Tune via MERID_LOOP_SLOW_ACTION_BUDGET_MS.
_SLOW_ACTION_BUDGET_MS = float(os.getenv("MERID_LOOP_SLOW_ACTION_BUDGET_MS", "1000"))  # Increased from 250ms — CPU-bound work (arb_scan, features, consensus) legitimately takes 800-1500ms with 32 workers

# Dedicated thread pool for CPU-heavy operations — avoids saturating default executor
_loop_executor: Optional[ThreadPoolExecutor] = None

def _get_loop_executor() -> ThreadPoolExecutor:
    """Get or create the dedicated loop executor with 32 workers."""
    global _loop_executor
    if _loop_executor is None or _loop_executor._shutdown:
        # 32 workers allows 35 agents to run concurrently without queue buildup
        _loop_executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="merid_loop")
    return _loop_executor


def _resolve_plan_adapter_venue(plan: Any, plan_domain: str) -> str:
    """Pick the external adapter venue for a TradePlan.

    Avoids cross-routing when both Kalshi and Alpaca adapters are registered
    (``KALSHI_ONLY=false``): prediction/betting must not fall through to the
    legacy ``alpaca`` default, and venue exposure caps must match execution.

    Kalshi crypto event tickers (KXBTC*, etc.) map to **kalshi** for execution
    even when ``plan.domain`` is ``crypto`` — spot venues are for context only.
    """
    v = getattr(plan, "venue", None)
    if v:
        return str(v).lower()
    sym = getattr(plan, "symbol", None)
    if sym:
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset

            if kalshi_ticker_to_asset(str(sym)) is not None:
                return "kalshi"
        except Exception:
            pass
    try:
        from merid.paper_config import get_paper_config

        dc = get_paper_config().domains.get(plan_domain)
        if dc and dc.venues:
            return dc.venues[0]
    except Exception:
        pass
    pd = (plan_domain or "").lower()
    if pd in ("prediction", "betting"):
        return "kalshi"
    if pd == "equity":
        return "alpaca"
    try:
        from merid.settings import settings as _s

        if getattr(_s, "KALSHI_ONLY", True):
            return "kalshi"
    except Exception:
        pass
    return "alpaca"


# ── Configuration ─────────────────────────────────────────────────────

@dataclass
class LoopConfig:
    """Cadence and feature flags for the main loop.

    Prefer constructing via ``LoopConfig.from_paper_config()`` so that
    domains, symbols, cadences, and limits are driven by the single
    config matrix in ``merid.paper_config``.
    """
    # Cadence (seconds)
    feature_refresh_interval: float = 30.0
    agent_cycle_interval: float = 60.0
    consensus_interval: float = 15.0
    arb_scan_interval: float = 60.0  # Increased from 10s to reduce event loop lag (was causing 8000ms+ blocks)
    cqi_interval: float = 300.0
    reconciliation_interval: float = 120.0

    # Feature flags
    enable_execution: bool = False        # Must be explicitly enabled
    enable_arb_execution: bool = False
    enable_reconciliation: bool = True
    enable_notifications: bool = True

    # Domains to run
    active_domains: List[str] = field(default_factory=lambda: ["crypto", "prediction"])
    active_symbols: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])

    # Per-domain mode map (populated by from_paper_config)
    domain_modes: Dict[str, str] = field(default_factory=dict)

    # Reconciliation venues (populated by from_paper_config)
    reconciliation_venues: List[str] = field(default_factory=list)

    @classmethod
    def from_paper_config(cls) -> "LoopConfig":
        """Build LoopConfig from the paper_config matrix.

        This is the preferred constructor — it ensures the loop is
        driven by the single source of truth in merid.paper_config.
        """
        from merid.paper_config import get_paper_config
        pc = get_paper_config()

        # Derive active symbols for feature refresh (short names for macro/signal layer)
        price_symbols = []
        for d in pc.active_domains():
            if d.feed_type == "price":
                for s in d.symbols:
                    # "BTC/USDT" -> "BTC", "AAPL" -> "AAPL"
                    short = s.split("/")[0] if "/" in s else s
                    price_symbols.append(short)

        domain_modes = {d.name: d.mode.value for d in pc.active_domains()}
        # paper_config keeps prediction=PAPER for legacy MeridLoop/matching semantics;
        # Kalshi PM execution is live via AgentGrid + VenueGate. Reflect that in logs
        # when the deployment is Kalshi live so operators are not misled.
        try:
            import os as _os

            from merid.settings import settings as _settings

            if (
                getattr(_settings, "KALSHI_ONLY", False)
                and _os.getenv("KALSHI_ENV", "").strip().lower() == "live"
                and "prediction" in domain_modes
            ):
                domain_modes["prediction"] = "live"
        except Exception:
            pass

        return cls(
            feature_refresh_interval=pc.tick_interval * 6,   # ~30s at 5s tick
            agent_cycle_interval=pc.agent_cycle_interval,
            consensus_interval=pc.consensus_interval,
            arb_scan_interval=pc.arb_scan_interval,
            cqi_interval=pc.cqi_interval,
            reconciliation_interval=pc.reconciliation_interval,
            enable_execution=pc.enable_execution,
            enable_arb_execution=pc.enable_arb_execution,
            enable_reconciliation=pc.enable_reconciliation,
            enable_notifications=pc.enable_notifications,
            active_domains=pc.active_domain_names(),
            active_symbols=sorted(set(price_symbols)),
            domain_modes=domain_modes,
            reconciliation_venues=pc.reconciliation_venues(),
        )


# ── Loop state ────────────────────────────────────────────────────────

@dataclass
class LoopMetrics:
    """Tracks loop performance and health."""
    total_ticks: int = 0
    total_errors: int = 0
    last_tick_at: float = 0.0
    last_tick_duration_ms: float = 0.0
    last_error: str = ""
    features_refreshed: int = 0
    agent_cycles_run: int = 0
    consensus_cycles_run: int = 0
    arb_scans_run: int = 0
    plans_generated: int = 0
    plans_executed: int = 0
    cqi_updates: int = 0
    reconciliations_run: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ticks": self.total_ticks,
            "total_errors": self.total_errors,
            "last_tick_at": self.last_tick_at,
            "last_tick_duration_ms": round(self.last_tick_duration_ms, 1),
            "last_error": self.last_error,
            "features_refreshed": self.features_refreshed,
            "agent_cycles_run": self.agent_cycles_run,
            "consensus_cycles_run": self.consensus_cycles_run,
            "arb_scans_run": self.arb_scans_run,
            "plans_generated": self.plans_generated,
            "plans_executed": self.plans_executed,
            "cqi_updates": self.cqi_updates,
            "reconciliations_run": self.reconciliations_run,
        }


# ── Main Loop ─────────────────────────────────────────────────────────

class MeridLoop:
    """Persistent orchestrator that drives the MERID swarm.

    Each `tick()` runs one full cycle. The `run()` method drives
    ticks continuously on the configured cadence.
    """

    _last_liquidity_refresh: Optional[float] = None  # Liquidity tracking for observability

    def __init__(self, config: Optional[LoopConfig] = None):
        self.config = config or LoopConfig()
        self.metrics = LoopMetrics()
        self._running = False
        self._last_liquidity_refresh = None  # Liquidity tracking for observability
        self._subscribers: Set[Callable] = set()
        self._matching_engines: Dict[str, Any] = {}
        self._agent_errors: Dict[str, int] = {}  # per-agent consecutive error count
        self._agent_bg_task: Optional[asyncio.Task] = None  # background agent cycle task
        self._promo_bg_task: Optional[asyncio.Task] = None  # background promotion sync task

        # Tick overlap protection and per-step timing
        # asyncio.Lock ensures atomic check-and-acquire even if tick() is called
        # from multiple coroutines in the same event loop (e.g. CLI + server).
        self._tick_lock = asyncio.Lock()
        self._tick_in_progress = False  # mirrored for health/status reads (no await needed)
        self._tick_step_timings: Dict[str, float] = {}  # per-step duration tracking

        # Adaptive slow-action tracking: skip steps that were recently slow (BUG-EL fix)
        self._slow_action_last_skip: Dict[str, float] = {}  # step -> timestamp when skipped due to slowness
        self._SLOW_ACTION_COOLDOWN_S = 60.0  # skip slow action for 60s after it exceeds budget

        # Timers for staggered cadences
        self._last_feature_refresh = 0.0
        self._last_agent_cycle = 0.0
        self._last_consensus = 0.0
        self._last_arb_scan = 0.0
        self._last_cqi_update = 0.0
        self._last_reconciliation = 0.0
        self._last_promotion_sync = 0.0
        self._promotion_sync_interval = 300.0  # 5 minutes
        self._last_reflection_cycle = 0.0
        self._reflection_cycle_interval = 300.0  # 5 minutes — run after enough fills accumulate
        self._last_liquidity_refresh = 0.0
        self._liquidity_refresh_interval = 120.0  # 120 seconds — orderbook health sweep (reduced from 60s to cut event-loop lag in half)
        self._last_config_reload = 0.0
        self._config_reload_interval = 300.0  # 5 minutes — hot-reload risk limits / reality assertions
        self._last_order_groups_sync = 0.0
        self._order_groups_sync_interval = 120.0  # 120s — lifecycle state check (increased from 60s to reduce event-loop lag)

        # W6: pre-initialise ws_bridge so _refresh_liquidity can safely reference it
        # before run() is called (e.g. in tests or if tick() is called standalone).
        self._ws_bridge = None

        # Initialize matching engines for domains that have them configured
        try:
            from merid.matching_engine import init_matching_engines
            self._matching_engines = init_matching_engines()
            if self._matching_engines:
                logger.info(
                    f"Matching engines active: {list(self._matching_engines.keys())}"
                )
        except Exception as e:
            logger.warning(f"Matching engine init skipped: {e}")

    # ── Lazy service accessors ────────────────────────────────────────

    def _feature_service(self):
        from merid.signals.features import get_feature_service
        return get_feature_service()

    def _scanner(self):
        from merid.signals.arbitrage import get_dislocation_scanner
        return get_dislocation_scanner()

    def _drift_detector(self):
        from merid.signals.drift import get_drift_detector
        return get_drift_detector()

    def _signal_store(self):
        from merid.signals.store import get_signal_store
        return get_signal_store()

    def _consensus_coordinator(self):
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator
        return EnhancedConsensusCoordinator.get_instance()

    def _risk_manager(self):
        from merid.pipeline.risk_manager import get_global_risk_manager
        return get_global_risk_manager()

    def _agent_registry(self):
        from merid.agents.base import get_canonical_registry
        return get_canonical_registry()

    def _execution_guard(self):
        from merid.execution_guard import get_execution_guard
        return get_execution_guard()

    def _risk_context(self):
        from merid.pipeline.risk_context import build_risk_context
        return build_risk_context()

    def _order_group_lifecycle(self):
        if not hasattr(self, '_og_lifecycle'):
            from merid.event_venues.kalshi.order_group_lifecycle import OrderGroupLifecycleManager
            from merid.event_venues.kalshi.client import get_kalshi_client
            self._og_lifecycle = OrderGroupLifecycleManager(get_kalshi_client())
        return self._og_lifecycle

    def _liquidity_monitor(self):
        if not hasattr(self, '_liq_monitor'):
            from merid.event_venues.kalshi.liquidity_monitor import LiquidityMonitor
            self._liq_monitor = LiquidityMonitor()
            # Log a summary of critical alerts (not per-market) to avoid spam
            _liq_alert_count = {"critical": 0, "other": 0}
            def _liq_alert_handler(a):
                if a.severity == "critical":
                    _liq_alert_count["critical"] += 1
                    logger.debug("liquidity_alert %s %s %s: %s", a.severity, a.kind, a.market_id, a.msg)
                else:
                    _liq_alert_count["other"] += 1
            self._liq_monitor.on_alert(_liq_alert_handler)
            self._liq_alert_count = _liq_alert_count
        return self._liq_monitor

    # ── Core tick ─────────────────────────────────────────────────────

    # Maximum acceptable tick duration before we log a warning (ms)
    TICK_DURATION_WARN_MS = float(os.getenv("MERID_LOOP_TICK_DURATION_WARN_MS", "30000"))

    _STEP_TIMEOUT_S = float(os.getenv("MERID_LOOP_STEP_TIMEOUT_S", "5"))  # max seconds per tick step
    # Step-specific timeout overrides (can be customized via env var as JSON)
    _STEP_TIMEOUT_OVERRIDES = json.loads(os.getenv(
        "MERID_LOOP_STEP_TIMEOUT_OVERRIDES",
        '{"features": 30, "agent_cycles": 30, "promotion_sync": 15, "liquidity": 20, "betting": 30, "reconciliation": 10, "arb_scan": 10}'
    ))

    def _should_skip_due_to_slowness(self, step_name: str, now: float) -> bool:
        """Check if a step should be skipped because it was recently slow (BUG-EL fix).

        Returns True if the step exceeded the slow-action budget within the cooldown window.
        This prevents event-loop lag by skipping steps that are known to be slow.
        """
        last_slow = self._slow_action_last_skip.get(step_name)
        if last_slow is None:
            return False
        if now - last_slow < self._SLOW_ACTION_COOLDOWN_S:
            return True
        # Cooldown expired, clear the record
        self._slow_action_last_skip.pop(step_name, None)
        return False

    def _get_event_loop_lag_ms(self) -> float:
        """Get current event-loop lag from monitor.
        
        EVENT-LOOP-FIX: Returns 0 if monitor unavailable, allowing graceful degradation.
        """
        try:
            from merid.diagnostics.loop_lag import get_current_lag_ms
            return get_current_lag_ms()
        except Exception:
            return 0.0

    async def _run_step(self, name: str, coro, summary: Dict) -> None:
        """Execute a single loop step with isolation — errors are logged
        and recorded in the summary but never propagate to crash the tick."""
        timeout = self._STEP_TIMEOUT_OVERRIDES.get(name, self._STEP_TIMEOUT_S)
        step_start = time.perf_counter()
        sub_timings: Dict[str, float] = {}
        
        try:
            # Wrap coro to capture sub-step timing if it supports it
            if hasattr(coro, '__self__') and hasattr(coro.__self__, '_sub_timings'):
                coro.__self__._sub_timings = sub_timings
            
            await asyncio.wait_for(coro, timeout=timeout)
            await asyncio.sleep(0.05)  # yield 50ms to event loop so HTTP stays responsive
        except asyncio.TimeoutError:
            self.metrics.total_errors += 1
            self.metrics.last_error = f"{name}: step timeout ({timeout}s)"
            logger.warning("Loop step '%s' timed out after %ds", name, timeout)
            summary["actions"].append(f"step_timeout:{name}")
        except Exception as exc:
            self.metrics.total_errors += 1
            self.metrics.last_error = f"{name}: {exc}"
            logger.error("Loop step '%s' failed: %s", name, exc, exc_info=True)
            summary["actions"].append(f"step_error:{name}:{exc}")
        finally:
            elapsed_ms = (time.perf_counter() - step_start) * 1000
            self._tick_step_timings[name] = round(elapsed_ms, 1)  # Store for tick summary
            logger.debug("merid.loop.action_ms action=%s ms=%.1f", name, elapsed_ms)
            
            # Log sub-timings if available for slow actions
            if sub_timings and elapsed_ms > 100:
                sub_str = ", ".join(f"{k}={v:.1f}ms" for k, v in sub_timings.items())
                logger.debug("merid.loop.sub_timings action=%s %s", name, sub_str)
            
            # Warn if individual action exceeds budget even if tick passes
            if elapsed_ms > _SLOW_ACTION_BUDGET_MS:
                logger.warning(
                    "Slow action '%s': %.1fms (budget %.0fms)",
                    name, elapsed_ms, _SLOW_ACTION_BUDGET_MS,
                )
                # Track for adaptive skipping (BUG-EL fix)
                self._slow_action_last_skip[name] = time.time()

    async def tick(self, now: Optional[float] = None, force: bool = False) -> Dict[str, Any]:
        """Run one full cycle of the swarm loop.

        Each step is isolated — a failure in one step never prevents
        subsequent steps from running.  Returns a summary dict.

        Args:
            now: Optional timestamp to use (defaults to current time)
            force: If True, run even if another tick is in progress (for tests)
        """
        # Tick overlap protection: skip if another tick is already running.
        # asyncio.Lock.acquire() is non-blocking here — we use try-acquire semantics
        # so a second caller sees the lock taken and returns immediately.
        if not force and self._tick_lock.locked():
            logger.warning("Tick skipped: previous tick still in progress")
            return {"tick": "skipped", "reason": "tick_in_progress", "actions": []}

        async with self._tick_lock:
            self._tick_in_progress = True
            self._tick_step_timings.clear()  # Reset per-step timings
            try:
                return await self._tick_body(now)
            finally:
                self._tick_in_progress = False

    async def _tick_body(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Internal tick implementation - separated for overlap protection."""
        import asyncio
        
        # EVENT-LOOP-FIX: Check for cancellation at start of tick for cooperative shutdown
        if hasattr(asyncio, 'current_task') and asyncio.current_task():
            if asyncio.current_task().cancelled():
                logger.debug("[TICK] Cancelled at start — skipping tick body")
                return {"tick": "cancelled", "actions": []}
        
        now = now or time.time()
        start = time.perf_counter()
        tick_number = self.metrics.total_ticks + 1
        summary: Dict[str, Any] = {"tick": tick_number, "actions": []}

        # BUG-8: set structured log context for this tick so every log line
        # emitted during this task carries tick, mode, and env dimensions.
        try:
            from merid.settings import settings as _ms
            _mode = _ms.MERID_TRADING_MODE
            _env = "demo" if _ms.KALSHI_USE_DEMO else "production"
        except Exception:
            _mode, _env = "unknown", "unknown"
        set_task_context(
            mode=_mode,
            env=_env,
            tick=tick_number,
            correlation_id=f"tick-{tick_number}-{_uuid.uuid4().hex[:8]}",
        )

        # Step 1: Launch background tasks (fire-and-forget, don't block tick)
        if now - self._last_agent_cycle >= self.config.agent_cycle_interval:
            self._last_agent_cycle = now
            if self._agent_bg_task is None or self._agent_bg_task.done():
                # Give background task its own summary — the tick summary is
                # returned/logged before the bg task finishes, so sharing it
                # causes a data-race (stale mutations after return).
                bg_summary: Dict[str, Any] = {"tick": summary["tick"], "actions": []}
                self._agent_bg_task = asyncio.create_task(self._run_agent_cycles_bg(bg_summary))
                summary["actions"].append("agent_cycles:launched")
            else:
                summary["actions"].append("agent_cycles:still_running")

        # Step 2b: Reflection / learning cycle (post-agent-cycle, every 5 min)
        if now - self._last_reflection_cycle >= self._reflection_cycle_interval:
            await self._run_step("reflection", self._run_reflection_cycle(summary), summary)
            self._last_reflection_cycle = now

        # ── Parallel batch: ALL independent steps run concurrently ────
        # Features, scans, reconciliation — none depend on each other.
        # Agent cycles run in background separately.
        parallel_coros = []

        if now - self._last_feature_refresh >= self.config.feature_refresh_interval:
            if self._should_skip_due_to_slowness("features", now):
                summary["actions"].append("features_refreshed:skipped_recently_slow")
            else:
                parallel_coros.append(self._run_step("features", self._refresh_features(now, summary), summary))
                self._last_feature_refresh = now

        if now - self._last_consensus >= self.config.consensus_interval:
            parallel_coros.append(self._run_step("consensus", self._run_consensus(summary), summary))
            self._last_consensus = now

        if now - self._last_arb_scan >= self.config.arb_scan_interval:
            if self._should_skip_due_to_slowness("arb_scan", now):
                summary["actions"].append("arb_scan:skipped_recently_slow")
            else:
                parallel_coros.append(self._run_step("arb_scan", self._run_arb_scan(now, summary), summary))
                self._last_arb_scan = now

        if now - self._last_liquidity_refresh >= self._liquidity_refresh_interval:
            if self._should_skip_due_to_slowness("liquidity", now):
                summary["actions"].append("liquidity_sweep:skipped_recently_slow")
            else:
                parallel_coros.append(self._run_step("liquidity", self._refresh_liquidity(now, summary), summary))
                self._last_liquidity_refresh = now

        if now - self._last_cqi_update >= self.config.cqi_interval:
            parallel_coros.append(self._run_step("cqi", self._update_cqi(now, summary), summary))
            self._last_cqi_update = now

        if "prediction" in self.config.active_domains and now - self._last_order_groups_sync >= self._order_groups_sync_interval:
            parallel_coros.append(self._run_step("order_groups", self._sync_order_groups(summary), summary))
            self._last_order_groups_sync = now

        if parallel_coros:
            await asyncio.gather(*parallel_coros)

        # ── Sequential post-steps (state-mutating, order matters) ────
        # BUG-H5+H6 fix: reconciliation MUST run before execution so that
        # has_critical_discrepancies() and VenueExposureCap are fresh when
        # _execute_plans checks them.  Previously reconciliation was in the
        # parallel batch (step 7) while execution ran at step 5 — wrong order.
        if self.config.enable_reconciliation and now - self._last_reconciliation >= self.config.reconciliation_interval:
            await self._run_step("reconciliation", self._reconcile_positions(summary), summary)
            self._last_reconciliation = now

        if self.config.enable_execution:
            await self._run_step("execution", self._execute_plans(summary), summary)

        if now - self._last_promotion_sync >= self._promotion_sync_interval:
            self._last_promotion_sync = now
            if self._promo_bg_task is None or self._promo_bg_task.done():
                # Isolate bg summary — promotion runs in a thread after tick returns
                _promo_summary: Dict[str, Any] = {"tick": summary["tick"], "actions": []}
                async def _promo_bg():
                    try:
                        await asyncio.to_thread(self._sync_promotion, _promo_summary)
                    except Exception as e:
                        logger.debug(f"Background promotion_sync failed: {e}")
                self._promo_bg_task = asyncio.create_task(_promo_bg())
                summary["actions"].append("promotion_sync:launched")
            else:
                summary["actions"].append("promotion_sync:still_running")

        if now - self._last_config_reload >= self._config_reload_interval:
            await self._run_step("config_reload", self._reload_config(summary), summary)
            self._last_config_reload = now

        # Step 8: Notify subscribers
        await self._run_step("notify", self._notify("tick_complete", summary), summary)

        elapsed_ms = (time.perf_counter() - start) * 1000
        self.metrics.total_ticks += 1
        self.metrics.last_tick_at = now
        self.metrics.last_tick_duration_ms = elapsed_ms
        summary["duration_ms"] = round(elapsed_ms, 1)
        summary["step_timings_ms"] = dict(self._tick_step_timings)  # Include per-step timings

        # Tick duration watchdog
        if elapsed_ms > self.TICK_DURATION_WARN_MS:
            logger.warning(
                "Slow tick #%d: %.0fms (threshold %dms). Actions: %s",
                self.metrics.total_ticks,
                elapsed_ms,
                self.TICK_DURATION_WARN_MS,
                ", ".join(summary.get("actions", [])),
            )

        return summary

    # ── Step implementations ──────────────────────────────────────────

    async def _refresh_features(self, now: float, summary: Dict):
        """Step 1: Refresh decay-aware features for active symbols.

        First tries live API feeds (Finnhub, FRED, CoinGecko).
        Then reads aggregated features through the feature service.
        For prediction domain: generates Kalshi-specific signals.
        """
        # AGGRESSIVE: Skip features refresh for first 120 ticks (~10 min) during startup
        if self.metrics.total_ticks < 120:
            summary["actions"].append("features_refreshed:skipped_startup_cooldown")
            return

        # Try live data first
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            await mgr.refresh_all(self.config.active_symbols, now)
        except Exception as e:
            logger.warning(f"Live feed refresh failed (using cached/synthetic): {e}")

        # Now read features (live-ingested or synthetic fallback)
        # Run in thread pool so sync SQLite/feature reads don't block event loop
        svc = self._feature_service()
        store = self._signal_store()
        step_start = time.perf_counter()

        # AGGRESSIVE LIMIT: Process max 1 symbol per tick to prevent event-loop blocking
        # BUG-EL18 fix: Reduced from 5 symbols to prevent 6.5s+ blocking (budget is 1s)
        MAX_SYMBOLS_PER_TICK = 1
        symbols_this_tick = self.config.active_symbols[:MAX_SYMBOLS_PER_TICK]
        
        def _sync_feature_refresh():
            batch = []
            for symbol in symbols_this_tick:
                try:
                    news = svc.get_news_features(symbol, now=now)
                    social = svc.get_social_features(symbol, now=now)
                    chain = "solana" if symbol in ("SOL", "BONK", "WIF") else "ethereum"
                    onchain = svc.get_onchain_features(chain, symbol, now=now)
                    batch.extend(fs.to_dict() for fs in [news, social, onchain])
                except Exception as e:
                    logger.warning(f"Feature refresh failed for {symbol}: {e}")
            macro = svc.get_macro_features(now=now)
            batch.append(macro.to_dict())
            store.store_feature_snapshots_batch(batch)
            return len(batch)

        # Run in dedicated executor to prevent default thread pool saturation
        loop = asyncio.get_running_loop()
        batch_size = await loop.run_in_executor(_get_loop_executor(), _sync_feature_refresh)
        thread_ms = (time.perf_counter() - step_start) * 1000
        
        # Generate Kalshi signals if prediction domain is active
        # Skip during first 30 ticks (2.5 min) to reduce startup load
        # BUG-EL19 fix: Run in thread pool with timeout to prevent blocking event loop
        kalshi_ms = 0
        if "prediction" in self.config.active_domains and self.metrics.total_ticks > 30:
            kalshi_start = time.perf_counter()
            # Skip if features thread pool work already took >500ms (we're running slow)
            if thread_ms > 500:
                summary["actions"].append("kalshi_signals:skipped_due_to_slow_features")
                logger.debug("Skipping Kalshi signals: features thread work took %.0fms", thread_ms)
            else:
                # Run Kalshi signal generation in thread pool to prevent blocking
                try:
                    loop = asyncio.get_running_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(_get_loop_executor(), self._sync_refresh_kalshi_signals, now),
                        timeout=2.0  # 2 second timeout for Kalshi signal generation
                    )
                    kalshi_ms = (time.perf_counter() - kalshi_start) * 1000
                except asyncio.TimeoutError:
                    logger.warning("Kalshi signal generation timed out after 2s")
                    summary["actions"].append("kalshi_signals:timeout")
                except Exception as _kexc:
                    logger.debug("Kalshi signal generation failed: %s", _kexc)
                    summary["actions"].append("kalshi_signals:error")
        
        self.metrics.features_refreshed += 1
        total_ms = (time.perf_counter() - step_start) * 1000
        summary["actions"].append(f"features_refreshed:{len(symbols_this_tick)}symbols")
        
        # Log detailed timings if slow
        if total_ms > 100:
            logger.debug("features timings: thread=%.0fms, kalshi=%.0fms, total=%.0fms, batch=%d", 
                        thread_ms, kalshi_ms, total_ms, batch_size)

    async def _refresh_kalshi_signals(self, now: float, summary: Dict, store):
        """Generate and store Kalshi-specific signals for prediction domain."""
        try:
            from merid.signals.kalshi_signals import get_kalshi_signal_generator
            
            generator = get_kalshi_signal_generator()
            signals = await generator.generate_all(now)
            
            # Store each signal
            for signal in signals:
                store.store_signal(signal.to_dict())
            
            # Always add action to summary (even with 0 signals for testability)
            logger.info(f"Generated {len(signals)} Kalshi signals")
            summary["actions"].append(f"kalshi_signals:{len(signals)}")
        except Exception as exc:
            logger.warning(f"Kalshi signal generation failed (graceful degradation): {exc}")
            summary["actions"].append("kalshi_signals:error")
    
    def _sync_refresh_kalshi_signals(self, now: float) -> None:
        """Synchronous wrapper for _refresh_kalshi_signals to run in thread pool.
        
        BUG-EL19 fix: This prevents blocking the event loop during Kalshi signal generation.
        """
        try:
            # Create a new event loop for this thread and run the async method
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create a minimal summary dict for the sync context
            _summary: Dict[str, Any] = {"actions": []}
            
            try:
                from merid.signals.store import get_signal_store
                store = get_signal_store()
                loop.run_until_complete(self._refresh_kalshi_signals(now, _summary, store))
            finally:
                loop.close()
        except Exception as exc:
            # Silent failure - this is fire-and-forget from thread pool
            logger.debug(f"Kalshi signal generation in thread pool failed: {exc}")
    
    async def _run_agent_cycles_bg(self, summary: Dict):
        """Background wrapper — runs agent cycles without blocking the tick."""
        try:
            await self._run_agent_cycles(summary)
        except Exception as e:
            logger.warning(f"Background agent cycle failed: {e}")

    async def _run_agent_cycles(self, summary: Dict):
        """Step 2: Run canonical agents and Kalshi agents concurrently.
        
        Both agent groups run in parallel via asyncio.gather to maximize
        throughput within the 30s step timeout.
        """
        try:
            # Build coroutines to run concurrently
            registry = self._agent_registry()
            coros = [registry.run_all()]
            
            if "prediction" in self.config.active_domains:
                coros.append(self._run_kalshi_agent_cycle(summary))
            
            # Run canonical + Kalshi agents concurrently
            gathered = await asyncio.gather(*coros, return_exceptions=True)
            
            # Process canonical agent results (first coro)
            canonical_result = gathered[0]
            if isinstance(canonical_result, Exception):
                logger.warning(f"Canonical agent cycle failed: {canonical_result}")
                summary["actions"].append(f"agent_cycles:error:{canonical_result}")
            else:
                results = canonical_result or []
                self.metrics.agent_cycles_run += 1
                summary["actions"].append(f"agent_cycles:{len(results)}agents")
                for agent_id in (getattr(r, "agent_id", None) for r in results):
                    if agent_id:
                        self._agent_errors.pop(agent_id, None)
            
            # Process Kalshi agent result if present (second coro)
            if len(gathered) > 1 and isinstance(gathered[1], Exception):
                logger.warning(f"Kalshi agent cycle failed: {gathered[1]}")
                
        except Exception as e:
            logger.warning(f"Agent cycle failed: {e}")
            summary["actions"].append(f"agent_cycles:error:{e}")
            err_key = f"_cycle_{self.metrics.agent_cycles_run}"
            self._agent_errors[err_key] = self._agent_errors.get(err_key, 0) + 1
            if self._agent_errors.get(err_key, 0) >= 5:
                logger.error("Agent cycle circuit breaker: 5 consecutive failures, pausing execution")
                self.config.enable_execution = False

    async def _run_kalshi_agent_cycle(self, summary: Dict):
        """Run KalshiTradingAgent decision cycle and collect signals.

        Note: For now, agents execute directly via their own cycle.
        Future: Submit signals to consensus for multi-agent voting.

        CPU-heavy signal processing is offloaded to thread pool to avoid
        blocking the event loop (BUG-EL12 fix).
        """
        try:
            from merid.prediction.agent_grid import get_agent_grid

            grid = get_agent_grid()

            # Check if grid is running
            if not grid.is_running:
                logger.debug("Kalshi agent grid not running, skipping agent cycle")
                return

            # Offload CPU-intensive signal scanning to thread pool
            def _scan_signals_sync():
                """Scan for actionable signals synchronously in thread pool."""
                signal_count = 0
                _sig_cutoff = time.time() - 120.0

                for agent in grid.agents:
                    if agent.state.enabled and agent.state.signal_log:
                        for s in agent.state.signal_log[-10:]:
                            act = str(s.get("action") or "").lower()
                            if act in ("no_action", "hold", ""):
                                continue
                            ts_raw = s.get("ts")
                            if ts_raw:
                                try:
                                    from datetime import datetime as _dt
                                    st = _dt.fromisoformat(
                                        str(ts_raw).replace("Z", "+00:00")
                                    )
                                    if st.timestamp() < _sig_cutoff:
                                        continue
                                except Exception:
                                    continue
                            signal_count += 1
                return signal_count

            loop = asyncio.get_running_loop()
            signal_count = await loop.run_in_executor(_get_loop_executor(), _scan_signals_sync)

            if signal_count > 0:
                logger.info(f"Kalshi agents generated {signal_count} actionable signals this cycle")
                summary["actions"].append(f"kalshi_agents:{signal_count}signals")

            # Submit actionable signals to consensus coordinator as AgentOpinions
            opinions_submitted = 0
            try:
                from consensus.taco_consensus import (
                    AgentOpinion,
                    AgentRole,
                )
                import uuid as _uuid

                coordinator = self._consensus_coordinator()
                _sig_cutoff = time.time() - 120.0

                # Offload opinion preparation to thread pool
                def _prepare_opinions_sync():
                    """Prepare opinions synchronously in thread pool."""
                    opinions = []
                    for agent in grid.agents:
                        if not (agent.state.enabled and agent.state.signal_log):
                            continue
                        recent_signals = []
                        for s in agent.state.signal_log[-5:]:
                            _a = str(s.get("action") or "").lower()
                            if _a in ("no_action", "hold", ""):
                                continue
                            ts_raw = s.get("ts")
                            if ts_raw:
                                try:
                                    from datetime import datetime as _dt
                                    st = _dt.fromisoformat(
                                        str(ts_raw).replace("Z", "+00:00")
                                    )
                                    if st.timestamp() < _sig_cutoff:
                                        continue
                                except Exception:
                                    continue
                            recent_signals.append(s)

                        for sig in recent_signals:
                            action = sig.get("action", "").lower()
                            # BUG-6 fix: SignalAction enum values are 'buy_yes', 'buy_no',
                            # 'sell_yes', 'sell_no'
                            if action in ("buy_yes", "buy_no", "buy", "yes", "long"):
                                score = sig.get("edge", 0.05)
                                stance = "bull"
                            elif action in ("sell_yes", "sell_no", "sell", "no", "short"):
                                score = -(sig.get("edge", 0.05))
                                stance = "bear"
                            else:
                                continue
                            confidence = float(sig.get("confidence", sig.get("edge", 0.5)))
                            confidence = max(0.1, min(1.0, confidence))
                            opinion = AgentOpinion(
                                opinion_id=f"op_{_uuid.uuid4().hex[:12]}",
                                agent_id=agent.agent_id,
                                role=AgentRole.TRADER.value,
                                symbol=sig.get("market_id", sig.get("ticker", "KALSHI")),
                                venue="kalshi",
                                stance=stance,
                                score=float(score),
                                confidence=confidence,
                                rationale=sig.get("reason", sig.get("signal_type", "kalshi_signal"))[:200],
                                horizon="short",
                            )
                            opinions.append(opinion)
                    return opinions

                opinions = await loop.run_in_executor(_get_loop_executor(), _prepare_opinions_sync)

                # Submit opinions asynchronously (I/O bound)
                for opinion in opinions:
                    try:
                        await coordinator.submit_opinion(opinion)
                        opinions_submitted += 1
                    except Exception as _submit_exc:
                        logger.debug(f"Opinion submission failed: {_submit_exc}")

            except Exception as _ce:
                logger.debug(f"Consensus opinion submission failed (non-fatal): {_ce}")

            if opinions_submitted:
                summary["actions"].append(f"consensus_opinions_submitted:{opinions_submitted}")
            
        except Exception as exc:
            logger.warning(f"Kalshi agent cycle failed (graceful degradation): {exc}")
    
    async def _run_reflection_cycle(self, summary: Dict):
        """Step 2b: Run post-task reflection and learning for Kalshi agents.

        For each active Kalshi agent, pulls its recent reflections from the
        ReflectionSystem, generates learning insights, and surfaces any
        critical recommendations (overconfidence, low accuracy) to the summary.
        Runs every 5 minutes — offloaded to thread pool to avoid blocking event loop.
        """
        if "prediction" not in self.config.active_domains:
            return
        
        # Skip reflection cycle during first 80 ticks (~6.7 min) to reduce startup load
        if self.metrics.total_ticks < 80:
            summary["actions"].append("reflection_cycle:skipped_startup_cooldown")
            return
            
        try:
            from agents.reflection.integration import get_reflection_system
            from merid.prediction.agent_grid import get_agent_grid

            reflection_sys = get_reflection_system()
            grid = get_agent_grid()

            # Offload to dedicated thread pool to prevent blocking event loop
            # Use max 5 agents per cycle to prevent thread pool saturation
            MAX_AGENTS_PER_CYCLE = 5
            agent_batch = list(grid.agents)[:MAX_AGENTS_PER_CYCLE]
            
            def _process_reflections():
                total_reflections = 0
                total_insights = 0
                critical_agents: list = []

                for agent in agent_batch:
                    agent_id = agent.agent_id
                    # Limit to 50 reflections per agent to reduce processing time
                    reflections = reflection_sys.core.get_agent_reflections(agent_id, limit=50)
                    if not reflections:
                        continue
                    total_reflections += len(reflections)

                    insights = reflection_sys.learning.generate_insights(
                        agent_id, reflections, force_refresh=True
                    )
                    total_insights += len(insights)

                    # Surface critical recommendations
                    for ins in insights:
                        if ins.insight_type == "recommendation" and "critical" in ins.title.lower():
                            critical_agents.append({
                                "agent": agent_id,
                                "issue": ins.title,
                                "confidence": ins.confidence,
                            })
                            logger.warning(
                                f"Reflection CRITICAL [{agent_id}]: {ins.title} "
                                f"(evidence={ins.evidence_count}, conf={ins.confidence:.2f})"
                            )
                
                return total_reflections, total_insights, critical_agents
            
            # Run in dedicated executor with 32 workers
            loop = asyncio.get_running_loop()
            total_reflections, total_insights, critical_agents = await loop.run_in_executor(
                _get_loop_executor(), _process_reflections
            )

            summary["actions"].append(
                f"reflection_cycle:{total_reflections}reflections,{total_insights}insights"
            )
            if critical_agents:
                summary["reflection_critical"] = critical_agents

        except Exception as exc:
            logger.warning(f"Reflection cycle failed (graceful degradation): {exc}")
            summary["actions"].append(f"reflection_cycle:error:{exc}")

    async def _reload_config(self, summary: Dict) -> None:
        """Step 7c: Hot-reload config — re-register live assertions in RealityAuditor
        and re-bootstrap PortfolioRebalancer targets so risk limit changes propagate
        without a server restart.
        """
        reloaded: list = []

        # 1. RealityAuditor hot-reload
        try:
            from core.reality_auditor import get_reality_auditor
            auditor = get_reality_auditor()
            ok = auditor.reload_from_persistent_store()
            reloaded.append(f"reality_auditor:{'ok' if ok else 'noop'}")
        except Exception as exc:
            logger.debug("config_reload: reality_auditor skipped: %s", exc)

        # 2. PortfolioRebalancer target re-bootstrap
        try:
            from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
            rebalancer = get_portfolio_rebalancer()
            rebalancer._bootstrap_targets()
            reloaded.append("rebalancer:bootstrapped")
        except Exception as exc:
            logger.debug("config_reload: rebalancer bootstrap skipped: %s", exc)

        # 3. RewardEngine — ensure singleton is alive (no-op if already running)
        try:
            from merid.rewards.engine import get_reward_engine
            get_reward_engine()
            reloaded.append("reward_engine:ok")
        except Exception as exc:
            logger.debug("config_reload: reward_engine skipped: %s", exc)

        if reloaded:
            summary["actions"].append("config_reload:" + ",".join(reloaded))
            logger.debug("config_reload: %s", reloaded)

    async def _run_consensus(self, summary: Dict):
        """Step 3: Run consensus for active symbols (decay-aware).

        Prunes expired plans from _active_plans and forces a consensus
        cycle for any symbol that has accumulated pending opinions since
        the last tick but hasn't yet crossed the min_opinions threshold
        (opinion-triggered cycles handle the normal path).

        CPU-heavy debate processing is offloaded to thread pool to avoid
        blocking the event loop (BUG-EL12 fix).
        """
        step_start = time.perf_counter()
        coordinator = self._consensus_coordinator()

        # Prune expired plans so _execute_plans never sees stale entries
        # Offload to thread pool to avoid blocking event loop
        prune_start = time.perf_counter()

        def _prune_sync():
            if hasattr(coordinator, 'prune_expired_plans'):
                coordinator.prune_expired_plans()
                return []
            else:
                _active_plans = getattr(coordinator, '_active_plans', {})
                expired_ids = [
                    pid for pid, plan in list(_active_plans.items())
                    if plan.is_expired()
                ]
                for pid in expired_ids:
                    _active_plans.pop(pid, None)
                return expired_ids

        loop = asyncio.get_running_loop()
        expired_ids = await loop.run_in_executor(_get_loop_executor(), _prune_sync)
        prune_ms = (time.perf_counter() - prune_start) * 1000

        # Force a consensus cycle for any symbol with pending opinions
        # LIMIT: Process max 5 symbols per tick (reduced from 10) to stay within budget
        _opinions = getattr(coordinator, '_opinions', {})
        pending_symbols = [
            sym for sym, ops in _opinions.items()
            if ops and len(ops) >= 1
        ][:5]  # Cap at 5 symbols per tick (reduced from 10)

        forced = 0
        consensus_start = time.perf_counter()
        for sym in pending_symbols:
            try:
                plan = await coordinator._run_consensus_cycle(sym)
                if plan:
                    forced += 1
            except Exception as _ce:
                logger.debug(f"Consensus cycle error for {sym}: {_ce}")
        consensus_ms = (time.perf_counter() - consensus_start) * 1000

        self.metrics.consensus_cycles_run += 1

        # === Debate Protocol Integration ===
        # For each forced consensus plan, open a DebateSession so agents can
        # argue for/against before execution.  Close open debates whose symbol
        # now has a fresh consensus probability.
        # Offloaded to thread pool to avoid blocking event loop (BUG-EL12 fix)
        debate_start = time.perf_counter()
        debates_opened = 0
        debates_closed = 0
        try:
            from merid.prediction.debate import get_debate_store, DebateSession

            # Capture coordinator state for thread-safe access
            _active_plans_ref = getattr(coordinator, '_active_plans', {})
            _opinions_ref = getattr(coordinator, '_opinions', {})

            def _process_debates_sync():
                """Process debate operations synchronously in thread pool."""
                opened = 0
                closed = 0
                debate_store = get_debate_store()

                # Open a debate for each freshly-forced plan (high-conviction only)
                # LIMIT: Max 3 debates per tick (reduced from 5)
                plans_to_debate = list(_active_plans_ref.values())[:3]

                for plan in plans_to_debate:
                    prob = getattr(plan, 'consensus_probability', None) or getattr(plan, 'probability', None)
                    if prob is None:
                        continue
                    # Only open debates for high-conviction signals (edge > 5%)
                    edge = abs(float(prob) - 0.5)
                    if edge < 0.05:
                        continue
                    symbol = getattr(plan, 'symbol', None) or getattr(plan, 'market_id', None)
                    if not symbol:
                        continue
                    # Avoid duplicate open debates for the same symbol
                    open_debates = debate_store.list_debates(symbol=symbol, status="open")
                    if open_debates:
                        continue
                    session = DebateSession(
                        symbol=symbol,
                        pre_debate_prob=float(prob),
                    )
                    debate_store.create_debate(session)
                    opened += 1

                # Close open debates whose symbol has a fresh consensus probability
                # LIMIT: Max 5 debates to check per tick (reduced from 10)
                for debate in debate_store.list_debates(status="open", limit=5):
                    sym_opinions = _opinions_ref.get(debate.symbol, [])
                    if not sym_opinions:
                        continue
                    # Use latest opinion confidence as post-debate probability
                    latest = sym_opinions[-1]
                    post_prob = getattr(latest, 'probability', None) or getattr(latest, 'confidence', None)
                    if post_prob is None:
                        continue
                    debate_store.close_debate(debate.id, float(post_prob))
                    closed += 1

                return opened, closed

            # Run debate processing in dedicated executor
            debates_opened, debates_closed = await loop.run_in_executor(
                _get_loop_executor(), _process_debates_sync
            )

            # Log debate activity outside the thread
            if debates_opened > 0:
                logger.debug("debate opened: %d debates", debates_opened)
            if debates_closed > 0:
                logger.debug("debate closed: %d debates", debates_closed)

        except Exception as _de:
            logger.debug("debate integration skipped: %s", _de)

        debate_ms = (time.perf_counter() - debate_start) * 1000
        total_ms = (time.perf_counter() - step_start) * 1000

        summary["actions"].append(
            f"consensus_check:expired_pruned={len(expired_ids)},forced={forced},"
            f"debates_opened={debates_opened},debates_closed={debates_closed}"
        )

        # Log detailed timings if slow
        if total_ms > 100:
            logger.debug("consensus timings: prune=%.0fms, consensus=%.0fms, debate=%.0fms, total=%.0fms",
                        prune_ms, consensus_ms, debate_ms, total_ms)

    async def _refresh_liquidity(self, now: float, summary: Dict) -> None:
        """Step 4b: Poll orderbook snapshots for active Kalshi markets.

        Feeds each snapshot into LiquidityMonitor which emits alerts on
        wide spreads, thin books, and sudden depth drops.  Critical alerts
        are logged at WARNING level so operators see them immediately.

        CPU-heavy orderbook processing is offloaded to thread pool to avoid
        blocking the event loop (BUG-EL12 fix).
        
        EVENT-LOOP-FIX: Added lag-aware scheduling and timeout guards.
        """
        import asyncio
        import os as _os
        
        # PROFILING: Track entry time and lag
        _profiling = _os.getenv("MERID_PROFILING")
        _prof_entry_ts = time.perf_counter() if _profiling else 0
        
        # AGGRESSIVE: Skip liquidity sweep for first 120 ticks (~10 min) to reduce startup load
        if self.metrics.total_ticks < 120:
            if _profiling:
                logger.debug("[PROF] liquidity:skipped_startup tick=%d", self.metrics.total_ticks)
            summary["actions"].append("liquidity_sweep:skipped_startup_cooldown")
            return
        
        # Check lag before starting
        current_lag = self._get_event_loop_lag_ms()
        if current_lag > 750:  # Skip if already lagging
            logger.warning(
                "[LAG-SKIP] action=liquidity_sweep reason=elevated_lag "
                f"lag_ms={current_lag:.0f} threshold_ms=750 timeout_count={getattr(self.metrics, 'liquidity_timeouts', 0)}"
            )
            summary["actions"].append("liquidity_sweep:skipped_due_to_lag")
            # Track skip metrics
            self.metrics.lag_skips_total = getattr(self.metrics, 'lag_skips_total', 0) + 1
            return

        sub_timings: Dict[str, float] = {}
        step_start = time.perf_counter()

        def _mark(label: str):
            sub_timings[label] = (time.perf_counter() - step_start) * 1000

        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.liquidity_monitor import OrderBookSnapshot

            _mark("init")
            monitor = self._liquidity_monitor()
            client = get_kalshi_client()
            _mark("get_client")

            # Fast-path: skip entire orderbook sweep if Kalshi circuit is open
            if getattr(client, "is_circuit_open", False):
                summary["actions"].append("liquidity_sweep:circuit_open")
                return

            # Collect active tickers from the agent grid - offload to thread pool
            def _collect_tickers_sync():
                tickers: List[str] = []
                try:
                    from merid.prediction.agent_grid import get_agent_grid
                    grid = get_agent_grid()
                    for agent in grid.agents:
                        tickers.extend(agent.state.active_tickers)
                except Exception as _age:
                    logger.debug("liquidity_sweep agent_grid skipped: %s", _age)
                return tickers

            loop = asyncio.get_running_loop()
            
            # EVENT-LOOP-FIX: Add timeout to thread pool operation
            try:
                tickers = await asyncio.wait_for(
                    loop.run_in_executor(_get_loop_executor(), _collect_tickers_sync),
                    timeout=2.0  # Max 2s for ticker collection
                )
            except asyncio.TimeoutError:
                logger.warning("[LAG-GUARD] liquidity ticker collection timed out after 2s")
                summary["actions"].append("liquidity_sweep:timeout_collecting_tickers")
                return
            _mark("collect_tickers")

            if not tickers:
                summary["actions"].append("liquidity_sweep:no_active_tickers")
                return

            # PHASE-3: Lag-aware scope reduction — fewer markets when lag is elevated
            # This prevents the 9.7s blocking observed in production
            base_max = 3 if self.metrics.total_ticks < 120 else 5
            if current_lag > 500:
                MAX_TICKERS = 1  # Critical lag: absolute minimum
                logger.warning("[BUDGET] liquidity: reduced scope to 1 market due to lag %.0fms", current_lag)
            elif current_lag > 250:
                MAX_TICKERS = 2  # Elevated lag: reduced scope
                logger.warning("[BUDGET] liquidity: reduced scope to 2 markets due to lag %.0fms", current_lag)
            else:
                MAX_TICKERS = base_max
            
            tickers = list(dict.fromkeys(tickers))[:MAX_TICKERS]

            # D13: Subscribe WS bridge to any new tickers discovered this sweep
            if getattr(self, '_ws_bridge', None) is not None:
                try:
                    await self._ws_bridge.subscribe(tickers)
                except Exception as _wse:
                    logger.debug("ws_bridge mid-session subscribe skipped: %s", _wse)

            _mark("prep_done")
            alerts_total = 0

            # PHASE-3: Hard budget enforcement for liquidity sweep
            # Track cumulative time and abort if approaching 1000ms budget
            LIQUIDITY_HARD_BUDGET_MS = 1000.0
            _budget_start = time.perf_counter()
            
            def _check_budget_exceeded() -> bool:
                elapsed_ms = (time.perf_counter() - _budget_start) * 1000
                if elapsed_ms > LIQUIDITY_HARD_BUDGET_MS:
                    logger.error(
                        "[BUDGET] liquidity_budget_exceeded: aborting after %.1fms (budget %.0fms)",
                        elapsed_ms, LIQUIDITY_HARD_BUDGET_MS
                    )
                    return True
                return False
            
            # Fetch orderbooks concurrently (max 2 at a time via semaphore - reduced from 3)
            _sem = asyncio.Semaphore(2)

            async def _fetch_ob(ticker: str):
                async with _sem:
                    # PHASE-3: Budget check before each fetch
                    if _check_budget_exceeded():
                        return (ticker, None)
                    
                    # Abort if circuit tripped during this sweep
                    if getattr(client, "is_circuit_open", False):
                        return (ticker, None)
                    try:
                        ob = await asyncio.wait_for(client.get_orderbook(ticker), timeout=2.0)  # reduced timeout
                        return (ticker, ob)
                    except Exception as _te:
                        logger.debug("liquidity_sweep %s skipped: %s", ticker, _te)
                        return (ticker, None)

            results = await asyncio.gather(*[_fetch_ob(t) for t in tickers])
            _mark("fetch_orderbooks")

            # Offload orderbook processing to thread pool to avoid blocking event loop
            def _process_results_sync():
                alerts_total = 0
                for ticker, ob in results:
                    if not ob:
                        continue
                    try:
                        bid = float(ob.bids[0][0]) if ob.bids else 0.0
                        ask = float(ob.asks[0][0]) if ob.asks else 1.0
                        bid_sz = int(ob.bids[0][1]) if ob.bids else 0
                        ask_sz = int(ob.asks[0][1]) if ob.asks else 0
                        snap = OrderBookSnapshot(
                            market_id=ticker,
                            best_bid=bid,
                            best_ask=ask,
                            bid_size=bid_sz,
                            ask_size=ask_sz,
                            ts=now,
                        )
                        alerts = monitor.process(snap)
                        alerts_total += len(alerts)
                    except Exception as _te:
                        logger.debug("liquidity_sweep %s process skipped: %s", ticker, _te)
                return alerts_total

            # EVENT-LOOP-FIX: Add timeout to orderbook processing
            try:
                alerts_total = await asyncio.wait_for(
                    loop.run_in_executor(_get_loop_executor(), _process_results_sync),
                    timeout=3.0  # Max 3s for orderbook processing
                )
            except asyncio.TimeoutError:
                logger.warning("[LAG-GUARD] liquidity orderbook processing timed out after 3s")
                summary["actions"].append("liquidity_sweep:timeout_processing")
                alerts_total = 0

            # Update stop-loss prices separately (lightweight, async-safe)
            for ticker, ob in results:
                if not ob:
                    continue
                try:
                    bid = float(ob.bids[0][0]) if ob.bids else 0.0
                    ask = float(ob.asks[0][0]) if ob.asks else 1.0
                    mid_cents = int(round((bid + ask) / 2 * 100))
                    if mid_cents > 0:
                        try:
                            from merid.prediction.agent_grid import get_agent_grid as _gg
                            for _agent in _gg().agents:
                                for _pos in _agent._tracked_positions.values():
                                    if _pos.ticker == ticker:
                                        _pos.current_price_cents = mid_cents
                        except Exception as _pe:
                            logger.debug("stop_loss price update skipped for %s: %s", ticker, _pe)
                except Exception:
                    pass  # Already logged in sync processing

            _mark("process_done")
            summary["actions"].append(
                f"liquidity_sweep:{len(tickers)}markets,{alerts_total}alerts"
            )
            # Log detailed timings if slow
            total_ms = (time.perf_counter() - step_start) * 1000
            if total_ms > 100:
                timing_str = ", ".join(f"{k}={v:.0f}ms" for k, v in sub_timings.items())
                logger.debug("liquidity_sweep timings: %s (total=%.0fms)", timing_str, total_ms)
            
            # PROFILING: Log structured metrics (bounded: only when profiling enabled)
            if _profiling and (total_ms > 50 or _prof_entry_ts):
                _prof_exit_ts = time.perf_counter()
                _current_lag = self._get_event_loop_lag_ms()
                logger.debug(
                    "[PROF] liquidity action=%s duration_ms=%.1f lag_ms=%.1f markets=%d alerts=%d",
                    "liquidity_sweep", total_ms, _current_lag, len(tickers), alerts_total
                )
        except Exception as exc:
            logger.debug("_refresh_liquidity skipped: %s", exc)

    async def _run_arb_scan(self, now: float, summary: Dict):
        """Step 4: Scan for cross-venue arbitrage/dislocations.
        
        CPU-heavy scanning is offloaded to thread pool to avoid blocking event loop.
        EVENT-LOOP-FIX: Added timeout guard and cancellation support.
        """
        import asyncio
        import os as _os
        
        # PROFILING: Track entry
        _profiling = _os.getenv("MERID_PROFILING")
        _prof_entry_ts = time.perf_counter() if _profiling else 0
        
        # Skip arb scan for first 40 ticks (~3.3 min) to let startup stabilize
        if self.metrics.total_ticks < 40:
            if _profiling:
                logger.debug("[PROF] arb_scan:skipped_startup tick=%d", self.metrics.total_ticks)
            summary["actions"].append("arb_scan:skipped_startup_cooldown")
            return
        
        # Check current lag before starting
        current_lag = self._get_event_loop_lag_ms()
        if current_lag > 200:  # Hardened: lowered from 500ms to 200ms
            logger.warning(
                "[LAG-SKIP] action=arb_scan reason=elevated_lag "
                f"lag_ms={current_lag:.0f} threshold_ms=200 timeout_count={getattr(self.metrics, 'arb_scan_timeouts', 0)}"
            )
            if _profiling:
                logger.debug("[PROF] arb_scan:skipped_due_to_lag lag_ms=%.1f", current_lag)
            summary["actions"].append("arb_scan:skipped_due_to_lag")
            # Track skip metrics
            self.metrics.lag_skips_total = getattr(self.metrics, 'lag_skips_total', 0) + 1
            return
            
        step_start = time.perf_counter()
        scanner = self._scanner()
        store = self._signal_store()
        
        try:
            # Combine scan + store + validate into a single executor call to
            # reduce thread-pool contention (all are lightweight in-memory ops).
            def _do_arb_scan_all():
                # PHASE-3: Yield points for GAP-2 fix — periodically release GIL to let asyncio breathe
                # This prevents multi-second blocking in CPU-heavy scanning loops
                # NOTE: time.sleep() here (not asyncio.sleep) because this runs in a thread pool
                # executor. It releases the GIL, allowing the main event loop thread to process.
                signals = scanner.scan(now)
                
                # Yield after initial scan to allow event loop processing
                time.sleep(0.001)  # 1ms GIL yield in thread pool context
                
                if not signals:
                    signals = scanner.synthetic_scan(now)
                    # Second yield point after synthetic scan
                    time.sleep(0.001)
                    
                if signals:
                    store.store_arb_signals_batch([sig.to_dict() for sig in signals])
                    # Third yield point after batch store
                    time.sleep(0.001)
                    
                scanner.validate_plans(now)
                return signals
            
            loop = asyncio.get_running_loop()
            
            # EVENT-LOOP-FIX: Add timeout to prevent thread pool starvation
            _ARB_TIMEOUT_S = float(os.getenv("MERID_ARB_SCAN_TIMEOUT_S", "2.0"))
            signals = await asyncio.wait_for(
                loop.run_in_executor(_get_loop_executor(), _do_arb_scan_all),
                timeout=_ARB_TIMEOUT_S
            )
            
            self.metrics.arb_scans_run += 1
            summary["actions"].append(f"arb_scan:{len(signals)}signals")
            
            # Log detailed timings if slow
            total_ms = (time.perf_counter() - step_start) * 1000
            if total_ms > 100:
                logger.debug("arb_scan total=%.0fms signals=%d", total_ms, len(signals))
        except asyncio.TimeoutError:
            logger.warning(f"[LAG-GUARD] arb_scan timed out after {_ARB_TIMEOUT_S}s — skipping")
            summary["actions"].append("arb_scan:timeout")
            # Track for adaptive skipping
            self._slow_action_last_skip["arb_scan"] = time.time()
        except asyncio.CancelledError:
            logger.debug("[LAG-GUARD] arb_scan cancelled during shutdown")
            raise
        except Exception as e:
            logger.warning(f"Arb scan failed: {e}")
            summary["actions"].append(f"arb_scan:error:{e}")

    async def _execute_plans(self, summary: Dict):
        """Step 5: Execute approved trade plans through the venue adapter.

        Every plan passes through the ExecutionGuard before submission.
        RiskContext further scales sizes based on system-level stress
        (CQI, drawdown, exposure).
        """
        guard = self._execution_guard()

        # Global kill switch short-circuit
        if guard.kill_switch_active:
            summary["actions"].append("execution:blocked_by_kill_switch")
            return

        # BUG-H2 fix: Kalshi circuit-open fast-path — mirrors _refresh_liquidity:821.
        # When the circuit is open every HTTP call would fail immediately, producing
        # log noise and leaving plans stuck in "approved" status indefinitely.
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client as _get_kc
            _kc = _get_kc()
            if getattr(_kc, "is_circuit_open", False):
                summary["actions"].append("execution:blocked_by_kalshi_circuit_open")
                logger.warning(
                    "Execution BLOCKED: Kalshi circuit breaker is open. "
                    "Plans deferred until circuit recovers."
                )
                return
        except Exception as _circuit_exc:
            logger.debug("Kalshi circuit check skipped: %s", _circuit_exc)

        # Hard reconciliation gate — refuse to execute if positions are out of sync
        try:
            from merid.reconciliation import has_critical_discrepancies
            if has_critical_discrepancies():
                logger.warning(
                    "Execution BLOCKED: critical reconciliation discrepancies detected. "
                    "Resolve with force_align_from_venue() or fix positions manually."
                )
                summary["actions"].append("execution:blocked_by_reconciliation")
                return
        except ImportError:
            logger.debug("reconciliation module not available — skipping discrepancy check")

        # Build risk context once per tick for system-level sizing
        try:
            risk_ctx = self._risk_context()
        except Exception as _rctx_exc:
            logger.debug("_risk_context unavailable (using None): %s", _rctx_exc)
            risk_ctx = None

        coordinator = self._consensus_coordinator()
        _active_plans = getattr(coordinator, '_active_plans', {})
        plans = list(_active_plans.values())
        approved = [p for p in plans if p.status == "approved" and not p.is_expired()]

        for plan in approved:
            domain = getattr(plan, "domain", "crypto")
            if isinstance(domain, str):
                pass
            else:
                domain = getattr(domain, "value", "crypto")

            size_usd = getattr(plan, "approved_size_usd", None) or plan.target_size_usd

            # Apply RiskContext size scaling before guard check
            if risk_ctx is not None and risk_ctx.size_scale_factor < 1.0:
                size_usd = size_usd * risk_ctx.size_scale_factor
                if size_usd <= 0:
                    summary["actions"].append(
                        f"blocked:{plan.symbol}:risk_context_scale=0"
                    )
                    continue

            # Pre-trade safety check
            # Extract asset from symbol for per-asset risk caps (crypto domain only)
            asset = ""
            if domain == "crypto" and "/" in plan.symbol:
                asset = plan.symbol.split("/")[0].upper()
            
            exec_venue = _resolve_plan_adapter_venue(plan, domain)
            verdict = guard.pre_trade_check(
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                domain=domain,
                size_usd=size_usd,
                direction=plan.direction,
                venue=exec_venue,
                asset=asset,  # Per-asset risk cap enforcement
            )

            if not verdict.allowed:
                summary["actions"].append(f"blocked:{plan.symbol}:{verdict.reason}")
                continue

            try:
                # Use guard-adjusted size
                plan.approved_size_usd = verdict.adjusted_size_usd
                result = await self._execute_single_plan(plan)
                if result:
                    guard.record_execution(domain, verdict.adjusted_size_usd, asset=asset)
                    self.metrics.plans_executed += 1
                    summary["actions"].append(
                        f"executed:{plan.symbol}:{plan.direction}"
                        f":${verdict.adjusted_size_usd:.0f}"
                        f"(throttle={verdict.throttle_pct:.0%})"
                    )
                    # Telegram success notification
                    try:
                        from agents.telegram_agent import get_telegram_agent
                        tg = get_telegram_agent()
                        if tg.enabled:
                            await tg.send_execute_success(
                                episode_id=plan.plan_id,
                                assets=[asset] if asset else [],
                                summary=f"{plan.direction.upper()} {plan.symbol} ${verdict.adjusted_size_usd:.0f}",
                                throttle=f"{verdict.throttle_pct:.0%}",
                                cqi=f"{verdict.cqi_score:.2f}",
                            )
                    except Exception as tg_exc:
                        logger.debug("Telegram success notification failed: %s", tg_exc)
            except Exception as e:
                logger.error(f"Plan execution failed {plan.plan_id}: {e}")
                summary["actions"].append(f"plan_failed:{plan.plan_id}:{plan.symbol}:{e}")
                # Telegram failure notification
                try:
                    from agents.telegram_agent import get_telegram_agent
                    tg = get_telegram_agent()
                    if tg.enabled:
                        await tg.send_execute_failure(
                            episode_id=plan.plan_id,
                            assets=[asset] if asset else [],
                            summary=f"Execution failed: {str(e)[:100]}",
                            error=str(e),
                        )
                except Exception as tg_exc:
                    logger.debug("Telegram failure notification failed: %s", tg_exc)

    async def _execute_single_plan(self, plan) -> Optional[Dict]:
        """Bridge a TradePlan to a TradeRequest and submit to the adapter.

        For domains with an active matching engine (e.g. prediction in paper
        mode), orders are routed internally instead of to an external venue.
        """
        domain = getattr(plan, "domain", "crypto")
        if isinstance(domain, str):
            plan_domain = domain
        else:
            plan_domain = getattr(domain, "value", "crypto")

        # Route to internal matching engine if available for this domain
        engine = self._matching_engines.get(plan_domain)
        if engine and engine.enabled:
            return await self._execute_via_matching_engine(plan, engine)

        # Otherwise route to external venue adapter
        import trading.adapters  # noqa: F401 — side-effect: Kalshi/Coinbase/etc. register
        from trading.adapters.base import TradeRequest, TradeSide, OrderType
        from trading.adapters.registry import get_adapter
        from trading.trade_mode import is_paper_or_mock

        venue = _resolve_plan_adapter_venue(plan, plan_domain)
        adapter = get_adapter(venue)
        if not adapter:
            logger.warning(f"No adapter for venue {venue}")
            return None

        side = TradeSide.BUY if plan.direction in ("long", "buy") else TradeSide.SELL
        qty = plan.approved_size_usd or plan.target_size_usd

        request = TradeRequest(
            venue=venue,
            symbol=plan.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            notional_usd=qty,
            client_reference=plan.plan_id,
            live=not is_paper_or_mock(),
        )

        result = await asyncio.get_running_loop().run_in_executor(
            None, adapter.submit_order, request
        )
        if result is None:
            logger.warning("adapter.submit_order returned None for plan %s", plan.plan_id)
            return None
        plan.status = "executed"
        return {"order_id": result.venue_order_id, "status": result.status}

    async def _execute_via_matching_engine(self, plan, engine) -> Optional[Dict]:
        """Execute a plan through the internal matching engine (paper mode)."""
        from merid.matching_engine import Order, OrderSide

        side = OrderSide.BUY if plan.direction in ("long", "buy") else OrderSide.SELL
        notional = plan.approved_size_usd or plan.target_size_usd

        order = Order(
            instrument_id=plan.symbol,
            side=side,
            notional_usd=notional,
            domain=engine.domain,
            agent_id=getattr(plan, "agent_id", ""),
            plan_id=plan.plan_id,
        )

        fill = await asyncio.get_running_loop().run_in_executor(
            None, engine.submit_order, order
        )

        if order.status.value == "filled":
            if fill is None:
                # Should not happen — engine marked order filled but returned no Fill object.
                # Log and treat as rejection rather than crash on fill.fill_id.
                logger.error(
                    "Matching engine inconsistency: order %s marked 'filled' but fill is None",
                    order.order_id,
                )
                return None
            plan.status = "executed"
            return {
                "order_id": order.order_id,
                "fill_id": fill.fill_id,
                "price": fill.price,
                "quantity": fill.quantity,
                "notional_usd": fill.notional_usd,
                "engine": "internal_matching",
                "status": "filled",
            }
        else:
            logger.warning(
                f"Matching engine rejected {order.order_id}: {order.status.value}"
            )
            return None

    async def _update_cqi(self, now: float, summary: Dict):
        """Step 6: Update drift metrics and CQI per domain.

        Also feeds CQI scores into the ExecutionGuard for throttling.
        CPU-heavy CQI computation runs in thread pool to avoid blocking event loop.
        """
        step_start = time.perf_counter()
        detector = self._drift_detector()
        store = self._signal_store()
        guard = self._execution_guard()
        cqi_scores: Dict[str, float] = {}
        
        # Run CPU-heavy CQI computation in dedicated executor to avoid blocking event loop
        def _compute_cqi_for_domain(domain: str):
            try:
                cqi = detector.compute_cqi(domain, now=now)
                score = cqi.score if hasattr(cqi, 'score') else cqi.get('score', 0.5) if isinstance(cqi, dict) else 0.5
                return domain, cqi, score, None
            except Exception as e:
                return domain, None, 0.5, e
        
        # Process domains concurrently via dedicated executor
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(_get_loop_executor(), _compute_cqi_for_domain, domain)
            for domain in self.config.active_domains
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        compute_ms = (time.perf_counter() - step_start) * 1000
        
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"CQI update failed: {result}")
                continue
            domain, cqi, score, error = result
            if error:
                logger.warning(f"CQI update failed for {domain}: {error}")
                continue
            try:
                store.store_cqi(cqi.to_dict())
                guard.update_cqi(domain, score)
                cqi_scores[domain] = score
            except Exception as e:
                logger.warning(f"CQI store/update failed for {domain}: {e}")
        
        self.metrics.cqi_updates += 1
        total_ms = (time.perf_counter() - step_start) * 1000
        summary["actions"].append(f"cqi_updated:{len(self.config.active_domains)}domains")
        summary["cqi_scores"] = cqi_scores
        
        # Log detailed timings if slow
        if total_ms > 100:
            logger.debug("cqi timings: compute=%.0fms, total=%.0fms, domains=%d", 
                        compute_ms, total_ms, len(self.config.active_domains))

    def _sync_promotion(self, summary: Dict):
        """Step 6b: Sync promotion report into the ExecutionGuard.

        Reads the cached promotion report and updates the guard's view
        of which domains/agents are eligible.  Runs every 5 minutes.
        """
        guard = self._execution_guard()
        try:
            guard.sync_promotion_report()
            n_eligible = len(getattr(guard, '_promotion_eligible_domains', None) or set())
            n_blocked = len(getattr(guard, '_promotion_blocked_agents', None) or set())
            summary["actions"].append(
                f"promotion_synced:{n_eligible}eligible,{n_blocked}blocked_agents"
            )
            summary["promotion_sync"] = {
                "eligible_domains": n_eligible,
                "blocked_agents": n_blocked,
                "report_ts": getattr(guard, '_promotion_report_ts', None),
            }
        except Exception as e:
            logger.warning(f"Promotion sync failed: {e}")
            summary["actions"].append(f"promotion_sync:error:{e}")

    async def _reconcile_positions(self, summary: Dict):
        """Step 7: Compare internal vs venue positions.
        
        For domains with venue reconcilers, run deep comparison and gate
        execution if critical issues are detected.
        """
        try:
            # Run Kalshi reconciliation if prediction domain is active
            if "prediction" in self.config.active_domains and self.metrics.total_ticks >= 100:
                from merid.reconciliation import reconcile_venue, has_critical_discrepancies
                
                # Reconcile Kalshi positions
                # Run synchronous reconcile_venue in a thread — it internally
                # uses asyncio.run() which would deadlock if called from the
                # event loop thread (blocks via concurrent.futures.Future.result
                # for up to 30s, freezing the loop and defeating wait_for).
                discrepancies = await asyncio.to_thread(reconcile_venue, "kalshi")
                
                critical_count = sum(1 for d in discrepancies if d.severity == "critical")
                warning_count = sum(1 for d in discrepancies if d.severity == "warning")
                
                logger.info(
                    f"Kalshi reconciliation complete: "
                    f"{len(discrepancies)} discrepancies ({critical_count} critical, {warning_count} warnings)"
                )
                
                summary["actions"].append(
                    f"kalshi_reconciliation:{len(discrepancies)}total,{critical_count}critical"
                )
                
                # Gate execution if critical issues detected
                # In paper trading mode, reconciliation mismatches are expected
                # (paper positions don't exist on the live/demo venue)
                import os as _os
                _trading_mode = _os.getenv("MERID_PM_TRADING_MODE", "paper")
                if has_critical_discrepancies() and _trading_mode != "paper":
                    logger.error(
                        f"CRITICAL reconciliation issues detected for Kalshi. "
                        f"Blocking new executions until resolved."
                    )
                    guard = self._execution_guard()
                    if guard:
                        reason = f"{critical_count} critical discrepancies detected"
                        try:
                            guard.activate_domain_kill_switch("prediction", reason=reason)
                        except Exception as _ks_exc:
                            logger.debug("activate_domain_kill_switch failed: %s", _ks_exc)

                    summary["actions"].append(f"reconciliation:CRITICAL:blocked_prediction_domain")
                elif has_critical_discrepancies() and _trading_mode == "paper":
                    logger.info(
                        f"Reconciliation: {critical_count} critical discrepancies (expected in paper mode, not blocking)"
                    )
                    summary["actions"].append(f"reconciliation:paper_mode_ok:{critical_count}critical")
                elif warning_count > 0:
                    logger.warning(f"Reconciliation warnings for Kalshi: {warning_count} issues")
                    summary["actions"].append(f"reconciliation:WARNING:{warning_count}issues")
                else:
                    summary["actions"].append("reconciliation:OK")

                # Store summary for API exposure
                summary["reconciliation"] = {
                    "kalshi": {
                        "total": len(discrepancies),
                        "critical": critical_count,
                        "warnings": warning_count,
                    }
                }

                # BUG-H4 fix: sync actual Kalshi position notional into ExecutionGuard
                # so VenueExposureCap.current_exposure_usd reflects reality after
                # restarts and position closes, not just the additive fill counter.
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client as _gkc
                    _positions_result = await asyncio.wait_for(
                        _gkc().get_positions(), timeout=5.0
                    )
                    if _positions_result and hasattr(_positions_result, "data"):
                        _pos_list = _positions_result.data or []
                        _notional = sum(
                            abs(getattr(p, "total_cost", 0) or getattr(p, "notional", 0) or 0)
                            for p in _pos_list
                        )
                        self._execution_guard().sync_venue_exposure("kalshi", float(_notional) / 100.0)
                        summary["actions"].append(
                            f"kalshi_exposure_synced:${float(_notional)/100.0:.2f}"
                        )
                except Exception as _exp_exc:
                    logger.debug("Kalshi exposure sync skipped: %s", _exp_exc)

                self.metrics.reconciliations_run += 1
            else:
                summary["actions"].append("reconciliation:skipped")
                
        except Exception as exc:
            logger.error(f"Reconciliation failed: {exc}")
            summary["actions"].append(f"reconciliation:failed:{exc}")

    async def _sync_order_groups(self, summary: Dict):
        """Step 7b: Sync order group lifecycle state for Kalshi.

        Ensures order groups are tracked, validates active groups,
        and records fills for accurate utilization metrics.

        CPU-heavy lifecycle state processing is offloaded to thread pool
        to avoid blocking the event loop (BUG-EL12 fix).
        """
        import os as _os
        
        # PROFILING: Track entry
        _profiling = _os.getenv("MERID_PROFILING")
        _prof_entry_ts = time.perf_counter() if _profiling else 0
        
        # AGGRESSIVE: Skip order groups sync for first 100 ticks (~8.3 min)
        if self.metrics.total_ticks < 100:
            if _profiling:
                logger.debug("[PROF] order_groups:skipped_startup tick=%d", self.metrics.total_ticks)
            summary["actions"].append("order_groups:skipped_startup_cooldown")
            return

        try:
            og_lifecycle = self._order_group_lifecycle()
            
            # PHASE-3: Hard budget for order_groups — must complete within 1000ms
            ORDER_GROUPS_BUDGET_MS = 1000.0
            _og_budget_start = time.perf_counter()

            # Start lifecycle manager if not running (skip if previously failed)
            if not getattr(og_lifecycle, '_running', False):
                if getattr(self, '_og_start_failed', False):
                    summary["actions"].append("order_groups:skipped_ws_unavailable")
                    return
                try:
                    # PHASE-3: Add timeout to prevent indefinite blocking
                    # GAP-1 fix: lifecycle.start() could hang indefinitely
                    await asyncio.wait_for(og_lifecycle.start(), timeout=5.0)
                    summary["actions"].append("order_groups:lifecycle_started")
                except asyncio.TimeoutError:
                    self._og_start_failed = True
                    logger.error("[BUDGET] order_groups: lifecycle start timed out after 5s")
                    summary["actions"].append("order_groups:start_timeout")
                    return
                except Exception as start_exc:
                    self._og_start_failed = True
                    logger.info(f"Order group WS unavailable, will use REST only: {start_exc}")
                    summary["actions"].append("order_groups:ws_unavailable")
                    return
            
            # Check budget after lifecycle start
            _og_elapsed_ms = (time.perf_counter() - _og_budget_start) * 1000
            if _og_elapsed_ms > ORDER_GROUPS_BUDGET_MS:
                logger.error(
                    "[BUDGET] order_groups_budget_exceeded: lifecycle took %.1fms (budget %.0fms)",
                    _og_elapsed_ms, ORDER_GROUPS_BUDGET_MS
                )
                summary["actions"].append("order_groups:budget_exceeded")
                return

            # Get current state summary - offload sync processing to thread pool
            def _get_state_sync():
                # PHASE-3: Yield point before state retrieval (GAP-3 fix)
                time.sleep(0.001)
                return og_lifecycle.get_lifecycle_state()

            loop = asyncio.get_running_loop()
            
            # Check remaining budget before thread pool call
            _og_remaining_budget = ORDER_GROUPS_BUDGET_MS - ((time.perf_counter() - _og_budget_start) * 1000)
            if _og_remaining_budget < 200:  # Need at least 200ms for state retrieval
                logger.warning(
                    "[BUDGET] order_groups: insufficient budget for state retrieval (%.0fms remaining)",
                    _og_remaining_budget
                )
                summary["actions"].append("order_groups:insufficient_budget_for_state")
                return
            
            state = await loop.run_in_executor(_get_loop_executor(), _get_state_sync)

            # Add order group metrics to summary
            summary["order_groups"] = {
                "total_tracked": state.get("total_groups", 0),
                "active": state.get("active_groups", 0),
                "triggered_groups": len(state.get("triggered_groups", [])),
                "recent_errors": len(state.get("recent_errors", [])),
            }

            # Log status if there are triggered groups
            triggered = state.get("triggered_groups", [])
            if triggered:
                logger.warning(f"Order groups triggered: {triggered}")
                summary["actions"].append(f"order_groups:triggered:{len(triggered)}")
            else:
                summary["actions"].append("order_groups:synced")

        except Exception as exc:
            logger.warning(f"Order group sync failed: {exc}")
            summary["actions"].append(f"order_groups:sync_failed:{exc}")
        
        # PROFILING: Log structured metrics
        if _profiling:
            total_ms = (time.perf_counter() - _prof_entry_ts) * 1000
            logger.debug(
                "[PROF] order_groups action=%s duration_ms=%.1f lag_ms=%.1f",
                "order_groups", total_ms, self._get_event_loop_lag_ms()
            )

    # ── Subscriber pattern ────────────────────────────────────────────

    def subscribe(self, callback: Callable):
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable):
        self._subscribers.discard(callback)

    async def _notify(self, event_type: str, data: Any):
        """Notify all subscribers with timing and isolation.
        
        Sync callbacks run in thread pool to avoid blocking event loop.
        Slow subscribers are logged for identification.
        
        EVENT-LOOP-FIX: Added per-subscriber timeout and overall budget enforcement.
        """
        import asyncio
        step_start = time.perf_counter()
        notify_count = 0
        slow_subscribers = []
        timed_out_count = 0
        
        # Check lag before starting
        current_lag = self._get_event_loop_lag_ms()
        if current_lag > 1000:  # Skip notify entirely if lag is critical
            logger.warning(
                "[LAG-SKIP] action=notify reason=critical_lag "
                f"lag_ms={current_lag:.0f} threshold_ms=1000 subscriber_count={len(self._subscribers)}"
            )
            # Track skip metrics
            self.metrics.lag_skips_total = getattr(self.metrics, 'lag_skips_total', 0) + 1
            return
        
        # Per-subscriber timeout: max 100ms each
        _CB_TIMEOUT_S = 0.1
        # Overall budget: max 500ms total for all subscribers
        _TOTAL_BUDGET_MS = 500.0
        
        for cb in self._subscribers:
            # Check if we're over budget
            elapsed_ms = (time.perf_counter() - step_start) * 1000
            if elapsed_ms > _TOTAL_BUDGET_MS:
                logger.warning(f"[LAG-GUARD] notify exceeded budget ({_TOTAL_BUDGET_MS:.0f}ms), skipping {len(self._subscribers) - notify_count} remaining subscribers")
                break
            
            cb_start = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(cb):
                    # Add timeout for async callbacks
                    await asyncio.wait_for(cb(event_type, data), timeout=_CB_TIMEOUT_S)
                else:
                    # Run sync callbacks in dedicated thread pool with timeout
                    loop = asyncio.get_running_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(_get_loop_executor(), cb, event_type, data),
                        timeout=_CB_TIMEOUT_S
                    )
                notify_count += 1
            except asyncio.TimeoutError:
                timed_out_count += 1
                cb_ms = (time.perf_counter() - cb_start) * 1000
                slow_subscribers.append(f"{cb.__name__ if hasattr(cb, '__name__') else str(cb)[:30]}:TIMEOUT:{cb_ms:.0f}ms")
                logger.warning(f"[LAG-GUARD] Subscriber {cb.__name__ if hasattr(cb, '__name__') else str(cb)[:20]} timed out after {_CB_TIMEOUT_S*1000:.0f}ms")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Subscriber notification failed: {e}")
            
            # Track slow subscribers (>50ms)
            cb_ms = (time.perf_counter() - cb_start) * 1000
            if cb_ms > 50 and "TIMEOUT" not in str(slow_subscribers[-1:]):
                slow_subscribers.append(f"{cb.__name__ if hasattr(cb, '__name__') else str(cb)[:30]}:{cb_ms:.0f}ms")
        
        total_ms = (time.perf_counter() - step_start) * 1000
        # Log if slow or if there were slow subscribers or timeouts
        if total_ms > 100 or slow_subscribers or timed_out_count > 0:
            logger.debug("notify timings: total=%.0fms, count=%d/%d, timeouts=%d, slow=[%s]", 
                        total_ms, notify_count, len(self._subscribers), timed_out_count,
                        "; ".join(slow_subscribers[:3]))

    # ── Run forever ───────────────────────────────────────────────────

    async def run(self, max_ticks: Optional[int] = None):
        """Run the loop continuously until stopped or max_ticks reached."""
        self._running = True
        tick_count = 0
        min_interval = min(
            self.config.feature_refresh_interval,
            self.config.consensus_interval,
            self.config.arb_scan_interval,
        )
        # Run at least every 5s, at most every min_interval
        sleep_time = max(1.0, min(5.0, min_interval))

        # Log full domain coverage
        mode_str = ", ".join(
            f"{d}={self.config.domain_modes.get(d, 'paper')}"
            for d in self.config.active_domains
        ) if self.config.domain_modes else ", ".join(self.config.active_domains)
        recon_str = f", reconciliation_venues={self.config.reconciliation_venues}" if self.config.reconciliation_venues else ""
        logger.info(
            f"MERID loop starting: domains=[{mode_str}], "
            f"symbols={len(self.config.active_symbols)} active, "
            f"execution={'ON' if self.config.enable_execution else 'OFF'}, "
            f"cadence={sleep_time:.1f}s{recon_str}"
        )
        logger.info(f"  Active symbols: {self.config.active_symbols}")

        from merid.tick_log import build_tick_record, get_tick_log
        tick_log = get_tick_log()

        # Reuse HashtagMonitor singleton (already started by lifespan)
        # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent extreme event-loop lag
        self._hashtag_monitor = None
        import os as _os
        _is_validation = _os.environ.get("MERID_VALIDATION_MODE", "") == "1"
        if _is_validation:
            logger.info("[VALIDATION MODE] HashtagMonitor skip in MeridLoop (prevents 57s+ lag)")
        else:
            try:
                from merid.sentiment.hashtag_monitor import get_hashtag_monitor
                self._hashtag_monitor = get_hashtag_monitor()
                if not getattr(self._hashtag_monitor, '_running', False):
                    await self._hashtag_monitor.start()
                    logger.info("HashtagMonitor started alongside loop")
                else:
                    logger.debug("HashtagMonitor already running (started by lifespan)")
            except Exception as _hme:
                logger.warning("HashtagMonitor start skipped: %s", _hme)
                self._hashtag_monitor = None

        # Reuse the singleton WS bridge from lifespan — never create a second instance
        self._ws_bridge = None
        if "prediction" in self.config.active_domains:
            try:
                from merid.event_venues.kalshi.ws_bridge import get_ws_bridge as _get_bridge
                self._ws_bridge = _get_bridge()
                logger.debug("KalshiWebSocketBridge: reusing lifespan singleton (running=%s)", self._ws_bridge.is_running())
            except Exception as _wse:
                logger.warning("KalshiWebSocketBridge reference skipped: %s", _wse)
                self._ws_bridge = None

        # A1: Start ExecutionSubscriber so bus-routed Decisions are processed.
        # Only started when execution is enabled to avoid dead subscriber overhead.
        self._execution_subscriber = None
        if self.config.enable_execution and "prediction" in self.config.active_domains:
            try:
                from merid.swarm.execution_subscriber import get_execution_subscriber
                self._execution_subscriber = get_execution_subscriber()
                await self._execution_subscriber.start()
                logger.info("ExecutionSubscriber started alongside loop")
            except Exception as _ese:
                logger.warning("ExecutionSubscriber start skipped: %s", _ese)
                self._execution_subscriber = None

        while self._running:
            summary = await self.tick()
            tick_count += 1

            # Persist structured tick record
            try:
                record = build_tick_record(summary)
                record.kill_switch_active = self._execution_guard().kill_switch_active
                tick_log.append(record)
            except Exception as e:
                logger.warning(f"Tick log write failed: {e}")

            if max_ticks and tick_count >= max_ticks:
                logger.info(f"Reached max_ticks={max_ticks}, stopping")
                self._running = False
                break

            await asyncio.sleep(sleep_time)

        self._running = False
        logger.info(f"MERID loop stopped after {tick_count} ticks")

        # BUG-H8 fix: drain in-flight background tasks before releasing shared
        # singletons.  Give them up to 6s (just over _STEP_TIMEOUT_S=5s) to
        # finish naturally, then cancel so they don't submit orders into a
        # disconnected Kalshi client.
        _bg_tasks = [
            t for t in (self._agent_bg_task, self._promo_bg_task)
            if t is not None and not t.done()
        ]
        if _bg_tasks:
            logger.info(
                "Waiting up to 6s for %d background task(s) to finish...", len(_bg_tasks)
            )
            try:
                done, pending = await asyncio.wait(_bg_tasks, timeout=6.0)
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
                if pending:
                    logger.warning(
                        "%d background task(s) cancelled (did not finish in time)", len(pending)
                    )
            except Exception as _drain_exc:
                logger.debug("Background task drain error: %s", _drain_exc)

        # A1: Stop ExecutionSubscriber cleanly before releasing other singletons.
        if self._execution_subscriber is not None:
            try:
                await self._execution_subscriber.stop()
                logger.info("ExecutionSubscriber stopped")
            except Exception as _es_stop_exc:
                logger.debug("ExecutionSubscriber stop error: %s", _es_stop_exc)
            self._execution_subscriber = None

        # Release references — actual .stop() is handled by _app_lifespan shutdown
        # to avoid double-stop errors on the shared singletons.
        self._hashtag_monitor = None
        self._ws_bridge = None

    def stop(self):
        """Signal the loop to stop after the current tick."""
        self._running = False
    
    async def shutdown(self, timeout: float = 10.0) -> None:
        """Graceful shutdown with background task cleanup.
        
        EVENT-LOOP-FIX: Cancels and awaits background tasks to prevent
        dangling work during loop closure.
        
        Args:
            timeout: Max seconds to wait for background tasks
        """
        import asyncio
        logger.info(f"[SHUTDOWN] Initiating graceful shutdown (timeout={timeout}s)")
        self._running = False
        
        # Collect background tasks to cancel
        bg_tasks = []
        if self._agent_bg_task and not self._agent_bg_task.done():
            bg_tasks.append(("agent_cycles", self._agent_bg_task))
        if self._promo_bg_task and not self._promo_bg_task.done():
            bg_tasks.append(("promotion_sync", self._promo_bg_task))
        
        if bg_tasks:
            logger.info(f"[SHUTDOWN] Cancelling {len(bg_tasks)} background tasks: {[n for n,_ in bg_tasks]}")
            for name, task in bg_tasks:
                task.cancel()
            
            # Await with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[t for _, t in bg_tasks], return_exceptions=True),
                    timeout=timeout
                )
                logger.info("[SHUTDOWN] Background tasks cancelled successfully")
            except asyncio.TimeoutError:
                logger.warning(f"[SHUTDOWN] Timeout waiting for background tasks after {timeout}s")
        
        logger.info("[SHUTDOWN] Complete")

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "config": {
                "active_domains": self.config.active_domains,
                "domain_modes": self.config.domain_modes,
                "active_symbols": self.config.active_symbols,
                "execution_enabled": self.config.enable_execution,
                "reconciliation_venues": self.config.reconciliation_venues,
            },
            "metrics": self.metrics.to_dict(),
        }


# ── Singleton ─────────────────────────────────────────────────────────

_loop: Optional[MeridLoop] = None
_loop_lock = threading.Lock()  # F7: guard against concurrent startup races


def get_merid_loop() -> MeridLoop:
    global _loop
    if _loop is None:
        with _loop_lock:
            if _loop is None:
                try:
                    config = LoopConfig.from_paper_config()
                except Exception as _cfg_exc:
                    logger.warning(f"LoopConfig.from_paper_config() failed, using defaults: {_cfg_exc}")
                    config = LoopConfig()
                _loop = MeridLoop(config)
    return _loop


# ── CLI entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Default: load from paper_config matrix (single source of truth)
    if "--legacy" in sys.argv:
        config = LoopConfig()
    else:
        config = LoopConfig.from_paper_config()

    if "--execute" in sys.argv:
        config.enable_execution = True
        logger.info("Execution ENABLED — trades will be submitted to venues")

    if "--domains" in sys.argv:
        idx = sys.argv.index("--domains") + 1
        if idx < len(sys.argv):
            requested = sys.argv[idx].split(",")
            config.active_domains = [d for d in config.active_domains if d in requested]
            config.domain_modes = {k: v for k, v in config.domain_modes.items() if k in requested}

    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols") + 1
        if idx < len(sys.argv):
            config.active_symbols = sys.argv[idx].split(",")

    loop = MeridLoop(config)

    try:
        asyncio.run(loop.run())
    except KeyboardInterrupt:
        logger.info("MERID loop interrupted")
        loop.stop()
