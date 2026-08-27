from __future__ import annotations

import hashlib
import math
import os

# Kalshi 15m Lean Loop - Minimal event loop for kalshi_crypto_15m_v2 profile.
# This is a clean, minimal loop designed specifically for the 15-minute crypto trading
# stack on Kalshi. It replaces the complex legacy merid.loop for this profile.
# Responsibilities:
# - Pull latest market state / RTI inputs
# - Run 5 agents' signal + decision logic via AgentGrid.run_cycle()
# - Route orders through KalshiTradingAgent / order router / risk
# - Run at 5-second cadence
# This loop intentionally does NOT include:
# - Legacy lane orchestration
# - Reflection/learning systems
# - KalshiContinuousTrader
# - PM agents or regime agents
# - Cross-venue arbitrage
# IMPORT POLICY (15m_live mode):
# Allowed imports:
# - merid.loop_15m (this module)
# - merid.prediction.agent_grid_15m
# - merid.prediction.candidate_optimizer
# - merid.event_venues.kalshi.* (venue adapter, market_state, risk)
# - data.unified_spot_service
# - config.kalshi_* (15m-specific configs only)
# - Generic utilities (logging, metrics, datetime, typing, dataclasses)
# CRITICAL FIX (2026-07-21): Feature flag for legacy direction mapping
# USE_LEGACY_DIRECTION_MAPPING: When False, uses pure functions from strategy_positions domain layer
# When True, falls back to legacy side derivation (for backward compatibility)
# Default: False (use new pure function approach)
# Set to True only for debugging or rollback scenarios
# CRITICAL FIX (2026-07-21): Feature flag for legacy direction mapping
# Set to False to use new pure function approach (recommended)
# Set to True to use legacy side derivation (backward compatibility only)
USE_LEGACY_DIRECTION_MAPPING = False


# Exit-guardrail tunables (2026-08-19): enforce a pre-trade loss/slippage bound
# on every automated discretionary exit while preserving emergency liquidation.
MERID_EXIT_MAX_LOSS_CENTS = int(os.getenv("MERID_EXIT_MAX_LOSS_CENTS", "3"))
MERID_EXIT_EMERGENCY_MAX_LOSS_CENTS = int(os.getenv("MERID_EXIT_EMERGENCY_MAX_LOSS_CENTS", "15"))
MERID_EXIT_MAX_SLIPPAGE_CENTS = int(os.getenv("MERID_EXIT_MAX_SLIPPAGE_CENTS", "2"))
MERID_EXIT_MIN_PROFIT_CENTS = int(os.getenv("MERID_EXIT_MIN_PROFIT_CENTS", "2"))
# Quote-age limit is tiered by time-to-expiry to avoid rejecting executable near-settlement exits.
MERID_EXIT_MAX_QUOTE_AGE_MS = int(os.getenv("MERID_EXIT_MAX_QUOTE_AGE_MS", "10000"))
MERID_EXIT_MAX_QUOTE_AGE_NEAR_EXPIRY_MS = int(os.getenv("MERID_EXIT_MAX_QUOTE_AGE_NEAR_EXPIRY_MS", "15000"))
MERID_EXIT_NEAR_EXPIRY_CUTOFF_SECONDS = int(os.getenv("MERID_EXIT_NEAR_EXPIRY_CUTOFF_SECONDS", "120"))
MERID_EXIT_EMERGENCY_CUTOFF_SECONDS = int(os.getenv("MERID_EXIT_EMERGENCY_CUTOFF_SECONDS", "60"))

# Canonical, human-auditable exit reasons.  Any non-emergency exit whose projected
# net P&L is worse than MERID_EXIT_MAX_LOSS_CENTS is rejected unless it is an
# explicit emergency/near-expiry liquidation.
MERID_EXIT_ALLOWED_REASONS = frozenset({
    "stop_loss",
    "trailing_stop",
    "take_profit",
    "time_exit",
    "signal_reversal",
    "expiry_liquidation",
    "reconciliation",
    "manual",
})

# Map internal ExitReason enum values to canonical audit reasons.
_EXIT_REASON_CANONICAL_MAP = {
    "stop_loss": "stop_loss",
    "trailing_stop": "trailing_stop",
    "trail": "trailing_stop",
    "take_profit": "take_profit",
    "time_stop": "time_exit",
    "adaptive_timing": "time_exit",
    "stale_data": "reconciliation",
    "risk": "reconciliation",
    "candle_reversal": "signal_reversal",
    "edge_decay": "signal_reversal",
    "opportunity_cost": "signal_reversal",
    "auto_exit_99c": "expiry_liquidation",
    "settlement_guard": "expiry_liquidation",
    "ratchet_floor": "take_profit",
    "loss_cut_40pct": "stop_loss",
    "manual": "manual",
    "scale_out": "take_profit",
}

# Reasons that may exceed the normal loss bound because they are explicit
# emergency / near-expiry liquidation paths.
_MERID_EXIT_EMERGENCY_REASONS = frozenset({"expiry_liquidation"})

# Reasons that are allowed to take a bounded loss (they are loss-seeking by
# construction) but are not unrestricted emergency exits.
_MERID_EXIT_STOP_REASONS = frozenset({"stop_loss", "trailing_stop", "loss_cut_40pct"})

# CRITICAL FIX (2026-08-23): Statuses that prove the exchange terminally processed
# the order and either accepted it or executed it.  ``request_completed`` alone is
# not enough because it also includes rejected/canceled/expired statuses.
_ACCEPTED_ORDER_STATUSES = frozenset({
    "filled_mock",
    "filled_paper",
    "filled_live",
    "partial_live",
    "partial_fill",
    "accepted_live",
    "submitted_live",
    "resting",
    "unfilled_ioc",
})


def _confirmed_submission(response) -> bool:
    """Return True only when the router response proves the order was accepted."""
    if not response:
        return False
    return bool(
        response.order_id
        or response.has_execution
        or (response.request_completed and getattr(response, "status", "") in _ACCEPTED_ORDER_STATUSES)
    )


def _exit_quote_age_limit_ms(seconds_to_expiry: Optional[float]) -> int:
    """
    Return the max acceptable quote age for an exit based on time-to-expiry.

    Near expiry, books become one-sided and WS updates slow; we allow a
    slightly older quote to avoid stranding profitable exits.  The default
    10,000 ms aligns with stop_candidate.py and position_monitor.py.
    """
    if seconds_to_expiry is None:
        return MERID_EXIT_MAX_QUOTE_AGE_MS
    if seconds_to_expiry <= MERID_EXIT_EMERGENCY_CUTOFF_SECONDS:
        return MERID_EXIT_MAX_QUOTE_AGE_NEAR_EXPIRY_MS
    if seconds_to_expiry <= MERID_EXIT_NEAR_EXPIRY_CUTOFF_SECONDS:
        return MERID_EXIT_MAX_QUOTE_AGE_NEAR_EXPIRY_MS
    return MERID_EXIT_MAX_QUOTE_AGE_MS


async def _get_canonical_post_position_cc(
    market_id: str,
    fallback_cc: Optional[int] = None,
) -> Optional[int]:
    """
    Return the exchange-reconciled position quantity in centi-contracts.

    First tries a fresh REST snapshot, then falls back to the in-memory
    position cache.  Returns ``None`` only when both fail and no fallback
    is supplied.
    """
    try:
        from merid.event_venues.kalshi.order_intent_contract import (
            fetch_fresh_signed_yes_exposure,
        )

        signed, _, _ = await fetch_fresh_signed_yes_exposure(
            market_id, timeout=1.0, fallback_to_cache=True
        )
        if signed is not None:
            return abs(signed)
    except Exception as exc:
        logger.warning(
            "[EXIT-RECONCILE] Fresh position fetch failed for %s: %s",
            market_id,
            exc,
        )

    if fallback_cc is not None:
        return fallback_cc
    return None


def assert_exit_delta(pre_position_size_cc: int, count_cc: int, market_id: str, position_id: str) -> int:
    """
    Validate exit order position-delta invariants and return post_size in
    centi-contracts.

    All inputs and outputs are integer centi-contracts (1 centi-contract =
    0.01 contracts).  This allows exact handling of fractional exits such as
    0.25 -> 0.75 without rounding.

    Invariants checked:
    1. Position must have positive size (cannot exit from zero)
    2. Exit count must be positive
    3. Exit count cannot exceed position size (cannot over-close)
    4. Expected post-size must be non-negative (cannot flip to negative)
    5. Expected post-size must be strictly less than pre-size (must decrease)
    """
    pre_position_size_cc = int(pre_position_size_cc) if pre_position_size_cc is not None else 0
    count_cc = int(count_cc) if count_cc is not None else 0

    if pre_position_size_cc <= 0:
        logger.critical(
            "[EXIT-INVARIANT-VIOLATION] ticker=%s position_id=%s pre_position_size_cc=%d - "
            "EXIT orders require pre_position_size_cc>0. Rejecting as critical bug.",
            market_id,
            position_id[:8] if position_id else "unknown",
            pre_position_size_cc,
        )
        raise RuntimeError(
            f"EXIT-INVARIANT-VIOLATION: Cannot exit position with size_cc={pre_position_size_cc} for {market_id}."
        )

    if count_cc <= 0:
        logger.critical(
            "[EXIT-INVARIANT-VIOLATION] ticker=%s position_id=%s count_cc=%d - "
            "EXIT orders require count_cc>0. Rejecting as critical bug.",
            market_id,
            position_id[:8] if position_id else "unknown",
            count_cc,
        )
        raise RuntimeError(
            f"EXIT-INVARIANT-VIOLATION: Invalid exit count_cc={count_cc} for {market_id}."
        )

    if count_cc > pre_position_size_cc:
        logger.critical(
            "[EXIT-INVARIANT-VIOLATION] ticker=%s position_id=%s pre_size_cc=%d count_cc=%d - "
            "EXIT orders cannot close more contracts than exist. Rejecting as critical bug.",
            market_id,
            position_id[:8] if position_id else "unknown",
            pre_position_size_cc,
            count_cc,
        )
        raise RuntimeError(
            f"EXIT-INVARIANT-VIOLATION: Exit count_cc={count_cc} exceeds position size_cc={pre_position_size_cc} for {market_id}."
        )

    expected_post_position_size_cc = pre_position_size_cc - count_cc

    if expected_post_position_size_cc < 0:
        logger.critical(
            "[EXIT-INVARIANT-VIOLATION] ticker=%s position_id=%s pre_size_cc=%d count_cc=%d post_size_cc=%d - "
            "EXIT orders cannot result in negative position size.",
            market_id,
            position_id[:8] if position_id else "unknown",
            pre_position_size_cc,
            count_cc,
            expected_post_position_size_cc,
        )
        raise RuntimeError(
            f"EXIT-INVARIANT-VIOLATION: Exit would result in negative size_cc={expected_post_position_size_cc} for {market_id}. "
            f"Exit orders cannot flip position sign."
        )

    if expected_post_position_size_cc >= pre_position_size_cc:
        logger.critical(
            "[EXIT-INVARIANT-VIOLATION] ticker=%s position_id=%s pre_size_cc=%d post_size_cc=%d - "
            "EXIT orders must strictly decrease position size. Rejecting as critical bug.",
            market_id,
            position_id[:8] if position_id else "unknown",
            pre_position_size_cc,
            expected_post_position_size_cc,
        )
        raise RuntimeError(
            f"EXIT-INVARIANT-VIOLATION: Exit would not decrease position (pre_cc={pre_position_size_cc}, post_cc={expected_post_position_size_cc}) for {market_id}."
        )

    logger.info(
        "[EXIT-INVARIANT-PASS] ticker=%s position_id=%s pre_size_cc=%d count_cc=%d post_size_cc=%d - "
        "Exit order passes all position-delta invariants (close-only validation)",
        market_id,
        position_id[:8] if position_id else "unknown",
        pre_position_size_cc,
        count_cc,
        expected_post_position_size_cc,
    )

    return expected_post_position_size_cc

# Forbidden imports:
# - PM runtime controllers
# - Paper trading engine
# - Reflection/learning systems
# - Social broadcasters
# - Cross-venue logic
# - Deprecated config modules (kalshi_15m_crypto_config.py)

# See docs/15M_STACK_SURFACE.md for complete allowed surface definition

# Degraded Mode Semantics
# Definition
# Degraded mode is a soft-fail / partial-health state where the system can continue
# trading in healthy markets while some markets are temporarily unavailable or illiquid.
# Scope of Degradation
# Degraded mode applies to:
# - Market health signals (catalog age, depth coverage, bankroll sanity)
# - NOT feature disabling (agents/timeframes remain active)
# - NOT per-market blocking (healthy markets continue trading)
# Allowed vs Disallowed Actions
# Allowed in degraded mode:
# - Continue quoting in healthy markets (those passing depth checks)
# - Continue consuming websockets
# - Maintain bookkeeping (bankroll, PnL, position tracking)
# - Run agent signal generation for all markets
# - Execute orders only in markets with sufficient depth
# Disallowed in degraded mode:
# - New market onboarding (catalog refresh continues but no new trading)
# - Aggressive scaling (position sizing may be throttled)
# - Opening new positions in markets failing depth checks
# Loop States & Execution Modes (cadence-aware)
# The loop separates THREE concerns so a normal gap between 15m strips is never
# confused with a systemic failure:
# 1. `infra_ready`      - platform health: catalog reachable+fresh, WS forwarder
#                         healthy, bankroll real+valid, risk profile loaded, TOP3 gate.
# 2. `markets_expected` - should strips exist now? (15m cadence + maintenance window).
# 3. `markets_present`  - does the catalog actually show >=1 active 15m strip?
# loop_state (high-level "should we be trading?" - the source of truth):
# - HALT     - infra_ready=False. System/venue broken or unsafe. Trading blocked. RED FLAG.
# - WAITING  - infra OK, markets expected, but none posted yet (venue posting lag). NOT a fault.
# - IDLE     - infra OK, markets not expected (maintenance / off hours). NOT a fault.
# - ACTIVE   - infra OK and >=1 strip present. Evaluate per-asset readiness.
# execution_mode (posture signal, meaningful ONLY inside ACTIVE):
# - NORMAL      - ready_assets_count >= 2. Full breadth, normal sizing.
# - DEGRADED    - ready_assets_count == 1. Trade the single ready asset (NOT a kill-switch).
# - ACTIVE-HALT - ready_assets_count == 0 while markets ARE present. RED FLAG (per-asset
#                   gates rejected everything despite live strips).
# - NONE        - set whenever loop_state != ACTIVE (no trading-relevant posture).
# An asset is "ready" iff its MD is fresh (<30s) AND its book depth meets the
# per-asset threshold. ready_assets_count is the number of ready assets (0..5).
# execution_ready (the SINGLE downstream trading gate) is True iff
# loop_state == ACTIVE and ready_assets_count >= 1.
# Why "0 ready assets" is not always HALT
# In a 15-minute strip system, "0 ready assets" usually means Kalshi has not posted
# the next set yet - a transient, EXPECTED gap - not that the platform is broken.
# Only HALT (infra failure) and ACTIVE-HALT (strips present but nothing tradable)
# are treated as faults / guardrail trips. WAITING and IDLE keep the system warm,
# do not trade, and are NOT logged as risk events.
# Venue Posting / Cadence
# - Kalshi posts crypto strips on a continuous 15-minute cadence, 24/7.
# - Weekly maintenance window: Thursday 03:00-05:00 ET (markets taken down -> IDLE).
# - Short posting lag (seconds to ~1-2 min) between a strip closing and the next
#   appearing; during that lag strips are still "expected" -> WAITING.
# - markets_expected_now() encodes this schedule (currently: outside maintenance).
# State Transitions
# - WAITING/IDLE -> ACTIVE : as soon as the catalog shows >=1 strip.
# - ACTIVE -> WAITING      : strips disappear (between-strip gap), infra still OK.
# - ANY -> HALT            : any infra signal fails (catalog/WS/bankroll/risk/gate).
# - NORMAL <-> DEGRADED <-> ACTIVE-HALT : driven purely by ready_assets_count.
# Per-Market Eligibility
# Each market has its own depth check:
# - depth_ok(market) = (min_depth_yes >= 25 AND min_depth_no >= 25)
# - Only markets passing this check are eligible for order placement
# - This is enforced at the agent level, not as a global gate
# Global Readiness vs Per-Market Eligibility
# Global readiness (ready):
# - Driven by CRITICAL signals only: WS connectivity, bankroll sanity, catalog not catastrophically stale
# - Depth coverage threshold: at least 1 market tradable (not 5/5)
# - If ready=False, NO trading occurs in any market
# Per-market eligibility:
# - Each market has its own depth_ok(market) check
# - Agents skip order placement for markets failing depth checks
# - Does NOT flip global ready flag
# - Only affects that specific market's trading
# Rationale
# In multi-asset systems, it's common and expected that some symbols are temporarily
# untradeable (low depth, paused, or disabled) while others remain active. Requiring
# perfect breadth (5/5) before using ANY edge is overly conservative and misaligned
# with typical trading infrastructure design.
# Example: If BTC/ETH/SOL have sufficient depth but XRP/DOGE are illiquid, the system
# should trade BTC/ETH/SOL (degraded mode) rather than blocking all trading (halt mode).

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
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
from enum import Enum
from dataclasses import dataclass

from utils.logger import get_logger


@dataclass(frozen=True)
class EntryReadiness:
    """Per-contract readiness diagnosis for the 15m entry gate.

    This is a structured audit object, not a policy decision.  It exposes every
    individual gate so an operator can see whether a new window is failing
    because of catalog, market-data, quote coherence, portfolio authority, or
    pending-intent state.
    """
    ticker: str
    catalog_ready: bool
    selected: bool
    ws_subscribed: bool
    ws_snapshot_complete: bool
    quote_fresh: bool
    quote_coherent: bool
    market_state_applied: bool
    portfolio_authoritative: bool
    intent_state_clean: bool
    queue_healthy: bool
    queue_lock_wait_ms: float
    queue_batch_duration_ms: float
    queue_lock_contention_count: int
    entries_allowed: bool
    blocker: Optional[str]

    def to_log_message(self) -> str:
        return (
            "ENTRY-READINESS "
            f"ticker={self.ticker} "
            f"catalog_ready={self.catalog_ready} "
            f"selected={self.selected} "
            f"ws_subscribed={self.ws_subscribed} "
            f"ws_snapshot_complete={self.ws_snapshot_complete} "
            f"quote_fresh={self.quote_fresh} "
            f"quote_coherent={self.quote_coherent} "
            f"market_state_applied={self.market_state_applied} "
            f"portfolio_authoritative={self.portfolio_authoritative} "
            f"intent_state_clean={self.intent_state_clean} "
            f"queue_healthy={self.queue_healthy} "
            f"queue_lock_wait_ms={self.queue_lock_wait_ms:.2f} "
            f"queue_batch_duration_ms={self.queue_batch_duration_ms:.2f} "
            f"queue_lock_contention_count={self.queue_lock_contention_count} "
            f"entries_allowed={self.entries_allowed} "
            f"blocker={self.blocker or 'none'}"
        )

# Canonical asset extraction from Kalshi tickers (single source of truth)
from merid.utils.kalshi_identity import extract_asset

# Single source of truth for cycle rejection breakdown and lifecycle events
from merid.prediction.agent_grid_15m import CycleResult
from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER

# Import candidate tracing for end-to-end validation
try:
    from merid.event_venues.kalshi.candidate_trace import (
        CandidateTrace,
        CandidateTraceStore,
        Side as TraceSide,
        EconomicsMode,
        TerminalState,
        get_trace_store,
    )
    CANDIDATE_TRACE_AVAILABLE = True
except ImportError:
    CANDIDATE_TRACE_AVAILABLE = False
    logger.warning("candidate_trace module not available - end-to-end tracing disabled")

# Import canonical YES/NO price space model for consistent side mapping
from merid.event_venues.kalshi.binary_price_space import (
    to_kalshi_side,
    parse_kalshi_side,
    extract_outcome_side,
    extract_action,
)

logger = get_logger("merid.loop_15m")
logger.info("[15M-LOOP] MODULE VERSION v20260529a-cache-fix")

# CRITICAL FIX (2026-08-02): Import unified probability model integration
# This addresses high-leverage bugs #1, #2, #7 (probability model issues)
try:
    from merid.event_venues.kalshi.probability_model_integration import (
        enrich_intent_with_binary_probability,
        validate_probability_model_consistency,
        get_probability_from_intent,
    )
    PROBABILITY_MODEL_INTEGRATION_AVAILABLE = True
    logger.info("[15M-LOOP] probability_model_integration available - using unified probability model")
except ImportError:
    PROBABILITY_MODEL_INTEGRATION_AVAILABLE = False
    logger.warning("[15M-LOOP] probability_model_integration not available - using legacy probability handling")


def _map_exit_reason_to_intent_contract(exit_reason_str: str) -> "ExitReason":
    # Map position_management.ExitReason to intent_contract.ExitReason.
    # This bridges the exit policy layer's ExitReason enum with the intent contract's
    # ExitReason enum for formal entry/exit direction contract enforcement.
    # Args:
    #     exit_reason_str: Exit reason string from position_management.exit_policy.ExitReason
    # Returns:
    #     ExitReason from intent_contract.ExitReason
    from merid.prediction.intent_contract import ExitReason
    
    # Map position_management exit reasons to intent_contract exit reasons
    mapping = {
        "take_profit": ExitReason.EXIT_TP,
        "stop_loss": ExitReason.EXIT_SL,
        "auto_exit_99c": ExitReason.EXIT_99C,
        "manual": ExitReason.EXIT_MANUAL,
        "time_stop": ExitReason.EXIT_EXPIRY,
        "risk": ExitReason.EXIT_RISK_LIMIT,
        "stale_data": ExitReason.EXIT_RISK_LIMIT,
        "candle_reversal": ExitReason.EXIT_MANUAL,
        "adaptive_timing": ExitReason.EXIT_MANUAL,
        "edge_decay": ExitReason.EXIT_MANUAL,
        "scale_out": ExitReason.EXIT_MANUAL,
        "extreme_profit": ExitReason.EXIT_99C,  # Deprecated but map to 99C
        "dynamic_take_profit": ExitReason.EXIT_TP,
        "ratchet_trim": ExitReason.EXIT_TP,
        "ratchet_floor": ExitReason.EXIT_TP,
        "trail": ExitReason.EXIT_MANUAL,
    }
    
    return mapping.get(exit_reason_str.lower(), ExitReason.EXIT_MANUAL)

# ── Loop diagnostics file IO (env-gated to avoid hot-loop disk overhead) ──────
# The 15m loop historically wrote to a hardcoded health_diagnostic.txt on EVERY
# cycle (open+write+flush), adding disk-fsync latency to the hot path - implicated
# in Windows ProactorEventLoop stalls. These writes are now DISABLED by default and
# gated behind MERID_LOOP_DIAG_FILE=1 for on-demand debugging.
_DIAG_FILE_PATH = "c:\\Dev\\MERID\\web\\health_diagnostic.txt"
_DIAG_FILE_ENABLED = os.getenv("MERID_LOOP_DIAG_FILE", "").strip().lower() in ("1", "true", "yes", "on")


class _NullDiagWriter:
    # No-op file-like context manager used when loop diagnostics are disabled.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, *_args, **_kwargs):
        return 0

    def flush(self):
        return None


def _diag_open():
    # Return a writable handle for loop diagnostics.
    # CRITICAL FIX: Always return no-op writer to prevent Windows ProactorEventLoop blocking.
    # The synchronous file I/O was causing the loop to hang on Windows.
    # Diagnostics are now disabled by default to ensure loop reliability.
    # CRITICAL: Always return no-op writer to prevent blocking on Windows ProactorEventLoop
    # The environment variable check is disabled to ensure loop reliability
    return _NullDiagWriter()


# Liquidity decision enum for order fill safety check
class LiquidityDecision(Enum):
    # Decision on whether an order can be filled safely.
    FULL = "FULL"  # Full size can be filled within slippage budget
    REDUCED = "REDUCED"  # Partial size available, should size down
    SKIP = "SKIP"  # Insufficient liquidity, skip this asset for this cycle

@dataclass
class LiquidityCheckResult:
    # Result of liquidity safety check for an asset.
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
    # Check if an order can be filled safely within slippage budget.
    # This replaces binary depth checks with a liquidity-aware decision:
    # - FULL: Enough depth at target price for full size
    # - REDUCED: Partial depth available, should size down
    # - SKIP: Insufficient liquidity, skip this asset
    # Args:
    #     state: KalshiMarketState with orderbook data
    #     target_qty: Target quantity in contracts
    #     max_slippage_cents: Maximum acceptable slippage in cents
    #     side: "yes" or "no" side of the book
    # Returns:
    #     LiquidityCheckResult with decision and diagnostics
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

# Import Coinbase WebSocket client for external spot velocity signals (Turbine research #1 winner)
_t4 = _import_time.time()
try:
    from merid.event_venues.coinbase.ws_client import get_coinbase_client, CoinbaseAsset
    COINBASE_WS_AVAILABLE = True
    logger.info("[LOOP-15M-IMPORT] Coinbase WebSocket client available for external velocity signals")
except ImportError as e:
    COINBASE_WS_AVAILABLE = False
    logger.warning("[LOOP-15M-IMPORT] Coinbase WebSocket client not available: %s", e)
_t5 = _import_time.time()
logger.debug("[LOOP-15M-IMPORT] Coinbase WS import took %.3fs", _t5 - _t4)

# Import exit policy resolver for take profit/stop loss setup
_t6 = _import_time.time()
from merid.event_venues.kalshi.order_router import resolve_exit_policy
# CRITICAL FIX (2026-07-18): ExitReason must be imported from risk.exit_policy
# because position_management.exit_policy.ExitReason doesn't have TRAIL member
# (needed for swing mode logic at line 1251)
from merid.risk.exit_policy import ExitReason
from merid.event_venues.kalshi.stop_candidate import (
    build_stop_candidate,
    maybe_submit_stop_candidate_sync,
    record_stop_candidate,
)
from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure
_t7 = _import_time.time()
logger.debug("[LOOP-15M-IMPORT] resolve_exit_policy import took %.3fs", _t7 - _t6)

# LEGACY REMOVAL: E2EInvariantChecker from merid.core is legacy code
# This import violates the 15m stack separation policy
# _t4 = _import_time.time()
# from merid.core.e2e_invariants import E2EInvariantChecker
# _t5 = _import_time.time()
# 


def is_within_kalshi_maintenance() -> bool:
    # Check if current time is within Kalshi scheduled maintenance window.
    # Kalshi has a weekly maintenance window on Thursday 3:00-5:00 AM ET.
    # This function checks if the current time falls within that window.
    # Returns:
    #     True if within maintenance window, False otherwise
    # Maintenance window configuration now comes from kalshi_agent_grid.yaml SessionConfig
    # (single source of truth) instead of settings.py env vars.
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
    # Return True if Kalshi 15m crypto strips are expected to exist right now.
    # This encodes the venue schedule/cadence, NOT whether markets are actually
    # present in the catalog. It is the difference between:
    #   - WAITING (markets expected but not yet posted -> transient venue/posting lag)
    #   - IDLE    (markets not expected -> scheduled downtime / maintenance)
    # For 15-minute crypto, Kalshi posts strips continuously every 15 minutes,
    # 24/7, EXCEPT during the weekly maintenance window (Thu 03:00-05:00 ET).
    # There is a short posting lag (seconds to ~1-2 min) between a strip closing
    # and the next strip appearing; during that lag strips are still expected.
    # Returns:
    #     True if strips should be available now (outside maintenance),
    #     False during the scheduled maintenance window (off hours).
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
    # Pure decision function for the 15m loop state machine with degraded modes.
    # Separates infra health from market presence and per-asset readiness so a
    # normal gap BETWEEN 15m strips is never confused with a systemic failure.
    # New execution modes for graceful degradation:
    # - RUN_NORMAL: MD and spot healthy for >=N assets, full trading allowed
    # - RUN_DEGRADED: Some assets stale but >=1 has good MD/spot, reduced trading
    # - NO_NEW_ENTRIES: MD not healthy enough for new entries, manage existing positions
    # - HALT_CRITICAL: Both MD and spot broken for all assets, sustained interval
    # Args:
    #     infra_ready: platform health (catalog/WS/bankroll/risk/gate all OK)
    #     markets_expected: should strips exist now? (cadence + maintenance)
    #     markets_present: does the catalog actually show >=1 active 15m strip?
    #     ready_assets_count: number of assets with fresh MD AND sufficient depth (0..5)
    #     md_fresh_count: number of assets with fresh MD (0..5)
    #     spot_fresh_count: number of assets with fresh spot (0..5)
    #     min_ready_for_normal: ready-asset count required for NORMAL (default 2)
    # Returns:
    #     (loop_state, execution_mode, execution_ready, allow_new_entries) where:
    #       loop_state        in {"HALT", "WAITING", "IDLE", "ACTIVE", "DEGRADED"}
    #       execution_mode    in {"NONE", "RUN_NORMAL", "RUN_DEGRADED", "NO_NEW_ENTRIES", "HALT_CRITICAL"}
    #       execution_ready:  True when loop_state allows any trading activity
    #       allow_new_entries: True when new position entries are allowed
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
    # Lean event loop for Kalshi 15m crypto trading.
    # Lifecycle:
    #     loop = Kalshi15mLoop(agent_grid, bankroll_service, risk_config, cadence_seconds=5.0)
    #     asyncio.create_task(loop.run_forever())
    #     ...
    #     await loop.stop()
    # NOTE: venue_adapter removed - it was dead code (TradingAgent bypasses it via route_order_async)

    def __init__(
        self,
        agent_grid: Any,
        bankroll_service: Any,
        risk_config: Any,
        cadence_seconds: float = 5.0,
        catalog: Any = None,
        ws_bridge: Any = None,
    ):
        # Initialize the 15m loop.
        # Args:
        #     agent_grid: AgentGrid instance with 5 trading agents
        #     bankroll_service: BankrollServiceV2 for balance tracking
        #     risk_config: KalshiRiskConfig for risk limits
        #     cadence_seconds: Loop cadence (default 5.0 seconds)
        #     catalog: KalshiMarketCatalog instance for market discovery
        #     ws_bridge: Shared WebSocket bridge instance (from main_15m_lean P1.5)
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
        # CRITICAL FIX (2026-07-15): Initialize to current window at startup to prevent phantom slot issues
        # Starting with None causes incorrect first window change detection
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
        try:
            initial_window = get_kalshi_15m_window()
            self._current_window_suffix = initial_window.suffix
            logger.info("[15m-LOOP] Initialized _current_window_suffix=%s at startup", self._current_window_suffix)
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to initialize _current_window_suffix: %s", e)
            self._current_window_suffix = None  # Fallback to None if initialization fails
        self._executed_candidates_this_window = {}  # Track executed candidates in current window to prevent duplicates (dict for edge comparison)
        self._halted_due_to_drawdown = False
        
        # Per-tick execution counter for sanity checks (reset each tick)
        self._tick_executed_count = 0
        
        # RESEARCH-ALIGNED: Rejection reason aggregation counters
        # Track why candidates are rejected to identify filtering bottlenecks.
        # CRITICAL FIX (2026-08-27): Use a Counter so agent_grid can supply the
        # canonical rejection_breakdown without a fixed, drifting key set.
        self._rejection_counters = Counter({
            "parity_blocked": 0,
            "parity_edge_threshold": 0,
            "parity_winner_mismatch": 0,
            "parity_price_violation": 0,
            "edge_below_threshold": 0,
            "duplicate_order": 0,
            "edge_improvement_cancel_failed": 0,
            "price_out_of_range": 0,
            "position_exists": 0,
            "resting_order_exists": 0,
            "edge_validation_failed": 0,
            "exit_policy_failed": 0,
            "router_rejected": 0,
            "router_exception": 0,
            "other": 0,
            "ENTRIES_DISABLED": 0,
            "signal_rejected": 0,
        })
        
        # Market making integration
        self._market_maker = None
        try:
            from merid.event_venues.kalshi.market_maker_15m import init_market_maker_15m, MarketMakingConfig
            from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile

            profile = get_crypto_15m_profile()
            if profile is not None:
                mm_raw = getattr(profile, 'market_making', {}) or {}
            else:
                mm_raw = {}

            # Env override takes precedence; otherwise use the profile.
            mm_env = os.environ.get("MERID_MARKET_MAKING_ENABLED", "").lower()
            if mm_env in ("1", "true"):
                enabled = True
            elif mm_env in ("0", "false"):
                enabled = False
            else:
                enabled = bool(mm_raw.get('enabled', False))

            mm_config = MarketMakingConfig(
                enabled=enabled,
                quoting_mode=mm_raw.get('quoting_mode', 'two_phase'),
                spread_cents=int(mm_raw.get('spread_cents', 2)),
                inventory_limit_contracts=int(mm_raw.get('inventory_limit_contracts', 50)),
                skew_adjustment=bool(mm_raw.get('skew_adjustment', True)),
                phase1_duration_seconds=int(mm_raw.get('phase1_duration_seconds', 720)),
                phase1_price_center_cents=int(mm_raw.get('phase1_price_center_cents', 50)),
                phase1_spread_cents=int(mm_raw.get('phase1_spread_cents', 3)),
                phase1_refresh_interval_seconds=int(mm_raw.get('phase1_refresh_interval_seconds', 15)),
                phase1_contracts_per_side=int(mm_raw.get('phase1_contracts_per_side', 15)),
                phase2_price_cents=int(mm_raw.get('phase2_price_cents', 52)),
                phase2_contracts=int(mm_raw.get('phase2_contracts', 15)),
                phase2_min_move_pct=float(mm_raw.get('phase2_min_move_pct', 0.0012))
            )
            self._market_maker = init_market_maker_15m(mm_config)
            logger.info("[15m-LOOP] Market maker initialized: enabled=%s quoting_mode=%s", mm_config.enabled, mm_config.quoting_mode)
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to initialize market maker: %s", e)
        
        # CRITICAL: Best-edge tracking per asset per 15-minute window
        # This implements signal generation vs execution separation:
        # - Agents generate candidates continuously (every 5s)
        # - Only the best edge per asset per window executes
        # - Position-based locking prevents re-execution until closed
        self._best_edge_per_asset: Dict[str, Dict] = {}  # asset -> {ticker, side, edge, candidate}
        
        # CRITICAL FIX: 2026-08-02 - Candidate lifecycle event log for invariant tracking
        # This provides a single source of truth for candidate state transitions
        self._candidate_event_log: list = []  # List of lifecycle events
        self._candidate_lifecycle_states: Dict[str, str] = {}  # candidate_id -> state
        
        # CRITICAL FIX: 2026-08-02 - Add lifecycle event logging helper
        self._log_candidate_lifecycle_event = self._create_lifecycle_logger()
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._best_edge_per_asset[asset] = None
        
        # Swing mode tracking: allows YES/NO reversal after trailing exit
        # When trailing stop exits in profit, enable swing mode to allow opposite-side entry
        self._swing_mode: Dict[str, Dict] = {}  # asset -> {enabled: bool, exited_side: str, exit_time: datetime}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
        
        # Per-asset position tracking for risk enforcement (use Decimal to match position.notional_value type)
        from decimal import Decimal
        self._asset_positions: Dict[str, Decimal] = {}  # asset -> current notional exposure
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._asset_positions[asset] = Decimal('0.0')
        
        # Coinbase WebSocket client for external spot velocity signals (Turbine research #1 winner)
        self._coinbase_client = None
        self._coinbase_velocity_signals: Dict[str, Dict] = {}  # asset -> {velocity, timestamp, signal_type}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self._coinbase_velocity_signals[asset] = {"velocity": 0.0, "timestamp": 0.0, "signal_type": "none"}
        
        if COINBASE_WS_AVAILABLE:
            try:
                self._coinbase_client = get_coinbase_client()
                logger.info("[15M-LOOP] Coinbase WebSocket client initialized for external velocity signals")
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to initialize Coinbase WebSocket client: %s", e)
        
        # Active trade tracking for concurrent trade limit enforcement
        # CRITICAL FIX (2026-07-17): Removed max_concurrent_trades - $2 exposure cap is the limit
        # GlobalSlotAllocator enforces MAX_EXPOSURE_USD=2.00, MAX_POSITIONS_PER_ASSET=1
        self._active_trades: Dict[str, int] = {}  # ticker -> order count (for tracking only, not limiting)
        
        # REMOVED: position_cache.clear_sync() call
        # The position cache is the single source of truth and should persist across restarts
        # Clearing it destroys position state and causes PositionMonitor to not load existing positions
        # Stale data should be handled by reconciliation, not by destroying the cache
        
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
                # Initialize all assets to 0 (use Decimal to match position.notional_value type)
                from decimal import Decimal
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._asset_positions[asset] = Decimal('0.0')
                
                # Get all positions and calculate exposure per asset
                all_positions = position_cache.get_all_positions(validate_freshness=False)
                logger.info("[15m-LOOP] Loaded %d positions from cache (attempt %d/%d)", len(all_positions), attempt + 1, max_retries)
                
                # CRITICAL FIX: Filter positions by current window to prevent counting stale positions
                # Each 15m window has a unique ticker. Get current window tickers for each asset.
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                current_window_tickers = {}
                if catalog:
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        try:
                            current_market = catalog.get_current_15m_market(asset)
                            if current_market:
                                current_window_tickers[asset] = current_market.market.market_id
                        except Exception as ticker_err:
                            logger.warning("[15m-LOOP] Failed to get current window ticker for %s: %s", asset, ticker_err)
                
                # Map ticker prefixes to assets
                asset_map = {
                    "KXBTC": "BTC",
                    "KXETH": "ETH",
                    "KXSOL": "SOL",
                    "KXXRP": "XRP",
                    "KXDOGE": "DOGE",
                }
                
                # Calculate exposure per asset (only current window positions)
                for market_id, position in all_positions.items():
                    # Extract asset from market_id
                    asset = None
                    for prefix, asset_name in asset_map.items():
                        if market_id.startswith(prefix):
                            asset = asset_name
                            break
                    
                    if asset and asset in self._asset_positions:
                        # CRITICAL FIX: Only count positions from current window
                        # Skip stale positions from previous windows
                        current_ticker = current_window_tickers.get(asset)
                        if current_ticker and market_id != current_ticker:
                            logger.debug("[15m-LOOP] Skipping stale position: market=%s current_window=%s", market_id, current_ticker)
                            continue
                        
                        # Calculate notional: contracts * avg_price_cents / 100
                        # CRITICAL FIX (2026-07-23): Handle None avg_price_cents (unknown entry price)
                        if position.avg_price_cents is not None:
                            notional = Decimal(str((position.contracts * position.avg_price_cents) / 100.0))
                            self._asset_positions[asset] += notional
                            logger.debug("[15m-LOOP] Position: market=%s asset=%s contracts=%d price=%d notional=%.2f", 
                                        market_id, asset, position.contracts, position.avg_price_cents, notional)
                        else:
                            logger.warning("[15m-LOOP] Position with unknown entry price: market=%s asset=%s contracts=%d - skipping notional calculation",
                                         market_id, asset, position.contracts)
                
                # Log final exposure for each asset
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    logger.info("[15m-LOOP] Loaded position from cache: asset=%s exposure=%.2f (attempt %d/%d)", 
                               asset, self._asset_positions[asset], attempt + 1, max_retries)
                
                # Validate that all assets were loaded
                loaded_assets = set(self._asset_positions.keys())
                expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                if loaded_assets == expected_assets:
                    logger.info("[15m-LOOP] Position tracking loaded from position cache: %s (attempt %d/%d)", list(self._asset_positions.keys()) if hasattr(self._asset_positions, 'keys') else str(self._asset_positions), attempt + 1, max_retries)
                    break  # Success, exit retry loop
                else:
                    missing = expected_assets - loaded_assets
                    logger.warning("[15m-LOOP] Position cache missing assets: %s (attempt %d/%d)", missing, attempt + 1, max_retries)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        # Fallback to default 0.0 values
                        logger.warning("[15m-LOOP] Position cache failed after %d retries, using default Decimal values", max_retries)
                        from decimal import Decimal
                        for asset in expected_assets:
                            if asset not in self._asset_positions:
                                self._asset_positions[asset] = Decimal('0.0')
                        logger.info("[15m-LOOP] Using default position tracking (all assets at 0.0): %s", list(self._asset_positions.keys()) if hasattr(self._asset_positions, 'keys') else str(self._asset_positions))
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to load positions from position cache (attempt %d/%d): %s", attempt + 1, max_retries, e, exc_info=True)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    # Fallback to default Decimal values
                    logger.warning("[15m-LOOP] Position cache failed after %d retries, using default Decimal values", max_retries)
                    from decimal import Decimal
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        self._asset_positions[asset] = Decimal('0.0')
                    logger.info("[15m-LOOP] Using default position tracking (all assets at 0.0): %s", list(self._asset_positions.keys()) if hasattr(self._asset_positions, 'keys') else str(self._asset_positions))
        
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

        # CRITICAL FIX: Reset slot allocator state to prevent phantom exposure blocking
        # The slot allocator may have stale slots from previous sessions that weren't released
        # This causes "Insufficient exposure" rejections even when position cache shows 0 positions
        try:
            from merid.risk.global_slot_allocator import get_global_slot_allocator
            slot_allocator = get_global_slot_allocator()
            position_count = len(all_positions) if 'all_positions' in locals() else 0
            slot_allocator.clear_slots_on_empty_positions(position_count)
            logger.info("[15m-LOOP] Slot allocator phantom slots cleared (position_count=%d)", position_count)
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to clear phantom slots from slot allocator: %s", e, exc_info=True)

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
                # Callback to record calibration outcome to the appropriate agent.
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
        # CRITICAL FIX (2026-07-17): PositionMonitor initialization MUST succeed
        # Previously, if initialization failed, self._position_monitor remained None,
        # causing all exit policies to be silently skipped. This is a critical safety violation.
        try:
            from merid.position_management.position_monitor import get_position_monitor
            self._position_monitor = get_position_monitor()
            logger.info("[15m-LOOP] Initialized PositionMonitor for TP/SL/trailing exits")
        except Exception as e:
            logger.error("[15m-LOOP] CRITICAL: Failed to initialize PositionMonitor: %s", e, exc_info=True)
            raise RuntimeError(f"PositionMonitor initialization failed - exit policies will not execute: {e}")

        # CRITICAL FIX (2026-07-31): Wire arbitrage callback for YES/NO arbitrage execution
        # This enables automatic execution of risk-free arbitrage opportunities when YES_ask + NO_bid < 100c
        # Previously, arbitrage opportunities were detected but never executed due to missing callback registration
        try:
            from merid.event_venues.kalshi.duality_validator import get_duality_validator
            from merid.event_venues.kalshi.order_router import execute_arbitrage_async
            
            def arbitrage_callback(arbitrage_opp):
                """Execute arbitrage opportunity when detected by duality validator."""
                try:
                    # Execute arbitrage asynchronously to avoid blocking the main loop
                    task = asyncio.create_task(execute_arbitrage_async(
                        yes_ticker=arbitrage_opp.yes_ticker,
                        no_ticker=arbitrage_opp.no_ticker,
                        yes_ask_cents=arbitrage_opp.yes_ask,
                        no_bid_cents=arbitrage_opp.no_bid,
                        size=arbitrage_opp.recommended_size,
                        market_id=arbitrage_opp.market_id
                    ))
                    logger.info(
                        "[ARBITRAGE-CALLBACK] Executing arbitrage: yes_ticker=%s no_ticker=%s edge=%dc size=%d",
                        arbitrage_opp.yes_ticker, arbitrage_opp.no_ticker,
                        arbitrage_opp.edge_cents, arbitrage_opp.recommended_size
                    )
                except Exception as arb_exc:
                    logger.error("[ARBITRAGE-CALLBACK] Failed to execute arbitrage: %s", arb_exc, exc_info=True)
            
            validator = get_duality_validator()
            validator.set_arbitrage_callback(arbitrage_callback)
            logger.info("[15m-LOOP] Arbitrage callback registered for YES/NO arbitrage execution")
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to register arbitrage callback: %s", e, exc_info=True)

    @property
    def is_running(self) -> bool:
        # Return whether the loop is currently running.
        return self._running

    @property
    def last_cycle_ts(self) -> Optional[datetime]:
        # Return the timestamp of the last cycle.
        return self._last_cycle_at

    @property
    def last_cycle_duration_ms(self) -> Optional[float]:
        # Return the duration of the last cycle in milliseconds.
        if self._cycle_duration_history:
            return self._cycle_duration_history[-1] * 1000 if self._cycle_duration_history else None
        return None

    @property
    def error_count(self) -> int:
        # Return the total error count.
        return self._error_count

    @property
    def cycle_id(self) -> int:
        # Return the current cycle ID (monotonically increasing).
        return self._tick

    @property
    def heartbeat_age_seconds(self) -> Optional[float]:
        # Return seconds since last cycle for heartbeat monitoring.
        if self._last_cycle_at is None:
            return None
        return (datetime.now(timezone.utc) - self._last_cycle_at).total_seconds()

    def _create_lifecycle_logger(self):
        """Create a lifecycle event logger for candidate state tracking.
        
        CRITICAL FIX: 2026-08-02 - This provides a single source of truth for candidate state transitions
        and enables invariant checking: candidates = executed + rejected + blocked + expired
        """
        def log_lifecycle_event(candidate_id: str, from_state: str, to_state: str, reason: str, context: dict = None):
            """Log a candidate lifecycle state transition."""
            timestamp_ms = int(time.time() * 1000)
            event = {
                "timestamp_ms": timestamp_ms,
                "tick_id": self._current_tick,  # CRITICAL FIX: Add tick_id for tick-scoped reconciliation
                "candidate_id": candidate_id,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
                "context": context or {}
            }
            self._candidate_event_log.append(event)
            self._candidate_lifecycle_states[candidate_id] = to_state
            
            # Keep event log bounded (last 1000 events)
            if len(self._candidate_event_log) > 1000:
                self._candidate_event_log = self._candidate_event_log[-1000:]
            
            # CRITICAL: 2026-08-02 - Detect missing tick_id (zero tolerance)
            if self._current_tick is None:
                try:
                    from merid.monitoring.trading_invariants_monitor import get_invariants_monitor
                    monitor = get_invariants_monitor()
                    monitor.record_missing_tick_id(candidate_id, f"{from_state} -> {to_state}")
                except ImportError:
                    logger.warning("[CANDIDATE-LIFECYCLE] Invariants monitor not available - missing tick_id not recorded")
            
            logger.debug(
                "[CANDIDATE-LIFECYCLE] tick=%d candidate_id=%s %s -> %s reason=%s context=%s",
                self._current_tick, candidate_id, from_state, to_state, reason, context
            )
        
        return log_lifecycle_event

    def _get_cached_envelope(self, current_bankroll: float):
        # Get cached risk envelope, recomputing only if bankroll changed significantly.
        # This avoids redundant envelope computation (5 agents × N cycles = 5N work).
        # Only recompute if bankroll changed by more than $1.00.
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
        # Schedule the next tick using asyncio.sleep (Windows ProactorEventLoop compatible).
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
        # Async tick handler (Windows ProactorEventLoop compatible).
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
            # Structured error classification for better debugging and alerting
            error_msg = str(exc).lower()
            error_type = type(exc).__name__
            
            # Classify error severity
            if any(keyword in error_msg for keyword in ["authentication", "unauthorized", "forbidden", "credential"]):
                severity = "CRITICAL"
                logger.critical("[15M-LOOP-ERROR] AUTH_FAILURE cycle=%d: %s - %s", cycle_id, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["timeout", "deadline", "timed out"]):
                severity = "WARNING"
                logger.warning("[15M-LOOP-ERROR] TIMEOUT cycle=%d: %s - %s", cycle_id, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["connection", "network", "dns"]):
                severity = "WARNING"
                logger.warning("[15M-LOOP-ERROR] NETWORK cycle=%d: %s - %s", cycle_id, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["memory", "allocation", "out of memory"]):
                severity = "CRITICAL"
                logger.critical("[15M-LOOP-ERROR] MEMORY cycle=%d: %s - %s", cycle_id, error_type, exc, exc_info=True)
            else:
                severity = "ERROR"
                logger.error("[15M-LOOP-ERROR] UNEXPECTED cycle=%d severity=%s: %s - %s", cycle_id, severity, error_type, exc, exc_info=True)

    async def _run_cycle_wrapper(self, cycle_id: int) -> None:
        # Async wrapper for cycle execution (called from callback).
        loop = asyncio.get_running_loop()
        start = loop.time()
        logger.info("[LOOP-STARTUP-WRAPPER] CYCLE-WRAPPER-ENTER cycle=%d loop_time=%.3f", cycle_id, start)
        
        # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with fixed $1 exposure model
        # This fixes the hardcoded $50 correlation stack cap bug
        logger.info("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR-ENTER: About to fetch bankroll")
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_async
            cycle_bankroll = await get_equity_for_risk_calc_async()
            logger.info("[15M-LOOP-WRAPPER] BALANCE-CALIBRATOR: Fetched bankroll=%s", cycle_bankroll)
            if cycle_bankroll is not None and cycle_bankroll > 0:
                # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with fixed $1 exposure model
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
            # Use cache=False so the loop always sees fresh readiness.
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(get_kalshi_health_snapshot, loop_tick=cycle_id, use_cache=False),
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
        # Start the loop in background task.
        if self._running:
            logger.warning("[15m-LOOP] Loop already running, skipping start")
            return
        
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._stop_event.clear()
        
        # CRITICAL FIX: Reset warmup timer when loop starts (not at module import)
        # This ensures agents have 5 minutes to populate history after actual trading begins
        try:
            from merid.prediction.agent_grid_15m import reset_warmup_timer
            reset_warmup_timer()
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to reset warmup timer: %s", e)
        
        # Initialize risk envelope for kalshi_crypto_15m_v2
        profile = os.getenv("MERID_PROFILE", "").lower()
        if profile == "kalshi_crypto_15m_v2":
            try:
                from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                service = get_risk_envelope_service()
                service.refresh_if_stale(max_age_seconds=30.0)
                self._risk_envelope = service.get_config()
                # CRITICAL FIX (2026-07-17): Removed max_concurrent_trades loading - $1 exposure cap is the limit
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

        # CRITICAL: Start Coinbase WebSocket for external spot velocity signals (Turbine research #1 winner)
        if self._coinbase_client:
            try:
                # Set up velocity signal callback once.  The callback is invoked on
                # every accepted Coinbase tick (including type=neutral) so the grid
                # always has a fresh external velocity snapshot.
                def on_velocity_signal(velocity_signal):
                    asset_map = {
                        "BTC-USD": "BTC",
                        "ETH-USD": "ETH",
                        "SOL-USD": "SOL",
                        "XRP-USD": "XRP",
                        "DOGE-USD": "DOGE",
                    }
                    asset = asset_map.get(velocity_signal.asset, velocity_signal.asset.replace("-USD", ""))
                    if asset in self._coinbase_velocity_signals:
                        self._coinbase_velocity_signals[asset] = {
                            "velocity": velocity_signal.velocity,
                            "timestamp": velocity_signal.timestamp,
                            "signal_type": velocity_signal.signal_type,
                        }
                        # Log at debug to avoid flooding; consumer logs show source.
                        logger.debug(
                            "[COINBASE-VELOCITY] asset=%s velocity=%.8f signal_type=%s",
                            asset, velocity_signal.velocity, velocity_signal.signal_type,
                        )

                self._coinbase_client.on_velocity_signal = on_velocity_signal

                # Start the connection/reconnect/run loop in background.
                asyncio.create_task(self._coinbase_client.run())
                logger.info("[15m-LOOP] Coinbase WebSocket run loop started for external velocity signals")
            except Exception as e:
                logger.error("[15m-LOOP] Failed to start Coinbase WebSocket: %s", e, exc_info=True)

        # CRITICAL: Start PositionMonitor for active TP/SL/trailing exit monitoring
        # CRITICAL FIX (2026-07-17): PositionMonitor start MUST succeed
        # Previously, if start() failed, the system would continue with exit policies disabled.
        # This is a critical safety violation - all positions would ride to settlement without exit enforcement.
        if self._position_monitor:
            try:
                # Register exit callback to trigger exit orders
                def exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close=None):
                    # Callback when PositionMonitor detects exit condition.
                    # CRITICAL FIX: 2026-07-15 - Added robustness improvements:
                    # - Exit order failure tracking
                    # - Position state validation before exit
                    # - Idempotency guard to prevent duplicate exits
                    # CRITICAL FIX (2026-08-22): Do not set exit_triggered before the
                    # order is actually accepted/filled. The PositionMonitor in-flight
                    # state is the source of truth for duplicate suppression.  Setting
                    # exit_triggered in this callback reintroduces the original stuck-
                    # exit bug: if _execute_exit_order returns early (guard/duplicate/
                    # no-market/exception), the terminal flag is never cleared and no
                    # exit order can ever be placed for this position.
                    try:
                        # CRITICAL: Check if position already exited (idempotency guard)
                        if position.exit_triggered:
                            if position.exited_at is not None:
                                logger.warning(
                                    "[POSITION-MONITOR-CALLBACK] Exit intent ignored - position already exited: position=%s reason=%s exit_reason=%s",
                                    position.position_id[:8], exit_reason, position.exit_reason
                                )
                                return
                            # Stale terminal flags from a lost/uncleaned prior exit
                            # attempt.  Clear and proceed so we can actually exit.
                            logger.warning(
                                "[POSITION-MONITOR-CALLBACK] Exit intent had stale exit_triggered, clearing and proceeding: position=%s reason=%s",
                                position.position_id[:8], exit_reason
                            )
                            position.exit_triggered = False
                            position.exit_reason = None
                            position.exit_price_cents = None
                        
                        logger.info(
                            "[POSITION-MONITOR-CALLBACK] Exit intent: position=%s reason=%s price=%dc contracts=%s",
                            position.position_id[:8], exit_reason, exit_price_cents, contracts_to_close or "all"
                        )

                        # CRITICAL FIX (2026-08-10, updated 2026-08-16): Direct STOP_LOSS
                        # exits go through the audited StopCandidate path.  Submission is
                        # gated by MERID_ENABLE_STOP_CANDIDATE_SUBMISSION; when the gate is
                        # off, new entries are rejected with PROTECTIVE_EXIT_DISABLED.
                        reason_str = getattr(exit_reason, "value", str(exit_reason)).lower()
                        if reason_str == "stop_loss":
                            # Position.size is in contracts (Decimal); canonical exposure is centi-contracts.
                            position_cc = to_signed_yes_exposure(
                                position.side.value,
                                int(position.size * Decimal("100")),
                            )
                            candidate = build_stop_candidate(
                                market_ticker=position.market_id,
                                exchange_position_cc=position_cc,
                                trigger_reason="POSITION_MONITOR_STOP",
                                entry_price_cents=position.avg_entry_price_cents,
                                fair_value_cents=None,
                                executable_exit_cents=exit_price_cents,
                                quote_age_ms=None,
                            )
                            record_stop_candidate(candidate)
                            maybe_submit_stop_candidate_sync(candidate)
                            logger.warning(
                                "[POSITION-MONITOR-CALLBACK] STOP_LOSS converted to StopCandidate "
                                "for %s - submission gated by MERID_ENABLE_STOP_CANDIDATE_SUBMISSION",
                                position.market_id,
                            )
                            if self._position_monitor:
                                self._position_monitor._clear_exit_intent_in_flight(position.position_id)
                            return

                        # CRITICAL INVARIANT CHECK: Exit orders can only execute on positions with size > 0
                        if position.size <= 0:
                            logger.warning(
                                "[POSITION-MONITOR-CALLBACK] Exit intent suppressed - no open position: position=%s market=%s size=%d reason=%s",
                                position.position_id[:8], position.market_id, position.size, exit_reason
                            )
                            if self._position_monitor:
                                self._position_monitor._clear_exit_intent_in_flight(position.position_id)
                            return

                        # CRITICAL FIX (2026-08-08): Gate exits by contract liveness. Never place
                        # orders against expired/closed markets; route to settlement reconciliation.
                        try:
                            from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker
                            expiry_ts = parse_expiry_from_ticker(position.market_id)
                            if expiry_ts > 0:
                                now_ts = datetime.now(timezone.utc).timestamp()
                                if now_ts > expiry_ts + 60:  # 60s post-expiry settlement buffer
                                    expiry_iso = datetime.fromtimestamp(expiry_ts, tz=timezone.utc).isoformat()
                                    logger.warning(
                                        "[POSITION-MONITOR-CALLBACK] Exit intent suppressed - market expired: position=%s market=%s expiry=%s reason=%s",
                                        position.position_id[:8], position.market_id, expiry_iso, exit_reason
                                    )
                                    # Record terminal state so the position is not retried
                                    position.exit_triggered = True
                                    position.exit_reason = ExitReason.MARKET_EXPIRED.value
                                    position.exited_at = datetime.utcnow()
                                    if self._position_monitor:
                                        self._position_monitor.remove_position(position.position_id)
                                        self._position_monitor._clear_exit_intent_in_flight(position.position_id)
                                    try:
                                        from merid.event_venues.kalshi.position_cache import get_position_cache
                                        get_position_cache().force_delete_phantom_position(position.market_id)
                                    except Exception as cache_err:
                                        logger.debug("[POSITION-MONITOR-CALLBACK] Failed to remove expired position from cache: %s", cache_err)
                                    return
                        except Exception as expiry_err:
                            logger.debug("[POSITION-MONITOR-CALLBACK] Could not check market expiry: %s", expiry_err)

                        # CRITICAL FIX (2026-08-22): The in-flight flag in PositionMonitor
                        # (and the loop-side position_exit_lock) prevents duplicate callbacks;
                        # do NOT set exit_triggered here.  Setting it before route_order_async
                        # returns creates a stuck terminal state on any early return or
                        # unrecovered exception.  The position is only marked terminal after
                        # a confirmed fill via position.mark_exited().
                        
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
                        logger.error(
                            "[POSITION-MONITOR-CALLBACK] Failed to execute exit: position=%s reason=%s error=%s",
                            position.position_id[:8] if hasattr(position, 'position_id') else 'unknown',
                            exit_reason,
                            cb_err,
                            exc_info=True
                        )
                        # CRITICAL: Track exit intent failures for monitoring
                        if not hasattr(self, '_exit_intent_failures'):
                            self._exit_intent_failures = 0
                        self._exit_intent_failures += 1
                        logger.warning(
                            "[POSITION-MONITOR-CALLBACK] Exit intent failure count: %d",
                            self._exit_intent_failures
                        )
                        # Clear in-flight so the next poll can retry; the position
                        # terminal flags were not touched by a successful fill.
                        if self._position_monitor and position and hasattr(position, 'position_id'):
                            self._position_monitor._clear_exit_intent_in_flight(position.position_id)

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
                
                # CRITICAL FIX (2026-07-23): Run startup health check for exit coverage
                # This ensures that on process restart, any mismatch between positions and
                # resting exit orders is detected and logged before trading resumes.
                # CRITICAL FIX (2026-07-23): Wait for startup grace window to complete
                # before enforcing exit invariants to prevent race conditions.
                try:
                    # Check if we're in startup grace window
                    if self._position_monitor.is_in_startup_grace_window():
                        logger.info(
                            "[STARTUP-EXIT-HEALTH] In startup grace window - skipping exit coverage check until orders are loaded"
                        )
                    else:
                        health_result = self._position_monitor.health_check_exit_coverage()
                        health_status = health_result.get("health_status", "unknown")
                        
                        if health_status == "critical":
                            logger.critical(
                                "[STARTUP-EXIT-HEALTH] CRITICAL: Exit coverage health check failed on startup: %s",
                                health_result
                            )
                            # Continue startup but log critical - positions may ride to settlement without exits
                        elif health_status == "warning":
                            logger.warning(
                                "[STARTUP-EXIT-HEALTH] WARNING: Exit coverage health check found issues on startup: %s",
                                health_result
                            )
                        else:
                            logger.info(
                                "[STARTUP-EXIT-HEALTH] Exit coverage health check passed on startup: %s",
                                health_result
                            )
                except Exception as health_err:
                    logger.error(
                        "[STARTUP-EXIT-HEALTH] Failed to run exit coverage health check on startup: %s",
                        health_err,
                        exc_info=True
                    )
            except Exception as e:
                logger.error("[15m-LOOP] CRITICAL: Failed to start PositionMonitor: %s", e, exc_info=True)
                raise RuntimeError(f"PositionMonitor start failed - exit policies will not execute: {e}")
        else:
            logger.error("[15m-LOOP] CRITICAL: PositionMonitor is None - exit policies will not execute!")
            raise RuntimeError("PositionMonitor is None - exit policies will not execute")


def _safe_int_cents(value: Any) -> Optional[int]:
    """Convert a value to an integer number of cents, rejecting non-integral values."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d != d.to_integral_value():
            return None
        return int(d)
    except Exception:
        return None


def _get_executable_ask_cents(state: Any, held_outcome: str) -> Optional[int]:
    """Return the best ask for the held contract from market state (own-side ask)."""
    if state is None:
        return None
    book = getattr(state, "book", None)
    if held_outcome == "yes":
        ask = getattr(state, "best_ask_cents", None)
        if ask is not None:
            return _safe_int_cents(ask)
        if book is not None:
            if hasattr(book, "best_yes_ask"):
                return _safe_int_cents(getattr(book, "best_yes_ask"))
            if getattr(book, "yes_asks", None):
                return _safe_int_cents(book.yes_asks[0].price_cents)
    else:
        ask = getattr(state, "no_ask_cents", None)
        if ask is not None:
            return _safe_int_cents(ask)
        if book is not None:
            if getattr(book, "no_asks", None):
                return _safe_int_cents(book.no_asks[0].price_cents)
            if hasattr(book, "best_no_ask"):
                return _safe_int_cents(getattr(book, "best_no_ask"))
        yes_bid = getattr(state, "best_bid_cents", None) or (
            getattr(book, "best_yes_bid", None) if book else None
        )
        if yes_bid is not None:
            return _safe_int_cents(100 - int(Decimal(str(yes_bid))))
    return None


def _estimate_exit_fees(entry_price_cents: int, exit_price_cents: int, count: int) -> int:
    """Round-trip taker fee estimate in cents for a closing order."""
    try:
        from merid.event_venues.kalshi.parabolic_fees import kalshi_taker_fee_cents_parabolic

        entry_fee = kalshi_taker_fee_cents_parabolic(entry_price_cents / 100.0, count)
        exit_fee = kalshi_taker_fee_cents_parabolic(exit_price_cents / 100.0, count)
        return max(0, entry_fee + exit_fee)
    except Exception:
        # Fallback: 1% of notional, rounded up, for both sides.
        notional_cents = (entry_price_cents + exit_price_cents) * count
        return max(1, (notional_cents + 99) // 100)


def _canonicalize_exit_reason(exit_reason: Any) -> Tuple[str, str]:
    """Return (original, canonical) exit reason strings."""
    original = str(getattr(exit_reason, "value", exit_reason)).lower()
    canonical = _EXIT_REASON_CANONICAL_MAP.get(original, original)
    return original, canonical


def _run_exit_price_guard(
    position: Any,
    exit_reason: Any,
    exit_price_cents: int,
    count: int,
) -> Tuple[bool, int, Dict[str, Any], str]:
    """Pre-trade exit guardrail: fresh quote, bounded loss, and decision record.

    Returns (approved, approved_exit_price_cents, decision_record, decision_id).
    """
    from merid.event_venues.kalshi.stop_candidate import (
        _book_age_ms,
        _get_executable_exit_cents,
        _get_market_state,
        _seconds_to_expiry,
    )
    from merid.event_venues.kalshi.order_intent_contract import persist_order_decision

    decision_id = f"exit-guard-{uuid.uuid4().hex[:12]}"
    record: Dict[str, Any] = {
        "type": "exit_guard",
        "decision_id": decision_id,
        "position_id": getattr(position, "position_id", None),
        "market_id": getattr(position, "market_id", None),
        "trigger_price_cents": int(exit_price_cents),
        "size": int(getattr(position, "size", 0)),
        "ts": time.time(),
    }

    original, canonical = _canonicalize_exit_reason(exit_reason)
    record["exit_reason_original"] = original
    record["exit_reason_canonical"] = canonical

    if canonical not in MERID_EXIT_ALLOWED_REASONS:
        record.update({"status": "rejected", "reject_reason": "exit_reason_not_allowed"})
        persist_order_decision(record)
        logger.critical(
            "[EXIT-GUARD-REJECT] position=%s market=%s reason=%s - "
            "Exit reason %s is not in the allowed set %s",
            (getattr(position, "position_id", "") or "")[:8],
            getattr(position, "market_id", None),
            original,
            canonical,
            sorted(MERID_EXIT_ALLOWED_REASONS),
        )
        return False, exit_price_cents, record, decision_id

    held_outcome = (
        getattr(position, "outcome_side", None)
        or getattr(position, "thesis_side", None)
        or (getattr(position.side, "value", None) if hasattr(position, "side") else None)
        or ""
    )
    held_outcome = str(held_outcome).lower()
    if held_outcome not in ("yes", "no"):
        record.update({"status": "rejected", "reject_reason": "unknown_held_outcome"})
        persist_order_decision(record)
        logger.critical(
            "[EXIT-GUARD-REJECT] position=%s market=%s - Cannot determine held outcome side",
            (getattr(position, "position_id", "") or "")[:8],
            getattr(position, "market_id", None),
        )
        return False, exit_price_cents, record, decision_id
    record["held_outcome"] = held_outcome

    ks, us = _get_market_state(getattr(position, "market_id", ""))
    state = ks or us
    quote_age_ms = _book_age_ms(state) if state is not None else None
    seconds_to_expiry = _seconds_to_expiry(state) if state is not None else None
    quote_source = (
        getattr(state, "book_source", None)
        or getattr(state, "source", None)
        or ("ws" if ks else ("unified" if us else None))
    )
    best_bid = _get_executable_exit_cents(state, held_outcome) if state is not None else None
    best_ask = _get_executable_ask_cents(state, held_outcome)

    record.update({
        "quote_age_ms": quote_age_ms,
        "seconds_to_expiry": seconds_to_expiry,
        "quote_source": quote_source,
        "best_bid_cents": best_bid,
        "best_ask_cents": best_ask,
        "entry_price_cents": getattr(position, "avg_entry_price_cents", None),
    })

    is_emergency = (
        canonical == "expiry_liquidation"
        and seconds_to_expiry is not None
        and seconds_to_expiry <= MERID_EXIT_EMERGENCY_CUTOFF_SECONDS
    )
    # Forced exits are time/market-driven and must be allowed to realize a loss;
    # otherwise the system holds losing positions into settlement.
    is_forced = canonical in ("expiry_liquidation", "time_exit")
    record["is_emergency"] = is_emergency
    record["is_forced"] = is_forced

    # Quote-freshness gate (tiered by time-to-expiry).
    max_quote_age_ms = _exit_quote_age_limit_ms(seconds_to_expiry)
    if quote_age_ms is None or quote_age_ms > max_quote_age_ms:
        if is_emergency or is_forced:
            logger.warning(
                "[EXIT-GUARD-FORCED] position=%s market=%s - "
                "Quote is stale (age_ms=%s) but reason=%s is forced, proceeding with extra scrutiny",
                (getattr(position, "position_id", "") or "")[:8],
                getattr(position, "market_id", None),
                quote_age_ms,
                canonical,
            )
        else:
            record.update({"status": "rejected", "reject_reason": "stale_quote"})
            persist_order_decision(record)
            logger.critical(
                "[EXIT-GUARD-REJECT] position=%s market=%s reason=%s - "
                "Quote is stale or missing (age_ms=%s, max_ms=%d).",
                (getattr(position, "position_id", "") or "")[:8],
                getattr(position, "market_id", None),
                canonical,
                quote_age_ms,
                max_quote_age_ms,
            )
            return False, exit_price_cents, record, decision_id

    if best_bid is None:
        record.update({"status": "rejected", "reject_reason": "no_executable_bid"})
        persist_order_decision(record)
        logger.critical(
            "[EXIT-GUARD-REJECT] position=%s market=%s - No executable bid for held outcome %s",
            (getattr(position, "position_id", "") or "")[:8],
            getattr(position, "market_id", None),
            held_outcome,
        )
        return False, exit_price_cents, record, decision_id

    # Determine slippage and whether this is a profit exit.
    is_profit_exit = canonical in ("take_profit",)
    slippage = 0 if is_profit_exit else MERID_EXIT_MAX_SLIPPAGE_CENTS

    # Determine the limit price.  For stop exits the limit is anchored to the
    # stop level minus slippage so the order cannot be swept past the stop.
    stop_price = None
    if canonical in _MERID_EXIT_STOP_REASONS:
        stop_price = (
            getattr(position, "stop_loss_price_cents", None)
            or getattr(position, "hard_stop_price_cents", None)
        )
        if stop_price is not None:
            # For both YES and NO, a worse own-side price is lower.
            limit_cents = max(1, stop_price - slippage)
            # The market must still be at or better than this limit; otherwise
            # the stop has already gapped through the slippage bound.
            if best_bid < limit_cents:
                record.update({
                    "status": "rejected",
                    "reject_reason": "stop_beyond_slippage",
                    "stop_price_cents": stop_price,
                    "limit_cents": limit_cents,
                })
                persist_order_decision(record)
                logger.critical(
                    "[EXIT-GUARD-REJECT] position=%s market=%s - "
                    "Best bid %dc is worse than stop-driven limit %dc (slippage=%dc)",
                    (getattr(position, "position_id", "") or "")[:8],
                    getattr(position, "market_id", None),
                    best_bid,
                    limit_cents,
                    slippage,
                )
                return False, exit_price_cents, record, decision_id
        else:
            limit_cents = max(1, best_bid - slippage)
    else:
        limit_cents = best_bid if is_profit_exit else max(1, best_bid - slippage)

    # Clamp to valid Kalshi 1-99 cent range.
    limit_cents = max(1, min(99, int(round(limit_cents))))

    # Projected PnL: own-side price, own-side entry, round-trip taker fees.
    entry_price = int(getattr(position, "avg_entry_price_cents", 0) or 0)
    closed_count = min(int(count), int(getattr(position, "size", 0) or 0))
    gross_expected = (best_bid - entry_price) * closed_count
    gross_worst = (limit_cents - entry_price) * closed_count
    fees = _estimate_exit_fees(entry_price, limit_cents, closed_count)
    net_expected = gross_expected - fees
    net_worst = gross_worst - fees

    record.update({
        "limit_cents": limit_cents,
        "closed_count": closed_count,
        "projected_gross_pnl_cents": gross_expected,
        "projected_fee_cents": fees,
        "projected_net_pnl_cents": net_worst,
    })

    # Max allowed net loss.
    if is_emergency:
        max_loss = MERID_EXIT_EMERGENCY_MAX_LOSS_CENTS
    elif canonical in _MERID_EXIT_STOP_REASONS:
        if stop_price is not None:
            stop_distance = abs(stop_price - entry_price)
            max_loss = stop_distance + slippage + fees
        elif canonical == "trailing_stop":
            # Trailing-stop exits are bounded by the actual giveback from the high
            # watermark to the current executable bid, plus slippage and fees.  The
            # trailing stop decision has already been made by the monitor; the guard
            # just verifies the executable quote is within the natural giveback.
            high_watermark = int(getattr(position, "max_favorable_price_cents", 0) or 0)
            if high_watermark > 0 and best_bid is not None and high_watermark >= best_bid:
                max_loss = (high_watermark - best_bid + slippage) * count + fees
            else:
                trail_distance = int(getattr(position, "trailing_param", 0) or 0)
                if trail_distance <= 0:
                    trail_distance = MERID_EXIT_MAX_LOSS_CENTS
                max_loss = trail_distance + slippage + fees
        else:
            max_loss = MERID_EXIT_MAX_LOSS_CENTS
    else:
        max_loss = MERID_EXIT_MAX_LOSS_CENTS

    record["max_loss_cents"] = max_loss

    # Discretionary (non-stop, non-emergency, non-forced) exits must be profitable after
    # fees and must clear a per-contract minimum profit floor.  Forced exits (expiry_liquidation, time_exit)
    # are allowed to realize a loss to prevent holding losers to settlement.
    is_stop_or_emergency = canonical in _MERID_EXIT_STOP_REASONS or is_emergency or is_forced
    if not is_stop_or_emergency:
        min_profit_total = MERID_EXIT_MIN_PROFIT_CENTS * closed_count
        if net_expected < min_profit_total or net_worst < 0:
            record.update({"status": "rejected", "reject_reason": "profit_exit_not_profitable"})
            persist_order_decision(record)
            logger.error(
                "[EXIT-GUARD-REJECT] position=%s market=%s reason=%s - "
                "Discretionary exit does not meet per-contract minimum profit floor "
                "(expected_net=%dc, worst_net=%dc, min_profit_per_contract=%dc, total_min=%dc, fees=%dc, closed_count=%d)",
                (getattr(position, "position_id", "") or "")[:8],
                getattr(position, "market_id", None),
                canonical,
                net_expected,
                net_worst,
                MERID_EXIT_MIN_PROFIT_CENTS,
                min_profit_total,
                fees,
                closed_count,
            )
            return False, exit_price_cents, record, decision_id

    # Net loss bound.  Forced exits must bypass this, otherwise an expiry or time
    # stop with a large unavoidable loss can never be approved.
    if not is_forced and net_worst < -max_loss:
        record.update({"status": "rejected", "reject_reason": "max_loss_exceeded"})
        persist_order_decision(record)
        logger.critical(
            "[EXIT-GUARD-REJECT] position=%s market=%s reason=%s - "
            "Worst-case net PnL %dc exceeds max allowed loss %dc "
            "(best_bid=%dc limit=%dc entry=%dc fees=%dc)",
            (getattr(position, "position_id", "") or "")[:8],
            getattr(position, "market_id", None),
            canonical,
            net_worst,
            max_loss,
            best_bid,
            limit_cents,
            entry_price,
            fees,
        )
        return False, exit_price_cents, record, decision_id

    record["status"] = "approved"
    persist_order_decision(record)
    logger.info(
        "[EXIT-GUARD-APPROVE] position=%s market=%s reason=%s - "
        "Limit=%dc best_bid=%dc entry=%dc expected_net=%dc worst_net=%dc max_loss=%dc "
        "quote_age_ms=%s source=%s",
        (getattr(position, "position_id", "") or "")[:8],
        getattr(position, "market_id", None),
        canonical,
        limit_cents,
        best_bid,
        entry_price,
        net_expected,
        net_worst,
        max_loss,
        quote_age_ms,
        quote_source,
    )
    return True, limit_cents, record, decision_id


async def _execute_exit_order(
    self,
    position,
    exit_reason,
    exit_price_cents,
    contracts_to_close=None,
    client_order_id: Optional[str] = None,
    resubmit_count: int = 0,
) -> None:
    # Execute exit order when PositionMonitor triggers exit condition.
    # Args:
    #     position: Position to exit
    #     exit_reason: Exit reason
    #     exit_price_cents: Exit price in cents
    #     contracts_to_close: Number of contracts to close (None = full exit)

    # Local helper: clear the monitor's in-flight flag when this coroutine bails
    # before a successful order submission, so the monitor can retry on the next
    # poll instead of waiting for the 15s timeout.
    def _clear_in_flight() -> None:
        if self._position_monitor:
            self._position_monitor._clear_exit_intent_in_flight(position.position_id)

    # CRITICAL INVARIANT CHECKS: Exit orders can only execute on valid positions
    assert position.size > 0, f"EXIT-ORDER: No open position for {position.market_id} - size={position.size}"
    
    # CRITICAL FIX (2026-07-23): Use position-level lock to prevent TOCTOU races
    # Only one thread can create an exit order for a given position at a time
    position_lock = self._position_monitor._get_position_lock(position.position_id)
    
    if not position_lock.acquire(blocking=False):
        logger.warning(
            "[EXIT-ORDER-LOCK] Position %s is locked for exit creation - skipping duplicate attempt",
            position.position_id[:8]
        )
        _clear_in_flight()
        return
    
    try:
        # CRITICAL FIX (2026-07-23): Check exit registry first (source of truth)
        # This is more reliable than querying RestingOrderMonitor which may have websocket lag
        if self._position_monitor._has_exit_order(position.position_id):
            existing_exits = self._position_monitor._get_exit_orders_for_position(position.position_id)
            logger.warning(
                "[EXIT-ORDER-DUPLICATE] Exit order already registered for position=%s - "
                "skipping new exit order to prevent duplicate fills. "
                "Registered exits: %s | New reason: %s | New price: %dc | Partial exit: %s",
                position.position_id[:8],
                existing_exits,
                exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                exit_price_cents,
                contracts_to_close is not None
            )
            _clear_in_flight()
            return
        
        # CRITICAL FIX (2026-07-23): Check for duplicate resting exit orders (one-position-one-exit invariant)
        # Before placing a new exit order, check if a resting exit order already exists for this market_id.
        # This prevents multiple independent exit orders for the same position, which can lead to
        # double-fills, flat-then-reversed states, and inconsistent exposure.
        # CRITICAL: This applies to BOTH full exits and partial exits - only one active exit order per position.
        try:
            from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
            resting_monitor = get_resting_order_monitor()
            
            # Check if there's a resting exit order for this market_id
            existing_exit_orders = resting_monitor.get_orders_by_ticker(position.market_id)
            
            # Filter for exit orders (check source markers)
            from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
            exit_orders = [order for order in existing_exit_orders if is_exit_order_from_source(order.exit_policy_id)]
            
            if exit_orders:
                logger.warning(
                    "[EXIT-ORDER-DUPLICATE] Resting exit order already exists for market=%s - "
                    "skipping new exit order to prevent duplicate fills. "
                    "Existing orders: %s | New reason: %s | New price: %dc | Partial exit: %s",
                    position.market_id,
                    [order.kalshi_order_id for order in exit_orders],
                    exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                    exit_price_cents,
                    contracts_to_close is not None
                )
                # Skip placing new exit order - existing one will handle the exit
                _clear_in_flight()
                return
        except Exception as dup_check_err:
            logger.warning(
                "[EXIT-ORDER-DUPLICATE] Failed to check for duplicate resting exit orders (non-critical): %s",
                dup_check_err
            )
            # Continue with exit order placement if check fails (fail-open for safety)
    finally:
        position_lock.release()
    
    # CRITICAL INVARIANT: Exit orders can only reduce or close existing positions
    # All sizing is in integer centi-contracts so fractional partial exits are exact.
    pre_position_size_cc = int(Decimal(str(position.size)) * Decimal("100"))
    requested_exit_cc = (
        int(Decimal(str(contracts_to_close)) * Decimal("100"))
        if contracts_to_close is not None
        else pre_position_size_cc
    )
    requested_exit_contracts = (
        Decimal(str(contracts_to_close))
        if contracts_to_close is not None
        else Decimal(str(position.size))
    )

    expected_post_position_size_cc = assert_exit_delta(
        pre_position_size_cc=pre_position_size_cc,
        count_cc=requested_exit_cc,
        market_id=position.market_id,
        position_id=position.position_id,
    )

    # EXIT PRICE GUARDRAIL (2026-08-19): fail-closed unless the exit is
    # attributable, bounded, and based on a fresh quote.  The guard re-prices
    # to the executable market and enforces per-reason max-loss / slippage.
    guard_approved, exit_price_cents, guard_record, guard_decision_id = _run_exit_price_guard(
        position=position,
        exit_reason=exit_reason,
        exit_price_cents=exit_price_cents,
        count=int(requested_exit_contracts),
    )
    if not guard_approved:
        logger.critical(
            "[EXIT-ORDER-GUARD-BLOCK] position=%s market=%s reason=%s - "
            "Exit guard rejected the order (record=%s). Position remains open.",
            position.position_id[:8],
            position.market_id,
            exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
            guard_record,
        )
        # CRITICAL FIX (2026-08-20): A rejected exit intent must not leave the
        # position in an in-flight / exit_triggered state.  Clear both so the
        # monitor can re-evaluate on the next poll.
        if self._position_monitor:
            self._position_monitor._clear_exit_intent_in_flight(position.position_id)
        if contracts_to_close is None:
            position.exit_triggered = False
            position.exit_reason = None
            position.exit_price_cents = None
        return

    # Record the chosen exit reason/price for telemetry.  The position is still
    # open; exit_triggered is only set after a confirmed fill.
    position.exit_reason = exit_reason.value if hasattr(exit_reason, 'value') else str(exit_reason)
    position.exit_price_cents = int(exit_price_cents)

    # Derive side_str from position for logging.  Prefer the confirmed canonical
    # outcome_side (from fills/positions) over the immutable strategy thesis.
    if getattr(position, 'outcome_side', None):
        side_str = position.outcome_side
    elif hasattr(position, 'thesis_side') and position.thesis_side:
        side_str = position.thesis_side
    else:
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)

    assert side_str in ("yes", "no", "YES", "NO"), f"EXIT-ORDER: Invalid side_str={side_str} for {position.market_id}"

    # Derive canonical asset and agent_id for this exit order once.
    # Use the same asset-prefixed agent_id as entry orders for audit consistency
    # and to avoid leaking a module name into the agent_id field.
    lifecycle_asset = "unknown"
    for _prefix, _asset_name in (("KXBTC", "BTC"), ("KXETH", "ETH"), ("KXSOL", "SOL"), ("KXXRP", "XRP"), ("KXDOGE", "DOGE")):
        if position.market_id.startswith(_prefix):
            lifecycle_asset = _asset_name
            break
    agent_id = f"{lifecycle_asset}_15M" if lifecycle_asset != "unknown" else "position_monitor"

    # CRITICAL: Check venue availability before attempting exit order
    # This prevents exit orders from failing silently when venue is unavailable
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.utils.kalshi_identity import extract_asset
        catalog = get_market_catalog()
        asset = extract_asset(position.market_id)
        asset_markets = catalog.get_active_markets(asset=asset, timeframe="15m")
        
        if not asset_markets:
            logger.error(
                "[EXIT-LIVENESS-FAIL] asset=%s market=%s reason=VENUE_UNAVAILABLE - "
                "No active 15m market found for asset, exit order cannot execute. "
                "Position will remain open until venue recovers.",
                asset,
                position.market_id
            )
            _clear_in_flight()
            return
    except Exception as venue_check_err:
        from merid.utils.kalshi_identity import extract_asset
        asset = extract_asset(position.market_id)
        logger.warning(
            "[EXIT-LIVENESS-FAIL] asset=%s market=%s reason=VENUE_CHECK_FAILED - "
            "Failed to check venue availability (non-critical): %s. "
            "Proceeding with exit order attempt.",
            asset,
            position.market_id,
            venue_check_err
        )
    
    # CRITICAL: Check for circuit breaker cooldown on REST series fetches
    # This prevents exit orders from failing when series data is throttled
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.utils.kalshi_identity import extract_asset
        client = get_kalshi_client()
        asset = extract_asset(position.market_id)
        
        # Check if client is in circuit breaker cooldown
        if hasattr(client, '_circuit_breaker_cooldown_until'):
            now = time.time()
            if now < client._circuit_breaker_cooldown_until:
                cooldown_remaining = client._circuit_breaker_cooldown_until - now
                logger.error(
                    "[EXIT-LIVENESS-FAIL] asset=%s market=%s reason=CIRCUIT_BREAKER_COOLDOWN - "
                    "REST client in circuit breaker cooldown for %.1fs, exit order may fail. "
                    "Proceeding with exit order attempt (may use stale data).",
                    asset,
                    position.market_id,
                    cooldown_remaining
                )
    except Exception as circuit_check_err:
        from merid.utils.kalshi_identity import extract_asset
        asset = extract_asset(position.market_id)
        logger.debug(
            "[EXIT-LIVENESS-FAIL] asset=%s market=%s reason=CIRCUIT_CHECK_FAILED - "
            "Failed to check circuit breaker status (non-critical): %s",
            asset,
            position.market_id,
            circuit_check_err
        )
    
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
                agent_id=agent_id,
                asset=asset or lifecycle_asset or "unknown",
                ticker=position.market_id,
                entry_price_cents=exit_price_cents,
                edge_pct=0.0,  # Exit orders don't have edge
                spread_cents=0,  # Exit orders don't care about spread
                confidence=0.5,  # Default confidence for exit orders
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
        from merid.event_venues.kalshi.exit_finalizer import (
            ExitOrderAttempt,
            can_finalize_full_exit,
        )
        from merid.event_venues.kalshi.canonical_portfolio import get_canonical_portfolio_store
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import get_canonical_portfolio_reconciler
        
        # CRITICAL FIX (2026-07-23): Verify exit orders bypass window limits
        # Exit orders are routed directly via route_order_async and do NOT go through
        # top3_batch_manager.validate_order where check_window_limit is called.
        # This ensures exit orders are never blocked by window-based risk limits.
        logger.info(
            "[EXIT-ORDER-WINDOW-BYPASS] Exit order routing path: direct route_order_async (bypasses top3 gate window limits)"
        )
        
        # CRITICAL FIX (2026-08-07): Exit direction must be derived from the confirmed
        # net venue exposure (outcome_side / book_side) and never from the immutable
        # strategy thesis.  The thesis predicts the market; the position record reports
        # what the exchange actually filled.
        from merid.event_venues.kalshi.strategy_positions import ThesisSide, build_exit_order

        confirmed_outcome = getattr(position, "outcome_side", None) or position.thesis_side
        if not confirmed_outcome:
            logger.error(
                "[EXIT-ORDER-CONFIRMED] Position %s has neither outcome_side nor thesis_side - "
                "CANNOT GENERATE EXIT ORDER",
                position.position_id[:8]
            )
            return

        # If the live confirmed exposure disagrees with the prediction thesis, the
        # confirmed exposure wins and a mismatch is logged for audit.
        if (
            getattr(position, "outcome_side", None)
            and position.thesis_side
            and position.outcome_side != position.thesis_side
        ):
            logger.critical(
                "[EXIT-ORDER-THESIS-MISMATCH] position=%s thesis_side=%s confirmed_outcome=%s - "
                "using confirmed exposure for exit",
                position.position_id[:8],
                position.thesis_side,
                position.outcome_side,
            )
        
        # Initialize action variable to prevent UnboundLocalError
        action = "SELL"
        
        # Build exit order using pure function from domain layer (if feature flag is False)
        if not USE_LEGACY_DIRECTION_MAPPING and confirmed_outcome:
            # Create a temporary StrategyPosition for the pure function.
            # The canonical outcome is the confirmed live exposure, not the thesis.
            from merid.event_venues.kalshi.strategy_positions import StrategyPosition
            try:
                thesis_side = ThesisSide.from_outcome_side(confirmed_outcome)
            except ValueError as e:
                logger.error(
                    "[EXIT-ORDER-CONFIRMED] Invalid confirmed outcome_side=%s: %s - CANNOT GENERATE EXIT ORDER",
                    confirmed_outcome, e
                )
                _clear_in_flight()
                return

            temp_position = StrategyPosition(
                ticker=position.market_id,
                agent_id=position.position_id or position.market_id or "",
                thesis_side=thesis_side,
                size_fp=position.size,
                avg_entry_price_cents=int(position.avg_entry_price_cents) if hasattr(position, 'avg_entry_price_cents') else 0
            )

            try:
                # CRITICAL FIX (2026-08-23): build_exit_order accepts fractional whole-contract
                # Decimal qty. requested_exit_contracts is the canonical whole-contract amount.
                exit_order = build_exit_order(temp_position, requested_exit_contracts, exit_price_cents)
                kalshi_side = exit_order["kalshi_side"]
                outcome_side = exit_order["outcome_side"]
                action = exit_order["action"]

                # VERIFICATION: Exit order logging (ticker, confirmed_outcome, exit_outcome_side, action, size_fp)
                logger.info(
                    "[EXIT-ORDER-GENERATION] ticker=%s confirmed_outcome=%s exit_outcome_side=%s action=%s kalshi_side=%s size_fp=%d price_cents=%d",
                    position.market_id, confirmed_outcome, outcome_side, action, kalshi_side, requested_exit_cc, exit_price_cents
                )

                logger.info(
                    "[EXIT-ORDER-PURE-FUNCTION] Built exit order using pure function: "
                    "confirmed=%s -> kalshi_side=%s count_fp=%d price=%dc",
                    confirmed_outcome, kalshi_side, requested_exit_cc, exit_price_cents
                )
            except ValueError as e:
                logger.error(
                    "[EXIT-ORDER-PURE-FUNCTION] Failed to build exit order: %s - CANNOT GENERATE EXIT ORDER",
                    e
                )
                # CRITICAL FIX: No fallback to legacy logic - fail closed
                logger.error(
                    "[EXIT-ORDER-CONFIRMED] Pure function failed - CANNOT GENERATE EXIT ORDER (fallback removed to prevent side inversion - Bug #6 fix)"
                )
                _clear_in_flight()
                return  # Fail closed - cannot generate exit order without valid confirmed outcome
        else:
            # CRITICAL FIX: No legacy fallback - fail closed if confirmed outcome not available
            logger.error(
                "[EXIT-ORDER-CONFIRMED] Confirmed outcome not available - CANNOT GENERATE EXIT ORDER "
                "(legacy fallback removed to prevent side inversion - Bug #6 fix)"
            )
            _clear_in_flight()
            return  # Fail closed - require confirmed outcome for all exits

        # AUDIT: Venue-side semantics - log Kalshi order semantics for exit
        logger.info(
            "[VENUE-SEMANTICS-AUDIT] position=%s market=%s exit_reason=%s "
            "kalshi_side=%s order_type=limit time_in_force=ioc aggressiveness=1.0 price=%dc count_fp=%d "
            "thesis_conversion=%s->%s executable=YES",
            position.position_id[:8],
            position.market_id,
            exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
            kalshi_side,
            exit_price_cents,
            requested_exit_cc,
            thesis_side,
            kalshi_side
        )
        
        logger.info(
            "[EXIT-ORDER] Kalshi side conversion: thesis_side=%s action=%s -> kalshi_side=%s",
            thesis_side, action, kalshi_side
        )

        # Create exit OrderIntent
        # CRITICAL FIX (2026-07-12): Exit orders MUST be marketable (aggressiveness=1.0) to execute immediately
        # Previous bug: exit orders defaulted to aggressiveness=0.0 (resting), causing them to rest on book
        # and potentially never fill when market moved away. Exit orders reduce exposure and should
        # execute immediately to lock in profits or stop losses.
        # CRITICAL FIX: Add exit_policy_id to satisfy order router validation for exit orders
        # Exit orders require exit_policy_id for tracking per _validate_risk_contract_linkage
        # CRITICAL FIX (2026-07-20): Add formal entry/exit direction contract fields
        # Populate entry_or_exit, exit_reason, pre_position_size, expected_post_position_size
        # to enforce position-delta invariants in order_router
        from merid.prediction.intent_contract import ExitReason as IntentExitReason
        
        # Map position_management.ExitReason to intent_contract.ExitReason
        exit_reason_str = exit_reason.value if hasattr(exit_reason, 'value') else str(exit_reason)
        intent_exit_reason = _map_exit_reason_to_intent_contract(exit_reason_str)
        
        # Position sizes already calculated and validated in invariant checks above
        # pre_position_size and expected_post_position_size are available from invariant section
        
        # CRITICAL FIX (2026-08-27): Pre-trade profitability check is now fee-aware.
        # It uses the canonical taker fee schedule and the position size to compute
        # the minimum exit price that produces a positive net profit per contract.
        # Risk-management exits (STOP_LOSS, SETTLEMENT_GUARD, TRAILING_STOP, TIME_STOP,
        # RISK, EDGE_DECAY, etc.) bypass this check to prevent runaway losses.
        entry_price = position.avg_entry_price_cents

        # Reasons that must always execute, regardless of exit price vs entry.
        exit_reason_str = str(getattr(exit_reason, 'value', exit_reason)).lower()
        bypass_profit_check_reasons = {
            'stop_loss', 'settlement_guard', 'auto_exit_99c', 'trail', 'trailing_stop',
            'time_stop', 'edge_decay', 'risk', 'stale_data', 'candle_reversal',
            'adaptive_timing', 'opportunity_cost', 'loss_cut_40pct', 'manual'
        }
        enforce_profit_check = exit_reason_str not in bypass_profit_check_reasons

        # Bid-ask spread warning (illiquid markets).
        MAX_SPREAD_THRESHOLD_CENTS = 5
        current_bid_cents = 0
        current_ask_cents = 0
        current_spread_cents = -1

        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            market_state = get_kalshi_market_state_store().get(position.market_id)
            if market_state:
                current_bid_cents = market_state.bid_cents
                current_ask_cents = market_state.ask_cents
                if current_bid_cents and current_ask_cents:
                    current_spread_cents = current_ask_cents - current_bid_cents
                    if current_spread_cents > MAX_SPREAD_THRESHOLD_CENTS:
                        logger.warning(
                            "[EXIT-SPREAD-WARNING] position=%s market=%s spread=%dc (threshold=%dc) "
                            "Market is illiquid - exit may have significant slippage. "
                            "exit_price=%dc bid=%dc ask=%dc",
                            position.position_id[:8],
                            position.market_id,
                            current_spread_cents,
                            MAX_SPREAD_THRESHOLD_CENTS,
                            exit_price_cents,
                            current_bid_cents,
                            current_ask_cents
                        )
        except Exception as spread_err:
            logger.debug(
                "[EXIT-SPREAD-CHECK] Failed to get market state for spread check (non-critical): %s",
                spread_err
            )

        if entry_price > 0:
            profit_margin_cents = exit_price_cents - entry_price
            if exit_price_cents < entry_price:
                if enforce_profit_check:
                    logger.error(
                        "[EXIT-PRICE-VALIDATION-FAIL] position=%s market=%s exit_price=%dc < entry_price=%dc "
                        "REJECTING exit order - would sell below entry price causing loss. "
                        "exit_reason=%s current_price=%dc profit_margin=%dc spread=%dc",
                        position.position_id[:8],
                        position.market_id,
                        exit_price_cents,
                        entry_price,
                        exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                        position.current_price_cents if hasattr(position, 'current_price_cents') else 0,
                        profit_margin_cents,
                        current_spread_cents
                    )
                    _clear_in_flight()
                    return
                else:
                    logger.warning(
                        "[EXIT-PRICE-VALIDATION-SKIP] position=%s market=%s exit_price=%dc < entry_price=%dc "
                        "bypassing profitability check for risk exit. "
                        "exit_reason=%s current_price=%dc profit_margin=%dc spread=%dc",
                        position.position_id[:8],
                        position.market_id,
                        exit_price_cents,
                        entry_price,
                        exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                        position.current_price_cents if hasattr(position, 'current_price_cents') else 0,
                        profit_margin_cents,
                        current_spread_cents
                    )
            elif enforce_profit_check:
                from merid.event_venues.kalshi.fees import (
                    min_profitable_exit_price_cents,
                    TAKE_PROFIT_MIN_PROFIT_CENTS,
                )
                min_profitable = min_profitable_exit_price_cents(
                    entry_price,
                    requested_exit_contracts,
                    gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                )
                if min_profitable is None:
                    min_profitable = entry_price + TAKE_PROFIT_MIN_PROFIT_CENTS

                if exit_price_cents < min_profitable:
                    logger.error(
                        "[EXIT-PRICE-VALIDATION-FAIL] position=%s market=%s exit_price=%dc < min_profitable=%dc "
                        "REJECTING exit order - would not be net profitable after round-trip taker fees. "
                        "exit_reason=%s entry=%dc profit_margin=%dc spread=%dc",
                        position.position_id[:8],
                        position.market_id,
                        exit_price_cents,
                        min_profitable,
                        exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                        entry_price,
                        profit_margin_cents,
                        current_spread_cents
                    )
                    _clear_in_flight()
                    return

                logger.info(
                    "[EXIT-PRICE-VALIDATION-PASS] position=%s market=%s exit_price=%dc entry=%dc "
                    "min_profitable=%dc profit_margin=%dc exit_reason=%s spread=%dc",
                    position.position_id[:8],
                    position.market_id,
                    exit_price_cents,
                    entry_price,
                    min_profitable,
                    profit_margin_cents,
                    exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                    current_spread_cents
                )
            else:
                logger.info(
                    "[EXIT-PRICE-VALIDATION-PASS] position=%s market=%s exit_price=%dc entry=%dc "
                    "risk_exit=true exit_reason=%s spread=%dc",
                    position.position_id[:8],
                    position.market_id,
                    exit_price_cents,
                    entry_price,
                    exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
                    current_spread_cents
                )
        else:
            logger.warning(
                "[EXIT-PRICE-VALIDATION-SKIP] position=%s market=%s entry_price=%dc - cannot validate profitability",
                position.position_id[:8],
                position.market_id,
                entry_price
            )

        # TRADE-TRACE LOG: Exit decision to IntentContract conversion
        # Logs direction, pre_size, post_size, and exit_reason on a single line
        # AUDIT: Timing correctness - track latency from trigger to intent creation
        intent_creation_ts = __import__('time').monotonic()
        logger.info(
            "[EXIT-INTENT-CONTRACT] position=%s market=%s direction=%s pre_size_fp=%d post_size_fp=%d "
            "exit_reason=%s exit_price=%dc type=%s intent_ts=%.3f",
            position.position_id[:8],
            position.market_id,
            "exit",
            pre_position_size_cc,
            expected_post_position_size_cc,
            intent_exit_reason.value,
            exit_price_cents,
            "FULL_EXIT" if contracts_to_close is None else f"PARTIAL_EXIT({contracts_to_close})",
            intent_creation_ts
        )
        
        # EXIT PRICE GUARD (2026-08-19): the _run_exit_price_guard above has
        # already re-priced the IOC limit from a fresh executable quote, applied
        # the per-reason max-loss / slippage bound, and persisted a decision
        # record.  Do not double-reprice with the older bounded-liquidation block.

        # CRITICAL FIX (2026-08-22): Preserve exact fractional contract count.
        # ``OrderIntent.count`` is a display/integer field; the canonical size is
        # ``count_fp``.  ``pre_position_fp`` and ``expected_post_position_fp`` are
        # integer centi-contracts and carry exact fractional position sizes.
        _count_fp = Decimal(requested_exit_cc) / Decimal("100")
        _pre_position_fp = pre_position_size_cc
        _expected_post_position_fp = expected_post_position_size_cc
        # Display values are whole-contract floors; canonical invariants use the FP fields.
        _pre_position_size = pre_position_size_cc // 100
        _expected_post_position_size = expected_post_position_size_cc // 100
        _count = requested_exit_cc // 100

        # CRITICAL FIX (2026-08-22): Separate parentage identifiers.  Never
        # promote a signal_id into a fill_id; that falsifies the identity chain.
        _entry_fill_id = getattr(position, "entry_fill_id", None)
        _entry_order_id = (
            getattr(position, "client_order_id", None)
            or getattr(position, "entry_order_id", None)
            or getattr(position, "entry_intent_id", None)
        )
        _entry_signal_id = getattr(position, "entry_signal_id", None)

        if _entry_fill_id and isinstance(_entry_fill_id, str) and _entry_fill_id.strip():
            _parentage_status = "CANONICAL_FILL"
        elif _entry_order_id and isinstance(_entry_order_id, str) and _entry_order_id.strip():
            _parentage_status = "ORDER_LINKED"
        elif _entry_signal_id and isinstance(_entry_signal_id, str) and _entry_signal_id.strip():
            _parentage_status = "SIGNAL_ONLY"
        else:
            _parentage_status = "UNKNOWN"

        # 2026-08-24: REST-synced and replayed positions often lack a real
        # ``entry_fill_id``.  Use the strongest available durable parent id
        # (order/intent) as the parent fill linkage for exit parentage checks,
        # while keeping parentage_status honest about the chain quality.
        _parent_entry_fill_id = _entry_fill_id
        if not (_parent_entry_fill_id and _parent_entry_fill_id.strip()):
            _parent_entry_fill_id = _entry_order_id

        intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
            action=action,  # Keep as lowercase "buy"/"sell" for early validation
            price_cents=int(round(exit_price_cents)),
            count=_count,
            count_fp=_count_fp,  # CRITICAL FIX (2026-08-22): preserve exact fractional count
            order_type="limit",  # Limit order with marketable aggressiveness = marketable-limit
            time_in_force="ioc",  # CRITICAL FIX (2026-08-07): Exits are IOC, never GTC
            source="position_monitor_exit",
            agent_id=agent_id,  # CRITICAL: Use asset-prefixed agent_id, not a module name
            rationale=f"exit_reason:{exit_reason_str}",  # Use rationale for exit reason
            exit_policy_id=position.exit_policy_id,  # CRITICAL FIX: Required for exit order validation
            aggressiveness=1.0,  # CRITICAL FIX: Force marketable execution for immediate fill
            reduce_only=True,  # CRITICAL FIX (2026-08-07): Exits must reduce, never increase, exposure
            # ENTRY/EXIT DIRECTION CONTRACT FIELDS
            entry_or_exit="exit",  # Formal direction classification
            exit_reason=intent_exit_reason.value,  # Mapped exit reason for invariants
            pre_position_size=_pre_position_size,  # Display whole-contract size before order
            expected_post_position_size=_expected_post_position_size,  # Display whole-contract size after order
            pre_position_fp=_pre_position_fp,  # Exact centi-contract size before order
            expected_post_position_fp=_expected_post_position_fp,  # Exact centi-contract size after order
            # EXIT GUARD (2026-08-19): carry the guard decision and parent fill for audit.
            decision_id=guard_decision_id,
            reason=f"exit:{exit_reason_str}",
            # CRITICAL FIX (2026-08-22): Separate durable parentage identifiers.  A
            # signal_id proves a strategy signal existed, not that a fill created
            # the position, so it is kept in its own field.
            parent_entry_fill_id=_parent_entry_fill_id,
            parent_entry_order_id=_entry_order_id,
            parent_entry_signal_id=_entry_signal_id,
            parentage_status=_parentage_status,
        )

        # CRITICAL FIX (2026-08-24): Finalize the durable order identity before the
        # order is marked in-flight and before route_order_async.  Each exit attempt
        # gets a fresh, persisted (client_order_id, order_attempt_id) pair, so retries
        # cannot collide with a previous attempt's identity record and the in-flight
        # tracker always carries the canonical wire id.
        #
        # CRITICAL FIX (2026-08-25): If a previous exit attempt for this position
        # is still unresolved, reuse its client_order_id. Kalshi idempotency makes
        # same-ClOrdID resubmission safe and prevents double-exits.
        try:
            from merid.event_venues.kalshi.order_identity import (
                finalize_order_identity,
                derive_exit_client_order_id,
                derive_exit_intent_id,
            )

            # CRITICAL FIX (2026-08-27): Derive a stable, authoritative exit identity
            # from the entry fill id so exit parentage and audit logs share one key.
            exit_parent_id = (
                getattr(position, "entry_fill_id", None)
                or getattr(position, "client_order_id", None)
                or position.position_id
            )
            intent.intent_id = derive_exit_intent_id(exit_parent_id, exit_reason_str)

            if not client_order_id and self._position_monitor:
                client_order_id = self._position_monitor._get_unresolved_exit_client_order_id(
                    position.position_id
                )
            if client_order_id:
                intent.client_order_id = client_order_id
                intent.client_tag = client_order_id
                logger.info(
                    "[EXIT-ORDER] Reusing unresolved client_order_id=%s for position=%s resubmit=%d",
                    client_order_id[:8] if client_order_id else "",
                    position.position_id[:8],
                    resubmit_count,
                )
            else:
                client_order_id = derive_exit_client_order_id(
                    exit_parent_id, exit_reason_str, resubmit_count=resubmit_count
                )
                intent.client_order_id = client_order_id
                intent.client_tag = client_order_id

            intent.run_id = os.environ.get("MERID_RUN_ID") or f"live_exit_{int(time.time())}"
            intent.process_id = str(os.getpid())
            finalize_order_identity(intent)
        except Exception as identity_err:
            logger.error(
                "[EXIT-ORDER-IDENTITY-REJECT] position=%s market=%s error=%s",
                position.position_id[:8],
                position.market_id,
                identity_err,
            )
            _clear_in_flight()
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)
            return

        # LIFECYCLE-EXIT CANONICAL LOG SCHEMA (machine-parseable, single line)
        logger.info(
            "[LIFECYCLE-EXIT] asset=%s ticker=%s agent_id=%s thesis_side=%s action=%s kalshi_side=%s "
            "size_before_fp=%d size_after_fp=%d count_fp=%d price_cents=%d exit_reason=%s entry_or_exit=exit client_order_id=%s",
            lifecycle_asset,
            position.market_id,
            agent_id,
            side_str.lower(),
            action.lower(),
            kalshi_side,
            _pre_position_fp,
            _expected_post_position_fp,
            requested_exit_cc,
            exit_price_cents,
            exit_reason_str,
            intent.client_order_id,
        )

        logger.info(
            "[EXIT-ORDER] Routing exit order: ticker=%s side=%s action=%s count=%d count_fp=%s price=%dc reason=%s client_order_id=%s order_attempt_id=%s",
            position.market_id, side_str, action, _count, str(_count_fp), exit_price_cents, exit_reason, intent.client_order_id, intent.order_attempt_id
        )

        # CRITICAL FIX (2026-08-20): Update in-flight intent with the real client
        # order id so the monitor can reconcile a timeout by looking up the order.
        # 2026-08-25: carry the trigger reason so in-flight diagnostics are not reset to "unknown".
        self._position_monitor._mark_exit_intent_in_flight(
            position.position_id, client_order_id=intent.client_order_id, reason=exit_reason_str
        )

        # CRITICAL FIX (2026-07-23): Register exit submission in cache before routing
        # This handles websocket lag - order is treated as "exists" even if not yet visible
        self._position_monitor._register_exit_submission(
            intent.client_order_id, position_id=position.position_id
        )

        # CRITICAL FIX (2026-08-22): Persist a durable order-attempt record before
        # any network I/O. This is the source of truth for in-flight reconciliation;
        # the in-flight lock must not be cleared without an attempt record on disk.
        try:
            from merid.event_venues.kalshi.order_intent_contract import persist_order_decision

            # Generate a durable attempt id.  The tuple (position_id, intent_id,
            # attempt_id) must be unique across retries and restarts.
            if not intent.order_attempt_id:
                intent.order_attempt_id = f"exit_attempt_{__import__('uuid').uuid4().hex}"

            persist_order_decision(
                {
                    "type": "exit_order_attempt",
                    "status": "submitted",
                    "position_id": position.position_id,
                    "market_id": position.market_id,
                    "client_order_id": intent.client_order_id,
                    "intent_id": intent.intent_id,
                    "order_attempt_id": intent.order_attempt_id,
                    "parent_entry_fill_id": intent.parent_entry_fill_id,
                    "parent_entry_order_id": intent.parent_entry_order_id,
                    "parent_entry_signal_id": intent.parent_entry_signal_id,
                    "parentage_status": intent.parentage_status,
                    "guard_decision_id": guard_decision_id,
                    "exit_reason": (
                        exit_reason.value
                        if hasattr(exit_reason, "value")
                        else str(exit_reason)
                    ),
                    "price_cents": exit_price_cents,
                    "count": _count,
                    "count_fp": str(_count_fp),
                    "pre_position_size": _pre_position_size,
                    "expected_post_position_size": _expected_post_position_size,
                    "pre_position_fp": _pre_position_fp,
                    "expected_post_position_fp": _expected_post_position_fp,
                }
            )
        except Exception as attempt_err:
            logger.warning(
                "[EXIT-ORDER-ATTEMPT-PERSIST] failed (non-critical): %s", attempt_err
            )

        # Capture the authoritative portfolio snapshot in effect when the order
        # is submitted.  The exit can only be finalized against a snapshot that
        # is strictly newer and after the submission timestamp.
        pre_submit_snapshot = get_canonical_portfolio_store().current()
        pre_submit_version = (
            pre_submit_snapshot.version if pre_submit_snapshot is not None else 0
        )
        submit_started_at_ns = time.time_ns()
        exit_attempt = ExitOrderAttempt(
            pre_submit_snapshot_version=pre_submit_version,
            submit_started_at_ns=submit_started_at_ns,
            submitted_count_fp=_count_fp,
        )

        # Route the exit order. For a lost POST ack, the in-router reconcile may
        # return not_submitted (authoritative empty) -> resubmit with the same
        # client_order_id. For submission_unknown / duplicate_unknown, keep the
        # in-flight lock and return; do NOT re-arm or clear it.
        _max_resubmits = 2
        _current_resubmit = resubmit_count
        while True:
            result = await route_order_async(intent)
            route_ok = _confirmed_submission(result)
            if route_ok:
                break

            _result_status = getattr(result, "status", "")
            _result_reason = getattr(result, "reason", "") or _result_status

            if _result_status == "not_submitted":
                if _current_resubmit >= _max_resubmits:
                    logger.error(
                        "[EXIT-ORDER] not_submitted resubmit limit reached: "
                        "position=%s market=%s client_order_id=%s attempts=%d",
                        position.position_id[:8],
                        position.market_id,
                        intent.client_order_id,
                        _current_resubmit + 1,
                    )
                    if self._position_monitor:
                        self._position_monitor._mark_exit_intent_submission_unknown(
                            position.position_id,
                            "not_submitted_resubmit_limit_exhausted",
                        )
                    return
                _current_resubmit += 1
                logger.warning(
                    "[EXIT-ORDER] Exit not_submitted; resubmitting with same client_order_id=%s "
                    "attempt=%d/%d",
                    intent.client_order_id,
                    _current_resubmit,
                    _max_resubmits + 1,
                )
                await asyncio.sleep(0.2)
                continue

            if getattr(result, "requires_recovery", False) or _result_status in (
                "submission_unknown",
                "duplicate_unknown",
            ):
                logger.warning(
                    "[EXIT-ORDER] Exit in %s state; keeping in-flight for reconcile: "
                    "position=%s market=%s client_order_id=%s",
                    _result_status,
                    position.position_id[:8],
                    position.market_id,
                    intent.client_order_id,
                )
                if self._position_monitor:
                    self._position_monitor._mark_exit_intent_submission_unknown(
                        position.position_id, _result_reason
                    )
                return

            # Any other failure (risk, firewall, hard reject) is terminal for this attempt.
            logger.error(
                "[EXIT-ORDER] route_order_async returned no confirmed order: "
                "position=%s market=%s status=%s reason=%s",
                position.position_id[:8],
                position.market_id,
                _result_status,
                _result_reason,
            )
            if self._position_monitor:
                self._position_monitor._mark_exit_intent_retryable(
                    position.position_id,
                    "RouteNoOrder",
                    f"status={_result_status} reason={_result_reason}",
                )
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)
            return

        # CRITICAL FIX (2026-08-23): Only mark the exit intent as SUBMITTED after a
        # successful router/exchange call. Prior to this point it is EXECUTION_PENDING.
        if self._position_monitor:
            self._position_monitor._mark_exit_intent_submitted(
                position.position_id,
                exchange_order_id=getattr(result, "order_id", None),
                client_order_id=intent.client_order_id,
                reason=exit_reason.value if hasattr(exit_reason, "value") else str(exit_reason),
            )

        # CRITICAL FIX (2026-08-23): Cooldown is a side effect, not an execution
        # prerequisite. Update it only after the order is confirmed SUBMITTED.
        try:
            from merid.prediction.strip_order_state import get_strip_order_state, ExitReason as StripExitReason

            strip_state = get_strip_order_state()
            cooldown_reason = None
            reason_str = exit_reason.value if hasattr(exit_reason, "value") else str(exit_reason)
            if reason_str == "stale_data":
                cooldown_reason = StripExitReason.STALEDATA
            elif reason_str == "risk":
                cooldown_reason = StripExitReason.RISK_LIMIT
            elif reason_str == "low_liquidity":
                cooldown_reason = StripExitReason.LOW_LIQUIDITY
            elif reason_str == "regime_halted":
                cooldown_reason = StripExitReason.REGIME_HALTED
            if cooldown_reason:
                strip_state.set_cooldown(
                    ticker=position.market_id,
                    exit_reason=cooldown_reason,
                    duration_seconds=300,
                )
                logger.info(
                    "[COOLDOWN-UPDATED] position_key=%s reason=%s duration=300s",
                    position.position_key, cooldown_reason.value
                )
        except Exception as cooldown_err:
            logger.info(
                "[COOLDOWN-UPDATE-FAILED-NONBLOCKING] position_key=%s exit_order_allowed=True "
                "cooldown_update=FAILED_NONBLOCKING error=%s",
                position.position_key, cooldown_err
            )

        # CRITICAL FIX (2026-08-22): Do not use ``result.remaining_quantity_cc``
        # as a proxy for account position size.  For an IOC, Kalshi's
        # ``remaining_count`` is the unexecuted portion of THIS order, not the
        # remaining account position.  A full close is only proven by an
        # exchange/cache-reconciled position quantity of zero.
        exchange_position_confirmed = False
        post_position_cc: Optional[int] = None
        if result and (result.is_terminal or result.has_execution):
            post_position_cc = await _get_canonical_post_position_cc(
                position.market_id, fallback_cc=None
            )
            if post_position_cc is not None:
                exchange_position_confirmed = True

        if post_position_cc is None:
            # No live exchange/cache source.  Derive a conservative fallback from
            # the order result only.  This is a degraded path and must never mark
            # a position terminal without at least a fully-filled exit order that
            # matches or exceeds the pre-position size.
            if result and result.has_execution:
                filled_cc = result.executed_quantity_cc
                post_position_cc = max(0, pre_position_size_cc - filled_cc)
                logger.warning(
                    "[EXIT-RECONCILE-FALLBACK] position=%s market=%s "
                    "filled_cc=%d pre_cc=%d post_cc=%d - no exchange/cache confirmation",
                    position.position_id[:8],
                    position.market_id,
                    filled_cc,
                    pre_position_size_cc,
                    post_position_cc,
                )
            else:
                post_position_cc = pre_position_size_cc

        # CRITICAL FIX (2026-08-22): Full exit finalization now requires an
        # authoritative post-order portfolio snapshot.  The snapshot must be
        # strictly newer than the submission snapshot, MATCHED, and prove zero
        # exchange position and no working exit order for this market.
        can_finalize = False
        finalizer_reason = "NO_RESULT"
        fresh_snapshot = None
        if result:
            try:
                fresh_snapshot = await get_canonical_portfolio_reconciler().build_snapshot()
                get_canonical_portfolio_store().publish(fresh_snapshot)
            except Exception as snap_err:
                logger.warning(
                    "[EXIT-FINALIZER] position=%s market=%s - failed to build fresh snapshot: %s",
                    position.position_id[:8],
                    position.market_id,
                    snap_err,
                )

            if fresh_snapshot is not None:
                can_finalize, finalizer_reason = can_finalize_full_exit(
                    snapshot=fresh_snapshot,
                    attempt=exit_attempt,
                    order_result=result,
                    position_key=position.market_id,
                    now_ns=time.time_ns(),
                )

        if can_finalize:
            logger.info(
                "[EXIT-ORDER] Position flat confirmed: order_id=%s status=%s reason=%s",
                result.order_id, result.status, finalizer_reason
            )

            # CRITICAL FIX (2026-07-29): Wire hedge auto-exit to alpha exit events
            # When an alpha position exits, trigger hedge auto-exit to close associated hedge positions
            # This prevents orphaned hedge positions that outlive their alpha positions
            try:
                from merid.hedging.pnl_tracker import get_hedge_pnl_tracker
                from merid.hedging.config import get_hedge_config

                # Get alpha fill ID from position (used to link to hedge positions)
                alpha_fill_id = getattr(position, 'fill_id', None)
                if alpha_fill_id:
                    hedge_tracker = get_hedge_pnl_tracker()
                    hedge_config = get_hedge_config()

                    # Trigger hedge auto-exit for this alpha position
                    hedge_exit_orders = hedge_tracker.auto_exit_hedges(
                        hedge_config,
                        closed_alpha_fills=[alpha_fill_id]
                    )

                    if hedge_exit_orders:
                        logger.info(
                            "[HEDGE-AUTO-EXIT] Triggered hedge exit for alpha fill=%s: %d hedge exit orders generated",
                            alpha_fill_id[:8],
                            len(hedge_exit_orders)
                        )
                    else:
                        logger.debug(
                            "[HEDGE-AUTO-EXIT] No hedge positions to close for alpha fill=%s",
                            alpha_fill_id[:8]
                        )
            except Exception as hedge_exit_err:
                logger.warning(
                    "[HEDGE-AUTO-EXIT] Failed to trigger hedge auto-exit for alpha position (non-critical): %s",
                    hedge_exit_err,
                    exc_info=True
                )

            # CRITICAL FIX (2026-07-23): Register exit order in first-class registry
            # This is the source of truth for exit orders, reducing reliance on exchange data
            # Pass the exit quantity for quantity-aware coverage invariant
            if result and result.order_id:
                self._position_monitor._register_exit_order(position.position_id, result.order_id, _count)

            # 2026-08-22 CRITICAL FIX: the position is only terminal after the
            # canonical portfolio snapshot proves it is flat.
            position.mark_exited(
                exit_reason.value if hasattr(exit_reason, 'value') else str(exit_reason),
                exit_price_cents,
            )
            self._position_monitor.remove_position(position.position_id)
            logger.critical(
                "[EXIT-ORDER-CONFIRMED] position=%s market=%s status=%s order_id=%s "
                "- position removed after confirmed full execution",
                position.position_id[:8],
                position.market_id,
                getattr(result, "status", "no_result"),
                getattr(result, "order_id", None),
            )
        elif result and result.has_execution:
            # The order executed but the finalizer is not satisfied (partial fill,
            # working order remains, portfolio not authoritative, etc.).  Update
            # the monitor's copy to the reconciled quantity and re-arm.
            if fresh_snapshot is not None:
                new_size = max(Decimal("0"), fresh_snapshot.exchange_position_fp(position.market_id))
            elif post_position_cc is not None:
                new_size = Decimal(post_position_cc) / Decimal("100")
            else:
                filled_cc = result.executed_quantity_cc
                new_size = max(Decimal("0"), Decimal(pre_position_size_cc - filled_cc) / Decimal("100"))

            logger.warning(
                "[EXIT-ORDER-PARTIAL] position=%s market=%s order_id=%s "
                "reason=%s new_size=%s - re-arming for remaining close",
                position.position_id[:8],
                position.market_id,
                result.order_id,
                finalizer_reason,
                new_size,
            )
            position.size = new_size
            position.mark_reconciling(finalizer_reason)
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close=None)
        else:
            logger.error(
                "[EXIT-ORDER] Exit order did not execute: status=%s error=%s reason=%s finalizer=%s",
                getattr(result, "status", "no_result"),
                getattr(result, "error", None),
                getattr(result, "reason", None),
                finalizer_reason,
            )
            # CRITICAL FIX (2026-07-16): Re-arm the position for retry on failure
            position.mark_reconciling(finalizer_reason)
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)

    except Exception as e:
        logger.error("[EXIT-ORDER] Failed to execute exit order: %s", e, exc_info=True)
        error_type = type(e).__name__
        is_code_failure = isinstance(e, (ImportError, ModuleNotFoundError, SyntaxError, NameError, AttributeError))
        if is_code_failure:
            # CRITICAL FIX (2026-08-23): Deployment/code failures must NOT be treated as
            # market rejections or retry attempts. Record reconciliation required and
            # re-arm without incrementing the retry counter.
            if self._position_monitor:
                self._position_monitor._mark_exit_intent_reconciliation_required(
                    position.position_id, error_type, str(e)
                )
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close, is_code_failure=True)
        else:
            if self._position_monitor:
                self._position_monitor._mark_exit_intent_retryable(
                    position.position_id, error_type, str(e)
                )
            # CRITICAL FIX (2026-07-16): Re-arm the position for retry on failure
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)

def _rearm_position_after_failed_exit(self, position, exit_reason, contracts_to_close=None, is_code_failure=False) -> None:
    # Re-arm a position in the PositionMonitor after a failed exit order.

    # CRITICAL FIX (2026-07-16): Previously a failed/rejected exit order left the
    # position orphaned - removed from monitoring (full exits) with no retry - so a
    # live position rode to settlement with NO exit enforcement. This violates the
    # "all trades are executed with the exit policy" invariant.
    # For full exits: reset exit state and re-add to the monitor so the exit
    # condition re-fires on the next poll. For partial exits: the position is still
    # monitored; restore the optimistically-decremented size so the retry closes
    # the correct amount.
    try:
        # 2026-08-11 CRITICAL FIX: always clear the in-flight flag before re-arming,
        # whether full or partial, so the monitor can re-evaluate exit conditions.
        if self._position_monitor:
            self._position_monitor._clear_exit_intent_in_flight(position.position_id)

        retry_count = getattr(position, "exit_retry_count", 0)
        if not is_code_failure:
            retry_count += 1
        position.exit_retry_count = retry_count

        # AUDIT: Idempotency - log retry attempt with dedupe context.
        # CRITICAL FIX (2026-08-23): The dedupe key must be stable across retries;
        # do not embed a per-attempt retry counter or a mutable string in the identity.
        retry_dedupe_key = (
            f"{position.position_id}:"
            f"{exit_reason.value if hasattr(exit_reason, 'value') else exit_reason}:"
            f"{'FULL_EXIT' if contracts_to_close is None else 'PARTIAL_EXIT'}"
        )
        logger.info(
            "[IDEMPOTENCY-AUDIT] position=%s market=%s reason=%s retry_count=%d dedupe_key=%s rearming_for_retry",
            position.position_id[:8],
            position.market_id,
            exit_reason.value if hasattr(exit_reason, "value") else exit_reason,
            retry_count,
            retry_dedupe_key
        )
        
        # CRITICAL FIX (2026-07-16): Add retry limit to prevent infinite retry loops
        # Without this, a position could keep retrying exits indefinitely if orders
        # keep failing (e.g., during market outage or API issues). Limit to 3 retries.
        MAX_EXIT_RETRIES = 3
        if retry_count > MAX_EXIT_RETRIES:
            # CRITICAL FIX (2026-08-08): If the market is already expired/closed,
            # stop retrying and route the position to settlement reconciliation.
            if (
                self._position_monitor
                and self._position_monitor._is_expired_market(position.market_id)
            ):
                logger.warning(
                    "[EXIT-ORDER-RETRY] market_expired after retries: position=%s market=%s reason=%s - "
                    "routing to settlement reconciliation",
                    position.position_id[:8],
                    position.market_id,
                    exit_reason.value if hasattr(exit_reason, "value") else exit_reason,
                )
                position.exit_triggered = True
                position.exit_reason = ExitReason.MARKET_EXPIRED.value
                position.exited_at = datetime.utcnow()
                self._position_monitor.remove_position(position.position_id)
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    get_position_cache().force_delete_phantom_position(position.market_id)
                except Exception as cache_err:
                    logger.debug("[EXIT-ORDER-RETRY] Failed to remove expired position from cache: %s", cache_err)
                return

            logger.error(
                "[EXIT-ORDER-RETRY] Position exceeded max exit retries (%d): position=%s market=%s reason=%s - "
                "ABANDONING position to settlement (manual intervention required)",
                MAX_EXIT_RETRIES,
                position.position_id[:8],
                position.market_id,
                exit_reason.value if hasattr(exit_reason, "value") else exit_reason,
            )
            # 2026-08-11 CRITICAL FIX: Do not remove the position when max retries are
            # exceeded while the market is still tradeable. The exchange is still
            # authoritative and holds the position; the monitor must retain it and the
            # allocator must retain capacity. Alert and stop further retries but leave
            # the position in the monitor for manual/rested settlement.
            if self._position_monitor:
                self._position_monitor._clear_exit_intent_in_flight(position.position_id)
            logger.critical(
                "[EXIT-ORDER-BLOCKED] Position exceeded max exit retries (%d): position=%s market=%s reason=%s - "
                "EXCHANGE POSITION STILL OPEN; monitor and capacity retained; manual intervention required",
                MAX_EXIT_RETRIES,
                position.position_id[:8],
                position.market_id,
                exit_reason.value if hasattr(exit_reason, 'value') else exit_reason,
            )
            return
        
        position.exit_retry_count = retry_count

        if contracts_to_close is None:
            # Full exit failed: clear exit state so monitor checks re-fire
            position.exit_triggered = False
            position.exit_reason = None
            position.exit_price_cents = None
            position.exited_at = None
            
            # CRITICAL FIX (2026-07-16): Clear all trigger flags to allow re-triggering
            # Without this, partial exit flags (scale_out_triggered, ratchet_trimmed, etc.)
            # would remain set after a failed full exit retry, preventing those conditions
            # from ever triggering again on the re-armed position.
            position.scale_out_triggered = False
            position.ratchet_trimmed = False
            position.dynamic_tp_triggered = False
            position.break_even_triggered = False
            # Note: trailing_profit_zone_activated is runtime state, not persisted, so it's
            # automatically reset when the position is re-added to the monitor

            if self._position_monitor:
                # 2026-08-11 CRITICAL FIX: clear the in-flight flag so the next poll can
                # re-evaluate the exit condition and attempt another order.
                self._position_monitor._clear_exit_intent_in_flight(position.position_id)
                # add_position is idempotent (skips if position_id already present)
                self._position_monitor.add_position(position)

            logger.warning(
                "[EXIT-ORDER-RETRY] Re-armed position for exit retry: position=%s market=%s "
                "reason=%s retry_count=%d - exit will re-fire on next poll",
                position.position_id[:8],
                position.market_id,
                exit_reason.value if hasattr(exit_reason, "value") else exit_reason,
                retry_count,
            )
        else:
            # Partial exit failed: position still monitored; restore trimmed size
            position.size += contracts_to_close
            logger.warning(
                "[EXIT-ORDER-RETRY] Partial exit failed, restored size: position=%s market=%s "
                "size=%d (+%d restored) reason=%s retry_count=%d",
                position.position_id[:8],
                position.market_id,
                position.size,
                contracts_to_close,
                exit_reason.value if hasattr(exit_reason, "value") else exit_reason,
                retry_count,
            )
    except Exception as rearm_err:
        logger.error(
            "[EXIT-ORDER-RETRY] Failed to re-arm position after failed exit: %s",
            rearm_err,
            exc_info=True,
        )

def _compute_allow_new_entries(self, cycle_bankroll: Optional[float]) -> bool:
    """Compute whether new entries are allowed for the current loop tick.

    Mirrors the logic in compute_loop_state using data available to _run_loop.
    Returns True only when the catalog/WS/bankroll are healthy and at least
    one asset has a live, depth-sufficient 15m market.
    """
    from merid.event_venues.kalshi.kalshi_config import KALSHI_READY
    from merid.event_venues.kalshi.market_catalog import get_market_catalog

    live_bankroll_valid = cycle_bankroll is not None and cycle_bankroll > 0
    infra_ready = KALSHI_READY and live_bankroll_valid
    markets_expected = markets_expected_now()

    # Ensure risk envelope is loaded so depth thresholds are correct.
    risk_envelope = self._get_cached_envelope(cycle_bankroll) if cycle_bankroll else getattr(self, "_risk_envelope", None)

    markets_present = False
    ready_assets_count = 0
    md_fresh_count = 0
    spot_fresh_count = 0

    # 2026-08-24: Collect per-ticker readiness for the ENTRY-READINESS audit log.
    per_ticker_readiness: List[Dict[str, Any]] = []

    try:
        catalog = get_market_catalog()

        # Spot service for freshness gate (best effort).
        spot_service = None
        try:
            from data.unified_spot_service import get_unified_spot_service, SpotError
            spot_service = get_unified_spot_service()
        except Exception:
            spot_service = None

        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            current_market = catalog.get_current_15m_market(asset)
            if current_market is None:
                continue
            markets_present = True
            market_id = (
                current_market.market.market_id
                if hasattr(current_market, "market")
                else current_market.market_id
            )
            state = self.market_state_store.get(market_id) if self.market_state_store else None
            if state is None:
                continue

            # CRITICAL FIX (2026-08-22): Use the authoritative *entry* readiness gate
            # for per-asset MD freshness.  This guarantees that the loop's allow-new-entry
            # decision agrees with the order-router stale-data gate under one clock domain
            # and prevents new signals from pricing off unconfirmed WS bootstrap snapshots.
            asset_md_fresh = False
            if self.market_state_store is not None:
                if hasattr(self.market_state_store, "is_market_entry_ready"):
                    asset_md_fresh, md_reason = self.market_state_store.is_market_entry_ready(market_id)
                else:
                    asset_md_fresh, md_reason = self.market_state_store.is_market_execution_ready(market_id)
                if not asset_md_fresh:
                    logger.info(
                        "[15M-LOOP-MD-READY] asset=%s ticker=%s not entry-ready: %s",
                        asset, market_id, md_reason,
                    )

            if asset_md_fresh:
                md_fresh_count += 1

            # Spot freshness (best effort).
            asset_spot_fresh = False
            if spot_service:
                try:
                    spot_result = spot_service.get(asset)
                    if not isinstance(spot_result, SpotError):
                        spot_ts = getattr(spot_result, "timestamp", 0)
                        if spot_ts:
                            asset_spot_fresh = (time.time() - (spot_ts / 1000.0)) < 30.0
                except Exception:
                    pass
            if asset_spot_fresh:
                spot_fresh_count += 1

            # Depth/liquidity sufficiency: use the same function as the main loop.
            if risk_envelope is not None:
                try:
                    depth_thresholds = risk_envelope.get_depth_thresholds(asset)
                    target_qty = int(depth_thresholds.get("min_depth_yes", 1))
                    max_slippage_cents = getattr(risk_envelope, "guardrails_max_slippage_cents", 3)
                except Exception:
                    target_qty = 1
                    max_slippage_cents = 3
            else:
                target_qty = 1
                max_slippage_cents = 3

            liquidity_result = can_fill_order_safely(state, target_qty, max_slippage_cents, side="yes")
            if (
                asset_md_fresh
                and liquidity_result.decision in (LiquidityDecision.FULL, LiquidityDecision.REDUCED)
            ):
                ready_assets_count += 1

            per_ticker_readiness.append({
                "asset": asset,
                "ticker": market_id,
                "catalog_ready": current_market is not None,
                "selected": True,
                "md_fresh": asset_md_fresh,
                "md_reason": md_reason if not asset_md_fresh else "",
                "spot_fresh": asset_spot_fresh,
                "depth_ok": liquidity_result.decision in (LiquidityDecision.FULL, LiquidityDecision.REDUCED),
                "market_state": state,
            })

    except Exception as e:
        logger.warning("[15m-LOOP] Failed to compute allow_new_entries: %s", e)

    _, _, _, allow_new_entries = compute_loop_state(
        infra_ready=infra_ready,
        markets_expected=markets_expected,
        markets_present=markets_present,
        ready_assets_count=ready_assets_count,
        md_fresh_count=md_fresh_count,
        spot_fresh_count=spot_fresh_count,
    )

    # P0 FIX: hard entry gate on WS bridge pipeline backpressure.
    # A market cannot be considered fresh for new entries while its public
    # data pipeline is backlogged, stalled, or the forwarder has stopped
    # processing events. This keeps the loop and router gates aligned.
    ws_queue_size = 0
    ws_time_since_last_event = float("inf")
    ws_healthy = True
    ws_first_event_ts = 0.0
    ws_queue_threshold = int(os.getenv("MERID_KALSHI_WS_QUEUE_ALLOW_THRESHOLD", "30000"))
    ws_queue_age_s = 0.0
    ws_queue_max_age_s = float(os.getenv("MERID_WS_QUEUE_MAX_AGE_S", "3.0"))
    if allow_new_entries:
        try:
            bridge = getattr(self, "_ws_bridge", None)
            if bridge is not None:
                bridge_health = bridge.get_forward_loop_health() or {}
                ws_queue_size = int(bridge_health.get("queue_size", 0) or 0)
                ws_time_since_last_event = float(bridge_health.get("time_since_last_event", float("inf")) or float("inf"))
                ws_healthy = bool(bridge_health.get("healthy", True))
                ws_first_event_ts = float(bridge_health.get("first_event_ts", 0.0) or 0.0)
                ws_last_event_ts = float(bridge_health.get("last_event_ts", 0.0) or 0.0)

                # CRITICAL FIX: compute_ws_health returns time_since_last_event=None (which
                # becomes inf here) when event_count_total==0, even if last_event_ts is
                # already set. This creates a transient "stalled for infs" false positive
                # at startup. Fall back to a direct last_event_ts-based age to avoid it.
                if not math.isfinite(ws_time_since_last_event) and ws_last_event_ts > 0.0:
                    ws_time_since_last_event = time.monotonic() - ws_last_event_ts

                # HARDEN (2026-08-23): Use queue *age* as the real freshness signal,
                # not an arbitrary backlog count.  A 60k backlog that drains in 500ms
                # is healthy; a 1k backlog that drains in 5s is stale.  If the
                # forwarder reports events_per_sec, estimate the backlog drain time.
                ws_queue_threshold = int(os.getenv("MERID_KALSHI_WS_QUEUE_ALLOW_THRESHOLD", "30000"))
                events_per_sec = float(bridge_health.get("events_per_sec", 0) or 0)
                ws_queue_age_s = (
                    ws_queue_size / events_per_sec
                    if events_per_sec and events_per_sec > 0.0
                    else 0.0
                )
                ws_queue_max_age_s = float(
                    os.getenv("MERID_WS_QUEUE_MAX_AGE_S", "3.0")
                )

                if ws_queue_size > ws_queue_threshold and ws_queue_age_s > ws_queue_max_age_s:
                    logger.warning(
                        "[15m-LOOP] ENTRY_BLOCKED: WS bridge queue stale backlog=%d drain_age=%.2fs > %.2fs",
                        ws_queue_size, ws_queue_age_s, ws_queue_max_age_s,
                    )
                    allow_new_entries = False
                elif ws_first_event_ts > 0.0 and ws_time_since_last_event > 5.0:
                    # Only declare the forwarder stalled after the first event
                    # has been seen; during startup the last_event clock may
                    # legitimately exceed 1s before the first message arrives.
                    logger.warning(
                        "[15m-LOOP] ENTRY_BLOCKED: WS forwarder stalled for %.1fs",
                        ws_time_since_last_event,
                    )
                    allow_new_entries = False
                elif not ws_healthy and ws_first_event_ts > 0.0:
                    logger.warning(
                        "[15m-LOOP] ENTRY_BLOCKED: WS forwarder not healthy",
                    )
                    allow_new_entries = False
        except Exception as e:
            logger.warning("[15m-LOOP] WS bridge health check failed: %s", e)

    # P0 FIX: portfolio authority gate. New entries require an authoritative,
    # non-stale canonical portfolio snapshot. Exits remain enabled.
    portfolio_age_ms = 0
    portfolio_authoritative = True
    if allow_new_entries:
        try:
            from merid.event_venues.kalshi.canonical_portfolio import get_canonical_portfolio_store
            portfolio = get_canonical_portfolio_store().current()
            if portfolio is not None:
                portfolio_authoritative = bool(portfolio.is_authoritative)
                portfolio_age_ms = int(portfolio.age_ms)
                if not portfolio_authoritative:
                    logger.warning(
                        "[15m-LOOP] ENTRY_BLOCKED: portfolio not authoritative status=%s reason=%s age_ms=%d",
                        portfolio.reconciliation_status,
                        portfolio.reconciliation_reason,
                        portfolio_age_ms,
                    )
                    allow_new_entries = False
                elif portfolio_age_ms > 300000:
                    # P0 FIX: The canonical portfolio reconciler runs every 60s. A 10s
                    # threshold caused constant false-positive entry blocks. 300s gives
                    # the reconciler several cycles plus long REST/build processing slack.
                    logger.warning(
                        "[15m-LOOP] ENTRY_BLOCKED: portfolio stale age_ms=%d > 300000",
                        portfolio_age_ms,
                    )
                    allow_new_entries = False
        except Exception as e:
            logger.warning("[15m-LOOP] Portfolio authority check failed: %s", e)

    logger.info(
        "[15m-LOOP] allow_new_entries=%s infra_ready=%s markets_expected=%s markets_present=%s "
        "ready_assets=%d md_fresh=%d spot_fresh=%d ws_queue=%d ws_lag=%.3fs ws_first=%.3f portfolio_authoritative=%s portfolio_age_ms=%d",
        allow_new_entries, infra_ready, markets_expected, markets_present, ready_assets_count, md_fresh_count, spot_fresh_count,
        ws_queue_size, ws_time_since_last_event, ws_first_event_ts, portfolio_authoritative, portfolio_age_ms,
    )

    # 2026-08-24: Per-ticker ENTRY-READINESS structured log.  This is the primary
    # diagnostic for rollover failures: it shows, for every active contract, which
    # gate is preventing entry (catalog, MD, quote, portfolio, intent, queue).
    #
    # 2026-08-24 (P0): `allow_new_entries` is now derived from per-ticker
    # `all_ready` eligibility.  The previous global-only gate could be True while
    # every individual market was blocked (e.g. by ws_snapshot_complete), which
    # produced misleading "allow_new_entries=true" audit logs and masked the
    # actual failure.  We collect per-ticker blockers, then recompute the global
    # gate so it is only True when at least one selected market can actually
    # enter.
    ws_queue_healthy = not (
        ws_queue_size > ws_queue_threshold and ws_queue_age_s > ws_queue_max_age_s
    ) and not (ws_first_event_ts > 0.0 and ws_time_since_last_event > 5.0) and ws_healthy
    readiness_records: List[Dict[str, Any]] = []
    try:
        from merid.event_venues.kalshi.order_intent_contract import (
            ticker_has_stale_pending_entry_intent,
        )

        for r in per_ticker_readiness:
            state = r["market_state"]
            ticker = r["ticker"]

            ws_subscribed = state is not None
            ws_snapshot_complete = state is not None and getattr(state, "snapshot_complete", False)
            quote_fresh = r["md_fresh"]
            md_reason = (r.get("md_reason") or "").lower()
            if self.market_state_store is not None:
                quote_coherent, quote_coherence_reason = self.market_state_store.is_quote_coherent(ticker)
                qm = self.market_state_store.get_queue_lock_metrics(ticker)
            else:
                quote_coherent = quote_fresh and "divergence" not in md_reason
                quote_coherence_reason = None
                qm = {"lock_contention_count": 0, "total_lock_wait_ms": 0.0, "last_batch_duration_ms": 0.0, "queue_depth": 0}
            market_state_applied = state is not None
            intent_state_clean = not ticker_has_stale_pending_entry_intent(ticker)

            # 2026-08-24: incorporate per-ticker queue/lock metrics into queue health.
            queue_lock_wait_ms = qm.get("total_lock_wait_ms", 0.0)
            queue_batch_duration_ms = qm.get("last_batch_duration_ms", 0.0)
            queue_lock_contention_count = qm.get("lock_contention_count", 0)
            queue_healthy = (
                ws_queue_healthy
                and queue_lock_wait_ms < 500.0
                and queue_batch_duration_ms < 250.0
                and queue_lock_contention_count < 5
            )

            checks = [
                ("catalog_ready", r["catalog_ready"]),
                ("selected", r["selected"]),
                ("ws_subscribed", ws_subscribed),
                ("ws_snapshot_complete", ws_snapshot_complete),
                ("quote_fresh", quote_fresh),
                ("quote_coherent", quote_coherent),
                ("market_state_applied", market_state_applied),
                ("portfolio_authoritative", portfolio_authoritative),
                ("intent_state_clean", intent_state_clean),
                ("queue_healthy", queue_healthy),
            ]
            blocker_name = next((name for name, ok in checks if not ok), None)
            if blocker_name == "quote_coherent" and quote_coherence_reason:
                blocker = f"{blocker_name}:{quote_coherence_reason}"
            else:
                blocker = blocker_name
            all_ready = all(ok for _, ok in checks)

            readiness_records.append({
                "r": r,
                "ticker": ticker,
                "ws_subscribed": ws_subscribed,
                "ws_snapshot_complete": ws_snapshot_complete,
                "quote_fresh": quote_fresh,
                "quote_coherent": quote_coherent,
                "market_state_applied": market_state_applied,
                "portfolio_authoritative": portfolio_authoritative,
                "intent_state_clean": intent_state_clean,
                "queue_healthy": queue_healthy,
                "queue_lock_wait_ms": queue_lock_wait_ms,
                "queue_batch_duration_ms": queue_batch_duration_ms,
                "queue_lock_contention_count": queue_lock_contention_count,
                "blocker_name": blocker_name,
                "blocker": blocker,
                "all_ready": all_ready,
            })

        # Recompute the global allow_new_entries from per-ticker eligibility.
        # Global blockers (bridge backpressure, portfolio authority) are already
        # applied in `allow_new_entries`; this step additionally requires that at
        # least one selected market passes every per-ticker gate.
        any_ready = any(rec["all_ready"] for rec in readiness_records)
        original_allow_new_entries = allow_new_entries
        allow_new_entries = allow_new_entries and any_ready

        if original_allow_new_entries and not any_ready and readiness_records:
            unready = [rec for rec in readiness_records if not rec["all_ready"]]
            blocker_counts = Counter(rec["blocker"] for rec in unready if rec["blocker"])
            # Map the canonical blocker to a count; None (all ready) is impossible here.
            blocker_summary = " ".join(
                f"{blocker}={count}" for blocker, count in blocker_counts.most_common()
            )
            logger.warning(
                "[15m-LOOP] ENTRY_DISABLED_ALL_MARKETS "
                "aggregate_blockers=%s total_unready=%d",
                blocker_summary,
                len(unready),
            )
        elif not original_allow_new_entries and any_ready:
            # Global gate is down (e.g. bridge backpressure) but some markets
            # are individually healthy.  Keep the aggregate reason concise.
            logger.warning(
                "[15m-LOOP] ENTRY_DISABLED_GLOBAL_GATE "
                "markets_ready=%d global_allow=%s",
                sum(1 for rec in readiness_records if rec["all_ready"]),
                original_allow_new_entries,
            )

        # Log the final per-ticker readiness using the recomputed global gate.
        for rec in readiness_records:
            ticker_entries_allowed = allow_new_entries and rec["all_ready"]
            readiness = EntryReadiness(
                ticker=rec["ticker"],
                catalog_ready=rec["r"]["catalog_ready"],
                selected=rec["r"]["selected"],
                ws_subscribed=rec["ws_subscribed"],
                ws_snapshot_complete=rec["ws_snapshot_complete"],
                quote_fresh=rec["quote_fresh"],
                quote_coherent=rec["quote_coherent"],
                market_state_applied=rec["market_state_applied"],
                portfolio_authoritative=rec["portfolio_authoritative"],
                intent_state_clean=rec["intent_state_clean"],
                queue_healthy=rec["queue_healthy"],
                queue_lock_wait_ms=rec["queue_lock_wait_ms"],
                queue_batch_duration_ms=rec["queue_batch_duration_ms"],
                queue_lock_contention_count=rec["queue_lock_contention_count"],
                entries_allowed=ticker_entries_allowed,
                blocker=rec["blocker"],
            )
            logger.info(readiness.to_log_message(), extra=readiness.__dict__)
    except Exception as e:
        logger.debug("[15M-LOOP] ENTRY-READINESS log failed: %s", e)

    # 2026-08-24: Re-log the final, per-ticker-derived allow_new_entries.  This
    # guarantees the audit line matches the actual return value used to decide
    # whether the trading cycle is allowed to place new orders.
    logger.info(
        "[15m-LOOP] allow_new_entries_final=%s derived_from_per_ticker=%s "
        "markets_ready=%d markets_total=%d ws_queue=%d ws_lag=%.3fs portfolio_authoritative=%s",
        allow_new_entries,
        any(rec["all_ready"] for rec in readiness_records) if readiness_records else None,
        sum(1 for rec in readiness_records if rec["all_ready"]),
        len(readiness_records),
        ws_queue_size,
        ws_time_since_last_event,
        portfolio_authoritative,
    )

    # EXIT_DECOUPLING: update the PositionMonitor with the current entry-gate state.
    # Exit evaluation must remain independent of allow_new_entries; this is only for
    # the structured EXIT_EVAL audit log so both gate dimensions are visible together.
    try:
        monitor = getattr(self, "_position_monitor", None)
        if monitor is not None and hasattr(monitor, "set_entry_gate_context"):
            ws_lag_ms = ws_time_since_last_event * 1000.0 if math.isfinite(ws_time_since_last_event) else -1.0
            monitor.set_entry_gate_context({
                "allow_new_entries": bool(allow_new_entries),
                "ws_queue_size": int(ws_queue_size),
                "ws_lag_ms": float(ws_lag_ms),
            })
    except Exception as e:
        logger.debug("[15m-LOOP] Failed to update PositionMonitor entry gate context: %s", e)

    return allow_new_entries

async def _run_loop(self) -> None:
    # Main loop execution - runs trading cycles at configured cadence.
    tick_id = 0
    logger.info("[15m-LOOP] Entering main loop")
    
    try:
        while self._running and not self._stop_event.is_set():
            tick_id += 1
            cycle_start = time.time()
            logger.info("[15m-LOOP] Starting tick %d", tick_id)
            
            # CRITICAL FIX: Track current tick for tick-scoped lifecycle reconciliation
            self._current_tick = tick_id
            
            # Reset per-tick counters for sanity checks
            self._tick_executed_count = 0
            
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
                
                # Initialize all assets to 0 (use Decimal to match position.notional_value type)
                from decimal import Decimal
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._asset_positions[asset] = Decimal('0.0')
                
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
                            notional = Decimal(str(position.notional_value))
                            self._asset_positions[asset] += notional
                            # CRITICAL FIX (2026-07-31): Log individual position notional for debugging
                            logger.debug(
                                "[15m-LOOP] Position notional: market=%s asset=%s contracts=%d avg_price=%dc notional=%s",
                                market_id, asset, position.contracts, position.avg_price_cents, notional
                            )
                
                logger.info("[15m-LOOP] Reloaded positions from cache: %s", list(self._asset_positions.keys()) if hasattr(self._asset_positions, 'keys') else str(self._asset_positions))
                
                # CRITICAL FIX (2026-07-31): Detect 0 exposure bug
                # If we have positions but all assets show 0 exposure, this indicates a bug
                total_positions = sum(1 for p in all_positions.values() if p.contracts > 0)
                total_exposure = sum(self._asset_positions.values())
                if total_positions > 0 and total_exposure == 0:
                    logger.critical(
                        "[15m-LOOP] CRITICAL BUG DETECTED: %d positions loaded but total exposure is 0. "
                        "This indicates position cache notional calculation is failing. "
                        "Positions: %s",
                        total_positions,
                        {mid: (p.contracts, p.avg_price_cents) for mid, p in all_positions.items() if p.contracts > 0}
                    )
                
                # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with fixed $1 exposure model
                # This fixes the hardcoded $50 correlation stack cap bug
                logger.info("[15m-LOOP] BALANCE-CALIBRATOR-ENTER: About to fetch bankroll")
                cycle_bankroll = None
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_async
                    cycle_bankroll = await get_equity_for_risk_calc_async()
                    logger.info("[15m-LOOP] BALANCE-CALIBRATOR: Fetched bankroll=%s", cycle_bankroll)
                    if cycle_bankroll is not None and cycle_bankroll > 0:
                        # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with fixed $1 exposure model
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
                    
                    # CRITICAL FIX (2026-07-16): Trigger catalog refresh on 15m window boundary
                    # This ensures the catalog is updated immediately when markets roll over
                    # preventing trading on expired markets during the brief window after rollover
                    logger.info("[15m-LOOP] WINDOW-CHANGE: Triggering catalog refresh for new 15m window")
                    try:
                        from merid.event_venues.kalshi.market_catalog import get_market_catalog
                        catalog = get_market_catalog()
                        # Force a refresh to get new markets for the new window
                        # Add timeout to prevent indefinite blocking if catalog refresh hangs
                        await asyncio.wait_for(catalog.refresh(force=True), timeout=30.0)
                        logger.info("[15m-LOOP] WINDOW-CHANGE: Catalog refresh completed for new window")
                    except asyncio.TimeoutError:
                        logger.error("[15m-LOOP] WINDOW-CHANGE: Catalog refresh timed out after 30s - will retry on next periodic refresh")
                    except Exception as e:
                        logger.warning(f"[15m-LOOP] WINDOW-CHANGE: Failed to trigger catalog refresh: {e}", exc_info=True)
                    
                    # Reset best-edge tracking for new window
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        self._best_edge_per_asset[asset] = None
                    logger.info("[15m-LOOP] Reset best-edge tracking for new window")
                    
                    # Reset swing mode for new window (swing mode only valid within same 15m window)
                    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
                    logger.info("[15m-LOOP] Reset swing mode for new window")
                    
                    # CRITICAL FIX (2026-07-15): Clear phantom slots from global slot allocator on timeframe transition
                    # This prevents false "Insufficient exposure" rejections when old slots from previous timeframe persist
                    logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing phantom slots from global slot allocator")
                    try:
                        from merid.event_venues.kalshi.position_cache import get_position_cache
                        from merid.risk.global_slot_allocator import get_global_slot_allocator
                        
                        position_cache = get_position_cache()
                        slot_allocator = get_global_slot_allocator()
                        
                        # Get current position count from cache
                        all_positions = position_cache.get_all_positions(validate_freshness=False)
                        open_positions = {k: v for k, v in all_positions.items() if v.contracts > 0}
                        position_count = len(open_positions)
                        
                        logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Current position_count={position_count}")
                        
                        # Clear slots on timeframe transition regardless of position count
                        # New timeframe = fresh start for slot allocation
                        slot_allocator.clear_slots_on_empty_positions(position_count=0)
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Cleared all slots for new timeframe")
                        
                        # CRITICAL FIX (2026-07-15): Reset window exposure on timeframe transition
                        # New timeframe should start with fresh window exposure tracking
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Resetting window exposure tracking")
                        try:
                            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
                            force_reset_window_exposure(reason="timeframe_transition")
                            logger.info("[15m-LOOP] TIMEFRAME-RESET: Window exposure reset complete")
                        except Exception as e:
                            logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to reset window exposure: %s", e, exc_info=True)
                    except Exception as e:
                        logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear slots: %s", e, exc_info=True)
                    
                    # CRITICAL FIX (2026-07-15): Clear position cache on timeframe transition ONLY if no actual positions
                    # This prevents losing track of positions held across timeframe boundaries
                    # Position cache is only cleared if position_count=0 (no actual open positions)
                    if position_count == 0:
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing position cache for new timeframe (position_count=0)")
                        try:
                            from merid.event_venues.kalshi.position_cache import get_position_cache
                            position_cache = get_position_cache()
                            await position_cache.clear()  # Use async clear() for mutex protection
                            logger.info("[15m-LOOP] TIMEFRAME-RESET: Position cache cleared")
                        except Exception as e:
                            logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear position cache: %s", e, exc_info=True)
                    else:
                        logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Skipping position cache clear (position_count={position_count} > 0)")
                    
                    # CRITICAL FIX (2026-07-15): Clear fills ledger open positions on timeframe transition ONLY if no actual positions
                    # This prevents losing track of positions held across timeframe boundaries
                    if position_count == 0:
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing fills ledger open positions for new timeframe (position_count=0)")
                        try:
                            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                            ledger = get_fills_ledger()
                            await ledger.clear_open_positions_on_empty_cache()
                            logger.info("[15m-LOOP] TIMEFRAME-RESET: Fills ledger open positions cleared")
                        except Exception as e:
                            logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear fills ledger: %s", e, exc_info=True)
                    else:
                        logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Skipping fills ledger clear (position_count={position_count} > 0)")
                    
                    # Reset UnifiedRiskManager cycle tracking
                    from merid.risk.unified_risk_manager import get_unified_risk_manager
                    risk_mgr = get_unified_risk_manager()
                    risk_mgr.reset_cycle()
                    logger.info("[15m-LOOP] Reset UnifiedRiskManager cycle for window=%s", current_window.suffix)
                else:
                    logger.debug("[15m-LOOP] Window unchanged: %s - skipping cycle reset", current_window.suffix)
                
                # CRITICAL: Run trading cycle via SINGLE canonical path
                # Call _run_agent_grid_with_timeout which returns candidates
                # This eliminates the dual call problem
                # CRITICAL FIX (2026-08-14): Respect allow_new_entries from loop state.
                allow_new_entries = self._compute_allow_new_entries(cycle_bankroll)
                logger.info("[15m-LOOP] About to call _run_agent_grid_with_timeout tick=%d allow_new_entries=%s", tick_id, allow_new_entries)
                candidates = await self._run_agent_grid_with_timeout(tick_id, trading_ready=allow_new_entries, allow_new_entries=allow_new_entries)
                logger.info("[15m-LOOP] Generated %d candidates in tick %d", len(candidates), tick_id)

                # CRITICAL FIX (2026-08-27): Ingest the canonical rejection breakdown and
                # lifecycle events returned by agent_grid so loop_15m's per-tick counters
                # are derived from a single source of truth, not a parallel drifting dict.
                if isinstance(candidates, CycleResult):
                    total_candidates = candidates.total_generated
                    if candidates.rejection_breakdown:
                        self._rejection_counters.update(candidates.rejection_breakdown)
                        logger.info(
                            "[REJECTION-BREAKDOWN-INGEST] tick=%d total_generated=%d breakdown=%s",
                            tick_id, total_candidates, dict(candidates.rejection_breakdown),
                        )
                    for event in candidates.lifecycle_events:
                        self._log_candidate_lifecycle_event(
                            candidate_id=event.get("candidate_id", "unknown"),
                            from_state=event.get("from_state", "RECEIVED"),
                            to_state=event.get("to_state", "REJECTED"),
                            reason=event.get("reason", "agent_grid"),
                            context={
                                "ticker": event.get("ticker"),
                                "asset": event.get("asset"),
                                "side": event.get("side"),
                                "source": "agent_grid",
                            },
                        )
                else:
                    total_candidates = len(candidates)

                # CRITICAL FIX (2026-07-16): Best-edge selection is now handled in agent_grid_15m._select_best_edge_per_asset
                # This ensures up to 2 contracts per asset per window (cheapest with best edge, capped by $1 exposure) is selected
                # before candidates are passed to the global allocator. The loop_15m execution logic
                # no longer needs to perform duplicate best-edge filtering.
                # agent_grid_15m already filtered to at most 1 candidate per asset.
                
                # CRITICAL: Log candidate details for debugging execution flow
                for i, candidate in enumerate(candidates):
                    logger.info(
                        "[15m-LOOP] Candidate %d: ticker=%s side=%s edge_pct=%.6f",
                        i, candidate.get("ticker"), candidate.get("side"), candidate.get("edge_pct", 0.0)
                    )
                
                # CRITICAL: Handle zero candidates case explicitly
                if len(candidates) == 0:
                    logger.info("[15m-LOOP] No candidates this cycle, skipping execution")
                elif not allow_new_entries:
                    # agent_grid_15m returns filtered candidates for telemetry even when
                    # entries are disabled; the loop must not execute them.
                    logger.info("[15m-LOOP] %d candidates generated but new entries are disabled; skipping execution", len(candidates))
                else:
                    # Execute candidates (already filtered by agent_grid_15m to 1 per asset)
                    logger.info("[15m-LOOP] Starting execution loop for %d candidates (pre-filtered by agent_grid_15m)", len(candidates))
                    for candidate in candidates:
                        try:
                            # CRITICAL FIX: 2026-08-02 - Log candidate lifecycle event for RECEIVED state
                            candidate_id = candidate.get("candidate_id", f"unknown-{int(time.time()*1000)}")
                            self._log_candidate_lifecycle_event(
                                candidate_id=candidate_id,
                                from_state="GENERATED",
                                to_state="RECEIVED",
                                reason="Candidate received from agent_grid_15m",
                                context={"ticker": candidate.get("ticker"), "edge_pct": candidate.get("edge_pct")}
                            )
                            
                            # Extract asset from ticker (e.g., "KXBTC15M-26JUN300345-45" -> "BTC")
                            ticker = candidate.get("ticker", "")
                            logger.info("[15m-LOOP] Processing candidate: ticker=%s candidate_id=%s", ticker, candidate_id)
                            
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
                            
                            # Get candidate edge (single source of truth: edge_pct in FRACTION units)
                            edge = candidate.get("edge_pct", 0.0)
                            side = candidate.get("side", "")
                            logger.info("[15M-LOOP-SIDE-AWARE] Candidate details: edge=%.6f side=%s", edge, side)
                            
                            # Check if we have an open position for this asset
                            current_position = self._asset_positions.get(asset, 0.0)
                            has_position = abs(current_position) > 0.01  # Small threshold for floating point
                            logger.info("[15m-LOOP] Position check: asset=%s position=%.2f has_position=%s", asset, current_position, has_position)
                            
                            # CRITICAL FIX (2026-07-16): Best-edge selection is now handled in agent_grid_15m
                            # The loop_15m no longer needs to track best edge per asset since agent_grid_15m
                            # already ensures only 1 candidate per asset (cheapest with best edge) is returned.
                            # We only need to check for swing mode and edge validation here.
                            
                            # Check swing mode status for this asset
                            swing_enabled = self._swing_mode.get(asset, {}).get("enabled", False)
                            exited_side = self._swing_mode.get(asset, {}).get("exited_side", None)
                            
                            # Determine if this is a swing reversal (opposite side to exited position)
                            is_swing_reversal = swing_enabled and exited_side and side != exited_side
                            
                            # PER-ASSET EDGE THRESHOLD (2026-07-14 FIX)
                            # Use validate_edge() from risk_parameters.py as single source of truth
                            # validate_edge() uses unified 2.5% threshold from profile edge_bands (industry standard)
                            # Previous EDGE_RESTING_ENTRY_* (1.25%-2.75%) were for order aggressiveness (maker vs taker), not trade execution
                            # This fix aligns with profile YAML edge_bands configuration which is the single source of truth
                            # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
                            # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
                            from merid.event_venues.kalshi.risk_parameters import validate_edge
                            
                            # Validate edge using unified 2.5% threshold from profile edge_bands
                            is_valid, reason = validate_edge(edge, asset, confidence=0.5)
                            
                            if not is_valid:
                                logger.debug(
                                    "[15m-LOOP] Edge validation failed: asset=%s edge=%.6f reason=%s",
                                    asset, edge, reason
                                )
                                # CRITICAL FIX: 2026-08-02 - Log lifecycle event for edge validation failure
                                self._log_candidate_lifecycle_event(
                                    candidate_id=candidate_id,
                                    from_state="RECEIVED",
                                    to_state="BLOCKED_EDGE_THRESHOLD",
                                    reason=f"Edge validation failed: {reason}",
                                    context={"asset": asset, "edge": edge}
                                )
                                self._rejection_counters["edge_below_threshold"] += 1
                                continue  # Skip if edge below 2.5%
                            
                            # CRITICAL FIX (2026-07-16): Since agent_grid_15m already filtered to best edge per asset,
                            # we only need to skip if swing mode is disabled and we have a position (no re-entry)
                            # Swing mode allows opposite-side entry after trailing exit
                            if has_position and not is_swing_reversal:
                                logger.debug(
                                    "[15m-LOOP] Asset has position and swing mode not enabled: asset=%s - skipping",
                                    asset
                                )
                                self._rejection_counters["position_exists"] += 1
                                self._log_candidate_lifecycle_event(
                                    candidate_id=candidate_id,
                                    from_state="RECEIVED",
                                    to_state="BLOCKED_POSITION",
                                    reason="Asset has open position and swing mode not enabled",
                                    context={"asset": asset, "ticker": ticker}
                                )
                                continue
                            
                            if is_swing_reversal:
                                logger.info(
                                    "[SWING-MODE] Reversal entry: asset=%s from %s to %s edge=%.2f%% - swing mode enabled",
                                    asset, exited_side, side, edge
                                )
                                # Disable swing mode after executing reversal
                                self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
                                logger.info("[SWING-MODE] Disabled for asset=%s after reversal entry", asset)
                            
                            # CRITICAL FIX (2026-08-05): Removed the ticker+side+price dedup here.
                            # It silently dropped candidates without lifecycle/counter updates, causing
                            # the per-tick invariant "candidates=N terminal=0" mismatch. The per-asset-window
                            # duplicate check below already handles the same window re-entry semantics and
                            # properly logs a BLOCKED_DUPLICATE terminal state.
                            
                            # CRITICAL FIX (2026-07-21): Check if asset already has position or pending order in current 15-minute window
                            # This enforces one-contract-per-asset-per-15-minute rule at execution time, not just signal time
                            # The key is asset + window (ticker prefix + 15-minute window ID), not just ticker+side+price
                            # CRITICAL FIX (2026-07-21): Use same source of truth as router (position_cache + resting_order_monitor)
                            # to ensure loop and router don't diverge on window state
                            asset_window_key = self._get_asset_window_key(candidate)
                            
                            # RESEARCH-ALIGNED: Exposure-aware re-entry logic instead of binary block
                            # Allow re-entry if: (1) current exposure < cap, OR (2) new edge > prior edge + delta
                            # This captures late-window edge formation instead of blocking all re-entries
                            # CRITICAL FIX (2026-07-29): Check if prior candidate is stale (pending order timeout)
                            # If global allocator cleared a stale pending order, loop_15m should also allow re-entry
                            # CRITICAL FIX (2026-07-30): Check thesis compatibility before allowing edge improvement re-entry
                            # Prevent same-side duplicate positions by checking existing position thesis_side
                            prior_candidate = self._executed_candidates_this_window.get(asset_window_key)
                            if prior_candidate:
                                prior_edge = prior_candidate.get("edge_pct", 0) / 100.0
                                current_edge = candidate.get("edge_pct", 0) / 100.0
                                edge_improvement_delta = 0.005  # 0.5% improvement required for re-entry
                                pending_order_timeout = 30.0  # Match global allocator timeout
                                
                                # CRITICAL FIX (2026-07-30): Check thesis compatibility with existing position
                                # Get current candidate side
                                current_side = candidate.get("side", "").lower()
                                
                                # Check position cache for existing position in this window
                                thesis_compatible = True
                                try:
                                    from merid.event_venues.kalshi.position_cache import get_position_cache
                                    position_cache = get_position_cache()
                                    if position_cache:
                                        all_positions = position_cache.get_all_positions(validate_freshness=False)
                                        for pos_ticker, pos_obj in all_positions.items():
                                            if pos_obj and pos_obj.contracts > 0:
                                                if asset in pos_ticker.upper() and window_id in pos_ticker:
                                                    # Found position in same asset-window
                                                    existing_thesis_side = getattr(pos_obj, 'thesis_side', None)
                                                    if existing_thesis_side and current_side:
                                                        if current_side == existing_thesis_side.lower():
                                                            # SAME SIDE - Block re-entry even with edge improvement
                                                            thesis_compatible = False
                                                            logger.warning(
                                                                "[15m-LOOP] Edge improvement blocked by thesis check: asset=%s ticker=%s "
                                                                "existing_thesis=%s new_thesis=%s - same-side position exists",
                                                                asset, ticker, existing_thesis_side, current_side
                                                            )
                                                            break
                                                        else:
                                                            # OPPOSITE SIDE - Allow hedging
                                                            logger.info(
                                                                "[15m-LOOP] Edge improvement allowed for hedging: asset=%s ticker=%s "
                                                                "existing_thesis=%s new_thesis=%s",
                                                                asset, ticker, existing_thesis_side, current_side
                                                            )
                                except Exception as thesis_check_err:
                                    logger.warning("[15m-LOOP] Failed to check thesis compatibility: %s", thesis_check_err)
                                
                                # Check if prior candidate is stale (older than pending order timeout)
                                prior_timestamp = prior_candidate.get("timestamp", 0)
                                if prior_timestamp > 0:
                                    time_since_prior = time.time() - prior_timestamp
                                    if time_since_prior >= pending_order_timeout:
                                        logger.info(
                                            "[15m-LOOP] Stale prior candidate cleared: asset=%s ticker=%s age=%.1fs - ALLOWING re-entry",
                                            asset, ticker, time_since_prior
                                        )
                                        # Clear stale prior candidate and allow new order
                                        del self._executed_candidates_this_window[asset_window_key]
                                    elif current_edge > prior_edge + edge_improvement_delta and thesis_compatible:
                                        logger.info(
                                            "[15m-LOOP] Edge improvement re-entry: asset=%s ticker=%s prior_edge=%.4f current_edge=%.4f improvement=%.4f - ALLOWING",
                                            asset, ticker, prior_edge, current_edge, current_edge - prior_edge
                                        )
                                        # CRITICAL FIX (2026-07-31): Cancel prior order before allowing edge improvement re-entry
                                        # This prevents multiple contracts per asset when edge improvement is triggered
                                        # Without this, both the prior order and new order can execute, violating risk limits
                                        # CRITICAL FIX (2026-08-09): Do not attempt to cancel a prior order that has already
                                        # filled; doing so causes 404 errors and can trip the event-loop circuit breaker.
                                        if prior_candidate.get("has_execution") or prior_candidate.get("status") in ("filled_live", "partially_filled"):
                                            self._rejection_counters["duplicate_order"] += 1
                                            self._log_candidate_lifecycle_event(
                                                candidate_id=candidate_id,
                                                from_state="RECEIVED",
                                                to_state="BLOCKED_DUPLICATE",
                                                reason="Edge improvement re-entry blocked - prior order already filled/executed",
                                                context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge, "prior_status": prior_candidate.get("status")}
                                            )
                                            logger.warning(
                                                "[15m-LOOP] Edge improvement blocked: prior order for %s already %s - treating as same-side position",
                                                ticker, prior_candidate.get("status") or "filled"
                                            )
                                            continue

                                        prior_order_canceled = False
                                        try:
                                            from merid.event_venues.kalshi.order_manager import get_order_manager
                                            order_manager = get_order_manager()
                                            if order_manager:
                                                # Get prior order ID from candidate metadata
                                                prior_order_id = prior_candidate.get("order_id")
                                                if prior_order_id:
                                                    # Track the externally-placed order so the manager can cancel it
                                                    order_manager.track_order(prior_order_id)
                                                    cancel_success = await order_manager.cancel_order(prior_order_id)
                                                    if cancel_success:
                                                        logger.info(
                                                            "[15m-LOOP] Edge improvement: Successfully canceled prior order %s for asset=%s ticker=%s",
                                                            prior_order_id, asset, ticker
                                                        )
                                                        prior_order_canceled = True
                                                    else:
                                                        logger.warning(
                                                            "[15m-LOOP] Edge improvement: Failed to cancel prior order %s for asset=%s ticker=%s - BLOCKING re-entry",
                                                            prior_order_id, asset, ticker
                                                        )
                                                else:
                                                    logger.warning(
                                                        "[15m-LOOP] Edge improvement: Prior candidate missing order_id for asset=%s ticker=%s - BLOCKING re-entry",
                                                        asset, ticker
                                                    )
                                        except Exception as cancel_err:
                                            logger.error(
                                                "[15m-LOOP] Edge improvement: Failed to cancel prior order for asset=%s ticker=%s: %s - BLOCKING re-entry",
                                                asset, ticker, cancel_err
                                            )
                                        
                                        # Only allow re-entry if prior order was successfully canceled
                                        if prior_order_canceled:
                                            # Update tracked candidate to new higher-edge version
                                            self._executed_candidates_this_window[asset_window_key] = candidate
                                        else:
                                            self._rejection_counters["edge_improvement_cancel_failed"] += 1
                                            self._log_candidate_lifecycle_event(
                                                candidate_id=candidate_id,
                                                from_state="RECEIVED",
                                                to_state="BLOCKED_DUPLICATE",
                                                reason="Edge improvement re-entry failed to cancel prior order",
                                                context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge}
                                            )
                                            logger.warning(
                                                "[15m-LOOP] Edge improvement blocked: asset=%s ticker=%s - prior order not canceled, blocking re-entry",
                                                asset, ticker
                                            )
                                            continue
                                    else:
                                        self._rejection_counters["duplicate_order"] += 1
                                        # CRITICAL FIX: 2026-08-02 - Log lifecycle event for duplicate rejection
                                        self._log_candidate_lifecycle_event(
                                            candidate_id=candidate_id,
                                            from_state="RECEIVED",
                                            to_state="BLOCKED_DUPLICATE",
                                            reason="Duplicate order in current window",
                                            context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge}
                                        )
                                        if not thesis_compatible:
                                            logger.warning(
                                                "[15m-LOOP] Asset already has same-side position: asset=%s ticker=%s - skipping (thesis check)",
                                                asset, ticker
                                            )
                                        else:
                                            logger.warning(
                                                "[15m-LOOP] Asset already has order in current window: asset=%s ticker=%s prior_edge=%.4f current_edge=%.4f - skipping (no material improvement)",
                                                asset, ticker, prior_edge, current_edge
                                            )
                                        continue
                                elif current_edge > prior_edge + edge_improvement_delta and thesis_compatible:
                                    logger.info(
                                        "[15m-LOOP] Edge improvement re-entry: asset=%s ticker=%s prior_edge=%.4f current_edge=%.4f improvement=%.4f - ALLOWING",
                                        asset, ticker, prior_edge, current_edge, current_edge - prior_edge
                                    )
                                    # CRITICAL FIX (2026-07-31): Cancel prior order before allowing edge improvement re-entry
                                    # This prevents multiple contracts per asset when edge improvement is triggered
                                    # Without this, both the prior order and new order can execute, violating risk limits
                                    # CRITICAL FIX (2026-08-09): Do not attempt to cancel a prior order that has already
                                    # filled; doing so causes 404 errors and can trip the event-loop circuit breaker.
                                    if prior_candidate.get("has_execution") or prior_candidate.get("status") in ("filled_live", "partially_filled"):
                                        self._rejection_counters["duplicate_order"] += 1
                                        self._log_candidate_lifecycle_event(
                                            candidate_id=candidate_id,
                                            from_state="RECEIVED",
                                            to_state="BLOCKED_DUPLICATE",
                                            reason="Edge improvement re-entry blocked - prior order already filled/executed",
                                            context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge, "prior_status": prior_candidate.get("status")}
                                        )
                                        logger.warning(
                                            "[15m-LOOP] Edge improvement blocked: prior order for %s already %s - treating as same-side position",
                                            ticker, prior_candidate.get("status") or "filled"
                                        )
                                        continue

                                    prior_order_canceled = False
                                    try:
                                        from merid.event_venues.kalshi.order_manager import get_order_manager
                                        order_manager = get_order_manager()
                                        if order_manager:
                                            # Get prior order ID from candidate metadata
                                            prior_order_id = prior_candidate.get("order_id")
                                            if prior_order_id:
                                                # Track the externally-placed order so the manager can cancel it
                                                order_manager.track_order(prior_order_id)
                                                cancel_success = await order_manager.cancel_order(prior_order_id)
                                                if cancel_success:
                                                    logger.info(
                                                        "[15m-LOOP] Edge improvement: Successfully canceled prior order %s for asset=%s ticker=%s",
                                                        prior_order_id, asset, ticker
                                                    )
                                                    prior_order_canceled = True
                                                else:
                                                    logger.warning(
                                                        "[15m-LOOP] Edge improvement: Failed to cancel prior order %s for asset=%s ticker=%s - BLOCKING re-entry",
                                                        prior_order_id, asset, ticker
                                                    )
                                            else:
                                                logger.warning(
                                                    "[15m-LOOP] Edge improvement: Prior candidate missing order_id for asset=%s ticker=%s - BLOCKING re-entry",
                                                    asset, ticker
                                                )
                                    except Exception as cancel_err:
                                        logger.error(
                                            "[15m-LOOP] Edge improvement: Failed to cancel prior order for asset=%s ticker=%s: %s - BLOCKING re-entry",
                                            asset, ticker, cancel_err
                                        )
                                    
                                    # Only allow re-entry if prior order was successfully canceled
                                    if prior_order_canceled:
                                        # Update tracked candidate to new higher-edge version
                                        self._executed_candidates_this_window[asset_window_key] = candidate
                                    else:
                                        self._rejection_counters["edge_improvement_cancel_failed"] += 1
                                        self._log_candidate_lifecycle_event(
                                            candidate_id=candidate_id,
                                            from_state="RECEIVED",
                                            to_state="BLOCKED_DUPLICATE",
                                            reason="Edge improvement re-entry failed to cancel prior order",
                                            context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge}
                                        )
                                        logger.warning(
                                            "[15m-LOOP] Edge improvement blocked: asset=%s ticker=%s - prior order not canceled, blocking re-entry",
                                            asset, ticker
                                        )
                                        continue
                                else:
                                    self._rejection_counters["duplicate_order"] += 1
                                    # CRITICAL FIX: 2026-08-02 - Log lifecycle event for duplicate rejection
                                    self._log_candidate_lifecycle_event(
                                        candidate_id=candidate_id,
                                        from_state="RECEIVED",
                                        to_state="BLOCKED_DUPLICATE",
                                        reason="Duplicate order in current window",
                                        context={"asset": asset, "ticker": ticker, "prior_edge": prior_edge, "current_edge": current_edge}
                                    )
                                    if not thesis_compatible:
                                        logger.warning(
                                            "[15m-LOOP] Asset already has same-side position: asset=%s ticker=%s - skipping (thesis check)",
                                            asset, ticker
                                        )
                                    else:
                                        logger.warning(
                                            "[15m-LOOP] Asset already has order in current window: asset=%s ticker=%s prior_edge=%.4f current_edge=%.4f - skipping (no material improvement)",
                                            asset, ticker, prior_edge, current_edge
                                        )
                                    continue
                            
                            # Check position cache for existing positions in this window (same as router)
                            try:
                                from merid.event_venues.kalshi.position_cache import get_position_cache
                                position_cache = get_position_cache()
                                if position_cache:
                                    all_positions = position_cache.get_all_positions(validate_freshness=False)
                                    for pos_ticker, pos_obj in all_positions.items():
                                        if pos_obj and pos_obj.contracts > 0:
                                            # Extract asset and window from position ticker
                                            pos_asset = None
                                            pos_ticker_upper = pos_ticker.upper()
                                            if "BTC" in pos_ticker_upper:
                                                pos_asset = "BTC"
                                            elif "ETH" in pos_ticker_upper:
                                                pos_asset = "ETH"
                                            elif "SOL" in pos_ticker_upper:
                                                pos_asset = "SOL"
                                            elif "XRP" in pos_ticker_upper:
                                                pos_asset = "XRP"
                                            elif "DOGE" in pos_ticker_upper:
                                                pos_asset = "DOGE"
                                            
                                            if pos_asset == asset:
                                                pos_window_id = pos_ticker.split("-")[-2] if "-" in pos_ticker else pos_ticker
                                                if pos_window_id == ticker.split("-")[-2] if "-" in ticker else ticker:
                                                    # CRITICAL FIX (2026-07-30): Side-aware check using thesis_side
                                                    # This check is now redundant with the earlier thesis check in edge improvement logic
                                                    # but kept as a safety net. The earlier check already blocks same-side duplicates.
                                                    # This is a legacy check that should be removed in future cleanup.
                                                    self._rejection_counters["position_exists"] += 1
                                                    # CRITICAL FIX: 2026-08-02 - Log lifecycle event for position exists rejection
                                                    self._log_candidate_lifecycle_event(
                                                        candidate_id=candidate_id,
                                                        from_state="RECEIVED",
                                                        to_state="BLOCKED_POSITION",
                                                        reason="Position already exists in current window",
                                                        context={"asset": asset, "ticker": ticker, "pos_ticker": pos_ticker}
                                                    )
                                                    logger.warning(
                                                        "[15m-LOOP] Asset already has position in current window: asset=%s window=%s position=%s (contracts=%d) - skipping (legacy check, superseded by thesis check)",
                                                        asset, pos_window_id, pos_ticker, pos_obj.contracts
                                                    )
                                                    continue
                            except Exception as pos_check_err:
                                logger.warning("[15m-LOOP] Failed to check position cache for asset-window state: %s", pos_check_err)
                            
                            # Check resting order monitor for pending orders in this window (same as router)
                            try:
                                from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
                                from merid.event_venues.kalshi.binary_price_space import to_kalshi_side
                                monitor = get_resting_order_monitor()
                                if monitor:
                                    # CRITICAL FIX: Convert candidate side/action to Kalshi format for duplicate detection
                                    # Resting order monitor stores Kalshi-formatted sides (BUY_YES, BUY_NO, etc.)
                                    # but candidates use lowercase sides (yes, no) and actions (buy, sell)
                                    candidate_side = str(candidate.get("side", "")).lower()
                                    candidate_action = str(candidate.get("action", "")).lower()
                                    try:
                                        kalshi_side = to_kalshi_side(candidate_side, candidate_action)
                                    except ValueError:
                                        # If conversion fails, use lowercase format as fallback
                                        kalshi_side = candidate_side
                                    
                                    open_order_id = monitor.find_open_order(
                                        ticker=ticker,
                                        side=kalshi_side,
                                        action=candidate_action
                                    )
                                    if open_order_id:
                                        self._rejection_counters["resting_order_exists"] += 1
                                        # CRITICAL FIX: 2026-08-02 - Log lifecycle event for resting order rejection
                                        self._log_candidate_lifecycle_event(
                                            candidate_id=candidate_id,
                                            from_state="RECEIVED",
                                            to_state="BLOCKED_RESTING_ORDER",
                                            reason="Resting order already exists in current window",
                                            context={"asset": asset, "ticker": ticker, "open_order_id": open_order_id}
                                        )
                                        logger.warning(
                                            "[15m-LOOP] Asset has resting order in current window: asset=%s ticker=%s order=%s - skipping",
                                            asset, ticker, open_order_id
                                        )
                                        continue
                            except Exception as monitor_err:
                                logger.warning("[15m-LOOP] Failed to check resting order monitor: %s", monitor_err)
                            
                            # CRITICAL: Re-validate edge before execution
                            if not self._validate_candidate_edge(candidate):
                                self._rejection_counters["edge_validation_failed"] += 1
                                logger.warning("[15m-LOOP] Candidate edge validation failed: %s - skipping execution", ticker)
                                continue
                            
                            # Use dynamic position sizing if enabled
                            try:
                                from merid.prediction.unified_sizing import compute_order_size
                                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_async
                                from decimal import Decimal
                                
                                # Async cache-only read; never blocks the event loop on a balance fetch.
                                bankroll_usd = await get_equity_for_risk_calc_async()
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
                                            candidate_side = str(candidate.get("side", "")).lower()
                                            # CRITICAL FIX: If side is missing, log error and skip - don't default to "yes"
                                            if not candidate_side:
                                                logger.error("[15m-LOOP] CRITICAL: candidate missing 'side' field for ticker=%s - CANNOT DETERMINE PRICE - SKIPPING", ticker)
                                                continue
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
                                        "[15m-LOOP] No real price available for sizing ticker=%s - using conservative 42c placeholder (midpoint of 10-75c canonical range)",
                                        ticker
                                    )
                                    price_cents = 42  # 2026-07-14: Fixed to 42c (midpoint of 10-75c canonical range)
                                
                                # Get edge, confidence, and model_prob from candidate
                                edge_pct = Decimal(str(candidate.get("edge_pct", 0.0)))
                                confidence = Decimal(str(candidate.get("confidence", 0.5)))
                                model_prob = candidate.get("model_prob", None)  # 2026-07-12: Kelly Criterion integration
                                candidate_side = str(candidate.get("side", "")).lower()  # 2026-07-13: Side for Kelly calculation
                                # CRITICAL FIX: If side is missing, log error and skip
                                if not candidate_side:
                                    logger.error("[15m-LOOP] CRITICAL: candidate missing 'side' field for ticker=%s - CANNOT CALCULATE KELLY - SKIPPING", ticker)
                                    continue
                                
                                # Extract canonical asset from ticker
                                asset = extract_asset(ticker)
                                
                                # Compute dynamic size
                                # 2026 Research-Based Risk Management: Apply time-of-day risk scaling
                                # 2026-07-12: Kelly Criterion integration - pass model_prob for edge filtering
                                # 2026-07-13: Pass side for correct Kelly calculation
                                # 2026-08-11: Enable fee-aware Kelly so signal EV and sizing agree.
                                time_of_day_multiplier = candidate.get("time_of_day_multiplier", 1.0)
                                _fee_cents = candidate.get("fee_cents")
                                _tte_seconds = candidate.get("time_to_expiry_seconds")
                                count, notional, metadata = compute_order_size(
                                    bankroll_usd=Decimal(str(bankroll_usd)),
                                    price_cents=int(price_cents),
                                    asset=asset,
                                    edge_pct=edge_pct,
                                    confidence=confidence,
                                    time_of_day_multiplier=time_of_day_multiplier,
                                    consider_fee_impact=True,
                                    estimated_fee_cents=int(_fee_cents) if _fee_cents is not None else None,
                                    tte_seconds=_tte_seconds,
                                    model_prob=model_prob,  # 2026-07-12: Kelly Criterion
                                    side=candidate_side  # 2026-07-13: Pass side for Kelly
                                )
                                
                                candidate["count"] = count

                                # FVG-influenced trades are scaled by MERID_FVG_SIZE_SCALE (default 0.5)
                                # to reduce live exposure while the placebo matrix is being collected.
                                fvg_size_scale = float(candidate.get("fvg_size_scale", 1.0) or 1.0)
                                if fvg_size_scale < 1.0 and fvg_size_scale > 0.0 and count > 0:
                                    scaled_count = max(1, int(count * fvg_size_scale))
                                    if scaled_count != count:
                                        logger.info(
                                            "[15M-LOOP-FVG-SIZE] ticker=%s original_count=%d scaled_count=%d fvg_size_scale=%.2f",
                                            ticker, count, scaled_count, fvg_size_scale,
                                        )
                                        candidate["count"] = scaled_count
                                
                                # CRITICAL FIX: Skip execution if sizing returned count=0
                                # This prevents invalid orders from being submitted
                                if count == 0:
                                    sizing_reason = metadata.get("reason", metadata.get("rejection_reason", "unknown"))
                                    logger.warning(
                                        "[15m-LOOP] Sizing returned count=0 for ticker=%s (notional=%.2f, rejection_reason=%s) - skipping execution",
                                        ticker, float(notional), sizing_reason
                                    )
                                    # CRITICAL FIX: Increment rejection counter for sizing failures
                                    # This prevents counter sanity mismatch warnings
                                    self._rejection_counters["other"] += 1
                                    self._log_candidate_lifecycle_event(
                                        candidate_id=candidate_id,
                                        from_state="RECEIVED",
                                        to_state="REJECTED",
                                        reason=f"Sizing returned count=0: {sizing_reason}",
                                        context={"asset": asset, "ticker": ticker, "notional": float(notional), "sizing_reason": sizing_reason}
                                    )
                                    continue
                                
                                logger.info(
                                    "[15m-LOOP] Dynamic sizing: ticker=%s edge=%.4f confidence=%.4f count=%d notional=%.2f",
                                    ticker, float(edge_pct), float(confidence), count, float(notional)
                                )
                                
                                # CRITICAL FIX (2026-08-01): DISABLE LiquidityAwareSizer for 15m crypto agents
                                # The $1 global rule enforces a shared exposure cap, but LiquidityAwareSizer
                                # can increase count based on market depth, violating the $1 cap.
                                # For 15m crypto agents with fixed $1 exposure, liquidity-aware sizing is incompatible.
                                # The slot allocator already enforces position limits based on available capital.
                                # Skip liquidity-aware sizing; unified_sizing determines count (1 or 2) within the $1 cap.
                                logger.debug(
                                    "[15m-LOOP] Liquidity-aware sizing DISABLED for $1 global rule enforcement: ticker=%s count=%d (up to %d contracts per trade)",
                                    ticker, count, MAX_CONTRACTS_PER_ORDER
                                )
                            except Exception as sizing_err:
                                logger.warning("[15m-LOOP] Dynamic sizing failed, using default count=1: %s", sizing_err)
                                candidate["count"] = 1
                            
                            # Execute candidate and check if order was actually submitted
                            order_submitted = await self._execute_candidate(candidate, tick_id)

                            # Only track as executed if order was actually submitted
                            if order_submitted:
                                # CRITICAL FIX: 2026-08-02 - Log lifecycle event for EXECUTED state
                                self._log_candidate_lifecycle_event(
                                    candidate_id=candidate_id,
                                    from_state="RECEIVED",
                                    to_state="EXECUTED",
                                    reason="Order submitted successfully",
                                    context={"ticker": ticker, "order_id": candidate.get("order_id")}
                                )
                                
                                # CRITICAL FIX (2026-07-29): Add timestamp to candidate for stale order detection
                                # This allows loop_15m to clear stale candidates like global_allocator does
                                candidate_with_timestamp = candidate.copy()
                                candidate_with_timestamp["timestamp"] = time.time()
                                
                                # CRITICAL FIX (2026-07-31): Preserve order_id from candidate after execution
                                # The order_id is set in _execute_candidate and must be preserved for edge improvement cancellation
                                if "order_id" in candidate:
                                    candidate_with_timestamp["order_id"] = candidate["order_id"]
                                    logger.info("[15M-LOOP] Preserved order_id=%s in stored candidate for ticker=%s", candidate["order_id"], ticker)
                                
                                # Track executed candidate to prevent duplicates
                                candidate_key = self._get_candidate_key(candidate)
                                self._executed_candidates_this_window[candidate_key] = candidate_with_timestamp
                                
                                # CRITICAL FIX (2026-07-21): Track asset-window key to enforce one-contract-per-asset rule
                                asset_window_key = self._get_asset_window_key(candidate)
                                self._executed_candidates_this_window[asset_window_key] = candidate_with_timestamp
                                
                                # Increment per-tick execution counter for sanity checks
                                self._tick_executed_count += 1
                            else:
                                # CRITICAL FIX: 2026-08-02 - Log lifecycle event for REJECTED state
                                # CRITICAL FIX 2026-08-04: Avoid double-logging a terminal state.
                                # _execute_candidate may already have logged a terminal state (e.g. BLOCKED_EDGE_THRESHOLD,
                                # BLOCKED_PARITY). If so, do NOT log REJECTED again; that creates a lifecycle mismatch
                                # where one candidate produces two terminal events.
                                terminal_states = {"EXECUTED", "REJECTED", "BLOCKED_PARITY", "BLOCKED_EDGE_THRESHOLD", "BLOCKED_DUPLICATE", "BLOCKED_POSITION", "BLOCKED_RESTING_ORDER"}
                                current_state = self._candidate_lifecycle_states.get(candidate_id, "RECEIVED")
                                if current_state not in terminal_states:
                                    self._log_candidate_lifecycle_event(
                                        candidate_id=candidate_id,
                                        from_state="RECEIVED",
                                        to_state="REJECTED",
                                        reason="Order submission failed or blocked",
                                        context={"ticker": ticker}
                                    )
                                else:
                                    logger.info(
                                        "[15M-LOOP] Candidate %s already has terminal state %s; skipping duplicate REJECTED lifecycle event",
                                        candidate_id, current_state
                                    )
                                
                                # CRITICAL FIX (2026-07-31): Do NOT increment "other" counter here
                                # The rejection is already counted in the specific category (router_rejected, etc.)
                                # in _execute_candidate. Counting it again causes counter sanity mismatch.
                                logger.warning(
                                    "[15m-LOOP] Order not submitted for ticker=%s (order_submitted=False) - rejection already counted in specific category",
                                    ticker
                                )
                            
                            # FIX: Do NOT reset cycle guards after each execution
                            # The global_slot_allocator should track total exposure across all positions
                            # to enforce the fixed $1 exposure cap. Resetting after each trade defeats this.
                            # Cycle reset only happens at the start of a new 15-minute window (line 1366)
                            
                            # CRITICAL FIX: Do NOT clear deduplication cache after each execution
                            # The cache should only be cleared at the start of a new 15-minute window (line 1346)
                            # Clearing it here allows the same order to be placed every 5 seconds, causing agents
                            # to exceed risk limits. The order gate and slot-based risk checks should handle
                            # allowing new orders when conditions change (different price, side, etc.)
                        except Exception as e:
                            logger.error("[15m-LOOP] Failed to execute candidate: %s", e, exc_info=True)
                            self._rejection_counters["other"] += 1
                            self._log_candidate_lifecycle_event(
                                candidate_id=candidate_id,
                                from_state="RECEIVED",
                                to_state="REJECTED",
                                reason=f"Execution exception: {e}",
                                context={"asset": asset, "ticker": ticker, "error": str(e)}
                            )
                
                # COUNTER SANITY CHECK: Verify candidate → order flow consistency
                # Use per-tick counters to avoid cumulative mismatch.
                # CRITICAL FIX (2026-08-27): total_candidates comes from the agent_grid
                # CycleResult (total_generated) so pre-loop rejections (ENTRIES_DISABLED,
                # allocator loss, allocator error) are included in the invariant.
                tick_rejections = sum(self._rejection_counters.values())
                tick_executed = self._tick_executed_count  # Use per-tick counter, not window-accumulated

                # CRITICAL FIX: 2026-08-02 - Verify against lifecycle event log for single source of truth
                # Count terminal states from event log for THIS TICK ONLY (tick-scoped reconciliation)
                terminal_states = {"EXECUTED", "REJECTED", "BLOCKED_PARITY", "BLOCKED_EDGE_THRESHOLD", "BLOCKED_DUPLICATE", "BLOCKED_POSITION", "BLOCKED_RESTING_ORDER"}
                lifecycle_terminal_count = 0
                lifecycle_breakdown = {}
                for event in self._candidate_event_log:
                    # CRITICAL FIX: Filter by tick_id to prevent accumulation across ticks
                    if event.get("tick_id") == tick_id and event.get("to_state") in terminal_states:
                        lifecycle_terminal_count += 1
                        state = event.get("to_state")
                        lifecycle_breakdown[state] = lifecycle_breakdown.get(state, 0) + 1

                logger.info(
                    "[COUNTER-SANITY-CHECK] tick=%d total_candidates=%d total_executed=%d total_rejections=%d "
                    "rejection_breakdown=%s lifecycle_terminal=%d lifecycle_breakdown=%s",
                    tick_id, total_candidates, tick_executed, tick_rejections, dict(self._rejection_counters),
                    lifecycle_terminal_count, lifecycle_breakdown
                )
                # LOG CONTRACT: Ensure no silent candidate loss (per-tick check)
                # Note: All counters are now per-tick (reset each tick)
                # 2026-08-27: Log as CRITICAL but do not raise. The invariant is a
                # release-gate signal, not a process-killer; a mismatch must be
                # visible and audited without aborting the tick (which would skip
                # the per-tick counter reset and let counters drift).
                if total_candidates != tick_executed + tick_rejections:
                    logger.critical(
                        "[COUNTER-INVARIANT-VIOLATION] tick=%d total_generated=%d != executed=%d + rejections=%d",
                        tick_id, total_candidates, tick_executed, tick_rejections,
                    )
                    self._error_count += 1
                # CRITICAL FIX: 2026-08-02 - Verify lifecycle log consistency
                if total_candidates != lifecycle_terminal_count:
                    logger.critical(
                        "[LIFECYCLE-INVARIANT-VIOLATION] tick=%d total_generated=%d != terminal_events=%d",
                        tick_id, total_candidates, lifecycle_terminal_count,
                    )
                    self._error_count += 1
                # Reset rejection counters for next tick to prevent accumulation
                for key in self._rejection_counters:
                    self._rejection_counters[key] = 0
                
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
                        logger.info("[15m-LOOP] Generated %d hedge intents, routing to execution", len(hedge_intents))
                        
                        # Route hedge orders
                        for hedge_intent in hedge_intents:
                            # CRITICAL FIX (2026-07-29): Hedge rejection retry logic
                            # Retry up to 3 times with 1s delay to handle transient rejections
                            max_retries = 3
                            result = None
                            for attempt in range(max_retries):
                                try:
                                    result = await route_order_async(hedge_intent)
                                    if result and (result.has_execution or (result.request_completed and not result.is_terminal)):
                                        logger.info(
                                            "[15m-LOOP] Hedge order routed successfully: ticker=%s side=%s count=%d status=%s attempt=%d",
                                            hedge_intent.ticker, hedge_intent.side, hedge_intent.count, result.status, attempt + 1
                                        )
                                        break
                                    else:
                                        _hedge_status = result.status if result else "none"
                                        _hedge_reason = result.reason or "unknown" if result else "unknown"
                                        logger.warning(
                                            "[15m-LOOP] Hedge order rejected (attempt %d/%d): ticker=%s side=%s count=%d status=%s reason=%s",
                                            attempt + 1, max_retries, hedge_intent.ticker, hedge_intent.side, hedge_intent.count, _hedge_status, _hedge_reason
                                        )
                                        if attempt < max_retries - 1:
                                            await asyncio.sleep(1)  # Wait 1s before retry
                                except Exception as hedge_err:
                                    logger.error(
                                        "[15m-LOOP] Failed to route hedge order (attempt %d/%d): %s",
                                        attempt + 1, max_retries, hedge_err, exc_info=True
                                    )
                                    if attempt < max_retries - 1:
                                        await asyncio.sleep(1)  # Wait 1s before retry
                            
                            if result and not (result.has_execution or (result.request_completed and not result.is_terminal)):
                                logger.error(
                                    "[15m-LOOP] Hedge order failed after %d retries: ticker=%s side=%s count=%d - alpha remains unhedged",
                                    max_retries, hedge_intent.ticker, hedge_intent.side, hedge_intent.count
                                )
                    else:
                        logger.debug("[15m-LOOP] No hedge orders needed (exposure within bounds)")
                except Exception as hedge_exc:
                    logger.warning("[15m-LOOP] Hedge pass failed (non-fatal): %s", hedge_exc, exc_info=True)
                
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
    # Stop the loop gracefully.
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
    # Run a single trading cycle.
    # Steps:
    # 1) Reset UnifiedRiskManager cycle tracking (critical for cycle cap enforcement)
    # 2) Update envelope equity once per cycle (not per order)
    # 3) Check if halted due to drawdown
    # 4) Skip cycle if halted
    # 5) Pull latest market state / RTI inputs (rely on WS caches)
    # 6) Call agent_grid.run_cycle(tick) to step all agents
    # 7) Let AgentGrid/TradingAgent issue orders via route_order_async
    # 8) Log band transitions
    # Phase 4.2: Enhanced with performance profiling
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
                        
                        
                        if self._ws_bridge and catalog_snapshot:
                            # Extract current 15m market tickers from catalog (one per asset)
                            initial_tickers = []
                            for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                                current = catalog_snapshot.get_current_15m_market(asset)
                                if current:
                                    initial_tickers.append(current.market.market_id)

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
                    if self._ws_bridge and catalog_snapshot:
                        # Extract current 15m market tickers from catalog (one per asset)
                        initial_tickers = []
                        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            current = catalog_snapshot.get_current_15m_market(asset)
                            if current:
                                initial_tickers.append(current.market.market_id)

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
                
                # CRITICAL FIX: 2026-07-16 - REMOVED warmup grace period for catalog freshness
                # Previous logic allowed trading during catalog initialization by forcing catalog_fresh=True
                # This bypassed proper health checks and allowed orders with insufficient data
                # Now catalog must pass freshness check naturally - no warmup bypass
                # if in_warmup:
                #     catalog_fresh = True  # Warmup grace: allow trading during catalog initialization
                if not catalog_fresh:
                    catalog_stale_reasons.append(f"catalog_age({catalog_age_s:.1f}s)")
                
                # Detect catalog roll (market IDs changed) for WS warmup grace period
                current_market_ids = set()
                if catalog_snapshot:
                    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        current = catalog_snapshot.get_current_15m_market(asset)
                        if current:
                            current_market_ids.add(current.market.market_id)

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
                    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        current = catalog_snapshot.get_current_15m_market(asset)
                        if not current:
                            continue
                        market_id = current.market.market_id
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
            
            # CRITICAL FIX: 2026-07-16 - REMOVED FINAL OVERRIDE warmup bypass
            # Previous logic forced catalog_fresh=True during warmup regardless of staleness
            # This bypassed all health checks and allowed orders with insufficient data
            # Now catalog must pass freshness check naturally - no warmup bypass
            # if in_warmup:
            #     catalog_fresh = True
            #     logger.info(
            #         "[CATALOG-WARMUP-OVERRIDE] Forcing catalog_fresh=True during warmup (%.1fs/%.1fs)",
            #         time_since_roll, self._catalog_warmup_seconds
            #     )
                
            
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
                        # CRITICAL FIX: 2026-07-16 - REMOVED warmup grace period for MD freshness
                        # Previous logic allowed trading during MD initialization by forcing asset_md_fresh=True
                        # This bypassed proper health checks and allowed orders with insufficient data
                        # Now MD must pass freshness check naturally - no warmup bypass
                        # if in_warmup:
                        #     asset_md_fresh = True  # Warmup grace: allow trading during MD initialization
                        # else:
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
                        min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 1)  # FIXED: Default 1 to match YAML (was 25)
                        min_depth_no_threshold = depth_thresholds.get('min_depth_no', 1)  # FIXED: Default 1 to match YAML (was 25)
                        
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
                        
                        # YES/NO ARBITRAGE CHECK: Check for arbitrage opportunities in this market
                        if state and asset_depth_ok:
                            try:
                                from merid.event_venues.kalshi.duality_validator import check_yes_no_duality
                                duality_result = check_yes_no_duality(
                                    yes_bid=state.best_bid_cents if state.has_bid else None,
                                    no_bid=state.best_no_bid_cents if state.has_no_bid else None,
                                    yes_ask=state.best_ask_cents if state.has_ask else None,
                                    no_ask=state.best_no_ask_cents if state.has_no_ask else None,
                                    ticker=market_id
                                )
                                if duality_result.arbitrage_opportunity:
                                    logger.info(
                                        "[ARBITRAGE-OPPORTUNITY-LOOP] asset=%s ticker=%s edge=%dc yes_ask=%dc no_bid=%dc",
                                        asset, market_id, duality_result.arbitrage_opportunity.edge_cents,
                                        duality_result.arbitrage_opportunity.yes_ask,
                                        duality_result.arbitrage_opportunity.no_bid
                                    )
                            except Exception as arb_exc:
                                logger.warning("[ARBITRAGE-CHECK-FAILED] asset=%s ticker=%s error=%s", asset, market_id, arb_exc)
                        
                        # MARKET MAKING: Generate quotes if enabled
                        if self._market_maker and state and asset_depth_ok:
                            try:
                                # Check if market maker should refresh quotes
                                if self._market_maker.should_refresh_quotes():
                                    # Get seconds to expiry from market state
                                    seconds_to_expiry = getattr(state, 'seconds_to_expiry', 900)
                                    
                                    # Generate quotes
                                    quotes = self._market_maker.generate_quotes(
                                        ticker=market_id,
                                        yes_bid=state.best_bid_cents if state.has_bid else None,
                                        yes_ask=state.best_ask_cents if state.has_ask else None,
                                        no_bid=state.best_no_bid_cents if state.has_no_bid else None,
                                        no_ask=state.best_no_ask_cents if state.has_no_ask else None,
                                        seconds_to_expiry=seconds_to_expiry
                                    )
                                    
                                    if quotes:
                                        logger.info(
                                            "[MM-15M-LOOP] Generated %d quotes for %s asset=%s phase=%s",
                                            len(quotes), market_id, asset, self._market_maker.get_phase()
                                        )
                                        
                                        # CRITICAL FIX (2026-07-31): Execute market making quotes via order router
                                        # Previously quotes were generated but never submitted, preventing two-sided liquidity
                                        # Convert quotes to OrderIntent objects and route to order router
                                        from merid.event_venues.kalshi.order_router import OrderIntent
                                        
                                        for quote in quotes:
                                            try:
                                                # CRITICAL FIX (2026-07-31): Convert side/action to Kalshi format
                                                # OrderIntent expects Kalshi-formatted sides (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
                                                # Market maker provides lowercase side/action, need to convert
                                                from merid.event_venues.kalshi.binary_price_space import to_kalshi_side
                                                kalshi_side = to_kalshi_side(quote.side, quote.action)
                                                
                                                # Convert quote to OrderIntent
                                                quote_intent = OrderIntent(
                                                    ticker=quote.ticker,
                                                    side=kalshi_side,  # Kalshi-formatted: BUY_YES, SELL_YES, BUY_NO, SELL_NO
                                                    action=quote.action,  # "buy" or "sell" for early validation
                                                    price_cents=int(round(quote.price_cents)),
                                                    count=quote.count,  # Number of contracts
                                                    source="market_maker_15m",
                                                    intent_id=f"mm_{quote.ticker}_{quote.side}_{quote.action}_{_time.monotonic():.0f}",
                                                    entry_or_exit="entry",  # CRITICAL: Explicitly mark as entry order
                                                )
                                                
                                                # Route quote to order router asynchronously
                                                from merid.event_venues.kalshi.order_router import route_order_async
                                                asyncio.create_task(route_order_async(quote_intent))
                                                logger.debug(
                                                    "[MM-15M-EXECUTE] Routed quote: ticker=%s side=%s action=%s kalshi_side=%s price=%dc count=%d",
                                                    quote.ticker, quote.side, quote.action, kalshi_side, quote.price_cents, quote.count
                                                )
                                            except Exception as quote_exc:
                                                logger.warning(
                                                    "[MM-15M-QUOTE-FAILED] ticker=%s side=%s action=%s error=%s",
                                                    quote.ticker, quote.side, quote.action, quote_exc
                                                )
                            except Exception as mm_exc:
                                logger.warning("[MM-15M-FAILED] asset=%s ticker=%s error=%s", asset, market_id, mm_exc)
                        
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
        
        # CRITICAL FIX: 2026-07-16 - REMOVED warmup grace period for catalog_age_ok
        # Previous logic allowed trading during catalog initialization by forcing catalog_age_ok=True
        # This bypassed proper health checks and allowed orders with insufficient data
        # Now catalog must pass age check naturally - no warmup bypass
        # if in_warmup:
        #     catalog_age_ok = True  # Warmup grace: allow trading during catalog initialization
        #     catalog_health = "FRESH"  # Override to FRESH during warmup
        depth_coverage_ready = depth_sufficient_count >= MIN_DEPTH_COVERAGE_FOR_READY
        md_coverage_ok = md_fresh_count >= MIN_MD_COVERAGE_FOR_READY
        
        # Check bankroll and risk profile status
        live_bankroll_source = "unknown"
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_async, get_bankroll_service
            live_bankroll = await get_equity_for_risk_calc_async()
            live_bankroll_valid = live_bankroll is not None and live_bankroll > 0.0

            # Get bankroll source for fake bankroll detection
            if live_bankroll is not None:
                try:
                    service = await get_bankroll_service()
                    if service and service._current and hasattr(service._current, 'source'):
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

        # CRITICAL FIX (2026-08-11): Surface trading-circuit-breaker halt in loop state.
        # The breaker is a process-wide fail-closed gate independent of execution_mode.
        from merid.governance.trading_circuit_breaker import get_trading_circuit_breaker
        _breaker = get_trading_circuit_breaker()
        if _breaker.halted:
            no_trade_reason = f"TRADING_CIRCUIT_BREAKER_HALT:{_breaker.reason or 'unknown'}"
            halt_components.append(no_trade_reason)
        
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
        
        
        # CRITICAL FIX: 2026-07-16 - REMOVED warmup override that allowed trading during catalog warmup
        # Previous logic forced all health checks to True during warmup, allowing orders within seconds of startup
        # This bypassed the 30-bar indicator warmup requirement and caused orders with insufficient data
        # Now trading is BLOCKED during warmup - all health checks must pass naturally
        # if in_warmup:
        #     catalog_fresh = True
        #     catalog_age_ok = True
        #     catalog_health = "FRESH"  # Override to FRESH during warmup
        #     md_coverage_ok = True  # Warmup grace: allow trading during MD initialization
        #     ws_forwarder_healthy = True  # Warmup grace: allow trading during WS initialization
        #     depth_coverage_ready = True  # Warmup grace: allow trading during depth initialization
        #     logger.info(
        #         "[CATALOG-WARMUP-FINAL-OVERRIDE] Forcing catalog_fresh=True, catalog_age_ok=True, catalog_health=FRESH, md_coverage_ok=True, ws_forwarder_healthy=True, depth_coverage_ready=True during warmup (%.1fs/%.1fs)",
        #         time_since_roll, self._catalog_warmup_seconds
        #     )
            
        
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
    
    
    # CRITICAL FIX: Periodic slot allocator cleanup to prevent phantom exposure
    # Clear stale slots that haven't been released (e.g., from crashed orders, network issues)
    # This prevents "Insufficient exposure" rejections when position cache shows 0 positions
    try:
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        slot_allocator = get_global_slot_allocator()
        # Clear slots older than 30 minutes (slots should be released on position close)
        stale_count = slot_allocator.clear_stale_slots(max_age_seconds=1800)
        if stale_count > 0:
            logger.warning(
                "[SLOT-ALLOCATOR-CLEANUP] cycle=%d cleared %d stale slots (age > 30min)",
                tick, stale_count
            )
    except Exception as e:
        logger.warning("[SLOT-ALLOCATOR-CLEANUP] Failed to clear stale slots: %s", e, exc_info=True)
    
    # DIAGNOSTIC: Log after slot allocator cleanup
    
    
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

    # Log parity metrics summary every 100 cycles
    if self._tick % 100 == 0:
        try:
            from merid.validation.yes_no_parity_checker import get_parity_metrics
            metrics = get_parity_metrics()
            summary = metrics.get_summary()
            is_healthy = metrics.is_healthy()
            
            logger.info(
                "[YES_NO_PARITY] cycle=%d evaluated=%d traded=%d failed=%d healthy=%s "
                "failures_by_reason=%s yes_won_no_traded=%d no_won_yes_traded=%d",
                self._tick,
                summary["total_markets_evaluated"],
                summary["total_markets_traded"],
                summary["parity_checks_failed"],
                is_healthy,
                summary["failures_by_reason"],
                summary["yes_won_but_no_traded"],
                summary["no_won_but_yes_traded"],
            )
            
            # Reset metrics for next 100-cycle window
            from merid.validation.yes_no_parity_checker import reset_parity_metrics
            reset_parity_metrics()
        except Exception as parity_metrics_err:
            logger.debug("[15M-LOOP] Failed to log parity metrics: %s", parity_metrics_err)
        
        # Log rejection reason summary every 100 cycles
        try:
            total_rejections = sum(self._rejection_counters.values())
            logger.info(
                "[REJECTION-COUNTERS] cycle=%d total_rejections=%d parity_blocked=%d edge_below_threshold=%d "
                "duplicate_order=%d price_out_of_range=%d position_exists=%d resting_order_exists=%d "
                "edge_validation_failed=%d exit_policy_failed=%d router_rejected=%d other=%d",
                self._tick,
                total_rejections,
                self._rejection_counters["parity_blocked"],
                self._rejection_counters["edge_below_threshold"],
                self._rejection_counters["duplicate_order"],
                self._rejection_counters["price_out_of_range"],
                self._rejection_counters["position_exists"],
                self._rejection_counters["resting_order_exists"],
                self._rejection_counters["edge_validation_failed"],
                self._rejection_counters["exit_policy_failed"],
                self._rejection_counters["router_rejected"],
                self._rejection_counters["other"],
            )
            
            # Reset counters for next 100-cycle window
            for key in self._rejection_counters:
                self._rejection_counters[key] = 0
        except Exception as rejection_err:
            logger.debug("[15M-LOOP] Failed to log rejection counters: %s", rejection_err)

    # P2 Task 11: Log periodic summary every hour (3600 cycles at 5s cadence = 18000s = 5h)
    # Adjust interval based on actual cadence
    if self._run_summary and self._tick % 720 == 0:  # Every ~1 hour (720 cycles × 5s = 3600s)
        try:
            self._run_summary.log_periodic(interval_seconds=3600.0)
        except Exception as e:
            logger.warning("[15m-LOOP] Failed to log periodic summary: %s", e, exc_info=True)

async def _run_agent_grid_with_timeout(self, tick: int, trading_ready: bool = True, allow_new_entries: bool = True) -> list[dict]:
    # Run agent grid cycle with proper error handling and return candidates.
    # This is the SINGLE canonical path for running the agent grid.
    # Args:
    #     tick: Current cycle tick number
    #     trading_ready: Whether trading is ready (can place orders)
    #     allow_new_entries: Whether new position entries are allowed (from execution_mode)
    # Returns:
    #     List of candidate dictionaries (empty list on error or no candidates)
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
            
            # Initialize all assets to 0 (use Decimal to match position.notional_value type)
            from decimal import Decimal
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                self._asset_positions[asset] = Decimal('0.0')
            
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
                        notional = Decimal(str(position.notional_value))
                        self._asset_positions[asset] += notional
                        # CRITICAL FIX (2026-07-31): Log individual position notional for debugging
                        logger.debug(
                            "[15M-LOOP] Position notional: market=%s asset=%s contracts=%d avg_price=%dc notional=%s",
                            market_id, asset, position.contracts, position.avg_price_cents, notional
                        )
            
            logger.info("[15M-LOOP] Reloaded positions from cache: %s", list(self._asset_positions.keys()) if hasattr(self._asset_positions, 'keys') else str(self._asset_positions))
            
            # CRITICAL FIX (2026-07-31): Detect 0 exposure bug
            # If we have positions but all assets show 0 exposure, this indicates a bug
            total_positions = sum(1 for p in all_positions.values() if p.contracts > 0)
            total_exposure = sum(self._asset_positions.values())
            if total_positions > 0 and total_exposure == 0:
                logger.critical(
                    "[15M-LOOP] CRITICAL BUG DETECTED: %d positions loaded but total exposure is 0. "
                    "This indicates position cache notional calculation is failing. "
                    "Positions: %s",
                    total_positions,
                    {mid: (p.contracts, p.avg_price_cents) for mid, p in all_positions.items() if p.contracts > 0}
                )
            
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
                
                # CRITICAL FIX (2026-07-16): Trigger catalog refresh on 15m window boundary
                # This ensures the catalog is updated immediately when markets roll over
                # preventing trading on expired markets during the brief window after rollover
                logger.info("[15m-LOOP] WINDOW-CHANGE: Triggering catalog refresh for new 15m window")
                try:
                    from merid.event_venues.kalshi.market_catalog import get_kalshi_market_catalog
                    catalog = get_kalshi_market_catalog()
                    # Force a refresh to get new markets for the new window
                    # Add timeout to prevent indefinite blocking if catalog refresh hangs
                    await asyncio.wait_for(catalog.refresh(force=True), timeout=30.0)
                    logger.info("[15m-LOOP] WINDOW-CHANGE: Catalog refresh completed for new window")
                except asyncio.TimeoutError:
                    logger.error("[15m-LOOP] WINDOW-CHANGE: Catalog refresh timed out after 30s - will retry on next periodic refresh")
                except Exception as e:
                    logger.warning(f"[15m-LOOP] WINDOW-CHANGE: Failed to trigger catalog refresh: {e}", exc_info=True)
                
                # Reset best-edge tracking for new window
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._best_edge_per_asset[asset] = None
                logger.info("[15m-LOOP] Reset best-edge tracking for new window")
                
                # Reset swing mode for new window (swing mode only valid within same 15m window)
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    self._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
                logger.info("[15m-LOOP] Reset swing mode for new window")
                
                # CRITICAL FIX (2026-07-13): Clear phantom slots from global slot allocator on timeframe transition
                # This prevents false "Insufficient exposure" rejections when old slots from previous timeframe persist
                logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing phantom slots from global slot allocator")
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    from merid.risk.global_slot_allocator import get_global_slot_allocator
                    
                    position_cache = get_position_cache()
                    slot_allocator = get_global_slot_allocator()
                    
                    # Get current position count from cache
                    all_positions = position_cache.get_all_positions(validate_freshness=False)
                    open_positions = {k: v for k, v in all_positions.items() if v.contracts > 0}
                    position_count = len(open_positions)
                    
                    logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Current position_count={position_count}")
                    
                    # Clear slots on timeframe transition regardless of position count
                    # New timeframe = fresh start for slot allocation
                    slot_allocator.clear_slots_on_empty_positions(position_count=0)
                    logger.info("[15m-LOOP] TIMEFRAME-RESET: Cleared all slots for new timeframe")
                    
                    # CRITICAL FIX (2026-07-13): Reset window exposure on timeframe transition
                    # New timeframe should start with fresh window exposure tracking
                    logger.info("[15m-LOOP] TIMEFRAME-RESET: Resetting window exposure tracking")
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
                        force_reset_window_exposure(reason="timeframe_transition")
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Window exposure reset complete")
                    except Exception as e:
                        logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to reset window exposure: %s", e, exc_info=True)
                except Exception as e:
                    logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear slots: %s", e, exc_info=True)
                
                # CRITICAL FIX (2026-07-13): Clear position cache on timeframe transition ONLY if no actual positions
                # This prevents losing track of positions held across timeframe boundaries
                # Position cache is only cleared if position_count=0 (no actual open positions)
                if position_count == 0:
                    logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing position cache for new timeframe (position_count=0)")
                    try:
                        from merid.event_venues.kalshi.position_cache import get_position_cache
                        position_cache = get_position_cache()
                        await position_cache.clear()  # Use async clear() for mutex protection
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Position cache cleared")
                    except Exception as e:
                        logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear position cache: %s", e, exc_info=True)
                else:
                    logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Skipping position cache clear (position_count={position_count} > 0)")
                
                # CRITICAL FIX (2026-07-13): Clear fills ledger open positions on timeframe transition ONLY if no actual positions
                # This prevents losing track of positions held across timeframe boundaries
                if position_count == 0:
                    logger.info("[15m-LOOP] TIMEFRAME-RESET: Clearing fills ledger open positions for new timeframe (position_count=0)")
                    try:
                        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                        ledger = get_fills_ledger()
                        await ledger.clear_open_positions_on_empty_cache()
                        logger.info("[15m-LOOP] TIMEFRAME-RESET: Fills ledger open positions cleared")
                    except Exception as e:
                        logger.warning("[15m-LOOP] TIMEFRAME-RESET: Failed to clear fills ledger: %s", e, exc_info=True)
                else:
                    logger.info(f"[15m-LOOP] TIMEFRAME-RESET: Skipping fills ledger clear (position_count={position_count} > 0)")
                
                # Reset UnifiedRiskManager cycle tracking
                from merid.risk.unified_risk_manager import get_unified_risk_manager
                risk_mgr = get_unified_risk_manager()
                risk_mgr.reset_cycle()
                logger.info("[15m-LOOP] Reset UnifiedRiskManager cycle for window=%s", current_window.suffix)
            else:
                logger.debug("[15m-LOOP] Window unchanged: %s - skipping cycle reset", current_window.suffix)
            
            # Balance calibration is the responsibility of the caller (_run_loop / _run_cycle_wrapper)
            # so that one logical tick consumes exactly one bankroll snapshot.
            # Pass Coinbase velocity signals to agent grid for external spot velocity integration
            # (Turbine research #1 winner: Coinbase 1-minute velocity)
            coinbase_velocity = self._coinbase_velocity_signals if hasattr(self, '_coinbase_velocity_signals') else {}
            # CRITICAL FIX (2026-08-11): Halt gating - stop signal generation, sizing,
            # allocation, and entry execution when the TradingCircuitBreaker is tripped.
            # Exchange reconciliation (sync_from_rest) and position monitoring remain alive;
            # only manual emergency closes with a valid token may route.
            from merid.governance.trading_circuit_breaker import get_trading_circuit_breaker
            breaker = get_trading_circuit_breaker()
            if breaker.halted:
                reason = breaker.reason or "unknown"
                logger.critical(
                    "[TRADING-CIRCUIT-BREAKER] Cycle %d gated: agent_grid.run_cycle skipped, "
                    "no candidates will be generated or sized. reason=%s",
                    tick, reason,
                )
                # Keep exchange reconciliation alive outside run_cycle.
                sync_result = {
                    "success": False,
                    "positions_count": 0,
                    "open_orders_count": 0,
                }
                if hasattr(self.agent_grid, 'sync_from_rest'):
                    try:
                        sync_result = await self.agent_grid.sync_from_rest(tick)
                        logger.info("[15M-LOOP] Halt gate: sync_from_rest completed for tick=%d", tick)
                    except Exception as sync_err:
                        logger.warning("[15M-LOOP] Halt gate: sync_from_rest failed: %s", sync_err)

                # CRITICAL FIX (2026-08-26): Auto-resume from an
                # unmatched_live_exchange_fill halt when the offending fill has been
                # classified and the exchange is provably flat (zero positions and
                # zero open orders).  This is the automated counterpart to
                # admin_release for stale WS→HTTP identity-race halts.
                #
                # Only proceed when the REST sync this cycle succeeded, so we do not
                # assume zero exposure from a skipped or failed sync.
                if (
                    breaker.reason == "unmatched_live_exchange_fill"
                    and sync_result.get("success") is True
                ):
                    try:
                        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                        ledger = get_fills_ledger()
                        since = datetime.now(timezone.utc) - timedelta(minutes=30)

                        # Resolve the triggering fill first.  This may reclassify the
                        # fill from unmatched to matched, reducing the count of
                        # remaining unmatched fills we check below.
                        fill_id = (breaker.halt_info or {}).get("metadata", {}).get("fill_id")
                        fill_state: Optional[Dict[str, Any]] = None
                        if fill_id:
                            fill_state = await ledger.get_fill_resolution_state(fill_id)

                        recent_unmatched = ledger.count_unmatched_fills(since=since)

                        breaker.maybe_auto_resume_unmatched(
                            exchange_positions_count=sync_result.get("positions_count", 0),
                            open_orders_count=sync_result.get("open_orders_count", 0),
                            fill_state=fill_state,
                            recent_unmatched_count=recent_unmatched,
                        )
                    except Exception as auto_resume_err:
                        logger.warning("[15M-LOOP] Halt gate: auto-resume check failed: %s", auto_resume_err)

                return []

            logger.info("[15M-LOOP] About to call agent_grid.run_cycle tick=%d", tick)
            candidates = await self.agent_grid.run_cycle(tick, allow_new_entries=allow_new_entries, coinbase_velocity=coinbase_velocity)
            logger.info("[15M-LOOP] Generated %d candidates in cycle %d", len(candidates), tick)
            
            # CRITICAL: Return candidates to caller for processing
            # This is the SINGLE canonical path - caller (_run_loop) will process candidates
            return candidates
        except Exception as exc:
            # CRITICAL: Log any exception in run_cycle with full stack trace and structured classification
            error_msg = str(exc).lower()
            error_type = type(exc).__name__
            
            # Classify error severity
            if any(keyword in error_msg for keyword in ["authentication", "unauthorized", "forbidden", "credential"]):
                severity = "CRITICAL"
                logger.critical("[15M-LOOP] AUTH_FAILURE agent_grid.run_cycle cycle=%d: %s - %s", tick, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["timeout", "deadline", "timed out"]):
                severity = "WARNING"
                logger.warning("[15M-LOOP] TIMEOUT agent_grid.run_cycle cycle=%d: %s - %s", tick, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["connection", "network", "dns"]):
                severity = "WARNING"
                logger.warning("[15M-LOOP] NETWORK agent_grid.run_cycle cycle=%d: %s - %s", tick, error_type, exc, exc_info=True)
            elif any(keyword in error_msg for keyword in ["memory", "allocation", "out of memory"]):
                severity = "CRITICAL"
                logger.critical("[15M-LOOP] MEMORY agent_grid.run_cycle cycle=%d: %s - %s", tick, error_type, exc, exc_info=True)
            else:
                severity = "ERROR"
                logger.error("[15M-LOOP] agent_grid.run_cycle failed cycle=%d severity=%s: %s - %s", tick, severity, error_type, exc, exc_info=True)
            
            with _diag_open() as f:
                f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: agent_grid.run_cycle EXCEPTION cycle={tick} severity={severity} error={exc}\n")
                f.write(f"[{datetime.now(timezone.utc)}] 15M-LOOP: STACK TRACE: {__import__('traceback').format_exc()}\n")
                f.flush()
            
            # CRITICAL: Return empty list on error instead of raising
            # This allows the caller (_run_loop) to handle the error gracefully
            logger.warning("[15M-LOOP] Returning empty candidate list due to exception in agent_grid.run_cycle")
            return []
        
        # CRITICAL: Log after agent_grid.run_cycle returns
        
        
        logger.debug("[15M-LOOP] GRID-RUN-CYCLE-AWAIT EXIT cycle=%d", tick)
        logger.debug("[15M-LOOP-TRACE] agent_grid.run_cycle returned cycle=%d", tick)
        
        # CRITICAL: Return candidates to caller for processing
        return candidates
    else:
        # Fallback: run agents directly if run_cycle not implemented
        pass  # Log below
        logger.info("[15M-LOOP-TRACE] run_cycle not implemented, running agents directly cycle=%d", tick)
        await self._run_agents_directly(tick)
        logger.info("[15M-LOOP-TRACE] _run_agents_directly returned cycle=%d", tick)
        
        # CRITICAL: Return empty list for fallback path
        return []
    logger.debug("[15M-LOOP-TRACE] _run_agent_grid_with_timeout EXIT cycle=%d", tick)
    logger.debug("[15M-LOOP] GRID-WITH-TIMEOUT-EXIT cycle=%d", tick)

def _get_candidate_key(self, candidate: Dict) -> str:
    # Generate a unique key for a candidate to track execution within a window.
    # Args:
    #     candidate: Candidate dict from agent grid
    # Returns:
    #     Unique key string (ticker + side + price_cents)
    # CRITICAL FIX (2026-07-13): Include price_cents to prevent re-executing
    # the same ticker+side at different prices within the same window.
    # This ensures we only execute 1 order per ticker+side+price per 15-minute window.
    ticker = candidate.get("ticker", "")
    side = candidate.get("side", "")
    price_cents = candidate.get("price_cents", 0)
    return f"{ticker}:{side}:{price_cents}"

def _get_asset_window_key(self, candidate: Dict) -> str:
    # Generate a key for asset + 15-minute window to enforce one-contract-per-asset rule.
    # Args:
    #     candidate: Candidate dict from agent grid
    # Returns:
    #     Unique key string (asset + 15-minute window ID)
    # CRITICAL FIX (2026-07-21): This enforces one-contract-per-asset-per-15-minute rule
    # at execution time, not just signal time. The key is tied to the specific 15-minute
    # contract (window), not just the asset, to prevent duplicate orders across windows.
    # CRITICAL FIX (2026-07-21): Use canonical identity helper for consistency across stack
    from merid.utils.kalshi_identity import extract_asset_window_key
    ticker = candidate.get("ticker", "")
    return extract_asset_window_key(ticker)

def _validate_candidate_edge(self, candidate: Dict) -> bool:
    # Re-validate candidate edge before execution to prevent bad trades.
    # This checks if the edge has shifted to unprofitable since the candidate
    # was generated. If the edge is no longer positive, the candidate is rejected.
    # Args:
    #     candidate: Candidate dict from agent grid
    # Returns:
    #     True if edge is still valid (positive), False otherwise
    # Single source of truth: edge_pct in FRACTION units
    edge = candidate.get("edge_pct", 0.0)
    
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

async def _execute_candidate(self, candidate: Dict, tick: int) -> bool:
    # Convert candidate dict to OrderIntent and route to order router.
    # Returns True if order was submitted, False if order was rejected/skipped.
    try:
        from merid.event_venues.kalshi.order_router import OrderIntent, resolve_window_policy, resolve_exit_policy, route_order_async
        
        ticker = candidate.get("ticker")
        if not ticker:
            logger.warning("[15M-LOOP] Candidate missing ticker, skipping")
            return False
        
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
                return False

            # CRITICAL FIX (2026-08-12): Extract signal model state up-front.
            # resolve_exit_policy() needs these before constructing OrderIntent.
            edge_pct = float(candidate.get("edge_pct", 0.0))
            confidence = float(candidate.get("confidence", 0.5))
            model_prob = candidate.get("model_prob", None)

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
        except Exception as e:
            self._rejection_counters["exit_policy_failed"] += 1
            logger.error(
                "[15M-LOOP] Failed to resolve policy setup for %s: %s - REJECTING ORDER for safety",
                ticker, e, exc_info=True
            )
            return False
        
        # CRITICAL FIX: Respect signal's price_cents unless invalid
        # Signal generation now sets correct price based on side (YES uses YES price, NO uses NO price)
        # Only override if signal's price_cents is invalid (<=0 or outside canonical range)
        price_cents = candidate.get("price_cents", 0)
        
        # CRITICAL FIX (2026-08-14): Single canonical entry range 10c-75c.
        # The previous side-aware/late-expiry expansion (15c-99c NO, 1c-90c YES)
        # allowed 97c extreme fills that destroyed the bankroll.
        from merid.event_venues.kalshi.binary_price_space import CANONICAL_MIN_CENTS, CANONICAL_MAX_CENTS
        min_price_cents, max_price_cents = CANONICAL_MIN_CENTS, CANONICAL_MAX_CENTS
        
        # Validate signal's price_cents
        price_valid = (price_cents > 0) and (min_price_cents <= price_cents <= max_price_cents)
        
        if price_valid:
            # Signal's price is valid - use it directly
            logger.info("[15M-LOOP] ticker=%s using signal price_cents=%d (side=%s, valid in canonical range)", 
                      ticker, price_cents, candidate.get("side"))
        else:
            # Signal's price is invalid - fall back to market state
            logger.warning(f"[15M-LOOP] ticker={ticker} signal price_cents={price_cents} invalid (<=0 or outside {min_price_cents}-{max_price_cents}c range), falling back to market state")
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                market_state_store = get_kalshi_market_state_store()
                market_state = market_state_store.get(ticker) if market_state_store else None
                if market_state:
                    # CRITICAL FIX: For NO orders, calculate NO mid-price from YES bid/ask
                    # Kalshi duality: NO_mid = 100 - YES_mid
                    candidate_side = candidate.get("side", "").lower()
                    # CRITICAL FIX: If side is missing, log error and skip
                    if not candidate_side:
                        logger.error("[15M-LOOP] CRITICAL: candidate missing 'side' field for ticker=%s - CANNOT DETERMINE PRICE - SKIPPING", ticker)
                        return False
                    if candidate_side == "no" or candidate_side == "buy_no":
                        # NO order: calculate NO mid-price
                        if market_state.best_bid_cents and market_state.best_ask_cents:
                            yes_mid = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                            raw_price_cents = 100 - yes_mid
                            # RESEARCH-ALIGNED: Clamp to dynamic price band (5-90c late, 10-75c early/mid)
                            price_cents = max(min_price_cents, min(max_price_cents, raw_price_cents))
                            logger.info("[15M-LOOP] ticker=%s NO order: YES_mid=%d -> NO_mid=%d (raw=%d, clamped=%d)", ticker, yes_mid, price_cents, raw_price_cents, price_cents)
                        elif market_state.mid_cents:
                            raw_price_cents = 100 - int(market_state.mid_cents)
                            # RESEARCH-ALIGNED: Clamp to dynamic price band (5-90c late, 10-75c early/mid)
                            price_cents = max(min_price_cents, min(max_price_cents, raw_price_cents))
                            logger.info("[15M-LOOP] ticker=%s NO order: YES_mid_cents=%.2f -> NO_mid=%d (raw=%d, clamped=%d)", ticker, market_state.mid_cents, price_cents, raw_price_cents, price_cents)
                        else:
                            logger.warning("[15M-LOOP] NO order but no market state data for %s, using default 42c", ticker)
                            price_cents = 42  # 2026-07-14: Fixed to 42c (midpoint of 10-75c canonical range)
                    else:
                        # YES order: use YES mid-price
                        if market_state.mid_cents:
                            # BUG #39 FIX: Convert mid_cents to integer
                            # mid_cents is a float from unified_market_state.py but order router requires integer
                            raw_price_cents = int(market_state.mid_cents)
                            # RESEARCH-ALIGNED: Clamp to dynamic price band (5-90c late, 10-75c early/mid)
                            price_cents = max(min_price_cents, min(max_price_cents, raw_price_cents))
                            logger.info("[15M-LOOP] ticker=%s YES order: price_cents from mid_cents=%d (raw=%.2f, clamped=%d)", ticker, price_cents, market_state.mid_cents, price_cents)
                        elif market_state.best_bid_cents and market_state.best_ask_cents:
                            # Use mid of bid/ask if mid not available
                            raw_price_cents = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                            # RESEARCH-ALIGNED: Clamp to dynamic price band (5-90c late, 10-75c early/mid)
                            price_cents = max(min_price_cents, min(max_price_cents, raw_price_cents))
                            logger.info("[15M-LOOP] ticker=%s YES order: price_cents from bid/ask mid=%d (raw=%d, clamped=%d) (bid=%d, ask=%d)", ticker, price_cents, raw_price_cents, price_cents, market_state.best_bid_cents, market_state.best_ask_cents)
                        else:
                            logger.warning("[15M-LOOP] YES order but no market state data for %s, using default 42c", ticker)
                            price_cents = 42  # 2026-07-14: Fixed to 42c (midpoint of 10-75c canonical range)
                else:
                    logger.warning("[15M-LOOP] No market state available for %s, using default 42c", ticker)
                    price_cents = 42  # 2026-07-14: Fixed to 42c (midpoint of 10-75c canonical range)
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to get price from market state for %s: %s", ticker, e)
                price_cents = 42  # 2026-07-14: Fixed to 42c (midpoint of 10-75c canonical range)

        # Kalshi prices are whole cents; normalize any float/numpy scalar that may
        # have leaked through from market-state arithmetic before building the intent.
        price_cents = int(round(price_cents))

        # CRITICAL FIX (2026-08-12): Resolve exit policy now that the final executable
        # entry price is known. resolve_exit_policy needs price_cents and model_prob
        # to compute a fee/fair-capped TP and to decide whether any fixed TP is reachable.
        try:
            edge_cents = None
            if model_prob is not None and price_cents is not None and price_cents > 0:
                edge_cents = (float(model_prob) - price_cents / 100.0) * 100.0
            edge_result = None
            if edge_cents is not None and edge_cents > 0:
                edge_result = {
                    "net_edge_cents": edge_cents,
                    "confidence": float(confidence) if confidence is not None else 0.5,
                }
            strip_context = {
                "entry_price_cents": price_cents,
                "entry_model_probability": float(model_prob) if model_prob is not None else None,
            }
            exit_policy = resolve_exit_policy(
                edge_result=edge_result,
                asset=asset,
                regime=regime,
                strip_context=strip_context,
            )
            if exit_policy:
                logger.info("[15M-LOOP] exit_policy resolved successfully: policy_id=%s asset=%s regime=%s", exit_policy.policy_id, asset, regime)
                assert exit_policy is not None, f"Exit policy resolution returned None for ticker={ticker}"
                assert exit_policy.policy_id is not None, f"Exit policy missing policy_id for ticker={ticker}"
                assert exit_policy.tp_r_multiple >= 0, f"Exit policy TP R-multiple must be non-negative for ticker={ticker}, got {exit_policy.tp_r_multiple}"
                assert exit_policy.sl_cents >= 0, f"Exit policy SL cents must be non-negative for ticker={ticker}, got {exit_policy.sl_cents}"
                assert exit_policy.max_hold_seconds > 0, f"Exit policy max_hold_seconds must be positive for ticker={ticker}, got {exit_policy.max_hold_seconds}"
                if not exit_policy.take_profit_enabled and not exit_policy.stop_loss_enabled:
                    self._rejection_counters["exit_policy_no_targets"] = self._rejection_counters.get("exit_policy_no_targets", 0) + 1
                    logger.warning("[15M-LOOP] No executable TP/SL for %s (no trusted edge) - rejecting order", ticker)
                    return False
            else:
                self._rejection_counters["exit_policy_failed"] += 1
                logger.error("[15M-LOOP] exit_policy is None after resolution! asset=%s regime=%s", asset, regime)
                return False
        except Exception as e:
            self._rejection_counters["exit_policy_failed"] += 1
            logger.error(
                "[15M-LOOP] Failed to resolve exit policy for %s: %s - REJECTING ORDER for safety",
                ticker, e, exc_info=True
            )
            return False

        # CRITICAL FIX: Consolidated sizing path - use count from unified_sizing
        # The count is already computed by compute_order_size in the main loop (line 1565)
        # This removes the dual sizing path inconsistency where _execute_candidate
        # would recalculate count from risk envelope, overwriting the unified_sizing result
        count = int(candidate.get("count", 1))
        
        # 2026-08-22: Count is computed by unified_sizing under the $1 cap. Allow up to
        # MAX_CONTRACTS_PER_ORDER as a defensive ceiling; compute_order_size will still
        # reduce the count when price/exposure doesn't allow 2 contracts.
        if count > MAX_CONTRACTS_PER_ORDER:
            logger.warning(
                "[15M-LOOP] CRITICAL: count=%d exceeds max_contracts_per_order=%d, capping. ticker=%s",
                count, MAX_CONTRACTS_PER_ORDER, ticker
            )
            count = MAX_CONTRACTS_PER_ORDER
        
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
        confidence_valid = candidate.get("confidence_valid", False)
        confidence_source = candidate.get("confidence_source", "unknown")
        settlement_reference = candidate.get("settlement_reference")
        model_prob = candidate.get("model_prob", 0.5)
        raw_logit = candidate.get("raw_logit", 0.0)  # Phase 5.4: Raw logit for calibration

        # CRITICAL FIX (2026-08-19): Backfill missing provenance from the canonical
        # TradeDecision object carried on the candidate.  Some return paths flatten
        # the candidate and drop run_id / decision_id / confidence state; this
        # ensures the OrderIntent always carries an attributable, release-qualified
        # identity and settlement chain.
        trade_decision = candidate.get("trade_decision")
        if trade_decision is not None:
            if not candidate.get("run_id"):
                candidate["run_id"] = getattr(trade_decision, "run_id", None)
            if not candidate.get("decision_id"):
                candidate["decision_id"] = getattr(trade_decision, "decision_id", None)
            if not candidate.get("confidence_valid"):
                candidate["confidence_valid"] = bool(getattr(trade_decision, "confidence_valid", False))
            if not candidate.get("confidence_source") or candidate.get("confidence_source") == "unknown":
                candidate["confidence_source"] = getattr(trade_decision, "confidence_source", "unknown")
            if not candidate.get("settlement_reference"):
                candidate["settlement_reference"] = getattr(trade_decision, "settlement_reference", None)
            if not candidate.get("data_state"):
                candidate["data_state"] = getattr(trade_decision, "data_state", None)
            if not candidate.get("regime_label"):
                candidate["regime_label"] = getattr(trade_decision, "regime_label", None)
            if candidate.get("regime_probability") is None:
                _rp = getattr(trade_decision, "regime_probability", None)
                candidate["regime_probability"] = float(_rp) if _rp is not None else None
            if candidate.get("gross_edge") is None and getattr(trade_decision, "gross_edge", None) is not None:
                candidate["gross_edge"] = float(getattr(trade_decision, "gross_edge"))
            if candidate.get("net_edge") is None and getattr(trade_decision, "net_edge", None) is not None:
                candidate["net_edge"] = float(getattr(trade_decision, "net_edge"))
            if candidate.get("min_required_edge") is None and getattr(trade_decision, "min_required_edge", None) is not None:
                candidate["min_required_edge"] = float(getattr(trade_decision, "min_required_edge"))
            if candidate.get("selected_outcome_price") is None and getattr(trade_decision, "selected_outcome_price", None) is not None:
                _sop = getattr(trade_decision, "selected_outcome_price")
                candidate["selected_outcome_price"] = int(round(float(_sop) * 100.0))

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
                # Get velocity threshold from profile (aligned with kalshi_crypto_15m_v2.yaml)
                velocity_threshold = 0.00015  # Default BTC threshold
                if asset == "ETH":
                    velocity_threshold = 0.00015
                elif asset == "SOL":
                    velocity_threshold = 0.000225
                elif asset == "XRP":
                    velocity_threshold = 0.000225
                elif asset == "DOGE":
                    velocity_threshold = 0.0003
                edge_pct = calculate_velocity_edge(velocity, velocity_threshold)
            except Exception as e:
                logger.warning("[15M-LOOP] Failed to use standardized edge calculation: %s, using fallback", e)
                edge_pct = abs(velocity)  # Fallback: keep in FRACTION units
            
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
            self._rejection_counters["other"] += 1
            logger.warning(
                "[15M-LOOP] REJECTING CANDIDATE: missing side=%s or action=%s for ticker=%s - "
                "preventing systematic YES bias by rejecting incomplete data",
                side_raw, action_raw, ticker
            )
            return False
        
        logger.debug("[15M-LOOP] Converting side/action: side_raw=%s action_raw=%s", side_raw, action_raw)
        
        # Use canonical side mapping function
        try:
            kalshi_side = to_kalshi_side(side_raw, action_raw)
        except ValueError as e:
            self._rejection_counters["other"] += 1
            logger.warning(
                "[15M-LOOP] Invalid side/action combination: side=%s action=%s for ticker=%s - %s",
                side_raw, action_raw, ticker, e
            )
            return False
        
        # CRITICAL INVARIANT CHECK: Entry orders must ALWAYS use BUY actions
        # Entry trades: BUY_YES (bullish) or BUY_NO (bearish)
        # SELL actions are ONLY for exit trades
        if action_raw == "SELL":
            # Check if this is an entry order using entry_or_exit field if available
            is_exit_order = False
            if "entry_or_exit" in candidate:
                is_exit_order = (candidate["entry_or_exit"] == "exit")
            else:
                # Legacy detection: check for exit_reason or exit in rationale
                is_exit_order = candidate.get("exit_reason") is not None
                is_exit_order = is_exit_order or ("rationale" in candidate and "exit" in str(candidate["rationale"]).lower())
            
            if not is_exit_order:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[ENTRY-ORDER-INVARIANT-VIOLATION] ticker=%s side=%s action=%s kalshi_side=%s - "
                    "Entry orders must use BUY actions only. SELL actions are for exit trades only. "
                    "Rejecting this entry order to prevent SELL YES/SELL_NO on entry.",
                    ticker, side_raw, action_raw, kalshi_side
                )
                return False
        
        # CRITICAL INVARIANT CHECK: Position-delta invariant for entry/exit direction
        # ENTRY: applying fill must strictly increase position magnitude (0 to >0)
        # EXIT: applying fill must strictly decrease position magnitude (|pos_after| < |pos_before|)
        entry_or_exit = None  # Initialize to prevent UnboundLocalError
        if "entry_or_exit" in candidate and "pre_position_size" in candidate and "expected_post_position_size" in candidate:
            entry_or_exit = candidate["entry_or_exit"]
            pre_position_size = candidate["pre_position_size"]
            expected_post_position_size = candidate["expected_post_position_size"]
        else:
            # CRITICAL FIX (2026-07-31): Default to "entry" if entry_or_exit not set
            # agent_grid_15m doesn't set this field, so we default to entry for new orders
            entry_or_exit = "entry"
            pre_position_size = 0  # Assume no existing position for entry
            expected_post_position_size = count  # Assume full position size for entry
            logger.debug(
                "[15M-LOOP] entry_or_exit not set in candidate, defaulting to entry: ticker=%s",
                ticker
            )
            
        if entry_or_exit == "entry":
            # Entry: must go from 0 to >0
            if pre_position_size != 0:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[ENTRY-POSITION-DELTA-VIOLATION] ticker=%s entry_or_exit=%s pre_position_size=%d - "
                    "ENTRY orders require pre_position_size=0. This order would increase existing position "
                    "which violates the entry/exit direction invariant. Rejecting.",
                    ticker, entry_or_exit, pre_position_size
                )
                return False
            if expected_post_position_size <= 0:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[ENTRY-POSITION-DELTA-VIOLATION] ticker=%s entry_or_exit=%s expected_post_position_size=%d - "
                    "ENTRY orders must result in positive position. This violates the entry/exit direction invariant. Rejecting.",
                    ticker, entry_or_exit, expected_post_position_size
                )
                return False
        elif entry_or_exit == "exit":
            # Exit: must decrease position magnitude, never go from 0 to nonzero
            if pre_position_size <= 0:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[EXIT-POSITION-DELTA-VIOLATION] ticker=%s entry_or_exit=%s pre_position_size=%d - "
                    "EXIT orders require pre_position_size>0 (existing position). This exit order has no position to close. "
                    "This violates the entry/exit direction invariant. Rejecting.",
                    ticker, entry_or_exit, pre_position_size
                )
                return False
            if expected_post_position_size >= pre_position_size:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[EXIT-POSITION-DELTA-VIOLATION] ticker=%s entry_or_exit=%s pre=%d post=%d - "
                    "EXIT orders must decrease position magnitude. This order would not decrease or would increase position. "
                    "This violates the entry/exit direction invariant. Rejecting.",
                    ticker, entry_or_exit, pre_position_size, expected_post_position_size
                )
                return False
            # Check for position flip (e.g., +5 -> -1) - exit trying to open opposite leg
            if expected_post_position_size < 0:
                self._rejection_counters["other"] += 1
                logger.error(
                    "[EXIT-POSITION-FLIP-VIOLATION] ticker=%s entry_or_exit=%s pre=%d post=%d - "
                    "EXIT orders cannot flip position sign (e.g., from +5 to -1). This would open exposure on opposite leg "
                    "instead of closing the current position. This violates the entry/exit direction invariant. Rejecting.",
                    ticker, entry_or_exit, pre_position_size, expected_post_position_size
                )
                return False
        
        # CRITICAL FIX (2026-07-19): Validate strategy intent vs net exposure
        # This prevents side/price mapping bugs where intent doesn't match exposure
        strategy_intent = candidate.get("strategy_intent")
        candidate_side = candidate.get("side")

        # CRITICAL INSTRUMENTATION (2026-07-23): Log candidate_side vs order_side for bias detection
        logger.info(
            "[SIDE-PRESERVATION-CHECK] ticker=%s candidate_side=%s order_side=%s order_action=%s kalshi_side=%s strategy_intent=%s",
            ticker, candidate_side, side_raw, action_raw, kalshi_side, strategy_intent
        )

        # CRITICAL INVARIANT (2026-07-23): For entries, order_side must match candidate_side
        # This catches side flipping in the router/allocator path
        if entry_or_exit == "entry" and candidate_side and side_raw:
            if candidate_side.lower() != side_raw.lower():
                logger.error(
                    "[SIDE-PRESERVATION-VIOLATION] ticker=%s candidate_side=%s != order_side=%s - SIDE FLIPPING DETECTED IN ROUTER/ALLOCATOR PATH",
                    ticker, candidate_side, side_raw
                )
                # Block the trade - this is a critical bug
                return False

        if strategy_intent:
            # DIRECTION POLICY (2026-08-07): Entry orders must use BUY actions only
            # Cross-leg equivalence is prohibited:
            # +Yes exposure: BUY_YES only
            # +No exposure: BUY_NO only
            # SELL actions are only for exits (same-leg close)
            if kalshi_side == "BUY_YES":
                net_exposure = "+Yes"
            elif kalshi_side == "BUY_NO":
                net_exposure = "+No"
            elif kalshi_side in ("SELL_YES", "SELL_NO"):
                # SELL actions are only for exits - reject as entry
                logger.error(
                    "[DIRECTION-POLICY-BREACH] ticker=%s kalshi_side=%s is a SELL action, which is only allowed for exits. "
                    "Entry orders must use BUY actions (BUY_YES or BUY_NO). Rejecting candidate.",
                    ticker, kalshi_side
                )
                return False
            else:
                net_exposure = "unknown"

            # Assert invariant: intent must match exposure
            if strategy_intent == "bullish_event":
                assert net_exposure == "+Yes", (
                    f"[STRATEGY-INTENT-VIOLATION] BULLISH_EVENT requires +Yes exposure, "
                    f"but got {net_exposure} for ticker={ticker} side={side_raw} action={action_raw} kalshi_side={kalshi_side}"
                )
                logger.info(
                    "[STRATEGY-INTENT-VALIDATION] ticker=%s intent=BULLISH_EVENT exposure=%s kalshi_side=%s ✓",
                    ticker, net_exposure, kalshi_side
                )
            elif strategy_intent == "bearish_event":
                assert net_exposure == "+No", (
                    f"[STRATEGY-INTENT-VIOLATION] BEARISH_EVENT requires +No exposure, "
                    f"but got {net_exposure} for ticker={ticker} side={side_raw} action={action_raw} kalshi_side={kalshi_side}"
                )
                logger.info(
                    "[STRATEGY-INTENT-VALIDATION] ticker=%s intent=BEARISH_EVENT exposure=%s kalshi_side=%s ✓",
                    ticker, net_exposure, kalshi_side
                )
            else:
                logger.debug(
                    "[STRATEGY-INTENT-VALIDATION] ticker=%s intent=%s (neutral/unknown) - skipping exposure check",
                    ticker, strategy_intent
                )
        else:
            logger.debug(
                "[STRATEGY-INTENT-VALIDATION] ticker=%s no strategy_intent in candidate - skipping exposure check",
                ticker
            )
        
        logger.debug("[15M-LOOP] Converted to Kalshi side: %s", kalshi_side)
        
        # DIRECTION POLICY (2026-08-07): Log one-line intent execution summary
        # Entry orders must use BUY actions only (BUY_YES or BUY_NO)
        if strategy_intent:
            if kalshi_side == "BUY_YES":
                net_exposure = "+YES"
            elif kalshi_side == "BUY_NO":
                net_exposure = "+NO"
            else:
                net_exposure = "UNKNOWN"

            logger.info(
                "[INTENT-EXEC] ticker=%s intent=%s exposure=%s kalshi_side=%s action=%s price=%dc",
                ticker, strategy_intent.upper(), net_exposure, kalshi_side, action_raw.lower(), price_cents
            )
        
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
        
        # CRITICAL FIX (2026-08-05): Always compute TP/SL from the single source of truth
        # (resolve_exit_policy) to avoid conflicting exit targets. The global allocator was
        # previously overriding the policy with extremely tight 1c TP targets, causing
        # premature exits and exit-policy discrepancies.
        # Compute TP/SL from exit policy
        # CRITICAL FIX (2026-08-04): A position is always long its own side.
        # Both YES and NO use SL below entry and TP above entry in their own price space.
        # CRITICAL FIX (2026-08-12): TP is either the absolute fee/fair-capped price
        # from resolve_exit_policy or a % of MAX GAIN. No unconditional 5c minimum,
        # no percent-of-entry, and no fixed TP when there is no trusted edge.
        if exit_policy and getattr(exit_policy, "take_profit_enabled", True):
            if getattr(exit_policy, "tp_price_cents", None) is not None:
                take_profit_price_cents = exit_policy.tp_price_cents
                take_profit_r_multiple = exit_policy.tp_r_multiple
            elif exit_policy.tp_r_multiple:
                # Fall back to max-gain fraction only when the policy provided one
                # (this should not happen for edge-based TPs now).
                tp_distance = max(1, int(exit_policy.tp_r_multiple * (100 - price_cents)))
                take_profit_price_cents = min(99, price_cents + tp_distance)
                take_profit_r_multiple = exit_policy.tp_r_multiple
            else:
                take_profit_price_cents = None
                take_profit_r_multiple = None
        else:
            take_profit_price_cents = None
            take_profit_r_multiple = None

        # CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch.
        # When disabled, we keep TP/trailing/ratchet but do not compute or attach a stop-loss.
        stop_loss_enabled = getattr(exit_policy, "stop_loss_enabled", True)
        if not stop_loss_enabled:
            stop_loss_price_cents = None
            logger.info(f"[15M-LOOP] Stop-loss DISABLED for {ticker}: tp={take_profit_price_cents}c sl=None")
        else:
            # CRITICAL FIX: Use fixed cent SL offset instead of absolute price (2026-07-15)
            # exit_policy.sl_cents is an offset (e.g., 5c), not an absolute price
            if exit_policy and exit_policy.sl_cents:
                sl_cents_offset = exit_policy.sl_cents
                stop_loss_price_cents = max(1, price_cents - sl_cents_offset)
            elif exit_policy and exit_policy.sl_r_multiple:
                # Fallback to R-multiple if sl_cents not set (legacy path)
                stop_loss_price_cents = max(1, int(price_cents * (1 - exit_policy.sl_r_multiple)))
            else:
                # Default to 5 cent SL if no policy
                stop_loss_price_cents = max(1, price_cents - 5)
            logger.info(f"[15M-LOOP] Computed TP/SL from exit policy: tp={take_profit_price_cents}c sl={stop_loss_price_cents}c")

        # CRITICAL FIX (2026-08-11): Spread-aware stop viability.  A stop-loss
        # must be wider than the entry-to-liquidation spread plus fees, or it
        # will be immediately triggered by the spread and lock in a round-trip
        # loss.  When this happens, disable the SL for this entry rather than
        # place a deterministic losing bracket.
        if stop_loss_enabled and stop_loss_price_cents is not None:
            yes_bid = candidate.get("yes_bid_cents")
            yes_ask = candidate.get("yes_ask_cents")
            no_bid = candidate.get("no_bid_cents")
            no_ask = candidate.get("no_ask_cents")
            # Derive NO prices from YES if only YES book is available.
            if no_bid is None and yes_ask is not None:
                no_bid = 100 - yes_ask
            if no_ask is None and yes_bid is not None:
                no_ask = 100 - yes_bid

            own_side = side_raw.lower() if isinstance(side_raw, str) else ("yes" if kalshi_side == "BUY_YES" else "no")
            if own_side == "yes":
                own_bid = yes_bid
                own_ask = yes_ask
            else:
                own_bid = no_bid
                own_ask = no_ask

            if own_bid is not None and own_ask is not None and 1 <= own_bid < own_ask <= 99:
                entry_spread_cents = own_ask - own_bid
                fee_buffer = candidate.get("fee_cents") or 2
                min_adverse_move = 1
                required_stop_distance = entry_spread_cents + fee_buffer + min_adverse_move
                planned_stop_distance = price_cents - stop_loss_price_cents
                if planned_stop_distance <= required_stop_distance:
                    try:
                        from merid.position_management.position_monitor import _bump_stop_counter
                        _bump_stop_counter(
                            "entry_stop_rejected_spread_unviable",
                            f"ticker={ticker} side={own_side} price={price_cents} spread={entry_spread_cents} planned={planned_stop_distance} required={required_stop_distance}",
                        )
                    except Exception:
                        pass
                    logger.critical(
                        "[STOP-VIABILITY-GUARD] ticker=%s side=%s price=%dc own_ask=%dc own_bid=%dc "
                        "spread=%dc planned_sl=%dc planned_distance=%dc required=%dc - "
                        "stop is inside round-trip crossing cost; disabling SL",
                        ticker, own_side, price_cents, own_ask, own_bid,
                        entry_spread_cents, stop_loss_price_cents,
                        planned_stop_distance, required_stop_distance,
                    )
                    stop_loss_enabled = False
                    stop_loss_price_cents = None

        # Generate unique trace_id for candidate → order → policy tracking
        import uuid
        trace_id = str(uuid.uuid4())[:8]
        candidate["trace_id"] = trace_id

        # PRE-SEND ASSERT: Ensure order price is within canonical entry range 10-75c.
        if not (min_price_cents <= price_cents <= max_price_cents):
            logger.error(
                "[PRE-SEND-ASSERT-FAILED] trace_id=%s price_cents=%d outside dynamic price_range [%d,%d] ticker=%s side=%s edge_pct=%s "
                "candidate_price_cents=%s source=%s time_to_expiry=%ds",
                trace_id, price_cents, min_price_cents, max_price_cents, ticker, kalshi_side, edge_pct,
                candidate.get("price_cents", "N/A"), "merid.prediction.agent_grid_15m", time_to_expiry_sec
            )
            raise AssertionError(f"Order price {price_cents}c outside dynamic price_range [{min_price_cents},{max_price_cents}] for ticker={ticker}")

        # CRITICAL FIX: Removed hardcoded count=1 assertion
        # The sizing calculation (compute_order_size) now determines count based on edge, confidence, and $1 cap
        # Global slot allocator enforces $1 exposure cap, so this assertion is redundant
        # Allow sizing calculation to determine optimal position size within risk limits
        
        # CRITICAL FIX: Use aggressiveness from candidate (set by signal generation)
        # Removed redundant aggressiveness calculation since signal generation now computes it
        # CRITICAL FIX 2026-08-09: Default missing aggressiveness to full taker (1.0)
        # so momentum_fvg and other signal modes still reach the book as IOC/marketable.
        aggressiveness = float(candidate.get("aggressiveness", 1.0) or 0.0)
        logger.info(
            "[15M-LOOP] Using aggressiveness from candidate: ticker=%s aggressiveness=%.2f",
            ticker, aggressiveness
        )
        
        # CRITICAL FIX (2026-07-27): model_prob is SIDE-SPECIFIC (P(YES) for YES candidates,
        # P(NO) for NO candidates). The microstructure gate expects p_hat_yes_cents to be the
        # CANONICAL YES probability. Without this conversion, NO orders had their model view
        # inverted (e.g. P(NO)=0.81 was stored as p_hat_yes=81c, so the gate valued NO at
        # 100-81=19c and rejected every NO order with a huge negative executable edge).
        model_prob_yes_canonical = model_prob
        if model_prob is not None and (isinstance(side_raw, str) and side_raw.upper() == "NO"):
            model_prob_yes_canonical = 1.0 - model_prob

        # CRITICAL FIX (2026-08-02): Use unified probability model integration
        # This addresses high-leverage bugs #1, #2, #7 (probability model issues)
        if PROBABILITY_MODEL_INTEGRATION_AVAILABLE:
            # Validate probability model consistency
            is_valid, prob_error = validate_probability_model_consistency(candidate, ticker)
            if not is_valid:
                logger.warning("[15M-LOOP] Probability model consistency check failed: %s - rejecting candidate", prob_error)
                return False
            
            # Enrich candidate with validated BinaryProbability model
            is_valid, enrich_error = enrich_intent_with_binary_probability(candidate, ticker)
            if not is_valid:
                logger.warning("[15M-LOOP] Failed to enrich candidate with probability model: %s - rejecting candidate", enrich_error)
                return False
            
            # Use validated probability model for p_hat fields
            # CRITICAL FIX 2026-08-02: Ensure probability interpretation matches router expectations
            # Router expects p_hat_yes_cents as YES outcome probability (canonical YES-space)
            # Signal layer calculates model_prob as probability of TRADE-WINNING outcome
            # For YES orders: model_prob is YES outcome prob, so p_hat_yes_cents = model_prob * 100
            # For NO orders: model_prob is NO outcome prob, so p_hat_yes_cents = (1 - model_prob) * 100
            # We already have model_prob_yes_canonical which does this conversion for NO orders
            if "_binary_probability" in candidate:
                prob = candidate["_binary_probability"]
                # Use canonical YES-space probability for router consistency
                # model_prob_yes_canonical is already YES-space for both YES and NO orders
                p_hat_yes_cents = model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
                p_hat_no_cents = (100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
                logger.info(
                    "[15M-LOOP] Using validated probability model: ticker=%s side=%s model_prob_yes_canonical=%.3f p_hat_yes=%.1fc p_hat_no=%.1fc",
                    ticker, kalshi_side, model_prob_yes_canonical, p_hat_yes_cents, p_hat_no_cents
                )
            else:
                # Fallback to legacy method using canonical YES-space probability
                p_hat_yes_cents = model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
                p_hat_no_cents = (100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
        else:
            # Legacy method without probability model integration
            # Use canonical YES-space probability for router consistency
            p_hat_yes_cents = model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
            p_hat_no_cents = (100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None

        # CRITICAL FIX 2026-08-02: Update candidate trace with canonical probability conversion
        if CANDIDATE_TRACE_AVAILABLE and candidate.get("candidate_id"):
            try:
                candidate_id = candidate["candidate_id"]
                trace_store = get_trace_store()
                existing_trace = trace_store.get_trace(candidate_id)
                if existing_trace:
                    # Create new trace with updated fields (frozen dataclass requires new instance)
                    updated_trace = CandidateTrace(
                        candidate_id=existing_trace.candidate_id,
                        signal_timestamp=existing_trace.signal_timestamp,
                        signal_model_prob=existing_trace.signal_model_prob,
                        signal_side=existing_trace.signal_side,
                        signal_edge_pct=existing_trace.signal_edge_pct,
                        canonical_yes_prob=model_prob_yes_canonical,
                        canonical_no_prob=1.0 - model_prob_yes_canonical if model_prob_yes_canonical is not None else None,
                        allocator_timestamp=time.time(),
                        chosen_side=TraceSide.YES if (isinstance(side_raw, str) and side_raw.upper() == "YES") else TraceSide.NO,
                        chosen_edge_pct=edge_pct,
                        policy_timestamp=existing_trace.policy_timestamp,
                        policy_intended_role=existing_trace.policy_intended_role,
                        economics_mode=existing_trace.economics_mode,
                        aggressiveness=existing_trace.aggressiveness,
                        microstructure_timestamp=existing_trace.microstructure_timestamp,
                        yes_bid_cents=existing_trace.yes_bid_cents,
                        no_bid_cents=existing_trace.no_bid_cents,
                        order_price_cents=existing_trace.order_price_cents,
                        spread_cents=existing_trace.spread_cents,
                        fee_cents=existing_trace.fee_cents,
                        raw_edge_cents=existing_trace.raw_edge_cents,
                        executable_edge_cents=existing_trace.executable_edge_cents,
                        router_timestamp=existing_trace.router_timestamp,
                        execution_timestamp=existing_trace.execution_timestamp,
                        terminal_state=existing_trace.terminal_state,
                        terminal_reason=existing_trace.terminal_reason,
                        ticker=ticker,
                        asset=asset,
                        metadata={**existing_trace.metadata, "stage": "allocator"}
                    )
                    trace_store.add_trace(updated_trace)
                    logger.info(
                        "[CANDIDATE-TRACE] Updated trace with canonical probability: candidate_id=%s canonical_yes=%.3f canonical_no=%.3f",
                        candidate_id, model_prob_yes_canonical, 1.0 - model_prob_yes_canonical if model_prob_yes_canonical is not None else None
                    )
            except Exception as trace_exc:
                logger.warning("[CANDIDATE-TRACE] Failed to update trace with canonical probability: %s", trace_exc)

        # CRITICAL FIX 2026-08-09: Resolve execution parameters as the final source of
        # truth before constructing the canonical OrderIntent.  Aggressiveness=0 -> maker
        # GTC, 0 < aggressiveness < 1 -> staged IOC taker, >= 1 -> full taker IOC.
        if aggressiveness <= 0.0:
            resolved_time_in_force = candidate.get("time_in_force", "gtc")
            resolved_execution_mode = candidate.get("execution_mode") or "maker"
            resolved_liquidity_role = "maker"
        elif aggressiveness >= 1.0:
            resolved_time_in_force = candidate.get("time_in_force", "ioc")
            resolved_execution_mode = candidate.get("execution_mode") or "taker"
            resolved_liquidity_role = "taker"
        else:
            resolved_time_in_force = candidate.get("time_in_force", "ioc")
            resolved_execution_mode = candidate.get("execution_mode") or "staged_ioc"
            resolved_liquidity_role = "taker"
        resolved_post_only = bool(candidate.get("post_only", False)) and aggressiveness == 0.0

        intent = OrderIntent(
            ticker=ticker,
            exchange_index=candidate.get("exchange_index"),
            side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
            action=action_raw,  # Keep as lowercase "buy"/"sell" for early validation
            price_cents=price_cents,  # BUG #2 FIX: Add required price_cents field
            count=count,  # CRITICAL FIX: Use count from sizing calculation instead of hardcoded 1
            source="merid.prediction.agent_grid_15m",  # Use 'source' instead of 'caller_module'
            agent_id=agent_id,  # CRITICAL: Pass actual agent_id for authorization
            edge_pct=edge_pct,  # BUG #34 FIX: Add edge_pct from candidate
            edgepct=edge_pct,  # PHASE 3 FIX: Populate edgepct for fills ledger audit trail
            # CRITICAL FIX (2026-08-12): netedgecents is the model edge in CENTS,
            # i.e. (P_true - P_market) * 100, not edge_pct * price_cents / 100.
            netedgecents=edge_cents if edge_cents is not None else 0.0,  # gross model edge in cents
            # CRITICAL FIX (2026-08-19): propagate decision provenance into OrderIntent.
            decision_id=candidate.get("decision_id"),
            decision_trace_id=candidate.get("decision_id"),
            run_id=candidate.get("run_id"),
            confidence=confidence,  # BUG #34 FIX: Add confidence from candidate
            confidence_valid=confidence_valid,
            confidence_source=confidence_source,
            settlement_reference=settlement_reference,
            data_state=candidate.get("data_state"),
            regime_label=candidate.get("regime_label"),
            regime_probability=candidate.get("regime_probability"),
            # CRITICAL FIX (2026-08-19): propagate economic provenance for fill-adjusted edge.
            p_yes=candidate.get("p_yes"),
            p_no=candidate.get("p_no"),
            p_selected=candidate.get("p_selected"),
            gross_edge=candidate.get("gross_edge"),
            net_edge_pretrade=candidate.get("net_edge"),
            selected_outcome_price_cents=candidate.get("selected_outcome_price"),
            model_prob=model_prob,  # BUG #34 FIX: Add model_prob from candidate
            # 2026-07-25: Dual-side edge-aware microstructure gate - populate both p_hat fields
            # 2026-07-27: p_hat fields are CANONICAL (YES-space), derived from side-specific model_prob above
            # 2026-08-02: Use validated probability model if available, otherwise legacy method
            # CRITICAL FIX 2026-08-02: p_hat_yes_cents is always YES outcome probability (router canonical)
            # For NO orders, we inverted model_prob to YES-space above to match router expectations
            p_hat_yes_cents=p_hat_yes_cents,  # YES outcome probability (router canonical)
            p_hat_no_cents=p_hat_no_cents,  # NO outcome probability (for logging/debugging)
            rationale=candidate.get("rationale"),  # CRITICAL: Pass rationale to skip edge validation for price-based strategy
            trace_id=trace_id,  # DEBUG: Add trace_id for candidate → order → policy tracking
            # Phase 2: Strategy identification for multi-strategy support
            strategy_id="heuristic_velocity",  # From profile strategies section
            strategy_type="heuristic_velocity",  # From profile strategies section
            regime=regime,  # Regime computed from market state (lines 2689-2717)
            # CRITICAL FIX 2026-07-29: Add execution mode for regime-based routing
            # 2026-08-09: Use resolved execution parameters (final source of truth)
            execution_mode=resolved_execution_mode,
            liquidity_role=resolved_liquidity_role,
            time_in_force=resolved_time_in_force,
            # Phase 5.4: Raw logit for probability calibration outcome recording
            raw_logit=raw_logit,
            # CRITICAL FIX: Use order_type from candidate (set by signal generation)
            order_type=candidate.get("order_type", "limit"),  # Default to limit
            # CRITICAL FIX: Use post_only from candidate (set by signal generation)
            # 2026-08-09: post_only only honored for true resting orders
            post_only=resolved_post_only,
            # CRITICAL FIX: Use aggressiveness from candidate (set by signal generation)
            # 2026-08-09: resolved above, defaulting to taker/IOC for missing values
            aggressiveness=aggressiveness,
            # CRITICAL FIX: Add client_tag for TP/SL registration with position cache
            client_tag=client_tag,
            # CRITICAL FIX: Add exit targets from resolved exit policy
            take_profit_price_cents=take_profit_price_cents,
            take_profit_r_multiple=take_profit_r_multiple,
            stop_loss_price_cents=stop_loss_price_cents,
            stop_loss_enabled=stop_loss_enabled,
            # CRITICAL FIX (2026-08-12): Carry the model's estimated fair probability
            # and market probability into the position monitor for edge-decay and audit.
            entry_model_probability=float(model_prob) if model_prob is not None else None,
            entry_market_probability=price_cents / 100.0 if price_cents > 0 else None,
            entry_edge=(float(model_prob) - price_cents / 100.0) if (model_prob is not None and price_cents > 0) else None,
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
            # CRITICAL FIX (2026-07-31): Add entry_or_exit field for entry/exit direction contract
            entry_or_exit=entry_or_exit,
            pre_position_size=pre_position_size if entry_or_exit == "exit" else 0,
            expected_post_position_size=expected_post_position_size if entry_or_exit == "exit" else count,
            # Phase 1: Add market microstructure data for fee-aware edge and microstructure gates
            yes_bid_cents=candidate.get("yes_bid_cents"),
            yes_ask_cents=candidate.get("yes_ask_cents"),
            no_bid_cents=candidate.get("no_bid_cents"),
            no_ask_cents=candidate.get("no_ask_cents"),
            yes_depth=candidate.get("yes_depth"),
            no_depth=candidate.get("no_depth"),
            # 2026-08-01: Add FLB position sizing multiplier for FLB-aware position sizing
            flb_position_multiplier=candidate.get("flb_position_multiplier", 1.0),
            # 2026-08-11: Single-source-of-truth economics and settlement telemetry.
            all_in_cost_cents=candidate.get("all_in_cost_cents"),
            ev_net_cents=candidate.get("ev_net_cents"),
            fee_cents=candidate.get("fee_cents"),
            slippage_cents=candidate.get("slippage_cents"),
            time_to_expiry_seconds=candidate.get("time_to_expiry_seconds"),
            settlement_input_price=candidate.get("settlement_input_price"),
            cf_rti_basis=candidate.get("cf_rti_basis"),
            is_counter_trend=candidate.get("is_counter_trend", False),
            thesis_side=candidate.get("thesis_side"),
            strategy_intent=candidate.get("strategy_intent"),
            # CRITICAL FIX (2026-08-19): carry the decision edge threshold for
            # fill-adjusted edge gating.
            min_required_edge=candidate.get("min_required_edge"),
        )

        # CRITICAL FIX 2026-08-20: order identity contract requires process_id and reason.
        intent.process_id = str(os.getpid())
        intent.reason = candidate.get("rationale") or "candidate_entry"

        logger.info(
            "[ORDER-INTENT-CREATED] trace_id=%s candidate_id=%s ticker=%s side=%s action=%s "
            "price_cents=%d count=%d edge_pct=%.6f source=%s",
            trace_id,
            candidate.get("candidate_id"),
            ticker,
            kalshi_side,
            action_raw,
            price_cents,
            count,
            float(edge_pct) if edge_pct is not None else 0.0,
            agent_id,
        )

        # CRITICAL DIAGNOSTIC: Log exit_policy_id being set
        logger.info("[15M-LOOP] Setting exit_policy_id=%s for ticker=%s (exit_policy=%s)",
                   intent.exit_policy_id,
                   ticker,
                   "present" if exit_policy else "None")

        # DIRECTION POLICY (2026-08-07): Mandatory event record at loop boundary
        # Log the canonical direction policy record for auditability
        from merid.event_venues.kalshi.binary_price_space import parse_kalshi_side
        outcome_side, _ = parse_kalshi_side(kalshi_side)
        logger.info(
            "[DIRECTION-POLICY-RECORD] trace_id=%s ticker=%s lifecycle=%s outcome_side=%s action=%s "
            "kalshi_side=%s price_cents=%d count=%d position_before=%d position_after_expected=%s",
            getattr(intent, 'trace_id', 'unknown'),
            ticker,
            entry_or_exit,
            outcome_side,
            action_raw.lower(),
            kalshi_side,
            price_cents,
            count,
            pre_position_size,
            expected_post_position_size
        )
        
        # LIFECYCLE-ENTRY CANONICAL LOG SCHEMA (machine-parseable, single line)
        # Contract: indicator_side in {yes,no}; entry_action == buy; thesis_side == indicator_side;
        # kalshi_side == BUY_YES iff thesis_side==yes, BUY_NO iff thesis_side==no.
        # Populate per-side edges from model_prob for dual-side visibility
        edge_yes_val = model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
        edge_no_val = (100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
        logger.info(
            "[LIFECYCLE-ENTRY] asset=%s ticker=%s agent_id=%s indicator_side=%s edge_yes=%.2f edge_no=%.2f "
            "edge_pct=%.4f thesis_side=%s entry_action=%s kalshi_side=%s price_cents=%d count=%d "
            "strategy_intent=%s entry_or_exit=%s",
            asset,
            ticker,
            agent_id,
            side_raw.lower(),
            edge_yes_val if edge_yes_val is not None else 0.0,
            edge_no_val if edge_no_val is not None else 0.0,
            edge_pct if edge_pct is not None else 0.0,
            side_raw.lower(),
            action_raw.lower(),
            kalshi_side,
            price_cents,
            count,
            strategy_intent or "entry",  # Default to "entry" if None
            entry_or_exit  # Use actual entry_or_exit value
        )
        
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
        
        # CRITICAL: Yes/No Parity Check before order submission
        # This ensures Yes/No intent, prices, and orders are internally consistent
        # per Kalshi's market framing and prevents side mapping bugs
        # CRITICAL FIX: 2026-08-02 - Separate edge threshold check from parity validation
        # Edge threshold: Is the opportunity strong enough? (select_winner_side)
        # Parity validation: Is the market directionally symmetric / disallowed? (parity checker)
        # Precedence: Edge threshold first, then parity validation if edge passes
        parity_blocked = False
        is_winner_mismatch = False  # CRITICAL FIX: 2026-08-02 - Initialize flag
        edge_threshold_passed = False  # CRITICAL FIX: 2026-08-02 - Track edge threshold separately
        try:
            from merid.validation.yes_no_parity_checker import (
                YesNoParityChecker,
                MarketSnapshot,
                BotView,
                ExecutionDecision,
                ExposureIntent,
                IntendedAction,
                get_parity_checker,
                get_parity_metrics,
            )
            from merid.prediction.canonical_edge import (
                CENTS_EDGE_GATE_ENABLED,
                compute_canonical_edges,
                required_edge_cents,
                select_winner_side,
                validate_price_parity,
            )

            # The canonical asset was already resolved at the top of _execute_candidate;
            # re-use it here so fee/liquidity buffers are applied to the right asset.

            # Get orderbook data for market snapshot
            yes_bid = None
            yes_ask = None
            no_bid = None
            no_ask = None
            market_price_yes = None
            market_price_no = None
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                state_store = get_kalshi_market_state_store()
                if state_store:
                    market_state = state_store.get(ticker)
                    if market_state:
                        yes_bid = getattr(market_state, 'best_bid_cents', None)
                        yes_ask = getattr(market_state, 'best_ask_cents', None)
                        # Derive NO prices from YES prices using Kalshi duality
                        if yes_bid is not None:
                            no_ask = 100 - yes_bid
                        if yes_ask is not None:
                            no_bid = 100 - yes_ask
                        # Use mid-price for edge computation if available
                        if yes_bid is not None and yes_ask is not None:
                            market_price_yes = (yes_bid + yes_ask) / 2.0 / 100.0  # Convert cents to fraction
                        if no_bid is not None and no_ask is not None:
                            market_price_no = (no_bid + no_ask) / 2.0 / 100.0  # Convert cents to fraction
            except Exception as ob_err:
                logger.debug("[15M-LOOP] Failed to get market state for parity check: %s", ob_err)
            
            # CRITICAL FIX: 2026-07-20 - Use canonical edge computation
            # Compute edges using canonical formula instead of deriving from kalshi_side
            # This fixes the bug where chosen_side was derived from order side instead of edge comparison
            # CRITICAL FIX: 2026-07-26 - Convert model_prob to canonical YES probability
            # model_prob is side-specific: P(YES) for YES candidates, P(NO) for NO candidates
            # compute_canonical_edges expects canonical YES probability (P(YES))
            model_prob_yes = model_prob
            if side_raw.lower() == "no":
                # For NO candidates, model_prob is P(NO), convert to P(YES) = 1 - P(NO)
                model_prob_yes = 1.0 - model_prob if model_prob is not None else None
            
            if market_price_yes is not None or market_price_no is not None:
                logger.info(
                    "[PARITY-BLOCK-DIAG] ticker=%s side=%s model_prob=%.4f model_prob_yes=%.4f market_yes=%.4f market_no=%.4f candidate_price=%dc edge_pct=%.4f",
                    ticker, side_raw.lower(), model_prob, model_prob_yes, market_price_yes, market_price_no, price_cents, edge_pct
                )
                edge_yes, edge_no = compute_canonical_edges(
                    model_prob_yes=model_prob_yes,
                    market_price_yes=market_price_yes,
                    market_price_no=market_price_no,
                )
                logger.info(
                    "[PARITY-BLOCK-EDGE-DIAG] ticker=%s computed edge_yes=%.4f edge_no=%.4f (from orderbook)",
                    ticker, edge_yes, edge_no
                )
            else:
                # Fallback to candidate edges if orderbook unavailable
                logger.warning("[PARITY-BLOCK] Orderbook unavailable for ticker=%s, using candidate edges", ticker)
                # CRITICAL FIX: 2026-07-26 - Use canonical YES probability for fallback edge calculation
                edge_yes = candidate.get("edge_yes", edge_pct / 100.0)
                # For NO candidates, derive edge_no from canonical YES probability
                if side_raw.lower() == "no":
                    # model_prob is P(NO), convert to P(YES) for canonical edge computation
                    fallback_model_prob_yes = 1.0 - model_prob if model_prob is not None else None
                    edge_no = candidate.get("edge_no", fallback_model_prob_yes - (1.0 - price_cents / 100.0) if fallback_model_prob_yes is not None else 0.0)
                else:
                    edge_no = candidate.get("edge_no", (1.0 - model_prob) - (1.0 - price_cents / 100.0) if model_prob else 0.0)
            
            # CRITICAL FIX: 2026-08-26 - Cents-based, fee-aware edge threshold.
            # A flat fractional threshold is the wrong instrument for Kalshi contracts:
            # 1% = 1 cent and the taker fee is price-dependent.  The threshold depends
            # on the actual side price, role, observable spread, fee and asset.
            #
            # Set MERID_ENABLE_CENTS_EDGE_GATE=0 to fall back to the legacy flat-fraction
            # threshold in an emergency.
            if CENTS_EDGE_GATE_ENABLED:
                yes_price_cents = int((yes_bid + yes_ask) / 2.0) if yes_bid is not None and yes_ask is not None else 50
                no_price_cents = int((no_bid + no_ask) / 2.0) if no_bid is not None and no_ask is not None else 50
                yes_spread = max(0, yes_ask - yes_bid) if yes_bid is not None and yes_ask is not None else None
                no_spread = max(0, no_ask - no_bid) if no_bid is not None and no_ask is not None else None

                min_edge_yes_cents = required_edge_cents(
                    price_cents=yes_price_cents,
                    liquidity_role=resolved_liquidity_role,
                    asset=asset,
                    spread_cents=yes_spread,
                )
                min_edge_no_cents = required_edge_cents(
                    price_cents=no_price_cents,
                    liquidity_role=resolved_liquidity_role,
                    asset=asset,
                    spread_cents=no_spread,
                )
                min_edge_yes = min_edge_yes_cents / 100.0
                min_edge_no = min_edge_no_cents / 100.0

                logger.debug(
                    "[15M-LOOP] Fee-aware edge threshold: ticker=%s role=%s asset=%s "
                    "yes_price=%dc yes_required=%dc yes_frac=%.4f "
                    "no_price=%dc no_required=%dc no_frac=%.4f",
                    ticker, resolved_liquidity_role, asset,
                    yes_price_cents, min_edge_yes_cents, min_edge_yes,
                    no_price_cents, min_edge_no_cents, min_edge_no,
                )

                chosen_side = select_winner_side(
                    edge_yes, edge_no, min_edge_yes=min_edge_yes, min_edge_no=min_edge_no
                )
            else:
                # Legacy flat-fraction fallback (emergency revert)
                base_min_edge = 0.015  # Default to YAML value (1.5%) instead of 2%
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile
                    profile_adapter = get_active_profile()
                    if profile_adapter and hasattr(profile_adapter, 'profile'):
                        profile = profile_adapter.profile
                        if hasattr(profile, 'guardrails'):
                            base_min_edge = profile.guardrails.get('min_post_fee_edge', 0.015)
                except Exception as edge_err:
                    logger.debug("[15M-LOOP] Failed to get min_edge from profile: %s", edge_err)

                time_to_expiry_sec = candidate.get("time_to_expiry_sec", 900)
                min_edge = max(base_min_edge, 0.005)
                logger.debug(
                    "[15M-LOOP] Dynamic edge threshold (legacy): time_to_expiry=%ds base_min_edge=%.4f -> dynamic_min_edge=%.4f",
                    time_to_expiry_sec, base_min_edge, min_edge
                )
                chosen_side = select_winner_side(edge_yes, edge_no, min_edge=min_edge)
                min_edge_yes = min_edge
                min_edge_no = min_edge

            # A single display threshold for the rest of the pipeline logs.
            if chosen_side == "yes":
                min_edge = min_edge_yes
            elif chosen_side == "no":
                min_edge = min_edge_no
            else:
                min_edge = (min_edge_yes + min_edge_no) / 2.0

            # CRITICAL FIX: 2026-08-02 - Separate edge threshold check from parity validation
            # Edge threshold: Is the opportunity strong enough?
            # If chosen_side == "none", this is an edge threshold failure, NOT a parity failure
            if chosen_side == "none":
                edge_threshold_passed = False
                logger.warning(
                    "[15M-LOOP] EDGE THRESHOLD FAILED: ticker=%s edge_yes=%.4f edge_no=%.4f "
                    "yes_required=%.4f no_required=%.4f - NO TRADE",
                    ticker, edge_yes, edge_no, min_edge_yes, min_edge_no
                )
                # Skip parity validation if edge threshold failed (no point checking parity)
                # This is handled by the edge_threshold_passed flag below
            else:
                edge_threshold_passed = True
                logger.debug(
                    "[15M-LOOP] EDGE THRESHOLD PASSED: ticker=%s chosen_side=%s edge_yes=%.4f "
                    "edge_no=%.4f chosen_required=%.4f (yes=%.4f no=%.4f)",
                    ticker, chosen_side, edge_yes, edge_no, min_edge, min_edge_yes, min_edge_no
                )
            
            # Derive exposure intent from chosen_side (edge-based, not order-based)
            # Per Kalshi semantics:
            # - YES winner means bullish (event happens)
            # - NO winner means bearish (event does not happen)
            if chosen_side == "yes":
                exposure_intent = ExposureIntent.BULLISH_EVENT
            elif chosen_side == "no":
                exposure_intent = ExposureIntent.BEARISH_EVENT
            else:
                exposure_intent = ExposureIntent.NEUTRAL
            
            # Convert chosen_side to IntendedAction (BUY based on winner)
            if chosen_side == "yes":
                intended_action = IntendedAction.BUY_YES
            elif chosen_side == "no":
                intended_action = IntendedAction.BUY_NO
            else:
                intended_action = IntendedAction.NONE
            
            # CRITICAL FIX: 2026-08-02 - Only run parity validation if edge threshold passed
            # Parity validation answers "is the market directionally symmetric / disallowed?"
            # This should only be checked if the edge is strong enough to trade
            if edge_threshold_passed:
                # Validate price parity if both prices available
                if market_price_yes is not None and market_price_no is not None:
                    if not validate_price_parity(market_price_yes, market_price_no):
                        logger.warning(
                            "[15M-LOOP] PRICE PARITY VIOLATION: ticker=%s yes=%.4f no=%.4f - blocking order",
                            ticker, market_price_yes, market_price_no
                        )
                        parity_blocked = True
                        # CRITICAL FIX: 2026-08-02 - Remove counter increment here to avoid double-counting
                        # Counter will be incremented once at final decision point (line 6392)
                
                # Create parity check data structures
                market_snapshot = MarketSnapshot(
                    market_id=ticker,
                    asset=asset,
                    expiry_ts=int(candidate.get("expiry_ts", 0)),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                )
                
                bot_view = BotView(
                    model_prob_yes=model_prob_yes_canonical,
                    model_prob_no=(1.0 - model_prob_yes_canonical) if model_prob_yes_canonical is not None else None,
                    edge_yes=edge_yes,
                    edge_no=edge_no,
                    chosen_side=chosen_side,
                    exposure_intent=exposure_intent,
                )
                
                execution_decision = ExecutionDecision(
                    intended_action=intended_action,
                    api_side=chosen_side,
                    api_yes_price=price_cents / 100.0 if chosen_side == "yes" else None,
                    api_no_price=price_cents / 100.0 if chosen_side == "no" else None,
                )
                
                # Run parity check
                checker = get_parity_checker()
                parity_result = checker.check(market_snapshot, bot_view, execution_decision)
                
                # Record metrics
                metrics = get_parity_metrics()
                metrics.record_evaluated()
                
                # CRITICAL FIX: 2026-07-20 - Make parity check BLOCKING for winner mismatches
                # CRITICAL FIX: 2026-08-02 - Initialize is_winner_mismatch flag
                is_winner_mismatch = False
                if not parity_result.ok:
                    metrics.record_failure(parity_result)
                    checker.log_failure(parity_result, cycle_id=f"15m_{ticker}", logger=logger)

                    # Check if failure is WINNER_MISMATCH - this is a critical bug
                    is_winner_mismatch = any("WINNER_MISMATCH" in reason for reason in parity_result.reasons)
                    if is_winner_mismatch:
                        parity_blocked = True
                        # CRITICAL FIX: 2026-08-02 - Remove counter increment here to avoid double-counting
                        # Counter will be incremented once at final decision point (line 6397)
                        logger.error(
                            "[15M-LOOP] PARITY BLOCKED (WINNER_MISMATCH): ticker=%s chosen_side=%s edge_yes=%.4f edge_no=%.4f reasons=%s - ORDER REJECTED",
                            ticker, chosen_side, edge_yes, edge_no, parity_result.reasons
                        )
                    else:
                        logger.warning(
                            "[15M-LOOP] PARITY CHECK FAILED (non-blocking): ticker=%s side=%s reasons=%s",
                            ticker, kalshi_side, parity_result.reasons
                        )
                else:
                    logger.debug(
                        "[15M-LOOP] PARITY CHECK PASSED: ticker=%s chosen_side=%s edge_yes=%.4f edge_no=%.4f",
                        ticker, chosen_side, edge_yes, edge_no
                    )
            else:
                # Edge threshold failed - skip parity validation
                logger.debug(
                    "[15M-LOOP] Skipping parity validation due to edge threshold failure: ticker=%s",
                    ticker
                )
                
        except Exception as parity_err:
            logger.warning("[15M-LOOP] Parity check failed (non-critical): %s", parity_err)
        
        # CRITICAL FIX: 2026-08-02 - Separate edge threshold from parity blocking
        # Edge threshold failure should be handled separately from parity validation
        if not edge_threshold_passed:
            # Edge threshold failed - this is NOT a parity block
            self._rejection_counters["parity_edge_threshold"] += 1
            # CRITICAL FIX: 2026-08-02 - Log lifecycle event for edge threshold failure
            candidate_id = candidate.get("candidate_id", f"unknown-{int(time.time()*1000)}")
            self._log_candidate_lifecycle_event(
                candidate_id=candidate_id,
                from_state="RECEIVED",
                to_state="BLOCKED_EDGE_THRESHOLD",
                reason="Edge threshold failed (both sides below min_edge)",
                context={"ticker": ticker, "edge_yes": edge_yes, "edge_no": edge_no, "min_edge": min_edge}
            )
            logger.warning(
                "[15M-LOOP] EDGE THRESHOLD BLOCK: ticker=%s edge_yes=%.4f edge_no=%.4f min_edge=%.4f - NO TRADE",
                ticker, edge_yes, edge_no, min_edge
            )
            # Skip routing this order - return to skip this candidate
            return False
        
        # CRITICAL FIX: 2026-07-20 - Skip order if parity blocked
        # CRITICAL FIX: 2026-08-02 - Add detailed rejection reason for debugging
        if parity_blocked:
            self._rejection_counters["parity_blocked"] += 1
            # Determine specific parity block reason for better diagnostics
            block_reason = "unknown"
            if is_winner_mismatch:
                self._rejection_counters["parity_winner_mismatch"] += 1
                block_reason = "winner_mismatch"
                logger.warning("[15M-LOOP] Order skipped due to parity block (winner mismatch): ticker=%s", ticker)
            else:
                self._rejection_counters["parity_price_violation"] += 1
                block_reason = "price_violation"
                logger.warning("[15M-LOOP] Order skipped due to parity block (price violation): ticker=%s", ticker)
            
            # CRITICAL FIX: 2026-08-02 - Log lifecycle event for parity block
            candidate_id = candidate.get("candidate_id", f"unknown-{int(time.time()*1000)}")
            self._log_candidate_lifecycle_event(
                candidate_id=candidate_id,
                from_state="RECEIVED",
                to_state="BLOCKED_PARITY",
                reason=f"Parity check failed: {block_reason}",
                context={"ticker": ticker, "edge_yes": edge_yes, "edge_no": edge_no, "min_edge": min_edge}
            )
            
            # 2026-07-25: Log pipeline trace for blocked candidate
            logger.info(
                "[PIPELINE-TRACE] ticker=%s side=%s canonical_edge_yes=%.4f canonical_edge_no=%.4f min_edge_frac=%.4f decision=BLOCK_REASON=PARITY_BOTH_SIDES_BELOW_THRESHOLD",
                ticker, kalshi_side, edge_yes, edge_no, min_edge
            )
            # Skip routing this order - return to skip this candidate
            return False

        # 2026-07-25: Log pipeline trace for candidate passing all gates before routing
        logger.info(
            "[PIPELINE-TRACE] ticker=%s side=%s canonical_edge_yes=%.4f canonical_edge_no=%.4f min_edge_frac=%.4f decision=PASSED_ALL_GATES",
            ticker, kalshi_side, edge_yes, edge_no, min_edge
        )

        # Route order
        result = await route_order_async(intent)

        # Post-result accounting and audit log.  Risk/position exposure is recorded
        # in the single canonical path inside order_router (_route_live) using the
        # normalized port result.  loop_15m only updates its own lightweight
        # tracking and emits a per-intent audit line.
        executed_quantity_cc = int(result.executed_quantity_cc) if result else 0
        fill_price_cents = int(result.fill.get("price_cents", price_cents)) if (result and result.fill) else price_cents
        executed_notional_usd = (executed_quantity_cc * fill_price_cents) / 10000.0
        remaining_quantity_cc = int(result.remaining_quantity_cc) if result else 0
        executed_count = executed_quantity_cc // 100
        remaining_count = remaining_quantity_cc // 100
        order_id = result.order_id if (result and result.order_id) else None
        client_order_id = getattr(result, "client_order_id", None) or intent.client_order_id or intent.client_tag or None

        logger.info(
            "[15M-LOOP-ORDER-RESULT] ticker=%s side=%s action=%s requested=%d executed=%d remaining=%d "
            "fill_price=%dc order_id=%s client_order_id=%s status=%s has_execution=%s",
            ticker, kalshi_side, action_raw, count, executed_count, remaining_count,
            fill_price_cents, order_id, client_order_id,
            result.status if result else "none", bool(result and result.has_execution)
        )

        if result and result.status == "rejected":
            self._rejection_counters["router_rejected"] += 1
            logger.warning(
                "[ROUTER-REJECTED] trace_id=%s candidate_id=%s ticker=%s side=%s count=%d "
                "reason=%s latency_ms=%s",
                trace_id,
                candidate.get("candidate_id"),
                ticker,
                kalshi_side,
                count,
                result.reason,
                result.latency_ms,
            )
            return False

        if result and result.requires_recovery:
            self._rejection_counters["router_rejected"] += 1
            logger.warning(
                "[ROUTER-REJECTED] trace_id=%s candidate_id=%s ticker=%s side=%s count=%d "
                "reason=%s status=%s latency_ms=%s",
                trace_id,
                candidate.get("candidate_id"),
                ticker,
                kalshi_side,
                count,
                result.reason,
                result.status,
                result.latency_ms,
            )
            return False

        if result and result.status == "unfilled_ioc":
            self._rejection_counters["other"] += 1
            logger.info(
                "[15M-LOOP-SIDE-AWARE] IOC order did not fill: ticker=%s side=%s count=%d status=%s order_id=%s",
                ticker, kalshi_side, count, result.status, result.order_id
            )
            return False

        # Store order_id for edge-improvement cancellation / duplicate suppression.
        if order_id:
            candidate["order_id"] = order_id
            logger.info("[15M-LOOP] Stored order_id=%s in candidate for ticker=%s", order_id, ticker)

        # CRITICAL FIX (2026-08-09): Preserve execution outcome so edge-improvement logic
        # can avoid canceling an already-filled order (causes 404 / circuit breaker trips).
        if result:
            candidate["status"] = result.status
            candidate["has_execution"] = result.has_execution

        # Only actual executions affect loop-level position/trade counters.
        if result and result.has_execution and asset:
            position_notional_usd = executed_notional_usd
            executed_notional_d = Decimal(str(position_notional_usd))
            if action_raw and action_raw.lower() == "sell":
                self._asset_positions[asset] = self._asset_positions.get(asset, Decimal('0.0')) - executed_notional_d
            else:
                self._asset_positions[asset] = self._asset_positions.get(asset, Decimal('0.0')) + executed_notional_d
            self._active_trades[ticker] = self._active_trades.get(ticker, 0) + 1
            logger.info(
                "[15M-LOOP] Position tracking updated: asset=%s exposure=%.2f ticker=%s active_trades=%d executed=%d",
                asset, self._asset_positions[asset], ticker, self._active_trades[ticker], executed_count
            )

        if result and (result.has_execution or (result.request_completed and not result.is_terminal)):
            logger.info("Order routed successfully: ticker=%s status=%s", ticker, result.status)
            return True
        self._rejection_counters["other"] += 1
        return False
        
    except Exception as e:
        self._rejection_counters["router_exception"] += 1
        logger.error("[15M-LOOP] Failed to execute candidate: %s", e, exc_info=True)
        return False  # Execution failed - do not track as executed

async def _run_agents_directly(self, tick: int) -> None:
    # Fallback: run agents directly if run_cycle not implemented.
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
    # Get loop status summary for API/monitoring.
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
        # REMOVED (2026-07-12): per_agent_window_limit_usd and total_venue_window_limit_usd removed
        # These were deprecated window-based risk limits, replaced by fixed $1 slot allocation
        
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


# Backwards-compatible alias used by legacy test suites.

# 2026-08-19: bind methods that were accidentally nested inside _run_exit_price_guard.
Kalshi15mLoop._execute_exit_order = _execute_exit_order
Kalshi15mLoop._rearm_position_after_failed_exit = _rearm_position_after_failed_exit
Kalshi15mLoop._compute_allow_new_entries = _compute_allow_new_entries
Kalshi15mLoop._run_loop = _run_loop
Kalshi15mLoop.stop = stop
Kalshi15mLoop._run_one_cycle = _run_one_cycle
Kalshi15mLoop._run_agent_grid_with_timeout = _run_agent_grid_with_timeout
Kalshi15mLoop._get_candidate_key = _get_candidate_key
Kalshi15mLoop._get_asset_window_key = _get_asset_window_key
Kalshi15mLoop._validate_candidate_edge = _validate_candidate_edge
Kalshi15mLoop._execute_candidate = _execute_candidate
Kalshi15mLoop._run_agents_directly = _run_agents_directly
Kalshi15mLoop.summary = summary

Loop15M = Kalshi15mLoop


def get_kalshi_15m_loop(
    agent_grid: Any,
    bankroll_service: Any,
    risk_config: Any,
    cadence_seconds: float = 5.0,
    catalog: Any = None,
    ws_bridge: Any = None,
) -> Kalshi15mLoop:
    # Factory function to create/get the Kalshi15mLoop singleton.
    # This is the canonical way to get the loop instance for the 15m profile.
    # NOTE: venue_adapter removed - it was dead code (TradingAgent bypasses it via route_order_async)
    return Kalshi15mLoop(
        agent_grid=agent_grid,
        bankroll_service=bankroll_service,
        risk_config=risk_config,
        cadence_seconds=cadence_seconds,
        catalog=catalog,
        ws_bridge=ws_bridge,
    )

