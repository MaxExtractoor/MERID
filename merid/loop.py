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
# 24/7-SCALPER-FIX (2026-05-02): Raised to 15000ms for continuous 15m scalping.
# BUG-FIX (2026-05-06): Increased to 20000ms to prevent warnings for arb_scan/notify (legitimately 4-6s)
# Features/consensus/notify can legitimately take 10-15s during high-frequency trading cycles.
_SLOW_ACTION_BUDGET_MS = float(os.getenv("MERID_LOOP_SLOW_ACTION_BUDGET_MS", "20000"))  # was 15000, now 20000

# Dedicated thread pool for CPU-heavy operations — avoids saturating default executor
_loop_executor: Optional[ThreadPoolExecutor] = None

# CRYPTO-15M-ARB: Separate thread pool for arb_scan to isolate from agent cycles
_arb_executor: Optional[ThreadPoolExecutor] = None

def _get_loop_executor() -> ThreadPoolExecutor:
    """Get or create the dedicated loop executor with 48 workers.
    
    DISABLED - use default executor (None) to avoid Windows event loop issues.
    """
    return None


def _get_arb_executor() -> ThreadPoolExecutor:
    """Get or create the dedicated arb_scan executor.
    
    CRYPTO-15M-ARB: Isolated pool prevents arb_scan from blocking agent cycles.
    """
    global _arb_executor
    if _arb_executor is None or _arb_executor._shutdown:
        # 4 workers is plenty for crypto 15m scanning (5 symbols, limited pairs)
        _arb_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="merid_arb")
    return _arb_executor


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
    consensus_interval: float = 120.0  # CRYPTO-15M-ARB: Increased from 60s to 120s to reduce CPU strain
    arb_scan_interval: float = float(os.getenv("MERID_ARB_SCAN_INTERVAL_S", "120"))  # Was 8000ms+ blocks at 10s
    cqi_interval: float = 300.0
    reconciliation_interval: float = 120.0

    # Feature flags
    enable_execution: bool = False        # Must be explicitly enabled
    enable_arb_execution: bool = False
    enable_reconciliation: bool = True
    enable_notifications: bool = True

    # Domains to run
    active_domains: List[str] = field(default_factory=lambda: ["crypto", "prediction"])
    active_symbols: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])

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
                    # "BTC/USD" -> "BTC", "AAPL" -> "AAPL"
                    short = s.split("/")[0] if "/" in s else s
                    price_symbols.append(short)
        
        # CRITICAL FIX: Derive crypto assets from catalog for prediction domain
        # paper_config has symbols=[] for prediction (dynamic), so get assets from catalog
        if any(d.name == "prediction" and d.enabled for d in pc.active_domains()):
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                catalog_assets = list(catalog.asset_index.keys())
                # Add catalog crypto assets to price_symbols
                price_symbols.extend([a for a in catalog_assets if a not in price_symbols])
            except Exception as _e:
                # Fallback to hardcoded list if catalog unavailable
                price_symbols.extend(["BTC", "ETH", "SOL", "XRP", "DOGE"])

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
            # CRYPTO-15M-ARB: Increased from 10s to 120s to reduce CPU strain
            arb_scan_interval=float(os.getenv("MERID_ARB_SCAN_INTERVAL_S", "120")),
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
    """Tracks loop performance and health.
    
    EVENT-LOOP-FIX: Added metrics for timeout counts, lag skips, and queue depth
    for better observability during high-load conditions.
    """
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
    
    # EVENT-LOOP-FIX: New metrics for observability under load
    timeout_count: int = 0  # Total step timeouts
    lag_skip_count: int = 0  # Steps skipped due to high loop lag
    slow_action_skips: int = 0  # Steps skipped due to recent slowness
    global_tick_timeouts: int = 0  # Full tick global timeouts
    last_lag_ms: float = 0.0  # Last recorded loop lag

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
            # EVENT-LOOP-FIX: New observability metrics
            "timeout_count": self.timeout_count,
            "lag_skip_count": self.lag_skip_count,
            "slow_action_skips": self.slow_action_skips,
            "global_tick_timeouts": self.global_tick_timeouts,
            "last_lag_ms": round(self.last_lag_ms, 1),
        }


# ── Main Loop ─────────────────────────────────────────────────────────

class MeridLoop:
    """Persistent orchestrator that drives the MERID swarm.

    EVENT-LOOP ARCHITECTURE:
    - This class runs ON the main asyncio event loop, NOT in a separate thread
    - All periodic tasks use asyncio.sleep() for cooperative scheduling
    - CPU-bound work (arb_scan, agent_cycles) is offloaded via run_in_executor()
    - Each tick step has a strict timeout to prevent event-loop starvation

    SCHEDULED TASKS:
    - tick(): Main orchestration cycle (every ~5-30s based on config)
    - _run_step(): Individual step execution with timeout guards
    - Background tasks: agent_cycles, promotion_sync (fire-and-forget)

    LAG DETECTION INTEGRATION:
    - Slow actions are tracked and adaptively skipped if recently slow
    - Global tick timeout prevents any single tick from starving the loop
    - Per-step timing metrics are exposed for diagnostics

    SHUTDOWN POLICY:
    - stop() gracefully cancels the main loop
    - Never initiates shutdown directly - reports health for external decision

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
        # BUG-EL FIX: Increased cooldown from 60s to 120s to give system more recovery time
        self._SLOW_ACTION_COOLDOWN_S = 120.0  # skip slow action for 120s after it exceeds budget

        # EVENT-LOOP-FIX: Lag circuit breaker for event loop health degradation
        # Tracks recent lag measurements to trigger soft degradation or restart
        self._lag_history: List[float] = []  # Recent lag measurements (ms)
        self._LAG_CIRCUIT_WINDOW_S = 60.0  # 60-second window for lag tracking
        self._LAG_SOFT_THRESHOLD_MS = 250.0  # Soft degradation: skip non-critical work
        self._LAG_HARD_THRESHOLD_MS = 1000.0  # Hard: force component restart
        self._lag_circuit_tripped = False
        self._lag_circuit_reset_ts: Optional[float] = None
        self._LAG_CIRCUIT_COOLDOWN_S = 30.0  # 30s cooldown after hard trip

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

        # Log lane and agent registration for debugging
        self._lanes: Dict[str, Any] = {}
        self._agents: List[Any] = []
        logger.info("[MERID-LOOP-INIT] lanes=%s agents=%s", sorted(self._lanes.keys()), len(self._agents))

        # WATCHDOG: Error budget and stall detection
        self._tick_errors: List[float] = []  # timestamps of recent tick errors
        self._last_tick_time: Optional[float] = None  # timestamp of last successful tick
        self._WATCHDOG_ERROR_BUDGET = 5  # max errors allowed in window
        self._WATCHDOG_ERROR_WINDOW_S = 300.0  # 5-minute window for error budget
        self._WATCHDOG_STALL_THRESHOLD_S = 60.0  # 60 seconds without successful tick = stall

        # MONITORING: Aggregate stats tracking
        self._tick_trades_count = 0  # trades in current tick
        self._aggregate_trades_since_start = 0  # total trades since start
        self._last_aggregate_log_tick = 0  # tick index of last aggregate log

        # P1-4: Log structured startup snapshot for kalshi_crypto_15m_v2 profile
        self._log_kalshi_startup_snapshot()

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

    def _check_watchdog(self, now: float) -> None:
        """Check error budget and stall detection.
        
        Enforces:
        - Error budget: if > N errors in last M minutes, halt
        - Stall detection: if no successful tick in threshold, log stall
        
        Args:
            now: Current timestamp
        """
        import time
        
        # Clean old errors outside the window
        window_start = now - self._WATCHDOG_ERROR_WINDOW_S
        self._tick_errors = [ts for ts in self._tick_errors if ts > window_start]
        
        # Check error budget
        error_count = len(self._tick_errors)
        if error_count >= self._WATCHDOG_ERROR_BUDGET:
            logger.critical(
                "[WATCHDOG] Error budget exceeded: %d errors in last %.1fs (budget=%d)",
                error_count, self._WATCHDOG_ERROR_WINDOW_S, self._WATCHDOG_ERROR_BUDGET
            )
            logger.critical("[WATCHDOG] Halting MeridLoop - too many tick errors")
            self._running = False
            return
        
        # Check stall detection
        if self._last_tick_time is not None:
            time_since_last_tick = now - self._last_tick_time
            if time_since_last_tick > self._WATCHDOG_STALL_THRESHOLD_S:
                logger.warning(
                    "[WATCHDOG] Stall detected: %.1fs since last successful tick (threshold=%.1fs)",
                    time_since_last_tick, self._WATCHDOG_STALL_THRESHOLD_S
                )
            elif error_count > 0:
                logger.info(
                    "[WATCHDOG] Health check: %d errors in window, %.1fs since last tick",
                    error_count, time_since_last_tick
                )

    def _compute_profile_signature(self) -> dict:
        """Compute a signature dict of critical profile parameters.
        
        This captures the key risk/edge/distance parameters that should not change
        unexpectedly. Used to detect configuration drift between runs.
        """
        signature = {}
        
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            
            # Venue caps
            signature['max_single_order_notional_usd'] = round(envelope.max_single_order_notional_usd, 2)
            signature['max_total_notional_usd'] = round(envelope.max_total_notional_usd, 2)
            signature['max_concurrent_trades'] = envelope.max_concurrent_trades
            signature['max_daily_loss_usd'] = round(envelope.max_daily_loss_usd, 2)
            signature['drawdown_halt_pct'] = round(envelope.drawdown_halt_pct, 4)
            signature['drawdown_unwind_pct'] = round(envelope.drawdown_unwind_pct, 4)
            
            # Per-asset caps
            signature['asset_caps'] = {
                asset: round(cap, 2) 
                for asset, cap in envelope.asset_max_notional_usd.items()
            }
        except Exception as e:
            logger.warning("[PROFILE-SIGNATURE] Failed to include envelope params: %s", e)
        
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            adapter = get_active_profile()
            if adapter:
                p = adapter.profile
                
                # Edge thresholds per asset
                signature['edge_thresholds'] = {}
                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
                    if asset in p.asset_configs:
                        ac = p.asset_configs[asset]
                        signature['edge_thresholds'][asset] = {
                            'early': round(ac.min_edge_early, 4),
                            'mid': round(ac.min_edge_mid, 4),
                            'late': round(ac.min_edge_late, 4),
                            'terminal': round(ac.min_edge_terminal, 4),
                        }
                
                # Kelly parameters
                signature['kelly'] = {
                    'hard_cap': round(p.kelly_hard_cap, 4),
                    'min_edge': round(p.kelly_min_edge_pct, 4),
                    'max_edge': round(p.kelly_max_edge_pct, 4),
                }
        except Exception as e:
            logger.warning("[PROFILE-SIGNATURE] Failed to include edge thresholds: %s", e)
        
        return signature
    
    def _log_profile_diff(self, current: dict, previous: dict) -> None:
        """Log differences between current and previous profile signatures.
        
        Args:
            current: Current profile signature dict
            previous: Previous profile signature dict (may be None)
        """
        if previous is None:
            logger.info("[PROFILE-DIFF] No previous snapshot found - creating baseline")
            return
        
        logger.info("=" * 80)
        logger.info("[PROFILE-DIFF] Configuration Change Detection")
        logger.info("=" * 80)
        
        changes = []
        
        # Compare top-level keys
        for key in set(current.keys()) | set(previous.keys()):
            if key not in previous:
                changes.append(f"  + {key}: {current[key]} (new)")
            elif key not in current:
                changes.append(f"  - {key}: {previous[key]} (removed)")
            elif current[key] != previous[key]:
                changes.append(f"  ~ {key}: {previous[key]} → {current[key]}")
        
        # Compare nested dicts
        for key in ['asset_caps', 'edge_thresholds', 'kelly']:
            if key in current or key in previous:
                curr_nested = current.get(key, {})
                prev_nested = previous.get(key, {})
                
                if curr_nested != prev_nested:
                    changes.append(f"  ~ {key}: {prev_nested} → {curr_nested}")
        
        if changes:
            logger.warning("[PROFILE-DIFF] %d parameter changes detected:", len(changes))
            for change in changes:
                logger.warning(change)
            logger.warning("[PROFILE-DIFF] Review these changes to ensure they are intentional")
        else:
            logger.info("[PROFILE-DIFF] No parameter changes detected")
        
        logger.info("=" * 80)
    
    def _save_profile_snapshot(self, signature: dict) -> None:
        """Save current profile signature to disk for next-run comparison.
        
        Args:
            signature: Current profile signature dict
        """
        try:
            from pathlib import Path
            import json
            from datetime import datetime
            
            snapshot_dir = Path("data/profile_snapshots")
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            # Save with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_file = snapshot_dir / f"kalshi_crypto_15m_{timestamp}.json"
            
            with open(snapshot_file, 'w') as f:
                json.dump({
                    'timestamp': timestamp,
                    'signature': signature
                }, f, indent=2)
            
            # Update "last.json" symlink/copy
            last_file = snapshot_dir / "last.json"
            with open(last_file, 'w') as f:
                json.dump({
                    'timestamp': timestamp,
                    'signature': signature
                }, f, indent=2)
            
            logger.info("[PROFILE-SNAPSHOT] Saved to %s", snapshot_file)
        except Exception as e:
            logger.warning("[PROFILE-SNAPSHOT] Failed to save snapshot: %s", e)

    def _log_kalshi_startup_snapshot(self) -> None:
        """Log structured startup snapshot for kalshi_crypto_15m_v2 profile.
        
        P1-4: This provides a single unified log showing the complete configuration
        flow from profile → envelope → capabilities → agents for observability.
        """
        import os
        profile = os.getenv("MERID_PROFILE", "").lower()
        
        # Only log for kalshi_crypto_15m_v2 profile
        if profile != "kalshi_crypto_15m_v2":
            return
        
        logger.info("=" * 80)
        logger.info("[STARTUP-SNAPSHOT] Kalshi 15m Crypto Profile Configuration")
        logger.info("=" * 80)
        
        # Log profile configuration
        logger.info("[PROFILE] MERID_PROFILE=%s", profile)
        logger.info("[PROFILE] MERID_PM_PROFILE=%s", os.getenv("MERID_PM_PROFILE", "baseline"))
        logger.info("[PROFILE] KALSHI_ENV=%s", os.getenv("KALSHI_ENV", "production"))
        
        # Profile diff detection
        try:
            from pathlib import Path
            import json
            
            # Compute current signature
            current_signature = self._compute_profile_signature()
            
            # Load previous signature
            previous_signature = None
            last_file = Path("data/profile_snapshots/last.json")
            if last_file.exists():
                with open(last_file) as f:
                    data = json.load(f)
                    previous_signature = data.get('signature')
            
            # Log diff
            self._log_profile_diff(current_signature, previous_signature)
            
            # Save current signature
            self._save_profile_snapshot(current_signature)
        except Exception as e:
            logger.warning("[PROFILE-DIFF] Failed to compute/log profile diff: %s", e)
        
        # Log risk envelope
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            logger.info("[ENVELOPE] profile_capital_usd=$%.2f", envelope.profile_capital_usd)
            logger.info("[ENVELOPE] live_bankroll_usd=$%.2f", envelope.live_bankroll_usd)
            logger.info("[ENVELOPE] max_single_order_notional_usd=$%.2f", envelope.max_single_order_notional_usd)
            logger.info("[ENVELOPE] max_total_notional_usd=$%.2f", envelope.max_total_notional_usd)
            logger.info("[ENVELOPE] max_concurrent_trades=%d", envelope.max_concurrent_trades)
            logger.info("[ENVELOPE] agent_max_notional_usd=$%.2f", envelope.agent_max_notional_usd)
            logger.info("[ENVELOPE] max_daily_loss_usd=$%.2f", envelope.max_daily_loss_usd)
            logger.info("[ENVELOPE] drawdown_halt_pct=%.2f%%", envelope.drawdown_halt_pct * 100)
            logger.info("[ENVELOPE] drawdown_unwind_pct=%.2f%%", envelope.drawdown_unwind_pct * 100)
            
            # Log per-asset caps
            logger.info("[ENVELOPE] Per-asset caps:")
            for asset, cap in envelope.asset_max_notional_usd.items():
                logger.info("[ENVELOPE-ASSET] %s: max_notional=$%.2f (%.1f%% of envelope capital)", 
                           asset, cap, (cap / envelope.profile_capital_usd * 100))
        except Exception as e:
            logger.warning("[STARTUP-SNAPSHOT] Failed to load risk envelope: %s", e)
        
        # Log capability maps
        try:
            from merid.guardrails.capabilities import get_capability_store
            cap_store = get_capability_store()
            stats = cap_store.get_stats()
            logger.info("[CAPABILITIES] total_agents=%d", stats.get("total_agents", 0))
            logger.info("[CAPABILITIES] by_max_scope=%s", stats.get("by_max_scope", {}))
            
            # Log each Kalshi PM agent capability
            kalshi_agents = [aid for aid in cap_store.list_agents() if "kalshi" in aid.lower() and "15m" in aid.lower()]
            for agent_id in kalshi_agents:
                cap_map = cap_store.get(agent_id)
                if cap_map:
                    logger.info(
                        "[CAPABILITY] agent=%s max_scope=%s max_notional=$%.2f tools=%d",
                        cap_map.agent_id,
                        cap_map.max_scope,
                        cap_map.max_notional_usd,
                        len(cap_map.allowed_tools)
                    )
        except Exception as e:
            logger.warning("[STARTUP-SNAPSHOT] Failed to load capability maps: %s", e)
        
        # Log paper session state
        try:
            from merid.prediction.paper_session import get_paper_session
            ps = get_paper_session()
            if ps:
                logger.info("[PAPER-SESSION] session_id=%s", ps._session_id)
                logger.info("[PAPER-SESSION] intervals=%d", len(ps._intervals))
                logger.info("[PAPER-SESSION] live_promoted=%d", len(ps._live_promoted))
        except Exception as e:
            logger.debug("[STARTUP-SNAPSHOT] Paper session not available: %s", e)
        
        # Log edge thresholds from profile YAML
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            adapter = get_active_profile()
            if adapter:
                p = adapter.profile
                logger.info("[THRESHOLDS] Per-asset edge thresholds from profile YAML:")
                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
                    if asset in p.asset_configs:
                        ac = p.asset_configs[asset]
                        logger.info(
                            "[THRESHOLD] %s: min_edge_early=%.2f%%, min_edge_mid=%.2f%%, min_edge_late=%.2f%%, min_edge_terminal=%.2f%%",
                            asset, ac.min_edge_early * 100, ac.min_edge_mid * 100, ac.min_edge_late * 100, ac.min_edge_terminal * 100
                        )
                logger.info("[THRESHOLDS] Kelly: hard_cap=%.2f%%, min_edge=%.2f%%, max_edge=%.2f%%", 
                           p.kelly_hard_cap * 100, p.kelly_min_edge_pct, p.kelly_max_edge_pct)
                logger.info("[THRESHOLDS] Max price caps: BTC/ETH/SOL/XRP=55¢, DOGE=50¢")
        except Exception as e:
            logger.debug("[STARTUP-SNAPSHOT] Thresholds not available: %s", e)
        
        logger.info("=" * 80)
        logger.info("[STARTUP-SNAPSHOT] End of configuration snapshot")
        logger.info("=" * 80)

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

    # OLD-HARDWARE FIX: Raised from 3s to 8s for weak hardware + spotty internet
    _STEP_TIMEOUT_S = float(os.getenv("MERID_LOOP_STEP_TIMEOUT_S", "8"))  # was 3s, now 8s
    # Step-specific timeout overrides (can be customized via env var as JSON)
    # OLD-HARDWARE FIX: Doubled all timeouts for unreliable networks and slow CPUs
    # BUG-FIX: Increased reconciliation timeout to 30s to prevent timeout errors during slow REST calls
    _STEP_TIMEOUT_OVERRIDES = json.loads(os.getenv(
        "MERID_LOOP_STEP_TIMEOUT_OVERRIDES",
        '{"features": 30, "agent_cycles": 40, "promotion_sync": 20, "liquidity": 20, "betting": 30, "reconciliation": 30, "arb_scan": 20, "consensus": 16, "notify": 5, "cqi": 20, "order_groups": 10}'
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

    def _record_lag(self, lag_ms: float) -> None:
        """Record lag measurement for circuit breaker tracking.
        
        EVENT-LOOP-FIX: Maintains rolling window of lag measurements.
        """
        now = time.time()
        self._lag_history.append((now, lag_ms))
        # Prune old measurements outside the window
        cutoff = now - self._LAG_CIRCUIT_WINDOW_S
        self._lag_history = [(ts, lag) for ts, lag in self._lag_history if ts > cutoff]
    
    def _check_lag_circuit_breaker(self) -> tuple[str, float]:
        """Check if lag circuit breaker should trip.
        
        Returns:
            Tuple of (status, avg_lag_ms) where status is:
            - "ok": Normal operation
            - "soft": Soft degradation (skip non-critical work)
            - "hard": Hard limit (restart recommended)
        """
        now = time.time()
        
        # Check if we're in cooldown after hard trip
        if self._lag_circuit_tripped:
            if self._lag_circuit_reset_ts and now < self._lag_circuit_reset_ts:
                remaining = self._lag_circuit_reset_ts - now
                return ("cooldown", remaining)
            # Reset the circuit breaker
            self._lag_circuit_tripped = False
            self._lag_circuit_reset_ts = None
            self._lag_history.clear()
            logger.warning("[LAG-CIRCUIT] Reset after cooldown period")
        
        if not self._lag_history:
            return ("ok", 0.0)
        
        # Calculate average lag over recent window
        recent_lags = [lag for ts, lag in self._lag_history[-10:]]  # Last 10 measurements
        avg_lag = sum(recent_lags) / len(recent_lags)
        
        # Check for hard threshold (sustained high lag)
        sustained_high = all(lag > self._LAG_HARD_THRESHOLD_MS for ts, lag in self._lag_history[-5:])
        if sustained_high:
            self._lag_circuit_tripped = True
            self._lag_circuit_reset_ts = now + self._LAG_CIRCUIT_COOLDOWN_S
            logger.critical(
                "[LAG-CIRCUIT] HARD TRIP — avg lag %.0fms over last %d measurements exceeds %.0fms threshold — "
                "initiating cooldown for %.0fs",
                avg_lag, len(self._lag_history[-5:]), self._LAG_HARD_THRESHOLD_MS, self._LAG_CIRCUIT_COOLDOWN_S
            )
            return ("hard", avg_lag)
        
        # Check for soft threshold (elevated but not critical)
        if avg_lag > self._LAG_SOFT_THRESHOLD_MS:
            return ("soft", avg_lag)
        
        return ("ok", avg_lag)

    async def _run_step(self, name: str, coro, summary: Dict) -> None:
        """Execute a single loop step with isolation — errors are logged
        and recorded in the summary but never propagate to crash the tick."""
        logger.info("[RUN-STEP] Starting step: %s", name)
        timeout = self._STEP_TIMEOUT_OVERRIDES.get(name, self._STEP_TIMEOUT_S)
        step_start = time.perf_counter()
        sub_timings: Dict[str, float] = {}

        try:
            # Wrap coro to capture sub-step timing if it supports it
            if hasattr(coro, '__self__') and hasattr(coro.__self__, '_sub_timings'):
                coro.__self__._sub_timings = sub_timings

            await asyncio.wait_for(coro, timeout=timeout)
            # TEMPORARILY DISABLED FOR DEBUGGING - asyncio.sleep(0.05) may cause event loop starvation on Windows
            # await asyncio.sleep(0.05)  # yield 50ms to event loop so HTTP stays responsive
            logger.info("[RUN-STEP] Completed step: %s", name)
        except asyncio.TimeoutError:
            self.metrics.total_errors += 1
            self.metrics.timeout_count += 1  # EVENT-LOOP-FIX: Track timeout count
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
        
        EVENT-LOOP-FIX: Added hard global timeout around entire tick to prevent
        any single tick from starving the event loop.

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
            
            # OLD-HARDWARE FIX: Raised from 60s to 120s for weak hardware
            # Prevents a tick from running indefinitely and starving the event loop
            _TICK_GLOBAL_TIMEOUT_S = float(os.getenv("MERID_TICK_GLOBAL_TIMEOUT_S", "120"))
            tick_start = time.perf_counter()
            now = time.time()  # Initialize current timestamp
            
            try:
                return await asyncio.wait_for(self._tick_body(now), timeout=_TICK_GLOBAL_TIMEOUT_S)
            except asyncio.TimeoutError:
                # Global tick timeout - this is a serious issue
                elapsed = time.perf_counter() - tick_start
                logger.critical(
                    "[TICK-TIMEOUT] Global tick timeout after %.1fs (limit %.0fs) — "
                    "event loop was stalled, forcing tick termination",
                    elapsed, _TICK_GLOBAL_TIMEOUT_S
                )
                self.metrics.total_errors += 1
                self.metrics.global_tick_timeouts += 1  # EVENT-LOOP-FIX: Track global timeout
                self.metrics.last_error = f"tick_global_timeout:{elapsed:.1f}s"
                return {
                    "tick": "timeout",
                    "reason": "global_tick_timeout",
                    "elapsed_seconds": round(elapsed, 1),
                    "timeout_seconds": _TICK_GLOBAL_TIMEOUT_S,
                    "actions": ["tick_aborted:global_timeout"]
                }
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
        
        # EVENT-LOOP-FIX: Record current lag for observability and circuit breaker
        current_lag_ms = self._get_event_loop_lag_ms()
        self.metrics.last_lag_ms = current_lag_ms
        self._record_lag(current_lag_ms)
        
        # Check lag circuit breaker for soft/hard degradation
        lag_status, lag_value = self._check_lag_circuit_breaker()
        if lag_status == "hard":
            # Hard trip: Skip all non-critical work this tick
            logger.critical(
                "[TICK-LAG-HARD] Skipping non-critical steps due to sustained high lag (%.0fms)",
                lag_value
            )
            summary["actions"].append(f"lag_circuit_hard:{lag_value:.0f}ms")
            # Only run critical steps (reconciliation, execution guard check)
            # Skip all parallel work
            parallel_coros = []
        elif lag_status == "soft":
            # Soft trip: Log warning and skip optional work
            if self.metrics.total_ticks % 10 == 0:  # Log every 10 ticks to avoid spam
                logger.warning(
                    "[TICK-LAG-SOFT] Elevated lag detected (%.0fms) — skipping optional features",
                    lag_value
                )
            summary["actions"].append(f"lag_circuit_soft:{lag_value:.0f}ms")
        elif lag_status == "cooldown":
            # In cooldown from hard trip
            summary["actions"].append(f"lag_circuit_cooldown:{lag_value:.0f}s_remaining")

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
        # FIX-3: Log stage boundary - DISCOVER stage starts here
        logger.info(
            "[CYCLE-TRACE] stage=DISCOVER_START | tick=%d | mode=%s | correlation_id=%s",
            tick_number, _mode, summary.get("correlation_id", "unknown")
        )
        if now - self._last_agent_cycle >= self.config.agent_cycle_interval:
            if self._agent_bg_task is None or self._agent_bg_task.done():
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
        # EVENT-LOOP-FIX: Initialize empty, conditionally populate based on lag circuit

        parallel_coros = []
        _skip_optional_due_to_lag = lag_status in ("hard", "soft", "cooldown")

        if now - self._last_feature_refresh >= self.config.feature_refresh_interval:
            # FIX-3: Log stage boundary - ANALYZE stage
            logger.info(
                "[CYCLE-TRACE] stage=ANALYZE_START | tick=%d | correlation_id=%s",
                tick_number, summary.get("correlation_id", "unknown")
            )
            parallel_coros.append(self._refresh_features(now, summary))

        if now - self._last_consensus >= self.config.consensus_interval:
            # FIX-3: Log stage boundary - CONSENSUS stage
            logger.info(
                "[CYCLE-TRACE] stage=CONSENSUS_START | tick=%d | correlation_id=%s",
                tick_number, summary.get("correlation_id", "unknown")
            )
            parallel_coros.append(self._run_consensus(summary))

        if now - self._last_arb_scan >= self.config.arb_scan_interval:
            parallel_coros.append(self._run_arb_scan(now, summary))

        logger.info("[LOOP] Checking liquidity refresh interval")
        if now - self._last_liquidity_refresh >= self._liquidity_refresh_interval:
            parallel_coros.append(self._refresh_liquidity(now, summary))
        else:
            logger.info("[LOOP] Liquidity refresh interval not passed")

        if now - self._last_cqi_update >= self.config.cqi_interval:
            parallel_coros.append(self._update_cqi(now, summary))

        # BUG-EL13 FIX: Added interval gate and slow-skip for order_groups
        if "prediction" in self.config.active_domains and now - self._last_order_groups_sync >= self._order_groups_sync_interval:
            parallel_coros.append(self._sync_order_groups(summary))

        if parallel_coros:
            logger.info("[LOOP] About to gather %d parallel coros", len(parallel_coros))
            await asyncio.gather(*parallel_coros)
            logger.info("[LOOP] Completed parallel coros gather")

        # ── Sequential post-steps (state-mutating, order matters) ────
        # BUG-H5+H6 fix: reconciliation MUST run before execution so that
        # has_critical_discrepancies() and VenueExposureCap are fresh when
        # _execute_plans checks them.  Previously reconciliation was in the
        # parallel batch (step 7) while execution ran at step 5 — wrong order.
        if self.config.enable_reconciliation and now - self._last_reconciliation >= self.config.reconciliation_interval:
            # FIX-3: Log stage boundary - MONITOR stage
            logger.info(
                "[CYCLE-TRACE] stage=MONITOR_START | tick=%d | correlation_id=%s",
                tick_number, summary.get("correlation_id", "unknown")
            )
            # P1-HARDENING: Wrap reconciliation in timeout to prevent blocking loop
            # FIX: Increased timeout from 1.2s to 30s to handle slow REST calls during heavy load
            try:
                await self._run_step(
                    "reconciliation",
                    asyncio.wait_for(self._reconcile_positions(summary), timeout=30.0),
                    summary
                )
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] reconciliation timed out after 30s — will retry next tick")
                summary["actions"].append("reconciliation:timeout_skip")
            except Exception as e:
                logger.exception("[RECONCILIATION-ERROR] Unexpected error during reconciliation: %s", e)
                summary["actions"].append("reconciliation:error")
            self._last_reconciliation = now
            logger.info("[LOOP] Reconciliation completed, checking enable_execution=%s", self.config.enable_execution)

        if self.config.enable_execution:
            # FIX-3: Log stage boundary - EXECUTE stage
            logger.info(
                "[CYCLE-TRACE] stage=EXECUTE_START | tick=%d | correlation_id=%s",
                tick_number, summary.get("correlation_id", "unknown")
            )
            await self._run_step("execution", self._execute_plans(summary), summary)

        if now - self._last_promotion_sync >= self._promotion_sync_interval:
            # FIX-3: Log stage boundary - PROMOTE stage
            logger.info(
                "[CYCLE-TRACE] stage=PROMOTE_START | tick=%d | correlation_id=%s",
                tick_number, summary.get("correlation_id", "unknown")
            )
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
        # FIX-3: Log stage boundary - PROTECT stage (risk checks happen before notify)
        logger.info(
            "[CYCLE-TRACE] stage=PROTECT_START | tick=%d | correlation_id=%s",
            tick_number, summary.get("correlation_id", "unknown")
        )
        await self._run_step("notify", self._notify("tick_complete", summary), summary)

        # FIX-3: Log cycle complete with summary
        logger.info(
            "[CYCLE-TRACE] stage=CYCLE_COMPLETE | tick=%d | duration_ms=%.1f | actions=%s | correlation_id=%s",
            tick_number, summary.get("duration_ms", 0),
            ", ".join(summary.get("actions", [])),
            summary.get("correlation_id", "unknown")
        )

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
        
        P1-HARDENING: Added global budget enforcement (4000ms) and per-API timeouts
        to prevent 10s+ stalls when external feeds are slow.
        """
        # AGGRESSIVE: Skip features refresh for first 120 ticks (~10 min) during startup
        if self.metrics.total_ticks < 120:
            summary["actions"].append("features_refreshed:skipped_startup_cooldown")
            return
        
        # 24/7-SCALPER-FIX: Global features budget raised to 10000ms for scalper mode
        FEATURES_MAX_MS = float(os.getenv("MERID_FEATURES_MAX_MS", "10000"))  # was 4000, now 10000
        features_start = time.perf_counter()
        
        def _check_features_budget() -> bool:
            elapsed_ms = (time.perf_counter() - features_start) * 1000
            if elapsed_ms > FEATURES_MAX_MS:
                logger.warning(
                    "[BUDGET] features budget_exceeded after %.1fms (budget %.0fms) — exiting early",
                    elapsed_ms, FEATURES_MAX_MS
                )
                return True
            return False

        # Try live data first with timeout
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            # OLD-HARDWARE FIX: 5.0s timeout for live feeds (was 1.0s)
            # Individual feeds have their own timeouts; this is the overall budget
            await asyncio.wait_for(
                mgr.refresh_all(self.config.active_symbols, now),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("[BUDGET] Live feed refresh timed out after 5.0s — using cached/synthetic")
            summary["actions"].append("features_refreshed:live_feed_timeout")
        except Exception as e:
            logger.warning(f"Live feed refresh failed (using cached/synthetic): {e}")

        # Now read features (live-ingested or synthetic fallback)
        # Run in thread pool so sync SQLite/feature reads don't block event loop
        svc = self._feature_service()
        store = self._signal_store()
        step_start = time.perf_counter()

        # BUG-EL15/EL18 FIX: Process max 1 symbol per tick with 30s minimum interval
        # to prevent thread pool saturation behind CPU work
        MAX_SYMBOLS_PER_TICK = 1
        _MIN_FEATURE_INTERVAL_S = 30.0
        
        # Check if enough time has passed since last feature refresh
        _last_features = getattr(self, '_last_feature_process_time', 0)
        if (now - _last_features) < _MIN_FEATURE_INTERVAL_S:
            summary["actions"].append("features_refreshed:interval_gate")
            return
        self._last_feature_process_time = now
        
        symbols_this_tick = self.config.active_symbols[:MAX_SYMBOLS_PER_TICK]
        
        # P1-HARDENING: Check budget before expensive thread pool work
        if _check_features_budget():
            summary["actions"].append("features_refreshed:budget_exceeded_before_processing")
            return
        
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
        # BUG-EL24 FIX: Added 2.0s timeout to prevent executor call from blocking indefinitely
        loop = asyncio.get_running_loop()
        try:
            batch_size = await asyncio.wait_for(
                loop.run_in_executor(_get_loop_executor(), _sync_feature_refresh),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            logger.warning("[BUDGET] Feature refresh timed out after 2.0s — skipping batch store")
            summary["actions"].append("features_refreshed:timeout")
            batch_size = 0
        thread_ms = (time.perf_counter() - step_start) * 1000
        
        # Generate Kalshi signals if prediction domain is active
        # Skip during first 30 ticks (2.5 min) to reduce startup load
        # BUG-EL19 fix: Run in thread pool with timeout to prevent blocking event loop
        kalshi_ms = 0
        if "prediction" in self.config.active_domains and self.metrics.total_ticks > 30:
            kalshi_start = time.perf_counter()
            # OLD-HARDWARE FIX: Skip if features took >2000ms (was 500ms)
            if thread_ms > 2000:
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
            logger.info("[BG-AGENT-CYCLE] Starting background agent cycle")
            await self._run_agent_cycles(summary)
            logger.info("[BG-AGENT-CYCLE] Background agent cycle completed")
        except Exception as e:
            import traceback
            logger.warning(f"Background agent cycle failed: {e}")
            logger.warning(f"Background agent cycle failed traceback:\n{traceback.format_exc()}")

    async def _run_agent_cycles(self, summary: Dict):
        """Step 2: Run canonical agents and Kalshi agents concurrently.
        
        Both agent groups run in parallel via asyncio.gather to maximize
        throughput within the 30s step timeout.
        """
        try:
            # PROFILE-GUARD: Skip canonical agent cycle for kalshi_crypto_15m_v2 (lean 15m stack)
            import os
            merid_profile = os.getenv("MERID_PROFILE", "").lower()
            if merid_profile == "kalshi_crypto_15m_v2":
                logger.info("[PROFILE-GUARD] Using AgentGrid.run_cycle() for kalshi_crypto_15m_v2 (lean 15m stack)")
                # For 15m profile, run AgentGrid.run_cycle() to step all 5 agents
                # This replaces the canonical agent cycle with the lean 15m path
                if "prediction" in self.config.active_domains:
                    from merid.prediction.agent_grid import get_agent_grid
                    from merid.risk.kill_switches import risk_controller
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

                    grid = get_agent_grid()
                    logger.info("[PROFILE-GUARD] grid.is_running=%s grid._running=%s", grid.is_running, grid._running)
                    if grid.is_running:
                        tick = summary.get("tick", 0)

                        # Log execution decision aligned with green path
                        trading_enabled = False
                        try:
                            store = get_kalshi_market_state_store()
                            trading_enabled = store.is_trading_enabled()
                        except Exception as exc:
                            logger.warning("[MERIDLOOP-15m] Failed to get trading_enabled: %s", exc)

                        risk_can_trade = risk_controller.can_trade()
                        execution_enabled = self.config.enable_execution

                        logger.info(
                            "[MERIDLOOP-15m] Kalshi 15m Crypto Loop tick=%d execution=%s trading_enabled=%s risk_can_trade=%s AgentGrid=healthy",
                            tick, execution_enabled, trading_enabled, risk_can_trade
                        )

                        await grid.run_cycle(tick)
                        logger.info(f"[PROFILE-GUARD] AgentGrid.run_cycle() completed for kalshi_crypto_15m_v2 (tick={tick})")
                        summary["actions"].append("agent_cycles:15m_grid")
                    else:
                        logger.warning("[PROFILE-GUARD] AgentGrid not running, skipping 15m cycle")
                gathered = []
            else:
                # Build coroutines to run concurrently
                registry = self._agent_registry()
                coros = [registry.run_all()]
                
                if "prediction" in self.config.active_domains:
                    coros.append(self._run_kalshi_agent_cycle(summary))
                
                # Run canonical + Kalshi agents concurrently
                gathered = await asyncio.gather(*coros, return_exceptions=True)
            
            # Process canonical agent results (first coro)
            # Guard: kalshi_crypto_15m_v2 profile path sets gathered=[] (no canonical run),
            # so only index gathered[0] when at least one coro was actually gathered.
            if gathered:
                canonical_result = gathered[0]
                if isinstance(canonical_result, Exception):
                    import traceback
                    logger.warning(f"Canonical agent cycle failed: {canonical_result}")
                    logger.warning(f"Canonical agent cycle failed traceback:\n{traceback.format_exc()}")
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
                import traceback
                logger.warning(f"Kalshi agent cycle failed: {gathered[1]}")
                logger.warning(f"Kalshi agent cycle failed traceback:\n{traceback.format_exc()}")
                
        except Exception as e:
            import traceback
            logger.warning(f"Agent cycle failed: {e}")
            logger.warning(f"Agent cycle failed traceback:\n{traceback.format_exc()}")
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

            # PROFILE-FILTER: Only process 15m crypto agents under kalshi_crypto_15m_v2 profile
            import os as _os
            _profile = _os.getenv("MERID_PROFILE", "full").lower().strip()
            _is_15m_crypto = _profile == "kalshi_crypto_15m_v2"
            
            if _is_15m_crypto:
                # Filter to only 15m crypto agents (BTC/ETH/SOL/XRP/DOGE)
                from merid.agents.agent_metadata import get_agent_metadata_from_instance
                _filtered_agents = []
                for agent in grid.agents:
                    try:
                        metadata = get_agent_metadata_from_instance(agent)
                        if (metadata.classification in ("prod_15m_core", "prod_15m_optional") and
                            metadata.age_bucket == "recent"):
                            _filtered_agents.append(agent)
                    except Exception:
                        # If metadata extraction fails, skip agent conservatively
                        pass
                _agents_to_scan = _filtered_agents
                logger.debug(
                    f"[PROFILE-FILTER] Scanning {len(_agents_to_scan)}/{len(grid.agents)} agents "
                    f"(profile={_profile}, classification=prod_15m_core/prod_15m_optional)"
                )
            else:
                # Non-15m profile: scan all agents
                _agents_to_scan = grid.agents

            # Offload CPU-intensive signal scanning to thread pool
            def _scan_signals_sync():
                """Scan for actionable signals synchronously in thread pool."""
                signal_count = 0
                _sig_cutoff = time.time() - 120.0

                for agent in _agents_to_scan:
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
            # BUG-EL24 FIX: Added 2.0s timeout to prevent executor saturation
            try:
                signal_count = await asyncio.wait_for(
                    loop.run_in_executor(_get_loop_executor(), _scan_signals_sync),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] Signal scan timed out after 2.0s")
                signal_count = 0

            if signal_count > 0:
                logger.info(f"Kalshi agents generated {signal_count} actionable signals this cycle")
                summary["actions"].append(f"kalshi_agents:{signal_count}signals")

        except Exception as exc:
            import traceback
            logger.warning(f"Kalshi agent cycle failed (graceful degradation): {exc}")
            logger.warning(f"Kalshi agent cycle failed (graceful degradation) traceback:\n{traceback.format_exc()}")
    
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
            
            # Run in dedicated executor with 48 workers
            loop = asyncio.get_running_loop()
            # BUG-EL24 FIX: Added 3.0s timeout to prevent executor saturation
            try:
                total_reflections, total_insights, critical_agents = await asyncio.wait_for(
                    loop.run_in_executor(_get_loop_executor(), _process_reflections),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning("[BUDGET] Reflection processing timed out after 3.0s")
                total_reflections, total_insights, critical_agents = 0, 0, []

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

            # OLD-HARDWARE FIX: Lag-aware scope reduction with relaxed thresholds
            # Use percentage of warning threshold (1500ms) instead of hardcoded values
            _WARN_MS = 1500.0  # From KALSHI_LOOP_LAG_HEALTHY_MS
            base_max = 2 if self.metrics.total_ticks < 120 else 3
            if current_lag > _WARN_MS * 1.5:  # >2250ms: severe lag
                MAX_TICKERS = 1
                logger.warning("[BUDGET] liquidity: reduced scope to 1 market due to severe lag %.0fms", current_lag)
            elif current_lag > _WARN_MS * 0.8:  # >1200ms: elevated lag
                MAX_TICKERS = 1
                logger.warning("[BUDGET] liquidity: reduced scope to 1 market due to elevated lag %.0fms", current_lag)
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
            # Track cumulative time and abort if approaching budget
            # 24/7-SCALPER-FIX: Raised to 10000ms for continuous operation (was 4000ms)
            LIQUIDITY_HARD_BUDGET_MS = float(os.getenv(
                "MERID_LIQUIDITY_HARD_BUDGET_MS", "10000.0"
            ))
            _budget_start = time.perf_counter()

            def _check_budget_exceeded() -> bool:
                elapsed_ms = (time.perf_counter() - _budget_start) * 1000
                if elapsed_ms > LIQUIDITY_HARD_BUDGET_MS:
                    logger.error(
                        "[BUDGET] liquidity_budget_exceeded: aborting sweep step after %.1fms "
                        "(budget %.0fms). This aborts the sweep only, NOT the server.",
                        elapsed_ms, LIQUIDITY_HARD_BUDGET_MS
                    )
                    return True
                return False
            
            # Fetch orderbooks concurrently (max 1 at a time via semaphore - reduced from 2)
            # CRITICAL-FIX: More conservative to prevent budget overruns
            _sem = asyncio.Semaphore(1)

            async def _fetch_ob(ticker: str):
                async with _sem:
                    # PHASE-3: Budget check before each fetch
                    if _check_budget_exceeded():
                        return (ticker, None)
                    
                    # Abort if circuit tripped during this sweep
                    if getattr(client, "is_circuit_open", False):
                        return (ticker, None)
                    try:
                        # OLD-HARDWARE FIX: 3.0s timeout for orderbook (was 1.0s)
                        ob = await asyncio.wait_for(client.get_orderbook(ticker), timeout=3.0)
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
        # OLD-HARDWARE FIX: Use warning threshold (1500ms) instead of 200ms
        _ARB_SKIP_THRESHOLD_MS = float(os.getenv("MERID_ARB_LAG_SKIP_MS", "1500.0"))
        if current_lag > _ARB_SKIP_THRESHOLD_MS:
            logger.warning(
                "[LAG-SKIP] action=arb_scan reason=elevated_lag "
                f"lag_ms={current_lag:.0f} threshold_ms={_ARB_SKIP_THRESHOLD_MS:.0f} timeout_count={getattr(self.metrics, 'arb_scan_timeouts', 0)}"
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
            # CRYPTO-15M-ARB: Update crypto venue prices before scanning
            try:
                from merid.signals.crypto_venue_bridge import get_crypto_venue_bridge
                bridge = get_crypto_venue_bridge()
                if bridge.update_prices():
                    summary["actions"].append("arb_scan:prices_updated")
            except Exception as _bridge_err:
                logger.debug("Crypto venue bridge update skipped: %s", _bridge_err)
            
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
            
            # CRYPTO-15M-ARB: Use isolated executor and longer timeout
            # BUG-EL23: Increased timeout from 2s to 5s, using dedicated arb_executor
            _ARB_TIMEOUT_S = float(os.getenv("MERID_ARB_SCAN_TIMEOUT_S", "5.0"))
            signals = await asyncio.wait_for(
                loop.run_in_executor(_get_arb_executor(), _do_arb_scan_all),
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

        # LEGACY REMOVAL: Consensus-based plan execution removed
        # Plans are now executed directly by AgentGrid for 15m Kalshi crypto stack
        summary["actions"].append("plan_execution:consensus_removed")

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
        logger.info("[CQI] Submitting CQI compute tasks for domains: %s", self.config.active_domains)
        tasks = [
            loop.run_in_executor(_get_loop_executor(), _compute_cqi_for_domain, domain)
            for domain in self.config.active_domains
        ]
        logger.info("[CQI] Waiting for CQI compute tasks to complete")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[CQI] CQI compute tasks completed, results=%s", len(results))

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
                # OLD-HARDWARE FIX: 2.5s timeout for position sync (was 1.0s) - trading critical
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client as _gkc
                    _positions_result = await asyncio.wait_for(
                        _gkc().get_positions(), timeout=10.0
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
            
            # OLD-HARDWARE FIX: 4000ms budget for order_groups (was 1000ms)
            ORDER_GROUPS_BUDGET_MS = 4000.0
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
        DEGRADED-MODE-FIX: Aggressive early-exit and reduced work when lag is elevated.
        """
        import asyncio
        step_start = time.perf_counter()
        notify_count = 0
        slow_subscribers = []
        timed_out_count = 0
        
        # Check lag before starting - DEGRADED MODE: skip at lower threshold
        current_lag = self._get_event_loop_lag_ms()
        # MICRO-BANKROLL FIX v9 (2026-04-26): Increased skip threshold from 500ms to 2000ms
        # to prevent blocking critical trading operations during transient lag spikes.
        # For micro-bankroll, missing a trade due to lag is worse than slow execution.
        if current_lag > 2000:  # v9: was 500, now 2000ms - only skip if severely lagged
            logger.warning(
                "[LAG-SKIP] action=notify reason=degraded_mode "
                f"lag_ms={current_lag:.0f} threshold_ms=2000 subscriber_count={len(self._subscribers)}"
            )
            # Track skip metrics
            self.metrics.lag_skips_total = getattr(self.metrics, 'lag_skips_total', 0) + 1
            return
        
        # DEGRADED-MODE: When lag > 500ms, reduce subscriber budget slightly
        # MICRO-BANKROLL FIX v9 (2026-04-26): Increased threshold from 200ms to 500ms
        # and increased subscriber limit from 3 to 10. Micro-bankroll needs to process
        # more trading agents even under moderate lag to avoid missing opportunities.
        _DEGRADED_THRESHOLD_MS = 500.0  # v9: was 200, now 500
        _is_degraded = current_lag > _DEGRADED_THRESHOLD_MS
        
        # Per-subscriber timeout: max 50ms in degraded mode, 100ms normal
        _CB_TIMEOUT_S = 0.05 if _is_degraded else 0.1
        # Overall budget: max 400ms in degraded mode, 500ms normal (less aggressive)
        _TOTAL_BUDGET_MS = 400.0 if _is_degraded else 500.0  # v9: was 250, now 400
        # Max subscribers to process in degraded mode
        _MAX_SUBSCRIBERS_DEGRADED = 10  # v9: was 3, now 10 to allow more agents
        
        for cb in self._subscribers:
            # Check if we're over budget
            elapsed_ms = (time.perf_counter() - step_start) * 1000
            if elapsed_ms > _TOTAL_BUDGET_MS:
                logger.warning(f"[LAG-GUARD] notify exceeded budget ({_TOTAL_BUDGET_MS:.0f}ms), skipping {len(self._subscribers) - notify_count} remaining subscribers")
                break
            
            # DEGRADED-MODE: Limit number of subscribers processed
            if _is_degraded and notify_count >= _MAX_SUBSCRIBERS_DEGRADED:
                logger.warning(f"[LAG-GUARD] notify degraded mode: limited to {_MAX_SUBSCRIBERS_DEGRADED} subscribers, skipping remaining {len(self._subscribers) - notify_count}")
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
        logger.info("[MERID-LOOP] run entry")
        logger.info("[MERID-LOOP] DEBUG: Setting _running=True")
        self._running = True
        logger.info("[MERID-LOOP] DEBUG: Initializing tick_count")
        tick_count = 0
        min_interval = min(
            self.config.feature_refresh_interval,
            self.config.consensus_interval,
            self.config.arb_scan_interval,
        )
        # Run at least every 5s, at most every min_interval
        sleep_time = max(1.0, min(5.0, min_interval))

        # Log full domain coverage
        # PROFILE-GUARD: For kalshi_crypto_15m_v2, simplify logging to 15m-specific semantics
        import os as _os
        _profile = _os.environ.get("MERID_PROFILE", "").lower()
        if _profile == "kalshi_crypto_15m_v2":
            logger.info(
                f"MERID loop starting (Kalshi 15m Crypto): symbols={len(self.config.active_symbols)} active, "
                f"execution=ON (AgentGrid healthy), cadence={sleep_time:.1f}s, "
                f"assets={self.config.active_symbols}"
            )
        else:
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

        # Reuse the singleton ExecutionSubscriber from lifespan
        self._execution_subscriber = None
        if self.config.enable_execution and "prediction" in self.config.active_domains:
            try:
                from merid.event_venues.kalshi.execution_subscriber import get_execution_subscriber as _get_exec_sub
                self._execution_subscriber = _get_exec_sub()
                logger.debug("ExecutionSubscriber: reusing lifespan singleton")
            except Exception as _ese:
                logger.warning("ExecutionSubscriber reference skipped: %s", _ese)
                self._execution_subscriber = None

        # PROFILE-GUARD: For kalshi_crypto_15m_v2, skip HashtagMonitor
        self._hashtag_monitor = None
        if _profile != "kalshi_crypto_15m_v2":
            try:
                from merid.monitoring.hashtag_monitor import get_hashtag_monitor as _get_monitor
                self._hashtag_monitor = _get_monitor()
                logger.debug("HashtagMonitor: reusing lifespan singleton")
            except Exception as _hme:
                logger.warning("HashtagMonitor reference skipped: %s", _hme)
                self._hashtag_monitor = None

        while self._running:
            now = time.time()
            try:
                # MONITORING: Log tick metrics for lightweight monitoring
                error_count_last_5m = len([ts for ts in self._tick_errors if now - ts < 300.0])
                try:
                    from merid.risk.kill_switches import risk_controller
                    kill_switch_active = not risk_controller.can_trade()
                except Exception:
                    kill_switch_active = False
                
                logger.info(
                    "[TICK-METRICS] tick_index=%d kill_switch=%s errors_last_5m=%d",
                    tick_count + 1, kill_switch_active, error_count_last_5m
                )

                # WATCHDOG: Log kill-switch status at start of each tick
                try:
                    from merid.risk.kill_switches import risk_controller
                    if not risk_controller.can_trade():
                        reason = risk_controller.get_kill_reason() or "kill_switch_active"
                        logger.warning(
                            "[RISK] 15m trading frozen due to kill-switch (%s); tick will run monitors only",
                            reason
                        )
                except Exception as ks_exc:
                    logger.debug(f"[KILL-SWITCH] Failed to check kill-switch status: {ks_exc}")

                logger.info("[LOOP] Starting tick %d (tick_count=%d, max_ticks=%s)", tick_count + 1, tick_count, max_ticks)
                summary = {"tick": tick_count + 1, "actions": []}
                
                # WATCHDOG: Wrap tick execution to track errors
                try:
                    await self.tick(summary)
                    # Successful tick - update timestamp
                    self._last_tick_time = time.time()
                    tick_count += 1
                    logger.info("[LOOP] Completed tick %d, sleeping %.1fs", tick_count, sleep_time)
                except Exception as tick_exc:
                    # Track tick error
                    self._tick_errors.append(time.time())
                    logger.exception("[WATCHDOG] Tick %d failed, tracking error", tick_count + 1)
                    # Continue running despite tick errors (watchdog will halt if budget exceeded)

                # Build and persist tick record
                try:
                    # FIX: build_tick_record expects a single tick_summary dict, not individual args
                    tick_summary_for_log = {
                        "tick": tick_count,
                        "timestamp": time.time(),
                        "duration_ms": summary.get("duration_ms", 0),
                        "actions": summary.get("actions", []),
                        "cqi_scores": summary.get("cqi_scores", {}),
                        "error": summary.get("error", ""),
                    }
                    record = build_tick_record(tick_summary_for_log)
                    record.kill_switch_active = self._execution_guard().kill_switch_active
                    logger.info("[LOOP] Appending tick record to log")
                    tick_log.append(record)
                    logger.info("[LOOP] Tick record appended successfully")
                except Exception as e:
                    logger.warning(f"Tick log write failed: {e}")

                if max_ticks and tick_count >= max_ticks:
                    logger.info(f"Reached max_ticks={max_ticks}, stopping")
                    self._running = False
                    break

                # WATCHDOG: Check error budget and stall detection after each tick
                self._check_watchdog(time.time())

                # MONITORING: Log aggregate stats every 60 ticks
                if tick_count > 0 and (tick_count - self._last_aggregate_log_tick) >= 60:
                    try:
                        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                        ledger = get_fills_ledger()
                        ledger_summary = ledger.summary()
                        daily_pnl = ledger_summary.get("daily_realized_pnl_usd", 0.0)
                        total_fills = ledger_summary.get("total_fills", 0)
                        
                        logger.info(
                            "[AGGREGATE-STATS] tick=%d daily_pnl=%.2f total_fills=%d trades_since_start=%d",
                            tick_count, daily_pnl, total_fills, self._aggregate_trades_since_start
                        )
                        self._last_aggregate_log_tick = tick_count
                    except Exception as agg_exc:
                        logger.debug(f"[MONITORING] Failed to log aggregate stats: {agg_exc}")

            except asyncio.CancelledError:
                logger.info("[LOOP] Cancelled during tick — exiting cleanly")
                break
            except Exception as e:
                logger.exception("[MERID-LOOP-ERROR] Unexpected error in tick: %s", e)
                # Continue running despite errors

            # Simple sleep - use blocking time.sleep in executor
            logger.info("[LOOP] About to sleep for %.1fs before next tick (blocking in executor)", sleep_time)
            try:
                import time as _time
                def _blocking_sleep(seconds):
                    logger.info("[LOOP] _blocking_sleep: sleeping for %.1fs", seconds)
                    _time.sleep(seconds)
                    logger.info("[LOOP] _blocking_sleep: woke up")
                loop = asyncio.get_running_loop()
                logger.info("[LOOP] Using default executor (None)")
                await loop.run_in_executor(None, _blocking_sleep, sleep_time)
                logger.info("[LOOP] Woke up from blocking sleep")
            except asyncio.CancelledError:
                logger.info("[LOOP] Cancelled during sleep — exiting cleanly")
                break
            except Exception as sleep_exc:
                logger.exception("[LOOP-ERROR] Exception during sleep: %s", sleep_exc)
                break

        self._running = False
        logger.info("[MERID-LOOP-EXIT] MERID loop stopped after %d ticks", tick_count)

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
        
        # SHUTDOWN-FIX: Cleanup thread pool executors to prevent thread leaks
        global _loop_executor, _arb_executor
        if _loop_executor is not None:
            logger.debug("[SHUTDOWN] Shutting down loop executor")
            _loop_executor.shutdown(wait=False)
            _loop_executor = None
        if _arb_executor is not None:
            logger.debug("[SHUTDOWN] Shutting down arb executor")
            _arb_executor.shutdown(wait=False)
            _arb_executor = None
        
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
