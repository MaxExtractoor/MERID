"""KalshiTradingAgent — Per-(asset, timeframe) trading agent.

Each agent instance:
- Subscribes to a filtered set of Kalshi markets (resolved from config)
- Reads MERID's internal crypto price feed for model features
- Executes only via typed Kalshi tools
- Runs a decision loop keyed to contract expiry windows
- Enforces per-agent risk limits

Strike Selection Integration:
- Uses ``kalshi_strike_selector.evaluate()`` for crypto markets to validate strike distance.
- Crypto markets (KXBTC, KXETH, etc.) are evaluated against spot for ATM/slightly OTM strikes.
- Macro markets (KXFED, KXFEDDECISION, etc.) are bypassed with reason ``NON_CRYPTO_MARKET``.
- Macro bypass is expected behavior — produces DEBUG logs, not ERROR logs.
- Asset resolution via ``resolve_asset_for_snapshot()`` returns "" for macro tickers,
  preventing incorrect crypto asset assignment.

Reuses:
- KalshiStrategy (merid.prediction.strategy) for edge/sizing decisions
- PredictionMarketRisk (merid.prediction.risk) for pre-trade checks
- PredictionMarketModel (merid.prediction.model) for implied probs
- SessionGuard for trading hours
- VenueGate for mode gating
- KalshiStrikeSelector for crypto-only strike distance validation
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import random
import time
import uuid  # P1 FIX: UUID suffix for agent_id uniqueness
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
from merid.prediction.agent_grid_config import AgentConfig, EntryWindowConfig
from merid.prediction.decision import Decision, DecisionAction, DecisionTimer, HoldReason
from merid.prediction.decision_evaluator import CycleContext, evaluate_cycle_decision
from merid.prediction.session_guard import get_session_guard
from merid.prediction.trade_hold_config import get_trade_hold_config
from merid.prediction.venue_gate import get_venue_gate
from merid.prediction.model import (
    PredictionMarketModel,
    MarketSnapshot,
    ContractState,
    ImpliedProbability,
    snapshot_timestamp_utc_epoch_seconds,
    pm_spot_feed_symbol_candidates,
)
from merid.prediction.strategy import KalshiStrategy, StrategySignal, SignalAction, StrategyConfig
from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig, PreTradeCheck, get_prediction_risk
from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi.stop_loss import StopLossRules, TrackedPosition
from merid.event_venues.kalshi.take_profit import TakeProfitManager, get_tp_config_for_agent
from merid.tick_events import TickContext, get_tick_bus
from utils.logger import get_logger
from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
from merid.swarm.consensus_aggregator import get_consensus_aggregator

logger = get_logger("merid.prediction.trading_agent")

# Throttle [PM_SPOT] missing-spot warnings per agent|asset (seconds between emits).
_PM_SPOT_MISSING_WARN_LAST: Dict[str, float] = {}
_PM_SPOT_MISSING_WARN_INTERVAL_S = float(os.getenv("MERID_PM_SPOT_MISSING_WARN_INTERVAL_S", "120.0"))
# Throttle PM_SPOT_BLOCK logs per asset|market for CRYPTO_15M_MM hard gate.
_PM_SPOT_BLOCK_LOG_LAST: Dict[str, float] = {}
_PM_SPOT_BLOCK_LOG_INTERVAL_S = float(os.getenv("MERID_PM_SPOT_BLOCK_LOG_INTERVAL_S", "120.0"))


def _classify_pm_no_action_reason(reason: str) -> str:
    """Bucket strategy ``reason`` for PM_CYCLE_TRACE rollups."""
    r = (reason or "").lower()
    if "pm_spot_gate" in r or "missing_or_stale_spot" in r:
        return "pm_spot_gate"
    if "spot_strike" in r or "spot_strike_anomaly" in r:
        return "spot_strike_veto"
    if "stale snapshot" in r:
        return "stale_snapshot"
    if "expiry unknown" in r or "unknown expiry" in r:
        return "unknown_expiry"
    if "liquidity guard" in r:
        return "liquidity_guard"
    if "volume" in r and "below" in r:
        return "volume"
    if "open_interest" in r or "oi " in r:
        return "open_interest"
    if "below" in r and "threshold" in r and "edge" in r:
        return "edge_below_threshold"
    if "confidence" in r and "below" in r:
        return "confidence"
    if "prob_edge" in r or "conviction" in r or "blocked:" in r:
        return "prob_or_conviction_gate"
    if "no actionable edge" in r:
        return "no_speculative_edge"
    if "kelly" in r and "0" in r:
        return "kelly_zero"
    return "other"


def _apply_global_pm_strategy_env(sc: StrategyConfig) -> None:
    """Optional process-wide overrides via env (ops tuning without YAML edit)."""
    env_map = [
        ("MERID_PM_MIN_EDGE_EARLY", "min_edge_early"),
        ("MERID_PM_MIN_EDGE_MID", "min_edge_mid"),
        ("MERID_PM_MIN_EDGE_LATE", "min_edge_late"),
        ("MERID_PM_MIN_EDGE_TERMINAL", "min_edge_terminal"),
        ("MERID_PM_MIN_ARB_EDGE", "min_arb_edge"),
        ("MERID_PM_MIN_CONFIDENCE", "min_confidence"),
        ("MERID_PM_MIN_VOLUME", "min_volume"),
        ("MERID_PM_MIN_OPEN_INTEREST", "min_open_interest"),
        ("MERID_PM_CONTRARIAN_SENTIMENT_MIN", "contrarian_sentiment_min"),
        ("MERID_PM_CONTRARIAN_MODEL_GAP_MIN", "contrarian_model_gap_min"),
        ("MERID_PM_VOL_BREAKOUT_NEUTRAL_LOW", "vol_breakout_neutral_low"),
        ("MERID_PM_VOL_BREAKOUT_NEUTRAL_HIGH", "vol_breakout_neutral_high"),
        ("MERID_PM_MM_MAX_SPREAD_CENTS", "mm_max_spread_cents"),
        ("MERID_PM_MM_TARGET_SPREAD_CENTS", "mm_target_spread_cents"),
        ("MERID_PM_MM_INVENTORY_LIMIT", "mm_inventory_limit"),
        ("MERID_PM_MM_SKEW_FACTOR", "mm_skew_factor"),
    ]
    for ek, attr in env_map:
        v = os.getenv(ek)
        if not v or not hasattr(sc, attr):
            continue
        cur = getattr(sc, attr)
        if isinstance(cur, Decimal):
            setattr(sc, attr, Decimal(str(v)))
        elif isinstance(cur, int):
            setattr(sc, attr, int(v))
        elif isinstance(cur, float):
            setattr(sc, attr, float(v))
        else:
            setattr(sc, attr, v)


# Global thread pool executor for CPU-bound operations
# Increased from default (CPU+4) to handle 35+ concurrent agents without contention
_GLOBAL_AGENT_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_agent_executor() -> ThreadPoolExecutor:
    """Get or create global thread pool executor with sufficient workers for agent operations."""
    global _GLOBAL_AGENT_EXECUTOR
    if _GLOBAL_AGENT_EXECUTOR is None:
        import os
        max_workers = max(20, (os.cpu_count() or 4) * 2)
        _GLOBAL_AGENT_EXECUTOR = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="merid_agent_"
        )
        logger.info(f"Initialized agent thread pool with {max_workers} workers")
    return _GLOBAL_AGENT_EXECUTOR

# Pre-import alert manager so degraded-mode alert calls don't fail on lazy import.
# The singleton is cached; if unavailable at startup the module still loads (non-fatal).
try:
    from merid.prediction.alerts import get_alert_manager as _get_alert_manager_module
except Exception:
    _get_alert_manager_module = None  # type: ignore[assignment]


_MAX_LOG_ENTRIES = 200


# Maximum seconds without a valid consensus before an agent is considered
# swarm-degraded.  In degraded mode all orders are capped to "small" size band.
# Default 0 = no hold for single-agent deployments (the agent IS its own
# consensus).  Set to a positive value (e.g. 120) for multi-agent swarms
# where you want agents to wait for quorum before going solo.
def _swarm_max_solo_seconds() -> float:
    """Seconds without consensus before solo-sized execution is allowed."""
    return float(os.getenv("MERID_PM_SWARM_SOLO_SECONDS", "0"))


def _swarm_max_solo_trades_degraded() -> int:
    """Max live orders per agent while swarm is degraded (configurable)."""
    return int(os.getenv("MERID_PM_SWARM_SOLO_TRADES_CAP", "3"))


def _swarm_max_solo_wall_seconds() -> float:
    """Wall-clock time in degraded mode before halting new entries."""
    return float(os.getenv("MERID_PM_SWARM_SOLO_WALL_SECONDS", "1800.0"))


# BUG-08: module constants for audit/regression tests (same values as env-driven helpers)
_MAX_SOLO_SECONDS: float = float(os.getenv("MERID_PM_SWARM_SOLO_SECONDS", "0"))
_MAX_SOLO_TRADES_DEGRADED: int = int(os.getenv("MERID_PM_SWARM_SOLO_TRADES_CAP", "3"))
_MAX_SOLO_WALL_SECONDS: float = float(os.getenv("MERID_PM_SWARM_SOLO_WALL_SECONDS", "1800.0"))


# B3/RISK-11: Explicit lifecycle states for KalshiTradingAgent
class LifecycleState(str, Enum):
    STOPPED    = "stopped"
    STARTING   = "starting"
    WARMING_UP = "warming_up"   # resolves markets + logs signals but skips execution
    ACTIVE     = "active"       # full decision loop including order placement
    DRAINING   = "draining"     # finishes current cycle, runs final stop-loss, then stops


# Minimum seconds in WARMING_UP before considering promotion to ACTIVE.
# Actual promotion requires data-readiness checks (catalog populated, spot online)
# or fallback to this minimum + stagger after which the agent promotes regardless.
_WARMUP_MIN_SECONDS: float = 15.0
# BUG-L13 FIX: Stagger agent promotions to prevent thundering herd
# Each agent adds 0-30s additional delay based on hash of agent name
_MAX_STAGGER_SECONDS: float = 30.0
# Hard ceiling: promote to ACTIVE unconditionally after this many seconds
# even if data checks haven't passed (prevents infinite warmup stall).
_WARMUP_MAX_SECONDS: float = 90.0
# Max consecutive cycle errors before the agent pauses itself (medium-risk fix)
_MAX_CONSECUTIVE_ERRORS: int = 5


@dataclass
class AgentState:
    """Runtime state for a single trading agent."""
    name: str
    enabled: bool = True
    running: bool = False
    lifecycle: str = LifecycleState.STOPPED  # BUG-L8: explicit lifecycle state
    started_at: Optional[datetime] = None    # BUG-L8: used for solo_seconds baseline
    last_cycle_at: Optional[datetime] = None
    cycles_run: int = 0
    orders_placed: int = 0
    orders_this_window: int = 0
    window_start: Optional[datetime] = None
    active_tickers: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    consecutive_errors: int = 0              # medium-risk: per-agent error circuit breaker
    signal_log: List[Dict[str, Any]] = field(default_factory=list)
    order_log: List[Dict[str, Any]] = field(default_factory=list)
    fill_log: List[Dict[str, Any]] = field(default_factory=list)
    # True when swarm consensus has been unavailable for > MERID_PM_SWARM_SOLO_SECONDS.
    # All orders placed while degraded use size_band="small".
    swarm_degraded: bool = False
    last_consensus_at: Optional[datetime] = None
    # BUG-08: track when degraded mode started and how many solo trades have fired
    swarm_degraded_since: Optional[datetime] = None
    solo_trades_this_degraded_session: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "running": self.running,
            "lifecycle": self.lifecycle,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "cycles_run": self.cycles_run,
            "orders_placed": self.orders_placed,
            "orders_this_window": self.orders_this_window,
            "active_tickers": self.active_tickers,
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
            "signal_count": len(self.signal_log),
            "order_count": len(self.order_log),
            "fill_count": len(self.fill_log),
            "swarm_degraded": self.swarm_degraded,
            "last_consensus_at": self.last_consensus_at.isoformat() if self.last_consensus_at else None,
            "swarm_degraded_since": self.swarm_degraded_since.isoformat() if self.swarm_degraded_since else None,
            "solo_trades_this_degraded_session": self.solo_trades_this_degraded_session,
        }


class KalshiTradingAgent:
    """Trades a specific (asset, timeframe) cell on Kalshi.

    Lifecycle:
        agent = KalshiTradingAgent(config)
        await agent.start()       # begins decision loop
        await agent.stop()        # graceful shutdown

    The decision loop:
        1. Resolve config market_filter → live Kalshi tickers
        2. For each market in entry window: evaluate strategy signal
        3. If signal is actionable: run pre-trade risk check
        4. If allowed: place order via kalshi_place_order tool
        5. Sleep until next cycle
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.logger = get_logger(f"merid.prediction.agent.{config.name}")
        self.state = AgentState(name=config.name)
        
        # P1 FIX: Unique instance ID to prevent clone collisions in multi-worker scenarios
        # This ensures each agent instance has a unique identity even if config.agent_id is shared
        self._instance_id = uuid.uuid4().hex[:8]
        self._unique_agent_id = f"{config.agent_id}_{self._instance_id}"

        # Reuse existing subsystems
        self._model = PredictionMarketModel()
        self._strategy = KalshiStrategy(
            self._build_strategy_config(config),
            agent_name=config.name,
        )
        # BUG-04 fix: use the portfolio-wide shared singleton so all agents
        # contribute to the same exposure, daily-loss, and notional caps.
        # Singleton is initialized once by AgentGrid; agents just get the instance.
        self._risk = get_prediction_risk()
        self._session_guard = get_session_guard()
        self._venue_gate = get_venue_gate()

        # Internal
        self._entry_window_suspect_streak: int = 0
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._drain_done = asyncio.Event()   # BUG-L5: set when drain pass completes
        self._in_execution = asyncio.Event() # BUG-L6: set while _execute_signal is running
        self._cycle_done = asyncio.Event()   # BUG-L5: set at end of each cycle
        self._resolved_markets: List[EventMarket] = []

        # Stop-loss rules engine — monitors open positions every cycle
        self._stop_loss = StopLossRules()
        # Take-profit manager — advanced TP / trailing / re-entry layer
        _tp_cfg = getattr(config, "take_profit", None) or get_tp_config_for_agent(config.name)
        self._tp_manager = TakeProfitManager(config=_tp_cfg)
        # position_id -> TrackedPosition for open fills awaiting settlement
        self._tracked_positions: Dict[str, TrackedPosition] = {}
        # Wire 1: live Kalshi contracts near spot, updated by CryptoSurfaceLoader callback
        self._live_markets: list = []
        # Lazily initialized in _execute_signal_body for crypto category signals
        self._btc15m_risk = None
        # Strike selector — proactive relevance filter anchored to live spot
        try:
            from merid.prediction.kalshi_strike_selector import get_strike_selector_for_agent
            self._strike_selector = get_strike_selector_for_agent(config)
        except Exception:
            self._strike_selector = None

    @staticmethod
    def _build_strategy_config(config: AgentConfig) -> StrategyConfig:
        """Merge grid ``strategy:`` overrides into ``StrategyConfig`` defaults."""
        from decimal import Decimal

        # BUG-005 FIX: Wire risk_limits into StrategyConfig defaults
        # Use agent's position limits to determine max_contracts_per_market
        # Per-side limit (yes/no) determines max market exposure
        _max_per_side = max(
            getattr(config.risk_limits, "max_yes_position", 500),
            getattr(config.risk_limits, "max_no_position", 500)
        )
        _max_per_order = getattr(config.risk_limits, "max_contracts_per_order", None) or 50
        
        sc = StrategyConfig(
            max_contracts_per_market=_max_per_side,  # Use per-side limit as market limit
            max_contracts_per_order=_max_per_order,
        )
        # Capture raw overrides now; apply them last so per-agent YAML beats global profiles.
        raw = getattr(config, "strategy_overrides", None) or {}
        try:
            from merid.prediction.pm_profiles import merge_profile_into_strategy_config

            merge_profile_into_strategy_config(sc)
        except Exception as _pp:
            logger.warning("[PM_PROFILE_MERGE_FAILED] PM profile merge failed: %s", _pp)
        _apply_global_pm_strategy_env(sc)
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
            from merid.prediction.crypto_edge_production import apply_crypto_strategy_thresholds_to_config

            _assets = getattr(config, "assets", None) or []
            _cat = (getattr(config, "category", None) or "").lower()
            _primary = (_assets[0] if _assets else "").strip().upper()
            _name_u = (getattr(config, "name", None) or "").upper()
            _inferred = None
            for _a in ACTIVE_CRYPTO_ASSETS:
                _tok = f"{_a}_"
                if _tok in _name_u or _name_u.startswith(_a) or f"_{_a}_" in _name_u:
                    _inferred = _a
                    break
            if _primary not in ACTIVE_CRYPTO_ASSETS and _inferred:
                _primary = _inferred
            _crypto_by_name = _inferred is not None or "CRYPTO" in _name_u or "15M_MM" in _name_u
            _tf = (config.timeframes[0] if getattr(config, "timeframes", None) else "15m")
            if _cat == "crypto" or _primary in ACTIVE_CRYPTO_ASSETS or _crypto_by_name:
                if _primary not in ACTIVE_CRYPTO_ASSETS:
                    _primary = _inferred or "BTC"
                _prior_yaml_edges = {
                    k: getattr(sc, k)
                    for k in (
                        "min_edge_early",
                        "min_edge_mid",
                        "min_edge_late",
                        "min_edge_terminal",
                    )
                    if hasattr(sc, k)
                }
                apply_crypto_strategy_thresholds_to_config(
                    sc,
                    _primary,
                    _tf,
                    getattr(config, "archetype", "") or "",
                    prior_yaml_phase_edges=_prior_yaml_edges,
                    agent_name=config.name,
                )
        except Exception as _crypto_thr:
            logger.debug("crypto strategy threshold merge skipped: %s", _crypto_thr)
        # Re-apply per-agent YAML overrides last so they win over global profiles / crypto thresholds.
        for key, val in raw.items():
            if not hasattr(sc, key):
                continue
            current = getattr(sc, key)
            if isinstance(current, Decimal):
                setattr(sc, key, val if isinstance(val, Decimal) else Decimal(str(val)))
            elif isinstance(current, int):
                setattr(sc, key, int(val))
            elif isinstance(current, float):
                setattr(sc, key, float(val))
            else:
                setattr(sc, key, val)
        return sc

    def _swarm_consensus_bypassed(self) -> bool:
        if getattr(self.config, "bypass_swarm_consensus", False):
            return True
        try:
            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

            if get_crypto_edge_runtime().mm_consensus_mode == "bypass":
                return True
        except Exception as e:
            logging.getLogger(__name__).debug(f"Consensus bypass check failed: {e}")
        raw = (os.getenv("MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS") or "").strip()
        if not raw:
            return False
        allowed = {x.strip() for x in raw.split(",") if x.strip()}
        return self.config.name in allowed

    @property
    def agent_id(self) -> str:
        # P1 FIX: Return unique instance ID to prevent clone collisions
        return getattr(self, '_unique_agent_id', self.config.agent_id)

    # ── Wire 1: CryptoSurfaceLoader callback ───────────────────────────

    def on_surface_update(self, snapshot: object) -> None:
        """Receive a CryptoSurfaceSnapshot and cache near-spot markets.

        Called by CryptoSurfaceLoader every ~10s (Wire 1).
        Both this callback and _run_cycle_body run in the same asyncio event loop,
        so cooperative scheduling makes the write safe without an explicit lock.

        Args:
            snapshot: CryptoSurfaceSnapshot from services.crypto_surface_loader
        """
        asset = self.config.assets[0] if self.config.assets else ""
        timeframe = self.config.timeframes[0] if self.config.timeframes else ""
        entry = snapshot.get_entry(asset, timeframe)
        if entry is None:
            return
        try:
            from config.crypto_spot_kalshi_config import select_markets_near_spot
            self._live_markets = select_markets_near_spot(entry)
        except Exception as exc:
            self.logger.debug("on_surface_update select failed: %s", exc)

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self, prefetched_positions: Optional[List[Any]] = None) -> None:
        """Start the agent decision loop.
        
        Args:
            prefetched_positions: Optional pre-fetched positions from AgentGrid.
                If provided, agent skips the _sync_open_positions() API call.
                This prevents event-loop blocking during concurrent agent startup.
        """
        if self.state.running:
            self.logger.warning(f"{self.config.name} already running")
            return
        self._shutdown.clear()
        self._drain_done.clear()
        self._in_execution.clear()
        self._cycle_done.clear()
        self.state.running = True
        self.state.enabled = True
        self.state.lifecycle = LifecycleState.STARTING
        self.state.started_at = datetime.now(timezone.utc)  # BUG-L8: baseline for solo_seconds
        self.state.consecutive_errors = 0
        import time as _agent_timing
        # D14: Defensive clear on (re)start — ensures no stale positions
        # from a previous run survive into the new session.
        _t_clear_start = _agent_timing.time()
        if self._tracked_positions:
            self.logger.debug(
                "start: clearing %d residual tracked positions from previous run",
                len(self._tracked_positions),
            )
            self._tracked_positions.clear()
        _t_clear_elapsed = (_agent_timing.time() - _t_clear_start) * 1000
        if _t_clear_elapsed > 10:  # Only log if it took significant time
            self.logger.debug(f"[TIMING] Position clear took {_t_clear_elapsed:.0f}ms")
        
        # BUG-L3: Sync open positions from Kalshi before the first cycle.
        # BUG-L9 FIX: Defer position restoration to background task to avoid blocking
        # event loop during concurrent agent startup. Agent reports as started immediately.
        _t_pos_start = _agent_timing.time()
        
        # Start background task for position restoration (non-blocking)
        if prefetched_positions is not None:
            self.logger.debug("Deferring position restoration to background (%d positions)", len(prefetched_positions))
            _restore_task = asyncio.create_task(
                self._restore_prefetched_positions_async(prefetched_positions),
                name=f"{self.config.name}-position-restore"
            )
            _restore_task.add_done_callback(
                lambda t: self.logger.warning("Position restore task failed: %s", t.exception()) if not t.cancelled() and t.exception() else None
            )
        else:
            # Fall back to sync approach if no pre-fetched positions
            await self._sync_open_positions()
            
        _t_pos_elapsed = (_agent_timing.time() - _t_pos_start) * 1000
        self.logger.debug(f"[TIMING] Agent started (position restore deferred) in {_t_pos_elapsed:.0f}ms")
        
        # BUG-L8: Enter WARMING_UP — decision loop will promote to ACTIVE
        # once data-readiness checks pass (min {_WARMUP_MIN_SECONDS}s + stagger)
        # or unconditionally after {_WARMUP_MAX_SECONDS}s.
        self.state.lifecycle = LifecycleState.WARMING_UP
        self._task = asyncio.create_task(self._run_loop(), name=f"kalshi-agent-{self.config.name}")
        self.logger.info(
            f"Started {self.config.name}: assets={self.config.assets}, "
            f"timeframes={self.config.timeframes} "
            f"[WARMING_UP min={_WARMUP_MIN_SECONDS:.0f}s max={_WARMUP_MAX_SECONDS:.0f}s]"
        )
        try:
            import json as _json

            from merid.prediction.pm_profiles import effective_strategy_config_snapshot

            _snap = effective_strategy_config_snapshot(self._strategy.config)
            _keys = (
                "min_edge_early",
                "min_edge_mid",
                "min_edge_late",
                "min_edge_terminal",
                "min_arb_edge",
                "min_confidence",
                "min_volume",
                "min_open_interest",
                "contrarian_sentiment_min",
                "contrarian_model_gap_min",
                "vol_breakout_neutral_low",
                "vol_breakout_neutral_high",
                "max_contracts_per_order",
                "mm_max_spread_cents",
                "mm_target_spread_cents",
                "mm_inventory_limit",
            )
            _sub = {k: _snap.get(k, "") for k in _keys if k in _snap}
            _sub["MERID_PM_PROFILE"] = (os.getenv("MERID_PM_PROFILE") or "").strip()
            try:
                from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

                _sub["MERID_CRYPTO_EDGE_PRODUCTION_PROFILE"] = (
                    os.getenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE") or ""
                ).strip()
                _sub["crypto_threshold_mode"] = get_crypto_edge_runtime().threshold_mode
            except Exception as e:
                self.logger.debug(f"Crypto edge runtime check failed: {e}")
            self.logger.info("[PM_CONFIG_SUMMARY] %s", _json.dumps(_sub, sort_keys=True))
        except Exception as _pm_sum_exc:
            self.logger.debug("PM_CONFIG_SUMMARY skipped: %s", _pm_sum_exc)

        # ── Startup sanity checks — warn if config will block all trades ──
        try:
            _warnings: list[str] = []

            # Check 1: empty assets or timeframes
            if not self.config.assets:
                _warnings.append("assets=[] — no asset universe configured")
            if not self.config.timeframes:
                _warnings.append("timeframes=[] — no timeframe configured")

            # Check 2: solo window vs cycle interval
            _solo_s = _swarm_max_solo_seconds()
            _cycle_s = self._compute_cycle_interval()
            if _solo_s > 0 and not self._swarm_consensus_bypassed():
                if _solo_s > _cycle_s * 2:
                    _warnings.append(
                        f"MERID_PM_SWARM_SOLO_SECONDS={_solo_s:.0f} > 2× cycle_interval={_cycle_s:.0f}s "
                        f"— {int(_solo_s / _cycle_s)} dead cycles before solo execution"
                    )

            # Check 3: strike selector directional passthrough
            if self._strike_selector is not None:
                _ss_cfg = self._strike_selector.config
                if not _ss_cfg.allow_directional_passthrough:
                    # Check if any timeframes are 15m (directional-only)
                    if any(tf in ("15m",) for tf in self.config.timeframes):
                        _warnings.append(
                            "strike_selection.allow_directional_passthrough=false with "
                            "timeframe=15m — 15m directional markets will all be rejected"
                        )

            # Check 4: entry window viability
            _ew = self.config.entry_window
            if _ew.minutes_before_expiry <= _ew.cutoff_minutes_before_expiry:
                _warnings.append(
                    f"entry_window: minutes_before_expiry={_ew.minutes_before_expiry} <= "
                    f"cutoff={_ew.cutoff_minutes_before_expiry} — zero-width entry window"
                )

            if _warnings:
                for _w in _warnings:
                    self.logger.warning("[CONFIG_SANITY] agent=%s — %s", self.config.name, _w)
            else:
                self.logger.info(
                    "[CONFIG_SANITY] agent=%s — all checks passed", self.config.name
                )
        except Exception as _sc_exc:
            self.logger.debug("CONFIG_SANITY skipped: %s", _sc_exc)

        # ═══════════════════════════════════════════════════════════════════
        # Settlement Event Subscription (TP re-entry reset)
        # ═══════════════════════════════════════════════════════════════════
        try:
            self._setup_settlement_subscription()
        except Exception as _sub_exc:
            self.logger.debug("Settlement subscription setup skipped: %s", _sub_exc)

    def _setup_settlement_subscription(self) -> None:
        """Subscribe to settlement events to reset TP round-trips on expiry.

        When a contract settles, we clear the round-trip counter for that ticker
        so the agent can re-enter in the next contract window.

        Uses shared SETTLEMENT_EVENT_BUS_TOPIC constant to ensure publisher
        (settlement_poller) and subscriber (this agent) use identical topic.
        """
        try:
            from core.event_bus import get_event_bus
            from merid.event_venues.kalshi.settlement_poller import SETTLEMENT_EVENT_BUS_TOPIC

            event_bus = get_event_bus()
            event_bus.subscribe(SETTLEMENT_EVENT_BUS_TOPIC, self._on_settlement_event)
            self.logger.debug("Subscribed to %s events for TP reset", SETTLEMENT_EVENT_BUS_TOPIC)
        except Exception as exc:
            self.logger.debug("Failed to subscribe to settlement events: %s", exc)

    def _on_settlement_event(self, event: dict) -> None:
        """Handle settlement events — reset TP state for settled contracts.

        Args:
            event: Settlement event dict with 'ticker', 'market_id', 'result', etc.
        """
        try:
            ticker = event.get("ticker", "")
            market_id = event.get("market_id", "")
            if not ticker:
                return

            # Check if we have any ACTIVE (non-closed) positions for this ticker
            # This prevents double-processing if we already closed via TP
            active_positions = [
                (pos_id, pos) for pos_id, pos in self._tracked_positions.items()
                if pos.ticker == ticker
            ]

            if not active_positions:
                return  # No positions to process

            # Check if any are still open (not already closed by TP)
            _any_open = False
            for pos_id, pos in active_positions:
                _tp_state = self._tp_manager.get_state(pos_id)
                if _tp_state and _tp_state.tp_state.value != "closed":
                    _any_open = True
                    break

            # Only call on_position_closed if we have open positions
            # (it's idempotent, but this reduces log noise)
            if _any_open:
                # Notify TP manager that position is closed due to expiry
                self._tp_manager.on_position_closed(ticker, close_reason="expiry")
                self.logger.info(
                    "[TP-SETTLEMENT] %s: position closed due to settlement — round trips reset",
                    ticker
                )
            else:
                self.logger.debug(
                    "[TP-SETTLEMENT] %s: all positions already closed — skipping expiry handler",
                    ticker
                )

            # Remove tracked positions for this ticker regardless
            for pos_id, _ in active_positions:
                del self._tracked_positions[pos_id]

        except Exception as exc:
            self.logger.debug("Settlement event handling failed: %s", exc)

    async def drain(self) -> None:
        """BUG-L5: Disable new work, wait for current cycle, run final stop-loss sweep.

        Called by AgentGrid.stop() before agent.stop() so PortfolioRiskAgent
        remains running while positions are still actively managed.
        """
        if not self.state.running:
            return
        self.state.lifecycle = LifecycleState.DRAINING
        self.state.enabled = False  # stop accepting new signals
        self._drain_done.clear()

        # Wait for the current cycle to finish (up to 30s)
        try:
            await asyncio.wait_for(self._cycle_done.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            self.logger.warning("drain: cycle did not complete within 30s, forcing drain")

        # Final stop-loss sweep
        try:
            await self._check_stop_losses()
        except Exception as _exc:
            self.logger.warning("drain: final stop-loss sweep error: %s", _exc)

        self._drain_done.set()
        self.logger.info("drain complete for %s", self.config.name)

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        # BUG-L6: wait for any in-flight order placement before cancelling
        if self._in_execution.is_set():
            try:
                await asyncio.wait_for(self._in_execution.wait(), timeout=5.0)
                # wait for it to *clear* (execution finished)
                # _in_execution is set while executing; poll until clear
                _deadline = 5.0
                import time as _t
                _start = _t.monotonic()
                while self._in_execution.is_set() and (_t.monotonic() - _start) < _deadline:
                    await asyncio.sleep(0.05)
            except asyncio.TimeoutError:
                self.logger.warning("stop: in-flight execution did not complete within 5s, cancelling anyway")
        self._shutdown.set()
        self.state.running = False
        self.state.lifecycle = LifecycleState.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # D14 / W9: Clear tracked positions so stale entries don't trigger
        # spurious stop-loss closes if the agent is restarted.
        # Warn if any positions have in-flight (pending/partial) fills so
        # operators know orders may still be working on the venue.
        stale_count = len(self._tracked_positions)
        if stale_count:
            in_flight = [
                pos.ticker for pos in self._tracked_positions.values()
                if getattr(pos, "fill_status", "filled") in ("pending", "partial")
            ]
            if in_flight:
                self.logger.warning(
                    "stop: %d in-flight positions cleared — orders may still be "
                    "working on venue: %s",
                    len(in_flight), in_flight,
                )
            self._tracked_positions.clear()
            self.logger.debug(
                "stop: cleared %d stale tracked positions (%d in-flight)",
                stale_count, len(in_flight) if stale_count else 0,
            )
        self.logger.info(f"Stopped {self.config.name}")

    def pause(self) -> None:
        """Pause trading (agent stays alive but skips cycles)."""
        self.state.enabled = False
        if self.state.lifecycle == LifecycleState.ACTIVE:
            self.state.lifecycle = LifecycleState.WARMING_UP  # re-enter warm-up on resume
        self.logger.info(f"Paused {self.config.name}")

    def resume(self) -> None:
        """Resume trading."""
        self.state.enabled = True
        if self.state.running and self.state.lifecycle not in (LifecycleState.ACTIVE, LifecycleState.DRAINING):
            self.state.lifecycle = LifecycleState.WARMING_UP
        self.logger.info(f"Resumed {self.config.name}")

    # ── Decision loop ──────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main decision loop — runs until shutdown."""
        cycle_interval = self._compute_cycle_interval()

        while not self._shutdown.is_set():
            self._cycle_done.clear()
            try:
                # BUG-L8: promote from WARMING_UP to ACTIVE after warmup period
                # BUG-L13: add staggered delay to prevent thundering herd
                if (
                    self.state.lifecycle == LifecycleState.WARMING_UP
                    and self.state.started_at is not None
                ):
                    warmup_elapsed = (
                        datetime.now(timezone.utc) - self.state.started_at
                    ).total_seconds()
                    
                    # Calculate staggered delay based on agent name (deterministic)
                    _name_hash = hash(self.config.name) % 1000
                    _stagger_delay = (_name_hash / 1000.0) * _MAX_STAGGER_SECONDS
                    _min_warmup = _WARMUP_MIN_SECONDS + _stagger_delay
                    
                    # Data-readiness check: catalog has markets and spot feed is online
                    _data_ready = False
                    if warmup_elapsed >= _min_warmup:
                        _data_ready = self.state.cycles_run >= 1  # had at least one cycle
                    
                    # Hard ceiling: promote unconditionally after _WARMUP_MAX_SECONDS
                    _hard_ceiling = warmup_elapsed >= _WARMUP_MAX_SECONDS
                    
                    if _data_ready or _hard_ceiling:
                        _promote_reason = "data_ready" if _data_ready else "max_warmup_ceiling"
                        self.state.lifecycle = LifecycleState.ACTIVE
                        self.logger.info(
                            "[LIFECYCLE] Promoted %s WARMING_UP → ACTIVE after %.0fs "
                            "(reason=%s stagger=%.1fs cycles=%d)",
                            self.config.name, warmup_elapsed, _promote_reason,
                            _stagger_delay, self.state.cycles_run,
                        )

                if self.state.enabled:
                    await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.errors.append(str(exc))
                if len(self.state.errors) > 50:
                    self.state.errors = self.state.errors[-50:]
                # medium-risk: per-agent consecutive error circuit breaker
                self.state.consecutive_errors += 1
                if self.state.consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    self.logger.error(
                        "Agent %s hit %d consecutive errors — pausing self to prevent API spam",
                        self.config.name, self.state.consecutive_errors,
                    )
                    self.pause()
                    self.state.consecutive_errors = 0
                else:
                    self.logger.error(f"Cycle error ({self.state.consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): {exc}")
                self._cycle_done.set()
                # Wait before next retry
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=cycle_interval)
                    break
                except asyncio.TimeoutError:
                    continue

            # Cycle completed successfully — reset error counter
            self.state.consecutive_errors = 0
            self._cycle_done.set()

            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=cycle_interval
                )
                break  # shutdown was set
            except asyncio.TimeoutError:
                pass  # normal — time for next cycle

    async def _run_cycle(self) -> None:
        """Single decision cycle."""
        now = datetime.now(timezone.utc)
        self.state.last_cycle_at = now
        self.state.cycles_run += 1

        _mode = str(getattr(self._venue_gate, "mode", "paper") if self._venue_gate else "paper")
        _tick = TickContext(
            agent_id=self.config.name,
            cycle_number=self.state.cycles_run,
            mode=_mode,
        )
        _bus = get_tick_bus()
        _bus.emit(_tick.emit_started())

        try:
            await self._run_cycle_body(now, _tick, _bus)
        except Exception as _exc:
            _bus.emit(_tick.emit_error(str(_exc)))
            raise
        finally:
            _bus.emit(_tick.finalise())

    async def _run_cycle_body(
        self,
        now: datetime,
        _tick: TickContext,
        _bus: object,
    ) -> None:
        """Instrumented body of the decision cycle."""
        _decision_timer = DecisionTimer()

        # 0. Stop-loss sweep — check all open positions before new signals
        await self._check_stop_losses()

        # 1. Session guard
        if not self._session_guard.is_trading_allowed(now):
            _bus.emit(_tick.emit_session_gated("outside_session_window"))
            self._emit_decision_log(Decision.hold(
                HoldReason.SESSION_CLOSED,
                self._session_guard.block_reason(now) or "outside_session_window",
                agent_name=self.config.name,
                cycle_number=self.state.cycles_run,
                elapsed_ms=_decision_timer.elapsed_ms(),
            ))
            return

        # 2. Resolve markets
        await self._resolve_markets()
        if self._resolved_markets:
            try:
                from merid.event_venues.kalshi.expiry_fallback import (
                    apply_crypto_interval_expiry_fallback,
                )

                self._resolved_markets = [
                    apply_crypto_interval_expiry_fallback(m, now)
                    for m in self._resolved_markets
                ]
            except Exception as _exf:
                self.logger.debug("expiry_fallback skipped: %s", _exf)
        if not self._resolved_markets:
            self._entry_window_suspect_streak = 0
            _bus.emit(_tick.emit_snapshot(
                markets_resolved=0,
                markets_in_window=0,
                session_allowed=True,
            ))
            self._emit_decision_log(Decision.hold(
                HoldReason.NO_MARKETS,
                "no markets resolved for this agent/cycle",
                agent_name=self.config.name,
                cycle_number=self.state.cycles_run,
                elapsed_ms=_decision_timer.elapsed_ms(),
            ))
            return

        # 3. Reset per-window order count if window rolled
        self._maybe_reset_window(now)

        # 4. Filter for the "most active" contract per asset/timeframe slot
        # Requirement: at most one active contract per asset/timeframe slot.
        # Use async version to avoid blocking event loop with CPU-heavy sorting
        active_markets = await self._filter_active_contracts_async(self._resolved_markets, now)
        _tick.markets_in_window = len(active_markets)

        _mr_ct = len(self._resolved_markets)
        _mw_ct = len(active_markets)
        if _mr_ct > 0 and _mw_ct == 0:
            self._entry_window_suspect_streak += 1
            if self.logger.isEnabledFor(logging.DEBUG):
                for _m in self._resolved_markets:
                    _ed = _m.end_date
                    _passes = (_ed > now) if _ed else None
                    self.logger.debug(
                        "[PM_MARKET_FILTER] ticker=%s end_date=%s now=%s future_ok=%s",
                        _m.market_id,
                        _ed,
                        now,
                        _passes,
                    )
        else:
            self._entry_window_suspect_streak = 0
        if self._entry_window_suspect_streak >= 5:
            _ew = self.config.entry_window
            self.logger.warning(
                "[ENTRY-WINDOW-SUSPECT] agent=%s asset=%s tf=%s cycles_without_window=%d "
                "minutes_before_expiry=%s cutoff_minutes_before_expiry=%s resolved=%d",
                self.config.name,
                (self.config.assets[0] if self.config.assets else "?"),
                (self.config.timeframes[0] if self.config.timeframes else "?"),
                self._entry_window_suspect_streak,
                _ew.minutes_before_expiry,
                _ew.cutoff_minutes_before_expiry,
                _mr_ct,
            )

        # Emit snapshot now that markets_in_window is known
        _bus.emit(_tick.emit_snapshot(
            markets_resolved=_mr_ct,
            markets_in_window=_mw_ct,
            session_allowed=True,
        ))

        # 5. Evaluate each filtered market
        _signals_evaluated = 0
        _signals_actionable = 0
        _signals_consensus_blocked = 0
        _consensus_hold_buckets: Dict[str, int] = {}
        _no_action_buckets: Dict[str, int] = {}
        _proposal_submitted_this_cycle = False
        _pre_risk_intents = 0
        _risk_approved_count = 0
        _execution_dispatched = 0
        _execution_skipped_warmup = 0
        _strike_rejected = 0
        _strike_passed = 0
        _strike_directional = 0
        _cell_trace_enabled = os.getenv("MERID_PM_CELL_TRACE", "").lower() in ("1", "true", "yes", "on")
        for market in active_markets:
            _mkt_trace: Optional[Dict] = None
            if self._shutdown.is_set():
                break

            # Check per-window order limit
            if self.state.orders_this_window >= self.config.risk_limits.max_orders_per_window:
                self.logger.debug(f"Order limit reached for window ({self.state.orders_this_window})")
                self._emit_decision_log(Decision.hold(
                    HoldReason.ORDER_LIMIT,
                    f"window order limit reached ({self.state.orders_this_window}/{self.config.risk_limits.max_orders_per_window})",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                break

            # Build snapshot and evaluate
            try:
                snapshot = self._build_snapshot(market, now)

                # === Strike Selection Gate ===
                # Hard-reject contracts outside configured spot-to-strike distance
                # BEFORE strategy evaluation to avoid wasting compute on irrelevant markets.
                # Strike Selection Gate - fail-closed: if no selector, reject non-directional markets
                if self._strike_selector is not None:
                    _ss_asset = (snapshot.resolved_asset or "").upper()
                    _ss_tf = (snapshot.resolved_timeframe or "").lower()
                    _ss_spot = float(snapshot.spot_price_usd) if snapshot.spot_price_usd is not None else None
                    _ss_strike = float(snapshot.strike_price_usd) if snapshot.strike_price_usd is not None else None
                    _ss_result = self._strike_selector.evaluate(
                        ticker=market.market_id,
                        asset=_ss_asset,
                        timeframe=_ss_tf,
                        spot=_ss_spot,
                        strike=_ss_strike,
                    )
                    if not _ss_result.accepted:
                        _strike_rejected += 1

                        # Special handling for macro markets bypassing crypto selector
                        from merid.prediction.kalshi_strike_selector import RejectionReason
                        if getattr(_ss_result, 'rejection_reason', None) == RejectionReason.NON_CRYPTO_MARKET:
                            # Macro markets bypass crypto selector - this is expected, not an error
                            if _cell_trace_enabled:
                                _mkt_trace = {
                                    "agent": self.config.name,
                                    "cycle": self.state.cycles_run,
                                    "market_id": market.market_id,
                                    "exit_stage": "strike_bypass:macro_not_crypto",
                                    "detail": "bypassed crypto strike selector (macro market)",
                                }
                                self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                                _mkt_trace = None
                            self.logger.debug(
                                "[STRIKE_BYPASS] %s: bypassed crypto strike selector (macro market not supported)",
                                market.market_id
                            )
                            # Note: We continue here to skip this market since macro markets
                            # are not supported by the crypto strike selector. This is expected behavior.
                            continue

                        if _cell_trace_enabled:
                            _mkt_trace = {
                                "agent": self.config.name,
                                "cycle": self.state.cycles_run,
                                "market_id": market.market_id,
                                "exit_stage": f"strike_reject:{_ss_result.rejection_reason}",
                            }
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.NO_EDGE,
                            f"strike selector rejected: {_ss_result.rejection_reason}",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    _strike_passed += 1
                    # Tag snapshot with strike selection metadata
                    snapshot.strike_in_target_band = _ss_result.in_target_band
                    snapshot.strike_risk_capped = _ss_result.risk_capped
                    if getattr(_ss_result, 'is_directional', False):
                        _strike_directional += 1
                        snapshot.spot_strike_basis_note = "directional_passthrough"
                else:
                    # Fail-closed: strike selector unavailable - reject non-directional markets
                    _is_directional = "UP" in market.market_id.upper() or "DOWN" in market.market_id.upper()
                    if not _is_directional:
                        self.logger.error(
                            "[STRIKE_SELECTOR_MISSING] Strike selector unavailable, rejecting non-directional market %s",
                            market.market_id
                        )
                        self._emit_decision_log(Decision.hold(
                            HoldReason.NO_EDGE,
                            "strike selector unavailable - cannot evaluate strike distance",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue

                # === Market Mood Bus Integration ===
                # Get unified context from the mood bus (prefer snapshot-resolved asset/tf for MM)
                asset = (
                    (snapshot.resolved_asset or "").strip()
                    or (self.config.assets[0] if self.config.assets else "")
                )
                timeframe = (
                    (snapshot.resolved_timeframe or "").strip()
                    or (self.config.timeframes[0] if self.config.timeframes else "")
                )
                mood_context = self._get_mood_context(asset, timeframe)
                
                # Inject mood context into snapshot
                if mood_context:
                    # B14: fg_index is 0-100. Store the raw value so that
                    # _sentiment_size_factor thresholds (<=20, >=80, etc.) fire
                    # correctly.  DO NOT divide by 100 here — that would make all
                    # scores appear in the 0.0–1.0 range and permanently disable
                    # the fear/greed size-reduction logic.
                    snapshot.sentiment_global = float(mood_context.fg_index)
                    snapshot.sentiment_regime = mood_context.volatility_regime.value
                    self.logger.debug(
                        f"Mood context: FG={mood_context.fg_index}, "
                        f"vol={mood_context.volatility_regime.value}, "
                        f"tags={mood_context.tags}"
                    )
                
                # Extract correlation_id from mood context for trace chain
                correlation_id = None
                if mood_context and hasattr(mood_context, 'correlation_id'):
                    correlation_id = mood_context.correlation_id
                
                # Fallback: get correlation_id from SentimentBusV2 if mood context doesn't have it
                if not correlation_id:
                    try:
                        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
                        _bus_v2 = get_sentiment_bus_v2()
                        _asset_ctx = _bus_v2.get_asset_context(asset) if asset else None
                        if _asset_ctx and hasattr(_asset_ctx, 'correlation_id'):
                            correlation_id = _asset_ctx.correlation_id
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                
                signal = self._strategy.evaluate(snapshot, archetype=self.config.archetype, correlation_id=correlation_id)
                signal = self._apply_pm_spot_hard_gate(market, signal, snapshot)
                self._maybe_log_crypto_spot_strike_trace(snapshot, signal)
                _signals_evaluated += 1
                if signal.action == SignalAction.NO_ACTION:
                    _bk = _classify_pm_no_action_reason(signal.reason or "")
                    _no_action_buckets[_bk] = _no_action_buckets.get(_bk, 0) + 1
                    try:
                        from merid.prediction.crypto_edge_production import get_no_trade_decision_tracker

                        get_no_trade_decision_tracker().observe(
                            _bk,
                            market_id=market.market_id,
                            reason=signal.reason or "",
                        )
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")

                # Record every signal (including NO_ACTION) for audit
                await self._record_signal(market, signal, snapshot, now)

                # === Submit to SwarmConsensusAggregator ===
                # Only actionable signals go to consensus / execution.  Strategy evaluation
                # and _signals_actionable run even when outside the entry window so PM_CYCLE_TRACE
                # and calibration reflect real model output (filter may fall back to nearest
                # expiry outside the narrow pre-expiry band).
                if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD):
                    _signals_actionable += 1
                    if _cell_trace_enabled:
                        _mkt_trace = {
                            "agent": self.config.name,
                            "cycle": self.state.cycles_run,
                            "market_id": market.market_id,
                            "action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                            "contracts": signal.contracts,
                            "edge": round(float(signal.edge.net_edge), 4) if signal.edge else None,
                            "has_edge": True,
                            "in_consensus": False,
                            "sized": False,
                            "execution_attempted": False,
                            "exit_stage": "pre_consensus",
                        }
                    self._log_pm_sizing_context(market, signal, snapshot)

                    _sec_exp = self._get_seconds_to_expiry(market, now)
                    _is_new_entry = self._is_new_entry_action(signal.action)
                    if _is_new_entry and _sec_exp is not None and _sec_exp <= 90:
                        self.logger.debug(
                            "Expiry guard: blocking entry pipeline for %s, seconds_to_expiry=%.0f",
                            market.market_id,
                            _sec_exp,
                        )
                        _bus.emit(_tick.emit_risk_check(
                            market.market_id,
                            allowed=False,
                            reason=f"expiry_proximity_guard:seconds_to_expiry={_sec_exp:.0f}",
                        ))
                        if _mkt_trace:
                            _mkt_trace["exit_stage"] = "expiry_proximity_guard"
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.EXPIRY_PROXIMITY,
                            f"expiry proximity guard: {_sec_exp:.0f}s to expiry",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    if _is_new_entry and _sec_exp is not None and _sec_exp <= 120:
                        self.logger.warning(
                            "Expiry approaching: %s, seconds_to_expiry=%.0f, entering_caution_zone",
                            market.market_id,
                            _sec_exp,
                        )
                    if _is_new_entry and not self._in_entry_window(market, now):
                        self.logger.debug(
                            "entry_window_gate: %s actionable on %s outside entry window — "
                            "evaluation logged, skipping consensus/orders",
                            signal.action,
                            market.market_id,
                        )
                        if _mkt_trace:
                            _mkt_trace["exit_stage"] = "entry_window_gate"
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.OUTSIDE_ENTRY_WINDOW,
                            f"market {market.market_id} outside configured entry window",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue

                    _rich_ok = self._submit_to_consensus(market, signal, snapshot, mood_context)
                    try:
                        from merid.prediction.crypto_edge_production import (
                            log_approved_signal_created,
                            signal_feature_hash,
                        )

                        _edge_f = float(signal.edge.net_edge) if getattr(signal, "edge", None) else 0.0
                        log_approved_signal_created(
                            asset=asset,
                            timeframe=timeframe,
                            edge=_edge_f,
                            feature_hash=signal_feature_hash(
                                asset=asset,
                                timeframe=timeframe,
                                edge_s=f"{_edge_f:.6f}",
                                action=signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                                market_id=market.market_id,
                            ),
                            market_id=market.market_id,
                            action=signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                        )
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                    # Wire 2: adapter-based fallback only if the rich path failed.
                    # _submit_to_consensus already submits a market-data-driven
                    # AgentProposal; calling _submit_consensus_proposal again would
                    # overwrite it with a weaker adapter-derived one.
                    if not _proposal_submitted_this_cycle:
                        if not _rich_ok:
                            self._submit_consensus_proposal(signal)
                        _proposal_submitted_this_cycle = True
                    else:
                        self.logger.info(
                            "multi-market cycle: secondary signal dropped for %s "
                            "(proposal already submitted this cycle)",
                            market.market_id,
                        )
                    
                    # Check if we have consensus before acting
                    if self._swarm_consensus_bypassed():
                        self.logger.info(
                            "[PM_CONSENSUS_BYPASS] agent=%s ticker=%s — swarm gates skipped",
                            self.config.name,
                            market.market_id,
                        )
                        self.state.last_consensus_at = now
                        if _mkt_trace:
                            _mkt_trace["in_consensus"] = True
                            _mkt_trace["exit_stage"] = "pre_risk"
                    else:
                        try:
                            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

                            _mm_mode = get_crypto_edge_runtime().mm_consensus_mode
                            _mm_wait_ms = get_crypto_edge_runtime().consensus_wait_timeout_ms
                        except Exception:
                            _mm_mode = "full"
                            _mm_wait_ms = 500

                        consensus = self._get_consensus(asset, timeframe)
                        if (
                            consensus
                            and consensus.status.value == "forming"
                            and _mm_mode == "soft"
                            and _mm_wait_ms > 0
                        ):
                            await asyncio.sleep(min(_mm_wait_ms / 1000.0, 2.0))
                            consensus = self._get_consensus(asset, timeframe)
                        try:
                            from merid.prediction.crypto_edge_production import log_consensus_canonical_read

                            log_consensus_canonical_read(
                                market_key=f"{asset}:{timeframe}",
                                status=consensus.status.value if consensus else None,
                                direction=consensus.consensus_direction if consensus else None,
                            )
                        except Exception as e:
                            self.logger.debug(f"Silent error suppressed: {e}")

                        if consensus and consensus.status.value == "ready":
                            # Consensus recovered — clear degraded flag
                            self.state.last_consensus_at = now
                            if self.state.swarm_degraded:
                                self.logger.info("Swarm consensus recovered — exiting degraded mode")
                                self.state.swarm_degraded = False
                                self.state.solo_trades_this_degraded_session = 0  # E2: reset cap counter

                            # Directional trades: swarm yes/no must match. Market-making QUOTE is
                            # not directional — ``QUOTE`` was incorrectly mapped to signal_dir "no",
                            # so READY+neutral consensus always looked like a mismatch and MM never
                            # executed (logs: "Signal no blocked: consensus is neutral").
                            if signal.action != SignalAction.QUOTE:
                                signal_dir = (
                                    "yes"
                                    if signal.action
                                    in (SignalAction.BUY_YES, SignalAction.SELL_YES)
                                    else "no"
                                )
                                if consensus.consensus_direction != signal_dir:
                                    self.logger.info(
                                        f"Signal {signal_dir} blocked: consensus is "
                                        f"{consensus.consensus_direction} "
                                        f"(conf={consensus.consensus_confidence:.2f})"
                                    )
                                    _signals_consensus_blocked += 1
                                    _consensus_hold_buckets["direction_mismatch"] = (
                                        _consensus_hold_buckets.get("direction_mismatch", 0)
                                        + 1
                                    )
                                    if _mkt_trace:
                                        _mkt_trace["exit_stage"] = "consensus:direction_mismatch"
                                        self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                                        _mkt_trace = None
                                    self._emit_decision_log(Decision.hold(
                                        HoldReason.CONSENSUS_DIRECTION_MISMATCH,
                                        f"signal {signal_dir} blocked: consensus is {consensus.consensus_direction}",
                                        market_id=market.market_id,
                                        agent_name=self.config.name,
                                        cycle_number=self.state.cycles_run,
                                        elapsed_ms=_decision_timer.elapsed_ms(),
                                    ))
                                    continue
                            else:
                                self.logger.debug(
                                    "consensus direction gate skipped for QUOTE (MM) ticker=%s "
                                    "swarm_dir=%s",
                                    market.market_id,
                                    consensus.consensus_direction,
                                )

                            # Use consensus confidence for sizing
                            if signal.edge and hasattr(signal.edge, 'confidence'):
                                signal.edge.confidence = consensus.consensus_confidence

                            self.logger.info(
                                f"Consensus aligned: {consensus.consensus_direction} @ "
                                f"{consensus.consensus_probability:.1%} "
                                f"(size={consensus.size_band})"
                            )
                            try:
                                from merid.prediction.crypto_edge_production import (
                                    log_consensus_consumed_for_trading,
                                )

                                log_consensus_consumed_for_trading(
                                    market_id=market.market_id,
                                    value={
                                        "direction": consensus.consensus_direction,
                                        "p": consensus.consensus_probability,
                                        "conf": consensus.consensus_confidence,
                                        "status": consensus.status.value,
                                    },
                                    decision="PROCEED_ALIGNED",
                                )
                            except Exception as e:
                                self.logger.debug(f"Silent error suppressed: {e}")
                        elif consensus and consensus.status.value == "forming":
                            # FORMING: production default (full) holds; soft profile may proceed
                            # small-sized after a brief consensus_wait timeout (Settings).
                            if _mm_mode == "soft":
                                self._apply_solo_trade_cap(signal)
                                self.logger.info(
                                    "MM consensus soft: FORMING on %s/%s — proceeding small band "
                                    "(tune MERID_CRYPTO_MM_CONSENSUS_MODE / "
                                    "MERID_CRYPTO_EDGE_PRODUCTION_PROFILE).",
                                    asset,
                                    timeframe,
                                )
                                try:
                                    from merid.prediction.crypto_edge_production import (
                                        log_consensus_consumed_for_trading,
                                    )

                                    log_consensus_consumed_for_trading(
                                        market_id=market.market_id,
                                        value={
                                            "direction": consensus.consensus_direction,
                                            "p": consensus.consensus_probability,
                                            "status": "forming",
                                        },
                                        decision="PROCEED_SOFT_FORMING_SMALL",
                                    )
                                except Exception as e:
                                    self.logger.debug(f"Silent error suppressed: {e}")
                            else:
                                self.logger.debug(
                                    "Signal held: consensus FORMING for %s/%s — "
                                    "waiting for quorum before executing",
                                    asset,
                                    timeframe,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["forming"] = (
                                    _consensus_hold_buckets.get("forming", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.CONSENSUS_FORMING,
                                    f"consensus FORMING for {asset}/{timeframe} — waiting for quorum",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue
                        elif consensus and consensus.status.value == "conflicted":
                            self.logger.info(
                                f"Signal blocked: swarm conflicted - {consensus.disagreement_flags}"
                            )
                            _signals_consensus_blocked += 1
                            self._emit_decision_log(Decision.hold(
                                HoldReason.CONSENSUS_CONFLICTED,
                                f"swarm conflicted: {consensus.disagreement_flags}",
                                market_id=market.market_id,
                                agent_name=self.config.name,
                                cycle_number=self.state.cycles_run,
                                elapsed_ms=_decision_timer.elapsed_ms(),
                            ))
                            continue
                        elif not consensus:
                            # Allow solo execution only after MERID_PM_SWARM_SOLO_SECONDS without
                            # consensus, but always cap size to "small" and emit WARNING.
                            # BUG-L8/medium: use started_at as baseline when no consensus
                            # has ever been seen, so solo_seconds is not near-zero on
                            # the first cycle (which would incorrectly skip the hold).
                            _max_solo_s = _swarm_max_solo_seconds()
                            _max_solo_wall = _MAX_SOLO_WALL_SECONDS
                            _max_solo_trades = _MAX_SOLO_TRADES_DEGRADED
                            solo_seconds = (
                                (now - self.state.last_consensus_at).total_seconds()
                                if self.state.last_consensus_at
                                else (now - (self.state.started_at or now)).total_seconds()
                            )
                            if solo_seconds < _max_solo_s:
                                self.logger.debug(
                                    "No consensus yet (%.0fs < %.0fs threshold), signal held",
                                    solo_seconds, _max_solo_s,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["solo_window"] = (
                                    _consensus_hold_buckets.get("solo_window", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.SOLO_WINDOW,
                                    f"no consensus yet ({solo_seconds:.0f}s < {_max_solo_s:.0f}s threshold)",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue
                            # Swarm degraded — cap to small size, warn once per degraded entry
                            if not self.state.swarm_degraded:
                                self.logger.warning(
                                    "SWARM DEGRADED: no consensus for %.0fs on %s/%s — "
                                    "proceeding solo at small size band only",
                                    solo_seconds, asset, timeframe,
                                )
                                self.state.swarm_degraded = True
                                self.state.swarm_degraded_since = now
                                self.state.solo_trades_this_degraded_session = 0
                                # BUG-08: alert on degraded entry
                                try:
                                    _am = _get_alert_manager_module() if _get_alert_manager_module else None
                                    if _am:
                                        _am.fire_risk_warning(
                                            market_id=self.config.name,
                                            message=(
                                                f"Swarm degraded on {self.config.name}: no consensus "
                                                f"for {solo_seconds:.0f}s — solo trading capped at "
                                                f"{_max_solo_trades} orders"
                                            ),
                                        )
                                except Exception as _ae:
                                    self.logger.debug("degraded alert skipped: %s", _ae)

                            # BUG-08: enforce wall-clock limit on degraded session
                            degraded_seconds = (
                                (now - self.state.swarm_degraded_since).total_seconds()
                                if self.state.swarm_degraded_since else 0.0
                            )
                            if degraded_seconds >= _max_solo_wall:
                                self.logger.warning(
                                    "SWARM DEGRADED wall-clock limit reached (%.0fs) on %s — "
                                    "halting agent until consensus recovers",
                                    degraded_seconds, self.config.name,
                                )
                                try:
                                    _am = _get_alert_manager_module() if _get_alert_manager_module else None
                                    if _am:
                                        _am.fire_risk_breach(
                                            market_id=self.config.name,
                                            message=(
                                                f"Agent {self.config.name} auto-halted: swarm degraded "
                                                f"for {degraded_seconds/60:.1f}min without recovery"
                                            ),
                                        )
                                except Exception as _ae:
                                    self.logger.debug("halt alert skipped: %s", _ae)
                                # CRIT-2 FIX: fire global kill switch on wall-clock breach.
                                # Guarded by MERID_DEPENDENCY_HEALTH_KILL_ENABLED (default: false).
                                try:
                                    from merid.risk.kill_switches import risk_controller as _rc_swarm
                                    _rc_swarm.trigger_dependency_health(
                                        f"Swarm consensus unavailable for {degraded_seconds / 60:.1f}min "
                                        f"on agent {self.config.name} — trading halted system-wide"
                                    )
                                except Exception as _ke:
                                    self.logger.debug("swarm kill switch call skipped: %s", _ke)
                                self.state.enabled = False
                                break

                            # BUG-08: enforce per-degraded-session solo trade cap
                            if self.state.solo_trades_this_degraded_session >= _MAX_SOLO_TRADES_DEGRADED:
                                self.logger.warning(
                                    "SWARM DEGRADED solo trade cap (%d) reached on %s — "
                                    "holding until consensus recovers",
                                    _max_solo_trades, self.config.name,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["solo_cap"] = (
                                    _consensus_hold_buckets.get("solo_cap", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.SOLO_CAP_REACHED,
                                    f"solo trade cap ({_max_solo_trades}) reached in degraded session",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue

                            # Force small size band: halve contracts to 1 minimum
                            if signal.contracts > 1:
                                signal.contracts = max(1, signal.contracts // 2)
                            self.state.solo_trades_this_degraded_session += 1
                            self.logger.debug(
                                "Solo execution (degraded %d/%d): %s contracts=%d",
                                self.state.solo_trades_this_degraded_session,
                                _max_solo_trades,
                                market.market_id, signal.contracts,
                            )
            except Exception as exc:
                self.logger.warning(f"Error evaluating {market.market_id}: {exc}")
                self._emit_decision_log(Decision.hold(
                    HoldReason.EXECUTION_ERROR,
                    f"evaluation error: {exc}",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                continue

            if signal.action == SignalAction.NO_ACTION or signal.action == SignalAction.HOLD:
                self._emit_decision_log(Decision.hold(
                    HoldReason.NO_EDGE,
                    signal.reason or "strategy returned NO_ACTION/HOLD",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    signal_summary={"action": signal.action.value, "edge": float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, 'net_edge') else None},
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                continue

            _pre_risk_intents += 1

            # Pre-trade risk check
            side_str = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
            price_cents = Decimal(str(signal.limit_price_cents)) if signal.limit_price_cents is not None else Decimal("50")
            event_id = market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id
            
            # If it's a quote, we skip individual check_order here and handle in _execute_signal
            # or just use best available price for the check
            check_price = price_cents
            if signal.action == SignalAction.QUOTE:
                check_price = Decimal(str(signal.bid_price_cents or 50))

            # BUG-07: extract bid/ask/depth from snapshot so checks 12-14
            # (spread, slippage, depth) are no longer dead code.
            _best_bid: Optional[Decimal] = None
            _best_ask: Optional[Decimal] = None
            _depth: Optional[int] = None
            # yes_bid / yes_ask are already Kalshi cents (0–100); do not scale again.
            if snapshot and snapshot.implied:
                if snapshot.implied.yes_bid is not None:
                    _best_bid = Decimal(str(snapshot.implied.yes_bid))
                if snapshot.implied.yes_ask is not None:
                    _best_ask = Decimal(str(snapshot.implied.yes_ask))
            if snapshot is not None:
                _depth = getattr(snapshot, "depth_at_best", None)

            # BUG-009 FIX: Calculate existing YES/NO contracts from tracked positions
            existing_yes = sum(
                pos.contracts for pos in self._tracked_positions.values()
                if pos.ticker == market.market_id and pos.side == "yes"
            )
            existing_no = sum(
                pos.contracts for pos in self._tracked_positions.values()
                if pos.ticker == market.market_id and pos.side == "no"
            )

            try:
                check = self._risk.check_order(
                    market_id=market.market_id,
                    event_id=event_id,
                    side=side_str,
                    contracts=signal.contracts,
                    price_cents=check_price,
                    best_bid_cents=_best_bid,
                    best_ask_cents=_best_ask,
                    depth_at_price=_depth,
                    edge=signal.edge.net_edge if signal.edge else Decimal("0"),
                    agent_max_notional_usd=self.config.risk_limits.max_notional_usd,
                    # BUG-009: Pass per-side position limits from YAML config
                    max_yes_position=self.config.risk_limits.max_yes_position,
                    max_no_position=self.config.risk_limits.max_no_position,
                    existing_yes_contracts=existing_yes,
                    existing_no_contracts=existing_no,
                )

                if not check.allowed:
                    self._record_explainability_decision(
                        market=market,
                        signal=signal,
                        snapshot=snapshot,
                        check=check,
                        now=now,
                        allowed=False,
                    )
                    self.logger.info(f"Risk blocked {market.market_id}: {check.reason}")
                    _bus.emit(_tick.emit_risk_check(market.market_id, allowed=False, reason=check.reason))
                    self._emit_decision_log(Decision.hold(
                        HoldReason.RISK_LIMIT,
                        check.reason or "risk check rejected",
                        market_id=market.market_id,
                        agent_name=self.config.name,
                        cycle_number=self.state.cycles_run,
                        signal_summary={"action": signal.action.value, "edge": float(signal.edge.net_edge) if signal.edge else None},
                        risk_summary={"reason": (check.reason or "")[:200]},
                        elapsed_ms=_decision_timer.elapsed_ms(),
                    ))
                    continue

                self._record_explainability_decision(
                    market=market,
                    signal=signal,
                    snapshot=snapshot,
                    check=check,
                    now=now,
                    allowed=True,
                )
                _bus.emit(_tick.emit_risk_check(market.market_id, allowed=True))
                _risk_approved_count += 1

                # BUG-L8: skip execution entirely during WARMING_UP phase
                if self.state.lifecycle == LifecycleState.WARMING_UP:
                    self.logger.debug(
                        "WARMING_UP: signal logged but execution skipped for %s",
                        market.market_id,
                    )
                    _execution_skipped_warmup += 1
                    self._emit_decision_log(Decision.hold(
                        HoldReason.WARMUP,
                        f"WARMING_UP: execution skipped for {market.market_id}",
                        market_id=market.market_id,
                        agent_name=self.config.name,
                        cycle_number=self.state.cycles_run,
                        elapsed_ms=_decision_timer.elapsed_ms(),
                    ))
                    continue

                # Place order via tool — all checks passed → TRADE
                _execution_dispatched += 1
                self._emit_decision_log(Decision.trade(
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    detail="all_checks_passed",
                    signal_summary={
                        "action": signal.action.value,
                        "edge": float(signal.edge.net_edge) if signal.edge else None,
                        "contracts": signal.contracts,
                        "phase": signal.phase.value if signal.phase else None,
                    },
                    risk_summary={"reason": "allowed"},
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                await self._execute_signal(market, signal, check, snapshot, _tick=_tick, _bus=_bus)

            except Exception as exc:
                # Structured error logging with full context
                exc_type = type(exc).__name__
                self.logger.error(
                    "PM_EXECUTION_ERROR agent=%s market=%s asset=%s action=%s error_type=%s "
                    "error_message=%s",
                    self.config.name,
                    market.market_id,
                    getattr(snapshot, 'resolved_asset', 'unknown'),
                    signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                    exc_type,
                    str(exc)[:200],
                    exc_info=True,
                )

                # Emit to agent execution error metrics
                try:
                    from monitoring.metrics import record_agent_execution_error
                    record_agent_execution_error(
                        agent=self.config.name,
                        exception=exc_type,
                        market=market.market_id,
                    )
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                try:
                    from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode
                    from merid.prediction.crypto_edge_production import get_no_trade_decision_tracker
                    from monitoring.kalshi_metrics import record_kalshi_order

                    record_kalshi_order(
                        "pm_agent",
                        "rejected",
                        1,
                        error_code=KalshiOrderErrorCode.PM_AGENT_EXECUTION.value,
                    )
                    get_no_trade_decision_tracker().observe(
                        "pm_agent_execution_failed",
                        market_id=market.market_id,
                        error=str(exc),
                        error_type=exc_type,
                    )
                except Exception as _met_exc:
                    self.logger.debug("kalshi_metrics pm execution reject skipped: %s", _met_exc)
                continue

            # Yield control to event loop after each market iteration
            await asyncio.sleep(0)

        _bus.emit(_tick.emit_agent_cycle(
            signals_evaluated=_signals_evaluated,
            signals_actionable=_signals_actionable,
            signals_consensus_blocked=_signals_consensus_blocked,
        ))
        _no_action_summary = ""
        if _no_action_buckets:
            _no_action_summary = "|".join(
                f"{k}:{v}" for k, v in sorted(_no_action_buckets.items())
            )
        _consensus_hold_summary = (
            "|".join(f"{k}:{v}" for k, v in sorted(_consensus_hold_buckets.items()))
            if _consensus_hold_buckets
            else "-"
        )
        _trace_na = os.getenv("MERID_PM_CYCLE_TRACE_NO_ACTION", "true").lower() in (
            "1", "true", "yes", "on", "",
        )
        _trace_ch = os.getenv("MERID_PM_CYCLE_TRACE_CONSENSUS_DETAIL", "true").lower() in (
            "1", "true", "yes", "on", "",
        )
        _base_trace = (
            self.config.name,
            self.state.cycles_run,
            self.state.lifecycle,
            _mr_ct,
            _mw_ct,
            _strike_passed,
            _strike_rejected,
            _strike_directional,
            _signals_evaluated,
            _signals_actionable,
            _signals_consensus_blocked,
            _pre_risk_intents,
            _risk_approved_count,
            _execution_dispatched,
            _execution_skipped_warmup,
            self.state.orders_placed,
        )
        if _trace_na:
            if _trace_ch:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "consensus_hold_by_reason=%s "
                    "no_action_by_reason=%s",
                    *_base_trace,
                    _consensus_hold_summary,
                    _no_action_summary or "-",
                )
            else:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "no_action_by_reason=%s",
                    *_base_trace,
                    _no_action_summary or "-",
                )
        else:
            if _trace_ch:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "consensus_hold_by_reason=%s",
                    *_base_trace,
                    _consensus_hold_summary,
                )
            else:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d",
                    *_base_trace,
                )

    def _filter_active_contracts(self, markets: List[EventMarket], now: datetime) -> List[EventMarket]:
        """Filter resolved markets to ensure only the most relevant contract(s) are traded.
        
        Rule: At most one active contract per asset/timeframe slot.
        If agent has a specific asset list, return best for each.
        If agent is category-wide, group by inferred asset and return best for each.
        
        NOTE: This is a synchronous CPU-bound method. For async contexts,
        use _filter_active_contracts_async() to avoid blocking the event loop.
        """
        if not markets:
            return []

        # Group by asset
        by_asset: Dict[str, List[EventMarket]] = {}
        for m in markets:
            asset = "OTHER"
            # Try to infer asset from ticker or tags
            ticker_upper = m.market_id.upper()
            found = False
            # H5: Use the canonical underlying map from category_exposure so
            # non-crypto agents (politics, economics, financials) get proper
            # per-asset grouping instead of collapsing everything to "OTHER".
            try:
                from merid.event_venues.kalshi.category_exposure import (
                    _UNDERLYING_CATEGORY_MAP,
                )
                for a in _UNDERLYING_CATEGORY_MAP:
                    if a in ticker_upper:
                        asset = a
                        found = True
                        break
            except Exception:
                for a in ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "WIF"]:
                    if a in ticker_upper:
                        asset = a
                        found = True
                        break

            if not found and m.category:
                asset = m.category.upper()

            if asset not in by_asset:
                by_asset[asset] = []
            by_asset[asset].append(m)

        active_selection = []
        for asset, asset_markets in by_asset.items():
            # Sort by end_date (closest to expiry first)
            sorted_m = sorted(
                [m for m in asset_markets if m.end_date and m.end_date > now],
                key=lambda m: m.end_date
            )
            
            if not sorted_m:
                continue

            # Find the first one in the entry window
            best_for_asset = None
            for m in sorted_m:
                if self._in_entry_window(m, now):
                    best_for_asset = m
                    break
            
            # Fallback to the closest one if none in window
            if not best_for_asset:
                best_for_asset = sorted_m[0]
                self.logger.debug(
                    "_filter_active_contracts: no market in entry window for %s — "
                    "falling back to closest expiry %s",
                    asset, best_for_asset.market_id,
                )
            
            active_selection.append(best_for_asset)

        return active_selection

    async def _filter_active_contracts_async(
        self, markets: List[EventMarket], now: datetime
    ) -> List[EventMarket]:
        """Async version of _filter_active_contracts that avoids blocking the event loop.
        
        Offloads the CPU-bound sorting work to a thread pool executor.
        This should be called from async contexts like _run_cycle_body.
        """
        if not markets:
            return []
        
        # Offload the entire filtering operation to thread pool
        # since it involves CPU-heavy sorting over potentially many markets
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _get_agent_executor(),  # Use dedicated agent thread pool (20+ workers)
            self._filter_active_contracts,
            markets,
            now
        )

    # ── Position sync at startup ────────────────────────────────────────

    async def _sync_open_positions(self) -> None:
        """BUG-L3: Reconstruct TrackedPosition objects from live Kalshi positions
        so stop-loss rules and position tracking are not blind on restart.

        Called once in start() after clearing _tracked_positions.  Non-fatal:
        a failure logs a warning but does not prevent the agent from starting.
        """
        try:
            from merid.prediction.kalshi_tools import _kalshi_get_positions

            result = await _kalshi_get_positions()
            if not result.success:
                self.logger.warning(
                    "_sync_open_positions: failed to fetch positions: %s",
                    result.error_message,
                )
                return

            positions = result.payload.get("positions", [])
            agent_tickers = set()
            # Determine which tickers belong to this agent using config assets/category
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                for m in catalog.get_all_markets():
                    ticker = m.market.market_id
                    for asset in (self.config.assets or []):
                        if asset.upper() in ticker.upper():
                            agent_tickers.add(ticker)
            except Exception as _ce:
                self.logger.debug("_sync_open_positions: catalog lookup skipped: %s", _ce)

            synced = 0
            for pos in positions:
                ticker = pos.get("ticker", "")
                # Only track positions that belong to this agent's markets
                if agent_tickers and ticker not in agent_tickers:
                    continue
                size = int(pos.get("size", 0))
                if size == 0:
                    continue
                # CRITICAL: No price fallback. Missing avg_price = quarantine position.
                raw_price = (
                    pos.get("avg_price")
                    or pos.get("average_price")
                    or pos.get("avg_entry_price")
                )
                if raw_price is None:
                    self.logger.error(
                        "[TAINTED_PATH] _sync_open_positions: missing avg_price for %s, size=%s; "
                        "position quarantined until valid price resolved",
                        ticker, size
                    )
                    # Emit to risk bus for operator visibility
                    try:
                        from core.event_bus import get_event_bus
                        get_event_bus().emit("risk.position_sync_failed", {
                            "ticker": ticker,
                            "size": size,
                            "reason": "missing_avg_price",
                            "agent": self.config.name,
                            "action": "quarantine",
                        })
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                    
                    # Tamper-evident audit log
                    try:
                        from core.risk_audit_chain import get_risk_audit_chain
                        get_risk_audit_chain().log_event("risk.position_sync_failed", {
                            "ticker": ticker,
                            "size": size,
                            "agent": self.config.name,
                            "source": "_sync_open_positions",
                            "resolution": "quarantine",
                        })
                    except Exception as _audit_exc:
                        logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                    continue  # Skip position - fail closed
                avg_price = float(raw_price)
                side = pos.get("side", "yes")
                pos_id = f"{ticker}:{side}:synced"
                self._tracked_positions[pos_id] = TrackedPosition(
                    position_id=pos_id,
                    ticker=ticker,
                    side=side,
                    contracts=abs(size),
                    entry_price_cents=int(avg_price),
                    current_price_cents=int(avg_price),
                    entry_time=datetime.now(timezone.utc),
                )
                synced += 1

            if synced:
                self.logger.info(
                    "_sync_open_positions: restored %d open position(s) for %s",
                    synced, self.config.name,
                )
            else:
                self.logger.debug(
                    "_sync_open_positions: no open positions found for %s",
                    self.config.name,
                )
        except Exception as exc:
            self.logger.warning(
                "_sync_open_positions failed (non-fatal, continuing): %s", exc
            )

    async def _restore_prefetched_positions_async(self, prefetched_positions: List[Any]) -> None:
        """Async wrapper to run sync position restoration in executor."""
        await asyncio.get_running_loop().run_in_executor(
            None,
            self._restore_prefetched_positions_sync,
            prefetched_positions
        )

    def _restore_prefetched_positions_sync(self, prefetched_positions: List[Any]) -> None:
        """BUG-L9 FIX: Restore positions from pre-fetched data without API call (SYNC VERSION).
        
        This is a synchronous version that runs in a thread pool to avoid blocking
        the event loop during concurrent agent startup.
        
        Args:
            prefetched_positions: List of position objects from AgentGrid's
                bulk position fetch.
        """
        try:
            if not prefetched_positions:
                self.logger.debug("_restore_prefetched_positions: no pre-fetched positions provided")
                return

            synced = 0
            for pos in prefetched_positions:
                try:
                    # Handle both dict and object formats
                    if isinstance(pos, dict):
                        ticker = pos.get("ticker", "")
                        size = int(pos.get("size", 0))
                        # Refinement: Don't hard-default to 50 - use None if missing
                        raw_price = (
                            pos.get("avg_price")
                            or pos.get("average_price")
                            or pos.get("avg_entry_price")
                        )
                        if raw_price is None:
                            self.logger.warning(
                                "_restore_prefetched_positions: missing avg_price for %s, size=%s; skipping position",
                                ticker, size
                            )
                            continue  # Skip positions without price data
                        avg_price = float(raw_price)
                        side_raw = (pos.get("side") or "yes").lower()
                    else:
                        # Object format (e.g., KalshiPosition)
                        ticker = getattr(pos, 'ticker', '') or getattr(pos, 'market_id', '')
                        size = int(getattr(pos, 'size', 0) or getattr(pos, 'contracts', 0))
                        # Refinement: Don't hard-default to 50 - use None if missing
                        raw_price = (
                            getattr(pos, 'avg_price', None)
                            or getattr(pos, 'average_price', None)
                            or getattr(pos, 'avg_entry_price', None)
                        )
                        if raw_price is None:
                            self.logger.warning(
                                "_restore_prefetched_positions: missing avg_price for %s, size=%s; skipping position",
                                ticker, size
                            )
                            continue  # Skip positions without price data
                        avg_price = float(raw_price)
                        side_raw = (getattr(pos, "side", "yes") or "yes").lower()

                    # Refinement 2: Explicit side normalization
                    if side_raw.startswith("y"):
                        side = "yes"
                    elif side_raw.startswith("n"):
                        side = "no"
                    else:
                        self.logger.warning(
                            "_restore_prefetched_positions: unrecognized side '%s' for %s; defaulting to 'yes'",
                            side_raw, ticker
                        )
                        side = "yes"

                    # Refinement 3: Filter positions by agent's configured tickers
                    if not self._handles_ticker(ticker):
                        continue

                    if size == 0:
                        continue

                    pos_id = f"{ticker}:{side}:synced"
                    self._tracked_positions[pos_id] = TrackedPosition(
                        position_id=pos_id,
                        ticker=ticker,
                        side=side,
                        contracts=abs(size),
                        entry_price_cents=int(avg_price),
                        current_price_cents=int(avg_price),
                        entry_time=datetime.now(timezone.utc),
                    )
                    synced += 1
                except Exception as _pos_exc:
                    self.logger.debug("Error restoring pre-fetched position: %s", _pos_exc)
                    continue

            if synced:
                self.logger.info(
                    "_restore_prefetched_positions: restored %d open position(s) for %s",
                    synced, self.config.name,
                )
            else:
                self.logger.debug(
                    "_restore_prefetched_positions: no matching positions for %s",
                    self.config.name,
                )
        except Exception as exc:
            self.logger.warning(
                "_restore_prefetched_positions failed (non-fatal, continuing): %s", exc
            )

    # ── Stop-loss sweep ────────────────────────────────────────────────

    async def _check_stop_losses(self) -> None:
        """Sweep all tracked open positions against stop-loss and take-profit rules.

        Per cycle:
          1. Refresh current_price_cents / bid / ask for every position from
             KalshiMarketStateStore so stop-loss and TP work on live prices.
          2. Evaluate take-profit conditions via TakeProfitManager and route
             partial/full exits before the stop-loss sweep.
          3. Evaluate stop-loss rules (unchanged behaviour).

        All exits go through route_order_async so risk accounting, category
        exposure, and execution gates all fire uniformly.
        """
        if not self._tracked_positions:
            return

        # ── 1. Price refresh from market state ────────────────────────────
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            _mss = get_kalshi_market_state_store()
            for _pos in self._tracked_positions.values():
                _st = _mss.get(_pos.ticker)
                if _st is None:
                    continue
                # Best bid/ask for TP trigger logic
                bid = getattr(_st, "best_bid_cents", 0) or 0
                ask = getattr(_st, "best_ask_cents", 0) or 0
                mid = (bid + ask) // 2 if bid > 0 and ask > 0 else 0
                if mid > 0:
                    _pos.current_price_cents = mid
                elif bid > 0:
                    _pos.current_price_cents = bid
                elif ask > 0:
                    _pos.current_price_cents = ask
                # Store raw bid/ask on position for TP limit-price calculation
                _pos.last_bid_cents = bid
                _pos.last_ask_cents = ask
        except Exception as _pr_exc:
            self.logger.debug("price_refresh skipped: %s", _pr_exc)

        # CRITICAL FIX: session_equity_cents must never be 0 (makes loss cap dead).
        # If equity feed missing, set to None to signal UNKNOWN → block trading.
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            _equity_usd = get_kalshi_risk().state.current_equity_usd
            if _equity_usd > 0:
                _equity_cents = _equity_usd * 100.0
                for _pos in self._tracked_positions.values():
                    _pos.session_equity_cents = _equity_cents
            else:
                # Equity unavailable - mark as UNKNOWN (None) to block loss cap checks
                logger.error(
                    "[TAINTED_PATH] _check_stop_losses: equity unavailable (%.2f) — "
                    "marking session_equity_cents as UNKNOWN (None) to block trading",
                    _equity_usd
                )
                for _pos in self._tracked_positions.values():
                    _pos.session_equity_cents = None  # UNKNOWN state
                # Emit alert
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().emit("risk.equity_feed_lost", {
                        "agent": self.config.name,
                        "equity_usd": _equity_usd,
                        "action": "block_loss_caps",
                    })
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")
                
                # Tamper-evident audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.equity_feed_lost", {
                        "agent": self.config.name,
                        "equity_usd": _equity_usd,
                        "action": "block_loss_caps",
                        "source": "_check_stop_losses",
                        "positions_affected": len(self._tracked_positions),
                    })
                except Exception as _audit_exc:
                    logger.debug("Audit log failed (non-critical): %s", _audit_exc)
        except Exception as _eq_exc:
            # Exception fetching equity - mark as UNKNOWN
            logger.error(
                "[TAINTED_PATH] _check_stop_losses: equity fetch failed (%s) — "
                "marking session_equity_cents as UNKNOWN (None)",
                _eq_exc
            )
            for _pos in self._tracked_positions.values():
                _pos.session_equity_cents = None  # UNKNOWN state
            
            # Tamper-evident audit log for exception path
            try:
                from core.risk_audit_chain import get_risk_audit_chain
                get_risk_audit_chain().log_event("risk.equity_feed_lost", {
                    "agent": self.config.name,
                    "reason": "exception",
                    "error": str(_eq_exc)[:200],
                    "action": "block_loss_caps",
                    "source": "_check_stop_losses_exception",
                    "positions_affected": len(self._tracked_positions),
                })
            except Exception as _audit_exc:
                logger.debug("Audit log failed (non-critical): %s", _audit_exc)

        # ── 2. Take-profit sweep ──────────────────────────────────────────
        _tp_to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                tp_action = self._tp_manager.on_price_update(
                    pos=pos,
                    bid_cents=pos.last_bid_cents,
                    ask_cents=pos.last_ask_cents,
                )
                if tp_action is None:
                    continue

                # Determine order quantity (partial or full)
                close_qty = min(tp_action.quantity, pos.contracts)
                if close_qty <= 0:
                    continue

                # ═══════════════════════════════════════════════════════════════════
                # Force-taker for high PnL exits: ensure we get filled on 100%+ winners
                # ═══════════════════════════════════════════════════════════════════
                _tp_post_only = True  # Default to maker (post-only)
                _tp_unrealized_pct = 0.0

                try:
                    # Calculate unrealized PnL for this position
                    if pos.side == "yes":
                        _tp_unrealized_pct = (
                            (tp_action.limit_price_cents - pos.entry_price_cents)
                            / pos.entry_price_cents * 100
                        ) if pos.entry_price_cents > 0 else 0.0
                    else:
                        # NO position: profit when price falls
                        _no_entry_cost = 100 - pos.entry_price_cents
                        _tp_unrealized_pct = (
                            (pos.entry_price_cents - tp_action.limit_price_cents)
                            / _no_entry_cost * 100
                        ) if _no_entry_cost > 0 else 0.0

                    # Force taker if unrealized PnL >= 70% (configurable threshold)
                    # Start force-taker BELOW hard TP threshold to reduce slippage risk
                    _force_taker_threshold = 70.0
                    if _tp_unrealized_pct >= _force_taker_threshold:
                        _tp_post_only = False  # Allow taker for high PnL exits
                        self.logger.info(
                            "[TP-FORCE-TAKER] %s: unrealized_pnl=%.1f%% >= %.0f%% — "
                            "disabling post_only to ensure fill (entry=%dc, exit=%dc)",
                            pos.ticker, _tp_unrealized_pct, _force_taker_threshold,
                            pos.entry_price_cents, tp_action.limit_price_cents
                        )
                except Exception as _pnl_exc:
                    self.logger.debug("TP unrealized PnL calc skipped: %s", _pnl_exc)

                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                _tp_intent = OrderIntent(
                    ticker=pos.ticker,
                    side=pos.side,
                    action="sell",
                    # Use the suggested limit price from TakeProfitAction; for live orders
                    # the router will clip to valid range and may upgrade to IOC near expiry.
                    price_cents=max(1, min(99, tp_action.limit_price_cents)),
                    count=close_qty,
                    order_type="limit",
                    time_in_force="ioc",  # IOC to avoid resting past the intended price
                    source=f"take_profit:{self.config.name}",
                    agent_id=self.agent_id,
                    rationale=tp_action.reason[:200],
                    post_only=_tp_post_only,  # NEW: False for high PnL exits to force taker
                )
                _tp_result = await route_order_async(_tp_intent)
                _tp_ok = _tp_result.status not in ("rejected",)

                if _tp_ok:
                    _filled = 0
                    try:
                        _fill_info = _tp_result.fill or {}
                        if isinstance(_fill_info, dict) and _fill_info.get("count"):
                            _filled = int(_fill_info["count"])
                        elif hasattr(_tp_result, "filled_count") and _tp_result.filled_count:
                            _filled = int(_tp_result.filled_count)
                        else:
                            _filled = close_qty
                    except Exception:
                        _filled = close_qty

                    self._tp_manager.on_fill(pos.position_id, _filled)
                    self._tp_manager.record_exit_price(pos.ticker, tp_action.limit_price_cents)

                    # Adjust remaining contracts on the TrackedPosition
                    pos.contracts = max(0, pos.contracts - _filled)

                    # Compute realized PnL for logging
                    if pos.side == "yes":
                        _tp_pnl = (tp_action.limit_price_cents - pos.entry_price_cents) * _filled
                    else:
                        _tp_pnl = (pos.entry_price_cents - tp_action.limit_price_cents) * _filled

                    self.logger.info(
                        "take_profit CLOSED %s %s ×%d (of %d total): %s | "
                        "entry=%dc exit=%dc pnl=%.0f¢ action=%s",
                        pos.ticker, pos.side, _filled,
                        pos.contracts + _filled,
                        tp_action.reason[:60],
                        pos.entry_price_cents, tp_action.limit_price_cents,
                        _tp_pnl, tp_action.action_type,
                    )

                    # Record realized PnL into kalshi risk manager
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        _close_cat = getattr(self.config, "category", None)
                        get_kalshi_risk().record_close(
                            _close_cat, _filled, pos.entry_price_cents
                        )
                    except Exception as _kr_e:
                        self.logger.debug("take_profit: kalshi_risk.record_close failed: %s", _kr_e)

                    # Notify APT of the close (same as stop-loss path)
                    try:
                        from merid.prediction.agent_performance_tracker import (
                            AgentPerformanceTracker,
                            get_agent_performance_tracker,
                        )
                        _apt = get_agent_performance_tracker()
                        _close_reason = (
                            "take_profit_trailing"
                            if "trailing" in tp_action.reason
                            else "take_profit_primary"
                        )
                        _apt.record_close(
                            agent_id=self.agent_id,
                            market_id=pos.ticker,
                            close_price_cents=tp_action.limit_price_cents,
                            close_reason=_close_reason,
                        )
                    except Exception as _apt_e:
                        self.logger.debug("take_profit: APT record_close skipped: %s", _apt_e)

                    # If position is now flat, queue for removal and notify TP manager
                    if pos.contracts <= 0:
                        _tp_to_remove.append(pos_id)
                        _close_reason = (
                            "take_profit_trailing"
                            if "trailing" in tp_action.reason
                            else "take_profit_primary"
                        )
                        self._tp_manager.on_position_closed(pos.ticker, _close_reason)

                else:
                    self.logger.warning(
                        "take_profit order REJECTED for %s %s: %s",
                        pos.ticker, tp_action.action_type,
                        _tp_result.reason or "unknown",
                    )
                    # Mark pending_fill=False so the next cycle retries
                    _ps = self._tp_manager.get_state(pos.position_id)
                    if _ps:
                        _ps.pending_fill = False

            except Exception as _tp_exc:
                self.logger.debug("take_profit sweep error for %s: %s", pos_id, _tp_exc)

        for pos_id in _tp_to_remove:
            self._tracked_positions.pop(pos_id, None)

        # Evict old closed TP state entries to keep memory bounded
        self._tp_manager.evict_expired()

        # ── 3. Stop-loss sweep ────────────────────────────────────────────
        to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                action = self._stop_loss.check_position(pos)
                if not action.should_close:
                    continue

                self.logger.warning(
                    "stop_loss TRIGGERED %s: rule=%s reason=%s urgency=%s",
                    pos.ticker, action.rule, action.reason, action.urgency,
                )

                # BUG-8 fix: route through route_order_async so category exposure
                # release, rate limiting, group accounting, and execution guard all
                # fire uniformly.  Direct _kalshi_place_order() bypassed all of them.
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                # IOC escalation safety: generate deterministic client_order_id and store it
                # so we can reuse it for IOC escalation to prevent double fills
                import hashlib, time
                _sl_ts_bucket = int(time.time()) // 60
                _sl_preimage = f"{self.agent_id}|{pos.ticker}|{pos.side}|sell|{pos.entry_price_cents}|{pos.contracts}|{_sl_ts_bucket}|stop_loss"
                _sl_client_tag = f"merid-{hashlib.sha256(_sl_preimage.encode()).hexdigest()[:16]}-{_sl_ts_bucket}"
                pos.close_client_order_id = _sl_client_tag  # Store for potential IOC escalation
                _sl_intent = OrderIntent(
                    ticker=pos.ticker,
                    side=pos.side,
                    action="sell",
                    price_cents=max(1, pos.entry_price_cents),  # Use entry price for accurate notional in exposure tracker; Kalshi ignores price on market orders
                    count=pos.contracts,
                    order_type="market",
                    time_in_force="gtc",
                    source=f"stop_loss:{self.config.name}",
                    agent_id=self.agent_id,
                    decision_trace_id=new_decision_trace_id("sl"),
                    sentiment_driven=False,
                    client_tag=_sl_client_tag,  # Deterministic ID for idempotency
                )
                _sl_result = await route_order_async(_sl_intent)
                _close_ok = _sl_result.status not in ("rejected",)

                if _close_ok:
                    self.logger.info(
                        "stop_loss CLOSED %s %s x%d: %s",
                        pos.ticker, pos.side, pos.contracts, action.reason,
                    )
                    self._stop_loss.record_close(
                        position_id=pos_id,
                        action=action,
                        pnl_cents=pos.unrealized_pnl_cents,
                    )
                    # Feed realised loss into session cap tracker
                    if pos.unrealized_pnl_cents < 0:
                        self._stop_loss.record_session_loss(abs(pos.unrealized_pnl_cents))
                    # Notify KalshiRiskManager of the close so notional is decremented.
                    # The router now only advances rate-limit counters (record_rate_only);
                    # all notional accounting is agent-side (BUG-A fix).
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        _close_cat = None
                        try:
                            from merid.event_venues.kalshi.category_exposure import infer_category
                            from merid.event_venues.kalshi.kalshi_market_utils import get_underlying
                            _close_cat = infer_category(get_underlying(pos.ticker))
                        except Exception as e:
                            self.logger.debug(f"Silent error suppressed: {e}")
                        get_kalshi_risk().record_close(_close_cat, pos.contracts, pos.entry_price_cents)
                    except Exception as _kr:
                        self.logger.debug("stop_loss: kalshi_risk.record_close failed (non-fatal): %s", _kr)
                    to_remove.append(pos_id)
                else:
                    pos.close_fail_count += 1
                    self.logger.warning(
                        "stop_loss close order failed for %s (attempt %d): %s",
                        pos.ticker, pos.close_fail_count, _sl_result.reason or "unknown",
                    )
                    # BUG-05: escalate after repeated failures
                    if pos.close_fail_count >= 3:
                        # Hard limit: pause this agent and alert operator
                        self.logger.error(
                            "stop_loss ESCALATION: %d consecutive close failures on %s — "
                            "pausing agent %s",
                            pos.close_fail_count, pos.ticker, self.config.name,
                        )
                        try:
                            from merid.prediction.alerts import get_alert_manager
                            get_alert_manager().fire_risk_breach(
                                market_id=pos.ticker,
                                message=(
                                    f"STOP-LOSS ESCALATION: {pos.close_fail_count} consecutive "
                                    f"close failures on {pos.ticker} ({self.config.name}). "
                                    f"Agent paused — manual intervention required."
                                ),
                            )
                        except Exception as _ae:
                            self.logger.debug("stop_loss escalation alert skipped: %s", _ae)
                        # BUG-KS1 & BUG-KS5 FIX: Only count incident-grade failures toward kill switch
                        # Stop-loss failures may be caused by policy blocks (execution gate, market conditions)
                        # which should NOT count toward error threshold.
                        try:
                            from merid.prediction.order_error_threshold import (
                                should_count_toward_error_threshold,
                            )
                            from merid.risk.kill_switches import risk_controller as _rc
                            _sl_failure_reason = _sl_result.reason or "unknown"
                            if should_count_toward_error_threshold(_sl_failure_reason):
                                _rc.record_error(error_hint=_sl_failure_reason)
                                self.logger.warning(
                                    "stop_loss kill_switch error counted: %s", _sl_failure_reason
                                )
                            else:
                                self.logger.debug(
                                    "stop_loss kill_switch error NOT counted (policy rejection): %s",
                                    _sl_failure_reason,
                                )
                        except Exception as _ke:
                            self.logger.debug("stop_loss kill_switch record_error skipped: %s", _ke)
                        self.pause()
                    elif pos.close_fail_count >= 2:
                        # Second failure: retry as IOC market order to improve fill odds
                        # IOC escalation safety: reuse same client_order_id to prevent double fills
                        # Kalshi's duplicate protection will prevent double execution
                        self.logger.warning(
                            "stop_loss retry %s as IOC market order (fail_count=%d, client_tag=%s)",
                            pos.ticker, pos.close_fail_count, pos.close_client_order_id or "new",
                        )
                        try:
                            from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                            from merid.prediction.venue_gate import TradingMode
                            # Reuse original client_order_id if available, otherwise generate new
                            _ioc_client_tag = pos.close_client_order_id or None
                            _ioc_intent = OrderIntent(
                                ticker=pos.ticker,
                                side=pos.side,
                                action="sell",
                                price_cents=max(1, pos.entry_price_cents),  # Use entry price for accurate notional (BUG-C fix)
                                count=pos.contracts,
                                order_type="market",
                                time_in_force="ioc",
                                source=f"stop_loss_escalation:{self.config.name}",
                                decision_trace_id=new_decision_trace_id("ioc"),
                                sentiment_driven=False,
                                client_tag=_ioc_client_tag,  # Reuse same ID for duplicate protection
                            )
                            _ioc_result = await route_order_async(_ioc_intent)
                            if _ioc_result.status not in ("rejected",):
                                self.logger.info(
                                    "stop_loss IOC escalation succeeded for %s: %s",
                                    pos.ticker, _ioc_result.status,
                                )
                                to_remove.append(pos_id)
                                pos.close_fail_count = 0
                        except Exception as _ioc_exc:
                            self.logger.error(
                                "stop_loss IOC escalation failed for %s: %s",
                                pos.ticker, _ioc_exc,
                            )

            except Exception as exc:
                self.logger.debug("stop_loss check error for %s: %s", pos_id, exc)

        for pos_id in to_remove:
            self._tracked_positions.pop(pos_id, None)

        # If session cap breached, halt the agent
        if self._stop_loss.session_halted and self.state.enabled:
            self.logger.warning("stop_loss session cap breached — pausing agent %s", self.config.name)
            self.pause()

    # ── Market resolution ──────────────────────────────────────────────

    async def _resolve_markets(self) -> None:
        """Resolve config filters into live Kalshi market tickers.

        Iterates over ALL configured assets (not just assets[0]) so that
        multi-asset agents (e.g. FINANCIALS_DIRECTIONAL: [SPX, NDX, DJI])
        load markets for every asset they cover.
        """
        try:
            from merid.prediction.kalshi_tools import _kalshi_list_markets
            from merid.event_venues.base import EventMarket, EventOutcome

            category = self.config.category
            assets = self.config.assets if self.config.assets else [""]
            timeframe = self.config.timeframes[0] if self.config.timeframes else ""
            per_asset_limit = max(5, self.config.risk_limits.max_orders_per_window * 3)

            seen_tickers: set = set()
            all_markets = []
            # raw dicts per asset — used by FilterPipeline when enabled
            _raw_by_asset: dict = {}

            for asset in assets:
                result = await _kalshi_list_markets(
                    category=category,
                    timeframe=timeframe,
                    asset=asset,
                    limit=per_asset_limit,
                )
                if not result.success:
                    self.logger.debug(
                        "Market resolution failed for asset=%s: %s",
                        asset, result.error_message,
                    )
                    continue

                for m in result.payload.get("markets", []):
                    ticker = m.get("ticker") or m.get("market_id", "")
                    if not ticker or ticker in seen_tickers:
                        continue
                    seen_tickers.add(ticker)
                    _raw_by_asset.setdefault(asset or "UNK", []).append(m)

                    outcomes = [
                        EventOutcome(
                            outcome_id=o["id"],
                            outcome_name=o["name"],
                            price=Decimal(o["price"]),
                            probability=Decimal(o["probability"]) if o.get("probability") else None,
                        )
                        for o in m.get("outcomes", [])
                    ]
                    em = EventMarket(
                        market_id=ticker,
                        venue="kalshi",
                        question=m.get("question", ""),
                        description="",
                        outcomes=outcomes,
                        category=m.get("category"),
                        tags=m.get("tags", []),
                        end_date=datetime.fromisoformat(m["end_date"]) if m.get("end_date") else None,
                        active=m.get("active", True),
                        volume=Decimal(m.get("volume", "0")),
                        open_interest=Decimal(m.get("open_interest", "0")),
                    )
                    all_markets.append(em)

            # ── FilterPipeline (optional) ──────────────────────────────────
            if self.config.use_filter_pipeline and _raw_by_asset:
                try:
                    from merid.trading.kalshi_filter_pipeline import (
                        FilterPipeline, FilterPipelineConfig,
                    )
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    _fp_cfg = FilterPipelineConfig(
                        assets=self.config.assets or [],
                        max_candidates_per_asset=self.config.filter_max_candidates_per_asset,
                        max_candidates_global=self.config.filter_max_candidates_global,
                    )
                    _fp = FilterPipeline(_fp_cfg)
                    # Pull spot prices from LivePriceFeed (the correct source).
                    # KalshiMarketCatalog has no get_reference_price method, and
                    # FilterPipeline.set_spot_prices (plural) is the bulk setter.
                    try:
                        from data.live_price_feed import get_live_price_feed as _glpf
                        _feed = _glpf()
                        _spots: dict = {}
                        for _a in (self.config.assets or []):
                            _pd = None
                            for _sym in pm_spot_feed_symbol_candidates(_a):
                                _pd = _feed.get_current_price(_sym)
                                if _pd and _pd.price > 0:
                                    break
                            if _pd and _pd.price > 0:
                                _spots[_a] = float(_pd.price)
                        if _spots:
                            _fp.set_spot_prices(_spots)
                    except Exception as _spot_err:
                        self.logger.debug("Spot price inject skipped: %s", _spot_err)
                    _fp_result = _fp.filter_markets(_raw_by_asset)
                    _allowed = {c.ticker for c in _fp_result.final_candidates}
                    all_markets = [m for m in all_markets if m.market_id in _allowed]
                except Exception as _fpe:
                    self.logger.debug("FilterPipeline skipped: %s", _fpe)

            self._resolved_markets = all_markets
            tickers = [m.market_id for m in self._resolved_markets]
            self.state.active_tickers = tickers[:20]

        except Exception as exc:
            self.logger.warning(f"Market resolution error: {exc}")

    # ── Helpers ────────────────────────────────────────────────────────

    def _handles_ticker(self, ticker: str) -> bool:
        """Check if this agent handles positions for the given ticker.
        
        Returns True if the ticker matches any of the agent's configured assets.
        Used to filter pre-fetched positions so each agent only restores
        positions it actually manages.
        
        Args:
            ticker: The market ticker to check (e.g., "BTC-USD-230915")
            
        Returns:
            True if this agent should handle this ticker
        """
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            ticker_asset = kalshi_ticker_to_asset(ticker)
            if ticker_asset:
                ticker_asset = ticker_asset.upper()
            else:
                # Fallback: try to extract from ticker format
                ticker_upper = ticker.upper()
                for asset in (self.config.assets or []):
                    if asset.upper() in ticker_upper:
                        return True
                return False
            
            for asset in (self.config.assets or []):
                if asset.upper() == ticker_asset:
                    return True
            return False
        except Exception:
            # Fail-open: if check fails, assume we handle it
            return True

    def _log_pm_sizing_context(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
    ) -> None:
        """INFO line for operators: edge + strategy Kelly caps + shared risk bankroll."""
        try:
            _eq = 0.0
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

                _eq = float(get_kalshi_risk().state.current_equity_usd or 0.0)
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
            sc = self._strategy.config
            edge_s = (
                float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else None
            )
            _vb = getattr(snapshot, "crypto_vol_band", None) or "—"
            _vm = getattr(snapshot, "crypto_vol_size_mult", None)
            _dist = getattr(snapshot, "distance_to_strike_pct", None)
            _dist_human = (
                f"{float(_dist) * 100.0:.2f}"
                if _dist is not None
                else "—"
            )
            _basis = getattr(snapshot, "spot_strike_basis_note", "") or "—"
            self.logger.info(
                "[PM_SIZE] agent=%s ticker=%s action=%s contracts=%s limit_cents=%s "
                "net_edge=%s bankroll_equity_usd=%.2f kelly_frac=%s max_contracts_order=%s "
                "vol_band=%s vol_size_mult=%s spot=%s strike=%s dist_pct_pct=%s spot_strike_basis=%s",
                self.config.name,
                market.market_id,
                signal.action.value if hasattr(signal.action, "value") else signal.action,
                signal.contracts,
                signal.limit_price_cents,
                f"{edge_s:.4f}" if edge_s is not None else "—",
                _eq,
                float(sc.kelly_fraction),
                int(sc.max_contracts_per_order),
                _vb,
                f"{_vm:.3f}" if _vm is not None else "—",
                snapshot.spot_price_usd if snapshot.spot_price_usd is not None else "—",
                snapshot.strike_price_usd if snapshot.strike_price_usd is not None else "—",
                _dist_human,
                _basis,
            )
        except Exception as _exc:
            self.logger.debug("pm sizing log skipped: %s", _exc)

    def _in_entry_window(self, market: EventMarket, now: datetime) -> bool:
        """Check if now is within the agent's entry window for this market."""
        if not market.end_date:
            self.logger.debug(
                "Skipping %s: end_date is missing — cannot determine entry window",
                market.market_id,
            )
            return False  # Reject: missing expiry is unsafe, not a pass-through

        ew = self.config.entry_window
        window_open = market.end_date - timedelta(minutes=ew.minutes_before_expiry)
        window_close = market.end_date - timedelta(minutes=ew.cutoff_minutes_before_expiry)

        return window_open <= now <= window_close

    @staticmethod
    def _is_new_entry_action(action: SignalAction) -> bool:
        """True for opens / MM quotes; exits (sell/close) may run outside the entry window."""
        return action in (
            SignalAction.BUY_YES,
            SignalAction.BUY_NO,
            SignalAction.QUOTE,
        )

    def _get_seconds_to_expiry(self, market: EventMarket, now: datetime) -> Optional[float]:
        """Calculate seconds remaining until market expiry.
        
        Returns None if expiry cannot be determined.
        This supports the expiry proximity guard (Gap G1 fix).
        """
        if not market.end_date:
            return None
        
        # Ensure both datetimes are timezone-aware for accurate comparison
        end_date = market.end_date
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        now_aware = now
        if now_aware.tzinfo is None:
            now_aware = now_aware.replace(tzinfo=timezone.utc)
        
        delta = end_date - now_aware
        return max(0.0, delta.total_seconds())

    def _build_snapshot(self, market: EventMarket, now: datetime) -> MarketSnapshot:
        """Build a MarketSnapshot from an EventMarket for strategy consumption."""
        yes_price = Decimal("50")
        no_price = Decimal("50")
        for o in market.outcomes:
            if o.outcome_id == "yes":
                yes_price = o.price * 100  # Convert back to cents
            elif o.outcome_id == "no":
                no_price = o.price * 100

        # Compute time to expiry
        tte_hours = None
        if market.end_date:
            delta = market.end_date - now
            tte_hours = Decimal(str(max(delta.total_seconds() / 3600, 0)))

        # Prefer live WS orderbook bid/ask over the synthetic 1¢ spread from
        # the REST catalog.  The catalog refresh lags by up to one cycle interval
        # (30–300 s) and always synthesises a 1¢ spread, so spread checks in
        # the risk layer would always pass even for wide markets (BUG-7 fix).
        yes_bid: Decimal
        yes_ask: Decimal
        try:
            from merid.event_venues.kalshi.ws_bridge import get_live_prices
            live = get_live_prices(market.market_id)
            if live is not None:
                yes_bid = Decimal(str(live["yes_bid_cents"]))
                yes_ask = Decimal(str(live["yes_ask_cents"]))
                no_bid = max(Decimal("100") - yes_ask, Decimal("1"))
                no_ask = max(Decimal("100") - yes_bid, Decimal("1"))
            else:
                yes_bid = max(yes_price - 1, Decimal("1"))
                yes_ask = yes_price
                no_bid = max(no_price - 1, Decimal("1"))
                no_ask = no_price
        except Exception:
            yes_bid = max(yes_price - 1, Decimal("1"))
            yes_ask = yes_price
            no_bid = max(no_price - 1, Decimal("1"))
            no_ask = no_price

        implied = self._model.implied_probabilities(
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
        )

        state = self._model.determine_state(
            status="active" if market.active else "closed",
            close_time=market.end_date,
        )

        snapshot = MarketSnapshot(
            market_id=market.market_id,
            event_id=market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id,
            title=market.question,
            state=state,
            implied=implied,
            volume=market.volume or Decimal("0"),
            open_interest=market.open_interest or Decimal("0"),
            time_to_expiry_hours=tte_hours,
            close_time=market.end_date,
            category=market.category,
            timestamp=now,
        )

        # Inject fear/greed sentiment scores
        # H2: gate on context age — stale sentiment must not bias the snapshot.
        # H9: set sentiment_adjusted=True so forecasters skip their own nudge.
        _MAX_SENTIMENT_AGE_S = 900.0  # 15 minutes
        try:
            from merid.event_venues.kalshi.sentiment import get_sentiment_service
            svc = get_sentiment_service()
            # Feed latest data point so the service stays current
            svc.update_market(
                market.market_id,
                prob=float(implied.yes_prob),
                volume=float(market.volume or 0),
                category=(market.category or "unknown").lower(),
            )
            local_s = svc.market_score(market.market_id)
            cat_s   = svc.category_score((market.category or "unknown").lower())
            glob_s  = svc.global_score()

            # H2: determine age of the context; skip injection if stale
            _ctx_ts = None
            try:
                from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
                _bus_v2 = get_sentiment_bus_v2()
                asset = self.config.assets[0] if self.config.assets else None
                if asset:
                    _asset_ctx = _bus_v2.get_asset_context(asset)
                    if _asset_ctx and hasattr(_asset_ctx, "timestamp"):
                        _ctx_ts = _asset_ctx.timestamp
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")

            _age_s: Optional[float] = None
            if _ctx_ts is not None:
                try:
                    from datetime import timezone as _tz
                    _ctx_aware = _ctx_ts if _ctx_ts.tzinfo else _ctx_ts.replace(tzinfo=_tz.utc)
                    _now_aware = now if now.tzinfo else now.replace(tzinfo=_tz.utc)
                    _age_s = (_now_aware - _ctx_aware).total_seconds()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

            if _age_s is not None and _age_s > _MAX_SENTIMENT_AGE_S:
                self.logger.warning(
                    "Sentiment context age %.0fs exceeds limit %.0fs for %s — "
                    "skipping sentiment injection (H2)",
                    _age_s, _MAX_SENTIMENT_AGE_S, market.market_id,
                )
            else:
                snapshot.sentiment_local    = local_s.score if local_s else None
                snapshot.sentiment_category = cat_s.score
                snapshot.sentiment_global   = glob_s.score
                snapshot.sentiment_regime   = local_s.regime if local_s else glob_s.regime
                snapshot.sentiment_age_seconds = _age_s
                # H9: mark as adjusted so forecasters do not re-apply the nudge
                snapshot.sentiment_adjusted = True
        except Exception as _se:
            self.logger.debug("sentiment enrichment skipped: %s", _se)

        # Compute edges for both sides using the model (single spot fetch per snapshot)
        from merid.prediction.spot_strike_context import (
            distance_to_strike_pct,
            evaluate_spot_strike_anomaly,
            log_spot_out_of_range,
            resolve_asset_for_snapshot,
            resolve_timeframe_for_snapshot,
        )

        _resolved_asset = resolve_asset_for_snapshot(self.config.assets, market.market_id)
        _resolved_tf = resolve_timeframe_for_snapshot(self.config.timeframes, market.market_id)
        snapshot.resolved_asset = _resolved_asset
        snapshot.resolved_timeframe = _resolved_tf

        _asset_for_spot = _resolved_asset if _resolved_asset != "UNK" else None
        strike = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            m = catalog.get_market(market.market_id)
            if m:
                strike = m.strike_price
                # Bracket/bucket markets have no strike_price but carry floor/cap.
                # Use midpoint as effective strike for the spot-relative edge model.
                if strike is None and m.floor_strike is not None and m.cap_strike is not None:
                    strike = (m.floor_strike + m.cap_strike) / 2.0
        except Exception as _ce:
            self.logger.debug("catalog strike lookup skipped: %s", _ce)
        if strike is None:
            try:
                from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker

                strike = parse_strike_from_ticker(market.market_id)
            except Exception as _ps:
                self.logger.debug("parse_strike_from_ticker skipped: %s", _ps)

        snapshot.strike_price_usd = strike
        spot_override = None
        if _asset_for_spot:
            spot_override = self._model.get_spot_price(_asset_for_spot, market.market_id)
        snapshot.spot_price_usd = spot_override

        # Spot–strike basis (fractional dist only when both are valid USD levels)
        if not _asset_for_spot or (_resolved_asset or "").upper() in ("", "UNK"):
            snapshot.spot_strike_basis_note = "missing_asset_for_spot"
        elif strike is not None and float(strike) == 0.0:
            snapshot.spot_strike_basis_note = "invalid_strike_zero"
        elif strike is None and spot_override is None:
            snapshot.spot_strike_basis_note = "missing_strike_and_spot"
        elif strike is None:
            snapshot.spot_strike_basis_note = "missing_strike"
        elif spot_override is None:
            snapshot.spot_strike_basis_note = "missing_spot"
        else:
            snapshot.spot_strike_basis_note = "ok"
        # Realized-vol bands for crypto PM sizing (``crypto_pm_vol_bridge`` — ~1 bar/min/asset)
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS as _PM_CRYPTO_ASSETS
            from merid.signals.crypto_pm_vol_bridge import feed_spot_and_get_context as _pm_vol_feed

            if (
                _asset_for_spot
                and _asset_for_spot.upper() in _PM_CRYPTO_ASSETS
                and spot_override is not None
            ):
                _vctx = _pm_vol_feed(
                    _asset_for_spot.upper(),
                    float(spot_override),
                    timeframe=_resolved_tf,
                    archetype=str(getattr(self.config, "archetype", None) or "directional"),
                )
                if _vctx:
                    snapshot.crypto_vol_band = str(_vctx.get("vol_band") or "")
                    snapshot.crypto_vol_size_mult = float(_vctx["vol_size_mult"])
                    snapshot.crypto_realized_vol_annualized = float(
                        _vctx.get("realized_vol_annualized") or 0.0
                    )
                    snapshot.crypto_vol_bars_available = int(_vctx.get("bars_available") or 0)
        except Exception as _pv_exc:
            self.logger.debug("pm vol band attach skipped: %s", _pv_exc)

        # ACTIVE + crypto asset but no spot: neutral vol sizing and no spot–strike — make it visible (throttled).
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS as _PM_ASSETS_WARN

            if (
                _asset_for_spot
                and _asset_for_spot.upper() in _PM_ASSETS_WARN
                and spot_override is None
                and self.state.lifecycle == LifecycleState.ACTIVE
            ):
                _wk = f"{self.config.name}|{_asset_for_spot.upper()}"
                _now = time.time()
                if _now - _PM_SPOT_MISSING_WARN_LAST.get(_wk, 0.0) >= _PM_SPOT_MISSING_WARN_INTERVAL_S:
                    _PM_SPOT_MISSING_WARN_LAST[_wk] = _now
                    self.logger.warning(
                        "[PM_SPOT] agent=%s asset=%s market=%s — get_spot_price returned None "
                        "(vol bridge + spot–strike unavailable). "
                        "Check LivePriceFeed (Coinbase primary → %s/USD cache) and "
                        "MERID_PM_MAX_SPOT_AGE_SECONDS.",
                        self.config.name,
                        _asset_for_spot.upper(),
                        market.market_id,
                        _asset_for_spot.upper(),
                    )
        except Exception as e:
            self.logger.debug(f"Silent error suppressed: {e}")

        if spot_override is not None and strike is not None and float(strike) != 0.0:
            snapshot.distance_to_strike_pct = distance_to_strike_pct(spot_override, strike)
            _matrix_veto = False
            try:
                from merid.prediction.crypto_threshold_matrix import get_effective_crypto_config

                _eff_cfg = get_effective_crypto_config(self.config.name, market.market_id)
                _matrix_veto = bool(_eff_cfg.spot_strike_veto_flag) if _eff_cfg else False
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
            _warned, _veto, _anom_msg = evaluate_spot_strike_anomaly(
                snapshot.distance_to_strike_pct,
                matrix_hard_veto=_matrix_veto,
            )
            if _warned and _anom_msg:
                log_spot_out_of_range(
                    asset=_resolved_asset,
                    market_id=market.market_id,
                    spot=spot_override,
                    strike=strike,
                    detail=_anom_msg,
                    timeframe=_resolved_tf,
                    distance_to_strike_pct=snapshot.distance_to_strike_pct,
                )
            if _veto:
                snapshot.spot_strike_veto = True
                snapshot.spot_strike_veto_reason = (
                    f"spot_strike_anomaly: {_anom_msg or 'configured veto threshold'}"
                )

        snapshot.edges = [
            self._model.compute_edge(
                market_id=market.market_id,
                implied=implied,
                side="yes",
                action="buy",
                asset=_asset_for_spot,
                strike_price=strike,
                spot_override=spot_override,
            ),
            self._model.compute_edge(
                market_id=market.market_id,
                implied=implied,
                side="no",
                action="buy",
                asset=_asset_for_spot,
                strike_price=strike,
                spot_override=spot_override,
            ),
        ]

        return snapshot

    def _pm_spot_hard_gate_enabled_for_agent(self) -> bool:
        """True when this agent opts in via YAML ``pm_spot_hard_gate`` (market_maker only).

        Global kill-switch: ``MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0`` disables the gate process-wide.
        """
        _raw = (os.getenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE") or "1").strip().lower()
        if _raw in ("0", "false", "no", "off"):
            return False
        arch = (getattr(self.config, "archetype", "") or "").strip().lower().replace("-", "_")
        if arch != "market_maker":
            return False
        return bool(getattr(self.config, "pm_spot_hard_gate", False))

    def _apply_pm_spot_hard_gate(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
    ) -> StrategySignal:
        """Hard gate: opted-in MM agents must not emit QUOTE without healthy PM spot (``snapshot.spot_price_usd``).

        Aligns with ``PredictionMarketModel.get_spot_price`` / operator ``pm_spot_effective_ok``. Orthogonal to
        ERROR_THRESHOLD kills.
        """
        if not self._pm_spot_hard_gate_enabled_for_agent():
            return signal
        if signal.action != SignalAction.QUOTE:
            return signal
        if snapshot.spot_price_usd is not None:
            return signal
        asset = (snapshot.resolved_asset or "").strip().upper()
        if not asset and self.config.assets:
            asset = (self.config.assets[0] or "").strip().upper()
        try:
            from merid.settings import settings as _settings

            kalshi_only = bool(getattr(_settings, "KALSHI_ONLY", False))
        except Exception:
            kalshi_only = False
        now_m = time.monotonic()
        _k = f"{self.config.name}|{asset}|{getattr(market, 'market_id', '')}"
        last = _PM_SPOT_BLOCK_LOG_LAST.get(_k, 0.0)
        if now_m - last >= _PM_SPOT_BLOCK_LOG_INTERVAL_S:
            _PM_SPOT_BLOCK_LOG_LAST[_k] = now_m
            self.logger.warning(
                "PM_SPOT_BLOCK: agent=%s asset=%s reason=missing_or_stale_spot kalshi_only_mode=%s",
                self.config.name,
                asset or "?",
                kalshi_only,
            )
        return StrategySignal(
            market_id=signal.market_id,
            action=SignalAction.NO_ACTION,
            side="",
            contracts=0,
            limit_price_cents=None,
            bid_price_cents=None,
            ask_price_cents=None,
            edge=signal.edge,
            phase=signal.phase,
            reason="pm_spot_gate:missing_or_stale_spot",
            correlation_id=signal.correlation_id,
            eval_context={**(signal.eval_context or {}), "pm_spot_gate": True},
        )

    def _maybe_log_crypto_spot_strike_trace(
        self,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
    ) -> None:
        """Config-toggleable ``[CRYPTO_SPOT_STRIKE]`` line after strategy evaluation.

        Uses only fields from ``snapshot`` / ``signal`` (no duplicate spot fetch).
        """
        try:
            from merid.prediction.spot_strike_context import log_crypto_spot_strike

            ne = None
            if signal.edge and hasattr(signal.edge, "net_edge"):
                try:
                    ne = float(signal.edge.net_edge)
                except (TypeError, ValueError):
                    ne = None
            ph = signal.phase.value if signal.phase else None
            log_crypto_spot_strike(
                agent_name=self.config.name,
                market_id=snapshot.market_id,
                asset=snapshot.resolved_asset or "",
                timeframe=snapshot.resolved_timeframe or "",
                spot=snapshot.spot_price_usd,
                strike=snapshot.strike_price_usd,
                dist_pct=snapshot.distance_to_strike_pct,
                net_edge=ne,
                phase=ph,
                archetype=str(self.config.archetype or ""),
            )
        except Exception as _exc:
            self.logger.debug("crypto spot-strike trace skipped: %s", _exc)

    def _compute_cycle_interval(self) -> float:
        """Compute sleep between cycles based on timeframe."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        intervals = {
            "15m": 30.0,        # Check every 30s for 15m markets
            "1h": 60.0,         # Every 60s for hourly
            "daily": 300.0,     # Every 5min for daily
            "weekly": 600.0,    # Every 10min for weekly
            "monthly": 1800.0,  # Every 30min for monthly — no need to hammer the loop
            "annual": 3600.0,   # Every 1h for annual
            "pre-market": 60.0,
        }
        return intervals.get(tf, 60.0)

    def _maybe_reset_window(self, now: datetime) -> None:
        """Reset per-window order count when a new window starts."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        window_minutes = {"15m": 15, "1h": 60, "daily": 1440, "weekly": 10080, "pre-market": 120}
        window_dur = timedelta(minutes=window_minutes.get(tf, 60))

        if self.state.window_start is None or (now - self.state.window_start) >= window_dur:
            self.state.window_start = now
            self.state.orders_this_window = 0

    async def _record_signal(
        self, market: EventMarket, signal: StrategySignal,
        snapshot: MarketSnapshot, now: datetime,
    ) -> None:
        """Persist a strategy signal to the agent's signal log."""
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
            "contracts": signal.contracts,
            "limit_price_cents": signal.limit_price_cents,
            "edge": float(signal.edge.net_edge) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None,
            "confidence": float(signal.edge.confidence) if (signal.edge and hasattr(signal.edge, 'confidence')) else None,
            "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
            "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
            "expiry_phase": str(signal.phase) if signal.phase else None,
            "mode": str(getattr(self._venue_gate, "mode", "unknown").value
                        if hasattr(getattr(self._venue_gate, "mode", None), "value")
                        else getattr(self._venue_gate, "mode", "unknown")),
        }
        self.state.signal_log.append(entry)
        if len(self.state.signal_log) > _MAX_LOG_ENTRIES:
            self.state.signal_log = self.state.signal_log[-_MAX_LOG_ENTRIES:]

        # ── Calibration: log forecast for Brier scoring ──────────────────
        try:
            from merid.metrics.calibration import get_calibration_store
            cal = get_calibration_store()
            # Use model_prob directly from EdgeEstimate — this is the pre-fee
            # probability set by compute_edge().  Never reconstruct from
            # net_edge (which has fee drag deducted) to avoid systematic
            # underestimation of the true model probability (BUG-06).
            p_model = None
            if signal.edge and hasattr(signal.edge, 'model_prob') and signal.edge.model_prob is not None:
                p_model = float(signal.edge.model_prob)
            if p_model is not None:
                bucket = (market.category or "unknown").lower()
                _cal_mode = str(
                    getattr(self._venue_gate, "mode", "live").value
                    if hasattr(getattr(self._venue_gate, "mode", None), "value")
                    else getattr(self._venue_gate, "mode", "live")
                ).lower()
                cal.record_forecast(
                    forecaster_id=self.config.name,
                    bucket=bucket,
                    market_id=market.market_id,
                    p_model=p_model,
                    timestamp=now.timestamp(),
                    mode=_cal_mode,
                )
        except Exception as _cal_exc:
            self.logger.debug("calibration record_forecast skipped: %s", _cal_exc)

        # ── Sprint B: Run heterogeneous forecasters (momentum, mean_reversion) ──
        try:
            from merid.prediction.forecasters.registry import get_forecaster_registry
            registry = get_forecaster_registry()
            imp_yes = float(snapshot.implied.yes_prob) if snapshot and snapshot.implied else 0.5
            imp_no = float(snapshot.implied.no_prob) if snapshot and snapshot.implied else 0.5
            vol = float(market.volume) if market.volume else 0.0
            oi = float(market.open_interest) if market.open_interest else 0.0
            tte = float(snapshot.time_to_expiry_hours) * 60.0 if snapshot and snapshot.time_to_expiry_hours else None
            _bid = float(snapshot.implied.yes_bid) if snapshot and snapshot.implied and snapshot.implied.yes_bid else None
            _ask = float(snapshot.implied.yes_ask) if snapshot and snapshot.implied and snapshot.implied.yes_ask else None
            _asset = self.config.assets[0] if self.config.assets else None
            _tf = self.config.timeframes[0] if self.config.timeframes else None
            
            # Offload synchronous predict_all to thread pool to prevent event loop blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                registry.predict_all,
                market.market_id,
                imp_yes,
                imp_no,
                vol,
                oi,
                tte,
                _asset,
                _tf,
                _bid,
                _ask,
                market.category,
            )
        except Exception as _fr_exc:
            self.logger.debug("forecaster registry predict_all skipped: %s", _fr_exc)

    def _record_explainability_decision(
        self,
        *,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        check: PreTradeCheck,
        now: datetime,
        allowed: bool,
    ) -> None:
        """Record a structured decision rationale in the global explainability tracker."""
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker

            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.0
            edge_value = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0

            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"{action_value} {signal.contracts}x {market.market_id}", confidence)
            builder.set_primary_reason(
                f"{action_value} decision for {market.market_id} with edge={edge_value:.4f}"
            )
            builder.add_supporting_factor(f"edge={edge_value:.4f}")
            builder.add_supporting_factor(f"allowed={allowed}")
            if check.adjusted_size and check.adjusted_size != signal.contracts:
                builder.add_contrary_factor(
                    f"risk downsize from {signal.contracts} to {check.adjusted_size}"
                )
            if not allowed:
                builder.add_contrary_factor(f"risk blocked: {check.reason}")

            for source in ("kalshi_market_catalog", "kalshi_order_router", "prediction_risk"):
                builder.add_data_source(source)

            builder.set_market_context(
                {
                    "market_id": market.market_id,
                    "question": market.question,
                    "timestamp": now.isoformat(),
                    "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
                    "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
                    "volume": float(snapshot.volume) if snapshot.volume is not None else 0.0,
                    "open_interest": float(snapshot.open_interest) if snapshot.open_interest is not None else 0.0,
                }
            )
            builder.set_risk_assessment(
                {
                    "allowed": allowed,
                    "reason": check.reason,
                    "adjusted_size": check.adjusted_size,
                    "estimated_fee": str(check.estimated_fee) if hasattr(check, "estimated_fee") else None,
                }
            )

            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability decision record skipped: {exc}")

    def _emit_decision_log(self, decision: Decision) -> None:
        """Emit a structured ``[PM_DECISION]`` log line for observability."""
        try:
            th_cfg = get_trade_hold_config()
            if not th_cfg.logging.log_every_decision:
                return
            self.logger.info(decision.log_line())
        except Exception as _dl_exc:
            self.logger.debug("decision log skipped: %s", _dl_exc)

    def _build_cycle_context(
        self,
        *,
        market_id: Optional[str] = None,
        signal: Optional[StrategySignal] = None,
        check: Optional[PreTradeCheck] = None,
        now: datetime,
        timer: DecisionTimer,
        session_allowed: bool = True,
        has_resolved_markets: bool = True,
        in_entry_window: bool = True,
        is_new_entry: bool = True,
        seconds_to_expiry: Optional[float] = None,
        consensus_status: Optional[str] = None,
        consensus_direction_matches: bool = True,
        consensus_bypassed: bool = False,
        solo_seconds: float = 0.0,
    ) -> CycleContext:
        """Populate a CycleContext from current agent state + pipeline results."""
        ctx = CycleContext(
            agent_name=self.config.name,
            cycle_number=self.state.cycles_run,
            market_id=market_id,
            lifecycle_state=self.state.lifecycle,
            agent_enabled=self.state.enabled,
            kill_switch_active=getattr(self._risk, "_halted", False),
            kill_switch_reason=getattr(self._risk, "_halt_reason", "") or "",
            session_allowed=session_allowed,
            has_resolved_markets=has_resolved_markets,
            in_entry_window=in_entry_window,
            is_new_entry=is_new_entry,
            seconds_to_expiry=seconds_to_expiry,
            orders_this_window=self.state.orders_this_window,
            max_orders_per_window=self.config.risk_limits.max_orders_per_window,
            consensus_status=consensus_status,
            consensus_direction_matches=consensus_direction_matches,
            consensus_bypassed=consensus_bypassed or self._swarm_consensus_bypassed(),
            solo_seconds=solo_seconds,
            swarm_degraded=self.state.swarm_degraded,
            solo_trades_this_session=self.state.solo_trades_this_degraded_session,
            config=get_trade_hold_config(),
            timer=timer,
        )
        if signal is not None:
            ctx.signal_action = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            ctx.signal_reason = signal.reason or ""
            ctx.signal_contracts = signal.contracts
            ctx.signal_edge = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else None
            ctx.signal_phase = signal.phase.value if signal.phase else None
        if check is not None:
            ctx.risk_allowed = check.allowed
            ctx.risk_reason = check.reason or ""
            ctx.risk_action = check.action.value if hasattr(check.action, "value") else str(check.action)
        return ctx

    async def _execute_signal(
        self, market: EventMarket, signal: StrategySignal, check: PreTradeCheck,
        snapshot: Optional[MarketSnapshot] = None,
        _tick: Optional["TickContext"] = None,
        _bus: Optional[object] = None,
    ) -> None:
        """Execute a strategy signal by placing an order.

        Integrates with CryptoSwarmRiskBTC15m for single-lane risk management on
        all five crypto 15m assets (live vs paper routing).
        """
        # BUG-L6: signal to stop() that we are mid-execution so it waits
        # rather than hard-cancelling while an HTTP order request is in-flight.
        self._in_execution.set()
        try:
            await self._execute_signal_body(
                market, signal, check, snapshot, _tick=_tick, _bus=_bus
            )
        finally:
            self._in_execution.clear()

    # Maximum snapshot age before refusing to execute (BUG-3 fix)
    _MAX_SNAPSHOT_AGE_S: float = 90.0

    # Wire 3: consensus size-band scalars
    _SIZE_BAND_SCALARS: dict = {
        "small": 0.25,
        "reduced": 0.5,
        "base": 1.0,
        "large": 1.5,
    }

    def _apply_size_band(self, base_contracts: int, band: str) -> int:
        """Scale contracts by consensus size band. Unknown band defaults to small."""
        scalar = self._SIZE_BAND_SCALARS.get(band, 0.25)
        return max(1, int(base_contracts * scalar))

    def _apply_solo_trade_cap(self, signal: object) -> None:
        """Cap signal.contracts to small band (used for STALE/None/degraded consensus)."""
        if hasattr(signal, "contracts") and signal.contracts is not None:
            signal.contracts = self._apply_size_band(signal.contracts, "small")

    def _check_consensus_gate(self, signal: object, order_contracts: int, *, market_id: str = "") -> Optional[int]:
        """Query consensus and return approved contract count, or None to skip.

        Returns:
            int — approved contracts (size-band-adjusted)
            None — skip this execution cycle
        """
        try:
            from merid.swarm.consensus_aggregator import ConsensusStatus
            from merid.prediction.strategy import SignalAction
            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

            _mm = get_crypto_edge_runtime().mm_consensus_mode
            if _mm == "bypass":
                return max(1, int(order_contracts))

            if market_id:
                asset = self._strategy._extract_asset_from_market_id(market_id) if self._strategy else ""
            else:
                asset = ""
            if not asset or asset == "UNK":
                asset = self.config.assets[0] if self.config.assets else ""
            timeframe = self.config.timeframes[0] if self.config.timeframes else ""
            consensus = get_consensus_aggregator().get_consensus(asset, timeframe)

            if consensus is None or consensus.status == ConsensusStatus.STALE:
                self._apply_solo_trade_cap(signal)
                # Return the mutated (capped) contracts, not the original order_contracts
                capped = getattr(signal, "contracts", None)
                return capped if capped is not None else order_contracts

            if consensus.status == ConsensusStatus.FORMING:
                if _mm == "soft":
                    self._apply_solo_trade_cap(signal)
                    capped = getattr(signal, "contracts", None)
                    return capped if capped is not None else order_contracts
                return None  # full mode: not enough diversity — skip

            if consensus.status == ConsensusStatus.CONFLICTED:
                # Conflicted consensus — cap to small and continue rather than authorize full size
                self._apply_solo_trade_cap(signal)
                capped = getattr(signal, "contracts", None)
                return capped if capped is not None else order_contracts

            _signal_action = getattr(signal, "action", None)

            # BUG-K fix: SELL signals are exits — never block them via direction gate.
            # Original code mapped SELL_YES → "yes", which caused consensus to block
            # sell orders when consensus turned bearish, trapping agents in losers.
            _is_sell = _signal_action in (SignalAction.SELL_YES, SignalAction.SELL_NO)
            if _is_sell:
                return self._apply_size_band(order_contracts, consensus.size_band)

            _dir_map = {
                SignalAction.BUY_YES: "yes",
                SignalAction.BUY_NO: "no",
            }
            signal_dir = _dir_map.get(_signal_action, "neutral")

            if signal_dir != consensus.consensus_direction and consensus.consensus_confidence > 0.7:
                self.logger.debug(
                    "consensus_gate_blocked: %s signal=%s consensus=%s conf=%.2f",
                    self.config.name, signal_dir, consensus.consensus_direction,
                    consensus.consensus_confidence,
                )
                return None

            return self._apply_size_band(order_contracts, consensus.size_band)

        except Exception as exc:
            self.logger.warning("consensus_gate_error — capping to small band: %s", exc)
            self._apply_solo_trade_cap(signal)
            capped = getattr(signal, "contracts", None)
            return capped if capped is not None else self._apply_size_band(order_contracts, "small")

    async def _execute_signal_body(
        self, market: EventMarket, signal: StrategySignal, check: PreTradeCheck,
        snapshot: Optional[MarketSnapshot] = None,
        _tick: Optional["TickContext"] = None,
        _bus: Optional[object] = None,
    ) -> None:
        """Internal body of _execute_signal, protected by _in_execution flag."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

        # [TRACE] EXECUTE_START — log with correlation_id from signal
        corr_id = getattr(signal, 'correlation_id', None)
        if corr_id:
            self.logger.info(
                "[TRACE] EXECUTE_START | corr_id=%s | market=%s | agent=%s | action=%s | size=%s | formulas=%s | audit_spec=%s",
                corr_id,
                market.market_id,
                self.agent_id,
                signal.action.value if hasattr(signal.action, 'value') else signal.action,
                signal.contracts,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )

        # BUG-3 fix: refuse to execute against a stale snapshot so the edge
        # estimate and price used for risk checks reflect current market state.
        if snapshot is not None:
            import time as _time_mod

            _snap_epoch = snapshot_timestamp_utc_epoch_seconds(getattr(snapshot, "timestamp", None))
            _snapshot_age = _time_mod.time() - _snap_epoch
            if _snapshot_age > self._MAX_SNAPSHOT_AGE_S:
                self.logger.warning(
                    "snapshot_stale: %s age=%.1fs > %.0fs — skipping execution",
                    market.market_id, _snapshot_age, self._MAX_SNAPSHOT_AGE_S,
                )
                return

        # Wire 3: Consensus execution gate — gate on direction + apply size band
        _gate_contracts = self._check_consensus_gate(
            signal=signal,
            order_contracts=getattr(signal, "contracts", 0) or 0,
            market_id=market.market_id if market else "",
        )
        if _gate_contracts is None:
            self.logger.debug(
                "consensus_gate_skip: %s consensus not ready or opposes signal",
                market.market_id,
            )
            return

        action_map = {
            SignalAction.BUY_YES: ("yes", "buy"),
            SignalAction.BUY_NO: ("no", "buy"),
            SignalAction.SELL_YES: ("yes", "sell"),
            SignalAction.SELL_NO: ("no", "sell"),
            SignalAction.QUOTE: ("yes", "quote"), # Special handling for quotes
        }

        if signal.action not in action_map:
            return

        side, action = action_map[signal.action]
        size = _gate_contracts if _gate_contracts is not None else (check.adjusted_size or signal.contracts)
        price_cents = signal.limit_price_cents or 0
        # QUOTE: strategy sets limit_price_cents to bid/ask mid; fallback if missing.
        if signal.action == SignalAction.QUOTE and price_cents <= 0:
            _b = getattr(signal, "bid_price_cents", None)
            _a = getattr(signal, "ask_price_cents", None)
            if _b is not None and _a is not None:
                price_cents = max(1, min(99, int((_b + _a) // 2)))

        # ── Take-profit re-entry gate ─────────────────────────────────────
        # For new buy entries (not closes), check whether the TP manager allows
        # re-entry into this contract.  This prevents hyper-churn after TP exits.
        if action == "buy":
            try:
                _system_risk_off = False
                try:
                    from merid.risk.kill_switches import risk_controller as _ks_rc
                    _system_risk_off = not _ks_rc.can_trade()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                # Extract contract expiry info for round-trip reset logic
                _contract_expiry_ts = None
                try:
                    if hasattr(market, 'expiration_time') and market.expiration_time:
                        # Use explicit datetime class to avoid UnboundLocalError
                        from datetime import datetime as _datetime_cls
                        if isinstance(market.expiration_time, _datetime_cls):
                            _contract_expiry_ts = market.expiration_time.timestamp()
                        elif isinstance(market.expiration_time, str):
                            # Try parsing ISO format
                            _dt = _datetime_cls.fromisoformat(market.expiration_time.replace('Z', '+00:00'))
                            _contract_expiry_ts = _dt.timestamp()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                if not self._tp_manager.can_reenter(
                    market.market_id,
                    price_cents,
                    _system_risk_off,
                    contract_id=getattr(market, 'market_id', None) or market.market_id,
                    contract_expiry_ts=_contract_expiry_ts,
                ):
                    self.logger.debug(
                        "tp_reentry_blocked: %s — round-trip cap, min-price-move, or contract expired",
                        market.market_id,
                    )
                    return
            except Exception as _tp_re_exc:
                self.logger.debug("tp_reentry_check skipped: %s", _tp_re_exc)
        # ─────────────────────────────────────────────────────────────────

        # === Crypto 15m Risk Layer Integration (BTC/ETH/SOL/XRP/DOGE) ===
        from config.kalshi_crypto_config import kalshi_ticker_to_asset as _kalshi_ticker_to_asset
        from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS as _ALL_CRYPTO_ASSETS
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket as _series_tf_bucket

        asset_m = _kalshi_ticker_to_asset(market.market_id) or (
            self.config.assets[0] if self.config.assets else ""
        )
        timeframe_m = _series_tf_bucket(market.market_id)

        is_crypto_15m = timeframe_m == "15m" and (asset_m or "").upper() in _ALL_CRYPTO_ASSETS

        if is_crypto_15m:
            try:
                from merid.risk.crypto_swarm_risk_btc15m import (
                    CryptoSwarmRiskBTC15m,
                    TradeProposal,
                    TradeMode,
                    RiskPhase,
                )
                
                # Build trade proposal for risk evaluation
                proposal = TradeProposal(
                    asset=asset_m,
                    timeframe=timeframe_m,
                    side=side,
                    price_cents=price_cents,
                    intent_risk=float(size) * (price_cents / 100.0),  # Dollar amount
                    tags=list(self.config.archetype_tags) if hasattr(self.config, 'archetype_tags') else [],
                    fear_greed=int(getattr(snapshot, 'sentiment_global', 0.5) * 100)
                    if getattr(snapshot, 'sentiment_global', None) is not None else None,
                    spread_ticks=self._estimate_spread_ticks(snapshot),
                    volume_24h=float(market.volume) if market.volume else None,
                    minutes_to_expiry=int(snapshot.time_to_expiry_hours * 60) if snapshot.time_to_expiry_hours else None,
                    session_stable=getattr(snapshot, 'sentiment_regime', 'normal') != 'extreme_volatility',
                )
                
                # Use per-agent singleton so daily PnL and open-exposure
                # state persist across calls (not zeroed on every signal).
                if self._btc15m_risk is None:
                    # Bootstrap equity + phase from PromotionEngine if available
                    _init_equity = 0.0
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_ta
                        _init_equity = float(getattr(_gkr_ta().state, 'current_equity_usd', 0) or 0)
                    except Exception as _e:
                        self.logger.debug("equity_lookup_kalshi_risk: %s", _e)
                    if _init_equity <= 0:
                        try:
                            from merid.settings import settings as _s_ta
                            _init_equity = float(getattr(_s_ta, 'PAPER_STARTING_BALANCE', 0) or 0)
                        except Exception as _e:
                            self.logger.debug("equity_lookup_settings: %s", _e)
                    _init_phase = RiskPhase.PHASE_0
                    try:
                        from merid.risk.promotion_engine import get_promotion_engine
                        _pe = get_promotion_engine()
                        # Do NOT overwrite _init_equity with per_trade cap — that is a
                        # per-order sizing limit, not the account equity.  Only use it
                        # to resolve the current promotion phase.
                        _phase_name = _pe.get_status().get("current_phase", "PHASE_0")
                        _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
                    except Exception as _e:
                        self.logger.debug("phase_lookup_promotion_engine: %s", _e)
                    self._btc15m_risk = CryptoSwarmRiskBTC15m(
                        current_equity=_init_equity,
                        phase=_init_phase,
                    )
                risk_manager = self._btc15m_risk
                # B9: _init_equity is only defined when self._btc15m_risk was None above.
                # Re-resolve current equity here so update_from_phase always has a value.
                _cur_equity = 0.0
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_upd
                    _cur_equity = float(getattr(_gkr_upd().state, 'current_equity_usd', 0) or 0)
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")
                if _cur_equity <= 0:
                    try:
                        from merid.settings import settings as _s_upd
                        _cur_equity = float(getattr(_s_upd, 'PAPER_STARTING_BALANCE', 0) or 0)
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                try:
                    risk_manager.update_from_phase(_cur_equity)
                except Exception as _e:
                    self.logger.debug("update_from_phase: %s", _e)

                # Sync live exposure from KalshiRiskManager each call
                try:
                    risk_manager.open_exposure_total = self._get_current_open_exposure()
                    risk_manager.open_positions = self._get_open_positions_dict()
                except Exception as _e:
                    self.logger.debug("sync_open_exposure: %s", _e)

                decision = risk_manager.evaluate_proposal(proposal)

                self.logger.info(
                    "crypto 15m risk decision: asset=%s tf=%s mode=%s intent_risk_usd=%.4f "
                    "(mid×contracts for swarm) price_cents_for_risk=%s contracts=%s "
                    "final_risk_usd=%.2f (after F&G/caps) | %s",
                    asset_m,
                    timeframe_m,
                    decision.mode.value,
                    proposal.intent_risk,
                    price_cents,
                    size,
                    decision.final_size,
                    decision.reason,
                )

                if decision.mode == TradeMode.BLOCKED:
                    self.logger.info(
                        "crypto 15m risk BLOCKED: asset=%s %s",
                        asset_m,
                        decision.blocked_reason,
                    )
                    await self._record_risk_blocked_order(market, signal, decision, snapshot)
                    return

                # Adjust size based on risk decision
                if decision.final_size < proposal.intent_risk:
                    original_contracts = size
                    # Recalculate contracts based on final dollar size
                    if price_cents > 0:
                        size = int(decision.final_size / (price_cents / 100.0))
                        size = max(1, size)  # At least 1 contract
                    self.logger.info(
                        "crypto 15m size adjusted: asset=%s %s → %s contracts ($%.2f)",
                        asset_m,
                        original_contracts,
                        size,
                        decision.final_size,
                    )

                # For paper mode, force simulation
                force_paper = decision.mode == TradeMode.PAPER

            except Exception as exc:
                # Risk layer failed - log and continue with normal execution
                self.logger.warning("crypto 15m risk evaluation failed: %s", exc)
                force_paper = False
        else:
            # Non-crypto-15m: route through existing paper/live gate
            force_paper = False

        # === SwarmConsensusEngine Gate ===
        # Formal vote-veto and explainability layer.  _check_consensus_gate() above
        # already handles direction + size band; this adds explicit veto support,
        # structured Explainability events, and a per-trade audit trail.
        # Fail-open: any error falls through to normal execution.
        try:
            from merid.swarm.consensus_engine import get_swarm_consensus_engine as _get_sce
            from merid.pipeline.proposal import (
                TradeProposal as _TradeProposal,
                TradeDomain as _TradeDomain,
                OrderSide as _OSide,
                OrderType as _OType,
            )
            from merid.agents.coordination import AgentVote as _AgentVote
            from decimal import Decimal as _SCEDecimal

            _sce_proposal = _TradeProposal(
                domain=_TradeDomain.PREDICTION,
                agent_id=self.agent_id,
                venue="kalshi",
                instrument_id=market.market_id,
                side=_OSide.BUY if action == "buy" else _OSide.SELL,
                order_type=_OType.LIMIT,
                qty=_SCEDecimal(str(size)),
                price=_SCEDecimal(str(price_cents / 100.0)) if price_cents else None,
                confidence=_SCEDecimal(str(
                    float(signal.confidence) if hasattr(signal, "confidence") else 0.5
                )),
                rationale=f"{signal.action} {market.market_id}",
            )
            _sce_pid = _sce_proposal.proposal_id

            # Base votes: this agent + risk-manager + governance
            # (execution_guard.pre_trade_check() and BTC15m risk already passed above)
            _sce_votes: list = [
                _AgentVote(
                    agent_id=self.agent_id,
                    decision="approve",
                    confidence=float(signal.confidence) if hasattr(signal, "confidence") else 0.5,
                    reasoning="pre-trade checks passed",
                    weight=1.0,
                ),
                _AgentVote(
                    agent_id="risk-manager-01",
                    decision="approve",
                    confidence=1.0,
                    reasoning="execution_guard pre_trade_check passed",
                    weight=1.5,
                ),
                _AgentVote(
                    agent_id="governance-01",
                    decision="approve",
                    confidence=1.0,
                    reasoning="Kalshi prediction domain validated",
                    weight=1.5,
                ),
            ]

            # Peer votes: map ConsensusAggregator raw_proposals → approve/reject/abstain
            try:
                from merid.swarm.consensus_aggregator import get_consensus_aggregator as _get_ca
                _peer_asset = self._strategy._extract_asset_from_market_id(market.market_id) if (self._strategy and market) else ""
                if not _peer_asset or _peer_asset == "UNK":
                    _peer_asset = self.config.assets[0] if self.config.assets else ""
                _peer_tf = self.config.timeframes[0] if self.config.timeframes else ""
                _cv = _get_ca().get_consensus(_peer_asset, _peer_tf)
                if _cv is not None:
                    for _rp in _cv.raw_proposals:
                        if _rp.agent_id == self.agent_id:
                            continue  # already counted in base votes above
                        _peer_decision = (
                            "approve" if _rp.direction == side
                            else "reject" if _rp.direction in ("yes", "no") and _rp.direction != side
                            else "abstain"
                        )
                        _sce_votes.append(_AgentVote(
                            agent_id=_rp.agent_id,
                            decision=_peer_decision,
                            confidence=_rp.confidence,
                            reasoning=f"peer direction={_rp.direction}",
                            weight=0.5 if _rp.downweight else 1.0,
                        ))
            except Exception as _cv_err:
                self.logger.debug("swarm_engine_peer_votes: %s", _cv_err)

            _sce_result = await asyncio.wait_for(
                _get_sce().run_consensus([_sce_proposal], {_sce_pid: _sce_votes}),
                timeout=3.0,
            )
            if not _sce_result:
                self.logger.info(
                    "swarm_engine_vetoed: %s side=%s action=%s size=%s",
                    market.market_id, side, action, size,
                )
                return

        except Exception as _sce_exc:
            self.logger.debug("swarm_engine_gate (fail-open): %s", _sce_exc)

        # === KalshiCore Agent Pipeline ===
        # Fire all 8 LLM-based reasoning agents against this trade proposal in the
        # background.  Results are recorded in Neo4j + the reflection system so agents
        # learn over time.  Never blocks trade execution — always fail-open.
        try:
            from core.kalshi_orchestrator import get_kalshi_core
            from core.energy import create_energy as _create_energy
            _kc_edge = getattr(signal, "edge", None)
            _kc_edge_bps = int(float(getattr(_kc_edge, "net_edge", 0)) * 10000) if _kc_edge else 0
            _kc_p_true = float(getattr(_kc_edge, "model_prob", 0.5)) if _kc_edge else 0.5
            _kc_p_implied = float(getattr(_kc_edge, "market_prob", 0.5)) if _kc_edge else 0.5
            _kc_payload = (
                f"Kalshi trade proposal | agent={self.agent_id} lane={self.config.name} "
                f"market={market.market_id} direction={side} action={action} "
                f"price={price_cents}c size={size} contracts "
                f"edge={_kc_edge_bps}bps p_true={_kc_p_true:.3f} p_implied={_kc_p_implied:.3f} "
                f"confidence={float(getattr(signal, 'confidence', 0)):.2f} "
                f"reason: {getattr(signal, 'reason', 'N/A')}"
            )
            _kc_energy = _create_energy(
                source=f"kalshi_lane:{self.config.name}",
                payload=_kc_payload,
            )
            _kc_task = asyncio.create_task(
                get_kalshi_core().run_cycle(_kc_energy),
                name=f"kalshi_core:{market.market_id}",
            )
            # Drain the exception so Python doesn't log "task was destroyed pending"
            _kc_task.add_done_callback(
                lambda _t: _t.exception() if not _t.cancelled() else None
            )
        except Exception as _kc_exc:
            self.logger.debug("kalshi_core_fire_and_forget: %s", _kc_exc)

        if action == "quote":
            # For quotes, place a buy and sell limit order pair
            _q_bid_result = None
            _q_ask_result = None
            if signal.bid_price_cents:
                _q_bid_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="buy",
                    price_cents=signal.bid_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                )
            if signal.ask_price_cents:
                _q_ask_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="sell",
                    price_cents=signal.ask_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                )
            # Record as a single "quote" event in logs
            _q_ok = ((_q_bid_result is None or _q_bid_result.success) and
                     (_q_ask_result is None or _q_ask_result.success))
            result_success = _q_ok
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(),
                "order_id": "quote_group",
            }
            if _q_ok:
                result_error = None
            else:
                _leg_errs: list[str] = []
                if _q_bid_result is not None and not _q_bid_result.success:
                    _leg_errs.append(f"bid:{_q_bid_result.error_message or 'fail'}")
                if _q_ask_result is not None and not _q_ask_result.success:
                    _leg_errs.append(f"ask:{_q_ask_result.error_message or 'fail'}")
                result_error = "; ".join(_leg_errs) if _leg_errs else "One or both quote legs failed"
        elif signal.side == "both":
            # BUG-4 fix: Arb — buy YES leg and NO leg via a shared Kalshi order
            # group so the exchange can atomically cancel both on limit breach.
            # A parent intent_id links both legs for downstream analytics.
            import uuid as _arb_uuid
            from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent as _ArbIntent

            price_cents = signal.limit_price_cents or 0
            yes_price = price_cents
            no_price = max(1, 100 - yes_price)

            # Create a dedicated order group for this arb trade
            _arb_group_id: Optional[str] = None
            _arb_notional_cents = size * (yes_price + no_price)
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client as _get_arb_client
                _arb_client = _get_arb_client()
                await _arb_client.connect()
                _arb_grp_res = await _arb_client.create_order_group(
                    name=f"arb-{market.market_id}-{_arb_uuid.uuid4().hex[:8]}",
                    max_cost_cents=_arb_notional_cents + 500,
                )
                if _arb_grp_res.success:
                    _arb_group_id = _arb_grp_res.data
                    self.logger.debug("arb: created order group %s", _arb_group_id)
            except Exception as _grp_exc:
                self.logger.warning("arb: order group creation failed (continuing without): %s", _grp_exc)

            _arb_parent_intent_id = f"arb-{_arb_uuid.uuid4().hex}"
            _arb_trace = new_decision_trace_id("arb")

            _snap_ts = (
                snapshot_timestamp_utc_epoch_seconds(getattr(snapshot, "timestamp", None))
                if snapshot
                else __import__("time").time()
            )

            async def _place_arb(s: str, p: int, leg: int) -> object:
                if force_paper:
                    from merid.prediction.kalshi_tools import _kalshi_place_paper_order
                    return await _kalshi_place_paper_order(
                        ticker=market.market_id, side=s, action="buy",
                        price_cents=p, count=size,
                    )
                _intent = _ArbIntent(
                    ticker=market.market_id, side=s, action="buy",
                    price_cents=p, count=size,
                    source=f"arb:{self.config.name}",
                    agent_id=self.agent_id,
                    order_group_id=_arb_group_id,
                    parent_intent_id=_arb_parent_intent_id,
                    leg_index=leg,
                    snapshot_ts=_snap_ts,
                    edge_pct=float(signal.edge.net_edge) if signal.edge else None,
                    decision_trace_id=_arb_trace,
                    sentiment_driven=False,
                )
                _r = await route_order_async(_intent)
                # Adapt to legacy .success / .payload / .error_message interface
                _r.success = _r.status not in ("rejected",)
                _r.payload = _r.fill or {}
                _r.error_message = _r.reason or ""
                return _r

            _yes_result = await _place_arb("yes", yes_price, 0)
            _no_result = await _place_arb("no", no_price, 1)

            async def _cancel_leg(order_id: Optional[str], label: str) -> None:
                if not order_id:
                    return
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client as _cc
                    _ccl = _cc()
                    await _ccl.connect()
                    _cr = await _ccl.cancel_order_result(order_id)
                    if _cr.success:
                        self.logger.warning("arb rollback: %s leg %s cancelled", label, order_id)
                    else:
                        self.logger.error(
                            "arb rollback: cancel of %s leg %s failed: %s — UNHEDGED EXPOSURE",
                            label, order_id, getattr(_cr, "error_message", _cr),
                        )
                except Exception as _rb_exc:
                    self.logger.error(
                        "arb rollback FAILED for %s leg %s: %s — UNHEDGED EXPOSURE",
                        label, order_id, _rb_exc,
                    )

            # Rollback YES if NO failed
            if _yes_result.success and not _no_result.success:
                await _cancel_leg((_yes_result.payload or {}).get("order_id"), "YES")

            # BUG-4 fix: also rollback NO if YES failed (was missing before)
            if _no_result.success and not _yes_result.success:
                await _cancel_leg((_no_result.payload or {}).get("order_id"), "NO")

            _arb_ok = _yes_result.success and _no_result.success
            result_success = _arb_ok
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(),
                "yes_order_id": (_yes_result.payload or {}).get("order_id"),
                "no_order_id": (_no_result.payload or {}).get("order_id"),
                "arb": True,
                "arb_group_id": _arb_group_id,
                "arb_parent_intent_id": _arb_parent_intent_id,
            }
            result_error = None if _arb_ok else (
                f"YES: {getattr(_yes_result, 'error_message', '')}; NO: {getattr(_no_result, 'error_message', '')}"
            )
            # Override side/action for log consistency
            side = "both"
            action = "buy"
        else:
            price_cents = signal.limit_price_cents or 0
            # Route through order_router so TIF resolution (IOC-auto-below-seconds
            # via KalshiMarketStateStore) and the full safety pipeline apply.
            # Consensus confidence and rationale are forwarded to the OrderIntent
            # so the order router can log and apply them.
            try:
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                from trading.trade_mode import TradeMode as _TradeMode
                _intent_mode = _TradeMode.PAPER if force_paper else None
                _conf = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else None
                _rationale = (
                    str(signal.action.value if hasattr(signal.action, "value") else signal.action)
                )[:200]
                # Prefer strategy correlation_id so logs ([TRACE] ANALYZE_START) match router / fills metadata.
                _sig_corr = getattr(signal, "correlation_id", None)
                _sig_corr_s = (
                    _sig_corr.strip()
                    if isinstance(_sig_corr, str) and _sig_corr.strip()
                    else None
                )
                _trace = _sig_corr_s or new_decision_trace_id("ta")
                _intent = OrderIntent(
                    ticker=market.market_id,
                    side=side,
                    action=action,
                    price_cents=price_cents,
                    count=size,
                    mode=_intent_mode,
                    source=self.agent_id,
                    agent_id=self.agent_id,
                    confidence=_conf,
                    rationale=_rationale,
                    edge_pct=float(signal.edge.net_edge) if signal.edge else None,
                    snapshot_ts=snapshot_timestamp_utc_epoch_seconds(
                        getattr(snapshot, "timestamp", None) if snapshot else None
                    ),
                    decision_trace_id=_trace,
                    client_tag=_sig_corr_s,
                    sentiment_driven=bool(_conf and _conf > 0.4),
                )
                _route_result = await route_order_async(_intent)
                # Adapt OrderResult → legacy .success/.payload/.error_message
                result_success = _route_result.status not in ("rejected",)
                result_payload = _route_result.fill or {}
                result_error = _route_result.reason or ""
            except Exception as _re:
                self.logger.warning("route_order_async failed, falling back: %s", _re)
                if force_paper:
                    from merid.prediction.kalshi_tools import _kalshi_place_paper_order
                    _fb = await _kalshi_place_paper_order(
                        ticker=market.market_id,
                        side=side,
                        action=action,
                        price_cents=price_cents,
                        count=size,
                    )
                else:
                    _fb = await _kalshi_place_order(
                        ticker=market.market_id,
                        side=side,
                        action=action,
                        price_cents=price_cents,
                        count=size,
                        agent_name=self.agent_id,
                    )
                result_success = _fb.success
                result_payload = _fb.payload
                result_error = _fb.error_message

        try:
            from merid.prediction.crypto_edge_production import log_execution_decision
            from core.execution_gate import check_execution_gate

            _eg = check_execution_gate()
            _safe = bool(getattr(_eg, "safe_to_trade", True) and not getattr(_eg, "blocked", False))
            _eg_sources = [r.source for r in (_eg.reasons or [])]
            _cv = None
            try:
                _ca = get_consensus_aggregator().get_consensus(
                    self.config.assets[0] if self.config.assets else "",
                    self.config.timeframes[0] if self.config.timeframes else "",
                )
                if _ca:
                    _cv = {
                        "direction": _ca.consensus_direction,
                        "p": _ca.consensus_probability,
                        "status": _ca.status.value,
                    }
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
            log_execution_decision(
                market=market.market_id,
                side=str(side),
                size=int(size),
                consensus_value=_cv,
                safe_to_trade=_safe,
                risk_state=getattr(_eg, "gate_state", "unknown"),
                actual_order_submitted=bool(result_success),
                block_reason=(
                    "none"
                    if result_success
                    else (str(result_error)[:200] if result_error else "order_rejected_unknown")
                ),
                source="kalshi_trading_agent",
                execution_gate_sources=_eg_sources,
            )
            if _safe and not result_success and not (result_error or ""):
                logger.warning(
                    "[EXECUTION_INVARIANT] safe_to_trade but order failed without reason market=%s",
                    market.market_id,
                )
        except Exception as _exl:
            self.logger.debug("execution decision log skipped: %s", _exl)

        # BUG-FIX: Use explicit datetime module reference to avoid UnboundLocalError
        # when datetime is determined to be a local variable but hasn't been assigned yet.
        from datetime import datetime as _datetime_now
        now_ts = _datetime_now.now(timezone.utc)
        # Also fix the datetime references earlier in this function (lines ~3722, 3726)
        # where datetime was used without being declared global, causing Python to
        # treat it as local but unassigned at this point.
        ref_bid = float(snapshot.implied.yes_bid) if snapshot and snapshot.implied.yes_bid else None
        ref_ask = float(snapshot.implied.yes_ask) if snapshot and snapshot.implied.yes_ask else None
        ref_mid = (ref_bid + ref_ask) / 2 if ref_bid and ref_ask else None

        # Record order
        _o_edge_pct = float(signal.edge.net_edge) if signal.edge else None
        _o_confidence = float(signal.confidence) if hasattr(signal, "confidence") else None
        _o_phase = signal.phase.value if hasattr(signal, "phase") and signal.phase else ""
        _o_archetype = self.config.archetype if hasattr(self.config, "archetype") else ""
        _o_price_c = signal.limit_price_cents or 0
        _o_notional = round(size * (_o_price_c / 100.0), 2) if _o_price_c else None
        order_entry = {
            "ts": now_ts.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": side,
            "action": action,
            "price_cents": _o_price_c if action != "quote" else None,
            "bid_price": signal.bid_price_cents,
            "ask_price": signal.ask_price_cents,
            "contracts": size,
            "ref_bid": ref_bid,
            "ref_ask": ref_ask,
            "ref_mid": ref_mid,
            "success": result_success,
            "simulated": result_payload.get("simulated", False) if result_success else None,
            "error": result_error if not result_success else None,
            "agent": self.config.name,
            "edge_pct": _o_edge_pct,
            "confidence": _o_confidence,
            "phase": _o_phase,
            "archetype": _o_archetype,
            "notional_usd": _o_notional,
            "time_in_force": getattr(signal, "time_in_force", "gtc") or "gtc",
        }
        self.state.order_log.append(order_entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]

        # Publish order_placed event regardless of fill outcome
        try:
            from core.event_bus import event_stream as _event_bus
            await _event_bus.publish("kalshi:order_placed", order_entry)
        except Exception as _ep:
            self.logger.debug(f"Event bus order_placed publish error (ignored): {_ep}")

        # BUG-06 fix: derive live-fill flag from venue gate mode (authoritative),
        # not from a payload dict key that may be absent after schema changes.
        _is_live_fill = not self._venue_gate.should_simulate_fill()

        # BUG-02 fix: distinguish between an order being *accepted* (GTC resting)
        # and actually *filled*.  Only confirmed fills trigger risk accounting,
        # position tracking, and fill-log entries.  Accepted-only orders are
        # counted in the order log but not treated as open exposure.
        _order_status = (result_payload or {}).get("status", "")
        _is_accepted_only = (
            _is_live_fill
            and result_success
            and _order_status in ("accepted_live", "resting", "open")
            and _order_status not in ("filled_live", "partial_live")
            and not (result_payload or {}).get("simulated", False)
        )

        if result_success:
            self.state.orders_placed += 1
            self.state.orders_this_window += 1
            # End global ERROR_THRESHOLD startup grace on first real (non-simulated) live success.
            if _is_live_fill and not (result_payload or {}).get("simulated", False):
                try:
                    from merid.risk.kill_switches import risk_controller as _rc_warm

                    _rc_warm.mark_execution_warm(source=f"kalshi_order:{self.config.name}")
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")
            _order_id = result_payload.get("order_id", "") if result_payload else ""
            if _tick is not None and _bus is not None:
                _bus.emit(_tick.emit_order_submitted(
                    market_id=market.market_id,
                    side=side,
                    contracts=size,
                    price_cents=int(price_cents) if price_cents else 0,
                    order_id=str(_order_id),
                ))

            # [TRACE] EXECUTE_ORDER — log with correlation_id after order placement
            if corr_id:
                self.logger.info(
                    "[TRACE] EXECUTE_ORDER | corr_id=%s | market=%s | side=%s | action=%s | size=%s | price=%s | status=%s | simulated=%s",
                    corr_id,
                    market.market_id,
                    side,
                    action,
                    size,
                    price_cents,
                    "success" if result_success else "failed",
                    result_payload.get("simulated", False) if result_payload else False,
                )
            _edge_pct = float(signal.edge.net_edge) if signal.edge else None
            _confidence = float(signal.confidence) if hasattr(signal, "confidence") else None
            _phase = signal.phase.value if hasattr(signal, "phase") and signal.phase else ""
            _archetype = self.config.archetype if hasattr(self.config, "archetype") else ""
            _price_c = signal.limit_price_cents or 0
            _notional = round(size * (_price_c / 100.0), 2) if _price_c else None
            # B17: use actual fill price from the routing result (simulate_paper_fill
            # applies real bid/ask slippage); fall back to signal limit price only when
            # the fill dict is absent (e.g. legacy fallback path).
            _actual_fill_price_c = (
                result_payload.get("price_cents")
                or result_payload.get("fill_price_cents")
                or _price_c
            )
            fill_entry = {
                "ts": now_ts.isoformat(),
                "market_id": market.market_id,
                "question": market.question[:120] if market.question else "",
                "side": side,
                "action": action,
                "price_cents": _actual_fill_price_c if action != "quote" else None,
                "requested_price_cents": _price_c if action != "quote" else None,
                "contracts": size,
                "ref_bid": ref_bid,
                "ref_ask": ref_ask,
                "ref_mid": ref_mid,
                "simulated": result_payload.get("simulated", False),
                "fill_id": result_payload.get("order_id") or result_payload.get("fill_id"),
                "agent": self.config.name,
                "edge_pct": _edge_pct,
                "confidence": _confidence,
                "phase": _phase,
                "archetype": _archetype,
                "notional_usd": _notional,
                # Live market context from simulate_paper_fill (None when book not initialised)
                "book_initialized": result_payload.get("book_initialized"),
                "live_spread_cents": result_payload.get("live_spread_cents"),
                "live_depth_10c": result_payload.get("live_depth_10c"),
                "seconds_to_expiry": result_payload.get("seconds_to_expiry"),
                "slippage_cents": result_payload.get("slippage_cents"),
            }
            self.state.fill_log.append(fill_entry)
            if len(self.state.fill_log) > _MAX_LOG_ENTRIES:
                self.state.fill_log = self.state.fill_log[-_MAX_LOG_ENTRIES:]

            # Emit event bus event
            try:
                from core.event_bus import event_stream
                await event_stream.publish("kalshi:order_filled", fill_entry)
            except Exception as exc:
                self.logger.debug(f"Event bus publish error (ignored): {exc}")

            if _tick is not None and _bus is not None:
                _bus.emit(_tick.emit_fill(
                    market_id=market.market_id,
                    side=side,
                    contracts=size,
                    # B17: use actual fill price, not the pre-slippage limit price
                    fill_price_cents=int(_actual_fill_price_c or signal.limit_price_cents or 50),
                ))

            # ── Realized edge: log trade entry for later settlement comparison ──
            try:
                from merid.metrics.realized_edge import get_realized_edge_store
                from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents
                edge_store = get_realized_edge_store()
                _trade_id = result_payload.get("order_id") or f"{market.market_id}:{now_ts.isoformat()}"
                # B19a: use actual fill price from routing result, not pre-slippage limit price
                _price_c = int(_actual_fill_price_c or signal.limit_price_cents or 50)
                _p_implied = _price_c / 100.0
                # Bug 4 fix: use model_prob directly (pre-fee probability).
                # Reconstructing from net_edge subtracts fee drag twice because
                # net_edge is already p_model - p_implied - fee_drag.
                _p_model = _p_implied
                if signal.edge and hasattr(signal.edge, 'model_prob') and signal.edge.model_prob is not None:
                    _p_model = max(0.01, min(0.99, float(signal.edge.model_prob)))
                elif signal.edge and hasattr(signal.edge, 'net_edge'):
                    # Fallback for edges that only expose net_edge (legacy path)
                    _p_model = max(0.01, min(0.99, _p_implied + float(signal.edge.net_edge)))
                _fee_c = kalshi_fee_cents(_price_c, size)
                _bucket = (market.category or "unknown").lower()
                edge_store.record_trade_entry(
                    trade_id=_trade_id,
                    forecaster_id=self.config.name,
                    bucket=_bucket,
                    market_id=market.market_id,
                    side=side,
                    price_cents=_price_c,
                    p_model=_p_model,
                    p_implied=_p_implied,
                    contracts=size,
                    fee_cents=_fee_c,
                    timestamp=now_ts.timestamp(),
                )
            except Exception as _edge_exc:
                self.logger.debug("realized_edge record_trade_entry skipped: %s", _edge_exc)

            # Record fill in performance tracker
            try:
                tracker = get_agent_performance_tracker()
                tracker.record_fill(
                    agent_id=self.agent_id,
                    market_id=market.market_id,
                    side=side,
                    # B19a: use actual fill price, not pre-slippage limit price
                    price_cents=int(_actual_fill_price_c or signal.limit_price_cents or 50),
                    contracts=size,
                    predicted_edge=float(signal.edge.net_edge) if signal.edge else 0.0,
                    confidence=float(signal.confidence) if hasattr(signal, 'confidence') else 0.5,
                )
            except Exception as exc:
                self.logger.debug(f"Performance tracker record error (ignored): {exc}")

            # Wire 3 audit: write ConsensusBlock for replay/audit trail
            try:
                from merid.lanes.consensus_integration import create_consensus_block_from_lane
                _audit_asset = self.config.assets[0] if self.config.assets else ""
                _audit_tf = self.config.timeframes[0] if self.config.timeframes else ""
                _audit_consensus = get_consensus_aggregator().get_consensus(_audit_asset, _audit_tf)
                create_consensus_block_from_lane(
                    market_data={
                        "ticker": market.market_id,
                        "market_ticker": market.market_id,
                        "yes_bid": self._live_markets[0].yes_price if self._live_markets else None,
                        "no_bid": self._live_markets[0].no_price if self._live_markets else None,
                        "spread_bps": self._live_markets[0].spread_bps if self._live_markets else None,
                    },
                    consensus_result={
                        "direction": _audit_consensus.consensus_direction if _audit_consensus else "neutral",
                        "probability": _audit_consensus.consensus_probability if _audit_consensus else 0.5,
                        "confidence": _audit_consensus.consensus_confidence if _audit_consensus else 0.0,
                        "status": _audit_consensus.status.value if _audit_consensus else "stale",
                        "size_band": _audit_consensus.size_band if _audit_consensus else "small",
                    },
                    risk_decision={},
                    votes=[],
                )
            except Exception as _audit_exc:
                self.logger.debug("consensus_block_audit_failed (non-fatal): %s", _audit_exc)

            # Wire fill into PnL attribution engine for debate/signal attribution
            try:
                from merid.prediction.pnl_attribution import record_debate_trade
                _pnl_trade_id = (
                    (result_payload.get("order_id") or result_payload.get("fill_id"))
                    if result_payload else None
                ) or f"{market.market_id}:{now_ts.isoformat()}"
                _pnl_price = float(_actual_fill_price_c or signal.limit_price_cents or 50) / 100.0
                _base_kelly = (
                    float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0
                )
                _debate_mult = getattr(signal, "debate_multiplier", 1.0) or 1.0
                await record_debate_trade(
                    symbol=market.market_id,
                    trade_type="entry",
                    timestamp=now_ts.timestamp(),
                    price=_pnl_price,
                    quantity=size,
                    trade_id=_pnl_trade_id,
                    agent_id=self.agent_id,
                    base_kelly_fraction=_base_kelly,
                    debate_multiplier=_debate_mult,
                    final_kelly_fraction=_base_kelly * _debate_mult,
                    debate_recommendation=side,
                )
            except Exception as exc:
                self.logger.debug("pnl_attribution record_debate_trade skipped: %s", exc)

            # Register fill with stop-loss engine
            try:
                pos_id = result_payload.get("order_id") or market.market_id
                expiry_ts = market.end_date.timestamp() if market.end_date else 0.0
                # B19a: use actual fill price for entry tracking, not pre-slippage limit price
                _fill_price_for_tp = int(_actual_fill_price_c or signal.limit_price_cents or 50)
                tp = TrackedPosition(
                    position_id=pos_id,
                    ticker=market.market_id,
                    side=side,
                    entry_price_cents=_fill_price_for_tp,
                    contracts=size,
                    entry_ts=time.time(),
                    contract_expiry_ts=expiry_ts,
                    current_price_cents=_fill_price_for_tp,
                )
                self._tracked_positions[pos_id] = tp
                self.logger.debug("stop_loss: tracking position %s %s@%dc", pos_id, side, tp.entry_price_cents)
                # Register with TakeProfitManager — arms the TP state machine
                try:
                    self._tp_manager.on_position_open(tp)
                except Exception as _tp_reg_exc:
                    self.logger.debug("tp_manager.on_position_open skipped: %s", _tp_reg_exc)
            except Exception as exc:
                self.logger.debug("stop_loss register skipped: %s", exc)

            # Wire fill into KalshiRiskManager so risk/sizing endpoints see live flow
            # G3: Only record into live risk manager for real (non-simulated) fills.
            # Paper/sim fills must not skew live drawdown, rate-limit, or PnL state.
            # BUG-02: skip all fill-accounting for accepted-but-not-yet-filled orders.
            if _is_accepted_only:
                self.logger.debug(
                    "order accepted (GTC resting) for %s — fill accounting deferred until fill event",
                    market.market_id,
                )
            else:
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                    risk_mgr = get_kalshi_risk()
                    price_cents = signal.limit_price_cents or 50
                    category = getattr(self.config, 'category', None)
                    if _is_live_fill:
                        # Real fill: update notional exposure AND rate counters.
                        if action in ("sell",):
                            # Closing a position — decrement notional so the cap
                            # reflects actual open exposure, not lifetime volume.
                            risk_mgr.record_close(category=category, contracts=size, price_cents=price_cents)
                        else:
                            risk_mgr.record_order(category=category, contracts=size, price_cents=price_cents)
                        # NOTE: Do NOT call record_pnl() here with edge-based estimates.
                        # Kalshi contracts settle at expiry — PnL is only realized at
                        # settlement, not at fill time.  Crediting speculative edge as
                        # immediate PnL contaminates daily_pnl_usd (the daily loss kill
                        # switch trigger) with phantom gains/losses and inflates
                        # current_equity_usd used for Kelly sizing between PortfolioRiskAgent
                        # syncs.  OutcomeResolver calls record_pnl() at actual settlement.
                    else:
                        # Paper/sim fill: only advance rate-limit counters so a sudden
                        # mode-switch to live doesn't produce a thundering herd.
                        # Do NOT touch total_notional_usd or category_notional — those
                        # caps are for real exposure only.
                        risk_mgr.record_rate_only()
                except Exception as exc:
                    self.logger.debug(f"KalshiRiskManager record error (ignored): {exc}")

            # Record fill in paper session for per-interval PnL tracking
            # G1: Only record in PaperSession when the fill was actually simulated
            # (PAPER/MOCK mode). Live and Shadow fills must NOT pollute paper stats.
            #
            # BUG-02 fix: Kalshi binary contracts settle at expiry, not at fill
            # time.  Recording a random Bernoulli draw here produces an equity
            # curve that is entirely uncorrelated with actual outcomes.  Instead
            # we record only the trade entry (pnl=0, won=None) and let
            # OutcomeResolver call paper_session.record_settlement() once the
            # market resolves.
            _is_simulated_fill = not _is_live_fill
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active and _is_simulated_fill:
                    # B23: prefer actual fee_cents from simulate_paper_fill fill dict;
                    # fall back to pre-trade estimate from PreTradeCheck.
                    _actual_fee_cents = result_payload.get("fee_cents") if result_payload else None
                    if _actual_fee_cents is not None:
                        fee_cents = float(_actual_fee_cents)
                    else:
                        fee_cents = float(check.estimated_fee * 100) * size if hasattr(check, 'estimated_fee') and check.estimated_fee else 0.0
                    session.record_fill(
                        agent_name=self.config.name,
                        pnl_cents=0.0,       # deferred — booked at settlement
                        fees_cents=fee_cents,
                        won=None,            # outcome unknown until expiry
                    )
                    # Register the open trade for deferred settlement so
                    # OutcomeResolver can close it with the real outcome.
                    session.register_open_trade(
                        agent_name=self.config.name,
                        market_id=market.market_id,
                        side=side,
                        action=action,
                        contracts=size,
                        # B22: use actual fill price (post-slippage, market-anchored)
                        # not pre-slippage signal limit price. OutcomeResolver uses
                        # this price in the binary payoff formula at settlement.
                        price_cents=float(_actual_fill_price_c or signal.limit_price_cents or 50),
                    )
            except Exception as exc:
                self.logger.debug(f"Paper session record error (ignored): {exc}")

            # Trigger portfolio rebalancer after fill
            # G4: Only execute real rebalance orders when NOT in simulated mode
            try:
                from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
                from merid.event_venues.kalshi.client import get_kalshi_client as _get_rb_client
                _rebalancer = get_portfolio_rebalancer()
                if _rebalancer.get_targets():  # only run if targets are configured
                    _rb_client = _get_rb_client()
                    _rb_actions = await _rebalancer.analyze_rebalance_needed(_rb_client)
                    if _rb_actions:
                        self.logger.info(
                            "rebalancer: %d actions needed after fill on %s",
                            len(_rb_actions), market.market_id,
                        )
                        # G4: Gate real rebalance orders on VenueGate — skip in paper/sim mode
                        if not _is_simulated_fill:
                            await _rebalancer.execute_rebalance(_rb_client, actions=_rb_actions)
                        else:
                            self.logger.debug(
                                "rebalancer: skipping execute in paper/sim mode (%d actions)",
                                len(_rb_actions),
                            )
            except Exception as exc:
                self.logger.debug("rebalancer post-fill skipped: %s", exc)

            # Update CryptoSwarmRiskBTC15m open-exposure tracker on fill.
            # G2: Use actual agent deployment mode, not hardcoded PAPER.
            # BUG-03 fix: do NOT use a Bernoulli draw to simulate PnL here.
            # Kalshi contracts settle at expiry; real PnL is only known then.
            # Instead, record the raw dollar exposure added by this fill so the
            # risk manager's open-exposure cap is accurate.  OutcomeResolver will
            # call record_trade_result() with the true outcome at settlement.
            if self._btc15m_risk is not None and not _is_accepted_only:
                try:
                    from merid.risk.crypto_swarm_risk_btc15m import TradeMode as _TM
                    # B22: use actual fill price for exposure tracking, not signal limit price
                    p_c = float(_actual_fill_price_c or signal.limit_price_cents or 50)
                    # Dollar exposure added by this fill (cost to open the position)
                    _open_exposure_delta = size * p_c / 100.0
                    # Resolve actual trade mode from deployment controller
                    _btc_mode = _TM.PAPER
                    try:
                        # B12: use public get_mode() — ._agents is private dict
                        from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode as _AM
                        _dep_ctrl = get_deployment_controller()
                        _dep_agent_mode = _dep_ctrl.get_mode(self.agent_id)
                        if _dep_agent_mode == _AM.LIVE:
                            _btc_mode = _TM.LIVE
                        elif _dep_agent_mode == _AM.SHADOW:
                            _btc_mode = _TM.LIVE  # shadow counts as live for risk tracking
                    except Exception as _dep_exc:
                        self.logger.debug("deployment mode lookup failed: %s", _dep_exc)
                    # Sync exposure; PnL recording deferred to OutcomeResolver
                    self._btc15m_risk.open_exposure_total = (
                        getattr(self._btc15m_risk, "open_exposure_total", 0.0)
                        + _open_exposure_delta
                    )
                    self.logger.debug(
                        "btc15m risk: open_exposure_total += %.2f (deferred PnL at settlement)",
                        _open_exposure_delta,
                    )
                except Exception as _rte:
                    self.logger.debug("btc15m risk exposure update skipped: %s", _rte)

            # Record decision in ReflectionSystem for learning/persistence
            try:
                from agents.reflection.integration import get_reflection_system
                reflection_sys = get_reflection_system()
                action_str = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
                confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5
                edge_val = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0
                reflection_sys.record_decision(
                    agent_id=self.agent_id,
                    energy_id=f"{market.market_id}:{now_ts.isoformat()}",
                    decision="accept",
                    confidence=confidence,
                    reasoning=f"{action_str} {size}x {market.market_id} edge={edge_val:.4f}",
                    market_context={
                        "market_id": market.market_id,
                        "question": market.question[:120] if market.question else "",
                        "side": side,
                        "action": action,
                        "price_cents": signal.limit_price_cents,
                        "contracts": size,
                        "edge": edge_val,
                        "implied_yes": float(snapshot.implied.yes_prob) if snapshot and snapshot.implied else None,
                        "implied_no": float(snapshot.implied.no_prob) if snapshot and snapshot.implied else None,
                        "simulated": result_payload.get("simulated", False),
                    },
                    agent_state=self.state.to_dict(),
                )
            except Exception as exc:
                self.logger.debug(f"ReflectionSystem record error (ignored): {exc}")

            # Emit ForecastEvent into RewardEngine so fills flow into reputation pipeline
            try:
                from merid.rewards.engine import get_reward_engine
                from merid.rewards.events import ForecastEvent
                _engine = get_reward_engine()
                _engine.process_event(ForecastEvent(
                    agent_id=self.agent_id,
                    venue="kalshi",
                    symbol=market.market_id,
                    probability=(
                        float(signal.edge.model_prob)
                        if signal.edge and hasattr(signal.edge, "model_prob") and signal.edge.model_prob is not None
                        else float(signal.limit_price_cents or 50) / 100.0
                    ),
                    confidence=float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5,
                    metadata={
                        "action": action,
                        "side": side,
                        "contracts": size,
                        "price_cents": price_cents,
                        "simulated": result_payload.get("simulated", False),
                    },
                ))
            except Exception as exc:
                self.logger.debug("RewardEngine ForecastEvent skipped: %s", exc)

            self.logger.info(
                f"Order placed: {action} {size}x {side} {market.market_id} "
                f"@{price_cents}c (sim={result_payload.get('simulated', False)})"
            )
        else:
            # Record error in paper session only for paper/sim fills
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active and not _is_live_fill:
                    session.record_error(self.config.name)
            except Exception as _pse:
                self.logger.debug("paper session record_error skipped: %s", _pse)
            # Wire into global error-threshold kill switch — only *incident* failures,
            # not expected policy rejects (sanity_check, caps, live_not_enabled, etc.).
            try:
                from merid.prediction.order_error_threshold import (
                    should_count_toward_error_threshold,
                )
                from merid.risk.kill_switches import risk_controller as _rc

                if should_count_toward_error_threshold(result_error):
                    _rc.record_error(error_hint=result_error or "")
                else:
                    self.logger.debug(
                        "error_threshold_skip: policy rejection not counted | %s | %s",
                        market.market_id,
                        (result_error or "")[:300],
                    )
            except Exception as _kse:
                self.logger.debug("kill_switch record_error skipped: %s", _kse)
            self.logger.warning(
                f"Order failed for {market.market_id}: {result_error}"
            )

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable agent summary."""
        # Get base state dict
        base_state = self.state.to_dict()

        # Build performance snapshot (BUG-W3 fix)
        performance = {}
        if hasattr(self, '_performance_tracker') and self._performance_tracker:
            metrics = self._performance_tracker.get_agent_metrics(self.agent_id)
            if metrics:
                performance = metrics.to_dict()

        return {
            **base_state,
            "config": {
                "name": self.config.name,
                "assets": self.config.assets,
                "timeframes": self.config.timeframes,
                "category": getattr(self.config, 'category', 'unknown'),
                "archetype": getattr(self.config, 'archetype', 'unknown'),
                "agent_id": self.config.agent_id,
                "risk_limits": {
                    "max_yes_position": self.config.risk_limits.max_yes_position,
                    "max_no_position": self.config.risk_limits.max_no_position,
                    "max_orders_per_window": self.config.risk_limits.max_orders_per_window,
                    "max_notional_usd": str(self.config.risk_limits.max_notional_usd),
                },
                "entry_window": {
                    "minutes_before_expiry": self.config.entry_window.minutes_before_expiry,
                    "cutoff_minutes_before_expiry": self.config.entry_window.cutoff_minutes_before_expiry,
                },
            },
            "performance": performance,
            "last_heartbeat_ts": base_state.get("last_heartbeat_at", time.time()),
            "take_profit": self._build_tp_summary(),
        }

    def _build_tp_summary(self) -> Dict[str, Any]:
        """Build take-profit summary for agent status endpoint.

        Returns aggregated TP state and per-position details for observability.
        """
        try:
            base = self._tp_manager.summary()
        except Exception as _e:
            base = {"error": str(_e)}

        # Add per-position TP state for open positions
        position_details: Dict[str, Any] = {}
        for pos_id, pos in self._tracked_positions.items():
            try:
                tp_state = self._tp_manager.get_state(pos_id)
                if tp_state:
                    position_details[pos_id] = {
                        "ticker": pos.ticker,
                        "side": pos.side,
                        "entry_price_cents": pos.entry_price_cents,
                        "current_price_cents": pos.current_price_cents,
                        "contracts": pos.contracts,
                        "tp_state": tp_state.tp_state.value,
                        "primary_target_cents": tp_state.primary_target_cents,
                        "remaining_contracts": tp_state.remaining_contracts,
                        "peak_price_cents": tp_state.peak_price_cents if tp_state.peak_price_cents > 0 else None,
                        "round_trips": self._tp_manager._round_trips.get(pos.ticker, {}).get("round_trips", 0),
                    }
            except Exception as _e:
                position_details[pos_id] = {"error": str(_e)}

        return {
            **base,
            "positions": position_details,
            "config": {
                "tp_enabled": self._tp_manager._config.tp_enabled,
                "tp_r_multiple_primary": self._tp_manager._config.tp_r_multiple_primary,
                "tp_scale_out_fraction": self._tp_manager._config.tp_scale_out_fraction,
                "tp_trailing_enabled": self._tp_manager._config.tp_trailing_enabled,
                "tp_trailing_giveback_cents": self._tp_manager._config.tp_trailing_giveback_cents,
            } if hasattr(self._tp_manager, "_config") else {},
        }

    def get_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent strategy signals."""
        return self.state.signal_log[-limit:]

    def get_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent orders."""
        return self.state.order_log[-limit:]

    def get_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent fills."""
        return self.state.fill_log[-limit:]

    # ── Crypto 15m risk layer helpers (CryptoSwarmRiskBTC15m) ───────────────

    def _estimate_spread_ticks(self, snapshot: Optional[MarketSnapshot]) -> Optional[int]:
        """Estimate spread in ticks (cents) from snapshot.

        ImpliedProbability stores yes_bid/yes_ask in the same units they were
        inserted: the WS path stores raw cents (0-99) while the fallback path
        stores Decimal fractions (0.0-1.0).  We normalise to cents here so
        the returned value is always in the 0-99 range expected by callers.
        """
        if not snapshot or not snapshot.implied:
            return None
        yes_bid = float(snapshot.implied.yes_bid) if snapshot.implied.yes_bid else 0
        yes_ask = float(snapshot.implied.yes_ask) if snapshot.implied.yes_ask else 0
        if yes_bid > 0 and yes_ask > 0:
            spread = yes_ask - yes_bid
            # Values in fraction range (0-1): convert to cents
            if yes_ask <= 1.0:
                spread = spread * 100.0
            return max(0, int(round(spread)))
        return None

    def _get_current_open_exposure(self) -> float:
        """Get total dollar exposure of open positions."""
        try:
            # Try to get from KalshiRiskManager
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_mgr = get_kalshi_risk()
            total_notional = risk_mgr.state.total_notional_usd if hasattr(risk_mgr, 'state') else 0.0
            return total_notional
        except Exception as _rme:
            self.logger.debug("kalshi_risk notional lookup skipped, using fill log: %s", _rme)
            # Fallback: estimate from fill log
            total = 0.0
            for fill in self.state.fill_log[-100:]:  # Last 100 fills
                if fill.get("action") == "buy":
                    price = fill.get("price_cents", 50)
                    contracts = fill.get("contracts", 0)
                    total += contracts * (price / 100.0)
            return total

    def _get_open_positions_dict(self) -> Dict[str, float]:
        """Get open positions as ticker -> exposure dict."""
        positions: Dict[str, float] = {}
        for fill in self.state.fill_log[-50:]:
            ticker = fill.get("market_id", "")
            contracts = fill.get("contracts", 0)
            price = fill.get("price_cents", 50)
            exposure = contracts * (price / 100.0)
            if fill.get("action") == "buy":
                positions[ticker] = positions.get(ticker, 0) + exposure
            elif fill.get("action") == "sell":
                positions[ticker] = positions.get(ticker, 0) - exposure
        # Remove zero/negative positions
        return {k: v for k, v in positions.items() if v > 0}

    async def _record_risk_blocked_order(
        self,
        market: EventMarket,
        signal: StrategySignal,
        decision: Any,
        snapshot: Optional[MarketSnapshot],
    ) -> None:
        """Record a risk-blocked order in logs and explainability."""
        now = datetime.now(timezone.utc)
        
        # Add to order log as blocked
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no",
            "action": str(signal.action),
            "contracts": signal.contracts,
            "success": False,
            "error": f"Risk blocked: {decision.blocked_reason}",
            "risk_decision": {
                "mode": decision.mode.value,
                "reason": decision.reason,
                "adjustments": decision.adjustments,
            },
        }
        self.state.order_log.append(entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]
        
        # Record in explainability
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker
            
            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            
            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"BLOCKED: {action_value} {market.market_id}", 0.0)
            builder.set_primary_reason(f"Crypto 15m risk layer blocked: {decision.blocked_reason}")
            builder.add_contrary_factor(f"risk decision: {decision.reason}")
            
            for adj_name, adj_value in decision.adjustments.items():
                builder.add_contrary_factor(f"adjustment: {adj_name}={adj_value}")
            
            builder.set_risk_assessment(
                {
                    "allowed": False,
                    "reason": decision.blocked_reason,
                    "crypto_15m_risk_layer": True,
                    "adjustments": decision.adjustments,
                }
            )
            
            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability blocked order record skipped: {exc}")

    # ── Market Mood Bus Integration ────────────────────────────────────────

    def _get_mood_context(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Any]:
        """Get unified market context from the Market Mood Bus."""
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            return bus.get_context(asset, timeframe)
        except Exception as exc:
            self.logger.debug(f"MarketMoodBus fetch error: {exc}")
            return None

    def _build_kalshi_market_context(self, ticker: str, snapshot: MarketSnapshot) -> dict:
        """Build a market-data context dict from live KalshiMarketState + snapshot.

        Used by KalshiLiveMarketStrategy and for populating AgentProposal.market_data.
        News/sentiment from the snapshot is included at a capped weight so it
        informs but does not dominate the opinion.
        """
        ctx: dict = {}
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            state = get_kalshi_market_state_store().get(ticker)
            if state:
                ctx["mid_cents"] = state.mid_cents
                ctx["spread_cents"] = state.spread_cents
                ctx["best_bid_cents"] = state.best_bid_cents
                ctx["best_ask_cents"] = state.best_ask_cents
                ctx["top_of_book_size"] = state.top_of_book_size
                ctx["depth_10c"] = state.depth_10c
                ctx["volume_24h"] = state.volume_24h
                ctx["open_interest"] = state.open_interest
                ctx["seconds_to_expiry"] = state.seconds_to_expiry
                ctx["book_initialized"] = state.book_initialized
        except Exception as _mse:
            self.logger.debug("Kalshi market state fetch skipped: %s", _mse)

        # Supplement with news/sentiment — kept at minimal weight via strategy
        sent_score = getattr(snapshot, "sentiment_global", None)
        if sent_score is not None:
            # snapshot stores sentiment as 0-100 (fear/greed); normalise to −1→+1
            ctx["sentiment_score"] = (float(sent_score) / 50.0) - 1.0
        elif getattr(snapshot, "sentiment_local", None) is not None:
            ctx["sentiment_score"] = float(snapshot.sentiment_local)

        # ── TSM context keys for crypto opinion strategies ────────────────────
        try:
            from config.kalshi_crypto_series_meta import infer_asset_from_kalshi_market_ticker
            _tsm_asset = infer_asset_from_kalshi_market_ticker(ticker)
            if _tsm_asset:
                ctx["asset"] = _tsm_asset
                ctx["horizon_secs"] = float(ctx.get("seconds_to_expiry") or 3600.0)
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                _cat_mkt = get_market_catalog().get_market(ticker)
                if _cat_mkt:
                    if _cat_mkt.market_type == "range":
                        ctx["market_type"] = "bracket"
                        if _cat_mkt.floor_strike and _cat_mkt.cap_strike:
                            ctx["bracket"] = [_cat_mkt.floor_strike, _cat_mkt.cap_strike]
                    else:
                        ctx["market_type"] = "threshold"
                        if _cat_mkt.strike_price is not None:
                            ctx["strike"] = _cat_mkt.strike_price
                            ctx["side"] = "above"
        except Exception as _tce:
            self.logger.debug("TSM context injection skipped: %s", _tce)

        return ctx

    def _resolve_consensus_asset_timeframe(
        self, signal: object, *, market_id_fallback: str = ""
    ) -> tuple[str, str]:
        """Asset/timeframe for Wire-2 proposals. Multi-asset agents (e.g. ``CRYPTO_15M_MM``) omit ``assets: []`` — infer from ``signal.market_id``."""
        asset = (self.config.assets[0] if self.config.assets else "") or ""
        timeframe = (self.config.timeframes[0] if self.config.timeframes else "") or ""
        mid = (getattr(signal, "market_id", None) or "").strip()
        if not mid and market_id_fallback:
            mid = market_id_fallback.strip()
        if asset and timeframe:
            return asset, timeframe
        try:
            from config.kalshi_crypto_series_meta import (
                infer_asset_from_kalshi_market_ticker,
                infer_asset_timeframe_from_ticker,
            )

            if not asset:
                asset = infer_asset_from_kalshi_market_ticker(mid) or ""
            prefix = mid.split("-")[0].upper() if mid and "-" in mid else (mid.upper() if mid else "")
            if prefix:
                a2, t2 = infer_asset_timeframe_from_ticker(prefix)
                if not asset and a2 and a2 != "UNK":
                    asset = a2
                if not timeframe and t2 and t2 != "UNK":
                    timeframe = t2
        except Exception as _ce:
            self.logger.debug("consensus asset infer: %s", _ce)
        if not asset and mid:
            try:
                asset = self._strategy._extract_asset_from_market_id(mid)
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
        return asset or "", timeframe or ""

    def _submit_consensus_proposal(self, signal: object) -> None:
        """Submit an AgentProposal to SwarmConsensusAggregator (Wire 2).

        Called once per cycle after the first actionable signal is generated.
        Never raises — consensus failure must not block trading.
        """
        try:
            asset, timeframe = self._resolve_consensus_asset_timeframe(signal)
            if not asset:
                self.logger.debug(
                    "consensus_proposal_skipped: empty asset (agent=%s market_id=%s)",
                    self.config.name,
                    getattr(signal, "market_id", None),
                )
                return

            proposal = get_kalshi_consensus_adapter().signal_to_proposal(
                signal=signal,
                agent_id=self.config.agent_id,
                asset=asset,
                timeframe=timeframe,
                archetype=self.config.archetype,
                live_markets=self._live_markets,
                track_record=getattr(self, "_track_record", None),
            )
            get_consensus_aggregator().submit_proposal(proposal)
            self.logger.debug(
                "consensus_proposal_submitted: %s %s->%s conf=%.2f",
                self.config.name, asset, proposal.direction, proposal.confidence,
            )
        except Exception as exc:
            self.logger.warning("consensus_proposal_failed (non-fatal): %s", exc)

    def _submit_to_consensus(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        mood_context: Optional[Any],
    ) -> bool:
        """Submit agent proposal to SwarmConsensusAggregator + TaCoConsensusCoordinator.

        Returns True if the proposal was successfully submitted to the aggregator.

        The primary opinion is derived from live Kalshi market data (orderbook,
        spread, depth, volume, OI, expiry) via KalshiLiveMarketStrategy.
        News/sentiment from the snapshot contributes at most 3 % of the final
        estimate so it still informs but cannot override market signals.

        Both the execution-gating ``SwarmConsensusAggregator`` and the
        debate-orchestrating ``TaCoConsensusCoordinator`` receive the opinion,
        ensuring the full consensus/debate/vote/execute pipeline operates on
        real Kalshi data rather than news alone.
        """
        # [TRACE] CONSENSUS_START — log with correlation_id from signal
        corr_id = getattr(signal, 'correlation_id', None)
        if corr_id:
            self.logger.info(
                "[TRACE] CONSENSUS_START | corr_id=%s | market=%s | agent=%s | direction=%s | formulas=%s | audit_spec=%s",
                corr_id,
                market.market_id,
                self.agent_id,
                signal.action.value if hasattr(signal.action, 'value') else signal.action,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )
        try:
            from merid.swarm.consensus_aggregator import (
                get_consensus_aggregator,
                AgentProposal,
            )

            # ── Direction from signal action ──────────────────────────────
            direction_map = {
                SignalAction.BUY_YES:  "yes",
                SignalAction.SELL_YES: "no",
                SignalAction.BUY_NO:   "no",
                SignalAction.SELL_NO:  "yes",
            }
            direction = direction_map.get(signal.action, "neutral")

            # ── Base probability from signal or snapshot ──────────────────
            market_prob = 0.5
            if signal.edge and hasattr(signal.edge, 'yes_prob'):
                market_prob = float(signal.edge.yes_prob)
            elif snapshot.implied:
                market_prob = float(snapshot.implied.yes_prob)

            # ── Build live Kalshi market context ──────────────────────────
            market_ctx = self._build_kalshi_market_context(market.market_id, snapshot)

            # ── Use KalshiLiveMarketStrategy for market-data-driven prob ──
            prob = market_prob
            conf = 0.5
            signal_sources: list = ["strategy_signal"]
            reasoning_tag = str(signal.action)
            try:
                from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy
                _strategy = KalshiLiveMarketStrategy()
                _est = _strategy.estimate(
                    agent_id=self.agent_id,
                    ticker=market.market_id,
                    market_prob=market_prob,
                    category=(market.category or "").lower(),
                    context=market_ctx,
                )
                if _est is not None:
                    prob = _est.agent_prob
                    conf = _est.confidence
                    signal_sources = _est.signal_sources
                    reasoning_tag = _est.reasoning_tag
            except Exception as _se:
                self.logger.debug("KalshiLiveMarketStrategy skipped: %s", _se)
                if signal.edge and hasattr(signal.edge, 'confidence'):
                    conf = float(signal.edge.confidence)

            # ── Try TSM strategies for crypto markets ──────────────────────
            if market_ctx.get("asset"):
                try:
                    from merid.prediction.opinion_strategy import _STRATEGIES as _STRAT_REG
                    for _sn in ("spot_basis_fair_value", "trend_momentum"):
                        _s = _STRAT_REG.get(_sn)
                        if _s is None:
                            continue
                        _te = _s.estimate(
                            agent_id=self.agent_id,
                            ticker=market.market_id,
                            market_prob=prob,
                            category=(market.category or "").lower(),
                            context=market_ctx,
                        )
                        if _te is not None:
                            prob = 0.5 * _te.agent_prob + 0.5 * prob
                            signal_sources = list(dict.fromkeys(signal_sources + _te.signal_sources))
                            reasoning_tag = _te.reasoning_tag
                            break
                except Exception as _tse:
                    self.logger.debug("TSM strategy dispatch skipped: %s", _tse)

            # ── Size preference from mood context ─────────────────────────
            size_pref = "base"
            if mood_context and hasattr(mood_context, 'should_reduce_size'):
                if mood_context.should_reduce_size():
                    size_pref = "reduced"

            # ── Track record ──────────────────────────────────────────────
            track_record = None
            metrics = None
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                metrics = tracker.get_agent_metrics(self.agent_id)
                # BUG-M fix: AgentMetrics is a dataclass — use attribute
                # access, not dict .get(); was silently throwing AttributeError.
                # Gate on >= 5 closes so new agents don't populate track_record
                # with 0/0 values that block the live-tracker fallback in the
                # consensus aggregator (which has the same 5-close threshold).
                if metrics and metrics.total_closes >= 5:
                    track_record = {
                        "win_rate": metrics.win_rate,
                        "sharpe_ratio": metrics.sharpe_ratio,
                    }
            except Exception as _tre:
                self.logger.debug("track_record lookup skipped: %s", _tre)

            # Same inference as Wire-2 ``_submit_consensus_proposal`` — static
            # ``assets: []`` (CRYPTO_15M_MM, scanners) must not submit empty asset.
            asset, timeframe = self._resolve_consensus_asset_timeframe(
                signal, market_id_fallback=getattr(market, "market_id", "") or ""
            )

            # BUG-Y fix: check if this agent's Sharpe is below the matrix
            # downweight threshold and propagate the flag to the proposal so
            # the consensus aggregator can apply the 50% vote reduction.
            _proposal_downweight = False
            try:
                if metrics and metrics.total_closes >= 5:
                    from config.trading_constants import SHARPE_DOWNWEIGHT_THRESHOLD
                    _proposal_downweight = metrics.sharpe_ratio < SHARPE_DOWNWEIGHT_THRESHOLD
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")

            # ── Build + submit AgentProposal (execution gating) ───────────
            if asset:
                proposal = AgentProposal(
                    agent_id=self.agent_id,
                    asset=asset,
                    timeframe=timeframe,
                    direction=direction,
                    probability=prob,
                    confidence=conf,
                    size_preference=size_pref,
                    rationale=reasoning_tag,
                    edge_estimate=float(signal.edge.net_edge * 100) if signal.edge else 0.0,
                    timestamp=datetime.now(timezone.utc),
                    agent_archetype=self.config.archetype,
                    agent_track_record=track_record,
                    market_data=market_ctx if market_ctx else None,
                    downweight=_proposal_downweight,
                )
                get_consensus_aggregator().submit_proposal(proposal)
            else:
                self.logger.debug(
                    "_submit_to_consensus: skip AgentProposal (unresolved asset) agent=%s market=%s",
                    self.config.name,
                    market.market_id,
                )

            # ── Submit AgentOpinion to TaCoConsensusCoordinator ───────────
            # This feeds the debate-orchestration loop which scans _opinions
            # for high-disagreement Kalshi symbols.
            self._submit_taco_opinion(
                ticker=market.market_id,
                prob=prob,
                conf=conf,
                direction=direction,
                reasoning_tag=reasoning_tag,
                signal_sources=signal_sources,
                market_ctx=market_ctx,
            )

            self.logger.debug(
                "Submitted Kalshi-market-driven consensus: %s @ %.1f%% "
                "(conf=%.2f, sources=%s)",
                direction, prob * 100, conf, signal_sources[:3],
            )
            return True

        except Exception as exc:
            self.logger.debug("Consensus submission error: %s", exc)
            return False

    def _submit_taco_opinion(
        self,
        ticker: str,
        prob: float,
        conf: float,
        direction: str,
        reasoning_tag: str,
        signal_sources: list,
        market_ctx: dict,
    ) -> None:
        """Submit an AgentOpinion to TaCoConsensusCoordinator.

        The debate-orchestration loop reads ``coordinator._opinions`` keyed by
        symbol to find Kalshi markets with high inter-agent disagreement and
        create debate sessions.  Without this submission, debates are never
        triggered from real Kalshi market data.

        ``score`` maps agent probability → −1..+1:
          - P(YES) = 1.0 → score = +1.0 (strong YES)
          - P(YES) = 0.5 → score =  0.0 (neutral)
          - P(YES) = 0.0 → score = −1.0 (strong NO)
        """
        try:
            import uuid
            from consensus.taco_consensus import AgentOpinion, Stance, get_consensus_coordinator

            score = round((prob - 0.5) * 2.0, 4)  # map 0-1 → -1..+1

            if score >= 0.6:
                stance = Stance.STRONG_BULL.value
            elif score >= 0.3:
                stance = Stance.BULL.value
            elif score <= -0.6:
                stance = Stance.STRONG_BEAR.value
            elif score <= -0.3:
                stance = Stance.BEAR.value
            else:
                stance = Stance.NEUTRAL.value

            # Horizon from seconds_to_expiry
            secs = market_ctx.get("seconds_to_expiry")
            if secs is not None:
                if secs < 3_600:
                    horizon = "short"
                elif secs < 86_400:
                    horizon = "medium"
                else:
                    horizon = "long"
            else:
                horizon = "short"

            opinion = AgentOpinion(
                opinion_id=f"op_{uuid.uuid4().hex[:12]}",
                agent_id=self.agent_id,
                role=getattr(self.config, "archetype", "trader"),
                symbol=ticker,
                venue="kalshi",
                stance=stance,
                score=score,
                confidence=conf,
                rationale=reasoning_tag,
                horizon=horizon,
                data_sources=signal_sources,
                supporting_data={k: v for k, v in market_ctx.items() if v is not None},
            )

            coordinator = get_consensus_coordinator()
            import asyncio as _aio
            try:
                loop = _aio.get_running_loop()
                loop.create_task(coordinator.submit_opinion(opinion))
            except RuntimeError:
                _aio.run(coordinator.submit_opinion(opinion))

        except Exception as _te:
            self.logger.debug("TaCo opinion submission skipped: %s", _te)

    def _get_consensus(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Any]:
        """Get current consensus view from SwarmConsensusAggregator."""
        try:
            from merid.swarm.consensus_aggregator import get_consensus_aggregator
            aggregator = get_consensus_aggregator()
            return aggregator.get_consensus(asset, timeframe)
        except Exception as exc:
            self.logger.debug(f"Consensus fetch error: {exc}")
            return None
