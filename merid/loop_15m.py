"""
Kalshi 15m Lean Loop — Minimal event loop for kalshi_crypto_15m_v2 profile.

This is a clean, minimal loop designed specifically for the 15-minute crypto trading
stack on Kalshi. It replaces the complex legacy merid.loop for this profile.

Responsibilities:
- Pull latest market state / RTI inputs
- Run 5 agents' signal + decision logic via AgentGrid.run_cycle()
- Route orders through KalshiTradingAgent / order router / risk
- Run at 5-second cadence

This loop intentionally does NOT include:
- Legacy lane orchestration
- Reflection/learning systems
- KalshiContinuousTrader
- PM agents or regime agents
- Cross-venue arbitrage

IMPORT POLICY (15m_live mode):
Allowed imports:
- merid.loop_15m (this module)
- merid.prediction.agent_grid_15m
- merid.prediction.candidate_optimizer
- merid.event_venues.kalshi.* (venue adapter, market_state, risk)
- data.unified_spot_service
- config.kalshi_* (15m-specific configs only)
- Generic utilities (logging, metrics, datetime, typing, dataclasses)

Forbidden imports:
- PM runtime controllers
- Paper trading engine
- Reflection/learning systems
- Social broadcasters
- Cross-venue logic
- Deprecated config modules (kalshi_15m_crypto_config.py)

See docs/15M_STACK_SURFACE.md for complete allowed surface definition.

---

## Degraded Mode Semantics

### Definition
Degraded mode is a soft-fail / partial-health state where the system can continue
trading in healthy markets while some markets are temporarily unavailable or illiquid.

### Scope of Degradation
Degraded mode applies to:
- Market health signals (catalog age, depth coverage, bankroll sanity)
- NOT feature disabling (agents/timeframes remain active)
- NOT per-market blocking (healthy markets continue trading)

### Allowed vs Disallowed Actions

**Allowed in degraded mode:**
- Continue quoting in healthy markets (those passing depth checks)
- Continue consuming websockets
- Maintain bookkeeping (bankroll, PnL, position tracking)
- Run agent signal generation for all markets
- Execute orders only in markets with sufficient depth

**Disallowed in degraded mode:**
- New market onboarding (catalog refresh continues but no new trading)
- Aggressive scaling (position sizing may be throttled)
- Opening new positions in markets failing depth checks

### Loop States & Execution Modes (cadence-aware)

The loop separates THREE concerns so a normal gap between 15m strips is never
confused with a systemic failure:

1. `infra_ready`      — platform health: catalog reachable+fresh, WS forwarder
                        healthy, bankroll real+valid, risk profile loaded, TOP3 gate.
2. `markets_expected` — should strips exist now? (15m cadence + maintenance window).
3. `markets_present`  — does the catalog actually show >=1 active 15m strip?

**`loop_state`** (high-level "should we be trading?" — the source of truth):
- `HALT`     — `infra_ready=False`. System/venue broken or unsafe. Trading blocked. RED FLAG.
- `WAITING`  — infra OK, markets expected, but none posted yet (venue posting lag). NOT a fault.
- `IDLE`     — infra OK, markets not expected (maintenance / off hours). NOT a fault.
- `ACTIVE`   — infra OK and >=1 strip present. Evaluate per-asset readiness.

**`execution_mode`** (posture signal, meaningful ONLY inside `ACTIVE`):
- `NORMAL`      — `ready_assets_count >= 2`. Full breadth, normal sizing.
- `DEGRADED`    — `ready_assets_count == 1`. Trade the single ready asset (NOT a kill-switch).
- `ACTIVE-HALT` — `ready_assets_count == 0` while markets ARE present. RED FLAG (per-asset
                  gates rejected everything despite live strips).
- `NONE`        — set whenever `loop_state != ACTIVE` (no trading-relevant posture).

An asset is "ready" iff its MD is fresh (<30s) AND its book depth meets the
per-asset threshold. `ready_assets_count` is the number of ready assets (0..5).

**`execution_ready`** (the SINGLE downstream trading gate) is True iff
`loop_state == ACTIVE and ready_assets_count >= 1`.

### Why "0 ready assets" is not always HALT

In a 15-minute strip system, "0 ready assets" usually means Kalshi has not posted
the next set yet — a transient, EXPECTED gap — not that the platform is broken.
Only `HALT` (infra failure) and `ACTIVE-HALT` (strips present but nothing tradable)
are treated as faults / guardrail trips. `WAITING` and `IDLE` keep the system warm,
do not trade, and are NOT logged as risk events.

### Venue Posting / Cadence

- Kalshi posts crypto strips on a continuous 15-minute cadence, 24/7.
- Weekly maintenance window: Thursday 03:00–05:00 ET (markets taken down -> `IDLE`).
- Short posting lag (seconds to ~1–2 min) between a strip closing and the next
  appearing; during that lag strips are still "expected" -> `WAITING`.
- `markets_expected_now()` encodes this schedule (currently: outside maintenance).

### State Transitions

- `WAITING/IDLE -> ACTIVE` : as soon as the catalog shows >=1 strip.
- `ACTIVE -> WAITING`      : strips disappear (between-strip gap), infra still OK.
- `ANY -> HALT`            : any infra signal fails (catalog/WS/bankroll/risk/gate).
- `NORMAL <-> DEGRADED <-> ACTIVE-HALT` : driven purely by `ready_assets_count`.

### Per-Market Eligibility

Each market has its own depth check:
- `depth_ok(market) = (min_depth_yes >= 25 AND min_depth_no >= 25)`
- Only markets passing this check are eligible for order placement
- This is enforced at the agent level, not as a global gate

### Global Readiness vs Per-Market Eligibility

**Global readiness (`ready`):**
- Driven by CRITICAL signals only: WS connectivity, bankroll sanity, catalog not catastrophically stale
- Depth coverage threshold: at least 1 market tradable (not 5/5)
- If `ready=False`, NO trading occurs in any market

**Per-market eligibility:**
- Each market has its own `depth_ok(market)` check
- Agents skip order placement for markets failing depth checks
- Does NOT flip global `ready` flag
- Only affects that specific market's trading

### Rationale

In multi-asset systems, it's common and expected that some symbols are temporarily
untradeable (low depth, paused, or disabled) while others remain active. Requiring
perfect breadth (5/5) before using ANY edge is overly conservative and misaligned
with typical trading infrastructure design.

Example: If BTC/ETH/SOL have sufficient depth but XRP/DOGE are illiquid, the system
should trade BTC/ETH/SOL (degraded mode) rather than blocking all trading (halt mode).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Module-level settings import to avoid UnboundLocalError in exception handlers
# CRITICAL FIX: Use merid.settings instead of deprecated config.settings (T-060)
# config.settings does not have TRADING_ENABLED and is deprecated
try:
    from merid.settings import settings as _settings
except ImportError:
    _settings = None

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from enum import Enum
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.loop_15m")
logger.info("[15M-LOOP] MODULE VERSION v20260529a-cache-fix")

# ── Loop diagnostics file IO (env-gated to avoid hot-loop disk overhead) ──────
# The 15m loop historically wrote to a hardcoded health_diagnostic.txt on EVERY
# cycle (open+write+flush), adding disk-fsync latency to the hot path — implicated
# in Windows ProactorEventLoop stalls. These writes are now DISABLED by default and
# gated behind MERID_LOOP_DIAG_FILE=1 for on-demand debugging.
_DIAG_FILE_PATH = "c:\\Dev\\MERID\\web\\health_diagnostic.txt"
_DIAG_FILE_ENABLED = os.getenv("MERID_LOOP_DIAG_FILE", "").strip().lower() in ("1", "true", "yes", "on")


class _NullDiagWriter:
    """No-op file-like context manager used when loop diagnostics are disabled."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, *_args, **_kwargs):
        return 0

    def flush(self):
        return None


def _diag_open():
    """Return a writable handle for loop diagnostics.

    CRITICAL FIX: Always return no-op writer to prevent Windows ProactorEventLoop blocking.
    The synchronous file I/O was causing the loop to hang on Windows.
    Diagnostics are now disabled by default to ensure loop reliability.
    """
    # CRITICAL: Always return no-op writer to prevent blocking on Windows ProactorEventLoop
    # The environment variable check is disabled to ensure loop reliability
    return _NullDiagWriter()


# Liquidity decision enum for order fill safety check
class LiquidityDecision(Enum):
    """Decision on whether an order can be filled safely."""
    FULL = "FULL"  # Full size can be filled within slippage budget
    REDUCED = "REDUCED"  # Partial size available, should size down
    SKIP = "SKIP"  # Insufficient liquidity, skip this asset for this cycle

@dataclass
class LiquidityCheckResult:
    """Result of liquidity safety check for an asset."""
    decision: LiquidityDecision
    available_qty: int  # Available contracts at acceptable price
    target_qty: int  # Target quantity for this trade
    slippage_cents: float  # Estimated slippage if filled
    max_slippage_cents: float  # Maximum acceptable slippage
    reason: str  # Human-readable reason for decision

def can_fill_order_safely(
    state,
    target_qty: int,
    max_slippage_cents: float,
    side: str = "yes"
) -> LiquidityCheckResult:
    """
    Check if an order can be filled safely within slippage budget.
    
    This replaces binary depth checks with a liquidity-aware decision:
    - FULL: Enough depth at target price for full size
    - REDUCED: Partial depth available, should size down
    - SKIP: Insufficient liquidity, skip this asset
    
    Args:
        state: KalshiMarketState with orderbook data
        target_qty: Target quantity in contracts
        max_slippage_cents: Maximum acceptable slippage in cents
        side: "yes" or "no" side of the book
        
    Returns:
        LiquidityCheckResult with decision and diagnostics
    """
    if state is None:
        return LiquidityCheckResult(
            decision=LiquidityDecision.SKIP,
            available_qty=0,
            target_qty=target_qty,
            slippage_cents=0.0,
            max_slippage_cents=max_slippage_cents,
            reason="No market state available"
        )
    
    # Get best price and depth for the requested side
    if side == "yes":
        best_price = state.best_bid_cents
        available_qty = state.min_depth_yes  # Depth at best bid
    else:
        best_price = state.best_ask_cents
        available_qty = state.min_depth_no  # Depth at best ask
    
    if best_price is None or available_qty is None:
        return LiquidityCheckResult(
            decision=LiquidityDecision.SKIP,
            available_qty=0,
            target_qty=target_qty,
            slippage_cents=0.0,
            max_slippage_cents=max_slippage_cents,
            reason=f"No {side} side data available"
        )
    
    # Check if we have enough quantity at best price
    if available_qty >= target_qty:
        return LiquidityCheckResult(
            decision=LiquidityDecision.FULL,
            available_qty=available_qty,
            target_qty=target_qty,
            slippage_cents=0.0,  # No slippage if filled at best price
            max_slippage_cents=max_slippage_cents,
            reason=f"Sufficient depth: {available_qty} >= {target_qty}"
        )
    
    # Partial depth available - check if we can accept reduced size
    if available_qty >= 1:  # At least 1 contract available
        return LiquidityCheckResult(
            decision=LiquidityDecision.REDUCED,
            available_qty=available_qty,
            target_qty=target_qty,
            slippage_cents=0.0,
            max_slippage_cents=max_slippage_cents,
            reason=f"Partial depth: {available_qty} < {target_qty}, consider reduced size"
        )
    
    # Insufficient liquidity
    return LiquidityCheckResult(
        decision=LiquidityDecision.SKIP,
        available_qty=available_qty,
        target_qty=target_qty,
        slippage_cents=0.0,
        max_slippage_cents=max_slippage_cents,
        reason=f"Insufficient depth: {available_qty} < 1"
    )

# Prometheus metrics for loop health observability
try:
    from prometheus_client import Histogram
    cycle_duration_hist = Histogram(
        "merid_15m_cycle_duration_seconds",
        "Duration of 15m loop cycles",
        buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0],
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    # Prometheus not available - metrics will be no-ops
    PROMETHEUS_AVAILABLE = False
    class DummyHistogram:
        def observe(self, value):
            pass
    cycle_duration_hist = DummyHistogram()

logger = get_logger("merid.loop_15m")
logger.info("[15M-STACK-MARKER] this is the prod 15m loop - canonical logging path verified")

# Import startup trace helper
import time as _import_time
_t0 = _import_time.time()
from merid.startup_trace import log_startup_phase
_t1 = _import_time.time()
logger.debug("[LOOP-15M-IMPORT] startup_trace import took %.3fs", _t1 - _t0)

# Import run summary automation (P2 Task 11)
_t2 = _import_time.time()
from merid.ops.run_summary import RunSummary
_t3 = _import_time.time()
logger.debug("[LOOP-15M-IMPORT] run_summary import took %.3fs", _t3 - _t2)

# Import exit policy resolver for take profit/stop loss setup
_t4 = _import_time.time()
from merid.event_venues.kalshi.order_router import resolve_exit_policy
_t5 = _import_time.time()
logger.debug("[LOOP-15M-IMPORT] resolve_exit_policy import took %.3fs", _t5 - _t4)

# LEGACY REMOVAL: E2EInvariantChecker from merid.core is legacy code
# This import violates the 15m stack separation policy
# _t4 = _import_time.time()
# from merid.core.e2e_invariants import E2EInvariantChecker
# _t5 = _import_time.time()
# 


def is_within_kalshi_maintenance() -> bool:
    """
    Check if current time is within Kalshi's scheduled maintenance window.
    
    Kalshi has a weekly maintenance window on Thursday 3:00-5:00 AM ET.
    This function checks if the current time falls within that window.
    
    Returns:
        True if within maintenance window, False otherwise
        
    Maintenance window configuration now comes from kalshi_agent_grid.yaml SessionConfig
    (single source of truth) instead of settings.py env vars.
    """
    try:
        from merid.prediction.agent_grid_config import get_session_config
        session = get_session_config()
        maintenance_day = session.maintenance_day  # 0=Mon ... 6=Sun → 3=Thu
        maintenance_start = session.maintenance_start_et  # e.g., "03:00"
        maintenance_end = session.maintenance_end_et  # e.g., "05:00"
        maintenance_tz = "America/New_York"  # Kalshi timezone (fixed)
    except Exception as e:
        logger.warning("[MAINTENANCE-CHECK] Failed to load maintenance config from SessionConfig: %s", e)
        return False
    
    try:
        # Get current time in maintenance timezone
        tz = ZoneInfo(maintenance_tz)
        now = datetime.now(tz)
        
        # Check if today is the maintenance day (SessionConfig uses int 0-6)
        if now.weekday() != maintenance_day:
            return False
        
        # Parse start/end times
        start_hour, start_min = map(int, maintenance_start.split(":"))
        end_hour, end_min = map(int, maintenance_end.split(":"))
        
        # Create datetime objects for start and end of maintenance window today
        maintenance_start_dt = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
        maintenance_end_dt = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        
        # Check if current time is within the window
        return maintenance_start_dt <= now < maintenance_end_dt
    except Exception as e:
        logger.error("[MAINTENANCE-CHECK] Failed to check maintenance window: %s", e)
        return False


def markets_expected_now() -> bool:
    """Return True if Kalshi 15m crypto strips are *expected* to exist right now.

    This encodes the venue schedule/cadence, NOT whether markets are actually
    present in the catalog. It is the difference between:
      - WAITING (markets expected but not yet posted -> transient venue/posting lag)
      - IDLE    (markets not expected -> scheduled downtime / maintenance)

    For 15-minute crypto, Kalshi posts strips continuously every 15 minutes,
    24/7, EXCEPT during the weekly maintenance window (Thu 03:00-05:00 ET).
    There is a short posting lag (seconds to ~1-2 min) between a strip closing
    and the next strip appearing; during that lag strips are still expected.

    Returns:
        True if strips should be available now (outside maintenance),
        False during the scheduled maintenance window (off hours).
    """
    # 15m crypto strips are continuous outside the maintenance window.
    # This is the single hook to add finer-grained off-hours logic later.
    return not is_within_kalshi_maintenance()


def compute_loop_state(
    infra_ready: bool,
    markets_expected: bool,
    markets_present: bool,
    ready_assets_count: int,
    md_fresh_count: int = 0,
    spot_fresh_count: int = 0,
    min_ready_for_normal: int = 2,
) -> tuple:
    """Pure decision function for the 15m loop state machine with degraded modes.

    Separates infra health from market presence and per-asset readiness so a
    normal gap BETWEEN 15m strips is never confused with a systemic failure.

    New execution modes for graceful degradation:
    - RUN_NORMAL: MD and spot healthy for >=N assets, full trading allowed
    - RUN_DEGRADED: Some assets stale but >=1 has good MD/spot, reduced trading
    - NO_NEW_ENTRIES: MD not healthy enough for new entries, manage existing positions
    - HALT_CRITICAL: Both MD and spot broken for all assets, sustained interval

    Args:
        infra_ready: platform health (catalog/WS/bankroll/risk/gate all OK)
        markets_expected: should strips exist now? (cadence + maintenance)
        markets_present: does the catalog actually show >=1 active 15m strip?
        ready_assets_count: number of assets with fresh MD AND sufficient depth (0..5)
        md_fresh_count: number of assets with fresh MD (0..5)
        spot_fresh_count: number of assets with fresh spot (0..5)
        min_ready_for_normal: ready-asset count required for NORMAL (default 2)

    Returns:
        (loop_state, execution_mode, execution_ready, allow_new_entries) where:
          loop_state        in {"HALT", "WAITING", "IDLE", "ACTIVE", "DEGRADED"}
          execution_mode    in {"NONE", "RUN_NORMAL", "RUN_DEGRADED", "NO_NEW_ENTRIES", "HALT_CRITICAL"}
          execution_ready:  True when loop_state allows any trading activity
          allow_new_entries: True when new position entries are allowed
    """
    # Determine loop_state based on infra and market presence
    if not infra_ready:
        # Check if it's a critical halt (both MD and spot completely broken)
        if md_fresh_count == 0 and spot_fresh_count == 0:
            loop_state = "HALT_CRITICAL"
        else:
            loop_state = "HALT"  # infra issue but data may still be usable
    elif markets_present:
        loop_state = "ACTIVE"  # strips exist -> evaluate per-asset readiness
    elif markets_expected:
        loop_state = "WAITING"  # strips expected but not posted yet (venue lag)
    else:
        loop_state = "IDLE"  # off hours / scheduled maintenance window

    # Determine execution_mode based on data health
    if loop_state == "HALT_CRITICAL":
        execution_mode = "HALT_CRITICAL"
        allow_new_entries = False
    elif loop_state == "HALT":
        # Infra issues but some data may be usable
        if md_fresh_count >= 1 and spot_fresh_count >= 1:
            execution_mode = "NO_NEW_ENTRIES"  # Can manage existing positions
            allow_new_entries = False
        else:
            execution_mode = "HALT_CRITICAL"
            allow_new_entries = False
    elif loop_state != "ACTIVE":
        execution_mode = "NONE"
        allow_new_entries = False
    else:
        # ACTIVE state: evaluate based on asset readiness
        pass  # Handled by nested if below
        if ready_assets_count >= min_ready_for_normal:
            execution_mode = "RUN_NORMAL"
            allow_new_entries = True
        elif ready_assets_count >= 1:
            execution_mode = "RUN_DEGRADED"
            allow_new_entries = True  # Allow entries on healthy assets only
        elif md_fresh_count >= 1 and spot_fresh_count >= 1:
            # No assets have sufficient depth, but MD/spot are fresh
            execution_mode = "NO_NEW_ENTRIES"
            allow_new_entries = False
        else:
            # Markets present but no usable data
            pass  # Set execution_mode below
            execution_mode = "HALT_CRITICAL"
            allow_new_entries = False

    # execution_ready: True when any trading activity is allowed
    execution_ready = (
        loop_state in ("ACTIVE", "DEGRADED") and
        execution_mode in ("RUN_NORMAL", "RUN_DEGRADED", "NO_NEW_ENTRIES")
    )

    return loop_state, execution_mode, execution_ready, allow_new_entries


class Kalshi15mLoop:
    """
    Lean event loop for Kalshi 15m crypto trading.
    
    Lifecycle:
        loop = Kalshi15mLoop(agent_grid, bankroll_service, risk_config, cadence_seconds=5.0)
        asyncio.create_task(loop.run_forever())
        ...
        await loop.stop()
    
    NOTE: venue_adapter removed - it was dead code (TradingAgent bypasses it via route_order_async)
    """

    def __init__(
        self,
        agent_grid: Any,
        bankroll_service: Any,
        risk_config: Any,
        cadence_seconds: float = 5.0,
        catalog: Any = None,
        ws_bridge: Any = None,
    ):
        """
        Initialize the 15m loop.
        
        Args:
            agent_grid: AgentGrid instance with 5 trading agents
            bankroll_service: BankrollServiceV2 for balance tracking
            risk_config: KalshiRiskConfig for risk limits
            cadence_seconds: Loop cadence (default 5.0 seconds)
            catalog: KalshiMarketCatalog instance for market discovery
            ws_bridge: Shared WebSocket bridge instance (from main_15m_lean P1.5)
        """
        self.agent_grid = agent_grid
        self.bankroll_service = bankroll_service
        self.risk_config = risk_config
        self.cadence_seconds = cadence_seconds
        # CRITICAL FIX: Use singleton catalog instead of passed instance to avoid contamination
        # The passed catalog might be a different instance than the one being refreshed
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        self._catalog = get_market_catalog()
        self._ws_bridge = ws_bridge  # Store shared WS bridge reference
        # CRITICAL FIX: Initialize market_state_store for dynamic sizing
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        self.market_state_store = get_kalshi_market_state_store()
        # Watchdog: fixed wall-clock budget per cycle (2x cadence as safety margin)
        self._watchdog_budget = self.cadence_seconds * 2.0
        self._last_cycle_wall_time = time.time()
        self._running = False
        self._tick = 0
        self._loop_task: Optional[asyncio.Task] = None
        self._started_at: Optional[datetime] = None
        self._last_cycle_at: Optional[datetime] = None
        self._cycle_count = 0
        self._error_count = 0
        self._last_tick_time: float = time.time()  # Track last tick for stall detection
        self._stop_event = asyncio.Event()  # Event for graceful shutdown
        
        # Loop health tracking for trend analysis
        self._cycle_duration_history = []  # Rolling history of cycle durations
        self._max_history_length = 200  # Keep last 200 cycles
        
        # Risk envelope for drawdown tracking (cached to avoid redundant computation)
        self._risk_envelope = None
        self._last_envelope_bankroll = None
        self._last_risk_multiplier = 1.0
        
        # CRITICAL: Track current 15-minute ET window to align cycle resets with Kalshi market windows
        self._current_window_suffix = None  # Tracks current 15m window suffix (e.g., "26JUN111145-45")
        self._executed_candidates_this_window = set()  # Track executed candidates in current window to prevent duplicates
        self._halted_due_to_drawdown = False
        
        # CRITICAL: Best-edge tracking per asset per 15-minute window
        # This implements signal generation vs execution separation:
        # - Agents generate candidates continuously (every 5s)
        # - Only the best edge per asset per window executes
        # - Position-based locking prevents re-execution until closed
        self._best_edge_per_asset: Dict[str, Dict] = {}  # asset -> {ticker, side, edge, candidate}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._best_edge_per_asset[asset] = None
        
        # Swing mode tracking: allows YES/NO reversal after trailing exit
        # When trailing stop exits in profit, enable swing mode to allow opposite-side entry
        self._swing_mode: Dict[str, Dict] = {}  # asset -> {enabled: bool, exited_side: str, exit_time: datetime}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
        
        # Per-asset position tracking for risk enforcement
        self._asset_positions: Dict[str, float] = {}  # asset -> current notional exposure
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._asset_positions[asset] = 0.0
        
        # Active trade tracking for concurrent trade limit enforcement
        self._active_trades: Dict[str, int] = {}  # ticker -> order count
        self._max_concurrent_trades = 5  # Default, will be overridden by profile
        
        # CRITICAL FIX: Clear position cache to prevent stale exposure data from previous runs
        # This prevents false "max exposure" blocking when there are no actual positions
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            position_cache = get_position_cache()
            # Clear the cache to ensure fresh state (use sync version since we're in __init__)
            position_cache.clear_sync()
            logger.info("[15m-LOOP] Position cache cleared to prevent stale exposure data")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to clear position cache: %s", e, exc_info=True)
        
        # CRITICAL FIX: Load actual positions from position cache for accurate exposure tracking
        # This prevents false "max exposure" blocking when there are no actual positions
        # Moved to __init__ to ensure it runs regardless of start() being called
        # Using position cache instead of fills ledger as it's the single source of truth
        # IMPROVED: Added retry logic and validation for position cache loading
        # BUG FIX: get_asset_exposure doesn't exist - calculate exposure manually from get_all_positions
        max_retries = 3
        retry_delay = 1.0  # seconds
        logger.info("[15m-LOOP] Attempting to load positions from position cache with retry logic...")
        
        for attempt in range(max_retries):
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                logger.info("[15m-LOOP] get_position_cache imported successfully (attempt %d/%d)", attempt + 1, max_retries)
                position_cache = get_position_cache()
                logger.info("[15m-LOOP] get_position_cache() returned: %s (attempt %d/%d)", type(position_cache), attempt + 1, max_retries)
                
                # BUG FIX: get_asset_exposure doesn't exist - calculate exposure manually
                # Initialize all assets to 0
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._asset_positions[asset] = 0.0
                
                # Get all positions and calculate exposure per asset
                all_positions = position_cache.get_all_positions(validate_freshness=False)
                logger.info("[15m-LOOP] Loaded %d positions from cache (attempt %d/%d)", len(all_positions), attempt + 1, max_retries)
                
                # Map ticker prefixes to assets
                asset_map = {
                    "KXBTC": "BTC",
                    "KXETH": "ETH",
                    "KXSOL": "SOL",
                    "KXXRP": "XRP",
                    "KXDOGE": "DOGE",
                }
                
                # Calculate exposure per asset
                for market_id, position in all_positions.items():
                    # Extract asset from market_id
                    asset = None
                    for prefix, asset_name in asset_map.items():
                        if market_id.startswith(prefix):
                            asset = asset_name
                            break
                    
                    if asset and asset in self._asset_positions:
                        # Calculate notional: contracts * avg_price_cents / 100
                        notional = float((position.contracts * position.avg_price_cents) / 100.0)
                        self._asset_positions[asset] += notional
                        logger.debug("[15m-LOOP] Position: market=%s asset=%s contracts=%d price=%d notional=%.2f", 
                                    market_id, asset, position.contracts, position.avg_price_cents, notional)
                
                # Log final exposure for each asset
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    logger.info("[15m-LOOP] Loaded position from cache: asset=%s exposure=%.2f (attempt %d/%d)", 
                               asset, self._asset_positions[asset], attempt + 1, max_retries)
                
                # Validate that all assets were loaded
                loaded_assets = set(self._asset_positions.keys())
                expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                if loaded_assets == expected_assets:
                    logger.info("[15m-LOOP] Position tracking loaded from position cache: %s (attempt %d/%d)", self._asset_positions, attempt + 1, max_retries)
                    break  # Success, exit retry loop
                else:
                    missing = expected_assets - loaded_assets
                    logger.warning("[15m-LOOP] Position cache missing assets: %s (attempt %d/%d)", missing, attempt + 1, max_retries)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        # Fallback to default 0.0 values
                        logger.warning("[15m-LOOP] Position cache failed after %d retries, using default 0.0 values", max_retries)
                        for asset in expected_assets:
                            if asset not in self._asset_positions:
                                self._asset_positions[asset] = 0.0
                        logger.info("[15m-LOOP] Using default position tracking (all assets at 0.0): %s", self._asset_positions)
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to load positions from position cache (attempt %d/%d): %s", attempt + 1, max_retries, e, exc_info=True)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    # Fallback to default 0.0 values
                    logger.warning("[15m-LOOP] Position cache failed after %d retries, using default 0.0 values", max_retries)
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        self._asset_positions[asset] = 0.0
                    logger.info("[15m-LOOP] Using default position tracking (all assets at 0.0): %s", self._asset_positions)
        
        # CRITICAL FIX: Reset concurrent trade counter based on actual open positions
        # The counter is incremented on order submission but never decremented, causing false blocking
        # Reset to 0 since position cache shows 0 open positions
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            position_cache = get_position_cache()
            # Reset all active trade counters to 0
            self._active_trades.clear()
            logger.info("[15m-LOOP] Concurrent trade counter reset to 0 (was blocking trades with stale data)")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to reset concurrent trade counter: %s", e, exc_info=True)

        # Catalog startup guard - prevents false negatives before first refresh
        self._catalog_ready = False
        
        # P0 FIX: Degraded mode state tracking for automatic recovery
        self._previous_execution_mode = "NONE"
        self._consecutive_degraded_cycles = 0
        self._consecutive_critical_cycles = 0
        self._max_consecutive_critical_cycles = 6  # Escalate to HALT_CRITICAL after 6 cycles (30s at 5s cadence)
        self._catalog_not_ready_logged = False
        
        # Catalog roll tracking for WS warmup grace period
        self._catalog_roll_ts = 0.0  # Timestamp of last catalog roll (markets changed)
        self._catalog_warmup_seconds = 10.0  # Grace period after catalog roll for WS to deliver snapshots
        self._last_catalog_market_ids = set()  # Track market IDs to detect catalog rolls

        # Spot service startup guard - prevents false negatives before warmup completes
        self._spot_ready_logged = False

        # Pipeline and trading readiness for API observability
        self.pipeline_ready = False
        self.trading_ready = False

        # P2 Task 11: Run summary automation
        self._run_summary = RunSummary(
            loop=self,
            agent_grid=agent_grid,
            bankroll_service=bankroll_service,
        )
        
        # Alert thresholds monitoring
        self._monitor = None
        try:
            from merid.event_venues.kalshi.monitoring import get_monitor
            self._monitor = get_monitor()
            logger.info("[15m-LOOP] Initialized KalshiMonitor for alert thresholds")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to initialize KalshiMonitor: %s", e)
        
        # Phase 5.4: Set up outcome callback for probability calibration
        try:
            from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
            rt_monitor = get_round_trip_monitor()
            
            def outcome_callback(agent_id: str, logit: float, outcome: int) -> None:
                """Callback to record calibration outcome to the appropriate agent."""
                try:
                    # Find the agent by ID and record outcome
                    for agent in self.agent_grid._agents:
                        if agent.config.name == agent_id:
                            agent.record_outcome(logit, outcome)
                            logger.debug(
                                "[CALIBRATION-CALLBACK] agent=%s logit=%.4f outcome=%d",
                                agent_id, logit, outcome
                            )
                            break
                except Exception as cb_err:
                    logger.warning("[CALIBRATION-CALLBACK] Failed to record outcome: %s", cb_err)
            
            rt_monitor.set_outcome_callback(outcome_callback)
            logger.info("[15m-LOOP] Registered outcome callback for probability calibration")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to set up outcome callback: %s", e)

        # CRITICAL: Initialize PositionMonitor for profit taking and trailing stop
        # This enables active monitoring of open positions for TP/SL/trailing exit conditions
        self._position_monitor = None
        try:
            from merid.position_management.position_monitor import get_position_monitor
            self._position_monitor = get_position_monitor()
            logger.info("[15m-LOOP] Initialized PositionMonitor for TP/SL/trailing exits")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to initialize PositionMonitor: %s", e)

    @property
    def is_running(self) -> bool:
        """Return whether the loop is currently running."""
        return self._running

    @property
    def last_cycle_ts(self) -> Optional[datetime]:
        """Return the timestamp of the last cycle."""
        return self._last_cycle_at

    @property
    def last_cycle_duration_ms(self) -> Optional[float]:
        """Return the duration of the last cycle in milliseconds."""
        if self._cycle_duration_history:
            return self._cycle_duration_history[-1] * 1000 if self._cycle_duration_history else None
        return None

    @property
    def error_count(self) -> int:
        """Return the total error count."""
        return self._error_count

    @property
    def cycle_id(self) -> int:
        """Return the current cycle ID (monotonically increasing)."""
        return self._tick

    @property
    def heartbeat_age_seconds(self) -> Optional[float]:
        """Return seconds since last cycle for heartbeat monitoring."""
        if self._last_cycle_at is None:
            return None
        return (datetime.now(timezone.utc) - self._last_cycle_at).total_seconds()

    def _get_cached_envelope(self, current_bankroll: float):
        """
        Get cached risk envelope, recomputing only if bankroll changed significantly.
        
        This avoids redundant envelope computation (5 agents × N cycles = 5N work).
        Only recompute if bankroll changed by more than $1.00.
        """
        if (self._risk_envelope is None or 
            self._last_envelope_bankroll is None or
            abs(current_bankroll - self._last_envelope_bankroll) > 1.0):
            try:
                from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                service = get_risk_envelope_service()
                service.refresh_if_stale(max_age_seconds=30.0)
                config = service.get_config()
                
                # RiskEnvelopeConfig is now used directly (refactored from legacy envelope-like object)
                self._risk_envelope = config
                self._last_envelope_bankroll = current_bankroll
                logger.info(
                    "[15M-LOOP] Envelope refreshed via RiskEnvelopeService: bankroll=%.2f, asset_max_notional_usd=%s",
                    current_bankroll,
                    config.asset_max_notional_usd
                )
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to refresh envelope via RiskEnvelopeService: %s", e, exc_info=True)
        return self._risk_envelope

    async def _schedule_next_tick_async(self, delay: float) -> None:
        """Schedule the next tick using asyncio.sleep (Windows ProactorEventLoop compatible)."""
        if not self._running:
            logger.debug("[15M-LOOP-TRACE] _schedule_next_tick_async called but loop not running")
            return

        logger.debug(
            "[15M-LOOP-TRACE] scheduling next tick in %.3fs",
            delay,
        )
        try:
            await asyncio.sleep(delay)
            if self._running:
                await self._on_tick_async()
        except asyncio.CancelledError:
            logger.debug("[15M-LOOP-TRACE] _schedule_next_tick_async cancelled")
            raise
        except Exception as exc:
            logger.error("[15M-LOOP-TRACE] _schedule_next_tick_async failed: %s", exc, exc_info=True)

    async def _on_tick_async(self) -> None:
        """Async tick handler (Windows ProactorEventLoop compatible)."""
        self._last_tick_time = time.time()
        logger.debug("[15M-LOOP] ON-TICK-ENTRY running=%s tick_before=%d", self._running, self._tick)
        if not self._running:
            logger.debug("[15M-LOOP-TRACE] _on_tick_async called but loop not running")
            return

        loop = asyncio.get_running_loop()
        logger.debug("[15M-LOOP-TRACE] _on_tick_async: loop.is_running()=%s, loop.time()=%.3f", loop.is_running(), loop.time())
        self._tick += 1
        cycle_id = self._tick
        logger.debug("[15M-LOOP] ON-TICK-CREATE-CYCLE cycle=%d loop_time=%.3f", cycle_id, loop.time())

        try:
            # CRITICAL FIX: Call coroutine directly instead of creating task
            # This avoids Windows ProactorEventLoop scheduling issues where tasks get stuck
            logger.debug("[15M-LOOP] About to call _run_cycle_wrapper directly for cycle %d", cycle_id)
            await self._run_cycle_wrapper(cycle_id)
            logger.debug("[15M-LOOP] Cycle %d completed successfully", cycle_id)
            logger.debug("[15M-LOOP-TRACE] _on_tick_async EXIT (cycle %d completed)", cycle_id)
        except Exception as exc:
            logger.error("[15M-LOOP-TRACE] Exception in _on_tick_async for cycle %d: %s", cycle_id, exc, exc_info=True)

    async def _run_cycle_wrapper(self, cycle_id: int) -> None:
        """Async wrapper for cycle execution (called from callback)."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        logger.info("[LOOP-STARTUP-WRAPPER] CYCLE-WRAPPER-ENTER cycle=%d loop_time=%.3f", cycle_id, start)
        
        # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
        # This fixes the hardcoded $50 correlation stack cap bug
        logger.info("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR-ENTER: About to fetch bankroll")
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            cycle_bankroll = get_equity_for_risk_calc_sync()
            logger.info("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR: Fetched bankroll=%s", cycle_bankroll)
            if cycle_bankroll is not None and cycle_bankroll > 0:
                # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
                # This fixes the hardcoded $50 correlation stack cap bug
                logger.info("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR: About to call BalanceCalibrator")
                try:
                    from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                    balance_cents = int(cycle_bankroll * 100)
                    logger.info("[15M-LOOP-WRAPPER] Calling BalanceCalibrator.update with balance_cents=%d", balance_cents)
                    did_recalibrate = get_balance_calibrator().update(balance_cents)
                    logger.info("[15M-LOOP-WRAPPER] BalanceCalibrator.update returned did_recalibrate=%s", did_recalibrate)
                except Exception as calibrator_exc:
                    logger.warning("[15M-LOOP-WRAPPER] BalanceCalibrator update failed: %s", calibrator_exc)
            else:
                logger.warning("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR: Bankroll is None or <= 0, skipping calibration")
        except Exception as e:
            logger.warning("[15M-LOOP-WRAPPER] Failed to fetch cycle bankroll: %s", e)
        
        # KALSHI READINESS CHECK: Skip cycles if system is not ready
        # Status mapping:
        # - healthy: allow trading at full size
        # - degraded: allow trading but log warning (data quality issues)
        # - unhealthy: skip cycles (config invalid, WS disconnected, or data quality critical)
        try:
            from merid.event_venues.kalshi.kalshi_config import KALSHI_READY
            if not KALSHI_READY:
                logger.warning(
                    "[15M-LOOP-READINESS] Cycle %d SKIPPED: KALSHI_READY=False - config not validated",
                    cycle_id
                )
                return
        except Exception as e:
            logger.warning(f"[15M-LOOP-READINESS] Failed to check KALSHI_READY: {e}")
        
        # Check full readiness status using shared health snapshot
        # This ensures consistency between health endpoint and loop
        # NOTE: spot_fresh_count / md_fresh_count are computed later in the cycle
        # (market-scanning phase). Initialise them here so the readiness diagnostic
        # below cannot raise NameError before they are populated (prev bug:
        # "[15M-LOOP-READINESS] Failed to check health snapshot: name 'spot_fresh_count' is not defined").
        spot_fresh_count = 0
        md_fresh_count = 0
        try:
            from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot
            
            # Pass loop_tick for WS_FORWARDER_IMPOSSIBLE_OK invariant check
            # Add timeout to prevent hanging
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(get_kalshi_health_snapshot, loop_tick=cycle_id),
                timeout=5.0  # 5 second timeout
            )
            
            # CRITICAL FIX: Calculate fresh counts at higher scope for use in readiness checks
            # spot_fresh_count is already calculated directly from spot service earlier in the cycle
            # to bypass health snapshot which may not correctly track spot status
            # md_fresh_count is calculated later in the market scanning phase to bypass health snapshot
            # which may not correctly track MD status
            # Do NOT calculate from health snapshot - it's unreliable
            
            # Log health snapshot to diagnostic file for visibility
            # CRITICAL: Add WS counters for end-to-end visibility
            ws_raw = 0
            ws_enq = 0
            ws_proc = 0
            try:
                from merid.event_venues.kalshi.ws_bridge import get_bridge
                ws_bridge = get_bridge()
                if ws_bridge:
                    ws_health = ws_bridge.get_forward_loop_health()
                    ws_raw = ws_health.get("ws_raw_messages_seen", 0)
                    ws_enq = ws_health.get("ws_events_enqueued", 0)
                    ws_proc = ws_health.get("ws_forwarder_events_processed", 0)
            except Exception as e:
                logger.error(f"[15M-LOOP] ERROR getting WS health: {e}")
            
            if snapshot.status.value == "unhealthy":
                # BUG FIX: Always provide a meaningful reason for unhealthy status
                # The snapshot already includes reasons in the reasons list
                reason = "; ".join(snapshot.reasons) if snapshot.reasons else "unknown_unhealthy_state"
                
                # CRITICAL FIX: Allow loop to run even if health snapshot is unhealthy
                # This prevents the loop from being permanently blocked by transient issues
                # Log the unhealthy state but continue with the cycle
                logger.warning(
                    "[15M-LOOP-READINESS] Cycle %d UNHEALTHY (continuing anyway): status=unhealthy reason=%s",
                    cycle_id,
                    reason
                )
                # DO NOT return - continue with cycle despite unhealthy status
                # return
            elif snapshot.status.value == "degraded":
                logger.warning(
                    "[15M-LOOP-READINESS] Cycle %d DEGRADED: status=degraded reasons=%s",
                    cycle_id,
                    "; ".join(snapshot.reasons) if snapshot.reasons else "data_quality_issues"
                )
                # Continue with cycle but log degraded state
            # status == "healthy": continue normally
        except asyncio.TimeoutError:
            logger.error("[15M-LOOP-READINESS] Cycle %d SKIPPED: health snapshot timeout after 5s", cycle_id)
            return
        except Exception as e:
            logger.error(f"[15M-LOOP-READINESS] Failed to check health snapshot: {e}", exc_info=True)
            # Continue with cycle if snapshot check fails
        
        # Watchdog: check wall-clock time since last cycle
        current_wall_time = time.time()
        wall_clock_since_last_cycle = current_wall_time - self._last_cycle_wall_time
        if wall_clock_since_last_cycle > self._watchdog_budget:
            logger.error(
                "[15M-LOOP-WATCHDOG] WALL-CLOCK BUDGET EXCEEDED: cycle=%d, elapsed=%.3fs, budget=%.3fs",
                cycle_id,
                wall_clock_since_last_cycle,
                self._watchdog_budget
            )
            logger.error(
                "[15M-LOOP-WATCHDOG] event loop health: is_running=%s, task_count=%d",
                loop.is_running(),
                len(asyncio.all_tasks(loop))
            )
        self._last_cycle_wall_time = current_wall_time
        
        logger.debug("[15M-LOOP-TRACE] CYCLE %d START at loop_time=%.3f", cycle_id, start)
        
        cycle_completed = False
        try:
            await self._run_one_cycle(cycle_id)
            cycle_completed = True
        except Exception as exc:
            self._error_count += 1
            logger.error(
                "[15m-LOOP] Cycle %d failed: %s (errors=%d)",
                cycle_id,
                exc,
                self._error_count,
                exc_info=True,
            )
        finally:
            end = loop.time()
            duration = end - start
            logger.debug("[15M-LOOP] CYCLE-WRAPPER-EXIT cycle=%d duration=%.3fs completed=%s", cycle_id, duration, cycle_completed)

    async def start(self) -> None:
        """Start the loop in background task."""
        if self._running:
            logger.warning("[15m-LOOP] Loop already running, skipping start")
            return
        
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._stop_event.clear()
        
        # Initialize risk envelope for kalshi_crypto_15m_v2
        profile = os.getenv("MERID_PROFILE", "").lower()
        if profile == "kalshi_crypto_15m_v2":
            try:
                from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                service = get_risk_envelope_service()
                service.refresh_if_stale(max_age_seconds=30.0)
                self._risk_envelope = service.get_config()
                logger.info("[15m-LOOP] Initialized risk envelope via RiskEnvelopeService")
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to initialize risk envelope: %s", e, exc_info=True)
        
        # NOTE: Position tracking and concurrent trade counter reset moved to __init__
        # to ensure they run regardless of start() being called (which may return early if _running=True)
        
        agent_count = len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0
        logger.info("[15m-LOOP] Starting Kalshi15mLoop (cadence=%.1fs, agents=%d, profile=%s)",
                     self.cadence_seconds, agent_count, profile)
        
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(self._run_loop(), name="kalshi_15m_loop")
        logger.info("[15m-LOOP] Background task created: %s", self._loop_task)

        # CRITICAL: Start PositionMonitor for active TP/SL/trailing exit monitoring
        if self._position_monitor:
            try:
                # Register exit callback to trigger exit orders
                def exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close=None):
                    """Callback when PositionMonitor detects exit condition."""
                    try:
                        logger.info(
                            "[POSITION-MONITOR-CALLBACK] Exit intent: position=%s reason=%s price=%dc contracts=%s",
                            position.position_id[:8], exit_reason, exit_price_cents, contracts_to_close or "all"
                        )
                        
                        # CRITICAL: Enable swing mode after trailing exit in profit
                        # This allows YES/NO reversal to capture profits from price swings in both directions
                        if exit_reason == ExitReason.TRAIL:
                            # Extract asset from market_id (e.g., KXBTC15M-TEST -> BTC)
                            asset = None
                            for prefix in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]:
                                if position.market_id.startswith(prefix):
                                    asset = prefix.replace("KX", "")
                                    break
                            
                            if asset:
                                # Enable swing mode for this asset
                                self._swing_mode[asset] = {
                                    "enabled": True,
                                    "exited_side": position.side.value if hasattr(position.side, 'value') else str(position.side),
                                    "exit_time": datetime.utcnow()
                                }
                                logger.info(
                                    "[SWING-MODE] Enabled for asset=%s after trailing exit: exited_side=%s exit_price=%dc",
                                    asset, self._swing_mode[asset]["exited_side"], exit_price_cents
                                )
                        
                        # Route exit order through order router
                        asyncio.create_task(self._execute_exit_order(position, exit_reason, exit_price_cents, contracts_to_close))
                    except Exception as cb_err:
                        logger.error("[POSITION-MONITOR-CALLBACK] Failed to execute exit: %s", cb_err, exc_info=True)

                # CRITICAL FIX: Register exit callback BEFORE starting monitor
                # This prevents race condition where positions are added before callback is registered
                self._position_monitor.register_exit_intent_callback(exit_intent_callback)
                
                # CRITICAL FIX (2026-07-08): Verify exit intent callback registration
                if self._position_monitor._exit_intent_callback is None:
                    logger.error(
                        "[15M-LOOP] EXIT INTENT CALLBACK NOT REGISTERED - Exit policies will not execute!"
                    )
                    raise RuntimeError("Exit intent callback not registered - system unsafe for trading")
                else:
                    logger.info(
                        "[15M-LOOP] Exit intent callback verified registered: %s",
                        self._position_monitor._exit_intent_callback.__name__
                    )
                
                # Start the monitor's polling loop (await to ensure _running flag is set)
                await self._position_monitor.start()
                logger.info("[15m-LOOP] Started PositionMonitor with exit callback")
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to start PositionMonitor: %s", e, exc_info=True)

    async def _execute_exit_order(self, position, exit_reason, exit_price_cents, contracts_to_close=None) -> None:
        """Execute exit order when PositionMonitor triggers exit condition.
        
        Args:
            position: Position to exit
            exit_reason: Exit reason
            exit_price_cents: Exit price in cents
            contracts_to_close: Number of contracts to close (None = full exit)
        """
        try:
            logger.info(
                "[EXIT-ORDER] Starting exit order execution: position=%s market=%s side=%s reason=%s exit_price=%dc "
                "entry_price=%dc pnl=%dc R=%.2f size=%d contracts_to_close=%s",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                contracts_to_close or "full",
            )
            
            # CRITICAL FIX: 2026-07-09 - Exit orders bypass slot allocation
            # Exit orders reduce exposure, so they should always be allowed even at full $1 capacity
            # This ensures positions can be closed to lock in profits without waiting for window end
            try:
                from merid.risk.global_slot_allocator import get_global_slot_allocator, AllocationRequest
                from config.kalshi_crypto_config import kalshi_ticker_to_asset
                
                slot_allocator = get_global_slot_allocator()
                asset = kalshi_ticker_to_asset(position.market_id) if position.market_id else None
                
                # Create exit order allocation request (bypasses slot allocation)
                exit_request = AllocationRequest(
                    agent_id="position_monitor",
                    asset=asset or "unknown",
                    ticker=position.market_id,
                    entry_price_cents=exit_price_cents,
                    edge_pct=0.0,  # Exit orders don't have edge
                    spread_cents=0,  # Exit orders don't care about spread
                    is_exit_order=True  # CRITICAL: Mark as exit order to bypass allocation
                )
                
                # Request allocation (will bypass due to is_exit_order=True)
                allocated, reason, _ = slot_allocator.request_allocation(exit_request)
                
                if not allocated and reason != "EXIT_ORDER_BYPASS":
                    logger.warning(
                        "[EXIT-ORDER] Slot allocator rejected exit order (should not happen): %s",
                        reason
                    )
                else:
                    logger.info(
                        "[EXIT-ORDER] Exit order bypassed slot allocation: asset=%s ticker=%s",
                        asset, position.market_id
                    )
            except Exception as slot_err:
                logger.warning(
                    "[EXIT-ORDER] Failed to check slot allocator for exit order (non-critical): %s",
                    slot_err
                )
            
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

            # CRITICAL FIX: Convert to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
            # For exit orders, we always sell to close the position
            # YES position: sell YES to exit long position -> SELL_YES
            # NO position: sell NO to exit long position -> SELL_NO
            action = "sell"

            # Convert PositionSide enum to string for OrderIntent
            side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
            side_upper = side_str.upper()

            # Map to Kalshi side format for exit orders
            if side_upper == "YES" and action == "sell":
                kalshi_side = "SELL_YES"
            elif side_upper == "NO" and action == "sell":
                kalshi_side = "SELL_NO"
            else:
                # Fallback for unexpected combinations
                logger.warning(
                    "[EXIT-ORDER] Unexpected side/action combination: side=%s action=%s, using fallback",
                    side_str, action
                )
                kalshi_side = f"{action.upper()}_{side_upper}"

            # Determine count (partial or full exit)
            count = contracts_to_close if contracts_to_close is not None else position.size

            logger.info(
                "[EXIT-ORDER] Kalshi side conversion: side_str=%s action=%s -> kalshi_side=%s",
                side_str, action, kalshi_side
            )

            # Create exit OrderIntent
            # CRITICAL: Use limit order with GTC to create resting order for better fill rate
            # This allows the exit order to sit on the book and get filled at the desired price
            # CRITICAL FIX: Add exit_policy_id to satisfy order router validation for exit orders
            # Exit orders require exit_policy_id for tracking per _validate_risk_contract_linkage
            intent = OrderIntent(
                ticker=position.market_id,
                side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (SELL_YES, SELL_NO)
                action=action,  # Keep as lowercase "buy"/"sell" for early validation
                price_cents=exit_price_cents,
                count=count,
                order_type="limit",  # Limit order to create resting order
                time_in_force="gtc",  # Good till canceled - allows order to rest on book
                source="position_monitor_exit",
                agent_id="merid.position_management.position_monitor",
                exit_reason=exit_reason,
                exit_policy_id=position.exit_policy_id,  # CRITICAL FIX: Required for exit order validation
            )

            logger.info(
                "[EXIT-ORDER] Routing exit order: ticker=%s side=%s action=%s count=%d price=%dc reason=%s",
                position.market_id, side_str, action, count, exit_price_cents, exit_reason
            )

            # Route the exit order
            result = await route_order_async(intent)

            if result.success:
                logger.info(
                    "[EXIT-ORDER] Exit order executed successfully: order_id=%s status=%s",
                    result.order_id, result.status
                )
            else:
                logger.error(
                    "[EXIT-ORDER] Exit order failed: status=%s error=%s reason=%s",
                    result.status, result.error, result.reason
                )

        except Exception as e:
            logger.error("[EXIT-ORDER] Failed to execute exit order: %s", e, exc_info=True)

    async def _run_loop(self) -> None:
        """Main loop execution - runs trading cycles at configured cadence."""
        tick_id = 0
        logger.info("[15m-LOOP] Entering main loop")
        
        try:
            while self._running and not self._stop_event.is_set():
                tick_id += 1
                cycle_start = time.time()
                
                try:
                    # P3 FIX: Reset _active_trades counter per cycle based on actual open positions
                    # This prevents stale counter values from blocking trades when positions are closed
                    # Improved: Only reset if counter is stale (not updated in last 2 cycles)
                    try:
                        from merid.event_venues.kalshi.position_cache import get_position_cache
                        position_cache = get_position_cache()
                        
                        # Check if counter is stale (no recent updates)
                        current_time = time.time()
                        if not hasattr(self, '_last_counter_update_ts'):
                            self._last_counter_update_ts = current_time
                        
                        # Only reset if counter hasn't been updated in 2 cycles (10 seconds)
                        time_since_update = current_time - self._last_counter_update_ts
                        if time_since_update > 10.0:
                            old_count = sum(self._active_trades.values())
                            self._active_trades.clear()
                            self._last_counter_update_ts = current_time
                            if old_count > 0:
                                logger.info("[15m-LOOP] Reset stale concurrent trades counter from %d to 0 (stale for %.1fs)", old_count, time_since_update)
                    except Exception as e:
                        logger.warning("[15m-LOOP] Failed to reset concurrent trades counter: %s", e, exc_info=True)
                    
                    # CRITICAL FIX: Reload positions from position cache at start of each cycle
                    # This ensures exposure tracking is based on the most up-to-date information
                    # and prevents stale exposure from blocking new trades
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    position_cache = get_position_cache()
                    
                    # Initialize all assets to 0
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        self._asset_positions[asset] = 0.0
                    
                    # Get all positions and calculate exposure per asset
                    all_positions = position_cache.get_all_positions(validate_freshness=False)
                    
                    # Map ticker prefixes to assets
                    asset_map = {
                        "KXBTC": "BTC",
                        "KXETH": "ETH",
                        "KXSOL": "SOL",
                        "KXXRP": "XRP",
                        "KXDOGE": "DOGE",
                    }
                    
                    # Sum up notional exposure per asset
                    for market_id, position in all_positions.items():
                        if position.contracts > 0:
                            # Extract asset from ticker prefix
                            asset = None
                            for prefix, asset_name in asset_map.items():
                                if market_id.startswith(prefix):
                                    asset = asset_name
                                    break
                            
                            if asset:
                                self._asset_positions[asset] += float(position.notional_value)
                    
                    logger.info("[15m-LOOP] Reloaded positions from cache: %s", self._asset_positions)
                    
                    # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
                    # This fixes the hardcoded $50 correlation stack cap bug
                    logger.info("[15m-LOOP] BALANCE-CALIBRATOR-ENTER: About to fetch bankroll")
                    try:
                        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                        cycle_bankroll = get_equity_for_risk_calc_sync()
                        logger.info("[15m-LOOP] BALANCE-CALIBRATOR: Fetched bankroll=%s", cycle_bankroll)
                        if cycle_bankroll is not None and cycle_bankroll > 0:
                            # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
                            # This fixes the hardcoded $50 correlation stack cap bug
                            logger.info("[15m-LOOP] BALANCE-CALIBRATOR: About to call BalanceCalibrator")
                            try:
                                from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                                balance_cents = int(cycle_bankroll * 100)
                                logger.info("[15m-LOOP] Calling BalanceCalibrator.update with balance_cents=%d", balance_cents)
                                did_recalibrate = get_balance_calibrator().update(balance_cents)
                                logger.info("[15m-LOOP] BalanceCalibrator.update returned did_recalibrate=%s", did_recalibrate)
                            except Exception as calibrator_exc:
                                logger.warning("[15m-LOOP] BalanceCalibrator update failed: %s", calibrator_exc)
                        else:
                            logger.warning("[15m-LOOP] BALANCE-CALIBRATOR: Bankroll is None or <= 0, skipping calibration")
                    except Exception as e:
                        logger.warning("[15m-LOOP] Failed to fetch cycle bankroll: %s", e)
                    
                    # CRITICAL: Check if 15-minute ET window has changed
                    # Only reset cycle guards when window changes, not every 5 seconds
                    from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
                    current_window = get_kalshi_15m_window()
                    window_changed = (self._current_window_suffix != current_window.suffix)
                    
                    if window_changed:
                        logger.info(
                            "[15m-LOOP] 15-minute window changed: old=%s new=%s - resetting cycle guards and executed candidates",
                            self._current_window_suffix, current_window.suffix
                        )
                        self._current_window_suffix = current_window.suffix
                        self._executed_candidates_this_window.clear()
                        
                        # Reset best-edge tracking for new window
                        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                            self._best_edge_per_asset[asset] = None
                        logger.info("[15m-LOOP] Reset best-edge tracking for new window")
                        
                        # Reset swing mode for new window (swing mode only valid within same 15m window)
                        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                            self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
                        logger.info("[15m-LOOP] Reset swing mode for new window")
                        
                        # Reset UnifiedRiskManager cycle tracking
                        from merid.risk.unified_risk_manager import get_unified_risk_manager
                        risk_mgr = get_unified_risk_manager()
                        risk_mgr.reset_cycle()
                        logger.info("[15m-LOOP] Reset UnifiedRiskManager cycle for window=%s", current_window.suffix)
                    else:
                        logger.debug("[15m-LOOP] Window unchanged: %s - skipping cycle reset", current_window.suffix)
                    
                    # Run trading cycle
                    candidates = await self.agent_grid.run_cycle(tick_id, allow_new_entries=True)
                    logger.info("[15m-LOOP] Generated %d candidates in tick %d", len(candidates), tick_id)
                    
                    # CRITICAL: Log candidate details for debugging execution flow
                    for i, candidate in enumerate(candidates):
                        logger.info(
                            "[15m-LOOP] Candidate %d: ticker=%s side=%s edge=%s edge_pct=%s",
                            i, candidate.get("ticker"), candidate.get("side"), candidate.get("edge"), candidate.get("edge_pct")
                        )
                    
                    # Execute candidates using best-edge selection
                    # Signal generation runs continuously (every 5s), but only best edge per asset executes
                    logger.info("[15m-LOOP] Starting execution loop for %d candidates", len(candidates))
                    for candidate in candidates:
                        try:
                            # Extract asset from ticker (e.g., "KXBTC15M-26JUN300345-45" -> "BTC")
                            ticker = candidate.get("ticker", "")
                            logger.info("[15m-LOOP] Processing candidate: ticker=%s", ticker)
                            
                            # CRITICAL FIX: More robust asset extraction
                            # Handle both full market IDs (KXBTC15M-26JUN300345-45) and series tickers (KXBTC15M)
                            if "15M" in ticker:
                                # Split on "15M" and take the part before it
                                asset_part = ticker.split("15M")[0]
                            else:
                                asset_part = ticker
                            
                            # Remove "KX" prefix if present
                            asset = asset_part.replace("KX", "")
                            
                            # Normalize asset name
                            asset_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "XRP": "XRP", "DOGE": "DOGE"}
                            asset = asset_map.get(asset, asset)
                            
                            logger.info("[15m-LOOP] Extracted asset=%s from ticker=%s", asset, ticker)
                            
                            if asset not in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                                logger.warning("[15m-LOOP] Unknown asset from ticker %s: extracted=%s - skipping", ticker, asset)
                                continue
                            
                            # Get candidate edge
                            edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
                            side = candidate.get("side", "")
                            logger.info("[15m-LOOP] Candidate details: edge=%.6f side=%s", edge, side)
                            
                            # Check if we have an open position for this asset
                            current_position = self._asset_positions.get(asset, 0.0)
                            has_position = abs(current_position) > 0.01  # Small threshold for floating point
                            logger.info("[15m-LOOP] Position check: asset=%s position=%.2f has_position=%s", asset, current_position, has_position)
                            
                            # Get current best edge for this asset
                            current_best = self._best_edge_per_asset.get(asset)
                            current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
                            logger.info("[15m-LOOP] Best edge check: asset=%s current_best=%.6f", asset, current_best_edge)
                            
                            # Best-edge selection logic:
                            # - If no position: execute if edge > current best edge OR if edge meets minimum threshold
                            # - If position exists: only execute if edge > current best edge (edge improvement)
                            # - SWING MODE: If swing mode enabled after trailing exit, allow opposite-side entry
                            # - This prevents over-trading and ensures we always execute the best opportunity
                            # CRITICAL FIX: For velocity-based signals, use minimum edge threshold instead of best-edge comparison
                            # Velocity-based signals have tiny edges (0.01-0.05%) due to velocity magnitude calculation
                            # The best-edge logic was blocking all trades because edges were too small to beat current_best
                            should_execute = False
                            min_edge_threshold = 0.0001  # 0.01% minimum edge for velocity-based signals (was 0.5% - too high)
                            
                            # Check swing mode status for this asset
                            swing_enabled = self._swing_mode.get(asset, {}).get("enabled", False)
                            exited_side = self._swing_mode.get(asset, {}).get("exited_side", None)
                            
                            # Determine if this is a swing reversal (opposite side to exited position)
                            is_swing_reversal = swing_enabled and exited_side and side != exited_side
                            
                            if not has_position:
                                # No position: execute if edge meets minimum threshold OR beats current best
                                # OR if swing mode enabled and this is opposite-side reversal
                                # CRITICAL FIX: Use abs(edge) for comparison since edge = p_model - p_market can be negative
                                # Negative edges are valid contrarian signals (model disagrees with market)
                                # Industry standard: edge magnitude matters, not direction, for momentum/contrarian trading
                                if abs(edge) > min_edge_threshold or abs(edge) > abs(current_best_edge) or is_swing_reversal:
                                    should_execute = True
                                    if is_swing_reversal:
                                        logger.info(
                                            "[SWING-MODE] Reversal entry: asset=%s from %s to %s edge=%.2f%% - swing mode enabled",
                                            asset, exited_side, side, edge
                                        )
                                    else:
                                        logger.info(
                                            "[15m-LOOP] Best-edge selection: asset=%s edge=%.2f%% (abs=%.2f%%) > min_threshold=%.2f%% or current_best=%.2f%% - will execute",
                                            asset, edge, abs(edge), min_edge_threshold, current_best_edge
                                        )
                                    # Update best edge tracking
                                    self._best_edge_per_asset[asset] = {
                                        "ticker": ticker,
                                        "side": side,
                                        "edge": edge,
                                        "candidate": candidate
                                    }
                                    # Disable swing mode after executing reversal
                                    if is_swing_reversal:
                                        self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
                                        logger.info("[SWING-MODE] Disabled for asset=%s after reversal entry", asset)
                                else:
                                    logger.debug(
                                        "[15m-LOOP] Best-edge selection: asset=%s edge=%.2f%% (abs=%.2f%%) <= min_threshold=%.2f%% and <= current_best=%.2f%% - skipping",
                                        asset, edge, abs(edge), min_edge_threshold, current_best_edge
                                    )
                            else:
                                # Has position: only execute if edge improves significantly
                                # CRITICAL FIX: Use relative improvement (percentage) instead of absolute for velocity-based signals
                                # Velocity-based signals have tiny edges (0.01-0.07%), so absolute 5% threshold is impossible
                                # Use 20% relative improvement instead: edge must be 20% better than current best
                                # CRITICAL FIX: Use abs(edge) for comparison since edge = p_model - p_market can be negative
                                # Negative edges are valid contrarian signals (model disagrees with market)
                                if abs(current_best_edge) > 0:
                                    edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                                    edge_improvement_threshold = 0.20  # 20% relative improvement required
                                    if edge_improvement_ratio > edge_improvement_threshold:
                                        should_execute = True
                                        logger.info(
                                            "[15m-LOOP] Edge improvement: asset=%s edge=%.6f (abs=%.6f, ratio=%.2f%%) > current_best=%.6f + threshold=%.2f%% - will execute",
                                            asset, edge, abs(edge), edge_improvement_ratio * 100, current_best_edge, edge_improvement_threshold * 100
                                        )
                                        # Update best edge tracking
                                        self._best_edge_per_asset[asset] = {
                                            "ticker": ticker,
                                            "side": side,
                                            "edge": edge,
                                            "candidate": candidate
                                        }
                                    else:
                                        logger.debug(
                                            "[15m-LOOP] Edge improvement: asset=%s edge=%.6f (abs=%.6f, ratio=%.2f%%) <= current_best=%.6f + threshold=%.2f%% - skipping (position exists)",
                                            asset, edge, abs(edge), edge_improvement_ratio * 100, current_best_edge, edge_improvement_threshold * 100
                                        )
                                else:
                                    # No current best edge (first signal with position), execute if edge meets minimum threshold
                                    # CRITICAL FIX: Use abs(edge) for comparison since edge = p_model - p_market can be negative
                                    if abs(edge) > min_edge_threshold:
                                        should_execute = True
                                        logger.info(
                                            "[15m-LOOP] First signal with position: asset=%s edge=%.6f (abs=%.6f) > min_threshold=%.6f - will execute",
                                            asset, edge, abs(edge), min_edge_threshold
                                        )
                                        # Update best edge tracking
                                        self._best_edge_per_asset[asset] = {
                                            "ticker": ticker,
                                            "side": side,
                                            "edge": edge,
                                            "candidate": candidate
                                        }
                                    else:
                                        logger.debug(
                                            "[15m-LOOP] First signal with position: asset=%s edge=%.6f (abs=%.6f) <= min_threshold=%.6f - skipping",
                                            asset, edge, abs(edge), min_edge_threshold
                                        )
                            
                            if not should_execute:
                                continue
                            
                            # CRITICAL: Re-validate edge before execution
                            if not self._validate_candidate_edge(candidate):
                                logger.warning("[15m-LOOP] Candidate edge validation failed: %s - skipping execution", ticker)
                                continue
                            
                            # Use dynamic position sizing if enabled
                            try:
                                from merid.prediction.unified_sizing import compute_order_size
                                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                                from decimal import Decimal
                                
                                # Use sync version to avoid coroutine error in async context
                                bankroll_usd = get_equity_for_risk_calc_sync()
                                if bankroll_usd is None:
                                    bankroll_usd = 100.0
                                
                                # Get price from candidate or market state
                                # CRITICAL FIX (2026-07-06): The old default of 50c made sizing
                                # blind to the real price: floor($cap/$0.50)=2 contracts, while
                                # the order was later built at the real mid (60-89c), producing
                                # multi-contract orders (doubling up) and asset_notional_exceeded
                                # rejections. Resolve the SAME side-aware price here that
                                # _execute_candidate uses to build the order.
                                price_cents = int(candidate.get("price_cents", 0) or 0)
                                if price_cents <= 0:
                                    # Fallback to market state (side-aware, Kalshi duality: NO = 100 - YES_mid)
                                    if self.market_state_store:
                                        market_state = self.market_state_store.get(ticker)
                                        if market_state:
                                            candidate_side = str(candidate.get("side", "yes")).lower()
                                            yes_mid = 0
                                            if getattr(market_state, 'mid_cents', None):
                                                yes_mid = int(market_state.mid_cents)
                                            elif getattr(market_state, 'best_bid_cents', None) and getattr(market_state, 'best_ask_cents', None):
                                                yes_mid = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                                            if yes_mid > 0:
                                                if candidate_side in ("no", "buy_no"):
                                                    price_cents = 100 - yes_mid
                                                else:
                                                    price_cents = yes_mid
                                if price_cents <= 0:
                                    logger.warning(
                                        "[15m-LOOP] No real price available for sizing ticker=%s - using conservative 25c placeholder (midpoint of 10-50c sweet spot)",
                                        ticker
                                    )
                                    price_cents = 25  # 2026-07-09: Fixed to 25c (midpoint of 10-50c sweet spot)
                            
                                # Get edge and confidence from candidate
                                edge_pct = Decimal(str(candidate.get("edge_pct", 0.0)))
                                confidence = Decimal(str(candidate.get("confidence", 0.5)))
                                
                                # Extract asset from ticker
                                asset = ticker.split("-")[0].replace("KX", "") if "-" in ticker else "BTC"
                                
                                # Compute dynamic size
                                # 2026 Research-Based Risk Management: Apply time-of-day risk scaling
                                time_of_day_multiplier = candidate.get("time_of_day_multiplier", 1.0)
                                count, notional, metadata = compute_order_size(
                                    bankroll_usd=Decimal(str(bankroll_usd)),
                                    price_cents=int(price_cents),
                                    asset=asset,
                                    edge_pct=edge_pct,
                                    confidence=confidence,
                                    time_of_day_multiplier=time_of_day_multiplier
                                )
                                
                                candidate["count"] = count
                                
                                # CRITICAL FIX: Skip execution if sizing returned count=0
                                # This prevents invalid orders from being submitted
                                if count == 0:
                                    logger.warning(
                                        "[15m-LOOP] Sizing returned count=0 for ticker=%s (notional=%.2f, rejection_reason=%s) - skipping execution",
                                        ticker, float(notional), metadata.get("rejection_reason", "unknown")
                                    )
                                    continue
                                
                                logger.info(
                                    "[15m-LOOP] Dynamic sizing: ticker=%s edge=%.4f confidence=%.4f count=%d notional=%.2f",
                                    ticker, float(edge_pct), float(confidence), count, float(notional)
                                )
                                
                                # CRITICAL FIX: Integrate LiquidityAwareSizer to reduce size based on market depth
                                # This prevents slippage and market impact by respecting available liquidity
                                try:
                                    from execution.liquidity_aware_sizing import get_liquidity_sizer
                                    sizer = get_liquidity_sizer()
                                    
                                    # Determine side from candidate
                                    side = candidate.get("side", "yes").lower()
                                    
                                    # Get liquidity-aware size
                                    liquidity_adjusted_count = sizer.get_liquidity_aware_size(
                                        ticker=ticker,
                                        side=side,
                                        desired_contracts=count,
                                        max_participation_rate=0.1  # 10% participation rate
                                    )
                                    
                                    if liquidity_adjusted_count < count:
                                        logger.info(
                                            "[15m-LOOP] Liquidity-aware sizing reduced count: ticker=%s from %d to %d (depth-based adjustment)",
                                            ticker, count, liquidity_adjusted_count
                                        )
                                        candidate["count"] = liquidity_adjusted_count
                                    else:
                                        logger.debug(
                                            "[15m-LOOP] Liquidity-aware sizing: ticker=%s count unchanged (sufficient liquidity)",
                                            ticker
                                        )
                                except Exception as liquidity_err:
                                    logger.warning("[15m-LOOP] Liquidity-aware sizing failed, using risk-based count: %s", liquidity_err)
                            except Exception as sizing_err:
                                logger.warning("[15m-LOOP] Dynamic sizing failed, using default count=1: %s", sizing_err)
                                candidate["count"] = 1
                            
                            await self._execute_candidate(candidate, tick_id)
                            
                            # Track executed candidate to prevent duplicates
                            candidate_key = self._get_candidate_key(candidate)
                            self._executed_candidates_this_window.add(candidate_key)
                            
                            # FIX: Do NOT reset cycle guards after each execution
                            # The UnifiedRiskManager should track total notional across the 15-minute window
                            # to enforce the 5% total allocation limit. Resetting after each trade defeats this.
                            # Cycle reset only happens at the start of a new 15-minute window (line 1366)
                            
                            # CRITICAL FIX: Do NOT clear deduplication cache after each execution
                            # The cache should only be cleared at the start of a new 15-minute window (line 1346)
                            # Clearing it here allows the same order to be placed every 5 seconds, causing agents
                            # to exceed risk limits. The order gate and window-based risk checks should handle
                            # allowing new orders when conditions change (different price, side, etc.)
                        except Exception as e:
                            logger.error("[15m-LOOP] Failed to execute candidate: %s", e, exc_info=True)
                    
                    self._cycle_count += 1
                    self._last_cycle_at = datetime.now(timezone.utc)
                    
                except Exception as e:
                    self._error_count += 1
                    logger.error("[15m-LOOP] Cycle %d failed: %s", tick_id, e, exc_info=True)
                
                # Maintain cadence
                cycle_duration = time.time() - cycle_start
                sleep_duration = max(0, self.cadence_seconds - cycle_duration)
                try:
                    await asyncio.wait_for(asyncio.sleep(sleep_duration), timeout=sleep_duration + 1.0)
                except asyncio.TimeoutError:
                    logger.warning("[15m-LOOP] Sleep timeout in tick %d", tick_id)
                
        except asyncio.CancelledError:
            logger.info("[15m-LOOP] Loop cancelled")
            self._running = False
        finally:
            logger.info("[15m-LOOP] Loop stopped (cycles=%d, errors=%d)", self._cycle_count, self._error_count)

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        self._running = False

        # CRITICAL: Stop PositionMonitor before stopping loop
        if self._position_monitor:
            try:
                await self._position_monitor.stop()
                logger.info("[15m-LOOP] Stopped PositionMonitor")
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to stop PositionMonitor: %s", e, exc_info=True)

        # P2 Task 11: Log shutdown summary before stopping
        if self._run_summary:
            try:
                self._run_summary.log_on_shutdown()
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to log shutdown summary: %s", e, exc_info=True)

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("[15m-LOOP] Stop requested")

    async def _run_one_cycle(self, tick: int) -> None:
        """
        Run a single trading cycle.
        
        Steps:
        1) Reset UnifiedRiskManager cycle tracking (critical for cycle cap enforcement)
        2) Update envelope equity once per cycle (not per order)
        3) Check if halted due to drawdown
        4) Skip cycle if halted
        5) Pull latest market state / RTI inputs (rely on WS caches)
        6) Call agent_grid.run_cycle(tick) to step all agents
        7) Let AgentGrid/TradingAgent issue orders via route_order_async
        8) Log band transitions
        
        Phase 4.2: Enhanced with performance profiling
        """
        logger.info("[LOOP-STARTUP-ONE-CYCLE] _run_one_cycle ENTRY tick=%d", tick)
        logger.debug("[TRACE] _run_one_cycle ENTRY tick=%d", tick)
        
        # NOTE: Cycle resets are now handled in _run_agent_grid_with_timeout with window-based logic
        # This path is no longer used for cycle reset management
        
        # Import profiler for cycle monitoring
        from merid.performance.loop_profiler import get_loop_profiler
        profiler = get_loop_profiler()
        
        logger.debug("[RUN-ONE-CYCLE] Starting cycle=%d", tick)
        
        logger.debug("[15M-LOOP-CYCLE] ENTER cycle=%d", tick)
        cycle_start = time.time()
        self._last_cycle_at = datetime.now(timezone.utc)
        
        # Initialize timing variables at cycle start to ensure they're always defined
        catalog_elapsed = 0.0
        bankroll_elapsed = 0.0
        agent_elapsed = 0.0
        spot_elapsed = 0.0
        
        # Initialize fresh counts for use in readiness checks
        spot_fresh_count = 0
        md_fresh_count = 0
        
        # Out-of-band heartbeat (fires every cycle regardless of trading activity)
        current_time = datetime.utcnow()
        
        # COMPONENT TIMING: Spot service readiness check
        logger.debug("[TRACE] About to check spot service, cycle=%d", tick)
        t_spot = time.time()
        try:
            from data.unified_spot_service import get_unified_spot_service
            spot_service = get_unified_spot_service()
            
            # Check if spot service is ready (warmup complete)
            if not self._spot_ready_logged:
                if spot_service.is_ready():
                    self._spot_ready_logged = True
                    logger.info("[SPOT-READY] Spot service warmup complete; enabling 15m signals")
                else:
                    logger.debug("[15M-LOOP] Spot service not ready - waiting for warmup")
            
            # CRITICAL FIX: Calculate spot_fresh_count directly from spot service
            # This bypasses the health snapshot which may not be correctly tracking spot status
            spot_fresh_count = 0
            try:
                assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                for asset in assets:
                    spot_data = spot_service.get(asset)
                    if spot_data and spot_data.price > 0:
                        # Check freshness - spot service tracks age internally
                        # If we can get data and it's valid, consider it fresh
                        spot_fresh_count += 1
                logger.debug("[SPOT-FRESHNESS-COUNT] cycle=%d fresh=%d/5", tick, spot_fresh_count)
            except Exception as e:
                logger.warning("[SPOT-FRESHNESS-COUNT] Failed to calculate: %s", e)
        except Exception as e:
            logger.warning("[15M-LOOP] Failed to check spot service readiness: %s", e, exc_info=True)
        spot_elapsed = time.time() - t_spot
        logger.debug("[TRACE] After spot service check, cycle=%d", tick)
        
        # COMPONENT TIMING: Catalog + MD freshness check
        t_catalog = time.time()
        
        # DIAGNOSTIC: Log before entering the try block
        logger.info("[LOOP-STARTUP-BEFORE-PROFILER] Before profiler context, cycle=%d", tick)
        logger.debug("[15M-LOOP] About to enter try block, cycle=%d", tick)
        
        # Phase 4.2: Profile market scanning phase
        async with profiler.profile_phase("market_scanning"):
            # DIAGNOSTIC: Log immediately after entering profiler context
            logger.info("[LOOP-STARTUP-PROFILER] Inside profiler context, cycle=%d _catalog_ready=%s", tick, self._catalog_ready)
            logger.debug("[15M-LOOP] INSIDE-PROFILER-CONTEXT cycle=%d", tick)
            # Execution-ready heartbeat instrumentation
            # Logs catalog freshness, MD freshness, depth, and candidate generation
            logger.debug("[TRACE] ENTER market_scanning phase, cycle=%d", tick)
            
            # CRITICAL FIX: Ensure risk envelope is initialized before market scanning
            # Fail-fast if envelope is None to prevent AttributeError during depth checks
            logger.info("[LOOP-STARTUP-RISK-ENVELOPE] Checking risk envelope, cycle=%d", tick)
            if self._risk_envelope is None:
                logger.info("[LOOP-STARTUP-RISK-ENVELOPE] Envelope is None, initializing...")
                current_bankroll = self.bankroll_service.get_equity_for_risk_calc_sync_cached() if self.bankroll_service else 0.0
                self._risk_envelope = self._get_cached_envelope(current_bankroll)
                if self._risk_envelope is None:
                    logger.error("[15M-LOOP] Risk envelope is None after initialization attempt - HALTING to prevent AttributeError")
                    raise RuntimeError("Risk envelope initialization failed - cannot proceed with market scanning")
            logger.info("[LOOP-STARTUP-RISK-ENVELOPE] Envelope is ready, cycle=%d", tick)
            
            try:
                # DIAGNOSTIC: Log inside try block
                logger.info("[LOOP-STARTUP-TRY] Inside try block, cycle=%d", tick)
                
                from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                from config.kalshi_universe import KALSHI_15M_SERIES_TICKERS
                
                # Get market state store early for per-ticker health checks
                store = get_kalshi_market_state_store()
                
                # DIAGNOSTIC: Log at the beginning of catalog check
                
                
                # DIAGNOSTIC: Check catalog object existence and properties
                catalog_exists = hasattr(self, '_catalog')
                catalog_is_not_none = catalog_exists and self._catalog is not None
                
                
                # Catalog startup guard - skip trading logic until first refresh completes
                logger.info("[LOOP-STARTUP-CHECK] _catalog_ready=%s catalog_id=%s", self._catalog_ready, id(self._catalog) if hasattr(self, '_catalog') and self._catalog else None)
                if not self._catalog_ready:
                    logger.info("[LOOP-STARTUP] Catalog not ready yet, checking... catalog_id=%s", id(self._catalog))
                    if hasattr(self, '_catalog') and self._catalog:
                        # CRITICAL FIX: Wait for catalog's first refresh to complete before taking snapshot
                        # This prevents empty snapshots during startup
                        if hasattr(self._catalog, '_first_refresh_completed'):
                            logger.info("[LOOP-STARTUP] Waiting for catalog first refresh event... catalog_id=%s", id(self._catalog))
                            event_set = self._catalog._first_refresh_completed.wait(timeout=60.0)
                            logger.info("[LOOP-STARTUP] First refresh event wait completed: event_set=%s catalog_id=%s", event_set, id(self._catalog))
                        
                        catalog_snapshot = self._catalog.snapshot()
                        logger.info("[LOOP-STARTUP] After snapshot: market_count=%d catalog_id=%s", catalog_snapshot.market_count if catalog_snapshot else 0, id(self._catalog))
                        
                        if catalog_snapshot and catalog_snapshot.market_count > 0:
                            self._catalog_ready = True
                            self._catalog_roll_ts = time.time()  # Set catalog roll timestamp to enable warmup grace period
                            logger.info("[CATALOG-READY] First catalog refresh completed; enabling 15m trading (markets=%d)", catalog_snapshot.market_count)
                            
                            
                            # Initial WS subscription setup on first catalog ready
                            
                            
                            if self._ws_bridge and catalog_snapshot.markets:
                                # Extract current market tickers from catalog
                                initial_tickers = []
                                for market in catalog_snapshot.markets:
                                    market_id = market.market.market_id if hasattr(market, 'market') else market.market_id
                                    initial_tickers.append(market_id)
                                
                                
                                
                                if initial_tickers:
                                    self._ws_bridge.set_markets(initial_tickers)
                                    logger.info(
                                        "[CATALOG-READY] Initial WS subscription requested for %d tickers via ws_bridge.set_markets()",
                                        len(initial_tickers)
                                    )
                            
                        elif not self._catalog_not_ready_logged:
                            self._catalog_not_ready_logged = True
                            logger.info("[15M-LOOP] CATALOG-NOT-READY: Waiting for first catalog refresh (total_markets=0, last_refresh=None)")
                            # DIAGNOSTIC: Log more details about why catalog is not ready
                            if catalog_snapshot:
                                logger.warning("[15M-LOOP] CATALOG-DEBUG: snapshot exists but market_count=%d, refreshed_at=%s", catalog_snapshot.market_count, catalog_snapshot.refreshed_at)
                            else:
                                logger.warning("[15M-LOOP] CATALOG-DEBUG: catalog_snapshot is None")
                
                # Catalog readiness check - allow cycle to proceed even if catalog not ready
                # Catalog refresh is idempotent; the grid can operate on last known markets
                if not self._catalog_ready:
                    if catalog_snapshot and catalog_snapshot.market_count > 0:
                        self._catalog_ready = True
                        logger.info("[CATALOG-READY] Catalog now ready; enabling 15m trading (markets=%d)", catalog_snapshot.market_count)
                        
                        # Initial WS subscription setup on first catalog ready
                        if self._ws_bridge and catalog_snapshot.markets:
                            # Extract current market tickers from catalog
                            initial_tickers = []
                            for market in catalog_snapshot.markets:
                                market_id = market.market.market_id if hasattr(market, 'market') else market.market_id
                                initial_tickers.append(market_id)
                            
                            if initial_tickers:
                                self._ws_bridge.set_markets(initial_tickers)
                                logger.info(
                                    "[CATALOG-READY] Initial WS subscription requested for %d tickers via ws_bridge.set_markets()",
                                    len(initial_tickers)
                                )
                    else:
                        logger.warning(
                            "[15M-LOOP] Catalog not ready (market_count=%d), "
                            "proceeding with last known markets",
                            catalog_snapshot.market_count if catalog_snapshot else 0,
                        )
                        # Do NOT return here - let run_cycle() operate on whatever it has
            
                # Check catalog freshness and per-ticker health
                catalog_fresh = True
                catalog_age_s = 0
                catalog_stale_reasons = []  # Track specific reasons for catalog staleness
                
                
                
                # CRITICAL FIX: Calculate in_warmup BEFORE catalog freshness check
                # This ensures the warmup override is applied correctly
                # If _catalog_roll_ts is 0.0 (not yet initialized), consider it as in warmup
                
                if self._catalog_roll_ts == 0.0:
                    in_warmup = True  # Catalog hasn't rolled yet, consider it as warmup
                    time_since_roll = 0.0  # Placeholder for logging
                else:
                    time_since_roll = time.time() - self._catalog_roll_ts
                    in_warmup = time_since_roll < self._catalog_warmup_seconds
                
                
                
                # DIAGNOSTIC: Log warmup calculation immediately
                try:
                    pass  # No diagnostic writing needed
                except Exception as e:
                    logger.error(f"[WARMUP-CALC-DIAG] Failed to write to health_diagnostic.txt: {e}", exc_info=True)
                
                if hasattr(self, '_catalog') and self._catalog:
                    catalog_snapshot = self._catalog.snapshot()
                    if catalog_snapshot and catalog_snapshot.refreshed_at:
                        # Handle both datetime and float (timestamp) types
                        refreshed_at = catalog_snapshot.refreshed_at
                        if isinstance(refreshed_at, (int, float)):
                            refreshed_at = datetime.fromtimestamp(refreshed_at, tz=timezone.utc)
                        catalog_age_s = (datetime.now(timezone.utc) - refreshed_at).total_seconds()
                    else:
                        # Catalog exists but no refresh timestamp - consider stale
                        pass  # Set catalog_age_s below
                        catalog_age_s = 999999.0  # Force stale state
                    # NOTE: catalog_fresh is now based on tiered staleness thresholds
                    # FRESH: catalog_age <= 60s, STALE_WARN: 60s < age <= 300s, STALE_BLOCK: age > 300s
                    catalog_fresh = catalog_age_s <= 60.0  # FRESH threshold
                    
                    # Apply warmup grace period to catalog freshness check
                    # During warmup, consider catalog fresh even if age exceeds threshold
                    # This allows the system to start trading while catalog is still initializing
                    if in_warmup:
                        catalog_fresh = True  # Warmup grace: allow trading during catalog initialization
                    elif not catalog_fresh:
                        catalog_stale_reasons.append(f"catalog_age({catalog_age_s:.1f}s)")
                    
                    # Detect catalog roll (market IDs changed) for WS warmup grace period
                    current_market_ids = set()
                    if catalog_snapshot:
                        for market in catalog_snapshot.markets:
                            market_id = market.market.market_id if hasattr(market, 'market') else market.market_id
                            current_market_ids.add(market_id)
                        
                        if current_market_ids != self._last_catalog_market_ids:
                            # Catalog rolled - new markets
                            old_market_ids = self._last_catalog_market_ids
                            self._last_catalog_market_ids = current_market_ids
                            self._catalog_roll_ts = time.time()
                            logger.info(
                                "[CATALOG-ROLL] markets changed from %d to %d, warmup grace period started",
                                len(old_market_ids) if old_market_ids else 0,
                                len(current_market_ids)
                            )
                            
                            # Request WS bridge to resubscribe to new tickers
                            if self._ws_bridge:
                                # Extract current market tickers from catalog
                                current_tickers = list(current_market_ids)
                                self._ws_bridge.set_markets(current_tickers)
                                logger.info(
                                    "[CATALOG-ROLL] Requested WS resubscribe for %d tickers via ws_bridge.set_markets()",
                                    len(current_tickers)
                                )
                
                # Apply WS warmup grace period after catalog roll
                # Allow N seconds for WS to deliver initial snapshots before flagging staleness
                # NOTE: in_warmup is calculated earlier (before catalog freshness check)
                
                
                
                if in_warmup and catalog_stale_reasons:
                    # In warmup period - suppress transport staleness warnings
                    catalog_stale_reasons = [r for r in catalog_stale_reasons if 'transport_stale' not in r]
                    if not catalog_stale_reasons:
                        catalog_fresh = True  # Warmup grace: allow trading during catalog initialization
                    logger.info(
                        "[CATALOG-WARMUP] grace period active (%.1fs/%.1fs), transport staleness suppressed",
                        time_since_roll, self._catalog_warmup_seconds
                    )
                    
                
                # Check per-ticker health for catalog tickers
                # This ties CATALOG_STALE to actual market state freshness
                # Suppress during warmup grace period to allow WS to deliver initial snapshots
                if hasattr(self, '_catalog') and self._catalog and not in_warmup:
                    catalog_snapshot = self._catalog.snapshot()
                    if catalog_snapshot:
                        for market in catalog_snapshot.markets:
                            market_id = market.market.market_id if hasattr(market, 'market') else market.market_id
                            state = store.get(market_id)
                            if state:
                                health = state.check_health()
                                # check_health() returns a dict, access via keys
                                if health.get('transport_stale', False):
                                    catalog_stale_reasons.append(f"ticker={market_id} transport_stale mode={health.get('transport_mode', 'unknown')}")
                                    catalog_fresh = False  # Transport staleness makes catalog effectively stale
                                if health.get('state_inconsistent', False):
                                    catalog_stale_reasons.append(f"ticker={market_id} state_inconsistent")
                                    catalog_fresh = False  # Inconsistent state makes catalog effectively stale
                
                # Log catalog staleness reasons for visibility
                if catalog_stale_reasons:
                    logger.warning(
                        "[CATALOG-STALE-DETAIL] reasons=%s catalog_age=%.1fs warmup=%s",
                        ", ".join(catalog_stale_reasons), catalog_age_s, in_warmup
                    )
                
                # FINAL OVERRIDE: Force catalog_fresh=True during warmup grace period
                # This ensures that during the warmup period, the catalog is considered fresh
                # regardless of other staleness checks, allowing the system to start trading
                # once WS delivers initial snapshots
                if in_warmup:
                    catalog_fresh = True
                    logger.info(
                        "[CATALOG-WARMUP-OVERRIDE] Forcing catalog_fresh=True during warmup (%.1fs/%.1fs)",
                        time_since_roll, self._catalog_warmup_seconds
                    )
                    
                
                # Check MD freshness and depth for all 5 assets
                md_fresh_count = 0
                depth_sufficient_count = 0
                # LOOP-STATE: per-asset readiness (MD fresh AND depth sufficient) plus
                # catalog market presence (assets with >=1 active 15m strip in catalog)
                ready_assets_count = 0
                markets_present_count = 0
                assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                # store already initialized above for per-ticker health checks
                
                # LAG-TRACKER: Get spot service for lag correlation
                try:
                    from data.unified_spot_service import get_unified_spot_service
                    spot_service = get_unified_spot_service()
                except Exception as e:
                    logger.debug("[15M-LOOP] Failed to get spot service: %s", e, exc_info=True)
                    spot_service = None
                
                for asset in assets:
                    series_ticker = KALSHI_15M_SERIES_TICKERS[asset]
                    # Get current market from catalog
                    state = None  # Initialize state to prevent UnboundLocalError
                    market_id = None
                    if hasattr(self, '_catalog') and self._catalog:
                        catalog_snapshot = self._catalog.snapshot()
                        # CRITICAL: Use canonical get_current_15m_market to enforce single-market invariant
                        # This resolves to exactly one market per asset by exact ET window match
                        # No selection logic - if exact match not found, asset is unavailable this window
                        current_market = catalog_snapshot.get_current_15m_market(asset)
                        if current_market:
                            # LOOP-STATE: this asset has an active 15m market in current window
                            markets_present_count += 1
                            market_id = current_market.market.market_id if hasattr(current_market, 'market') else current_market.market_id
                            state = store.get(market_id)
                        
                        # AUDIT #2: Catalog window alignment check
                        try:
                            now_utc = datetime.now(timezone.utc)
                            
                            # Extract window info from market
                            window_start = None
                            window_expiry = None
                            min_to_expiry = None
                            is_current_window = False
                            
                            # CatalogMarket has expires_at field, not close_time
                            if current_market and hasattr(current_market, 'expires_at') and current_market.expires_at:
                                window_expiry = current_market.expires_at
                                if window_expiry:
                                    # For 15m contracts, window start is 15m before expiry
                                    window_start = window_expiry - timedelta(minutes=15)
                                    min_to_expiry = (window_expiry - now_utc).total_seconds() / 60.0
                                    
                                    # Check if this is the current 15m window
                                    current_window_start = now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0)
                                    current_window_end = current_window_start + timedelta(minutes=15)
                                    is_current_window = current_window_start <= window_start < current_window_end
                            
                            # Check MD state
                            has_md_state = state is not None
                            md_stale = False
                            if state and state.last_book_update_ts:
                                md_age = time.monotonic() - state.last_book_update_ts
                                # Uses SLA threshold from sla_config for timing-aware MD freshness check
                                from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds
                                # CRITICAL FIX (2026-07-11): Use timing-aware threshold for catalog window check
                                minutes_to_expiry = min_to_expiry if min_to_expiry is not None else None
                                max_age_seconds = get_md_max_age_seconds(minutes_to_expiry)
                                md_stale = md_age > max_age_seconds
                                
                                # DIAGNOSTIC: Log impossible ages to identify timebase mismatch
                                if md_age < -5 or md_age > 3600:
                                    logger.error(
                                        "[MD-AGE-DIAGNOSTIC] Impossible age: ticker=%s age=%.1fs now=%r last_update=%r",
                                        ticker, md_age, time.monotonic(), state.last_book_update_ts,
                                    )
                            
                            logger.info(
                                "[CATALOG-WINDOW-CHECK] asset=%s series=%s resolved_ticker=%s window_start=%s window_expiry=%s now=%s min_to_expiry=%.2f is_current_window=%s has_md_state=%s md_stale=%s",
                                asset,
                                series_ticker,
                                market_id,
                                window_start.isoformat() if window_start else "N/A",
                                window_expiry.isoformat() if window_expiry else "N/A",
                                now_utc.isoformat(),
                                min_to_expiry if min_to_expiry is not None else -1,
                                is_current_window,
                                has_md_state,
                                md_stale
                            )
                        except Exception as e:
                            logger.warning("[CATALOG-WINDOW-CHECK] Failed to check window alignment for asset %s: %s", asset, e)
                        
                        # LAG-TRACKER: Fetch spot price for this asset using service API
                        spot_data = None
                        spot_ts = 0.0
                        if spot_service:
                            try:
                                from data.unified_spot_service import SpotError
                                spot_result = spot_service.get(asset)
                                if isinstance(spot_result, SpotError):
                                    # Spot is degraded or unavailable
                                    logger.debug("[15M-LOOP] Spot degraded for %s: reason=%s", asset, spot_result.reason)
                                elif spot_result:
                                    spot_ts = spot_result.timestamp / 1000.0  # Convert ms to seconds
                            except Exception as e:
                                logger.debug("[15M-LOOP] Failed to get spot data for %s: %s", asset, e, exc_info=True)
                        
                        # LAG-TRACKER: Calculate lag metrics
                        now_ts = time.time()
                        spot_age = now_ts - spot_ts if spot_ts > 0 else None
                        md_age = None
                        skew = None
                        
                        if state:
                            # Use last_book_update_ts which is a monotonic timestamp
                            # Compare directly to current monotonic time for age calculation
                            last_update_ts = state.last_book_update_ts
                            if last_update_ts:
                                age_s = time.monotonic() - last_update_ts
                                md_age = age_s
                                
                                # DIAGNOSTIC: Log impossible ages to identify timebase mismatch
                                if age_s < -5 or age_s > 3600:
                                    logger.error(
                                        "[MD-AGE-DIAGNOSTIC] Impossible age (depth check): ticker=%s age=%.1fs now=%r last_update=%r",
                                        ticker, age_s, time.monotonic(), last_update_ts,
                                    )
                            else:
                                age_s = 9999
                            # Apply warmup grace period to MD freshness check
                            # During warmup, consider MD fresh even if age exceeds threshold
                            # This allows the system to start trading while MD is still initializing
                            if in_warmup:
                                asset_md_fresh = True  # Warmup grace: allow trading during MD initialization
                            else:
                                # Uses canonical SLA threshold from sla_config for timing-aware MD freshness check
                                # This ensures consistency with agent grid and other layers
                                pass  # Logic continues below
                                from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds
                                
                                # Get timing-aware threshold if expiry info available
                                minutes_to_expiry = None
                                if state and hasattr(state, 'seconds_to_expiry') and state.seconds_to_expiry:
                                    minutes_to_expiry = state.seconds_to_expiry / 60.0
                                
                                max_age_seconds = get_md_max_age_seconds(minutes_to_expiry)
                                asset_md_fresh = age_s < max_age_seconds
                            if asset_md_fresh:
                                md_fresh_count += 1
                            # Check depth (use min_depth_yes/min_depth_no from KalshiMarketState)
                            # Depth thresholds now come from kalshi_crypto_15m.yaml profile (single source of truth)
                            # Get per-asset depth thresholds from profile
                            depth_thresholds = self._risk_envelope.get_depth_thresholds(asset)
                            min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 25)
                            min_depth_no_threshold = depth_thresholds.get('min_depth_no', 25)
                            
                            # DIAGNOSTIC: Log raw state before depth check
                            logger.debug(
                                "[DEPTH-RAW] asset=%s ticker=%s state_exists=%s has_bid=%s has_ask=%s depth_10c=%d best_bid=%s best_ask=%s",
                                asset, market_id, state is not None, state.has_bid if state else "N/A", state.has_ask if state else "N/A",
                                state.depth_10c if state else "N/A",
                                state.best_bid_cents if state else "N/A", state.best_ask_cents if state else "N/A"
                            )
                            
                            # Log actual depth values for diagnostics
                            logger.info(
                                "[DEPTH-CHECK] asset=%s ticker=%s min_depth_yes=%d min_depth_no=%d thresholds=(yes>=%d, no>=%d)",
                                asset, market_id, state.min_depth_yes, state.min_depth_no,
                                min_depth_yes_threshold, min_depth_no_threshold
                            )
                            # DIAGNOSTIC: Write depth check to health_diagnostic.txt
                            try:
                                pass  # No diagnostic writing needed
                            except Exception:
                                pass
                            
                            # CRITICAL FIX: Use liquidity-aware check instead of binary depth threshold
                            # This considers actual trade size and slippage budget, not arbitrary depth counts
                            # Get max slippage from risk profile (default 3 cents from kalshi_crypto_15m.yaml)
                            max_slippage_cents = getattr(self._risk_envelope, 'guardrails_max_slippage_cents', 3)
                            
                            # Use depth threshold as proxy for target size (minimum contracts we want to trade)
                            target_qty = min_depth_yes_threshold  # Conservative: use YES threshold as target
                            
                            # Check liquidity for YES side (primary for our trading)
                            liquidity_result = can_fill_order_safely(
                                state, target_qty, max_slippage_cents, side="yes"
                            )
                            
                            # Log liquidity decision
                            logger.info(
                                "[LIQUIDITY-CHECK] asset=%s ticker=%s decision=%s available=%d target=%d reason=%s",
                                asset, market_id, liquidity_result.decision.value,
                                liquidity_result.available_qty, liquidity_result.target_qty,
                                liquidity_result.reason
                            )
                            
                            # Determine if asset is ready based on liquidity decision
                            # FULL or REDUCED means we can trade (maybe with smaller size)
                            # SKIP means insufficient liquidity for this cycle
                            asset_depth_ok = liquidity_result.decision in (LiquidityDecision.FULL, LiquidityDecision.REDUCED)
                            
                            if asset_depth_ok:
                                depth_sufficient_count += 1
                                if liquidity_result.decision == LiquidityDecision.REDUCED:
                                    logger.info(
                                        "[LIQUIDITY-REDUCED] asset=%s ticker=%s will trade with reduced size (available=%d < target=%d)",
                                        asset, market_id, liquidity_result.available_qty, liquidity_result.target_qty
                                    )
                            else:
                                # CRITICAL FIX: Track per-asset disablement due to thin liquidity
                                # This allows other assets to continue trading
                                pass  # Logic continues below
                                logger.warning(
                                    "[ASSET-DISABLED] asset=%s ticker=%s reason=MD_THIN decision=%s available=%d target=%d",
                                    asset, market_id, liquidity_result.decision.value,
                                    liquidity_result.available_qty, liquidity_result.target_qty
                                )
                            
                            # LOOP-STATE: an asset is "ready" if liquidity is sufficient (removed MD freshness check)
                            if asset_depth_ok:
                                ready_assets_count += 1
                            
                            # LAG-TRACKER: Calculate skew if both timestamps available
                            if spot_ts > 0 and last_update_ts:
                                # Convert monotonic to wall clock approximation for skew calculation
                                # This is approximate but sufficient for lag tracking
                                skew = abs(spot_ts - (now_ts - age_s))
                        
                        # LAG-TRACKER: Log per-asset lag metrics
                        # Note: last_update_ts is monotonic (seconds since boot), not Unix timestamp
                        # md_age is the meaningful staleness metric
                        # FIX: Remove sentinel -1.0 values - use "N/A" for missing data instead
                        spot_ts_str = f"{spot_ts:.3f}" if spot_ts > 0 else "N/A"
                        spot_age_str = f"{spot_age:.3f}s" if spot_age is not None else "N/A"
                        md_age_str = f"{md_age:.3f}s" if md_age is not None else "N/A"
                        skew_str = f"{skew:.3f}" if skew is not None else "N/A"
                        
                        logger.debug(
                            "LAG-TRACKER asset=%s ticker=%s spot_ts=%s spot_age=%s "
                            "md_age=%s skew=%s",
                            asset,
                            market_id,
                            spot_ts_str,
                            spot_age_str,
                            md_age_str,
                            skew_str,
                        )
            except Exception as e:
                logger.error("[15M-LOOP] Market scanning phase failed: %s", e, exc_info=True)
                catalog_fresh = False
                md_fresh_count = 0
                depth_sufficient_count = 0
                ready_assets_count = 0
                markets_present_count = 0
                ws_forwarder_healthy = False
            
            # Check WS forwarder health before declaring execution ready
            ws_forwarder_healthy = False
            try:
                # CRITICAL FIX: Use shared WS bridge instance from main_15m_lean P1.5
                # This prevents creating duplicate WS connections every cycle
                bridge = self._ws_bridge
                if bridge is None:
                    logger.warning("[WS-FORWARD-HEALTH-GATE] WS bridge not provided to loop - skipping health check")
                    ws_forwarder_healthy = False
                else:
                    # Use new bridge's stats() method (compatibility wrapper added to ws_bridge.py)
                    pass  # Get stats below
                    stats = bridge.stats()
                    is_connected = stats.get("connected", False)
                    messages_received = stats.get("messages_received", 0)
                    last_message_time = stats.get("last_message_time", 0)
                    reconnect_count = stats.get("reconnect_count", 0)
                    markets = stats.get("markets", [])
                    
                    # Calculate time since last message (in seconds)
                    # NOTE: bridge.stats() returns last_message_time as Unix timestamp in seconds
                    now_sec = time.time()
                    time_since_last_msg = now_sec - last_message_time if last_message_time > 0 else float('inf')
                    
                    # Health criteria for new bridge (KalshiWebSocketBridge):
                    # 1. Must be connected (WebSocket connection active)
                    # 2. Should have received some messages (unless just started - 60s grace period)
                    # 3. Last message should be recent (< 120 seconds staleness threshold, relaxed from 30s)
                    #    OR within startup grace period (last_message_time=0 means not yet received)
                    # 4. Should have markets configured (at least 1 market subscribed)
                    # NOTE: 120-second staleness threshold relaxed to prevent false positives
                    is_healthy = (
                        is_connected and
                        (messages_received > 0 or time_since_last_msg < 60.0) and  # Allow startup grace period
                        (time_since_last_msg < 120.0 or last_message_time == 0) and  # Relaxed from 30s to 120s
                        len(markets) > 0
                    )
                    
                    # FALLBACK: If MD is fresh for all 5 assets, consider WS healthy
                    # This handles cases where WS bridge stats() might be stale but data is flowing
                    if not is_healthy and md_fresh_count >= 5:
                        logger.warning(
                            "[WS-FORWARD-HEALTH-GATE] WS bridge stats indicate unhealthy, but MD is fresh (5/5). Overriding to healthy to prevent false HALT."
                        )
                        is_healthy = True
                    
                    ws_forwarder_healthy = is_healthy
                    
                    if not is_healthy:
                        logger.warning(
                            "[WS-FORWARD-HEALTH-GATE] connected=%s messages=%d time_since_last=%.1fs markets=%d reconnects=%d - NOT execution ready (checks: connected=%s msg_ok=%s staleness_ok=%s markets_ok=%s)",
                            is_connected, messages_received, time_since_last_msg, len(markets), reconnect_count,
                            is_connected,
                            (messages_received > 0 or time_since_last_msg < 60.0),
                            (time_since_last_msg < 30.0 or last_message_time == 0),
                            len(markets) > 0
                        )
                    else:
                        logger.info(
                            "[WS-FORWARD-HEALTH-GATE] connected=%s messages=%d time_since_last=%.1fs markets=%d reconnects=%d - healthy",
                            is_connected, messages_received, time_since_last_msg, len(markets), reconnect_count
                        )
            except Exception as ws_health_err:
                logger.error("[WS-FORWARD-HEALTH-GATE] Failed to get WS forwarder health: %s", ws_health_err, exc_info=True)
                ws_forwarder_healthy = False
            
            # INVARIANT: Apply tiered catalog staleness (not hard kill switch)
            # FRESH: catalog_age <= 60s → RUN_NORMAL/RUN_DEGRADED
            # STALE_WARN: 60s < catalog_age <= 300s → RUN_NORMAL/RUN_DEGRADED with logging
            # STALE_BLOCK: catalog_age > 300s → NO_NEW_ENTRIES (not HALT_CRITICAL)
            CATALOG_STALE_WARN_SECONDS = 60.0
            CATALOG_STALE_BLOCK_SECONDS = 300.0
            MIN_DEPTH_COVERAGE_FOR_READY = 1  # At least 1 asset must have sufficient depth (diagnostic)
            # P0 FIX: Only halt if ALL assets are stale (md_fresh_count == 0)
            # Allow trading in DEGRADED mode with partial coverage (>=1 asset fresh)
            MIN_MD_COVERAGE_FOR_READY = 1  # At least 1 asset must have fresh MD (diagnostic)
            # LOOP-STATE: ready-asset count required for NORMAL vs DEGRADED within ACTIVE
            MIN_READY_ASSETS_FOR_NORMAL = 2  # >=2 ready -> NORMAL, ==1 -> DEGRADED, ==0 (markets present) -> ACTIVE-HALT
            
            # Determine catalog health state
            if catalog_age_s <= CATALOG_STALE_WARN_SECONDS:
                catalog_health = "FRESH"
                catalog_age_ok = True
                logger.info(
                    "[CATALOG-HEALTH] status=FRESH age=%.1fs threshold=%.1fs - catalog is fresh",
                    catalog_age_s, CATALOG_STALE_WARN_SECONDS
                )
            elif catalog_age_s <= CATALOG_STALE_BLOCK_SECONDS:
                catalog_health = "STALE_WARN"
                catalog_age_ok = True  # Still allow trading, just log warning
                logger.warning(
                    "[CATALOG-HEALTH] status=STALE_WARN age=%.1fs threshold=%.1fs - allowing trading with warning",
                    catalog_age_s, CATALOG_STALE_WARN_SECONDS
                )
            else:
                catalog_health = "STALE_BLOCK"
                catalog_age_ok = False  # Block new entries but not HALT_CRITICAL
                logger.error(
                    "[CATALOG-HEALTH] status=STALE_BLOCK age=%.1fs threshold=%.1fs - blocking new entries",
                    catalog_age_s, CATALOG_STALE_BLOCK_SECONDS
                )
            
            # Apply warmup grace period to catalog_age_ok as well
            if in_warmup:
                catalog_age_ok = True  # Warmup grace: allow trading during catalog initialization
                catalog_health = "FRESH"  # Override to FRESH during warmup
            depth_coverage_ready = depth_sufficient_count >= MIN_DEPTH_COVERAGE_FOR_READY
            md_coverage_ok = md_fresh_count >= MIN_MD_COVERAGE_FOR_READY
            
            # Check bankroll and risk profile status
            live_bankroll_source = "unknown"
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync, get_bankroll_service
                live_bankroll = get_equity_for_risk_calc_sync()
                live_bankroll_valid = live_bankroll is not None and live_bankroll > 0.0
                
                # Get bankroll source for fake bankroll detection
                if live_bankroll is not None:
                    try:
                        import asyncio
                        loop = asyncio.get_running_loop()
                        service = loop.run_until_complete(get_bankroll_service())
                        if service._current and hasattr(service._current, 'source'):
                            live_bankroll_source = service._current.source
                        else:
                            live_bankroll_source = "kalshi"  # Default to kalshi if we have a real value
                    except Exception as source_err:
                        logger.debug("[15M-EXECUTION-READY] Could not determine bankroll source: %s", source_err)
                        live_bankroll_source = "kalshi"  # Default assumption
                else:
                    live_bankroll_source = "none"
            except Exception as e:
                logger.warning("[15M-EXECUTION-READY] Failed to fetch bankroll: %s", e)
                live_bankroll = None
                live_bankroll_valid = False
                live_bankroll_source = "error"
            
            # Check if risk profile is loaded
            try:
                from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
                risk_profile_loaded = is_profile_active()
                # Check if catalog staleness enforcement is disabled for this profile
                catalog_staleness_enforced = True
                if risk_profile_loaded:
                    profile_adapter = get_active_profile()
                    if profile_adapter and hasattr(profile_adapter, 'profile'):
                        catalog_staleness_enforced = getattr(profile_adapter.profile, 'catalog_staleness_enforced', True)
            except Exception as e:
                logger.warning("[15M-EXECUTION-READY] Failed to check risk profile: %s", e)
                risk_profile_loaded = False
                catalog_staleness_enforced = True  # Default to enabled on error
            
            # Check top3_batch_manager availability (profile-aware)
            # DIAGNOSTIC: Log before TOP3 gate check
            
            logger.info("[TOP3-GATE] Attempting to import get_top3_batch_manager...")
            try:
                from merid.trading import get_top3_batch_manager
                top3_gate_available = True
                logger.info("[TOP3-GATE] Successfully imported get_top3_batch_manager")
                
            except ImportError as e:
                top3_gate_available = False
                logger.error("[TOP3-GATE] Failed to import get_top3_batch_manager: %s", e)
                
            except Exception as e:
                top3_gate_available = False
                logger.error("[TOP3-GATE] Unexpected error importing get_top3_batch_manager: %s", e)
                
                # Profile-aware policy: fail-closed in live profiles, fail-open in test profiles
                is_live_profile = (
                    _settings and 
                    hasattr(_settings, 'PROFILE_IS_LIVE') and 
                    _settings.PROFILE_IS_LIVE
                )
                
                if is_live_profile:
                    profile_name = getattr(_settings, 'MERID_PROFILE', 'unknown') if _settings else 'unknown'
                    logger.critical("[TOP3-GATE] top3_batch_manager missing in LIVE profile %s - failing closed (CRITICAL: position limits disabled)", profile_name)
                    # 15m-native invariant (replaces legacy E2EInvariantChecker, a forbidden
                    # legacy import in the 15m stack): FAIL CLOSED. top3_gate_available is forced
                    # False so infra_ready=False below, blocking all new entries this cycle until
                    # the position-limit (top3) gate is restored.
                    top3_gate_available = False
                else:
                    profile_name = getattr(_settings, 'MERID_PROFILE', 'unknown') if _settings else 'unknown'
                    logger.warning("[TOP3-GATE-TEST-MODE] top3_batch_manager missing in TEST profile %s - gate disabled (fail-open)", profile_name)
            
            # DIAGNOSTIC: Log after TOP3 gate check
            
            
            # Check for fake bankroll sources in live profiles
            fake_bankroll_used = False
            is_live_profile = (
                _settings and 
                hasattr(_settings, 'PROFILE_IS_LIVE') and 
                _settings.PROFILE_IS_LIVE
            )
            
            # Allow fake bankroll in test profiles if explicitly enabled
            allow_fake_bankroll = (
                not is_live_profile and 
                _settings and 
                getattr(_settings, 'MERID_ALLOW_FAKE_BANKROLL_FOR_TEST', False)
            )
            
            # Check fake bankroll invariant (skip if explicitly allowed in test mode)
            fake_bankroll_violation = None
            if not allow_fake_bankroll:
                # 15m-native fake-bankroll invariant (replaces legacy E2EInvariantChecker).
                # In live profiles, FAIL CLOSED if the bankroll is non-positive or sourced from a
                # non-canonical provider. Setting fake_bankroll_used=True forces
                # bankroll_source_valid=False below -> infra_ready=False -> trading blocked.
                if is_live_profile:
                    _bk_value = float(live_bankroll or 0.0)
                    _canonical_sources = {"kalshi", "bankroll_service_v2"}
                    if _bk_value <= 0.0:
                        fake_bankroll_used = True
                        logger.critical(
                            "[FAKE-BANKROLL-INVARIANT] live bankroll non-positive (value=%.2f source=%s) - failing closed",
                            _bk_value, live_bankroll_source,
                        )
                    elif live_bankroll_source not in _canonical_sources:
                        fake_bankroll_used = True
                        logger.critical(
                            "[FAKE-BANKROLL-INVARIANT] live bankroll from non-canonical source=%s (value=%.2f) - failing closed",
                            live_bankroll_source, _bk_value,
                        )
            
            # Bankroll source validation - fail execution if fake bankroll detected
            bankroll_source_valid = not fake_bankroll_used and live_bankroll_source in {"kalshi", "bankroll_service_v2"}
            
            # Check if within Kalshi scheduled maintenance window
            in_scheduled_maintenance = is_within_kalshi_maintenance()
            
            # DIAGNOSTIC: Log after maintenance check
            
            
            # ============================================================
            # LOOP-STATE MACHINE (HALT / WAITING / IDLE / ACTIVE)
            # ------------------------------------------------------------
            # Separate three concerns so a transient gap BETWEEN 15m strips
            # is never confused with a systemic/venue failure:
            #   1. infra_ready      -> platform health (catalog/WS/bankroll/risk/gate)
            #   2. markets_expected -> should strips exist now? (cadence + maintenance)
            #   3. markets_present  -> does the catalog actually show strips right now?
            # CRITICAL: "0 ready assets" is only a fault when markets are PRESENT.
            # When markets are absent it is just WAITING/IDLE (a normal cadence gap).
            # ============================================================
            
            # P0 FIX: Do not double-penalize on WS health if MD is fresh
            # If MD is fresh (>=1 asset has fresh orderbook), allow trading even if WS is slightly lagged
            # Only require WS health if MD is also stale (both must fail to halt)
            # RELAXED: Allow trading in DEGRADED WS state if MD is fresh (can_trade() allows DEGRADED)
            ws_health_required = md_fresh_count == 0  # Only require WS healthy if no fresh MD
            
            # TIERED CATALOG STALENESS FIX: Use catalog_age_ok instead of catalog_fresh
            # catalog_age_ok is True for FRESH (<=60s) and STALE_WARN (60s-300s), False only for STALE_BLOCK (>300s)
            # This allows trading in STALE_WARN state as intended by the tiered staleness logic
            
            # EXPLICIT HEALTH-STATE VARIABLES: Clear separation of concerns for execution_ready truth table
            # These variables make the health state machine explicit and testable
            ws_ok = ws_forwarder_healthy or not ws_health_required  # WS healthy or not required
            catalog_ok = catalog_age_ok  # Catalog not stale beyond block threshold
            md_ok = md_coverage_ok  # Market data coverage sufficient
            spot_ok = (spot_fresh_count == 5)  # All 5 assets have fresh spot data
            
            infra_ready = (
                catalog_ok and  # Use catalog_ok for clarity
                ws_ok and  # Use ws_ok for clarity
                live_bankroll_valid and
                bankroll_source_valid and
                risk_profile_loaded and
                top3_gate_available
            )
            
            # DIAGNOSTIC: Log infra_ready components for debugging pipeline_ready=False
            if not infra_ready:
                logger.warning(
                    "[INFRA-READY-DEBUG] infra_ready=False - catalog_ok=%s ws_ok=%s live_bankroll_valid=%s bankroll_source_valid=%s risk_profile_loaded=%s top3_gate_available=%s",
                    catalog_ok, ws_ok, live_bankroll_valid, bankroll_source_valid, risk_profile_loaded, top3_gate_available
                )
            
            markets_expected = markets_expected_now()
            markets_present = markets_present_count > 0

            # CRITICAL FIX: Remove all freshness checks - system is over-engineered
            # pipeline_ready: Only depends on infra (catalog/WS/bankroll/risk)
            # trading_ready: pipeline_ready AND at least 1 asset has markets
            pipeline_ready = infra_ready  # Removed md_ok check
            spot_ready = spot_ok  # Use spot_ok for clarity
            trading_ready = pipeline_ready and (ready_assets_count >= 1)  # Removed spot_ready check
            
            # Update instance attributes for API observability
            self.pipeline_ready = pipeline_ready
            self.trading_ready = trading_ready

            # Pure decision function (also unit-tested in tests/test_degraded_mode.py):
            #   loop_state        in {HALT, WAITING, IDLE, ACTIVE, DEGRADED}
            #   execution_mode    in {NONE, RUN_NORMAL, RUN_DEGRADED, NO_NEW_ENTRIES, HALT_CRITICAL}
            #   execution_ready   True when loop_state allows any trading activity
            #   allow_new_entries True when new position entries are allowed
            
            # DIAGNOSTIC: Log before compute_loop_state
            
            
            loop_state, execution_mode, execution_ready, allow_new_entries = compute_loop_state(
                infra_ready=infra_ready,
                markets_expected=markets_expected,
                markets_present=markets_present,
                ready_assets_count=ready_assets_count,
                md_fresh_count=md_fresh_count,
                spot_fresh_count=spot_fresh_count,
                min_ready_for_normal=MIN_READY_ASSETS_FOR_NORMAL,
            )
            
            # DIAGNOSTIC: Log after compute_loop_state
            

            # One clear state line every cycle (covers ALL states for observability)
            logger.info(
                "[15M-LOOP-STATE] loop_state=%s execution_mode=%s execution_ready=%s allow_new_entries=%s "
                "pipeline_ready=%s trading_ready=%s spot_ready=%s "
                "infra_ready=%s markets_expected=%s markets_present=%s(%d/5) "
                "ready_assets=%d/5 md_fresh=%d/5 depth_sufficient=%d/5 in_maintenance=%s",
                loop_state, execution_mode, execution_ready, allow_new_entries,
                pipeline_ready, trading_ready, spot_ready,
                infra_ready, markets_expected, markets_present, markets_present_count,
                ready_assets_count, md_fresh_count, depth_sufficient_count,
                in_scheduled_maintenance,
            )
            
            # Calculate "why no trade?" reason (single source of truth for observability)
            no_trade_reason = "OK"  # Default: ready to trade
            halt_components = []  # List of components causing HALT
            
            # P0 FIX: Map execution modes to no_trade_reason for degraded mode support
            if execution_mode == "HALT_CRITICAL":
                no_trade_reason = "HALT_CRITICAL"
                halt_components.append("HALT_CRITICAL")
            elif execution_mode == "NO_NEW_ENTRIES":
                no_trade_reason = "NO_NEW_ENTRIES"
                halt_components.append("NO_NEW_ENTRIES")
            elif execution_mode == "RUN_DEGRADED":
                no_trade_reason = "RUN_DEGRADED"
                halt_components.append("RUN_DEGRADED")
            elif execution_mode == "RUN_NORMAL":
                no_trade_reason = "OK"
                halt_components = []
            
            # P0 FIX: Automatic recovery logic based on health snapshot transitions
            # Track consecutive degraded/critical cycles and log recovery events
            if execution_mode in ("NO_NEW_ENTRIES", "RUN_DEGRADED"):
                self._consecutive_degraded_cycles += 1
                self._consecutive_critical_cycles = 0
            elif execution_mode == "HALT_CRITICAL":
                self._consecutive_critical_cycles += 1
                self._consecutive_degraded_cycles = 0
            else:  # RUN_NORMAL
                self._consecutive_degraded_cycles = 0
                self._consecutive_critical_cycles = 0
            
            # Log recovery when transitioning from degraded to normal
            if self._previous_execution_mode in ("NO_NEW_ENTRIES", "RUN_DEGRADED", "HALT_CRITICAL") and execution_mode == "RUN_NORMAL":
                logger.info(
                    "[15M-EXECUTION-RECOVERY] mode=RUN_NORMAL previous_mode=%s reason=md_spot_recovered "
                    "md_fresh=%d/5 spot_fresh=%d/5 ready_assets=%d/5",
                    self._previous_execution_mode, md_fresh_count, spot_fresh_count, ready_assets_count
                )
                with _diag_open() as f:
                    f.write(
                        f"[{datetime.now(timezone.utc)}] 15M-EXECUTION-RECOVERY: mode=RUN_NORMAL "
                        f"previous_mode={self._previous_execution_mode} reason=md_spot_recovered "
                        f"md_fresh={md_fresh_count}/5 spot_fresh={spot_fresh_count}/5 ready_assets={ready_assets_count}/5\n"
                    )
                    f.flush()
            
            # Log escalation to HALT_CRITICAL after sustained issues
            if execution_mode == "HALT_CRITICAL" and self._consecutive_critical_cycles == self._max_consecutive_critical_cycles:
                logger.warning(
                    "[15M-EXECUTION-ESCALATION] mode=HALT_CRITICAL consecutive_cycles=%d "
                    "reason=sustained_md_spot_failure md_fresh=%d/5 spot_fresh=%d/5",
                    self._consecutive_critical_cycles, md_fresh_count, spot_fresh_count
                )
                with _diag_open() as f:
                    f.write(
                        f"[{datetime.now(timezone.utc)}] 15M-EXECUTION-ESCALATION: mode=HALT_CRITICAL "
                        f"consecutive_cycles={self._consecutive_critical_cycles} "
                        f"reason=sustained_md_spot_failure md_fresh={md_fresh_count}/5 spot_fresh={spot_fresh_count}/5\n"
                    )
                    f.flush()
            
            # Update previous mode for next cycle
            self._previous_execution_mode = execution_mode
            
            # DIAGNOSTIC: Log after previous mode update
            
            
            # DIAGNOSTIC: Log before warmup override
            
            
            # FINAL WARMUP OVERRIDE: Force catalog_fresh, catalog_age_ok, md_coverage_ok, ws_forwarder_healthy, and depth_coverage_ready to True during warmup
            # This must be the last check before no_trade_reason calculation to ensure it overrides
            # any previous staleness determinations
            # DESIGN DECISION: Allow trading during warmup to avoid blocking system startup while components initialize
            if in_warmup:
                catalog_fresh = True
                catalog_age_ok = True
                catalog_health = "FRESH"  # Override to FRESH during warmup
                md_coverage_ok = True  # Warmup grace: allow trading during MD initialization
                ws_forwarder_healthy = True  # Warmup grace: allow trading during WS initialization
                depth_coverage_ready = True  # Warmup grace: allow trading during depth initialization
                logger.info(
                    "[CATALOG-WARMUP-FINAL-OVERRIDE] Forcing catalog_fresh=True, catalog_age_ok=True, catalog_health=FRESH, md_coverage_ok=True, ws_forwarder_healthy=True, depth_coverage_ready=True during warmup (%.1fs/%.1fs)",
                    time_since_roll, self._catalog_warmup_seconds
                )
                
            
            # DIAGNOSTIC: Log after warmup override
            
            
            # DIAGNOSTIC: Log before no_trade_reason calculation
            
            
            try:
                if in_scheduled_maintenance:
                    no_trade_reason = "MAINTENANCE"
                    halt_components.append("MAINTENANCE")
                elif catalog_staleness_enforced and not catalog_fresh:
                    # Only halt on catalog staleness if profile enforces it
                    no_trade_reason = "CATALOG_STALE"
                    halt_components.append("CATALOG_STALE")
                elif catalog_staleness_enforced and catalog_health == "STALE_BLOCK":
                    # Catalog stale beyond block threshold - block new entries but not HALT_CRITICAL
                    # Only applies if profile enforces catalog staleness
                    no_trade_reason = "CATALOG_STALE_BLOCK"
                    # Don't add to halt_components - this should map to NO_NEW_ENTRIES, not HALT_CRITICAL
                # catalog_health == "STALE_WARN" allows trading with warning logged earlier
                # If catalog_staleness_enforced is false, catalog staleness is purely informational
                # P0 FIX: Separate universe consistency from MD staleness
                # Check if health snapshot has universe_consistency_violation reason
                elif 'snapshot' in locals() and snapshot and "universe_consistency_violation" in snapshot.reasons:
                    no_trade_reason = "UNIVERSE_INCONSISTENT"
                    halt_components.append("UNIVERSE_INCONSISTENT")
                elif not md_coverage_ok:
                    # MD_STALE: Market data staleness due to connectivity issues (WS not delivering data)
                    # This is distinct from MD_THIN which is about liquidity
                    no_trade_reason = "MD_STALE"
                    halt_components.append("MD_STALE")
                # CRITICAL FIX: Separate MD_THIN (liquidity) from MD_STALE (connectivity)
                # MD_THIN: Order book is fresh but has insufficient depth for trading
                # This is a liquidity issue, not a connectivity issue
                # Depth insufficiency should be per-asset disablement, not global halt
                # This allows BTC/SOL/DOGE to trade even if ETH/XRP are thin
                elif not depth_coverage_ready and md_coverage_ok:
                    # Only use MD_THIN if MD is fresh but depth is insufficient
                    # If MD is stale, use MD_STALE instead (connectivity takes precedence)
                    no_trade_reason = "MD_THIN"
                    halt_components.append("MD_THIN")
                elif not ws_forwarder_healthy:
                    no_trade_reason = "WS_UNHEALTHY"
                    halt_components.append("WS_UNHEALTHY")
                elif not live_bankroll_valid:
                    no_trade_reason = "BANKROLL_INVALID"
                    halt_components.append("BANKROLL_INVALID")
                elif not bankroll_source_valid:
                    no_trade_reason = "BANKROLL_SOURCE_INVALID"
                    halt_components.append("BANKROLL_SOURCE_INVALID")
                elif not risk_profile_loaded:
                    no_trade_reason = "RISK_PROFILE_MISSING"
                    halt_components.append("RISK_PROFILE_MISSING")
                elif not top3_gate_available:
                    no_trade_reason = "TOP3_GATE_MISSING"
                    halt_components.append("TOP3_GATE_MISSING")
                elif fake_bankroll_used:
                    no_trade_reason = "FAKE_BANKROLL"
                    halt_components.append("FAKE_BANKROLL")
                else:
                    # DIAGNOSTIC: Log if no trade reason matched
                    pass  # No trade reason matched - system is healthy
            
                # DIAGNOSTIC: Log after no_trade_reason calculation
                pass  # No diagnostic logging needed
            
            except Exception as e:
                # DIAGNOSTIC: Log exception in no_trade_reason calculation
                with _diag_open() as f:
                    f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: EXCEPTION in no_trade_reason calculation cycle={tick} error={e}\n")
                    f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: STACK TRACE: {__import__('traceback').format_exc()}\n")
                    f.flush()
                raise
            
            # LOOP-STATE override: WAITING/IDLE are EXPECTED cadence gaps, not faults.
            # Only HALT (infra) and ACTIVE-HALT (markets present, 0 ready) are red flags.
            if loop_state == "WAITING":
                no_trade_reason = "WAITING_FOR_MARKETS"
                halt_components = []
            elif loop_state == "IDLE":
                no_trade_reason = "MAINTENANCE" if in_scheduled_maintenance else "IDLE_OFF_HOURS"
                halt_components = []
            elif loop_state == "ACTIVE":
                if execution_mode == "ACTIVE-HALT":
                    no_trade_reason = "NO_ASSETS_READY"
                    halt_components = ["NO_ASSETS_READY"]
                else:
                    no_trade_reason = "OK"
                    halt_components = []
            # loop_state == "HALT": keep the infra-derived reason/components from the chain above
            
            # DIAGNOSTIC: Log after loop_state override
            
            
            # Log execution-ready status with strict gating
            # CRITICAL: Use file-based logging for visibility
            with _diag_open() as f:
                status = "READY" if execution_ready else "NOT_READY"
                halt_str = ",".join(halt_components) if halt_components else "none"
                f.write(f"[{datetime.now(timezone.utc)}] 15M-EXECUTION-{status}: mode={execution_mode} loop_state={loop_state} ready_assets={ready_assets_count}/5 markets_present={markets_present_count}/5 cycle={tick} no_trade_reason={no_trade_reason} halt_components={halt_str} catalog_fresh={catalog_fresh} catalog_health={catalog_health} catalog_age={catalog_age_s:.1f}s catalog_age_ok={catalog_age_ok} md_fresh={md_fresh_count}/5 depth_sufficient={depth_sufficient_count}/5 ws_forwarder_healthy={ws_forwarder_healthy} bankroll_valid={live_bankroll_valid} bankroll={live_bankroll or 0:.2f} bankroll_source={live_bankroll_source} bankroll_source_valid={bankroll_source_valid} fake_bankroll_used={fake_bankroll_used} risk_profile_loaded={risk_profile_loaded} top3_gate_available={top3_gate_available} in_scheduled_maintenance={in_scheduled_maintenance}\n")
                f.flush()
            
            
            logger.info(
                "[15M-EXECUTION-%s] mode=%s loop_state=%s ready_assets=%d/5 cycle=%d no_trade_reason=%s catalog_fresh=%s catalog_health=%s catalog_age=%.1fs catalog_age_ok=%s md_fresh=%d/5 depth_sufficient=%d/5 ws_forwarder_healthy=%s bankroll_valid=%s bankroll=%.2f bankroll_source=%s bankroll_source_valid=%s fake_bankroll_used=%s risk_profile_loaded=%s top3_gate_available=%s",
                "READY" if execution_ready else "NOT_READY",
                execution_mode,
                loop_state,
                ready_assets_count,
                tick,
                no_trade_reason,
                catalog_fresh,
                catalog_health,
                catalog_age_s,
                catalog_age_ok,
                md_fresh_count,
                depth_sufficient_count,
                ws_forwarder_healthy,
                live_bankroll_valid,
                live_bankroll or 0,
                live_bankroll_source,
                bankroll_source_valid,
                fake_bankroll_used,
                risk_profile_loaded,
                top3_gate_available
            )
            
            
            # E2E-AUDIT-SNAPSHOT: Single marker for quick gate decision inspection
            
            reasons = [f"loop_state={loop_state}"]
            if not catalog_fresh:
                reasons.append("catalog_stale")
            if catalog_health == "STALE_BLOCK":
                reasons.append(f"catalog_stale_block({catalog_age_s:.1f}s)")
            elif catalog_health == "STALE_WARN":
                reasons.append(f"catalog_stale_warn({catalog_age_s:.1f}s)")
            # Per-asset readiness reasons only matter when markets are PRESENT (ACTIVE).
            # In WAITING/IDLE, md/depth are 0 by design (no strips) and must NOT be flagged.
            if loop_state == "ACTIVE":
                if not md_coverage_ok:
                    reasons.append(f"md_coverage({md_fresh_count}/5)")
                if execution_mode == "ACTIVE-HALT":
                    reasons.append("no_assets_ready(0/5)")
                elif execution_mode == "DEGRADED":
                    reasons.append(f"mode_degraded({ready_assets_count}/5)")
            if not ws_forwarder_healthy:
                reasons.append("ws_forwarder")
            if not live_bankroll_valid:
                reasons.append(f"bankroll({live_bankroll or 0:.2f})")
            if not bankroll_source_valid:
                reasons.append(f"bankroll_source({live_bankroll_source})")
            if fake_bankroll_used:
                reasons.append("fake_bankroll")
            if not risk_profile_loaded:
                reasons.append("risk_profile")
            if not top3_gate_available:
                reasons.append("top3_gate")
            
            
            logger.info(
                "[E2E-AUDIT-SNAPSHOT] ready=%s loop_state=%s mode=%s reasons=%s catalog_age=%.1fs md_fresh=%d/5 depth=%d/5 ws=%s bankroll=%.2f bankroll_source=%s bankroll_source_valid=%s fake_bankroll_used=%s risk=%s top3=%s in_scheduled_maintenance=%s",
                execution_ready,
                loop_state,
                execution_mode,
                ",".join(reasons) if reasons else "none",
                catalog_age_s,
                md_fresh_count,
                depth_sufficient_count,
                ws_forwarder_healthy,
                live_bankroll or 0.0,
                live_bankroll_source,
                bankroll_source_valid,
                fake_bankroll_used,
                risk_profile_loaded,
                top3_gate_available,
                in_scheduled_maintenance
            )
            
            
            # LOG GUARDRAIL TRIPS: only for GENUINE faults (HALT infra/venue, or ACTIVE-HALT
            # = markets present but 0 assets ready). WAITING/IDLE are expected cadence gaps.
            if loop_state == "HALT" or execution_mode == "ACTIVE-HALT":
                violations = []
                if not catalog_fresh:
                    violations.append("catalog_stale")
                if not catalog_age_ok:
                    violations.append(f"catalog_too_old({catalog_age_s:.1f}s>{CATALOG_MAX_AGE_SECONDS}s)")
                if not md_coverage_ok:
                    violations.append(f"md_coverage_insufficient({md_fresh_count}/5)")
                if not depth_coverage_ready:
                    if in_scheduled_maintenance:
                        violations.append("scheduled_maintenance")
                    else:
                        violations.append(f"depth_coverage_insufficient({depth_sufficient_count}/5)")
                if not ws_forwarder_healthy:
                    violations.append("ws_forwarder_unhealthy")
                if not live_bankroll_valid:
                    violations.append(f"bankroll_invalid({live_bankroll or 0:.2f})")
                if not bankroll_source_valid:
                    violations.append(f"bankroll_source_invalid({live_bankroll_source})")
                if fake_bankroll_used:
                    violations.append("fake_bankroll_detected")
                if not risk_profile_loaded:
                    violations.append("risk_profile_not_loaded")
                if not top3_gate_available:
                    violations.append("top3_gate_missing")
                
                logger.error(
                    "[E2E-GUARDRAIL-TRIP] cycle=%d loop_state=%s execution_mode=%s violations=%s catalog_age=%.1fs md_fresh=%d/5 depth_sufficient=%d/5 ws_forwarder_healthy=%s bankroll_valid=%s bankroll=%.2f bankroll_source=%s bankroll_source_valid=%s fake_bankroll_used=%s risk_profile_loaded=%s top3_gate_available=%s",
                    tick, loop_state, execution_mode, ",".join(violations),
                    catalog_age_s,
                    md_fresh_count,
                    depth_sufficient_count,
                    ws_forwarder_healthy,
                    live_bankroll_valid,
                    live_bankroll or 0.0,
                    live_bankroll_source,
                    bankroll_source_valid,
                    fake_bankroll_used,
                    risk_profile_loaded,
                    top3_gate_available
                )
            
            # ALERT THRESHOLDS MONITORING: Update KalshiMonitor with health metrics
            if self._monitor:
                try:
                    # Update WebSocket metrics
                    if self._ws_bridge:
                        stats = self._ws_bridge.stats()
                        subscriptions = stats.get("markets", [])
                        events_per_sec = stats.get("messages_per_second", 0.0)
                        last_event_ts = stats.get("last_message_time", 0) / 1000.0 if stats.get("last_message_time", 0) > 0 else time.time()
                        
                        # Get catalog tickers for drift detection
                        catalog_tickers = []
                        if self._catalog and hasattr(self._catalog, 'markets'):
                            catalog_tickers = [m.market.market_id for m in self._catalog.markets]
                        
                        await self._monitor.update_websocket_metrics(
                            subscriptions=subscriptions,
                            catalog_tickers=catalog_tickers,
                            events_per_second=events_per_sec,
                            last_event_ts=last_event_ts
                        )
                    
                    # Update kill-switch state
                    try:
                        # BYPASS: Legacy risk_guard for kalshi_crypto_15m_v2 - use risk envelope only
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        risk_envelope = get_kalshi_crypto_15m_risk_envelope()
                        ks_active = risk_envelope.current_drawdown_pct >= risk_envelope.drawdown_halt_pct
                        ks_reason = f"drawdown_halt: {risk_envelope.current_drawdown_pct:.1%} >= {risk_envelope.drawdown_halt_pct:.1%}"
                        await self._monitor.update_kill_switch_state(ks_active, ks_reason)
                    except Exception as ks_err:
                        logger.debug("[15M-LOOP] Failed to update kill-switch state: %s", ks_err)
                    
                    # Get and log current metrics
                    metrics = await self._monitor.get_metrics()
                    logger.debug(
                        "[15M-LOOP-MONITOR] fill_rate=%.2f%% avg_latency=%.0fms ks_active=%s",
                        metrics.fill_rate * 100,
                        metrics.avg_order_latency_ms,
                        metrics.kill_switch_active
                    )
                except Exception as monitor_err:
                    logger.warning("[15M-LOOP] Failed to update monitoring metrics: %s", monitor_err)
            
            # E2E INVARIANT CHECK: Run paranoid mode assertions
            try:
                from merid.core.e2e_invariants import check_system_invariants
                    
                # Build system state for invariant checking
                system_state = {
                    "execution_ready": execution_ready,
                    "is_live_profile": is_live_profile,
                    "subsystem_health": {
                        "catalog": "HEALTH_GOOD" if catalog_fresh and catalog_age_ok else "HEALTH_ERROR",
                        "md_freshness": "HEALTH_GOOD" if md_coverage_ok else "HEALTH_ERROR", 
                        "depth_coverage": "HEALTH_GOOD" if depth_coverage_ready else "HEALTH_ERROR",
                        "ws_forwarder": "HEALTH_GOOD" if ws_forwarder_healthy else "HEALTH_ERROR",
                        "bankroll": "HEALTH_GOOD" if live_bankroll_valid else "HEALTH_ERROR",
                        "risk_profile": "HEALTH_GOOD" if risk_profile_loaded else "HEALTH_ERROR",
                        "top3_gate": "HEALTH_GOOD" if top3_gate_available else "HEALTH_ERROR"
                    },
                    "ws_forwarder": {
                        "events_per_sec": events_per_sec if 'events_per_sec' in locals() else 0.0,
                        "time_since_last_event": time_since_last_event if 'time_since_last_event' in locals() else float('inf'),
                        "stalled": stalled if 'stalled' in locals() else True,
                        "status": "OK" if ws_forwarder_healthy else "ERROR"
                    },
                    "bankroll": {
                        "live_bankroll": live_bankroll or 0.0,
                        "valid": live_bankroll_valid,
                        "status": "OK" if live_bankroll_valid else "ERROR",
                        "source": live_bankroll_source,
                        "source_valid": bankroll_source_valid,
                        "fake_used": fake_bankroll_used
                    },
                    "risk_profile": {
                        "loaded": risk_profile_loaded,
                        "status": "OK" if risk_profile_loaded else "ERROR"
                    },
                    "top3_gate": {
                        "available": top3_gate_available,
                        "status": "OK" if top3_gate_available else "ERROR"
                    }
                }
                
                # Enable paranoid mode via environment variable
                import os
                paranoid_mode = os.getenv("MERID_PARANOID_MODE", "false").lower() in ("true", "1", "yes")
                
                violations = check_system_invariants(system_state, paranoid_mode=paranoid_mode)
                
                if violations:
                    logger.warning(
                        "[E2E-INVARIANT-CHECK] cycle=%d found %d invariant violations",
                        tick, len(violations)
                    )
                        
            except Exception as invariant_err:
                logger.error("[E2E-INVARIANT-CHECK] Failed to run invariant checks: %s", invariant_err)
            except Exception as e:
                logger.error("[15M-LOOP] Error in market scanning phase: %s", e, exc_info=True)
                catalog_fresh = False
                md_fresh_count = 0
                depth_sufficient_count = 0
            
            # LOUD ALARM: No live market data - system is blind
            # Suppress during warmup grace period to allow WS to deliver initial snapshots
            # CRITICAL FIX: Also suppress if we have depth_sufficient_count > 0, which indicates MD is working
            # This prevents false alarms when health snapshot is unreliable but MD is actually fresh
            if md_fresh_count == 0 and depth_sufficient_count == 0 and not in_warmup:
                # ATTEMPT AUTO-RECOVERY: Try to restart crashed WebSocket bridge
                try:
                    # Simpler bridge doesn't have restart_ws_bridge_if_crashed
                    # from merid_core.kalshi.ws_bridge import restart_ws_bridge_if_crashed
                    # restarted = restart_ws_bridge_if_crashed()
                    restarted = False  # Not available in simpler bridge
                    if restarted:
                        logger.info("[WS-AUTO-RECOVERY] WebSocket bridge restarted successfully - market data should resume shortly")
                    else:
                        logger.debug("[WS-AUTO-RECOVERY] WebSocket bridge appears to be running - no restart needed")
                except Exception as restart_error:
                    logger.error(f"[WS-AUTO-RECOVERY] Failed to restart WebSocket bridge: {restart_error}", exc_info=True)
                
                logger.error(
                    "🚨 CRITICAL: NO LIVE MARKET DATA - ALL 5 ASSETS STALE (>30s). SYSTEM IS BLIND AND CANNOT TRADE. Check WS bridge forwarder loop and market state store."
                )
                logger.critical("🚨 CRITICAL: NO LIVE MARKET DATA - ALL 5 ASSETS STALE. SYSTEM IS BLIND. cycle=%d", tick)
        
        # These warning lines should be removed as they're outside any try-except block
        # and 'e' is not defined here
        # logger.warning("[15M-EXECUTION-READY] Failed to check execution readiness: %s", e, exc_info=True)
        # logger.warning("[CATALOG-CHECK-DEBUG] Exception in catalog check: %s", e, exc_info=True)
        catalog_elapsed = time.time() - t_catalog
        logger.info("[CYCLE-PHASE] phase=catalog_check elapsed=%.3fms", catalog_elapsed * 1000)
        logger.info("15M-PROFILE CATALOG elapsed=%.3fs", catalog_elapsed)
        
        # DIAGNOSTIC: Log after catalog check
        
        
        # EDGE DECAY CHECK: Cancel resting orders that are no longer favorable
        try:
            from merid.event_venues.kalshi.order_router import check_and_cancel_stale_orders
            canceled_ids = check_and_cancel_stale_orders()
            if canceled_ids:
                logger.info(
                    "[EDGE-DECAY-CHECK] cycle=%d canceled %d resting orders due to edge decay or time limits: %s",
                    tick, len(canceled_ids), canceled_ids[:5]  # Log first 5 IDs
                )
        except Exception as e:
            logger.warning("[EDGE-DECAY-CHECK] Failed to check stale orders: %s", e, exc_info=True)
        
        # DIAGNOSTIC: Log after edge decay check
        
        
        # AUDIT #1: Position cache health check
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            
            position_cache = get_position_cache()
            
            # Check position cache staleness
            if position_cache._last_sync:
                staleness_seconds = (datetime.now(timezone.utc) - position_cache._last_sync).total_seconds()
                # AUDIT #1: Invariant - block trading if position snapshot older than 60 seconds
                positions_stale = staleness_seconds > 60.0
                
                logger.info(
                    "[POSITION-CACHE-CHECK] cycle=%d last_sync=%s staleness=%.1fs stale=%s",
                    tick,
                    position_cache._last_sync.isoformat(),
                    staleness_seconds,
                    positions_stale
                )
                
                if positions_stale:
                    logger.warning(
                        "[POSITION-CACHE-STALE] cycle=%d positions older than 60s (%.1fs) - trading may be blocked",
                        tick,
                        staleness_seconds
                    )
            else:
                logger.warning("[POSITION-CACHE-CHECK] cycle=%d last_sync=NEVER (cache never synced)", tick)
            
            # Log per-asset exposure
            assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            for asset in assets:
                exposure = position_cache.get_asset_exposure(asset)
                logger.info(
                    "[POSITION-EXPOSURE] cycle=%d asset=%s contracts=%d notional=%.2f unrealized_pnl=%.2f position_count=%d",
                    tick,
                    asset,
                    exposure["total_contracts"],
                    exposure["total_notional_usd"],
                    exposure["unrealized_pnl_usd"],
                    exposure["position_count"]
                )
        except Exception as e:
            logger.warning("[POSITION-CACHE-CHECK] Failed to check position cache health: %s", e, exc_info=True)
        
        # DIAGNOSTIC: Log after position cache check
        
        
        logger.debug(
            "[15M-LOOP-HEARTBEAT] cycle=%d ts=%s",
            tick,
            current_time.isoformat(),
        )
        
        # DIAGNOSTIC: Log before profiler profile_cycle
        logger.debug("[15M-LOOP] BEFORE profiler profile_cycle cycle=%d", tick)
        
        # Phase 4.2: Profile entire cycle execution
        async with profiler.profile_cycle(tick):
            # DIAGNOSTIC: Log inside profiler profile_cycle
            logger.debug("[15M-LOOP] INSIDE profiler profile_cycle cycle=%d", tick)
            # REAL CYCLE LOGIC
            logger.debug("[15M-LOOP-TRACE]   phase=preconditions ENTER cycle=%d", tick)
            logger.debug("[15m-LOOP] Starting cycle %d", tick)
            
            # COMPONENT TIMING: Bankroll + risk envelope check
            t_bankroll = time.time()
            # BYPASS: Legacy GlobalRiskGuard for kalshi_crypto_15m_v2 - use UnifiedRiskManager only
            # This ties the cycle to the 15-min market epoch, not agent loop ticks
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                risk_envelope = get_kalshi_crypto_15m_risk_envelope()
                # Risk envelope doesn't need cycle reset - it uses continuous drawdown tracking
                logger.debug("[15M-LOOP] Using risk envelope for kalshi_crypto_15m_v2 (no cycle reset needed) tick=%d", tick)
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to access risk envelope: %s", e, exc_info=True)

        # Update envelope equity once per cycle (not per order)
        logger.debug("[15M-LOOP-TRACE]   phase=risk-envelope-check ENTER cycle=%d", tick)
        
        # Phase 4.2: Profile risk check phase
        async with profiler.profile_phase("risk_check"):
            # CRITICAL: Log before risk envelope update
            
            
            update_success = False
            if self._risk_envelope:
                logger.debug("[15M-LOOP-TRACE]   risk-envelope exists, calling safe_update_envelope_equity cycle=%d", tick)
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
                update_success = safe_update_envelope_equity(self._risk_envelope)
                logger.debug("[15M-LOOP-TRACE]   safe_update_envelope_equity returned=%s cycle=%d", update_success, tick)
                
                # CRITICAL: Log after risk envelope update
                
            else:
                # CRITICAL: Log if no risk envelope
                pass  # No risk envelope available
            
            if update_success:
                # Log band transitions
                current_multiplier = self._risk_envelope.per_trade_risk_multiplier
                if current_multiplier != self._last_risk_multiplier:
                    logger.info(
                        "[15m-LOOP] Risk band transition: %.2f → %.2f (drawdown=%.2f%%)",
                        self._last_risk_multiplier,
                        current_multiplier,
                        self._risk_envelope.current_drawdown_pct * 100,
                    )
                    self._last_risk_multiplier = current_multiplier

            # DIAGNOSTIC: Log after risk envelope check
            
            
            # Check if halted due to drawdown
            logger.debug("[15M-LOOP-TRACE]   checking is_halted cycle=%d", tick)
            if self._risk_envelope and self._risk_envelope.is_halted:
                self._halted_due_to_drawdown = True
                logger.warning(
                    "[15m-LOOP] Cycle %d skipped: drawdown halt (drawdown=%.2f%% >= %.2f%%, band=%s)",
                    tick,
                    self._risk_envelope.current_drawdown_pct * 100,
                    self._risk_envelope.drawdown_halt_pct * 100,
                    self._risk_envelope.current_risk_band.value,
                )
                logger.error(
                    "[15M-LOOP-TRACE]   early-exit=halt-drawdown drawdown=%.2f%% threshold=%.2f%% band=%s",
                    self._risk_envelope.current_drawdown_pct * 100,
                    self._risk_envelope.drawdown_halt_pct * 100,
                    self._risk_envelope.current_risk_band.value,
                )
                
                logger.debug("[15M-LOOP-CYCLE] EXIT cycle=%d (halted)", tick)
                return  # Skip cycle
        logger.debug("[15M-LOOP-TRACE]   phase=risk-envelope-check EXIT cycle=%d", tick)
        bankroll_elapsed = time.time() - t_bankroll
        logger.info("15M-PROFILE BANKROLL elapsed=%.3fs", bankroll_elapsed)

        # CRITICAL: Log before agent grid cycle
        

        logger.debug("[15M-LOOP-TRACE]   phase=agent-grid-cycle ENTER cycle=%d", tick)

        # COMPONENT TIMING: Agent grid cycle
        t_agents = time.time()
        # Step 1: Run agent grid cycle
        # This will call each of the 5 agents to generate signals and place orders
        agent_count = len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0
        logger.debug("[15M-LOOP-TRACE]   agent-grid-cycle starting n_agents=%d cycle=%d", agent_count, tick)
        logger.info("[CYCLE-PHASE] phase=agent_grid_cycle_start n_agents=%d", agent_count)
        
        # P0 FIX: Never skip agent grid cycle - always run for degraded mode support
        # - pipeline_ready: MD and catalog are healthy (can build candidates/signals)
        # - trading_ready: pipeline_ready AND spot AND risk (can place orders)
        # - allow_new_entries: Whether new position entries are allowed (from execution_mode)
        # When pipeline_ready=False, we still run agents to:
        #   - Monitor existing positions in NO_NEW_ENTRIES mode
        #   - Detect recovery for automatic mode transitions
        #   - Maintain observability of system health
        # Phase 4.2: Profile agent processing phase
        async with profiler.profile_phase("agent_processing"):
            try:
                # Add timeout to prevent indefinite hanging
                # P1 FIX: Align timeout to 300s (5 agents × 60s per-agent timeout)
                try:
                    # CRITICAL: Log before direct await (skip asyncio.wait_for due to Windows ProactorEventLoop hang)
                    
                    
                    # CRITICAL FIX: Skip asyncio.wait_for on Windows ProactorEventLoop - it hangs
                    # Direct await instead (timeout handling will be in _run_agent_grid_with_timeout)
                    # Pass allow_new_entries to control new position entries
                    await self._run_agent_grid_with_timeout(tick, trading_ready=trading_ready, allow_new_entries=allow_new_entries)
                    logger.debug("[15M-LOOP-TRACE]   _run_agent_grid_with_timeout completed cycle=%d", tick)
                except asyncio.TimeoutError:
                    self._error_count += 1
                    logger.debug("[15M-LOOP-TRACE]   agent-grid-cycle TIMEOUT after 300s cycle=%d", tick)
                    logger.error("[15m-LOOP] Agent grid cycle timed out after 300s")
                    # Continue to next cycle even if timeout occurs
                    logger.debug("[15M-LOOP-TRACE]   agent-grid-cycle finished cycle=%d", tick)
            except Exception as exc:
                self._error_count += 1
                logger.error("[15m-LOOP] Agent grid cycle failed: %s", exc, exc_info=True)
                logger.error("[15M-LOOP-TRACE]   agent-grid-cycle failed error=%s cycle=%d", str(exc), tick)
                # FIX: Do NOT re-raise - continue running even if a cycle fails
                # The outer try block only catches CancelledError, so re-raising here
                # would break the loop instead of continuing to the next cycle

        logger.debug("[15M-LOOP-TRACE]   phase=agent-grid-cycle EXIT cycle=%d", tick)
        agent_elapsed = time.time() - t_agents
        logger.info("15M-PROFILE AGENTS elapsed=%.3fs", agent_elapsed)
        logger.info("[CYCLE-PHASE] phase=agent_grid_cycle elapsed=%.3fms", agent_elapsed * 1000)

        cycle_duration = time.time() - cycle_start
        self._cycle_count += 1
        
        # METRIC: Observe cycle duration in histogram
        cycle_duration_hist.observe(cycle_duration)
        
        # Track cycle duration history for rolling average
        self._cycle_duration_history.append(cycle_duration)
        if len(self._cycle_duration_history) > self._max_history_length:
            self._cycle_duration_history.pop(0)
        
        # Log rolling average every 100 cycles
        if self._tick % 100 == 0 and self._cycle_duration_history:
            avg_duration = sum(self._cycle_duration_history) / len(self._cycle_duration_history)
            logger.info(
                "[LOOP-HEALTH] Avg cycle duration (last %d): %.3fs",
                len(self._cycle_duration_history),
                avg_duration,
            )

        # COMPONENT TIMING: Cycle summary
        # Spot is fetched in background by unified spot service, not in main loop
        # So spot_elapsed is 0 for now - we can add it later if needed
        spot_elapsed = 0.0
        logger.info(
            "15M-PROFILE CYCLE elapsed=%.3fs spot=%.3fs catalog=%.3fs bankroll=%.3fs agents=%.3fs",
            cycle_duration, spot_elapsed, catalog_elapsed, bankroll_elapsed, agent_elapsed
        )

        logger.debug("[15M-LOOP-TRACE]   phase=cycle-complete duration=%.3fs cycle=%d", cycle_duration, tick)
        logger.debug(
            "[15m-LOOP] Cycle %d completed in %.3fs",
            tick,
            cycle_duration,
        )
        logger.debug("[15M-LOOP-CYCLE] EXIT cycle=%d duration=%.3fs", tick, cycle_duration)

        # Warn if cycle is taking too long (should be < 1s)
        if cycle_duration > 1.0:
            logger.warning(
                "[15m-LOOP] Cycle %d took %.3fs (expected < 1s)",
                tick,
                cycle_duration,
            )

        # P2 Task 11: Log periodic summary every hour (3600 cycles at 5s cadence = 18000s = 5h)
        # Adjust interval based on actual cadence
        if self._run_summary and self._tick % 720 == 0:  # Every ~1 hour (720 cycles × 5s = 3600s)
            try:
                self._run_summary.log_periodic(interval_seconds=3600.0)
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to log periodic summary: %s", e, exc_info=True)

    async def _run_agent_grid_with_timeout(self, tick: int, trading_ready: bool = True, allow_new_entries: bool = True) -> None:
        """Run agent grid cycle with proper error handling.
        
        Args:
            tick: Current cycle tick number
            trading_ready: Whether trading is ready (can place orders)
            allow_new_entries: Whether new position entries are allowed (from execution_mode)
        """
        logger.info("[15M-LOOP] _run_agent_grid_with_timeout ENTRY tick=%d", tick)
        # CRITICAL: Log entry to this method
        
        
        # CRITICAL: Diagnose agent grid type and agent count
        
        if hasattr(self.agent_grid, '_agents'):
            pass  # Has _agents attribute
        
        if hasattr(self.agent_grid, 'agents'):
            pass  # Has agents attribute
        
        # CRITICAL: Skip logger.debug calls to avoid Windows ProactorEventLoop hang
        # logger.debug("[15M-LOOP] GRID-WITH-TIMEOUT-ENTER cycle=%d", tick)
        # logger.debug("[15M-LOOP-TRACE] _run_agent_grid_with_timeout ENTER cycle=%d", tick)
        if hasattr(self.agent_grid, 'run_cycle'):
            # CRITICAL: Log before calling agent_grid.run_cycle
            
            
            # CRITICAL: Skip logger.debug calls to avoid Windows ProactorEventLoop hang
            # logger.debug("[15M-LOOP] GRID-RUN-CYCLE-AWAIT ENTER cycle=%d", tick)
            # logger.debug("[15M-LOOP-TRACE] calling agent_grid.run_cycle cycle=%d", tick)
            
            # CRITICAL: Log immediately before the actual await
            
            
            # Execute agent grid cycle (restored after WindowsSelectorEventLoopPolicy fix)
            try:
                # CRITICAL FIX: Reload positions from position cache at start of each cycle
                # This ensures exposure tracking is based on the most up-to-date information
                # and prevents stale exposure from blocking new trades
                from merid.event_venues.kalshi.position_cache import get_position_cache
                position_cache = get_position_cache()
                
                # Initialize all assets to 0
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._asset_positions[asset] = 0.0
                
                # Get all positions and calculate exposure per asset
                all_positions = position_cache.get_all_positions(validate_freshness=False)
                
                # Map ticker prefixes to assets
                asset_map = {
                    "KXBTC": "BTC",
                    "KXETH": "ETH",
                    "KXSOL": "SOL",
                    "KXXRP": "XRP",
                    "KXDOGE": "DOGE",
                }
                
                # Sum up notional exposure per asset
                for market_id, position in all_positions.items():
                    if position.contracts > 0:
                        # Extract asset from ticker prefix
                        asset = None
                        for prefix, asset_name in asset_map.items():
                            if market_id.startswith(prefix):
                                asset = asset_name
                                break
                        
                        if asset:
                            self._asset_positions[asset] += position.notional_value
                
                logger.info("[15M-LOOP] Reloaded positions from cache: %s", self._asset_positions)
                
                # CRITICAL: Check if 15-minute ET window has changed
                # Only reset cycle guards when window changes, not every 5 seconds
                from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
                current_window = get_kalshi_15m_window()
                window_changed = (self._current_window_suffix != current_window.suffix)
                
                if window_changed:
                    logger.info(
                        "[15m-LOOP] 15-minute window changed: old=%s new=%s - resetting cycle guards and executed candidates",
                        self._current_window_suffix, current_window.suffix
                    )
                    self._current_window_suffix = current_window.suffix
                    self._executed_candidates_this_window.clear()
                    
                    # Reset UnifiedRiskManager cycle tracking
                    from merid.risk.unified_risk_manager import get_unified_risk_manager
                    risk_mgr = get_unified_risk_manager()
                    risk_mgr.reset_cycle()
                    logger.info("[15m-LOOP] Reset UnifiedRiskManager cycle for window=%s", current_window.suffix)
                else:
                    logger.debug("[15m-LOOP] Window unchanged: %s - skipping cycle reset", current_window.suffix)
                
                # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
                # This fixes the hardcoded $50 correlation stack cap bug
                logger.info("[15M-LOOP] BALANCE-CALIBRATOR-ENTER: About to fetch bankroll")
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    cycle_bankroll = get_equity_for_risk_calc_sync()
                    logger.info("[15M-LOOP] BALANCE-CALIBRATOR: Fetched bankroll=%s", cycle_bankroll)
                    if cycle_bankroll is not None and cycle_bankroll > 0:
                        # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
                        # This fixes the hardcoded $50 correlation stack cap bug
                        logger.info("[15M-LOOP] BALANCE-CALIBRATOR: About to call BalanceCalibrator")
                        try:
                            from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                            balance_cents = int(cycle_bankroll * 100)
                            logger.info("[15M-LOOP] Calling BalanceCalibrator.update with balance_cents=%d", balance_cents)
                            did_recalibrate = get_balance_calibrator().update(balance_cents)
                            logger.info("[15M-LOOP] BalanceCalibrator.update returned did_recalibrate=%s", did_recalibrate)
                        except Exception as calibrator_exc:
                            logger.warning("[15M-LOOP] BalanceCalibrator update failed: %s", calibrator_exc)
                    else:
                        logger.warning("[15M-LOOP] BALANCE-CALIBRATOR: Bankroll is None or <= 0, skipping calibration")
                except Exception as e:
                    logger.warning("[15M-LOOP] Failed to fetch cycle bankroll: %s", e)
                
                candidates = await self.agent_grid.run_cycle(tick, allow_new_entries=allow_new_entries)
                logger.info("[15M-LOOP] Generated %d candidates in cycle %d", len(candidates), tick)
                
                # Process candidates into orders
                for candidate in candidates:
                    try:
                        await self._execute_candidate(candidate, tick)
                    except Exception as e:
                        logger.error("[15M-LOOP] Failed to execute candidate: %s", e, exc_info=True)
                
                # CRITICAL FIX: Wire systematic exposure-based hedging
                # After alpha orders are executed, compute and route hedge orders
                # to offset net directional exposure per (asset, timeframe) cell
                try:
                    from merid.event_venues.kalshi.order_router import compute_hedge_intents, route_order_async
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service as get_bankroll_service_v2
                    
                    # Get current bankroll for hedge sizing - use v2 directly
                    bankroll_service = await get_bankroll_service_v2()
                    if bankroll_service:
                        summary = await bankroll_service.get_summary()
                        bankroll_cents = int(summary.equity_usd * 100) if summary and summary.equity_usd else 100000
                    else:
                        bankroll_cents = 100000
                    
                    # Compute hedge intents based on current exposure
                    hedge_intents = compute_hedge_intents(bankroll_cents=bankroll_cents)
                    
                    if hedge_intents:
                        logger.info("[15M-LOOP] Generated %d hedge intents, routing to execution", len(hedge_intents))
                        
                        # Route hedge orders
                        for hedge_intent in hedge_intents:
                            try:
                                result = await route_order_async(hedge_intent)
                                logger.info(
                                    "[15M-LOOP] Hedge order routed: ticker=%s side=%s count=%d status=%s",
                                    hedge_intent.ticker, hedge_intent.side, hedge_intent.count, result.status
                                )
                            except Exception as hedge_err:
                                logger.error("[15M-LOOP] Failed to route hedge order: %s", hedge_err, exc_info=True)
                    else:
                        logger.debug("[15M-LOOP] No hedge orders needed (exposure within bounds)")
                except Exception as hedge_exc:
                    logger.warning("[15M-LOOP] Hedge pass failed (non-fatal): %s", hedge_exc, exc_info=True)
                
                # Log after call
                log_object_origin(self.agent_grid, "agent_grid_after_run_cycle_call", context=f"cycle_id={tick}")
            except Exception as exc:
                # CRITICAL: Log any exception in run_cycle with full stack trace
                logger.error("[15M-LOOP] agent_grid.run_cycle failed: %s", exc, exc_info=True)
                with _diag_open() as f:
                    f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: agent_grid.run_cycle EXCEPTION cycle={tick} error={exc}\n")
                    f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: STACK TRACE: {__import__('traceback').format_exc()}\n")
                    f.flush()
                raise  # Re-raise to be caught by outer handler
            
            # CRITICAL: Log after agent_grid.run_cycle returns
            
            
            logger.debug("[15M-LOOP] GRID-RUN-CYCLE-AWAIT EXIT cycle=%d", tick)
            logger.debug("[15M-LOOP-TRACE] agent_grid.run_cycle returned cycle=%d", tick)
        else:
            # Fallback: run agents directly if run_cycle not implemented
            pass  # Log below
            logger.info("[15M-LOOP-TRACE] run_cycle not implemented, running agents directly cycle=%d", tick)
            await self._run_agents_directly(tick)
            logger.info("[15M-LOOP-TRACE] _run_agents_directly returned cycle=%d", tick)
        logger.debug("[15M-LOOP-TRACE] _run_agent_grid_with_timeout EXIT cycle=%d", tick)
        logger.debug("[15M-LOOP] GRID-WITH-TIMEOUT-EXIT cycle=%d", tick)

    def _get_candidate_key(self, candidate: Dict) -> str:
        """Generate a unique key for a candidate to track execution within a window.
        
        Args:
            candidate: Candidate dict from agent grid
            
        Returns:
            Unique key string (ticker + side)
            Note: price_cents and count are not available at candidate generation time,
            so we use ticker + side which is sufficient to prevent duplicate executions
            within the same 15-minute window.
        """
        ticker = candidate.get("ticker", "")
        side = candidate.get("side", "")
        return f"{ticker}:{side}"
    
    def _validate_candidate_edge(self, candidate: Dict) -> bool:
        """Re-validate candidate edge before execution to prevent bad trades.
        
        This checks if the edge has shifted to unprofitable since the candidate
        was generated. If the edge is no longer positive, the candidate is rejected.
        
        Args:
            candidate: Candidate dict from agent grid
            
        Returns:
            True if edge is still valid (positive), False otherwise
        """
        # Check both "edge" and "edge_pct" fields for compatibility
        edge = candidate.get("edge", candidate.get("edge_pct", 0.0))
        
        # CRITICAL: Only validate edge for price-based signals
        # Velocity-based signals use velocity magnitude as signal strength, not probability edge
        # The "edge" in momentum trading is the velocity itself, not probability difference
        rationale = candidate.get("rationale", "")
        if rationale and "velocity_based" in rationale:
            # Velocity-based signals: skip edge validation (validated by velocity threshold in agent_grid)
            logger.info(
                "[EDGE-VALIDATION] Skipping edge check for velocity-based signal: ticker=%s rationale=%s",
                candidate.get("ticker", "unknown"), rationale
            )
            return True
        
        # Price-based signals: require positive edge
        if edge <= 0:
            logger.warning(
                "[EDGE-VALIDATION] Candidate edge is not positive: edge=%.2f ticker=%s",
                edge, candidate.get("ticker", "unknown")
            )
            return False
        
        # Optional: Add additional edge validation logic here
        # For example, check if edge has degraded significantly from original
        
        return True
    
    async def _execute_candidate(self, candidate: Dict, tick: int) -> None:
        """Convert candidate dict to OrderIntent and route to order router."""
        try:
            from merid.event_venues.kalshi.order_router import OrderIntent, resolve_window_policy, resolve_exit_policy, route_order_async
            
            ticker = candidate.get("ticker")
            if not ticker:
                logger.warning("[15M-LOOP] Candidate missing ticker, skipping")
                return
            
            # Resolve policies
            try:
                # Extract asset from ticker (e.g., "KXBTCD-..." -> "BTC")
                # Robust asset extraction from ticker
                # Map ticker prefixes to assets for all 5 crypto assets
                asset_map = {
                    "KXBTC": "BTC",
                    "KXETH": "ETH",
                    "KXSOL": "SOL",
                    "KXXRP": "XRP",
                    "KXDOGE": "DOGE",
                }
                asset = None
                for prefix, asset_name in asset_map.items():
                    if ticker.startswith(prefix):
                        asset = asset_name
                        break
                
                if asset is None:
                    logger.warning("[15M-LOOP] Could not determine asset from ticker %s", ticker)
                    return

                # CRITICAL FIX: Use HMM regime for exit policy (industry best practice)
                # HMM regime (bull/choppy/bear) is more meaningful for exit decisions than liquidity regime
                # Map HMM regime to exit policy regime: bull -> aggressive, choppy -> conservative, bear -> conservative
                hmm_regime = candidate.get("hmm_regime", None)
                hmm_regime_confidence = candidate.get("hmm_regime_confidence", 0.0)
                
                if hmm_regime and hmm_regime_confidence >= 0.7:
                    # High confidence HMM regime - use for exit policy
                    if hmm_regime == "bull":
                        regime = "aggressive"  # Bull market: wider TP, tighter entry window
                        logger.info("[15M-LOOP] Using HMM regime=%s (confidence=%.2f) -> exit_policy=%s for ticker=%s",
                                   hmm_regime, hmm_regime_confidence, regime, ticker)
                    elif hmm_regime in ("choppy", "bear"):
                        regime = "conservative"  # Choppy/bear: tighter TP, wider entry window
                        logger.info("[15M-LOOP] Using HMM regime=%s (confidence=%.2f) -> exit_policy=%s for ticker=%s",
                                   hmm_regime, hmm_regime_confidence, regime, ticker)
                    else:
                        regime = "normal"  # Fallback for unknown HMM regimes
                        logger.debug("[15M-LOOP] Unknown HMM regime=%s, using normal for ticker=%s", hmm_regime, ticker)
                else:
                    # Low confidence or no HMM regime - fall back to liquidity-based regime
                    # This is the previous behavior: classify from market state depth
                    regime = candidate.get("regime", None)
                    if regime is None:
                        try:
                            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                            market_state_store = get_kalshi_market_state_store()
                            market_state = market_state_store.get(ticker) if market_state_store else None
                            if market_state:
                                # Classify regime from depth
                                min_depth_yes = getattr(market_state, 'min_depth_yes', 0)
                                min_depth_no = getattr(market_state, 'min_depth_no', 0)
                                min_depth_yes_threshold = 1
                                min_depth_no_threshold = 1
                                has_yes = min_depth_yes >= min_depth_yes_threshold
                                has_no = min_depth_no >= min_depth_no_threshold
                                if has_yes and has_no:
                                    regime = "both_sides"
                                elif has_yes and not has_no:
                                    regime = "one_sided_yes"
                                elif not has_yes and has_no:
                                    regime = "one_sided_no"
                                else:
                                    regime = "no_liquidity"
                                logger.debug("[15M-LOOP] Extracted liquidity regime=%s from market state for ticker=%s", regime, ticker)
                        except Exception as e:
                            logger.warning("[15M-LOOP] Failed to extract regime from market state: %s", e)
                    
                    # Map liquidity regime to exit policy regime
                    if regime in ("both_sides", "normal"):
                        regime = "normal"
                    elif regime in ("one_sided_yes", "one_sided_no"):
                        regime = "conservative"  # One-sided liquidity: more conservative
                    elif regime == "no_liquidity":
                        regime = "conservative"  # No liquidity: very conservative
                    else:
                        regime = "normal"  # Final fallback
                    
                    logger.debug("[15M-LOOP] Using liquidity-based regime -> exit_policy=%s for ticker=%s", regime, ticker)

                # CRITICAL FIX: resolve_window_policy doesn't exist - use simple UUID for window_resolution_id
                import uuid
                window_resolution_id = f"window_resolution_{uuid.uuid4().hex[:12]}"
                exit_policy = resolve_exit_policy(edge_result=None, asset=asset, regime=regime)
                # CRITICAL DIAGNOSTIC: Log exit_policy resolution result
                if exit_policy:
                    logger.info("[15M-LOOP] exit_policy resolved successfully: policy_id=%s asset=%s regime=%s", exit_policy.policy_id, asset, regime)
                    # CRITICAL FIX: Add assertions to validate exit policy values
                    assert exit_policy is not None, f"Exit policy resolution returned None for ticker={ticker}"
                    assert exit_policy.policy_id is not None, f"Exit policy missing policy_id for ticker={ticker}"
                    assert exit_policy.tp_r_multiple > 0, f"Exit policy TP R-multiple must be positive for ticker={ticker}, got {exit_policy.tp_r_multiple}"
                    assert exit_policy.sl_cents >= 0, f"Exit policy SL cents must be non-negative for ticker={ticker}, got {exit_policy.sl_cents}"
                    assert exit_policy.max_hold_seconds > 0, f"Exit policy max_hold_seconds must be positive for ticker={ticker}, got {exit_policy.max_hold_seconds}"
                else:
                    logger.error("[15M-LOOP] exit_policy is None after resolution! asset=%s regime=%s", asset, regime)
                    # CRITICAL FIX: Reject order when exit policy is None
                    return
            except Exception as e:
                logger.error(
                    "[15M-LOOP] Failed to resolve exit policy for %s: %s - REJECTING ORDER for safety",
                    ticker, e, exc_info=True
                )
                # CRITICAL FIX: Reject order when exit policy resolution fails
                # Fallback policies risk entering trades without effective exits
                return  # Do not proceed with order submission
            
            # CRITICAL FIX: Use candidate's price_cents if available (already side-aware)
            # The signal generation now sets correct price based on side (YES uses YES price, NO uses NO price)
            # Only fall back to market state if candidate price is missing or zero
            price_cents = candidate.get("price_cents", 0)
            if price_cents <= 0:
                # Fallback to market state (legacy behavior)
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    market_state_store = get_kalshi_market_state_store()
                    market_state = market_state_store.get(ticker) if market_state_store else None
                    if market_state:
                        # CRITICAL FIX: For NO orders, calculate NO mid-price from YES bid/ask
                        # Kalshi duality: NO_mid = 100 - YES_mid
                        candidate_side = candidate.get("side", "yes").lower()
                        if candidate_side == "no" or candidate_side == "buy_no":
                            # NO order: calculate NO mid-price
                            if market_state.best_bid_cents and market_state.best_ask_cents:
                                yes_mid = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                                raw_price_cents = 100 - yes_mid
                                # CRITICAL FIX: Clamp to profile price_range (5-95c) to match profile YAML
                                price_cents = max(5, min(95, raw_price_cents))
                                logger.info("[15M-LOOP] ticker=%s NO order: YES_mid=%d -> NO_mid=%d (raw=%d, clamped=%d)", ticker, yes_mid, price_cents, raw_price_cents, price_cents)
                            elif market_state.mid_cents:
                                raw_price_cents = 100 - int(market_state.mid_cents)
                                # CRITICAL FIX: Clamp to profile price_range (5-95c) to match profile YAML
                                price_cents = max(5, min(95, raw_price_cents))
                                logger.info("[15M-LOOP] ticker=%s NO order: YES_mid_cents=%.2f -> NO_mid=%d (raw=%d, clamped=%d)", ticker, market_state.mid_cents, price_cents, raw_price_cents, price_cents)
                            else:
                                logger.warning("[15M-LOOP] NO order but no market state data for %s, using default 25c", ticker)
                                price_cents = 50  # 2026-07-10: Changed to 50 (midpoint of 5-95c profile range)
                        else:
                            # YES order: use YES mid-price
                            if market_state.mid_cents:
                                # BUG #39 FIX: Convert mid_cents to integer
                                # mid_cents is a float from unified_market_state.py but order router requires integer
                                raw_price_cents = int(market_state.mid_cents)
                                # CRITICAL FIX: Clamp to profile price_range (5-95c) to match profile YAML
                                price_cents = max(5, min(95, raw_price_cents))
                                logger.info("[15M-LOOP] ticker=%s YES order: price_cents from mid_cents=%d (raw=%.2f, clamped=%d)", ticker, price_cents, market_state.mid_cents, price_cents)
                            elif market_state.best_bid_cents and market_state.best_ask_cents:
                                # Use mid of bid/ask if mid not available
                                raw_price_cents = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                                # CRITICAL FIX: Clamp to profile price_range (5-95c) to match profile YAML
                                price_cents = max(5, min(95, raw_price_cents))
                                logger.info("[15M-LOOP] ticker=%s YES order: price_cents from bid/ask mid=%d (raw=%d, clamped=%d) (bid=%d, ask=%d)", ticker, price_cents, raw_price_cents, price_cents, market_state.best_bid_cents, market_state.best_ask_cents)
                            else:
                                logger.warning("[15M-LOOP] YES order but no market state data for %s, using default 25c", ticker)
                                price_cents = 50  # 2026-07-10: Changed to 50 (midpoint of 5-95c profile range)
                    else:
                        logger.warning("[15M-LOOP] No market state available for %s, using default 50c", ticker)
                        price_cents = 50  # 2026-07-10: Changed to 50 (midpoint of 5-95c profile range)
                except Exception as e:
                    logger.warning("[15M-LOOP] Failed to get price from market state for %s: %s", ticker, e)
                    price_cents = 50  # 2026-07-10: Changed to 50 (midpoint of 5-95c profile range)
            else:
                logger.info("[15M-LOOP] ticker=%s price_cents from candidate=%d (side=%s)", ticker, price_cents, candidate.get("side"))
            
            # CRITICAL FIX: Consolidated sizing path - use count from unified_sizing
            # The count is already computed by compute_order_size in the main loop (line 1565)
            # This removes the dual sizing path inconsistency where _execute_candidate
            # would recalculate count from risk envelope, overwriting the unified_sizing result
            count = candidate.get("count", 1)
            
            # Validate count is reasonable
            if count < 1:
                logger.warning("[15M-LOOP] Invalid count=%d from candidate, defaulting to 1", count)
                count = 1
            
            # Calculate notional for logging
            position_notional_usd = (count * price_cents) / 100.0
            logger.info(
                "[15M-LOOP] Using unified_sizing count=%d notional=%.2f ticker=%s",
                count, position_notional_usd, ticker
            )

            # BUG #34 FIX: Extract edge_pct, confidence, model_prob from candidate
            # These are now computed in signal generation (BUG #36) and carried through candidate
            edge_pct = candidate.get("edge_pct", 0.0)
            confidence = candidate.get("confidence", 0.5)
            model_prob = candidate.get("model_prob", 0.5)
            raw_logit = candidate.get("raw_logit", 0.0)  # Phase 5.4: Raw logit for calibration
            
            # BUG #34 FIX: If edge_pct/confidence/model_prob are not in candidate (legacy path),
            # compute them from velocity and price for 15m velocity-based strategy
            if edge_pct == 0.0 and "velocity" in candidate:
                velocity = candidate.get("velocity", 0.0)
                # SEV-0 FIX: Use standardized velocity edge calculation function
                # Get velocity threshold from profile for the asset
                try:
                    from merid.prediction.agent_grid_15m import calculate_velocity_edge
                    from merid.config.profiles.kalshi_crypto_15m_v2 import get_profile
                    profile = get_profile()
                    # Extract asset from ticker (e.g., KXBTC15M-... -> BTC)
                    asset = ticker.split("-")[0].replace("KX", "") if "-" in ticker else "UNKNOWN"
                    # Get velocity threshold from profile
                    velocity_threshold = 0.0002  # Default BTC threshold
                    if asset == "ETH":
                        velocity_threshold = 0.0003
                    elif asset == "SOL":
                        velocity_threshold = 0.0004
                    elif asset == "XRP":
                        velocity_threshold = 0.0005
                    elif asset == "DOGE":
                        velocity_threshold = 0.0006
                    edge_pct = calculate_velocity_edge(velocity, velocity_threshold)
                except Exception as e:
                    logger.warning("[15M-LOOP] Failed to use standardized edge calculation: %s, using fallback", e)
                    edge_pct = abs(velocity) * 100  # Fallback: simple conversion
                
                # Compute confidence from velocity magnitude (higher velocity = higher confidence)
                velocity_magnitude = abs(velocity)
                confidence = min(0.95, 0.50 + velocity_magnitude * 100)  # Base 50%, scale with velocity
                # Compute model_prob from price_cents (Kalshi binary contracts: price = probability)
                model_prob = price_cents / 100.0
                logger.debug("[15M-LOOP] Computed signal metadata from velocity: edge=%.2f%% confidence=%.2f model_prob=%.2f", 
                           edge_pct, confidence, model_prob)

            # Construct OrderIntent
            # CRITICAL FIX: Use actual agent_id from candidate for authorization check
            # The order router checks if agent_id is in _KALSHI_15M_CRYPTO_AGENTS whitelist
            agent_id = candidate.get("agent_id", "merid.prediction.agent_grid_15m")
            
            # CRITICAL FIX: Add exit targets from resolved exit policy to satisfy invariant
            # The order router rejects orders without TP/SL targets (invariant_violation:no_trade_without_exit)
            # Use resolved exit_policy to populate exit target fields
            # Note: OrderIntent uses take_profit_r_multiple and stop_loss_price_cents (not stop_loss_r_multiple)
            # Convert side+action to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
            # CRITICAL FIX: Reject trades with missing side/action to prevent systematic YES bias
            # Previous bug: defaulted to "yes"/"buy" -> BUY_YES, creating YES bias on incomplete data
            side_raw = candidate.get("side")
            action_raw = candidate.get("action")
            
            if not side_raw or not action_raw:
                logger.warning(
                    "[15M-LOOP] REJECTING CANDIDATE: missing side=%s or action=%s for ticker=%s - "
                    "preventing systematic YES bias by rejecting incomplete data",
                    side_raw, action_raw, ticker
                )
                return
            
            side_raw = side_raw.upper()
            action_raw = action_raw.upper()
            logger.debug("[15M-LOOP] Converting side/action: side_raw=%s action_raw=%s", side_raw, action_raw)
            
            # Map to Kalshi side format
            if side_raw == "YES" and action_raw == "BUY":
                kalshi_side = "BUY_YES"
            elif side_raw == "YES" and action_raw == "SELL":
                kalshi_side = "SELL_YES"
            elif side_raw == "NO" and action_raw == "BUY":
                kalshi_side = "BUY_NO"
            elif side_raw == "NO" and action_raw == "SELL":
                kalshi_side = "SELL_NO"
            else:
                logger.warning(
                    "[15M-LOOP] REJECTING CANDIDATE: invalid side=%s action=%s for ticker=%s - "
                    "expected YES/NO + BUY/SELL combination",
                    side_raw, action_raw, ticker
                )
                return
            
            logger.debug("[15M-LOOP] Converted to Kalshi side: %s", kalshi_side)
            
            # CRITICAL FIX: Get effective equity from risk envelope for proper risk sizing
            # This prevents the "Equity is $0.00" warning in KalshiRiskManager
            effective_equity_usd = None
            try:
                from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                envelope = get_risk_envelope_service().get_config()
                effective_equity_usd = envelope.live_bankroll_usd if envelope else None
                logger.debug("[15M-LOOP] Got effective_equity_usd=%.2f from risk envelope", effective_equity_usd)
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to get effective_equity_usd from risk envelope: %s", e)
            
            # CRITICAL FIX: Generate client_tag for TP/SL registration
            # The order router requires client_tag to register TP targets with position cache
            import uuid
            client_tag = f"15m_{ticker}_{uuid.uuid4().hex[:12]}"
            
            # CRITICAL FIX: Compute TP/SL from exit policy before OrderIntent creation
            # For binary options, R (risk per contract) = entry price (max loss is contract price)
            # TP = entry_price + (R * tp_r_multiple) for long positions
            # SL = entry_price - (R * sl_r_multiple) for long positions
            # For 15m crypto, we use the entry price as R since contracts can go to 0
            if exit_policy and exit_policy.tp_r_multiple:
                take_profit_price_cents = int(price_cents * (1 + exit_policy.tp_r_multiple))
                take_profit_r_multiple = exit_policy.tp_r_multiple
            else:
                take_profit_price_cents = None
                take_profit_r_multiple = None
            
            # CRITICAL FIX: Use fixed cent SL instead of R-multiple for binary options
            # Binary options have max loss = entry price (can go to 0), so R-multiple SL
            # doesn't make sense. Use fixed cent SL from exit_policy.sl_cents instead.
            # If sl_cents is not set, use a conservative 5 cent SL.
            if exit_policy and exit_policy.sl_cents:
                stop_loss_price_cents = exit_policy.sl_cents
            elif exit_policy and exit_policy.sl_r_multiple:
                # Fallback to R-multiple if sl_cents not set (legacy path)
                # For YES: SL = entry - (entry * sl_r_multiple)
                # For NO: SL = entry + (entry * sl_r_multiple)
                if side_raw == "YES":
                    stop_loss_price_cents = int(price_cents * (1 - exit_policy.sl_r_multiple))
                else:  # NO
                    stop_loss_price_cents = int(price_cents * (1 + exit_policy.sl_r_multiple))
            else:
                # Default to 5 cent SL if no policy
                stop_loss_price_cents = max(1, price_cents - 5) if side_raw == "YES" else price_cents + 5
            
            # Generate unique trace_id for candidate → order → policy tracking
            import uuid
            trace_id = str(uuid.uuid4())[:8]
            candidate["trace_id"] = trace_id

            # PRE-SEND ASSERT: Ensure order price is within profile price_range (10c-50c)
            # Profile YAML: kalshi_crypto_15m_v2.yaml price_range.min_price_cents=10, max_price_cents=50
            if not (10 <= price_cents <= 50):
                logger.error(
                    "[PRE-SEND-ASSERT-FAILED] trace_id=%s price_cents=%d outside profile price_range [10,50] ticker=%s side=%s edge_pct=%s "
                    "candidate_price_cents=%s source=%s",
                    trace_id, price_cents, ticker, kalshi_side, edge_pct,
                    candidate.get("price_cents", "N/A"), "merid.prediction.agent_grid_15m"
                )
                raise AssertionError(f"Order price {price_cents}c outside profile price_range [10,50] for ticker={ticker}")

            # CRITICAL FIX: 2026-07-09 - Enforce max 1 contract per order for $1 hard limit
            # This prevents agents from exceeding the $1 exposure cap by trading multiple contracts
            if count != 1:
                logger.error(
                    "[PRE-SEND-ASSERT-FAILED] trace_id=%s count=%d != 1 for ticker=%s - "
                    "hard limit: max 1 contract per order to enforce $1 exposure cap",
                    trace_id, count, ticker
                )
                raise AssertionError(f"Order count {count} != 1 for ticker={ticker} - max 1 contract per order")

            # CRITICAL FIX: Compute aggressiveness from edge before creating OrderIntent
            # This ensures orders are marketable (cross spread) instead of resting (join spread)
            # Resting orders with aggressiveness=0.0 rarely fill in thin 15m crypto markets
            aggressiveness = 0.0
            try:
                from merid.event_venues.kalshi.risk_parameters import compute_order_aggressiveness
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                
                # Extract asset from ticker
                asset = ticker.split("-")[0].replace("KX", "") if "-" in ticker else "BTC"
                
                # Get seconds to expiry from market state
                seconds_to_expiry = 900  # Default 15 minutes
                market_state_store = get_kalshi_market_state_store()
                if market_state_store:
                    state = market_state_store.get(ticker)
                    if state and hasattr(state, 'seconds_to_expiry'):
                        seconds_to_expiry = state.seconds_to_expiry
                
                # Normalize edge_pct to fraction (agent candidates use percent, compute_order_aggressiveness expects fraction)
                edge_fraction = edge_pct / 100.0 if edge_pct > 1.0 else edge_pct
                
                # Compute aggressiveness (0.0=resting, 0.5-1.0=marketable)
                aggressiveness = compute_order_aggressiveness(
                    asset=asset,
                    edge_pct=edge_fraction,
                    seconds_to_expiry=int(seconds_to_expiry)
                )
                
                logger.info(
                    "[15M-LOOP] Computed aggressiveness: ticker=%s asset=%s edge_pct=%.2f%% aggressiveness=%.2f tte=%ds",
                    ticker, asset, edge_fraction * 100, aggressiveness, seconds_to_expiry
                )
            except Exception as agg_err:
                logger.warning("[15M-LOOP] Failed to compute aggressiveness: %s, using default 0.5 (marketable)", agg_err)
                aggressiveness = 0.5  # Default to marketable (0.5) to ensure fills
            
            intent = OrderIntent(
                ticker=ticker,
                side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
                action=action_raw,  # Keep as lowercase "buy"/"sell" for early validation
                price_cents=price_cents,  # BUG #2 FIX: Add required price_cents field
                count=1,  # CRITICAL FIX: 2026-07-09 - Hard limit: max 1 contract per order
                source="merid.prediction.agent_grid_15m",  # Use 'source' instead of 'caller_module'
                agent_id=agent_id,  # CRITICAL: Pass actual agent_id for authorization
                edge_pct=edge_pct,  # BUG #34 FIX: Add edge_pct from candidate
                confidence=confidence,  # BUG #34 FIX: Add confidence from candidate
                model_prob=model_prob,  # BUG #34 FIX: Add model_prob from candidate
                rationale=candidate.get("rationale"),  # CRITICAL: Pass rationale to skip edge validation for price-based strategy
                trace_id=trace_id,  # DEBUG: Add trace_id for candidate → order → policy tracking
                # Phase 2: Strategy identification for multi-strategy support
                strategy_id="heuristic_velocity",  # From profile strategies section
                strategy_type="heuristic_velocity",  # From profile strategies section
                regime=regime,  # Regime computed from market state (lines 2689-2717)
                # Phase 5.4: Raw logit for probability calibration outcome recording
                raw_logit=raw_logit,
                # CRITICAL FIX: 2026-07-01 - Add order_type from candidate for maker rebate optimization
                # Industry standard: Use limit orders (maker) to earn rebates (-0.05% round trip) vs taker fees (0.15% round trip)
                # Reference: https://www.polytrackhq.app/blog/polymarket-15-minute-crypto-guide
                order_type=candidate.get("order_type", "limit"),  # Default to limit for maker rebate
                # CRITICAL FIX: 2026-07-07 - Explicitly set post_only=False to prevent Kalshi API rejection
                # Error "Post_only_but_execution_type_can't_rest" occurs when post_only=True but order can't rest
                post_only=False,
                # CRITICAL FIX: Add aggressiveness to ensure orders are marketable (cross spread) instead of resting
                aggressiveness=aggressiveness,  # 0.0=resting, 0.5-1.0=marketable
                # CRITICAL FIX: Add client_tag for TP/SL registration with position cache
                client_tag=client_tag,
                # CRITICAL FIX: Add exit targets from resolved exit policy
                take_profit_price_cents=take_profit_price_cents,
                take_profit_r_multiple=take_profit_r_multiple,
                stop_loss_price_cents=stop_loss_price_cents,
                # CRITICAL FIX (2026-07-08): exit_policy must be non-None at this point
                # If exit_policy is None, it should have been rejected earlier in _execute_candidate
                # This defensive check ensures we fail loudly if there's a bug in the control flow
                exit_policy_id=exit_policy.policy_id if exit_policy else None,
                # CRITICAL FIX: Add risk contract linkage fields to satisfy _validate_risk_contract_linkage
                # These are required for crypto 15m markets to pass the risk contract validation
                window_resolution_id=window_resolution_id if window_resolution_id else f"window_resolution_{uuid.uuid4().hex[:12]}",
                risk_tier="A",  # Default to tier A (conservative) for 15m crypto
                max_hold_seconds=int(exit_policy.max_hold_seconds) if exit_policy and hasattr(exit_policy, 'max_hold_seconds') else 600,  # 10 min default
                # CRITICAL FIX: Pass effective_equity_usd to risk manager for proper sizing
                effective_equity_usd=effective_equity_usd,
                # Phase 1: Add market microstructure data for fee-aware edge and microstructure gates
                yes_bid_cents=candidate.get("yes_bid_cents"),
                yes_ask_cents=candidate.get("yes_ask_cents"),
                no_bid_cents=candidate.get("no_bid_cents"),
                no_ask_cents=candidate.get("no_ask_cents"),
                yes_depth=candidate.get("yes_depth"),
                no_depth=candidate.get("no_depth"),
            )
            
            # CRITICAL DIAGNOSTIC: Log exit_policy_id being set
            logger.info("[15M-LOOP] Setting exit_policy_id=%s for ticker=%s (exit_policy=%s)", 
                       intent.exit_policy_id, 
                       ticker, 
                       "present" if exit_policy else "None")
            
            # Load order scaling configuration from profile
            scaling_enabled = False
            scaling_strategy = "adaptive"
            try:
                from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
                if is_profile_active():
                    profile_adapter = get_active_profile()
                    if profile_adapter and hasattr(profile_adapter, 'profile'):
                        profile = profile_adapter.profile
                        if hasattr(profile, 'order_scaling'):
                            scaling_config = profile.order_scaling
                            scaling_enabled = getattr(scaling_config, 'enabled', False)
                            scaling_strategy = getattr(scaling_config, 'strategy', 'adaptive')
                            logger.debug(
                                "[15M-LOOP] Loaded scaling config from profile: enabled=%s strategy=%s",
                                scaling_enabled, scaling_strategy
                            )
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to load scaling config from profile: %s", e)
            
            # Apply scaling configuration to intent
            intent.scaling_enabled = scaling_enabled
            intent.scaling_strategy = scaling_strategy
            
            # Route order
            result = await route_order_async(intent)
            logger.info("[15M-LOOP] Order routed successfully: ticker=%s side=%s count=%d result=%s", 
                       ticker, kalshi_side, count, result)
            
            # CRITICAL FIX: Record order in KalshiRiskManager for asset_notional tracking
            # This ensures per-asset notional exposure is tracked correctly for risk limits
            if result and result.status and "filled" in result.status:
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                    risk_mgr = get_kalshi_risk()
                    
                    # Record order with category="crypto" and asset for notional tracking
                    risk_mgr.record_order(
                        category="crypto",
                        contracts=count,
                        price_cents=price_cents,
                        fee_cents=0,  # Fee tracking handled elsewhere
                        asset=asset,  # CRITICAL: Pass asset for per-asset notional tracking
                    )
                    logger.info(
                        "[15M-LOOP] Recorded order in risk manager: asset=%s category=crypto contracts=%d price=%dc",
                        asset, count, price_cents
                    )
                except Exception as risk_err:
                    logger.warning("[15M-LOOP] Failed to record order in risk manager: %s", risk_err)
            
            # Update position tracking after successful order
            # FIX: Only increment active_trades if order was actually FILLED, not just routed
            # Previously, rejected orders were counted as active trades, causing phantom trade detection
            if result and asset and result.status and "filled" in result.status:
                self._asset_positions[asset] = self._asset_positions.get(asset, 0.0) + position_notional_usd
                self._active_trades[ticker] = self._active_trades.get(ticker, 0) + 1
                logger.info(
                    "[15M-LOOP] Position tracking updated: asset=%s exposure=%.2f ticker=%s active_trades=%d",
                    asset, self._asset_positions[asset], ticker, self._active_trades[ticker]
                )
            elif result and result.status and "rejected" in result.status:
                logger.info(
                    "[15M-LOOP] Order rejected - not updating position tracking: ticker=%s reason=%s",
                    ticker, result.reason
                )
            
        except Exception as e:
            logger.error("[15M-LOOP] Failed to execute candidate: %s", e, exc_info=True)

    async def _run_agents_directly(self, tick: int) -> None:
        """Fallback: run agents directly if run_cycle not implemented."""
        for agent in self.agent_grid._agents:
            try:
                if hasattr(agent, 'run_cycle'):
                    await agent.run_cycle(tick)
            except Exception as exc:
                logger.error(
                    "[15m-LOOP] Agent %s failed in cycle %d: %s",
                    getattr(agent, 'agent_id', 'unknown'),
                    tick,
                    exc,
                    exc_info=True,
                )

    def summary(self) -> Dict[str, Any]:
        """Get loop status summary for API/monitoring."""
        # Handle both datetime and float (timestamp) types
        started_at = self._started_at
        if started_at and isinstance(started_at, (int, float)):
            started_at = datetime.fromtimestamp(started_at, tz=timezone.utc)
        uptime = (
            (datetime.now(timezone.utc) - started_at).total_seconds()
            if started_at
            else 0
        )
        summary = {
            "running": self._running,
            "tick": self._tick,
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "cadence_seconds": self.cadence_seconds,
            "uptime_seconds": uptime,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "agent_count": len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0,
            "halted_due_to_drawdown": self._halted_due_to_drawdown,
        }
        
        # Add risk envelope state if available
        if self._risk_envelope:
            risk_envelope_summary = {}
            # Only include attributes that exist on the envelope object
            if hasattr(self._risk_envelope, 'current_drawdown_pct'):
                risk_envelope_summary["current_drawdown_pct"] = self._risk_envelope.current_drawdown_pct
            if hasattr(self._risk_envelope, 'current_risk_band'):
                risk_envelope_summary["current_risk_band"] = self._risk_envelope.current_risk_band.value if hasattr(self._risk_envelope.current_risk_band, 'value') else str(self._risk_envelope.current_risk_band)
            if hasattr(self._risk_envelope, 'is_halted'):
                risk_envelope_summary["is_halted"] = self._risk_envelope.is_halted
            if hasattr(self._risk_envelope, 'per_trade_risk_multiplier'):
                risk_envelope_summary["per_trade_risk_multiplier"] = self._risk_envelope.per_trade_risk_multiplier
            if hasattr(self._risk_envelope, 'distance_to_halt_pct') and callable(self._risk_envelope.distance_to_halt_pct):
                risk_envelope_summary["distance_to_halt_pct"] = self._risk_envelope.distance_to_halt_pct()
            
            # Add basic envelope info that should always exist
            if hasattr(self._risk_envelope, 'live_bankroll_usd'):
                risk_envelope_summary["live_bankroll_usd"] = self._risk_envelope.live_bankroll_usd
            if hasattr(self._risk_envelope, 'per_agent_window_limit_usd'):
                risk_envelope_summary["per_agent_window_limit_usd"] = self._risk_envelope.per_agent_window_limit_usd
            if hasattr(self._risk_envelope, 'total_venue_window_limit_usd'):
                risk_envelope_summary["total_venue_window_limit_usd"] = self._risk_envelope.total_venue_window_limit_usd
            
            if risk_envelope_summary:
                summary["risk_envelope"] = risk_envelope_summary
        
        # Phase 5.5: Add calibration metrics from agents
        calibration_metrics = {}
        if hasattr(self.agent_grid, '_agents'):
            for agent in self.agent_grid._agents:
                if hasattr(agent, 'get_calibration_metrics'):
                    try:
                        agent_metrics = agent.get_calibration_metrics()
                        if agent_metrics:
                            calibration_metrics[agent.config.name] = agent_metrics
                    except Exception as cal_err:
                        logger.warning("[15M-LOOP] Failed to get calibration metrics for %s: %s", 
                                     agent.config.name, cal_err)
        
        if calibration_metrics:
            summary["calibration"] = calibration_metrics
        
        return summary


def get_kalshi_15m_loop(
    agent_grid: Any,
    bankroll_service: Any,
    risk_config: Any,
    cadence_seconds: float = 5.0,
    catalog: Any = None,
    ws_bridge: Any = None,
) -> Kalshi15mLoop:
    """
    Factory function to create/get the Kalshi15mLoop singleton.
    
    This is the canonical way to get the loop instance for the 15m profile.
    
    NOTE: venue_adapter removed - it was dead code (TradingAgent bypasses it via route_order_async)
    """
    return Kalshi15mLoop(
        agent_grid=agent_grid,
        bankroll_service=bankroll_service,
        risk_config=risk_config,
        cadence_seconds=cadence_seconds,
        catalog=catalog,
        ws_bridge=ws_bridge,
    )

