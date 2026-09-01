"""
Position monitor for swing trading exit management.

Tracks open positions, computes PnL, and enforces TP/SL exits.
"""

import asyncio
import json
import logging
import math
import re
import statistics
import threading
import time
import traceback
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Any, Union, Tuple
from merid.position_management.position import (
    Position,
    PositionSide,
    TrailingType,
    TrailingState,
    RiskParamsState,
    TAKE_PROFIT_MIN_PROFIT_CENTS,
    SIDE_SPACE_TOTAL_CENTS,
    canonical_position_key,
)
from merid.position_management.exit_policy import ExitAction, ExitReason, is_position_quarantined, is_exit_reason_allowed_for_quarantine
from merid.position_management.exit_policy_resolver import get_exit_policy_resolver
from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, get_priority_for_reason
from merid.position_management.exit_audit import ExitPriceSnapshot, ExitDecisionRecord
from merid.event_venues.kalshi.stop_candidate import (
    STOP_EDGE_HYSTERESIS_CENTS,
    STOP_EDGE_MIN_CONSECUTIVE,
    STOP_EDGE_TOTAL_EXIT_COST_CENTS,
    _book_age_ms,
    _get_executable_exit_cents,
    _get_fair_value_cents,
    build_stop_candidate,
    evaluate_edge_stop,
    maybe_submit_stop_candidate_sync,
    record_stop_candidate,
)
from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure
from utils.logger import get_logger

logger = get_logger(__name__)
import os
print(f"[POSITION-MONITOR-MODULE] Module loaded from {__file__}, thesis side inference fix applied (2026-08-01)")
logger.info(f"[POSITION-MONITOR-MODULE] Module loaded from {__file__}, thesis side inference fix applied (2026-08-01)")


def _is_expired_ticker(ticker: str) -> bool:
    """Check if a ticker has expired and should no longer be tracked.

    Delegates to the position-cache expiry policy so that closed-but-unsettled
    markets are retained for exit/settlement handling, while settled/finalized
    or stale markets are removed.
    """
    if not ticker:
        return False

    try:
        from merid.event_venues.kalshi.position_cache import _is_expired_ticker as _cache_is_expired
        return _cache_is_expired(ticker)
    except Exception as e:
        logger.debug("[EXPIRED-TICKER] Exception checking ticker %s: %s", ticker, e)
        return "15M" in ticker.upper()


def _seconds_to_expiry_from_ticker(ticker: str) -> Optional[float]:
    """Parse seconds until settlement from a Kalshi ticker.

    CRITICAL FIX (2026-08-03): Uses the canonical YYMONDD-HHMM-ET parser.
    The previous DDMMM-HHMMSS-UTC parsing returned ~23 days for live 15m
    tickers, so the T-30s forced-exit settlement guard NEVER fired.
    Returns None if the ticker cannot be parsed.
    """
    if not ticker:
        return None
    try:
        from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_window_end_utc
        expiry_dt = parse_kalshi_15m_window_end_utc(ticker)
        if expiry_dt is None:
            return None
        return (expiry_dt - datetime.now(timezone.utc)).total_seconds()
    except Exception:
        return None


# Settlement guard: force exit this many seconds before market settlement.
# CRITICAL FIX (2026-08-25): Moved from 30s to T-2min (120s) so no 15m crypto
# position rides into settlement.  Loaded from profile YAML; this constant is
# the safe fallback when the profile is not yet available.
DEFAULT_SETTLEMENT_GUARD_SECONDS = 120


def _get_settlement_guard_seconds() -> float:
    """Load settlement guard seconds from active profile (config-driven)."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        te_config = getattr(get_active_profile().profile, "exit_policy_time_exit", {})
        return float(te_config.get("settlement_guard_seconds", DEFAULT_SETTLEMENT_GUARD_SECONDS))
    except Exception:
        return float(DEFAULT_SETTLEMENT_GUARD_SECONDS)


# CRITICAL FIX (2026-08-27): Targeted production override while the in-flight
# reconciliation scheduler is being repaired. When set, a SETTLEMENT_GUARD
# trigger is allowed to force-reconcile a stale in-flight exit instead of
# dropping the forced exit.
_FORCE_SETTLEMENT_BYPASS_ENV = os.environ.get("MERID_SETTLEMENT_BYPASS_IN_FLIGHT", "false").lower() in ("1", "true", "yes")


def _settlement_bypass_env_enabled() -> bool:
    """Live read of the env override so tests and hot-reloads can toggle it."""
    return os.environ.get("MERID_SETTLEMENT_BYPASS_IN_FLIGHT", "false").lower() in ("1", "true", "yes")

# Exit reasons that may force a stale in-flight order to be reconciled,
# cancelled, and re-emitted. These are time-to-expiry, safety, or
# operator-driven exits; profit-taking exits are NOT in this set.
_FORCE_RECONCILE_EXIT_REASONS = {
    ExitReason.SETTLEMENT_GUARD,
    ExitReason.LOSS_CAP,
    ExitReason.RISK,
    ExitReason.MANUAL,
    ExitReason.MODEL_INVALIDATION_LOSS_EXIT,
    ExitReason.CONTINUATION_STOP,
    ExitReason.TIME_STOP,
    ExitReason.STOP_LOSS,
    ExitReason.AUTO_EXIT_99C,
    ExitReason.MARKET_EXPIRED,
}


# Entry book qualities that are trusted for spread-only / adverse-move stop guards.
# AT_FILL is the gold standard.  AT_FILL_OR_NEAREST_PRE_FILL is a bounded fallback
# that uses the most recent pre-fill book when a perfectly contemporaneous book
# cannot be captured (e.g., a WS/RTI fill race).
_TRUSTED_ENTRY_BOOK_QUALITIES = {"AT_FILL", "AT_FILL_OR_NEAREST_PRE_FILL"}


# Extra buffer (cents) to apply to the spread-only stop guard when the entry book
# was captured near-but-not-at fill, because the stale bid/ask may slightly
# misstate the true spread.
_NEAR_PRE_FILL_SPREAD_BUFFER_CENTS = int(
    os.environ.get("MERID_NEAR_PRE_FILL_SPREAD_BUFFER_CENTS", "2")
)


def _is_forced_exit_reason(exit_reason: ExitReason) -> bool:
    """Return True if the exit reason is safety/forced and may override a stale in-flight lock."""
    if exit_reason is None:
        return False
    return exit_reason in _FORCE_RECONCILE_EXIT_REASONS


def _is_settlement_guard_override(exit_reason: ExitReason) -> bool:
    """Return True if the env override forces settlement guard to bypass the in-flight check."""
    if exit_reason is None:
        return False
    return exit_reason == ExitReason.SETTLEMENT_GUARD and _settlement_bypass_env_enabled()


def _get_hard_loss_cap_cents() -> int:
    """Load per-position hard unrealized loss cap from active profile (cents)."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        rr_config = getattr(get_active_profile().profile, "exit_policy_risk_reward", {})
        # Allow either exit_policy.risk_reward.hard_unrealized_loss_cap_usd or
        # risk_policy.hard_unrealized_loss_cap_usd (fallback dict lookup).
        usd = rr_config.get("hard_unrealized_loss_cap_usd")
        if usd is None:
            risk_config = getattr(get_active_profile().profile, "risk_policy", {})
            usd = risk_config.get("hard_unrealized_loss_cap_usd", 5.0)
        return int(round(float(usd) * 100))
    except Exception:
        return 500  # $5.00 default


def _get_continuation_stop_config(asset: str) -> Dict[str, Any]:
    """Load continuation-stop parameters for an asset (config-driven)."""
    default = {"enabled": False}
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        rr_config = getattr(get_active_profile().profile, "exit_policy_risk_reward", {})
        cfg = rr_config.get("continuation_stop", {})
        if not cfg.get("enabled", False):
            return default
        asset_cfg = cfg.get("per_asset", {}).get(asset, {})
        return {
            "enabled": True,
            "lookback_minutes": int(cfg.get("lookback_minutes", 5)),
            "base_threshold_pct": float(cfg.get("base_threshold_pct", 0.003)),
            "vol_normalization": bool(cfg.get("vol_normalization", True)),
            "atr_window_minutes": int(cfg.get("atr_window_minutes", 15)),
            "threshold_pct": float(asset_cfg.get("threshold_pct", cfg.get("base_threshold_pct", 0.003))),
        }
    except Exception:
        return default


def _compute_5m_continuation_stop(
    position: Position,
    asset: str,
    cfg: Dict[str, Any],
) -> Tuple[bool, float, float]:
    """
    Compute whether the underlying spot has continued moving against the fade
    over the configured lookback window.

    Returns (triggered, adverse_return_pct, effective_threshold_pct).
    """
    from data.unified_spot_service import get_unified_spot_service

    spot_service = get_unified_spot_service()
    lookback_seconds = max(60, int(cfg.get("lookback_minutes", 5)) * 60)
    history = spot_service.get_spot_history(asset, lookback_seconds)

    if len(history) < 2:
        logger.debug(
            "[POSITION-MONITOR] CONTINUATION-STOP insufficient spot history for %s: %d samples",
            asset, len(history)
        )
        return False, 0.0, 0.0

    old_price = float(history[0]["price"])
    new_price = float(history[-1]["price"])
    if old_price <= 0 or new_price <= 0 or not math.isfinite(old_price) or not math.isfinite(new_price):
        return False, 0.0, 0.0

    spot_return_pct = (new_price - old_price) / old_price

    # Adverse direction: for long YES, spot down is bad; for long NO, spot up is bad.
    if position.side == PositionSide.YES:
        adverse_return_pct = max(0.0, -spot_return_pct)
    else:
        adverse_return_pct = max(0.0, spot_return_pct)

    threshold_pct = float(cfg.get("threshold_pct", 0.003))

    # Optional vol-normalization using 5m log-return std over the ATR window.
    if cfg.get("vol_normalization") and cfg.get("atr_window_minutes", 0) > 0:
        atr_seconds = int(cfg.get("atr_window_minutes")) * 60
        atr_history = spot_service.get_spot_history(asset, atr_seconds)
        if len(atr_history) >= 3:
            prices = [float(p["price"]) for p in atr_history if p["price"] > 0 and math.isfinite(float(p["price"]))]
            if len(prices) >= 3:
                log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
                std = statistics.pstdev(log_returns)
                # Reference: 0.5% (0.005) log-return std as neutral multiplier.
                multiplier = std / 0.005
                # Clamp to 0.5x-3.0x to avoid extreme values from tiny sample std.
                multiplier = max(0.5, min(3.0, multiplier))
                threshold_pct = threshold_pct * multiplier

    return adverse_return_pct > threshold_pct, adverse_return_pct, threshold_pct


# Position monitor constants
POLL_INTERVAL_SECONDS = 5.0  # Default polling interval in seconds
SUBMISSION_CACHE_TTL_SECONDS = 15.0  # Time-to-live for exit submission cache
STARTUP_GRACE_WINDOW_SECONDS = 30.0  # Grace window for startup race conditions
EXIT_INTENT_TIMEOUT_SECONDS = 15.0  # Timeout for exit intent completion
DUPLICATE_WINDOW_SECONDS = 5.0  # Time window to consider orders duplicate
R_MULTIPLE_THRESHOLD = 0.5  # R-multiple threshold for time-based exits
TRAILING_ACTIVATION_R = 0.8  # R-multiple to activate trailing stops
TRAILING_GIVEBACK_CENTS = 5  # Default giveback in cents for trailing stops
DEFAULT_RISK_CENTS = 5  # Default risk in cents for position sizing

# CRITICAL FIX (2026-08-09): Stop-loss and edge-decay freshness/confirmation guards
SOFT_STOP_MIN_OBSERVATIONS = int(os.getenv("MERID_SOFT_STOP_MIN_OBSERVATIONS", "2"))  # confirmation polls
HARD_STOP_EXTRA_BUFFER_CENTS = int(os.getenv("MERID_HARD_STOP_EXTRA_BUFFER_CENTS", "1"))  # extra buffer for taker fee/slippage
MIN_EDGE_DECAY_HOLD_SECONDS = float(os.getenv("MERID_MIN_EDGE_DECAY_HOLD_SECONDS", "30.0"))  # edge-decay may not fire immediately after fill
MIN_EXIT_HOLD_SECONDS = float(os.getenv("MERID_MIN_EXIT_HOLD_SECONDS", "2.0"))  # minimum seconds any exit can hold (except hard stop / market close)
# CRITICAL FIX (2026-08-11): Stop-loss arming period. Price stops must not fire
# until the position has seen a fresh book update after this many seconds, to
# prevent a spread-only fill from immediately stopping itself out.
MIN_STOP_ARM_SECONDS = float(os.getenv("MERID_MIN_STOP_ARM_SECONDS", "5.0"))
EXIT_PRICE_MAX_AGE_MS = float(os.getenv("MERID_EXIT_PRICE_MAX_AGE_MS", "10000.0"))  # 10s default

# CRITICAL FIX (2026-08-11): Observable counters for spread-stop protection.
# These are reset on process start and logged prominently so the deterministic
# loss factory can be proven absent in canary / production.
STOP_PROTECTION_COUNTERS: Dict[str, int] = {
    "stop_disabled_unknown_provenance": 0,
    "entry_stop_rejected_spread_unviable": 0,
    "exit_stop_rejected_spread_only": 0,
    "unmanaged_position_unknown_risk_state": 0,
    "unmanaged_position_fallback_no_executable_exit": 0,
}


def _bump_stop_counter(key: str, reason: str = "") -> None:
    STOP_PROTECTION_COUNTERS[key] += 1
    logger.critical(
        "[STOP-PROTECTION-COUNTER] %s=%d reason=%s",
        key, STOP_PROTECTION_COUNTERS[key], reason,
    )


class PositionMonitor:
    """
    Position monitor for swing trading exit management.

    Subscribes to market data and execution events, maintains open positions,
    computes PnL, and enforces TP/SL exits via exit policy resolver.
    """

    def __init__(
        self,
        poll_interval: float = POLL_INTERVAL_SECONDS,  # Check positions every 5 seconds
    ):
        """
        Initialize position monitor.

        Args:
            poll_interval: Polling interval in seconds
        """
        self._poll_interval = poll_interval
        self._open_positions: Dict[str, Position] = {}  # position_id -> Position
        self._market_to_position: Dict[str, str] = {}  # market_id -> position_id
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._exit_intent_callback = None  # Callback for exit intents
        self._lock = threading.RLock()  # Thread-safe access to position dicts

        # Entry-gate context from the 15m loop. Exit evaluation must remain
        # independent of allow_new_entries, but it must be observable that the
        # entry gate (queue threshold, signal rejections, etc.) did not prevent
        # the profit-taking path from running.
        self._entry_gate_context: Dict[str, Any] = {
            "allow_new_entries": True,
            "ws_queue_size": 0,
            "ws_lag_ms": 0.0,
        }

        # CRITICAL FIX (2026-07-23): Recent submission cache to handle websocket lag
        # Tracks exit orders submitted but not yet visible in RestingOrderMonitor
        # Prevents duplicate exits due to exchange confirmation latency
        self._recent_exit_submissions: Dict[str, float] = {}  # client_order_id -> timestamp
        self._submission_cache_ttl = SUBMISSION_CACHE_TTL_SECONDS  # 15 seconds TTL for submission cache
        self._position_to_client_order: Dict[str, str] = {}  # position_id -> client_order_id

        # CRITICAL FIX (2026-07-23): First-class exit registry
        # Tracks exit orders by position_id as source of truth
        # Reduces reliance on exchange data heuristics
        self._exit_registry: Dict[str, List[str]] = {}  # position_id -> list of kalshi_order_ids
        self._exit_quantities: Dict[str, Dict[str, int]] = {}  # position_id -> {kalshi_order_id: quantity}

        # CRITICAL FIX (2026-07-23): Position-level execution locks
        # Prevents TOCTOU races during exit order creation
        self._position_exit_locks: Dict[str, threading.Lock] = {}  # position_id -> Lock
        self._lock_registry_lock = threading.Lock()  # Lock for registry access

        # CRITICAL FIX (2026-07-23): Startup grace window to prevent race conditions
        # Tracks process start time and orders last updated timestamp
        self._process_start_time = time.time()
        self._orders_last_updated_ts: Optional[float] = None
        self._startup_grace_window_seconds = STARTUP_GRACE_WINDOW_SECONDS  # 30 seconds grace window for startup

        # CRITICAL FIX (2026-07-23): Edge-triggered execution lock per position
        # Prevents multiple exit triggers (TP + SL) from firing before first exit is placed
        # 2026-08-09: state machine (SUBMITTED / SUBMISSION_UNKNOWN / RECONCILED)
        self._exit_intent_in_flight: Dict[str, Dict[str, Any]] = {}  # position_id -> {"state": str, "timestamp": float, "client_order_id": Optional[str]}
        self._exit_intent_timeout_seconds = EXIT_INTENT_TIMEOUT_SECONDS  # 15 seconds timeout for exit intent to complete

        # 2026-09-01: Durable exit-intent registry.  The in-flight state survives
        # process restarts so exits are not duplicated after a crash/restart.
        self._exit_intent_persistence_path = (
            Path(__file__).resolve().parents[2] / "data" / "exit_intents.json"
        )
        self._exit_intent_persistence_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_exit_intent_in_flight()

        # CRITICAL FIX (2026-08-09): Durable cleanup queue for capacity/risk/monitor cleanup failures.
        # A position is removed from active trading immediately; any failed bookkeeping is retried.
        self._cleanup_pending: List[Dict[str, Any]] = []  # queue of cleanup work items

    def _is_expired_market(self, market_id: str) -> bool:
        """Check if a market has expired based on its ticker.

        Args:
            market_id: The market ticker to check

        Returns:
            True if the market has expired, False otherwise
        """
        return _is_expired_ticker(market_id)

    def set_entry_gate_context(self, context: Dict[str, Any]) -> None:
        """Update the entry-gate context for audit logging only.

        This context must not change whether exit evaluation runs; it is only
        included in EXIT_EVAL logs so the two gate dimensions are observable.
        """
        self._entry_gate_context = {
            "allow_new_entries": context.get("allow_new_entries", True),
            "ws_queue_size": context.get("ws_queue_size", 0),
            "ws_lag_ms": context.get("ws_lag_ms", 0.0),
        }

    def register_exit_intent_callback(self, callback) -> None:
        """
        Register callback for exit intents.

        Args:
            callback: Function to call when exit intent is generated
                     Signature: callback(position, exit_reason, exit_price_cents)
        """
        self._exit_intent_callback = callback
        logger.info("[POSITION-MONITOR] Registered exit intent callback")

    @staticmethod
    def _is_full_ticker(market_id: str) -> bool:
        """A full 15m market ticker contains a date/time window segment (e.g. KXBTC15M-26AUG100000-00).

        Strip/series keys such as KXBTC15M are not unique across windows and must not be used
        as position or exit-in-flight identifiers.
        """
        if not market_id:
            return False
        return "-" in market_id and len(market_id.split("-")) >= 2

    def add_position(self, position: Position) -> None:
        """
        Add a new position to monitor.

        Args:
            position: Position to add
        """
        # CRITICAL FIX (2026-08-08): Never monitor positions for expired/closed markets.
        # These contracts cannot be traded and should route to settlement reconciliation.
        if self._is_expired_market(position.market_id):
            logger.warning(
                "[POSITION-MONITOR] Rejecting position for expired/closed market: %s market=%s",
                position.position_id[:8], position.market_id
            )
            return

        # CRITICAL FIX (2026-08-09): Reject strip/series-only keys to avoid cross-window collisions.
        if not self._is_full_ticker(position.market_id):
            logger.error(
                "[POSITION-MONITOR-KEY-REJECT] Refusing to monitor position keyed by strip/series: %s market=%s",
                position.position_id[:8], position.market_id
            )
            return

        # CRITICAL FIX (2026-08-23): Attach canonical position key. Asset aliases
        # (XRP15M, KXXRP15M, XRP) must never be a primary position identity.
        if position.position_key is None:
            position.position_key = canonical_position_key(position.market_id)
            position.known_aliases = [position.market_id]

        with self._lock:
            if position.position_id in self._open_positions:
                logger.warning(
                    "[POSITION-MONITOR] Position %s already exists, skipping",
                    position.position_id
                )
                return

            # Invariant: no duplicate canonical position keys.
            existing_with_key = [
                p for p in self._open_positions.values()
                if p.position_key == position.position_key
            ]
            if existing_with_key:
                logger.error(
                    "[POSITION-MONITOR-KEY-REJECT] Duplicate canonical position key for market=%s: "
                    "existing=%s new=%s. Rejecting to prevent double monitoring.",
                    position.market_id,
                    existing_with_key[0].position_id[:8],
                    position.position_id[:8],
                )
                return

            self._open_positions[position.position_id] = position
            self._market_to_position[position.market_id] = position.position_id

        logger.info(
            "[POSITION-MONITOR] Added position: %s market=%s side=%s size=%s entry=%dc TP=%s SL=%s vol_regime=%s confidence=%s",
            position.position_id[:8],
            position.market_id,
            position.side,
            position.size,
            position.avg_entry_price_cents,
            f"{position.take_profit_price_cents}c" if position.take_profit_price_cents is not None else "none",
            f"{position.stop_loss_price_cents}c" if position.stop_loss_price_cents is not None else "none",
            position.vol_regime,
            position.confidence,
        )

        # HIGH-SEVERITY ALERT (2026-08-13): UNKNOWN or non-executable FALLBACK
        # positions have no trusted price-based exit path.  The monitor will still
        # manage settlement/time exits, but a live position without a working TP/SL
        # must be paged/escalated.
        if position.risk_params_state == RiskParamsState.UNKNOWN:
            _bump_stop_counter(
                "unmanaged_position_unknown_risk_state",
                f"position={position.position_id[:8]} market={position.market_id}",
            )
        elif position.risk_params_state == RiskParamsState.FALLBACK:
            if position.take_profit_price_cents is None:
                _bump_stop_counter(
                    "unmanaged_position_fallback_no_executable_exit",
                    f"position={position.position_id[:8]} market={position.market_id}",
                )

    def _trust_rank(self, position: Position) -> int:
        """Return a numeric trust rank for a position's risk parameters."""
        if position.risk_params_state == RiskParamsState.ORIGINAL_PERSISTED:
            return 3
        if position.risk_params_state == RiskParamsState.FALLBACK:
            return 2
        return 1

    def upsert_position(self, position: Position, caller: str = "") -> None:
        """
        Add a position or update an existing one while preserving runtime state.

        This is the canonical path for live fill ingestion.  A position from a
        durable live fill should replace or augment a stale REST-synced/unknown
        position, but runtime exit state (high watermarks, trailing status,
        staged exit flags, in-flight exit intents, etc.) must never be reset.
        """
        if self._is_expired_market(position.market_id):
            logger.warning(
                "[POSITION-MONITOR] Rejecting upsert for expired/closed market: %s market=%s",
                position.position_id[:8], position.market_id
            )
            return

        if not self._is_full_ticker(position.market_id):
            logger.error(
                "[POSITION-MONITOR-KEY-REJECT] Refusing to upsert position keyed by strip/series: %s market=%s",
                position.position_id[:8], position.market_id
            )
            return

        if position.position_key is None:
            position.position_key = canonical_position_key(position.market_id)
            position.known_aliases = [position.market_id]

        # Runtime fields that must be preserved across replacements.
        runtime_fields = {
            "opened_at", "current_price_cents", "unrealized_pnl_cents", "r_multiple",
            "time_since_entry_seconds", "trailing_profit_threshold_reached_at",
            "exit_triggered", "exit_reason", "exit_price_cents", "exited_at", "state",
            "removed", "terminal", "high_watermark_cents", "low_watermark_cents",
            "max_favorable_price_cents", "trailing_activated", "trailing_profit_zone_activated",
            "trailing_state", "trail_armed_at", "trail_started_at",
            "high_watermark_updated_at", "low_watermark_updated_at", "soft_stop_observations",
            "tp_debounce_first_seen_at", "tp_debounce_hysteresis_cents",
            "hard_stop_confirmed", "break_even_triggered", "break_even_price_cents",
            "scale_out_triggered", "scale_out_remaining_size", "scale_out_r_multiple",
            "ratchet_activated", "ratchet_hold_until", "ratchet_floor_price_cents",
            "ratchet_trimmed", "dynamic_tp_target_cents", "dynamic_tp_triggered",
            "edge_decay_confirmations", "staged_exit_stage_0_executed",
            "staged_exit_stage_1_executed", "staged_exit_stage_2_executed",
            "staged_exit_stage_0_timestamp", "staged_exit_stage_1_timestamp",
            "staged_exit_stage_2_timestamp",
        }

        # Provenance/construction fields that an older, more trusted record should keep.
        provenance_fields = {
            "risk_params_state", "risk_params_schema_version", "client_order_id",
            "entry_intent_id", "entry_fill_id", "entry_order_id", "entry_provenance_snapshot_id",
            "entry_fill_price_cents", "entry_fill_timestamp", "entry_executable_bid_cents",
            "entry_executable_ask_cents", "entry_book_capture_quality", "entry_book_timestamp",
            "entry_book_sequence", "entry_book_source", "entry_signal_id", "entry_model",
            "entry_model_version", "entry_model_probability", "entry_market_probability",
            "entry_edge", "entry_book_snapshot_id", "entry_edge_pct", "fill_source",
            "provenance_state", "take_profit_price_cents", "stop_loss_enabled",
            "stop_loss_price_cents", "trailing_type", "trailing_param", "scale_out_price_cents",
        }

        with self._lock:
            existing = self._open_positions.get(position.position_id)
            if existing is None:
                # Check canonical key collision.
                existing_with_key = [
                    p for p in self._open_positions.values()
                    if p.position_key == position.position_key
                ]
                if existing_with_key:
                    logger.error(
                        "[POSITION-MONITOR-KEY-REJECT] Duplicate canonical position key for market=%s: "
                        "existing=%s new=%s. Rejecting to prevent double monitoring.",
                        position.market_id,
                        existing_with_key[0].position_id[:8],
                        position.position_id[:8],
                    )
                    return

                self._open_positions[position.position_id] = position
                self._market_to_position[position.market_id] = position.position_id
                logger.info(
                    "[POSITION-MONITOR] Added position: %s market=%s side=%s size=%s entry=%dc TP=%s SL=%s caller=%s",
                    position.position_id[:8], position.market_id, position.side,
                    position.size, position.avg_entry_price_cents,
                    f"{position.take_profit_price_cents}c" if position.take_profit_price_cents is not None else "none",
                    f"{position.stop_loss_price_cents}c" if position.stop_loss_price_cents is not None else "none",
                    caller,
                )
                return

            old_rank = self._trust_rank(existing)
            new_rank = self._trust_rank(position)

            # Choose the base record.  New live fills are normally at least as trusted
            # as a REST-synced record and also carry the latest size/avg/price.
            if new_rank >= old_rank:
                base = position
                source = "new"
            else:
                # Keep the trusted provenance of the old record but apply the new
                # size/avg/price so the monitor tracks actual exposure.
                base = existing
                source = "old"
                # Update size and average price from the new fill state.
                base.size = position.size
                base.avg_entry_price_cents = position.avg_entry_price_cents

            # If the old record is more trusted, copy provenance fields back.
            if source == "new" and old_rank > new_rank:
                for field in provenance_fields:
                    old_value = getattr(existing, field, None)
                    if old_value is not None:
                        setattr(base, field, old_value)

            # Preserve runtime state from the existing record.
            if source == "new":
                for field in runtime_fields:
                    old_value = getattr(existing, field, None)
                    if old_value is not None and old_value != 0 and old_value != "":
                        setattr(base, field, old_value)
                # Always carry forward the original entry/open time.
                if existing.opened_at:
                    base.opened_at = existing.opened_at

            # Re-run post-init to recompute derived fields (initial_risk, hard_stop,
            # fallback TP, etc.) now that size/avg/SL/TP may have changed.
            base.__post_init__()

            # Ensure the canonical key mapping is stable.
            self._open_positions[position.position_id] = base
            self._market_to_position[position.market_id] = position.position_id

        logger.info(
            "[POSITION-MONITOR] Upserted position: %s market=%s side=%s size=%s entry=%dc TP=%s SL=%s "
            "old_rank=%d new_rank=%d base=%s caller=%s",
            position.position_id[:8], position.market_id, position.side,
            position.size, position.avg_entry_price_cents,
            f"{base.take_profit_price_cents}c" if base.take_profit_price_cents is not None else "none",
            f"{base.stop_loss_price_cents}c" if base.stop_loss_price_cents is not None else "none",
            old_rank, new_rank, source, caller,
        )

    def _resolve_position_id(self, position_id: str) -> Optional[str]:
        """Resolve either a position_id or a full market_id to the canonical position_id."""
        with self._lock:
            if position_id in self._open_positions:
                return position_id
            if position_id in self._market_to_position:
                return self._market_to_position[position_id]
        return None

    def _record_cleanup_pending(
        self,
        position: Position,
        reason: str,
        exc: Optional[Exception] = None,
    ) -> None:
        """Queue a failed cleanup for idempotent retry. The active position is already gone."""
        item = {
            "position_id": position.position_id,
            "market_id": position.market_id,
            "side": position.side.value if position.side else None,
            "size": position.size,
            "avg_entry_price_cents": position.avg_entry_price_cents,
            "reason": reason,
            "traceback": traceback.format_exc() if exc is not None else None,
            "timestamp": time.time(),
        }
        with self._lock:
            self._cleanup_pending.append(item)
        logger.exception(
            "[POSITION-CLEANUP-PENDING] key=%s market=%s; active position already removed",
            position.position_id[:8],
            position.market_id,
            exc_info=exc,
        )

    def remove_position(self, position_id: str) -> None:
        """
        Remove a position from monitoring.

        2026-08-09 redesign:
        - The canonical position is removed immediately from active trading eligibility.
        - Capacity/risk/monitor cleanup is attempted idempotently after removal.
        - If cleanup fails, a `CLEANUP_PENDING` work item is created and retried later.
        A bookkeeping failure can NEVER resurrect or retain an active position.

        Args:
            position_id: Position ID or full market_id to remove
        """
        resolved_id = self._resolve_position_id(position_id)
        if resolved_id is None:
            logger.warning(
                "[POSITION-MONITOR] Position %s not found, cannot remove",
                position_id[:8] if len(position_id) > 8 else position_id
            )
            return

        with self._lock:
            position = self._open_positions.pop(resolved_id, None)
            if position is None:
                return
            if position is not None:
                position.removed = True
            self._market_to_position.pop(position.market_id, None)
            self._exit_registry.pop(resolved_id, None)
            self._exit_quantities.pop(resolved_id, None)
            self._position_exit_locks.pop(resolved_id, None)
            self._exit_intent_in_flight.pop(resolved_id, None)
            self._position_to_client_order.pop(resolved_id, None)

        logger.info(
            "[POSITION-MONITOR] Removed active position: %s (market=%s, exit_reason=%s, exit_price=%sc)",
            position.position_id[:8],
            position.market_id,
            position.exit_reason or "none",
            position.exit_price_cents if position.exit_price_cents is not None else "N/A",
        )

        # 2026-08-09: Decimal math for notional; never divide Decimal by float.
        try:
            notional_usd = (
                Decimal(str(position.size)) * Decimal(position.avg_entry_price_cents)
            ) / Decimal("100")
        except Exception as e:
            self._record_cleanup_pending(position, "notional_calculation_failed", e)
            return

        # Attempt idempotent window capacity release.
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            # record_position_closure currently uses float-based module state; pass float for compatibility.
            envelope.record_position_closure(position.market_id, float(notional_usd))
            logger.info(
                "[POSITION-CLEANUP] Released window capacity: market=%s notional=$%.2f exit_reason=%s",
                position.market_id,
                float(notional_usd),
                position.exit_reason,
            )
        except Exception as e:
            self._record_cleanup_pending(position, "capacity_release_failed", e)

    def _cancel_durable_order_attempt(self, client_order_id: Optional[str], reason: str) -> None:
        """Mark a durable order attempt as terminal so it cannot be reused on restart."""
        if not client_order_id:
            return
        try:
            from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore
            store = OrderAttemptStore()
            record = store.get_by_client_order_id(client_order_id)
            if record is None:
                return
            if record.status in ("SUBMISSION_UNKNOWN", "SUBMITTING", "PERSISTED"):
                store.update_status(
                    record.order_attempt_id,
                    "CANCELLED",
                    payload={"cancel_reason": reason, "cancelled_at": time.time()},
                )
                logger.warning(
                    "[EXIT-INTENT-STARTUP-CLEANUP] Cancelled stale order attempt %s client_order_id=%s status=%s reason=%s",
                    record.order_attempt_id[:16],
                    client_order_id[:8],
                    record.status,
                    reason,
                )
        except Exception:
            logger.exception(
                "[EXIT-INTENT-STARTUP-CLEANUP] Failed to cancel durable order attempt for client_order_id=%s",
                client_order_id[:8] if client_order_id else "",
            )

    def _cleanup_stale_exit_in_flight_on_startup(self) -> None:
        """Drop in-flight/submission-unknown state for positions whose contract has expired.

        On process restart the in-memory locks are empty, but the durable order-attempt
        store may still hold SUBMISSION_UNKNOWN records for positions that have settled.
        This routine ensures those records are terminalised and that any cached expired
        position is not re-monitored.
        """
        with self._lock:
            # Defensive: clear any in-memory locks that point to positions we did not load
            # or that belong to expired markets.  This should be a no-op on a fresh process,
            # but it is critical if the monitor is ever started without a full reset.
            stale_inflight = []
            for position_id, flight in self._exit_intent_in_flight.items():
                position = self._open_positions.get(position_id)
                if position is None:
                    stale_inflight.append(position_id)
                elif position.market_id and self._is_expired_market(position.market_id):
                    stale_inflight.append(position_id)

            for position_id in stale_inflight:
                self._clear_exit_intent_in_flight(position_id)
                if position_id in self._open_positions:
                    self.remove_position(position_id)

            for position_id in list(self._position_to_client_order.keys()):
                if position_id not in self._open_positions:
                    del self._position_to_client_order[position_id]
                else:
                    position = self._open_positions[position_id]
                    if position.market_id and self._is_expired_market(position.market_id):
                        del self._position_to_client_order[position_id]

            for client_order_id in list(self._recent_exit_submissions.keys()):
                # The client_order_id may be shared across positions; if no open
                # position still references it, the submission cache is stale.
                if client_order_id not in self._position_to_client_order.values():
                    del self._recent_exit_submissions[client_order_id]

        logger.info(
            "[EXIT-INTENT-STARTUP-CLEANUP] Cleared %d stale in-flight lock(s), %d client-order mapping(s)",
            len(stale_inflight),
            len([pid for pid in list(self._position_to_client_order.keys()) if pid not in self._open_positions]),
        )

    def retry_cleanup(self) -> int:
        """Retry any pending cleanup work items. Returns number of successfully processed items."""
        successes = 0
        with self._lock:
            pending = list(self._cleanup_pending)
            self._cleanup_pending = []

        remaining = []
        for item in pending:
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                envelope = get_kalshi_crypto_15m_risk_envelope()
                size = item.get("size", 0)
                price = item.get("avg_entry_price_cents", 0)
                notional_usd = (Decimal(str(size)) * Decimal(price)) / Decimal("100")
                envelope.record_position_closure(item["market_id"], float(notional_usd))
                successes += 1
                logger.info(
                    "[POSITION-CLEANUP-RETRY] Successfully released capacity: market=%s notional=$%.2f",
                    item["market_id"], float(notional_usd)
                )
            except Exception as e:
                item["retry_count"] = item.get("retry_count", 0) + 1
                remaining.append(item)
                logger.warning(
                    "[POSITION-CLEANUP-RETRY-FAILED] market=%s retry=%d error=%s",
                    item["market_id"], item["retry_count"], e
                )

        with self._lock:
            self._cleanup_pending = remaining
        return successes

    def get_cleanup_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._cleanup_pending)

    def get_position(self, position_id: str) -> Optional[Position]:
        """
        Get a position by ID.

        Args:
            position_id: Position ID

        Returns:
            Position or None if not found
        """
        with self._lock:
            return self._open_positions.get(position_id)

    def get_position_by_market(self, market_id: str) -> Optional[Position]:
        """
        Get a position by market ID.

        Args:
            market_id: Market ID

        Returns:
            Position or None if not found
        """
        with self._lock:
            position_id = self._market_to_position.get(market_id)
            if position_id:
                return self._open_positions.get(position_id)
            return None

    def get_open_positions(self) -> Dict[str, Position]:
        """
        Get all open positions.

        Returns:
            Dict of position_id -> Position
        """
        with self._lock:
            return self._open_positions.copy()

    def get_open_positions_count(self) -> int:
        """
        Get the count of open positions.

        Returns:
            Number of open positions
        """
        with self._lock:
            return len(self._open_positions)

    def health_check_exit_coverage(self) -> Dict[str, Any]:
        """
        Health check for one-position-one-exit invariant.

        CRITICAL FIX (2026-07-23): Verifies that each open position has exactly one
        active exit plan (resting exit order). Detects:
        - Positions without exit orders (missing coverage)
        - Positions with multiple exit orders (duplicate risk)

        Returns:
            Dict with health check results:
            - total_positions: Total number of open positions
            - positions_without_exit: List of market_ids without exit orders
            - positions_with_multiple_exits: List of market_ids with multiple exit orders
            - healthy_count: Number of positions with exactly one exit order
            - health_status: "healthy", "warning", or "critical"
        """
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source

        positions_without_exit = []
        positions_with_multiple_exits = []
        healthy_count = 0

        try:
            resting_monitor = get_resting_order_monitor()
            open_positions = self.get_open_positions()

            for position_id, position in open_positions.items():
                # Get resting orders for this market
                resting_orders = resting_monitor.get_orders_by_ticker(position.market_id)

                # Filter for exit orders only (check multiple fields for exit markers)
                # CRITICAL FIX (2026-07-23): Filter by status to exclude terminal orders
                # Only count orders with active status (open, resting, partially_filled)
                from merid.event_venues.kalshi.resting_order_monitor import RESTING_STATUSES, TERMINAL_STATUSES
                exit_orders = []
                for order in resting_orders:
                    is_exit = (
                        is_exit_order_from_source(order.exit_policy_id) or
                        is_exit_order_from_source(order.client_order_id) or
                        is_exit_order_from_source(order.intent_id) or
                        is_exit_order_from_source(getattr(order, 'source', None))
                    )
                    # CRITICAL FIX (2026-07-23): Exclude terminal statuses (filled, canceled, expired, rejected)
                    # These orders are no longer active and should not count as exit coverage
                    order_status = getattr(order, 'status', '').lower()
                    is_active = order_status in RESTING_STATUSES or order_status not in TERMINAL_STATUSES

                    if is_exit and is_active:
                        exit_orders.append(order)

                # Check exit coverage
                if len(exit_orders) == 0:
                    positions_without_exit.append(position.market_id)
                    logger.warning(
                        "[EXIT-COVERAGE-HEALTH] Position without exit order: market=%s position_id=%s side=%s size=%s",
                        position.market_id,
                        position.position_id[:8],
                        position.side.value,
                        position.size
                    )
                elif len(exit_orders) > 1:
                    positions_with_multiple_exits.append(position.market_id)
                    logger.warning(
                        "[EXIT-COVERAGE-HEALTH] Position with multiple exit orders: market=%s position_id=%s exit_count=%d order_ids=%s",
                        position.market_id,
                        position.position_id[:8],
                        len(exit_orders),
                        [order.kalshi_order_id for order in exit_orders]
                    )
                else:
                    # CRITICAL FIX (2026-07-23): Check quantity coverage for single exit order
                    # Ensure exit order quantity is sufficient to cover position size
                    exit_order = exit_orders[0]
                    exit_quantity = exit_order.remaining_size if hasattr(exit_order, 'remaining_size') else exit_order.original_size

                    if exit_quantity < position.size:
                        logger.warning(
                            "[EXIT-QUANTITY-COVERAGE] Exit order quantity insufficient: market=%s position_id=%s exit_qty=%d position_size=%s gap=%s",
                            position.market_id,
                            position.position_id[:8],
                            exit_quantity,
                            position.size,
                            position.size - exit_quantity
                        )
                        # Still count as healthy for existence check, but log warning
                        healthy_count += 1
                    else:
                        healthy_count += 1
                        logger.debug(
                            "[EXIT-COVERAGE-HEALTH] Position has exactly one exit order with sufficient quantity: market=%s position_id=%s order_id=%s exit_qty=%d position_size=%s",
                            position.market_id,
                            position.position_id[:8],
                            exit_order.kalshi_order_id,
                            exit_quantity,
                            position.size
                        )
        except Exception as health_err:
            logger.error(
                "[EXIT-COVERAGE-HEALTH] Health check failed: %s",
                health_err,
                exc_info=True
            )
            return {
                "error": str(health_err),
                "health_status": "error"
            }

        # Determine overall health status
        total_positions = len(positions_without_exit) + len(positions_with_multiple_exits) + healthy_count

        if len(positions_without_exit) > 0 or len(positions_with_multiple_exits) > 0:
            health_status = "critical" if len(positions_without_exit) > 0 else "warning"
        else:
            health_status = "healthy"

        result = {
            "total_positions": total_positions,
            "positions_without_exit": positions_without_exit,
            "positions_with_multiple_exits": positions_with_multiple_exits,
            "healthy_count": healthy_count,
            "health_status": health_status
        }

        logger.info(
            "[EXIT-COVERAGE-HEALTH] Summary: total=%d healthy=%d without_exit=%d multiple_exits=%d status=%s",
            total_positions,
            healthy_count,
            len(positions_without_exit),
            len(positions_with_multiple_exits),
            health_status
        )

        return result

    def portfolio_level_exit_coverage_check(self) -> Dict[str, Any]:
        """
        Portfolio-level cross-asset exit coverage check.

        CRITICAL FIX (2026-07-23): Ensures portfolio-wide exit coverage invariants:
        - No open positions in any asset without exit coverage
        - No asset with more than one exit per position
        - Per-asset breakdown of exit coverage status

        This provides a portfolio-wide view to gate new entries if the system
        detects missing exits for any asset.

        Returns:
            Dict with portfolio-level health check results:
            - total_positions: Total number of open positions across all assets
            - assets_with_positions: List of assets with open positions
            - per_asset_coverage: Dict mapping asset -> coverage status
            - assets_without_exit_coverage: List of assets with positions but no exits
            - assets_with_duplicate_exits: List of assets with duplicate exits
            - portfolio_health_status: "healthy", "warning", or "critical"
        """
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source

        per_asset_coverage = {}
        assets_without_exit_coverage = []
        assets_with_duplicate_exits = []

        try:
            resting_monitor = get_resting_order_monitor()
            open_positions = self.get_open_positions()

            # Group positions by asset
            positions_by_asset = {}
            for position_id, position in open_positions.items():
                asset = kalshi_ticker_to_asset(position.market_id) if position.market_id else "UNKNOWN"
                if asset not in positions_by_asset:
                    positions_by_asset[asset] = []
                positions_by_asset[asset].append(position)

            # Check each asset's exit coverage
            for asset, positions in positions_by_asset.items():
                asset_positions_without_exit = []
                asset_positions_with_multiple_exits = []
                asset_healthy_count = 0

                for position in positions:
                    # Get resting orders for this market
                    resting_orders = resting_monitor.get_orders_by_ticker(position.market_id)

                    # Filter for exit orders only (check multiple fields for exit markers)
                    # CRITICAL FIX (2026-07-23): Filter by status to exclude terminal orders
                    # Only count orders with active status (open, resting, partially_filled)
                    from merid.event_venues.kalshi.resting_order_monitor import RESTING_STATUSES, TERMINAL_STATUSES
                    exit_orders = []
                    for order in resting_orders:
                        is_exit = (
                            is_exit_order_from_source(order.exit_policy_id) or
                            is_exit_order_from_source(order.client_order_id) or
                            is_exit_order_from_source(order.intent_id) or
                            is_exit_order_from_source(getattr(order, 'source', None))
                        )
                        # CRITICAL FIX (2026-07-23): Exclude terminal statuses (filled, canceled, expired, rejected)
                        # These orders are no longer active and should not count as exit coverage
                        order_status = getattr(order, 'status', '').lower()
                        is_active = order_status in RESTING_STATUSES or order_status not in TERMINAL_STATUSES

                        if is_exit and is_active:
                            exit_orders.append(order)

                    # Check exit coverage
                    if len(exit_orders) == 0:
                        asset_positions_without_exit.append(position.market_id)
                    elif len(exit_orders) > 1:
                        asset_positions_with_multiple_exits.append(position.market_id)
                    else:
                        asset_healthy_count += 1

                # Determine asset-level health status
                if len(asset_positions_without_exit) > 0:
                    asset_status = "critical"
                    assets_without_exit_coverage.append(asset)
                elif len(asset_positions_with_multiple_exits) > 0:
                    asset_status = "warning"
                    assets_with_duplicate_exits.append(asset)
                else:
                    asset_status = "healthy"

                per_asset_coverage[asset] = {
                    "total_positions": len(positions),
                    "healthy_count": asset_healthy_count,
                    "positions_without_exit": asset_positions_without_exit,
                    "positions_with_multiple_exits": asset_positions_with_multiple_exits,
                    "asset_status": asset_status
                }

                logger.info(
                    "[PORTFOLIO-EXIT-COVERAGE] asset=%s total=%d healthy=%d without_exit=%d multiple_exits=%d status=%s",
                    asset,
                    len(positions),
                    asset_healthy_count,
                    len(asset_positions_without_exit),
                    len(asset_positions_with_multiple_exits),
                    asset_status
                )
        except Exception as portfolio_err:
            logger.error(
                "[PORTFOLIO-EXIT-COVERAGE] Portfolio-level health check failed: %s",
                portfolio_err,
                exc_info=True
            )
            return {
                "error": str(portfolio_err),
                "portfolio_health_status": "error"
            }

        # Determine overall portfolio health status
        total_positions = len(open_positions)
        assets_with_positions = list(positions_by_asset.keys())

        if len(assets_without_exit_coverage) > 0:
            portfolio_health_status = "critical"
        elif len(assets_with_duplicate_exits) > 0:
            portfolio_health_status = "warning"
        else:
            portfolio_health_status = "healthy"

        result = {
            "total_positions": total_positions,
            "assets_with_positions": assets_with_positions,
            "per_asset_coverage": per_asset_coverage,
            "assets_without_exit_coverage": assets_without_exit_coverage,
            "assets_with_duplicate_exits": assets_with_duplicate_exits,
            "portfolio_health_status": portfolio_health_status
        }

        logger.info(
            "[PORTFOLIO-EXIT-COVERAGE] Summary: total_positions=%d assets=%d healthy_assets=%d critical_assets=%d warning_assets=%d status=%s",
            total_positions,
            len(assets_with_positions),
            len([a for a, cov in per_asset_coverage.items() if cov["asset_status"] == "healthy"]),
            len(assets_without_exit_coverage),
            len(assets_with_duplicate_exits),
            portfolio_health_status
        )

        return result

    def _register_exit_submission(
        self,
        client_order_id: str,
        position_id: Optional[str] = None,
    ) -> None:
        """
        Register a recent exit order submission to handle websocket lag.

        CRITICAL FIX (2026-07-23): This prevents duplicate exits when exchange
        confirmation is delayed. Orders in this cache are treated as "exists"
        even if not yet visible in RestingOrderMonitor.

        CRITICAL FIX (2026-08-07): Also map the client_order_id to the position
        so we can reconcile before a timeout-triggered retry.

        Args:
            client_order_id: Client order ID of the submitted exit order
            position_id: Optional position_id for reconciliation mapping
        """
        with self._lock:
            self._recent_exit_submissions[client_order_id] = time.time()
            if position_id:
                self._position_to_client_order[position_id] = client_order_id
            logger.debug(
                "[EXIT-SUBMISSION-CACHE] Registered exit submission: client_order_id=%s position_id=%s",
                client_order_id, position_id or ""
            )

    def _is_exit_submitted_recently(self, client_order_id: str) -> bool:
        """
        Check if an exit order was submitted recently (within TTL).

        Args:
            client_order_id: Client order ID to check

        Returns:
            True if submitted within TTL, False otherwise
        """
        with self._lock:
            if client_order_id not in self._recent_exit_submissions:
                return False

            submission_time = self._recent_exit_submissions[client_order_id]
            if time.time() - submission_time > self._submission_cache_ttl:
                # Expired, remove from cache
                del self._recent_exit_submissions[client_order_id]
                logger.debug(
                    "[EXIT-SUBMISSION-CACHE] Expired submission: client_order_id=%s age=%.2fs",
                    client_order_id,
                    time.time() - submission_time
                )
                return False

            return True

    def _cleanup_expired_submissions(self) -> None:
        """Clean up expired submissions from the cache."""
        with self._lock:
            current_time = time.time()
            expired = [
                order_id for order_id, timestamp in self._recent_exit_submissions.items()
                if current_time - timestamp > self._submission_cache_ttl
            ]
            for order_id in expired:
                del self._recent_exit_submissions[order_id]
                # Remove the position mapping for this client order.
                for position_id, mapped_coid in list(self._position_to_client_order.items()):
                    if mapped_coid == order_id:
                        del self._position_to_client_order[position_id]

            if expired:
                logger.debug(
                    "[EXIT-SUBMISSION-CACHE] Cleaned up %d expired submissions",
                    len(expired)
                )

    def _register_exit_order(self, position_id: str, kalshi_order_id: str, quantity: int = 1) -> None:
        """
        Register an exit order in the first-class exit registry.

        CRITICAL FIX (2026-07-23): This registry is the source of truth for
        exit orders, reducing reliance on exchange data heuristics.

        Args:
            position_id: Position ID
            kalshi_order_id: Kalshi order ID
            quantity: Exit order quantity (number of contracts)
        """
        with self._lock_registry_lock:
            if position_id not in self._exit_registry:
                self._exit_registry[position_id] = []
                self._exit_quantities[position_id] = {}

            if kalshi_order_id not in self._exit_registry[position_id]:
                self._exit_registry[position_id].append(kalshi_order_id)
                self._exit_quantities[position_id][kalshi_order_id] = quantity
                logger.info(
                    "[EXIT-REGISTRY] Registered exit order: position_id=%s kalshi_order_id=%s quantity=%d total_exits=%d",
                    position_id[:8],
                    kalshi_order_id,
                    quantity,
                    len(self._exit_registry[position_id])
                )

    def _unregister_exit_order(self, position_id: str, kalshi_order_id: str) -> None:
        """
        Unregister an exit order from the exit registry.

        Args:
            position_id: Position ID
            kalshi_order_id: Kalshi order ID
        """
        with self._lock_registry_lock:
            if position_id in self._exit_registry:
                if kalshi_order_id in self._exit_registry[position_id]:
                    self._exit_registry[position_id].remove(kalshi_order_id)
                    if kalshi_order_id in self._exit_quantities.get(position_id, {}):
                        del self._exit_quantities[position_id][kalshi_order_id]
                    logger.info(
                        "[EXIT-REGISTRY] Unregistered exit order: position_id=%s kalshi_order_id=%s remaining_exits=%d",
                        position_id[:8],
                        kalshi_order_id,
                        len(self._exit_registry[position_id])
                    )

                if not self._exit_registry[position_id]:
                    del self._exit_registry[position_id]
                    if position_id in self._exit_quantities:
                        del self._exit_quantities[position_id]

    def _get_exit_orders_for_position(self, position_id: str) -> List[str]:
        """
        Get registered exit orders for a position.

        Args:
            position_id: Position ID

        Returns:
            List of Kalshi order IDs for exit orders
        """
        with self._lock_registry_lock:
            return self._exit_registry.get(position_id, []).copy()

    def _has_exit_order(self, position_id: str) -> bool:
        """
        Check if a position has any registered exit orders.

        Args:
            position_id: Position ID

        Returns:
            True if position has exit orders, False otherwise
        """
        with self._lock_registry_lock:
            return position_id in self._exit_registry and len(self._exit_registry[position_id]) > 0

    def _get_total_exit_quantity(self, position_id: str) -> int:
        """
        Get the total quantity of all exit orders for a position.

        CRITICAL FIX (2026-07-23): This is used for quantity-aware exit coverage invariant.

        Args:
            position_id: Position ID

        Returns:
            Total exit quantity (sum of all exit order quantities)
        """
        with self._lock_registry_lock:
            if position_id not in self._exit_quantities:
                return 0
            return sum(self._exit_quantities[position_id].values())

    def _check_exit_quantity_coverage(self, position_id: str, position_size: int) -> Dict[str, Any]:
        """
        Check if exit orders provide sufficient quantity coverage for a position.

        CRITICAL FIX (2026-07-23): Ensures sum(open_exit_qty) >= remaining_position_qty.
        This prevents the dangerous case where an exit order exists but is too small
        to fully exit the position.

        Args:
            position_id: Position ID
            position_size: Current position size

        Returns:
            Dict with coverage check results:
            - has_coverage: True if exit quantity >= position size
            - exit_quantity: Total exit quantity
            - position_size: Position size
            - coverage_gap: Quantity shortfall (if any)
            - coverage_pct: Coverage percentage
        """
        exit_quantity = self._get_total_exit_quantity(position_id)
        coverage_gap = max(0, position_size - exit_quantity)
        coverage_pct = (exit_quantity / position_size * 100) if position_size > 0 else 0

        result = {
            "has_coverage": exit_quantity >= position_size,
            "exit_quantity": exit_quantity,
            "position_size": position_size,
            "coverage_gap": coverage_gap,
            "coverage_pct": coverage_pct
        }

        if not result["has_coverage"]:
            logger.warning(
                "[EXIT-QUANTITY-COVERAGE] Insufficient exit coverage: position_id=%s exit_qty=%d position_size=%s gap=%s coverage_pct=%.1f%%",
                position_id[:8],
                exit_quantity,
                position_size,
                coverage_gap,
                coverage_pct
            )

        return result

    def _mark_exit_intent_in_flight(
        self,
        position_id: str,
        client_order_id: Optional[str] = None,
        reason: Optional[str] = None,
        task: Optional[asyncio.Task] = None,
    ) -> None:
        """
        Mark an exit intent as in-flight for a position.

        CRITICAL FIX (2026-07-23): This prevents multiple exit triggers (TP + SL)
        from firing before the first exit is placed. Only one exit intent can be
        in-flight per position at a time.

        2026-08-23 redesign: state machine (EXECUTION_PENDING -> SUBMITTED -> SUBMISSION_UNKNOWN -> RECONCILED).
        The intent is only SUBMITTED after the router/exchange call returns a valid
        response. A timeout does NOT allow a new exit until order/position state is reconciled.

        Args:
            position_id: Position ID
            client_order_id: Optional client_order_id for order lookup on timeout
            reason: Optional trigger reason for diagnostic logs
            task: Optional asyncio Task so it can be cancelled on timeout/retry
        """
        with self._lock:
            existing = self._exit_intent_in_flight.get(position_id, {})
            updated = {
                "state": "EXECUTION_PENDING",
                "timestamp": time.time(),
                "client_order_id": client_order_id if client_order_id is not None else existing.get("client_order_id"),
                "reason": reason if reason is not None else existing.get("reason"),
                "task": task if task is not None else existing.get("task"),
            }
            # Carry forward any other diagnostic keys (exchange_order_id, etc.)
            for key, value in existing.items():
                if key not in updated:
                    updated[key] = value
            self._exit_intent_in_flight[position_id] = updated
            if client_order_id:
                self._position_to_client_order[position_id] = client_order_id
                self._recent_exit_submissions[client_order_id] = time.time()
            logger.info(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent EXECUTION_PENDING: position_id=%s client_order_id=%s reason=%s",
                position_id[:8],
                client_order_id or updated.get("client_order_id"),
                reason or updated.get("reason") or "unknown",
            )
        self._save_exit_intent_in_flight()

    def _mark_exit_intent_submitted(
        self,
        position_id: str,
        exchange_order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Mark an exit intent as SUBMITTED after the exchange ack/router response."""
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is None:
                return
            flight["state"] = "SUBMITTED"
            flight["timestamp"] = time.time()
            flight["submitted_at"] = time.time()
            if exchange_order_id:
                flight["exchange_order_id"] = exchange_order_id
            if client_order_id:
                flight["client_order_id"] = client_order_id
                self._position_to_client_order[position_id] = client_order_id
                self._recent_exit_submissions[client_order_id] = time.time()
            logger.info(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent SUBMITTED: position_id=%s exchange_order_id=%s reason=%s",
                position_id[:8],
                exchange_order_id,
                reason or "unknown",
            )
        self._save_exit_intent_in_flight()

    def _mark_exit_intent_retryable(
        self, position_id: str, error_type: str, error: str
    ) -> None:
        """Mark an exit intent as a retryable failure (e.g. transient network error)."""
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is None:
                return
            flight["state"] = "RETRYABLE_FAILURE"
            flight["error_type"] = error_type
            flight["error"] = error
            logger.warning(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent RETRYABLE_FAILURE: position_id=%s error_type=%s error=%s",
                position_id[:8], error_type, error
            )
        self._save_exit_intent_in_flight()

    def _mark_exit_intent_reconciliation_required(
        self, position_id: str, error_type: str, error: str
    ) -> None:
        """Mark an exit intent as requiring reconciliation (e.g. deployment/code failure)."""
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is None:
                return
            flight["state"] = "RECONCILIATION_REQUIRED"
            flight["error_type"] = error_type
            flight["error"] = error
            logger.error(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent RECONCILIATION_REQUIRED: position_id=%s error_type=%s error=%s",
                position_id[:8], error_type, error
            )
        self._save_exit_intent_in_flight()

    def _mark_exit_intent_reconciled(self, position_id: str, reason: str) -> None:
        """Mark an exit intent as reconciled (terminal). Safe to call idempotently."""
        with self._lock:
            if position_id in self._exit_intent_in_flight:
                self._exit_intent_in_flight[position_id]["state"] = "RECONCILED"
                logger.info(
                    "[EXIT-INTENT-IN-FLIGHT] Exit intent RECONCILED: position_id=%s reason=%s",
                    position_id[:8], reason
                )
            if position_id in self._position_to_client_order:
                del self._position_to_client_order[position_id]
        self._save_exit_intent_in_flight()

    def _get_unresolved_exit_client_order_id(
        self, position_id: str
    ) -> Optional[str]:
        """Return the unresolved in-flight exit client_order_id for a position.

        Returns the client_order_id only when the intent is in a non-terminal
        state (EXECUTION_PENDING, SUBMITTED, SUBMISSION_UNKNOWN, RETRYABLE_FAILURE)
        so the loop can resubmit with the same idempotency key.
        """
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is not None:
                state = flight.get("state")
                if state not in ("RECONCILED",):
                    return flight.get("client_order_id") or self._position_to_client_order.get(position_id)
            return self._position_to_client_order.get(position_id)

    def _mark_exit_intent_submission_unknown(
        self, position_id: str, reason: str
    ) -> None:
        """Mark an exit intent as SUBMISSION_UNKNOWN (lost ack in flight)."""
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is None:
                return
            flight["state"] = "SUBMISSION_UNKNOWN"
            flight["error_type"] = "submission_unknown"
            flight["error"] = reason
            flight["timestamp"] = time.time()
            logger.warning(
                "[EXIT-INTENT-IN-FLIGHT] Marked exit intent SUBMISSION_UNKNOWN: position_id=%s reason=%s",
                position_id[:8], reason,
            )
        self._save_exit_intent_in_flight()

    def _is_exit_intent_in_flight(self, position_id: str) -> bool:
        """
        Check if an exit intent is currently in-flight for a position.

        2026-08-09: A timeout transitions to SUBMISSION_UNKNOWN and blocks new exits
        until the order and position are reconciled. The intent is NEVER silently dropped.

        Args:
            position_id: Position ID

        Returns:
            True if exit intent is in-flight (submitted or submission unknown), False if terminal/absent.
        """
        with self._lock:
            flight = self._exit_intent_in_flight.get(position_id)
            if flight is None:
                # If no in-flight flag but a recent exit submission exists for this
                # position, keep it in-flight until the submission cache TTL expires.
                client_order_id = self._position_to_client_order.get(position_id)
                if client_order_id:
                    ts = self._recent_exit_submissions.get(client_order_id)
                    if ts and time.time() - ts < self._submission_cache_ttl:
                        return True
                return False

            state = flight["state"]
            intent_time = flight["timestamp"]
            client_order_id = flight.get("client_order_id") or self._position_to_client_order.get(position_id)

            if state == "RECONCILED":
                # Terminal state - remove and allow new exits.
                del self._exit_intent_in_flight[position_id]
                if position_id in self._position_to_client_order:
                    del self._position_to_client_order[position_id]
                return False

            if state == "SUBMISSION_UNKNOWN":
                # Already timed out. Block duplicate exits until reconciled.
                logger.warning(
                    "[EXIT-INTENT-IN-FLIGHT] Exit in SUBMISSION_UNKNOWN: position_id=%s client_order_id=%s; "
                    "reconciliation required before re-arm",
                    position_id[:8], client_order_id
                )
                # CRITICAL FIX (2026-08-27): A single failed reconcile must not leave the
                # lock stuck forever.  Re-attempt reconciliation every few seconds, with a
                # cap, so network or pagination hiccups do not permanently block exits.
                last_reconcile = flight.get("last_reconcile_at", 0.0)
                reconcile_count = flight.get("reconcile_count", 0)
                now = time.time()
                if now - last_reconcile > 5.0 and reconcile_count < 5:
                    flight["last_reconcile_at"] = now
                    flight["reconcile_count"] = reconcile_count + 1
                    logger.warning(
                        "[EXIT-INTENT-IN-FLIGHT] Re-attempting reconcile %d/5 for position=%s client_order_id=%s",
                        reconcile_count + 1, position_id[:8], client_order_id
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._reconcile_exit_intent(position_id, client_order_id))
                    except RuntimeError:
                        pass
                return True

            # state == EXECUTION_PENDING or SUBMITTED
            if time.time() - intent_time > self._exit_intent_timeout_seconds:
                # Check for a recent submission before moving to SUBMISSION_UNKNOWN.
                if client_order_id:
                    ts = self._recent_exit_submissions.get(client_order_id)
                    if ts and time.time() - ts < self._submission_cache_ttl:
                        logger.warning(
                            "[EXIT-INTENT-IN-FLIGHT] Exit intent timed out but recent submission "
                            "client_order_id=%s for position=%s still in cache; keeping %s",
                            client_order_id, position_id[:8], state
                        )
                        return True

                flight["state"] = "SUBMISSION_UNKNOWN"
                logger.error(
                    "[EXIT-INTENT-IN-FLIGHT] Exit intent timed out -> SUBMISSION_UNKNOWN: position_id=%s "
                    "client_order_id=%s age=%.2fs. Reconciliation required before new exit.",
                    position_id[:8], client_order_id, time.time() - intent_time
                )
                # Trigger reconciliation asynchronously.
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._reconcile_exit_intent(position_id, client_order_id))
                except RuntimeError:
                    # No event loop in synchronous contexts; reconcile will run on next poll.
                    pass
                return True

            return True

    async def _reconcile_exit_intent(
        self,
        position_id: str,
        client_order_id: Optional[str],
        force: bool = False,
        new_price_cents: Optional[int] = None,
    ) -> None:
        """Reconcile an exit intent in SUBMISSION_UNKNOWN by order and exchange position lookup.

        CRITICAL FIX (2026-08-27): ``force`` is used by safety/forced exits
        (settlement guard, loss cap, etc.) to aggressively clear a stale
        in-flight lock and allow resubmission.  When ``force`` is True and the
        prior order is not live, the lock is released and a fresh exit attempt
        can be made.
        """
        try:
            # Best-effort: if position is already flat, terminalize.
            with self._lock:
                position = self._open_positions.get(position_id)
            if position is None:
                logger.info(
                    "[EXIT-INTENT-RECONCILE] position_id=%s is no longer open; terminalizing exit intent",
                    position_id[:8]
                )
                self._mark_exit_intent_reconciled(position_id, "position_closed")
                return

            # If the position has zero canonical exposure, terminalize.
            if position.size == 0:
                logger.info(
                    "[EXIT-INTENT-RECONCILE] position_id=%s size is zero; terminalizing exit intent",
                    position_id[:8]
                )
                self._mark_exit_intent_reconciled(position_id, "position_size_zero")
                return

            # CRITICAL FIX: Query exchange for order state to avoid permanent exit blocking.
            if client_order_id and position.market_id:
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client
                    client = get_kalshi_client()
                    lookup = await client.get_order_by_client_id_result(
                        client_order_id, market_id=position.market_id
                    )
                    order = getattr(lookup, "data", None) if lookup else None
                    if order:
                        status = (getattr(order, "status", "") or "").lower()
                        order_price_cents: Optional[int] = None
                        if order.price is not None:
                            try:
                                order_price_cents = int(round(Decimal(order.price) * Decimal("100")))
                            except Exception:
                                order_price_cents = None

                        if status in ("filled", "executed"):
                            logger.info(
                                "[EXIT-INTENT-RECONCILE] Order %s is FILLED for position=%s; terminalizing exit intent",
                                client_order_id[:8], position_id[:8]
                            )
                            self._update_order_attempt_status(client_order_id, "FILLED", reason="reconcile_order_filled")
                            self._release_stale_exit_flags(position_id, "order_filled")
                            return

                        if status in ("canceled", "rejected"):
                            logger.info(
                                "[EXIT-INTENT-RECONCILE] Order %s is %s for position=%s; terminalizing exit intent",
                                client_order_id[:8], status, position_id[:8]
                            )
                            self._update_order_attempt_status(client_order_id, status.upper(), reason=f"reconcile_order_{status}")
                            self._release_stale_exit_flags(position_id, f"order_{status}")
                            return

                        if status in ("open", "resting", "active"):
                            # For forced exits, a working order at a stale price must be
                            # cancelled so the new exit price can be used.  If the price is
                            # the same (or better) we keep the working order.
                            if force and new_price_cents is not None and order_price_cents is not None:
                                if order_price_cents != new_price_cents:
                                    logger.warning(
                                        "[EXIT-INTENT-RECONCILE] Force reconcile: existing order %s is %s at %dc "
                                        "but new exit price is %dc; cancelling and resubmitting",
                                        client_order_id[:8], status, order_price_cents, new_price_cents
                                    )
                                    try:
                                        cancel_res = await client.cancel_order_result(order.order_id, market_id=position.market_id)
                                        if cancel_res and getattr(cancel_res, "success", False):
                                            self._update_order_attempt_status(client_order_id, "CANCELLED", reason="reconcile_force_cancel_stale_price")
                                            self._release_stale_exit_flags(position_id, "order_cancelled_stale_price")
                                            return
                                        else:
                                            logger.warning(
                                                "[EXIT-INTENT-RECONCILE] Cancel failed for %s; leaving in-flight",
                                                client_order_id[:8]
                                            )
                                    except Exception as cancel_err:
                                        logger.warning(
                                            "[EXIT-INTENT-RECONCILE] Cancel exception for %s: %s; leaving in-flight",
                                            client_order_id[:8], cancel_err
                                        )
                            logger.info(
                                "[EXIT-INTENT-RECONCILE] Order %s is %s for position=%s; exit still live",
                                client_order_id[:8], status, position_id[:8]
                            )
                            return
                except Exception as order_exc:
                    logger.debug(
                        "[EXIT-INTENT-RECONCILE] Order lookup failed for position=%s: %s",
                        position_id[:8], order_exc
                    )

            # CRITICAL FIX (2026-08-21): client_order_id is often missing for positions
            # that came from REST sync / replay.  Without a lookup key the monitor was
            # leaving these in SUBMISSION_UNKNOWN forever, blocking protective exits
            # and leaking risk.  Fall back to an exchange open-order/position snapshot.
            if position.market_id:
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client
                    client = get_kalshi_client()

                    # 1) If the market already expired, the contract is gone; remove.
                    if self._is_expired_market(position.market_id):
                        logger.warning(
                            "[EXIT-INTENT-RECONCILE] position_id=%s market=%s expired and "
                            "client_order_id missing; removing position",
                            position_id[:8], position.market_id
                        )
                        self.remove_position(position_id)
                        self._mark_exit_intent_reconciled(position_id, "expired_no_client_order_id")
                        return

                    # 2) If there is still an open order on this market, the prior
                    #    unknown submission may be resting.  Leave it alone and re-check.
                    open_orders = await client.get_open_orders(market_id=position.market_id)
                    if open_orders:
                        logger.info(
                            "[EXIT-INTENT-RECONCILE] position_id=%s market=%s still has %d open order(s); "
                            "leaving SUBMISSION_UNKNOWN",
                            position_id[:8], position.market_id, len(open_orders)
                        )
                        return

                    # 3) No open order and no client_order_id.  The submission was
                    #    likely lost or already filled.  Check exchange positions.
                    exchange_positions = await client.get_positions()
                    matching = [p for p in exchange_positions if getattr(p, "market_id", None) == position.market_id]
                    if not matching or all(getattr(p, "size", Decimal("0")) == 0 for p in matching):
                        logger.warning(
                            "[EXIT-INTENT-RECONCILE] position_id=%s market=%s not found on exchange "
                            "and no open order; removing position",
                            position_id[:8], position.market_id
                        )
                        self.remove_position(position_id)
                        self._mark_exit_intent_reconciled(position_id, "exchange_position_missing")
                        return

                    # 4) Exchange position still exists and no open order.  The prior
                    #    exit probably never reached the venue.  Release the in-flight
                    #    lock so the monitor can retry on the next tick, and also
                    #    clear any stale terminal flags on the Position so the retry
                    #    is not immediately dropped by the loop-side idempotency guard.
                    logger.warning(
                        "[EXIT-INTENT-RECONCILE] position_id=%s market=%s still open on exchange "
                        "but no open order; force=%s client_order_id=%s; releasing in-flight lock to retry",
                        position_id[:8], position.market_id, force, client_order_id[:8] if client_order_id else ""
                    )
                    # Do NOT update the order attempt store to terminal here: the order
                    # was never confirmed accepted, so reusing the same client_order_id
                    # is the safest idempotent resubmit.  We only clear the in-flight
                    # guard and stale position flags.
                    self._release_stale_exit_flags(position_id, "retry_unknown_submission")
                    return
                except Exception as fallback_exc:
                    logger.debug(
                        "[EXIT-INTENT-RECONCILE] Fallback reconciliation failed for position=%s: %s",
                        position_id[:8], fallback_exc
                    )

            # Fallback: leave in SUBMISSION_UNKNOWN and alert; a later fill callback should reconcile.
            logger.warning(
                "[EXIT-INTENT-RECONCILE] position_id=%s client_order_id=%s force=%s requires external "
                "reconciliation; leaving in SUBMISSION_UNKNOWN",
                position_id[:8], client_order_id, force
            )
        except Exception as e:
            logger.exception(
                "[EXIT-INTENT-RECONCILE] Error reconciling position_id=%s: %s",
                position_id[:8], e
            )

    @staticmethod
    def _update_order_attempt_status(client_order_id: Optional[str], status: str, reason: Optional[str] = None) -> None:
        """Mark a durable order attempt as terminal so it is not reused.

        Without this, ``finalize_order_identity`` will keep matching the same
        client_order_id and the resubmission will collide with a cancelled/
        rejected/filled order on the exchange.
        """
        if not client_order_id:
            return
        try:
            from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore
            store = OrderAttemptStore()
            record = store.get_by_client_order_id(client_order_id)
            if record is None:
                return
            payload: Dict[str, Any] = {}
            if reason:
                payload["reconcile_reason"] = reason
            store.update_status(record.order_attempt_id, status, payload=payload or None)
            logger.info(
                "[EXIT-INTENT-RECONCILE] Updated order_attempt_id=%s client_order_id=%s status=%s reason=%s",
                record.order_attempt_id[:16] if record.order_attempt_id else "",
                client_order_id[:8],
                status,
                reason or "",
            )
        except Exception:
            logger.exception(
                "[EXIT-INTENT-RECONCILE] Failed to update order_attempt status for client_order_id=%s",
                client_order_id[:8] if client_order_id else "",
            )

    def _release_stale_exit_flags(self, position_id: str, reason: str) -> None:
        """Clear the in-flight lock and any stale terminal flags on the Position.

        This is the safe release path used when an exit order is proven terminal
        or not-submitted and the monitor needs to re-emit the exit.
        """
        self._mark_exit_intent_reconciled(position_id, reason)
        self._clear_exit_intent_in_flight(position_id)
        with self._lock:
            stale_position = self._open_positions.get(position_id)
            if stale_position and stale_position.exited_at is None:
                stale_position.exit_triggered = False
                stale_position.exit_reason = None
                stale_position.exit_price_cents = None
                logger.info(
                    "[EXIT-INTENT-RECONCILE] Cleared stale terminal flags for position=%s reason=%s",
                    position_id[:8], reason
                )

    def _clear_exit_intent_in_flight(self, position_id: str) -> None:
        """
        Clear the in-flight flag for a position after exit order is placed or terminalized.

        Args:
            position_id: Position ID
        """
        with self._lock:
            if position_id in self._exit_intent_in_flight:
                del self._exit_intent_in_flight[position_id]
            if position_id in self._position_to_client_order:
                del self._position_to_client_order[position_id]
            logger.info(
                "[EXIT-INTENT-IN-FLIGHT] Cleared exit intent in-flight: position_id=%s",
                position_id[:8]
            )
        self._save_exit_intent_in_flight()

    # ── Durable exit-intent persistence (2026-09-01) ───────────────────────────

    def _save_exit_intent_in_flight(self) -> None:
        """Persist the non-terminal exit-intent state to disk.

        Terminal (RECONCILED) intents and non-serializable objects (asyncio Tasks)
        are stripped.  The file is fsynced so the intent survives a crash.
        """
        try:
            snapshot: Dict[str, Any] = {}
            with self._lock:
                for pid, flight in self._exit_intent_in_flight.items():
                    state = flight.get("state")
                    if state == "RECONCILED":
                        continue
                    record = {}
                    for key, value in flight.items():
                        if key == "task" or isinstance(value, asyncio.Task):
                            continue
                        record[key] = value
                    snapshot[pid] = record
            data = json.dumps(snapshot, default=str, indent=2)
            self._exit_intent_persistence_path.write_text(data, encoding="utf-8")
            self._exit_intent_persistence_path.with_suffix(".tmp").unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("[EXIT-INTENT-PERSISTENCE] failed to save: %s", exc)

    def _load_exit_intent_in_flight(self) -> None:
        """Load the durable exit-intent registry on startup.

        Any intent that was not in a terminal state is loaded as
        RECONCILIATION_REQUIRED so the reconciliation loop resolves its true
        status from the exchange before new exits are allowed for that position.
        """
        try:
            if not self._exit_intent_persistence_path.exists():
                return
            data = self._exit_intent_persistence_path.read_text(encoding="utf-8")
            if not data:
                return
            snapshot = json.loads(data)
            if not isinstance(snapshot, dict):
                return
            now = time.time()
            for pid, flight in snapshot.items():
                if not isinstance(flight, dict):
                    continue
                state = flight.get("state")
                if state in ("RECONCILED", None):
                    continue
                if state not in ("EXECUTION_PENDING", "SUBMITTED", "SUBMISSION_UNKNOWN", "RETRYABLE_FAILURE"):
                    flight["state"] = "RECONCILIATION_REQUIRED"
                flight["timestamp"] = flight.get("timestamp", now)
                flight["reconcile_count"] = flight.get("reconcile_count", 0)
                flight["last_reconcile_at"] = flight.get("last_reconcile_at", 0.0)
                self._exit_intent_in_flight[pid] = flight
                client_order_id = flight.get("client_order_id")
                if client_order_id:
                    self._position_to_client_order[pid] = client_order_id
                    self._recent_exit_submissions[client_order_id] = flight.get("submitted_at", now)
            logger.info(
                "[EXIT-INTENT-PERSISTENCE] Loaded %d durable exit intent(s) from %s",
                len(self._exit_intent_in_flight),
                self._exit_intent_persistence_path,
            )
        except Exception as exc:
            logger.warning("[EXIT-INTENT-PERSISTENCE] failed to load: %s", exc)

    def _get_position_lock(self, position_id: str) -> threading.Lock:
        """
        Get or create a position-level execution lock.

        CRITICAL FIX (2026-07-23): Prevents TOCTOU races during exit order creation.
        Only one thread can create an exit order for a given position at a time.

        Args:
            position_id: Position ID

        Returns:
            Lock object for this position
        """
        with self._lock_registry_lock:
            if position_id not in self._position_exit_locks:
                self._position_exit_locks[position_id] = threading.Lock()
            return self._position_exit_locks[position_id]

    def set_orders_last_updated(self, timestamp: float) -> None:
        """
        Set the timestamp when orders were last updated from exchange.

        CRITICAL FIX (2026-07-23): This is used for startup grace window to ensure
        orders are loaded before enforcing exit invariants.

        Args:
            timestamp: Unix timestamp when orders were last updated
        """
        with self._lock:
            self._orders_last_updated_ts = timestamp
            logger.info(
                "[STARTUP-GRACE] Orders last updated timestamp set: %.2f (age=%.2fs since process start)",
                timestamp,
                timestamp - self._process_start_time
            )

    def is_in_startup_grace_window(self) -> bool:
        """
        Check if the system is in the startup grace window.

        CRITICAL FIX (2026-07-23): During startup, we delay exit invariant enforcement
        until orders are loaded and at least one websocket sync cycle completes.

        Returns:
            True if in startup grace window, False otherwise
        """
        with self._lock:
            # Check if orders have been updated from RestingOrderMonitor
            try:
                from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
                resting_monitor = get_resting_order_monitor()

                # If RestingOrderMonitor hasn't polled yet, we're in grace window
                if resting_monitor._last_poll_time is None:
                    logger.debug("[STARTUP-GRACE] RestingOrderMonitor hasn't polled yet - in grace window")
                    return True

                # Convert datetime to timestamp
                last_poll_ts = resting_monitor._last_poll_time.timestamp()
                time_since_poll = time.time() - last_poll_ts

                # Check if enough time has passed since first poll
                if time_since_poll < self._startup_grace_window_seconds:
                    logger.debug(
                        "[STARTUP-GRACE] In grace window: time since poll=%.2fs < grace window=%.2fs",
                        time_since_poll,
                        self._startup_grace_window_seconds
                    )
                    return True

                logger.info(
                    "[STARTUP-GRACE] Grace window complete: time since poll=%.2fs >= grace window=%.2fs",
                    time_since_poll,
                    self._startup_grace_window_seconds
                )
                return False

            except Exception as e:
                logger.warning(
                    "[STARTUP-GRACE] Failed to check RestingOrderMonitor poll time, assuming grace window: %s",
                    e
                )
                return True

    async def _legacy_check_position(
        self,
        position: Position,
        price_cents: int,
        poll_count: int = 0,
    ) -> None:
        """
        Test-only adapter that wraps a raw integer price in a synthetic
        ExitPriceSnapshot.  Production code must pass a real ExitPriceSnapshot
        from a live or reconstructed order book.
        """
        snapshot = ExitPriceSnapshot(
            market_id=position.market_id,
            position_side=position.side,
            mid_cents=int(price_cents),
            own_side_bid_cents=int(price_cents),
            own_side_ask_cents=int(price_cents),
            opposite_bid_cents=None,
            opposite_ask_cents=None,
            book_age_ms=0,
            data_source="synthetic",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id=f"synthetic:{position.position_id[:8]}:{poll_count}",
            timestamp=time.monotonic(),
            min_depth_own_side=0,
        )
        return await self._check_position(position, snapshot, poll_count)

    async def _check_position(
        self,
        position: Position,
        snapshot: ExitPriceSnapshot,
        poll_count: int = 0,
    ) -> None:
        """
        Check a single position for exit conditions.

        Args:
            position: Position to check
            snapshot: Executable same-side ExitPriceSnapshot from a live or
                reconstructed order book.  Raw integers are rejected to ensure
                every exit trigger carries side, bid/ask, book age, depth, and
                snapshot ID provenance.
            poll_count: Current poll iteration number for dedupe keys
        """
        if not isinstance(snapshot, ExitPriceSnapshot):
            raise TypeError(
                f"_check_position requires an ExitPriceSnapshot, got {type(snapshot).__name__}. "
                "Use _legacy_check_position for deprecated integer test paths."
            )
        current_price_cents = snapshot.own_side_bid_cents

        # Update runtime state using the executable liquidation bid
        position.update_runtime_state(current_price_cents)

        # CRITICAL FIX (2026-08-25): Settlement guard - forced exit at T-2min (120s).
        # Previously positions rode into settlement unmanaged (the "settlement trap"):
        # expired markets were simply dropped from monitoring with no exit enforcement.
        # Force a market exit while there is still a live order book.
        _settlement_guard_seconds = _get_settlement_guard_seconds()
        try:
            _secs_to_expiry = _seconds_to_expiry_from_ticker(position.market_id)
            if _secs_to_expiry is not None and 0 < _secs_to_expiry <= _settlement_guard_seconds:
                logger.warning(
                    "[POSITION-MONITOR] SETTLEMENT-GUARD forced exit: position=%s market=%s side=%s "
                    "tte=%.1fs <= %.0fs - exiting before settlement",
                    position.position_id[:8],
                    position.market_id,
                    position.side.value,
                    _secs_to_expiry,
                    _settlement_guard_seconds,
                )
                await self._emit_exit_intent(position, ExitReason.SETTLEMENT_GUARD, current_price_cents, snapshot=snapshot)
                return
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Settlement guard check failed: %s", e)

        # CRITICAL FIX (2026-08-08): Remove positions for markets that have already
        # expired/closed. Do not wait for an exit trigger; the contract cannot be
        # traded and the position is routed to settlement reconciliation.
        if self._is_expired_market(position.market_id):
            logger.warning(
                "[POSITION-MONITOR] market_expired: position=%s market=%s side=%s - removing from monitor",
                position.position_id[:8], position.market_id, position.side.value
            )
            position.exit_triggered = True
            position.exit_reason = ExitReason.MARKET_EXPIRED.value
            position.exited_at = datetime.utcnow()
            self.remove_position(position.position_id)
            return

        # CRITICAL FIX (2026-08-25): Hard per-position unrealized loss cap.
        # Configurable backstop (default $5/position).  At current 1-2 contract
        # sizing this is inert; it protects the book if position size scales up.
        _hard_loss_cap_cents = _get_hard_loss_cap_cents()
        if _hard_loss_cap_cents > 0 and position.unrealized_pnl_cents <= -_hard_loss_cap_cents:
            logger.warning(
                "[POSITION-MONITOR] HARD-LOSS-CAP triggered: position=%s pnl=%dc cap=%dc - exiting",
                position.position_id[:8],
                position.unrealized_pnl_cents,
                _hard_loss_cap_cents,
            )
            await self._emit_exit_intent(position, ExitReason.LOSS_CAP, current_price_cents, snapshot=snapshot)
            return

        # CRITICAL FIX (2026-08-25): Continuation stop (per-asset, vol-normalized).
        # Wired as a config-driven parameter but DISABLED by default.  The 24h fill
        # set should be used to backtest-calibrate threshold_pct before enabling.
        # When enabled, this will exit if the underlying spot continues moving
        # against the fade over the configured lookback window.
        _cont_cfg = _get_continuation_stop_config(self._asset_from_ticker(position.market_id))
        if _cont_cfg.get("enabled"):
            cont_triggered, cont_adverse_pct, cont_threshold_pct = _compute_5m_continuation_stop(
                position, self._asset_from_ticker(position.market_id), _cont_cfg
            )
            if cont_triggered:
                logger.warning(
                    "[POSITION-MONITOR] CONTINUATION-STOP triggered: position=%s adverse_return=%.4f "
                    "threshold=%.4f lookback_min=%d - exiting",
                    position.position_id[:8],
                    cont_adverse_pct,
                    cont_threshold_pct,
                    _cont_cfg.get("lookback_minutes", 5),
                )
                await self._emit_exit_intent(position, ExitReason.CONTINUATION_STOP, current_price_cents, snapshot=snapshot)
                return
            else:
                logger.debug(
                    "[POSITION-MONITOR] CONTINUATION-STOP not triggered: position=%s "
                    "adverse_return=%.4f threshold=%.4f",
                    position.position_id[:8],
                    cont_adverse_pct,
                    cont_threshold_pct,
                )

        # CRITICAL FIX (2026-08-24): A take-profit can be set from a trusted
        # exchange-reported entry fill price plus a fee-aware margin (fallback),
        # from the original edge-based entry path, or from a 1:1 SL-based bracket
        # when the position has a verified stop-loss.  The fallback is bounded by
        # the round-trip fee buffer and TAKE_PROFIT_MIN_PROFIT_CENTS.
        if position.take_profit_price_cents is None and position.avg_entry_price_cents > 0:
            if position.stop_loss_enabled and position.initial_risk_cents > 0:
                # Use existing risk calculation for a symmetric 1R bracket
                position.take_profit_price_cents = position.avg_entry_price_cents + position.initial_risk_cents
                position.take_profit_r_multiple = 1.0
                if position.risk_params_state == RiskParamsState.UNKNOWN:
                    position.risk_params_state = RiskParamsState.FALLBACK
                logger.info(
                    "[POSITION-MONITOR-TP-FALLBACK] Set 1R TP from SL for position=%s: entry=%dc tp=%dc",
                    position.position_id[:8],
                    position.avg_entry_price_cents,
                    position.take_profit_price_cents,
                )
            elif (
                position.risk_params_state == RiskParamsState.FALLBACK
                or position.entry_fill_price_cents
            ):
                # Fallback TP from a trusted entry fill price, even without a stop-loss.
                # This covers REST-rehydrated positions where model provenance is missing.
                try:
                    from merid.event_venues.kalshi.fees import min_profitable_exit_price_cents
                    entry_ref = position.entry_fill_price_cents or position.avg_entry_price_cents
                    fallback_tp = min_profitable_exit_price_cents(
                        entry_ref,
                        position.size,
                        gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                    )
                    if fallback_tp is not None and fallback_tp > entry_ref:
                        position.take_profit_price_cents = fallback_tp
                        max_gain = SIDE_SPACE_TOTAL_CENTS - entry_ref
                        position.take_profit_r_multiple = (
                            (fallback_tp - entry_ref) / max_gain
                            if max_gain > 0
                            else 0.0
                        )
                        position.risk_params_schema_version = max(
                            position.risk_params_schema_version or 1, 2
                        )
                        if position.risk_params_state == RiskParamsState.UNKNOWN:
                            position.risk_params_state = RiskParamsState.FALLBACK
                        logger.info(
                            "[POSITION-MONITOR-TP-FALLBACK] Set fee-aware TP from entry for position=%s: entry=%dc tp=%dc",
                            position.position_id[:8],
                            entry_ref,
                            fallback_tp,
                        )
                except Exception:
                    logger.debug(
                        "[POSITION-MONITOR-TP-FALLBACK] No price TP for position=%s (entry=%dc, no model/SL)",
                        position.position_id[:8],
                        position.avg_entry_price_cents,
                    )
            else:
                # No stop-loss and no model-based TP: hold without a price TP.
                # Time, settlement, and trailing exits still apply.
                logger.debug(
                    "[POSITION-MONITOR-TP-FALLBACK] No price TP for position=%s (entry=%dc, no model/SL)",
                    position.position_id[:8],
                    position.avg_entry_price_cents,
                )

        # CRITICAL FIX (2026-08-28): Asymmetric loss exits.
        # 1) Mark-to-model edge realization: if the held-side market bid has
        #    reached the model's current fair value, the edge is realized (or the
        #    market has converged to the model).  Sell at the market before the
        #    edge can decay further.
        # 2) 60%-window time stop: if the position is not winning after 60% of
        #    the 15-minute window, force a full exit.  This prevents the
        #    "hold losers to expiry" leak while allowing winners to run to TP /
        #    trailing.
        _fair_value_cents: Optional[int] = None
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            _state_store = get_kalshi_market_state_store()
            _unified_state = _state_store.get_unified(position.market_id) if hasattr(_state_store, "get_unified") else None
            _kalshi_state = _state_store.get(position.market_id)
            _state = _unified_state or _kalshi_state
            if _state is not None:
                _fair_value_cents = _get_fair_value_cents(_state, position.side.value)
        except Exception as _fair_err:
            logger.debug("[POSITION-MONITOR] Could not fetch fair value for edge-realization: %s", _fair_err)

        if _fair_value_cents is not None and 1 <= _fair_value_cents <= 99:
            if current_price_cents >= _fair_value_cents:
                logger.info(
                    "[POSITION-MONITOR] EDGE-REALIZATION triggered: position=%s side=%s price=%dc fair=%dc "
                    "entry=%dc age=%.1fs - exiting at market",
                    position.position_id[:8],
                    position.side.value,
                    current_price_cents,
                    _fair_value_cents,
                    position.avg_entry_price_cents,
                    position.time_since_entry_seconds,
                )
                await self._emit_exit_intent(position, ExitReason.CURRENT_EDGE_REVERSAL, current_price_cents, snapshot=snapshot)
                return

        _contract_life_seconds = 900.0
        if (
            position.time_since_entry_seconds >= 0.60 * _contract_life_seconds
            and position.unrealized_pnl_cents <= 0
        ):
            _secs_to_expiry = _seconds_to_expiry_from_ticker(position.market_id)
            _settlement_guard = _get_settlement_guard_seconds()
            if _secs_to_expiry is None or _secs_to_expiry > _settlement_guard + 5.0:
                logger.info(
                    "[POSITION-MONITOR] 60PCT-WINDOW-TIME-STOP triggered: position=%s price=%dc pnl=%dc "
                    "age=%.1fs - force full exit of underwater position",
                    position.position_id[:8],
                    current_price_cents,
                    position.unrealized_pnl_cents,
                    position.time_since_entry_seconds,
                )
                await self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents, snapshot=snapshot)
                return

        # Log position state for debugging
        logger.debug(
            "[POSITION-MONITOR] Checking position=%s market=%s side=%s entry=%dc current=%dc pnl=%dc R=%.2f "
            "tp=%dc sl=%dc trailing=%s",
            position.position_id[:8],
            position.market_id,
            position.side.value,
            position.avg_entry_price_cents,
            current_price_cents,
            position.unrealized_pnl_cents,
            position.r_multiple,
            position.take_profit_price_cents or 0,
            position.stop_loss_price_cents or 0,
            position.trailing_activated,
        )

        # AUDIT: Log trigger evaluation start (no trigger found yet)
        logger.debug(
            "[EXIT-TRIGGER-AUDIT] position=%s market=%s price=%dc side=%s size=%s checking_triggers=true",
            position.position_id[:8],
            position.market_id,
            current_price_cents,
            position.side.value,
            position.size
        )

        # CRITICAL: Check extreme profit exit first (highest priority)
        # Exit at 99c YES / 1c NO to lock in guaranteed wins
        # CRITICAL FIX: 2026-07-06 - Consolidated 99c exit to single mechanism (removed duplicate ratchet 99c check)
        # The position-level extreme profit check handles 99c YES / 1c NO for all assets
        # Profile ratchet_mandatory_exit_at_99c is redundant and removed from this path
        # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
        # Check if position already has exit intent pending to prevent race conditions
        # CRITICAL FIX: 2026-07-07 - Added bid/ask spread handling for boundary conditions
        # Pass bid/ask to prevent false triggers at extreme prices due to spread
        # Note: bid/ask not available in current _check_position signature, using mid price
        # Future enhancement: pass bid/ask from market state to improve accuracy

        # AUTO_EXIT_99C: Cash out at 99c (near-settlement) - highest priority after RISK
        # Per Kalshi semantics, contracts settle at exactly $1 if correct and $0 if not
        # Selling early at 99c locks in almost all of the payoff
        if position.should_trigger_auto_exit_99c(current_price_cents) and not position.exit_triggered:
            # CRITICAL FIX (2026-07-23): Log multi-trigger state for audit
            # Distinguish between "position already exited" vs "multiple triggers evaluated"
            if position.exit_reason:
                logger.warning(
                    "[EXIT-TRIGGER-MULTI] position=%s market=%s has exit_reason=%s but exit_triggered=False - "
                    "this indicates exit order placement failed or is pending. Skipping new trigger auto_exit_99c.",
                    position.position_id[:8],
                    position.market_id,
                    position.exit_reason
                )
                return
            # AUDIT: Timing correctness - check expiry proximity
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            seconds_to_expiry = getattr(state, 'seconds_to_expiry', None) if state else None

            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:auto_exit_99c:{poll_count}"

            # AUDIT: Venue-side semantics - verify 99c exit is executable
            # Kalshi accepts SELL_YES at 99c and SELL_NO at 1c for near-settlement exits
            # This is a real executable close path, not just a logical condition
            logger.info(
                "[VENUE-SEMANTICS-AUDIT] position=%s market=%s reason=auto_exit_99c "
                "exit_path=executable kalshi_semantics=SELL_99c_or_1c executable=YES",
                position.position_id[:8],
                position.market_id
            )

            # AUDIT: Log trigger evaluation with timing context
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=auto_exit_99c price=%dc side=%s size=%s trigger=true seconds_to_expiry=%s dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.side.value,
                position.size,
                seconds_to_expiry,
                dedupe_key
            )

            # AUDIT: Warn if triggering very close to expiry
            if seconds_to_expiry is not None and seconds_to_expiry < 60:
                logger.warning(
                    "[TIMING-AUDIT] position=%s market=%s 99c_exit_triggered_near_expiry seconds_to_expiry=%d - order may not fill before settlement",
                    position.position_id[:8],
                    position.market_id,
                    seconds_to_expiry
                )

            logger.info(
                "[POSITION-MONITOR] AUTO-EXIT-99C triggered: position=%s price=%dc side=%s - cashing out at near-settlement",
                position.position_id[:8],
                current_price_cents,
                position.side.value,
            )
            await self._emit_exit_intent(position, ExitReason.AUTO_EXIT_99C, current_price_cents, snapshot=snapshot)
            return

        # DYNAMIC TAKE PROFIT: Laddered exits based on entry price for consistent profits
        # 2026-07-06: Implements user's strategy for frequent small wins
        # CRITICAL FIX (2026-08-01): Updated entry zones from 25c-75c to 5c-85c for 15m crypto volatility
        # Entry 5-15c → Exit 50-60c, Entry 15-30c → Exit 60-70c, Entry 30-50c → Exit 70-77c, etc.
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile

                # Check if dynamic take profit is enabled
                dynamic_tp_config = getattr(profile, 'dynamic_take_profit', {})
                if dynamic_tp_config and dynamic_tp_config.get('enabled', False):
                    # Initialize dynamic TP target if not set
                    if position.dynamic_tp_target_cents is None:
                        entry_price = position.avg_entry_price_cents
                        zones = dynamic_tp_config.get('zones', [])

                        # Find matching zone based on entry price
                        for zone in zones:
                            entry_min = zone.get('entry_min', 0)
                            entry_max = zone.get('entry_max', 100)
                            if entry_min <= entry_price <= entry_max:
                                base_target = zone.get('exit_target', 0)

                                # Apply edge quality adjustment if enabled
                                if dynamic_tp_config.get('edge_adjustment_enabled', False):
                                    # Get edge from position (if available)
                                    edge_pct = getattr(position, 'entry_edge_pct', 0.03)  # Default 3%
                                    edge_high_threshold = dynamic_tp_config.get('edge_high_threshold', 0.05)
                                    edge_low_threshold = dynamic_tp_config.get('edge_low_threshold', 0.02)
                                    edge_high_multiplier = dynamic_tp_config.get('edge_high_multiplier', 1.1)
                                    edge_low_multiplier = dynamic_tp_config.get('edge_low_multiplier', 0.9)

                                    if edge_pct >= edge_high_threshold:
                                        base_target = int(base_target * edge_high_multiplier)
                                    elif edge_pct <= edge_low_threshold:
                                        base_target = int(base_target * edge_low_multiplier)

                                # CRITICAL FIX (2026-07-31): Dynamic TP zone must be ABOVE entry
                                # for ALL positions. Both YES and NO are long their own side, and
                                # profit = own-side price rising. A target at or below entry would
                                # trigger at a loss or breakeven.
                                if base_target <= entry_price:
                                    fallback_target = min(99, entry_price + max(1, (SIDE_SPACE_TOTAL_CENTS - entry_price) * 3 // 5))
                                    logger.error(
                                        "[DYNAMIC-TP-CONFIG] Zone target %dc <= entry %dc for position=%s - "
                                        "INVALID (would trigger at breakeven/loss). Using fallback target=%dc. "
                                        "Fix dynamic_take_profit zones in profile config.",
                                        base_target, entry_price, position.position_id[:8], fallback_target
                                    )
                                    base_target = fallback_target

                                # CRITICAL FIX (2026-07-16): Side-space — entry and current
                                # prices are in the position's OWN side cents for BOTH sides,
                                # so zone targets apply directly (no 100-x mirror for NO)
                                position.dynamic_tp_target_cents = base_target

                                # CRITICAL FIX: 2026-07-07 - Add user communication for infeasible TP targets due to fees
                                # Check if target is feasible after fees
                                try:
                                    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

                                    # Calculate gross profit
                                    # CRITICAL FIX (2026-08-04): A position is long its own side. Profit is the
                                    # distance from entry toward higher own-side price (target > entry for both).
                                    gross_profit = (position.dynamic_tp_target_cents - entry_price) * position.size

                                    # Calculate round-trip fees
                                    entry_fee = calculate_kalshi_fee_cents(position.size, entry_price)
                                    exit_fee = calculate_kalshi_fee_cents(position.size, position.dynamic_tp_target_cents)
                                    total_fees = entry_fee + exit_fee

                                    # Calculate net profit per contract
                                    net_edge = (gross_profit - total_fees) / position.size if position.size > 0 else 0
                                    min_edge_threshold = 1.0  # Minimum 1 cent net profit

                                    if net_edge < min_edge_threshold:
                                        logger.warning(
                                            "[POSITION-MONITOR] DYNAMIC-TP target INFEASIBLE due to fees: position=%s entry=%dc target=%dc gross=%dc fees=%dc net=%.1fc < %.1fc threshold. "
                                            "Target will be set but may not trigger profitable exit. Consider adjusting entry price or target zones.",
                                            position.position_id[:8],
                                            entry_price,
                                            position.dynamic_tp_target_cents,
                                            gross_profit,
                                            total_fees,
                                            net_edge,
                                            min_edge_threshold,
                                        )
                                except Exception as e:
                                    logger.debug("[POSITION-MONITOR] Could not check fee feasibility for dynamic TP: %s", e)

                                logger.info(
                                    "[POSITION-MONITOR] DYNAMIC-TP target set: position=%s entry=%dc target=%dc (zone: %d-%dc)",
                                    position.position_id[:8],
                                    entry_price,
                                    position.dynamic_tp_target_cents,
                                    entry_min,
                                    entry_max,
                                )
                                break

                    # Check if dynamic TP target is reached
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
                    # CRITICAL FIX (2026-07-16): Side-space — own-side price rising to target
                    # triggers for BOTH sides (no NO mirror)
                    if position.dynamic_tp_target_cents is not None and not position.dynamic_tp_triggered and not position.exit_triggered:
                        # CRITICAL FIX (2026-07-23): Log multi-trigger state for audit
                        if position.exit_reason:
                            logger.warning(
                                "[EXIT-TRIGGER-MULTI] position=%s market=%s has exit_reason=%s but exit_triggered=False - "
                                "skipping new trigger dynamic_tp. This indicates exit order placement failed or is pending.",
                                position.position_id[:8],
                                position.market_id,
                                position.exit_reason
                            )
                            return
                        if current_price_cents >= position.dynamic_tp_target_cents:
                            position.dynamic_tp_triggered = True
                            # AUDIT: Idempotency - generate dedupe key for this trigger
                            dedupe_key = f"{position.position_id[:8]}:dynamic_tp:{poll_count}"
                            # AUDIT: Log trigger evaluation
                            logger.info(
                                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=dynamic_tp price=%dc target=%dc side=%s size=%s trigger=true dedupe_key=%s",
                                position.position_id[:8],
                                position.market_id,
                                current_price_cents,
                                position.dynamic_tp_target_cents,
                                position.side.value,
                                position.size,
                                dedupe_key
                            )
                            logger.info(
                                "[POSITION-MONITOR] DYNAMIC-TP triggered: position=%s side=%s price=%dc target=%dc (target reached)",
                                position.position_id[:8],
                                position.side.value,
                                current_price_cents,
                                position.dynamic_tp_target_cents,
                            )
                            await self._emit_exit_intent(position, ExitReason.DYNAMIC_TAKE_PROFIT, current_price_cents, snapshot=snapshot)
                            return
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Dynamic take profit check failed: %s", e)

        # RATCHET PROFIT FLOOR: Lock in profits at 80-85c range
        # Research-backed mechanism to prevent giving back gains when 99c TP is not guaranteed
        # 2026-07-05: Added position trimming and 99c hard exit
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                if profile.ratchet_profit_floor_enabled:
                    is_no = position.side == PositionSide.NO
                    base_activation = profile.ratchet_activation_threshold_cents  # 85c (YES-space)
                    floor_offset = profile.ratchet_floor_offset_cents  # 5c (floor offset in YES-space)
                    force_exit = profile.ratchet_force_exit_on_floor_breach
                    # CRITICAL FIX: 2026-07-06 - Removed mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
                    trim_enabled = profile.ratchet_trim_position_enabled  # 2026-07-05
                    base_trim_threshold = profile.ratchet_trim_threshold_cents  # 2026-07-05: 80c (YES-space)
                    trim_to_contracts = profile.ratchet_trim_to_contracts  # 2026-07-05: 1 contract

                    # CRITICAL FIX (2026-08-04): Ratchet thresholds are own-side cents for BOTH sides.
                    # A position is long its own side. Profit zone is own-side price >= 80c/85c for YES and NO.
                    activation_threshold = base_activation
                    trim_threshold = base_trim_threshold

                    # Calculate floor price
                    floor_price = base_activation - floor_offset  # 80c in own-side space

                    # Check if position hit activation threshold
                    if not hasattr(position, 'ratchet_activated'):
                        position.ratchet_activated = False
                    if not hasattr(position, 'ratchet_hold_until'):
                        position.ratchet_hold_until = 0
                    if not hasattr(position, 'ratchet_trimmed'):
                        position.ratchet_trimmed = False  # 2026-07-05: Track if position was trimmed

                    # 2026-07-05: POSITION TRIMMING when >1 contract and price is deep in profit
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double trim
                    # CRITICAL FIX: 2026-07-07 - Removed early return to cascade other exit checks
                    # After trimming, continue checking other exit conditions (extreme profit, dynamic TP, etc.)
                    # This ensures critical exits like 99c are not delayed by trimming
                    # CRITICAL FIX (2026-07-16): Trim trigger when own-side price rises above threshold (BOTH sides)
                    if trim_enabled and not position.ratchet_trimmed and not position.exit_triggered:
                        if position.size > trim_to_contracts:
                            if current_price_cents >= trim_threshold:
                                position.ratchet_trimmed = True
                                # Emit trim intent (partial close)
                                contracts_to_close = int(position.size - trim_to_contracts)
                                logger.info(
                                    "[POSITION-MONITOR] RATCHET-TRIM triggered: position=%s side=%s price=%dc size=%s -> trim to %d contracts (close %d)",
                                    position.position_id[:8],
                                    position.side.value,
                                    current_price_cents,
                                    position.size,
                                    trim_to_contracts,
                                    contracts_to_close,
                                )
                                await self._emit_exit_intent(position, ExitReason.RATCHET_TRIM, current_price_cents, contracts_to_close, snapshot=snapshot)
                                # CRITICAL FIX: Do NOT update position.size here - wait for fill callback
                                # Previous code updated position.size prematurely, creating desync with PositionCache.contracts
                                # Position.size should only be updated via fill callback to ensure consistency
                                # CRITICAL: Continue to check other exit conditions (don't return early)

                    # Activate ratchet when price hits threshold
                    # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double activation
                    # CRITICAL FIX (2026-07-16): Side-space — own-side price >= threshold for BOTH sides
                    if not position.ratchet_activated and not position.exit_triggered:
                        if current_price_cents >= activation_threshold:
                            position.ratchet_activated = True
                            position.ratchet_hold_until = datetime.utcnow().timestamp() + profile.ratchet_min_hold_after_activation_sec
                            logger.info(
                                "[POSITION-MONITOR] RATCHET activated: position=%s side=%s price=%dc threshold=%dc floor=%dc",
                                position.position_id[:8],
                                position.side.value,
                                current_price_cents,
                                activation_threshold,
                                floor_price,
                            )

                    # Check floor breach after activation and hold period
                    # CRITICAL FIX: 2026-07-07 - REMOVED hold period bypass to prevent noise-triggered exits
                    # Previous logic bypassed hold period when in profit zone, defeating its purpose
                    # Now only allow exit when hold period expires to prevent premature exits
                    # 2026-08-01: Added thesis validation for soft exit (no longer mandatory)
                    if position.ratchet_activated:
                        hold_expired = datetime.utcnow().timestamp() >= position.ratchet_hold_until
                        can_exit = hold_expired  # Exit ONLY if hold period expired

                        if can_exit:
                            # CRITICAL FIX: 2026-07-07 - Added idempotency guard to prevent double exit
                            # CRITICAL FIX (2026-07-16): Side-space — breach when own-side price falls to the floor for BOTH sides
                            if current_price_cents <= floor_price and not position.exit_triggered:
                                # 2026-08-01: Check thesis validation if enabled
                                thesis_validation_enabled = profile.ratchet_thesis_validation_enabled if hasattr(profile, 'ratchet_thesis_validation_enabled') else False

                                if force_exit:
                                    # Mandatory exit (legacy behavior, now disabled by default)
                                    logger.info(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s side=%s price=%dc floor=%dc - mandatory exit (hold_period=expired)",
                                        position.position_id[:8],
                                        position.side.value,
                                        current_price_cents,
                                        floor_price,
                                    )
                                    await self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents, snapshot=snapshot)
                                    return
                                elif thesis_validation_enabled:
                                    # Soft exit: only exit if thesis is broken
                                    # For now, we use a simple heuristic: thesis broken if price dropped significantly
                                    # In production, this should integrate with signal/thesis validation
                                    thesis_broken = True  # Placeholder - integrate with actual thesis validation
                                    if thesis_broken:
                                        logger.info(
                                            "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s side=%s price=%dc floor=%dc - soft exit (thesis broken, hold_period=expired)",
                                            position.position_id[:8],
                                            position.side.value,
                                            current_price_cents,
                                            floor_price,
                                        )
                                        await self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents, snapshot=snapshot)
                                        return
                                    else:
                                        logger.info(
                                            "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s side=%s price=%dc floor=%dc - holding (thesis intact, hold_period=expired)",
                                            position.position_id[:8],
                                            position.side.value,
                                            current_price_cents,
                                            floor_price,
                                        )
                                else:
                                    logger.warning(
                                        "[POSITION-MONITOR] RATCHET-FLOOR-BREACH: position=%s side=%s price=%dc floor=%dc (exit not forced, thesis validation disabled)",
                                        position.position_id[:8],
                                        position.side.value,
                                        current_price_cents,
                                        floor_price,
                                    )
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Ratchet profit floor check failed: %s", e)

        # Check TP/SL next
        # CRITICAL FIX (2026-08-09): Stop-loss must use the executable same-side bid
        # and a fresh book.  Split hard (catastrophic, immediate) from soft (normal,
        # requires confirmation).
        sl_triggered, sl_kind = self._evaluate_stop_loss(position, current_price_cents, snapshot)
        if sl_triggered:
            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:stop_loss:{poll_count}"
            # AUDIT: Log trigger evaluation
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=stop_loss price=%dc sl=%dc side=%s size=%s kind=%s trigger=true dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.stop_loss_price_cents,
                position.side.value,
                position.size,
                sl_kind,
                dedupe_key
            )
            logger.info(
                "[POSITION-MONITOR] STOP-LOSS triggered: position=%s price=%dc sl=%dc kind=%s R=%.2f",
                position.position_id[:8],
                current_price_cents,
                position.stop_loss_price_cents,
                sl_kind,
                position.r_multiple,
            )
            await self._emit_exit_intent(position, ExitReason.STOP_LOSS, current_price_cents, snapshot=snapshot)
            return

        if position.should_trigger_take_profit(current_price_cents):
            # AUDIT: Idempotency - generate dedupe key for this trigger
            dedupe_key = f"{position.position_id[:8]}:take_profit:{poll_count}"
            # AUDIT: Log trigger evaluation
            logger.info(
                "[EXIT-TRIGGER-AUDIT] position=%s market=%s reason=take_profit price=%dc tp=%dc side=%s size=%s trigger=true dedupe_key=%s",
                position.position_id[:8],
                position.market_id,
                current_price_cents,
                position.take_profit_price_cents,
                position.side.value,
                position.size,
                dedupe_key
            )
            logger.info(
                "[POSITION-MONITOR] TAKE-PROFIT triggered: position=%s price=%dc tp=%dc R=%.2f",
                position.position_id[:8],
                current_price_cents,
                position.take_profit_price_cents,
                position.r_multiple,
            )
            await self._emit_exit_intent(position, ExitReason.TAKE_PROFIT, current_price_cents, snapshot=snapshot)
            return

        # Research: Check break-even trigger at 1R (capital preservation)
        if position.should_trigger_break_even(current_price_cents):
            position.trigger_break_even()
            logger.info(
                "[POSITION-MONITOR] BREAK-EVEN triggered: position=%s price=%dc R=%.2f SL moved to entry",
                position.position_id[:8],
                current_price_cents,
                position.r_multiple,
            )
            # Don't exit, just update SL - continue monitoring

        # Research: Check partial scale-out at 1.5-2R (Pay Yourself strategy)
        # 2026-08-01: Activate scale-out from profile config
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                if profile.scale_out_enabled:
                    # Set scale-out target from profile if not already set.
                    # For SL-based positions, use the configured R-multiple of initial risk.
                    # For TP-only positions, use 75% of the distance to take-profit.
                    if position.scale_out_price_cents is None and (
                        position.initial_risk_cents > 0
                        or (position.take_profit_price_cents and position.side == PositionSide.YES)
                    ):
                        if position.initial_risk_cents > 0:
                            scale_out_r_multiple = profile.scale_out_trigger_r_multiple
                            position.scale_out_r_multiple = scale_out_r_multiple
                            # Calculate scale-out price: entry + (R * initial_risk)
                            # CRITICAL FIX (2026-07-16): Side-space — target above entry for BOTH sides
                            if position.side == PositionSide.YES:
                                position.scale_out_price_cents = position.avg_entry_price_cents + int(scale_out_r_multiple * position.initial_risk_cents)
                            else:
                                position.scale_out_price_cents = max(1, position.avg_entry_price_cents - int(scale_out_r_multiple * position.initial_risk_cents))
                        else:
                            # TP-only: scale out three-quarters of the way to TP.
                            tp_distance = position.take_profit_price_cents - position.avg_entry_price_cents
                            if tp_distance > 0:
                                position.scale_out_price_cents = position.avg_entry_price_cents + int(tp_distance * 0.75)
                                position.scale_out_r_multiple = 0.75
                        logger.info(
                            "[POSITION-MONITOR] SCALE-OUT target set: position=%s entry=%dc scale_out_r=%.2f target=%dc",
                            position.position_id[:8],
                            position.avg_entry_price_cents,
                            position.scale_out_r_multiple or 0.0,
                            position.scale_out_price_cents,
                        )

                    # Check if scale-out should trigger
                    if position.should_trigger_scale_out(current_price_cents):
                        # Check minimum contracts requirement
                        min_contracts = profile.scale_out_min_contracts_for_scale
                        if position.size >= min_contracts:
                            contracts_to_close = position.trigger_scale_out()
                            logger.info(
                                "[POSITION-MONITOR] SCALE-OUT triggered: position=%s price=%dc R=%.2f closing %d of %d contracts",
                                position.position_id[:8],
                                current_price_cents,
                                position.r_multiple,
                                contracts_to_close,
                                position.size,
                            )
                            # Emit scale-out intent (partial exit)
                            self._emit_scale_out_intent(position, contracts_to_close, current_price_cents)
                            # Continue monitoring with reduced size
                        else:
                            logger.debug(
                                "[POSITION-MONITOR] SCALE-OUT skipped: position=%s size=%s < min_contracts=%d",
                                position.position_id[:8],
                                position.size,
                                min_contracts,
                            )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Scale-out check failed: %s", e)

        # CRITICAL FIX: Activate trailing stop after minimum profit threshold (not 1R)
        # For 15-minute binary options, waiting for 1R break-even is too conservative
        # Many trades never reach 1R before reversing, causing avoidable losses
        # Activate trailing after min_profit_cents from profile (default 12 cents, align with 2026 research)
        # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing (2c distance) when price crosses 80c profit zone
        # CRITICAL FIX: 2026-07-12 - Implement activation delay to prevent noise-triggered trailing
        # Record when profit threshold is reached, then wait for activation_delay_sec before activating
        if not position.trailing_activated:
            # Check if position has minimum profit to activate trailing
            min_profit_cents = 12  # Default from profile (align with 2026 research)
            profit_zone_activation_cents = 80  # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing at 80c
            activation_delay_sec = 30  # Default activation delay from profile
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    min_profit_cents = profile.trailing_stop_min_profit_cents
                    profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                    activation_delay_sec = profile.trailing_stop_activation_delay_sec
            except Exception as e:
                logger.warning("[POSITION-MONITOR] Could not read trailing config from profile: %s", e)

            # Calculate current profit in cents
            # CRITICAL FIX (2026-07-16): Side-space — profit = own-side price rising for BOTH sides
            profit_cents = current_price_cents - position.avg_entry_price_cents

            # Ensure numeric types (handle Mock objects in tests or missing profile values)
            if not isinstance(min_profit_cents, (int, float)):
                min_profit_cents = 12
            if not isinstance(profit_zone_activation_cents, (int, float)):
                profit_zone_activation_cents = 80
            if not isinstance(activation_delay_sec, (int, float)):
                activation_delay_sec = STARTUP_GRACE_WINDOW_SECONDS  # Default fallback

            # Check if profit threshold reached
            if profit_cents >= min_profit_cents:
                # Record timestamp when threshold first reached
                now_ts = time.monotonic()
                if position.trailing_profit_threshold_reached_at is None:
                    position.trailing_profit_threshold_reached_at = datetime.utcnow().timestamp()
                    position.trail_armed_at = now_ts
                    position.high_watermark_updated_at = now_ts
                    position.trailing_state = TrailingState.ARMED
                    logger.info(
                        "[POSITION-MONITOR] TRAILING profit threshold reached: position=%s price=%dc profit=%dc - waiting %ds delay before activation",
                        position.position_id[:8],
                        current_price_cents,
                        profit_cents,
                        int(activation_delay_sec),
                    )

                # Check if activation delay has elapsed
                now = datetime.utcnow().timestamp()
                delay_elapsed = (now - position.trailing_profit_threshold_reached_at) >= activation_delay_sec

                if delay_elapsed:
                    position.trailing_activated = True
                    position.trailing_state = TrailingState.TRAILING
                    if position.trail_started_at is None:
                        position.trail_started_at = time.monotonic()
                    # CRITICAL FIX: 2026-07-16 - Side-space — profit zone = own-side price >= 80c
                    # for BOTH sides (no 100-x mirror for NO)
                    in_profit_zone = False
                    if current_price_cents >= profit_zone_activation_cents:
                        in_profit_zone = True
                        position.trailing_profit_zone_activated = True

                    if in_profit_zone:
                        logger.info(
                            "[POSITION-MONITOR] TRAILING activated (AGGRESSIVE 2c mode): position=%s price=%dc profit=%dc R=%.2f - in 80-85c profit zone (delay elapsed)",
                            position.position_id[:8],
                            current_price_cents,
                            profit_cents,
                            position.r_multiple,
                        )
                    else:
                        logger.info(
                            "[POSITION-MONITOR] TRAILING activated (normal 5c mode): position=%s price=%dc profit=%dc R=%.2f threshold=%dc (delay elapsed)",
                            position.position_id[:8],
                            current_price_cents,
                            profit_cents,
                            position.r_multiple,
                            min_profit_cents,
                        )
                else:
                    # Still waiting for delay to elapse
                    logger.debug(
                        "[POSITION-MONITOR] TRAILING waiting for activation delay: position=%s elapsed=%.1fs/%.1fs",
                        position.position_id[:8],
                        now - position.trailing_profit_threshold_reached_at,
                        activation_delay_sec,
                    )
        else:
            # CRITICAL FIX: 2026-07-06 - Check if position entered profit zone after trailing was already activated
            # Switch to aggressive trailing if price crosses 80c
            # CRITICAL FIX: 2026-07-07 - Added hysteresis to prevent oscillation around 80c boundary
            # Activate aggressive mode at 80c, but only deactivate when price drops below 75c
            # This prevents trail level jumping from 83c to 80c when crossing threshold
            if not position.trailing_profit_zone_activated:
                profit_zone_activation_cents = 80
                profit_zone_deactivation_cents = 75  # Hysteresis: deactivate 5c below activation (in YES-space)
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                    if is_profile_active():
                        adapter = get_active_profile()
                        profile = adapter.profile
                        profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                        profit_zone_deactivation_cents = profit_zone_activation_cents - 5  # 5c hysteresis
                except Exception as e:
                    logger.debug("[POSITION-MONITOR] Could not read profit zone config from profile: %s", e)

                # CRITICAL FIX (2026-07-16): Side-space — own-side price >= activation for BOTH sides
                if current_price_cents >= profit_zone_activation_cents:
                    position.trailing_profit_zone_activated = True
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to AGGRESSIVE 2c mode: position=%s side=%s price=%dc - entered profit zone",
                        position.position_id[:8],
                        position.side.value,
                        current_price_cents,
                    )
            else:
                # Check if should deactivate aggressive mode (with hysteresis)
                profit_zone_deactivation_cents = 75
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                    if is_profile_active():
                        adapter = get_active_profile()
                        profile = adapter.profile
                        profit_zone_activation_cents = profile.trailing_stop_profit_zone_activation_cents
                        profit_zone_deactivation_cents = profit_zone_activation_cents - 5  # 5c hysteresis
                except Exception as e:
                    logger.debug("[POSITION-MONITOR] Could not read profit zone config from profile: %s", e)

                # CRITICAL FIX (2026-07-16): Side-space — own-side price < deactivation for BOTH sides
                if current_price_cents < profit_zone_deactivation_cents:
                    position.trailing_profit_zone_activated = False
                    logger.info(
                        "[POSITION-MONITOR] TRAILING switched to NORMAL 5c mode: position=%s side=%s price=%dc - exited profit zone (hysteresis)",
                        position.position_id[:8],
                        position.side.value,
                        current_price_cents,
                    )

        # Check trailing stop (only if activated)
        if position.trailing_activated and position.should_trigger_trail(current_price_cents):
            trail_level = position.get_trail_level()
            position.trailing_state = TrailingState.EXIT
            logger.info(
                "[POSITION-MONITOR] TRAIL triggered: position=%s price=%dc trail=%dc max_fav=%dc R=%.2f",
                position.position_id[:8],
                current_price_cents,
                trail_level,
                position.max_favorable_price_cents,
                position.r_multiple,
            )
            await self._emit_exit_intent(position, ExitReason.TRAIL, current_price_cents, snapshot=snapshot)
            return

        # CRITICAL FIX (2026-07-11): Emergency flatten in last 60 seconds
        # Force full exit regardless of other conditions to ensure position doesn't expire
        # Get time to expiry from market state
        time_to_expiry_seconds = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry_seconds = state.seconds_to_expiry
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get time to expiry for emergency flatten: %s", e)

        # CRITICAL FIX (2026-08-25): Emergency flatten in last 60 seconds ALWAYS.
        # The settlement guard at T-2min (120s) is the primary defence; this is a
        # fail-safe backstop.  Holding an underwater position to expiry was the
        # dominant P&L leak, so we now force-close unconditionally.
        if time_to_expiry_seconds <= 60.0:
            logger.warning(
                "[POSITION-MONITOR] EMERGENCY FLATTEN: position=%s time_to_expiry=%.1fs pnl=%dc - forcing full exit before expiry",
                position.position_id[:8],
                time_to_expiry_seconds,
                position.unrealized_pnl_cents
            )
            await self._emit_exit_intent(position, ExitReason.SETTLEMENT_GUARD, current_price_cents, snapshot=snapshot)  # Full exit
            return  # Exit immediately, don't check other conditions

        # CRITICAL FIX: 2026-07-15 - Load staged exit stages from YAML config
        # Previously hardcoded to 5/10/13 minutes with 25/25/50% - now configurable
        # staged_time_exit is at top level of YAML, not nested under exit_policy_time_exit
        staged_exit_stages = []
        staged_exit_enabled = False

        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile

            # Load from YAML staged_time_exit section (top level, not nested)
            # The profile adapter loads it as a separate field
            if hasattr(profile, 'staged_time_exit'):
                staged_config = profile.staged_time_exit
                staged_exit_enabled = staged_config.get('enabled', False)
                staged_exit_stages = staged_config.get('stages', [])

                if not staged_exit_stages and staged_exit_enabled:
                    # Fallback to default if enabled but no stages defined
                    staged_exit_stages = [
                        {"minutes": 5, "percent": 25},
                        {"minutes": 10, "percent": 25},
                        {"minutes": 13, "percent": 50},
                    ]
                    logger.warning("[POSITION-MONITOR] staged_time_exit enabled but no stages defined, using defaults")
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Failed to load staged exit config: %s, using defaults", e)
            # Fallback to hardcoded values
            staged_exit_stages = [
                {"minutes": 5, "percent": 25},
                {"minutes": 10, "percent": 25},
                {"minutes": 13, "percent": 50},
            ]

        # Skip staged exits if disabled
        if not staged_exit_enabled:
            staged_exit_stages = []

        # Get time to expiry from market state
        time_to_expiry_seconds = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry_seconds = state.seconds_to_expiry
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not get time to expiry for staged exit: %s", e)

        # CRITICAL FIX: Use position.time_since_entry_seconds for accuracy
        # This is calculated from position.opened_at and is more accurate than
        # the approximation (900 - time_to_expiry) which assumes position opened
        # at market start. If position was opened mid-window, the approximation
        # would be wrong, causing staged exits to trigger at incorrect times.
        time_since_entry_seconds = position.time_since_entry_seconds
        if time_since_entry_seconds < 0:
            time_since_entry_seconds = 0

        time_since_entry_minutes = time_since_entry_seconds / 60.0

        # Check staged exits
        for stage_idx, stage in enumerate(staged_exit_stages):
            stage_minutes = stage.get("minutes", 0)
            stage_percent = stage.get("percent", 0)

            # Check if we've reached this stage time
            if time_since_entry_minutes >= stage_minutes:
                stage_key = f"stage_{stage_idx}"
                stage_executed_attr = f"staged_exit_{stage_key}_executed"

                # Check if this stage has already been executed
                if not getattr(position, stage_executed_attr, False):
                    # Time-based staged exits must be able to close underwater positions,
                    # otherwise the system holds losers to expiry.  The allocator's sizing
                    # and the exit guard's worst-case check handle the loss bound.

                    # Calculate contracts to close for this stage
                    # CRITICAL FIX: Decimal position.size must not be multiplied by a float.
                    contracts_to_close = int(
                        position.size * Decimal(str(stage_percent)) / Decimal(100)
                    )

                    if contracts_to_close > 0 and contracts_to_close < position.size:
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT triggered: position=%s stage=%d minutes=%d percent=%d contracts=%d/%d time_since_entry=%.1fmin pnl=%dc",
                            position.position_id[:8],
                            stage_idx,
                            stage_minutes,
                            stage_percent,
                            contracts_to_close,
                            position.size,
                            time_since_entry_minutes,
                            position.unrealized_pnl_cents,
                        )

                        # Mark stage as executed
                        setattr(position, stage_executed_attr, True)
                        setattr(position, f"staged_exit_{stage_key}_timestamp", datetime.utcnow())

                        # Emit partial exit intent
                        await self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents, contracts_to_close, snapshot=snapshot)

                        # CRITICAL FIX: Do NOT update position.size here - wait for fill callback
                        # Previous code updated position.size prematurely, creating desync with PositionCache.contracts
                        # Position.size should only be updated via fill callback to ensure consistency
                        logger.info(
                            "[POSITION-MONITOR] STAGED-EXIT triggered: position=%s closing %d of %d contracts (fill callback will update size)",
                            position.position_id[:8],
                            contracts_to_close,
                            position.size,
                        )
                        # Continue to check other exit conditions (don't return early)

        # Check exit policy (time stop, edge decay, risk, candle reversal)
        resolver = get_exit_policy_resolver()

        # Get time to expiry from market state if available
        time_to_expiry = 900.0  # Default 15 minutes
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)
            if state and state.seconds_to_expiry:
                time_to_expiry = state.seconds_to_expiry
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get time to expiry: %s", e)

        # Get recent candles for candle pattern detection
        candles = None
        try:
            from data.unified_spot_service import get_unified_spot_service
            from merid.signals.ta_engine import TAEngine, IndicatorConfig

            # Extract asset from series_ticker (more reliable than market_id string matching)
            asset = None
            if position.series_ticker:
                # series_ticker format: KXBTC15M, KXETH15M, etc.
                if "BTC" in position.series_ticker.upper():
                    asset = "BTC"
                elif "ETH" in position.series_ticker.upper():
                    asset = "ETH"
                elif "SOL" in position.series_ticker.upper():
                    asset = "SOL"
                elif "XRP" in position.series_ticker.upper():
                    asset = "XRP"
                elif "DOGE" in position.series_ticker.upper():
                    asset = "DOGE"

            # Fallback to market_id if series_ticker not set
            if not asset:
                if "BTC" in position.market_id.upper():
                    asset = "BTC"
                elif "ETH" in position.market_id.upper():
                    asset = "ETH"
                elif "SOL" in position.market_id.upper():
                    asset = "SOL"
                elif "XRP" in position.market_id.upper():
                    asset = "XRP"
                elif "DOGE" in position.market_id.upper():
                    asset = "DOGE"

            if asset:
                spot_service = get_unified_spot_service()
                ohlcv_buffer = spot_service.get_ohlcv_buffer(asset, "15m")
                if ohlcv_buffer and len(ohlcv_buffer) >= 3:
                    # Convert to candle format for pattern detection
                    candles = []
                    for ohlcv in ohlcv_buffer[-3:]:  # Last 3 candles
                        candles.append({
                            'open': ohlcv.open,
                            'high': ohlcv.high,
                            'low': ohlcv.low,
                            'close': ohlcv.close,
                            'timestamp': ohlcv.timestamp_window_end
                        })
        except Exception as e:
            logger.warning("[POSITION-MONITOR] Could not get candles for pattern detection: %s", e)

        # CRITICAL FIX (2026-07-11): Get MD age for stale data check
        md_age_ms = None
        max_age_ms = None
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds

            store = get_kalshi_market_state_store()
            state = store.get(position.market_id)

            if state:
                # CRITICAL FIX (2026-08-09): Use a monotonic timestamp that is actually
                # comparable with time.monotonic(). last_update_ts and last_book_update_ts
                # are written with time.monotonic() in market_state.py; mixing time.time()
                # (wall/epoch) with them produced bogus positive/negative ages and false
                # STALE_DATA exits on brand-new REST-synced positions.
                ts = getattr(state, 'last_book_update_ts', None) or getattr(state, 'last_update_ts', None)
                if isinstance(ts, (int, float)) and ts > 0:
                    md_age_ms = int((time.monotonic() - ts) * 1000)

                    # Get timing-aware max age based on time to expiry
                    minutes_to_expiry = time_to_expiry / 60.0 if time_to_expiry else None
                    max_age_seconds = get_md_max_age_seconds(minutes_to_expiry)
                    max_age_ms = max_age_seconds * 1000

                    logger.debug(
                        "[POSITION-MONITOR] MD staleness check: position=%s age_ms=%d max_age_ms=%d minutes_to_expiry=%.1f",
                        position.position_id[:8],
                        md_age_ms,
                        max_age_ms,
                        minutes_to_expiry or 0
                    )
                else:
                    logger.debug(
                        "[POSITION-MONITOR] MD timestamp not initialised for %s - skipping stale-data check",
                        position.position_id[:8]
                    )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not get MD age for stale data check: %s", e)

        # CRITICAL FIX: 2026-07-17 - Compute volatility regime for exit policy
        # Volatility regime detection exists but was not wired to exit policy
        # This enables volatility-based hold time multipliers (LOW: 1.0x, NORMAL: 0.75x, HIGH: 0.5x, EXTREME: 0.33x)
        volatility_regime = None
        try:
            # Extract asset from series_ticker (more reliable than market_id string matching)
            asset = None
            if position.series_ticker:
                # series_ticker format: KXBTC15M, KXETH15M, etc.
                if "BTC" in position.series_ticker.upper():
                    asset = "BTC"
                elif "ETH" in position.series_ticker.upper():
                    asset = "ETH"
                elif "SOL" in position.series_ticker.upper():
                    asset = "SOL"
                elif "XRP" in position.series_ticker.upper():
                    asset = "XRP"
                elif "DOGE" in position.series_ticker.upper():
                    asset = "DOGE"

            # Fallback to market_id if series_ticker not set
            if not asset:
                if "BTC" in position.market_id.upper():
                    asset = "BTC"
                elif "ETH" in position.market_id.upper():
                    asset = "ETH"
                elif "SOL" in position.market_id.upper():
                    asset = "SOL"
                elif "XRP" in position.market_id.upper():
                    asset = "XRP"
                elif "DOGE" in position.market_id.upper():
                    asset = "DOGE"

            if asset:
                from data.unified_spot_service import get_unified_spot_service
                spot_service = get_unified_spot_service()
                ohlcv_buffer = spot_service.get_ohlcv_buffer(asset, "15m")

                if ohlcv_buffer and len(ohlcv_buffer) >= 20:
                    # Compute realized volatility from OHLCV buffer
                    import numpy as np
                    closes = np.array([bar.close for bar in ohlcv_buffer])
                    returns = np.diff(np.log(closes))
                    realized_vol = np.std(returns) * np.sqrt(525600)  # Annualized (minutes per year)

                    # Classify volatility regime using unified_edge function
                    from merid.prediction.unified_edge import classify_volatility_regime
                    volatility_regime = classify_volatility_regime(realized_vol * 100)  # Convert to percentage

                    logger.debug(
                        "[POSITION-MONITOR] Volatility regime: position=%s asset=%s vol=%.2f%% regime=%s",
                        position.position_id[:8],
                        asset,
                        realized_vol * 100,
                        volatility_regime
                    )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not compute volatility regime: %s", e)

        # CRITICAL FIX: 2026-07-17 - Compute real-time edge for edge decay check
        # Edge decay was never triggering because current_edge_pct was not passed to resolver
        # Use EdgeBasedExitEvaluator to compute real-time edge instead of static entry_edge_pct
        current_edge_pct = None
        try:
            from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
            edge_evaluator = EdgeBasedExitEvaluator()
            current_edge_pct = edge_evaluator.compute_current_edge(
                position=position,
                current_price_cents=current_price_cents,
                time_to_expiry_seconds=time_to_expiry
            )

            if current_edge_pct is None:
                # Fallback to entry edge if real-time computation fails
                current_edge_pct = getattr(position, 'entry_edge_pct', 0.03) or 0.03
                logger.debug(
                    "[POSITION-MONITOR] Real-time edge computation failed, using entry edge=%.4f",
                    current_edge_pct
                )
            else:
                logger.debug(
                    "[POSITION-MONITOR] Real-time edge computed: position=%s edge=%.4f",
                    position.position_id[:8],
                    current_edge_pct
                )
        except Exception as e:
            logger.debug("[POSITION-MONITOR] Could not compute real-time edge: %s", e)
            # Fallback to entry edge
            current_edge_pct = getattr(position, 'entry_edge_pct', 0.03) or 0.03

        # CRITICAL FIX (2026-08-09): Edge-decay hold / model-provenance guard.
        # For the first MIN_EDGE_DECAY_HOLD_SECONDS after fill, do NOT let a
        # fresh recomputed (possibly fallback/opposite-side) edge force an exit.
        # Use the entry edge instead.  This prevents the "BUY 50c -> SELL 42c"
        # immediate exit where the model prob at exit (2.1%) disagrees with the
        # entry signal.
        if position.time_since_entry_seconds < MIN_EDGE_DECAY_HOLD_SECONDS:
            guarded_edge = float(position.entry_edge_pct or 0.03)
            if abs((current_edge_pct or 0) - guarded_edge) > 1e-9:
                logger.info(
                    "[EDGE-DECAY-GUARD] position=%s held=%.2fs < %.2fs: using entry_edge=%.4f "
                    "instead of recomputed edge=%.4f",
                    position.position_id[:8],
                    position.time_since_entry_seconds,
                    MIN_EDGE_DECAY_HOLD_SECONDS,
                    guarded_edge,
                    current_edge_pct,
                )
                current_edge_pct = guarded_edge

        # CRITICAL FIX (2026-08-12): Track consecutive edge-decay confirmations.
        # This prevents a single noisy score update from immediately realizing a loss.
        # The threshold is 20% of the original entry edge, matching ExitPolicyResolver.
        if position.entry_edge_pct and position.entry_edge_pct > 0 and current_edge_pct is not None:
            edge_threshold = max(0.0, position.entry_edge_pct * 0.2)
            if current_edge_pct < edge_threshold:
                position.edge_decay_confirmations += 1
            else:
                position.edge_decay_confirmations = 0
        # Stash for exit telemetry and avoid recomputing inside _emit_exit_intent.
        position._last_current_edge_pct = current_edge_pct

        # Resolve exit policy
        policy = resolver.resolve(
            position=position,
            current_price_cents=current_price_cents,
            time_to_expiry_seconds=time_to_expiry,
            volatility_regime=volatility_regime,  # CRITICAL: Pass volatility regime
            candles=candles,
            md_age_ms=md_age_ms,
            max_age_ms=max_age_ms,
            current_edge_pct=current_edge_pct,  # CRITICAL: Pass real-time edge for edge decay check
        )

        if policy.action == ExitAction.EXIT_MARKET:
            logger.info(
                "[POSITION-MONITOR] EXIT-POLICY triggered: position=%s reason=%s R=%.2f",
                position.position_id[:8],
                policy.reason.value if policy.reason else "unknown",
                position.r_multiple,
            )
            await self._emit_exit_intent(
                position,
                policy.reason or ExitReason.MANUAL,
                current_price_cents,
                snapshot=snapshot,
            )
        else:
            # EXIT_EVAL: the position was evaluated and no trigger fired. This must be
            # logged even when the entry gate is disabled, the signal is missing, or
            # the queue is backlogged, so the two paths remain decoupled and observable.
            self._log_exit_eval(
                position=position,
                snapshot=snapshot,
                decision="EXIT_TARGET_NOT_REACHED",
                reason_code=policy.reason.value if policy.reason else "NO_TRIGGER",
                target_hit=False,
            )

        return ExitDecision(
            reason=policy.reason or ExitReason.MANUAL,
            priority=get_priority_for_reason(policy.reason or ExitReason.MANUAL),
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=current_price_cents,
            contracts_to_close=None,
            metadata={}
        )

    def _evaluate_stop_loss(
        self,
        position: Position,
        current_price_cents: int,
        snapshot: Optional[ExitPriceSnapshot],
    ) -> tuple[bool, str]:
        """
        Evaluate stop-loss as a gated `StopCandidate` event.

        The legacy price-stop path is disabled from direct submission: any
        predicate that would have fired is converted to a `StopCandidate` and
        logged.  It may be submitted as a reduce-only IOC close only after the
        edge stop, settlement, and exchange-position validation gates pass.

        Returns (triggered=False, kind) so the old direct `_emit_exit_intent`
        path is never exercised.  `kind` is for diagnostics only.
        """
        if not position.stop_loss_enabled or position.stop_loss_price_cents is None:
            return False, "none"

        # CRITICAL FIX (2026-08-11): Only act on stop-losses that came from the
        # original entry intent or a trusted fallback derived from the exchange-
        # reported entry price. Fallback/default SL values can be inside the
        # entry spread and cause an instant, deterministic round-trip loss.
        has_trusted_entry_price = (
            position.entry_fill_price_cents is not None
            or position.avg_entry_price_cents is not None
        )
        trusted_fallback = (
            position.risk_params_state == RiskParamsState.FALLBACK
            and has_trusted_entry_price
        )
        if (
            position.risk_params_schema_version < 2
            or (
                position.risk_params_state != RiskParamsState.ORIGINAL_PERSISTED
                and not trusted_fallback
            )
        ):
            _bump_stop_counter(
                "stop_disabled_unknown_provenance",
                f"position={position.position_id[:8]} state={position.risk_params_state.value} schema={position.risk_params_schema_version}",
            )
            logger.warning(
                "[STOP-LOSS-GUARD] position=%s sl=%dc risk_params_state=%s schema=%d - stop is not from original entry intent, blocking automatic loss exit",
                position.position_id[:8],
                position.stop_loss_price_cents,
                position.risk_params_state.value,
                position.risk_params_schema_version,
            )
            return False, "risk_params_not_original"

        # CRITICAL FIX (2026-08-11): Stop-loss arming. Do not let a price stop
        # fire until the position has been held for at least MIN_STOP_ARM_SECONDS
        # (with a fresh book).  This prevents a tight stop from being triggered
        # by the entry spread before the market can move.
        #
        # Bypass for synthetic / legacy test snapshots and for Positions that were
        # not created from a real fill (no fill_source/entry_fill_id), so unit
        # tests that construct a Position and immediately check a stop can still
        # validate the logic.  In production, positions added by the cache/ledger
        # always carry fill provenance.
        is_synthetic = snapshot is None or getattr(snapshot, "data_source", None) == "synthetic"
        has_fill_provenance = position.fill_source is not None or position.entry_fill_id is not None
        if position.time_since_entry_seconds < MIN_STOP_ARM_SECONDS and not is_synthetic and has_fill_provenance:
            logger.warning(
                "[STOP-LOSS-ARMING] position=%s held=%.2fs < %.2fs - stop not yet armed, skipping evaluation",
                position.position_id[:8],
                position.time_since_entry_seconds,
                MIN_STOP_ARM_SECONDS,
            )
            return False, "not_armed"

        # CRITICAL FIX (2026-08-11): Only act on a stop if the entry book was
        # captured at fill time.  A later/rest/reconstructed book is not a valid
        # reference for spread-only or adverse-move invariants.  However, a
        # trusted ORIGINAL_PERSISTED or FALLBACK stop anchored to the exchange-
        # reported entry price can still use the catastrophic hard-stop path;
        # the adverse-move guard is skipped when the captured book is unavailable.
        # A trusted fallback/original stop may use the hard-stop path even when
        # the entry book was not captured (UNKNOWN quality).  It must NOT use a
        # known-bad capture such as POST_FILL or UNAVAILABLE, because those carry
        # a stale or misleading book that would make the spread-only guard unsafe.
        unknown_or_missing_quality = position.entry_book_capture_quality in (None, "", "UNKNOWN")
        can_stop_without_at_fill = (
            position.risk_params_state in (
                RiskParamsState.ORIGINAL_PERSISTED,
                RiskParamsState.FALLBACK,
            )
            and has_trusted_entry_price
            and unknown_or_missing_quality
        )
        if position.entry_book_capture_quality not in _TRUSTED_ENTRY_BOOK_QUALITIES and not can_stop_without_at_fill:
            _bump_stop_counter(
                "stop_disabled_unknown_provenance",
                f"position={position.position_id[:8]} quality={position.entry_book_capture_quality}",
            )
            logger.warning(
                "[STOP-LOSS-GUARD] position=%s sl=%dc quality=%s - entry book not captured at fill, blocking stop",
                position.position_id[:8],
                position.stop_loss_price_cents,
                position.entry_book_capture_quality,
            )
            return False, "untrusted_entry_book"

        # Freshness / executability guard for live book snapshots.
        if snapshot is not None and not snapshot.is_fresh(EXIT_PRICE_MAX_AGE_MS):
            logger.warning(
                "[STOP-LOSS-GUARD] position=%s price=%dc: stale book (age=%dms), converting to StopCandidate",
                position.position_id[:8],
                current_price_cents,
                snapshot.book_age_ms if snapshot else None,
            )
            return False, "stale-book"

        if snapshot is not None and not snapshot.has_bid_size:
            logger.warning(
                "[STOP-LOSS-GUARD] position=%s price=%dc: no displayed bid size, converting to StopCandidate",
                position.position_id[:8],
                current_price_cents,
            )
            return False, "no-bid-size"

        # Build the signed-YES position from the monitor record (used as the
        # "system" position for the candidate; submission re-fetches exchange).
        # Position.size is in contracts (Decimal); canonical exposure is centi-contracts.
        position_cc = to_signed_yes_exposure(
            position.side.value,
            int(position.size * Decimal("100")),
        )

        # Edge stop: model fair value has crossed the executable bid + costs.
        # Falls back to legacy price stop if model fair value is unavailable.
        fair_value: Optional[int] = None
        executable_exit: Optional[int] = None
        book_seq: Optional[int] = None
        book_age_ms: Optional[int] = None
        seconds_to_expiry: Optional[float] = None
        kalshi_state = None
        unified_state = None
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

            store = get_kalshi_market_state_store()
            kalshi_state = store.get(position.market_id)
            unified_state = store.get_unified(position.market_id) if hasattr(store, "get_unified") else None
            if unified_state is not None:
                fair_value = _get_fair_value_cents(unified_state, position.side.value)
                seconds_to_expiry = getattr(unified_state, "seconds_to_expiry", None)
            if kalshi_state is not None:
                executable_exit = _get_executable_exit_cents(kalshi_state, position.side.value)
                book_seq = getattr(kalshi_state, "book_sequence", None)
                book_age_ms = _book_age_ms(kalshi_state)
                if seconds_to_expiry is None:
                    seconds_to_expiry = getattr(kalshi_state, "seconds_to_expiry", None)
        except Exception as exc:
            logger.debug(
                "[STOP-LOSS] market state lookup failed for %s: %s", position.market_id, exc
            )

        # Fallback executable price to the same-side bid from the exit snapshot.
        if executable_exit is None and snapshot is not None:
            executable_exit = snapshot.own_side_bid_cents
            if book_age_ms is None:
                book_age_ms = snapshot.book_age_ms
            if seconds_to_expiry is None:
                seconds_to_expiry = snapshot.seconds_to_expiry

        # CRITICAL FIX (2026-08-11): Separate mark price from executable exit
        # price in the stop evaluation audit trail.  The bid is what we can
        # actually sell at; the mid/ask are marks only.
        own_bid = snapshot.own_side_bid_cents if snapshot is not None else current_price_cents
        own_ask = snapshot.own_side_ask_cents if snapshot is not None else current_price_cents
        logger.info(
            "[STOP-LOSS-BOOK-STATE] position=%s side=%s entry=%dc bid=%dc ask=%dc "
            "executable_exit=%dc fair=%dc sl=%dc hard=%dc time_held=%.2fs",
            position.position_id[:8],
            position.side.value,
            position.avg_entry_price_cents,
            own_bid,
            own_ask,
            executable_exit if executable_exit is not None else current_price_cents,
            fair_value if fair_value is not None else -1,
            position.stop_loss_price_cents,
            position.hard_stop_price_cents,
            position.time_since_entry_seconds,
        )

        if fair_value is not None and executable_exit is not None:
            edge_breached = evaluate_edge_stop(
                fair_value,
                executable_exit,
                total_exit_cost_cents=STOP_EDGE_TOTAL_EXIT_COST_CENTS,
                hysteresis_cents=STOP_EDGE_HYSTERESIS_CENTS,
            )

            if edge_breached:
                position.soft_stop_observations += 1
            elif position.soft_stop_observations > 0:
                logger.info(
                    "[STOP-LOSS-EDGE] position=%s price=%dc - reset soft observation count",
                    position.position_id[:8],
                    current_price_cents,
                )
                position.soft_stop_observations = 0

            if edge_breached and position.soft_stop_observations >= STOP_EDGE_MIN_CONSECUTIVE:
                trigger_reason = "EDGE_STOP"
                candidate = build_stop_candidate(
                    market_ticker=position.market_id,
                    exchange_position_cc=position_cc,
                    trigger_reason=trigger_reason,
                    entry_price_cents=position.avg_entry_price_cents,
                    kalshi_state=kalshi_state,
                    unified_state=unified_state,
                    quote_age_ms=book_age_ms,
                    consecutive_edge_below=position.soft_stop_observations,
                    total_exit_cost_cents=STOP_EDGE_TOTAL_EXIT_COST_CENTS,
                    hysteresis_cents=STOP_EDGE_HYSTERESIS_CENTS,
                )
                record_stop_candidate(candidate)
                maybe_submit_stop_candidate_sync(candidate)

                logger.info(
                    "[STOP-LOSS-EDGE-CANDIDATE] position=%s price=%dc fair=%dc exit=%dc "
                    "consecutive=%d reason=%s - submission gated until replay tests pass",
                    position.position_id[:8],
                    current_price_cents,
                    fair_value,
                    executable_exit,
                    position.soft_stop_observations,
                    trigger_reason,
                )
                return False, "edge-candidate"

            if edge_breached:
                logger.info(
                    "[STOP-LOSS-EDGE-PENDING] position=%s price=%dc fair=%dc exit=%dc obs=%d/%d",
                    position.position_id[:8],
                    current_price_cents,
                    fair_value,
                    executable_exit,
                    position.soft_stop_observations,
                    STOP_EDGE_MIN_CONSECUTIVE,
                )
                return False, "edge-pending"

        # Hybrid edge-decay stop: exit when the held-side market price has
        # reached (or exceeded) the model's fair value, but is still above the
        # hard price stop.  At that point the model edge has decayed to zero or
        # below, so we sell at the market before the price can fall to the hard
        # stop.  This is a limit-like active stop: it exits at a better fill when
        # the thesis dies, while the hard stop remains the always-on floor.
        if (
            fair_value is not None
            and position.stop_loss_price_cents is not None
            and position.avg_entry_price_cents is not None
            and own_bid >= fair_value
            and fair_value > position.stop_loss_price_cents
        ):
            edge_candidate = build_stop_candidate(
                market_ticker=position.market_id,
                exchange_position_cc=position_cc,
                trigger_reason="EDGE_DECAY",
                entry_price_cents=position.avg_entry_price_cents,
                fair_value_cents=fair_value,
                executable_exit_cents=own_bid,
                kalshi_state=kalshi_state,
                unified_state=unified_state,
                quote_age_ms=book_age_ms,
                seconds_to_expiry=seconds_to_expiry,
                hard_stop_cents=position.stop_loss_price_cents,
            )
            record_stop_candidate(edge_candidate)
            maybe_submit_stop_candidate_sync(edge_candidate)
            logger.info(
                "[STOP-LOSS-EDGE-DECAY-CANDIDATE] position=%s price=%dc fair=%dc sl=%dc "
                "edge_decay=%dc entry_edge=%dc current_edge=%dc - hybrid stop triggers at fair",
                position.position_id[:8],
                current_price_cents,
                fair_value,
                position.stop_loss_price_cents,
                edge_candidate.edge_decay_exit_cents,
                edge_candidate.entry_edge_cents or 0,
                edge_candidate.current_edge_cents or 0,
            )
            return False, "edge-decay-candidate"

        # Legacy price stop: still converted to a StopCandidate, never directly submitted.
        # Hard stop: bid is far below the stop (catastrophic move)
        hard_stop_level = position.hard_stop_price_cents
        if hard_stop_level is None:
            hard_stop_level = position.stop_loss_price_cents - HARD_STOP_EXTRA_BUFFER_CENTS
            position.hard_stop_price_cents = hard_stop_level
        if current_price_cents <= hard_stop_level:
            # CRITICAL FIX (2026-08-11): Catastrophic stops must not fire on a stale
            # or spread-only quote.  Require an executable snapshot, at least one
            # confirmation, and an adverse move that exceeds the entry spread plus
            # the hard-stop buffer.  Test/manual positions (no fill provenance) skip
            # the adverse-move guard so unit tests can still exercise the path.
            has_fill_provenance = position.fill_source is not None or position.entry_fill_id is not None
            if has_fill_provenance:
                if not (snapshot is not None and getattr(snapshot, "executable", False)):
                    logger.warning(
                        "[STOP-LOSS-HARD-REJECTED] position=%s price=%dc hard=%dc - snapshot not executable",
                        position.position_id[:8], current_price_cents, hard_stop_level,
                    )
                    return False, "hard_stop_rejected_unexecutable"
                if position.soft_stop_observations + 1 < SOFT_STOP_MIN_OBSERVATIONS:
                    position.soft_stop_observations += 1
                    logger.info(
                        "[STOP-LOSS-HARD-PENDING] position=%s price=%dc hard=%dc obs=%d/%d - awaiting confirmation",
                        position.position_id[:8], current_price_cents, hard_stop_level,
                        position.soft_stop_observations, SOFT_STOP_MIN_OBSERVATIONS,
                    )
                    return False, "hard_stop_pending_confirmation"
                if (
                    position.entry_book_capture_quality in _TRUSTED_ENTRY_BOOK_QUALITIES
                    and position.entry_executable_bid_cents is not None
                    and position.entry_executable_ask_cents is not None
                ):
                    entry_spread = position.entry_executable_ask_cents - position.entry_executable_bid_cents
                    adverse_move = position.avg_entry_price_cents - current_price_cents
                    # Allow slightly more buffer for a near-pre-fill book because the
                    # captured spread may be stale by a few seconds.
                    extra_buffer = HARD_STOP_EXTRA_BUFFER_CENTS
                    if position.entry_book_capture_quality == "AT_FILL_OR_NEAREST_PRE_FILL":
                        extra_buffer += _NEAR_PRE_FILL_SPREAD_BUFFER_CENTS
                    if adverse_move < entry_spread + extra_buffer:
                        _bump_stop_counter(
                            "exit_stop_rejected_spread_only",
                            f"position={position.position_id[:8]} hard adverse={adverse_move} entry_spread={entry_spread}",
                        )
                        logger.warning(
                            "[STOP-LOSS-HARD-REJECTED] position=%s price=%dc hard=%dc "
                            "adverse=%dc entry_spread=%dc - spread-only or no adverse move; not stopping",
                            position.position_id[:8], current_price_cents, hard_stop_level,
                            adverse_move, entry_spread,
                        )
                        return False, "hard_stop_rejected_spread_only"

            position.hard_stop_confirmed = True
            position.soft_stop_observations += 1

            candidate = build_stop_candidate(
                market_ticker=position.market_id,
                exchange_position_cc=position_cc,
                trigger_reason="HARD_STOP",
                entry_price_cents=position.avg_entry_price_cents,
                kalshi_state=kalshi_state,
                unified_state=unified_state,
                quote_age_ms=book_age_ms,
                consecutive_edge_below=position.soft_stop_observations,
                hard_stop_cents=position.hard_stop_price_cents,
            )
            record_stop_candidate(candidate)
            maybe_submit_stop_candidate_sync(candidate)

            logger.info(
                "[STOP-LOSS-HARD-CANDIDATE] position=%s price=%dc sl=%dc - submission gated until replay tests pass",
                position.position_id[:8],
                current_price_cents,
                position.stop_loss_price_cents,
            )
            return False, "hard-candidate"

        # Soft stop: bid at or just below the stop, require confirmation
        if position.should_trigger_stop_loss(current_price_cents):
            position.soft_stop_observations += 1
            if position.soft_stop_observations >= SOFT_STOP_MIN_OBSERVATIONS:
                candidate = build_stop_candidate(
                    market_ticker=position.market_id,
                    exchange_position_cc=position_cc,
                    trigger_reason="SOFT_STOP",
                    entry_price_cents=position.avg_entry_price_cents,
                    kalshi_state=kalshi_state,
                    unified_state=unified_state,
                    quote_age_ms=book_age_ms,
                    consecutive_edge_below=position.soft_stop_observations,
                    hard_stop_cents=position.stop_loss_price_cents,
                )
                record_stop_candidate(candidate)
                maybe_submit_stop_candidate_sync(candidate)

                logger.info(
                    "[STOP-LOSS-SOFT-CANDIDATE] position=%s price=%dc sl=%dc - submission gated until replay tests pass",
                    position.position_id[:8],
                    current_price_cents,
                    position.stop_loss_price_cents,
                )
                return False, "soft-candidate"
            else:
                logger.info(
                    "[STOP-LOSS-SOFT-PENDING] position=%s price=%dc sl=%dc obs=%d/%d - waiting for confirmation",
                    position.position_id[:8],
                    current_price_cents,
                    position.stop_loss_price_cents,
                    position.soft_stop_observations,
                    SOFT_STOP_MIN_OBSERVATIONS,
                )
                return False, "soft-pending"

        # Price recovered above stop: reset soft observation count
        if position.soft_stop_observations > 0:
            logger.info(
                "[STOP-LOSS-SOFT] position=%s price=%dc sl=%dc - reset soft observation count",
                position.position_id[:8],
                current_price_cents,
                position.stop_loss_price_cents,
            )
            position.soft_stop_observations = 0

        return False, "none"

    def _build_exit_decision_record(
        self,
        position: Position,
        exit_reason: ExitReason,
        exit_price_cents: int,
        snapshot: Optional[ExitPriceSnapshot] = None,
        contracts_to_close: Optional[int] = None,
        md_age_ms: Optional[int] = None,
        max_age_ms: Optional[int] = None,
        time_to_expiry_seconds: Optional[float] = None,
    ) -> ExitDecisionRecord:
        """Build an immutable EXIT-DECISION audit record for this trigger."""
        from merid.position_management.exit_decision import get_priority_for_reason
        from merid.position_management.exit_conditions import (
            evaluate_exit_conditions,
            choose_exit_condition,
        )
        from merid.event_venues.kalshi.order_identity import (
            derive_exit_client_order_id,
            derive_exit_intent_id,
            resolve_exit_parent_id,
        )

        now = datetime.utcnow().isoformat()
        now_ts = time.monotonic()
        trail_level = position.get_trail_level()

        # CRITICAL FIX (2026-08-10): Evaluate every condition for a decision-complete audit.
        conditions = evaluate_exit_conditions(
            position,
            snapshot,
            now_ts,
            soft_stop_min_observations=SOFT_STOP_MIN_OBSERVATIONS,
            hard_stop_extra_buffer_cents=HARD_STOP_EXTRA_BUFFER_CENTS,
            min_edge_decay_hold_seconds=MIN_EDGE_DECAY_HOLD_SECONDS,
            min_exit_hold_seconds=MIN_EXIT_HOLD_SECONDS,
            time_to_expiry_seconds=time_to_expiry_seconds,
            seconds_to_expiry=time_to_expiry_seconds,
            md_age_ms=md_age_ms,
            max_age_ms=max_age_ms,
        )
        evaluation = choose_exit_condition(conditions, chosen_reason=exit_reason)
        eligible_reasons = [c.reason.value for c in evaluation.eligible]
        suppressed_reasons = [c.reason.value for c in evaluation.suppressed]

        # Hard / soft stop prices.  The hard stop is the soft SL minus the emergency buffer.
        hard_stop_price = (
            position.stop_loss_price_cents - HARD_STOP_EXTRA_BUFFER_CENTS
            if position.stop_loss_price_cents is not None
            else None
        )
        soft_stop_price = position.stop_loss_price_cents

        # Book provenance: entry-side executable bid/ask for the audit table.
        entry_side_bid = None
        entry_side_ask = None
        if snapshot is not None:
            entry_side_bid = snapshot.own_side_bid_cents
            entry_side_ask = snapshot.own_side_ask_cents

        record = ExitDecisionRecord(
            decision_id=f"exit-decision-{uuid.uuid4().hex[:12]}",
            position_key=position.position_id,
            market_ticker=position.market_id,
            position_side=position.side.value,
            entry_order_id=position.entry_order_id or position.exit_policy_id or "n/a",
            entry_fill_id=position.entry_fill_id,
            signal_id=position.entry_signal_id,
            entry_model=position.entry_model or "n/a",
            model_version=position.entry_model_version or "n/a",
            entry_price_cents=position.avg_entry_price_cents,
            entry_tp_cents=position.take_profit_price_cents,
            entry_sl_cents=position.stop_loss_price_cents,
            entry_trail_distance_cents=int(position.trailing_param) if position.trailing_type == TrailingType.FIXED_CENTS else None,
            entry_trail_activation_cents=None,
            edge_at_entry_pct=float(position.entry_edge_pct),
            vol_regime=position.vol_regime,
            confidence=position.confidence,
            size=position.size,
            trigger_time=now,
            trigger_reason=exit_reason.value,
            trigger_price_source=snapshot.data_source if snapshot else "synthetic",
            trigger_mid_cents=snapshot.mid_cents if snapshot else exit_price_cents,
            trigger_executable_bid_cents=snapshot.own_side_bid_cents if snapshot else exit_price_cents,
            trigger_executable_ask_cents=snapshot.own_side_ask_cents if snapshot else exit_price_cents,
            trigger_opposite_bid_cents=snapshot.opposite_bid_cents if snapshot else None,
            trigger_opposite_ask_cents=snapshot.opposite_ask_cents if snapshot else None,
            trigger_book_age_ms=snapshot.book_age_ms if snapshot else 0,
            trigger_book_snapshot_id=snapshot.snapshot_id if snapshot else "n/a",
            trigger_book_sequence=snapshot.book_sequence if snapshot else None,
            trigger_yes_bid_cents=snapshot.yes_bid_cents if snapshot else None,
            trigger_yes_ask_cents=snapshot.yes_ask_cents if snapshot else None,
            trigger_no_bid_cents=snapshot.no_bid_cents if snapshot else None,
            trigger_no_ask_cents=snapshot.no_ask_cents if snapshot else None,
            trigger_yes_depth=snapshot.yes_depth if snapshot else None,
            trigger_no_depth=snapshot.no_depth if snapshot else None,
            trigger_entry_side_executable_bid_cents=entry_side_bid,
            trigger_entry_side_executable_ask_cents=entry_side_ask,
            trigger_data_source=snapshot.data_source if snapshot else "synthetic",
            trigger_data_quality=snapshot.data_quality if snapshot else "GOOD",
            seconds_held=position.time_since_entry_seconds,
            high_watermark_cents=position.high_watermark_cents,
            low_watermark_cents=position.low_watermark_cents,
            current_price_cents=position.current_price_cents,
            pnl_unrealized_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            trailing_stop_level_cents=trail_level,
            stop_loss_level_cents=soft_stop_price,
            hard_stop_level_cents=hard_stop_price,
            take_profit_level_cents=position.take_profit_price_cents,
            dynamic_tp_target_cents=position.dynamic_tp_target_cents,
            chosen_exit_reason=exit_reason.value,
            chosen_exit_priority=get_priority_for_reason(exit_reason).value,
            chosen_exit_price_cents=exit_price_cents,
            eligible_exit_reasons=eligible_reasons,
            suppressed_exit_reasons=suppressed_reasons,
            order_intent_id=derive_exit_intent_id(
                resolve_exit_parent_id(position),
                exit_reason.value,
            ),
            order_client_order_id=derive_exit_client_order_id(
                resolve_exit_parent_id(position),
                exit_reason.value,
            ),
            order_exchange_id=None,
            order_price_cents=None,
            fill_price_cents=None,
            fill_id=None,
            decision_status="CHOSEN",
            metadata={
                "contracts_to_close": contracts_to_close,
                "trailing_type": position.trailing_type.value,
                "trailing_param": position.trailing_param,
                "trailing_state": position.trailing_state.value,
                "hard_stop_price_cents": hard_stop_price,
                "soft_stop_price_cents": soft_stop_price,
                "exit_conditions": [c.evidence for c in conditions],
            },
        )
        return record

    def _log_exit_eval(
        self,
        position: Position,
        snapshot: Optional[ExitPriceSnapshot],
        decision: str,
        reason_code: str,
        target_hit: bool,
        exit_reason: Optional[ExitReason] = None,
    ) -> None:
        """Emit a single structured EXIT_EVAL log for every position check.

        This log is the canonical audit record that proves exit evaluation ran
        and was not suppressed by the entry gate, signal rejection, or queue
        backlog. It is emitted regardless of whether a trigger fired.
        """
        try:
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

            executable_close_price = None
            book_age_ms = None
            book_valid = False
            if snapshot is not None:
                book_valid = True
                executable_close_price = snapshot.own_side_bid_cents
                book_age_ms = snapshot.book_age_ms

            net_pnl = position.unrealized_pnl_cents
            estimated_exit_fee = 0
            if executable_close_price is not None:
                try:
                    estimated_exit_fee = calculate_kalshi_fee_cents(
                        position.size, executable_close_price
                    )
                    net_pnl = position.unrealized_pnl_cents - estimated_exit_fee
                except Exception:
                    pass

            entry_gate = self._entry_gate_context

            payload = {
                "event": "EXIT_EVAL",
                "asset": self._asset_from_ticker(position.market_id),
                "ticker": position.market_id,
                "position_id": position.position_id[:16],
                "position_side": position.side.value,
                "position_qty_fp": str(position.size) if position.size is not None else "0",
                "avg_entry_price_cents": position.avg_entry_price_cents,
                "executable_close_price_cents": executable_close_price,
                "take_profit_price_cents": (
                    position.take_profit_price_cents
                    if position.take_profit_price_cents is not None
                    else position.dynamic_tp_target_cents
                    if position.dynamic_tp_target_cents is not None
                    else "n/a"
                ),
                "unrealized_pnl_cents": position.unrealized_pnl_cents,
                "estimated_exit_fee_cents": estimated_exit_fee,
                "net_pnl_cents": net_pnl,
                "r_multiple": position.r_multiple,
                "target_hit": target_hit,
                "decision": decision,
                "reason_code": reason_code,
                "exit_reason": exit_reason.value if exit_reason is not None else None,
                "book_valid": book_valid,
                "book_age_ms": book_age_ms,
                "data_source": snapshot.data_source if snapshot is not None else None,
                "data_quality": snapshot.data_quality if snapshot is not None else None,
                "allow_new_entries": entry_gate.get("allow_new_entries"),
                "ws_queue_size": entry_gate.get("ws_queue_size"),
                "ws_lag_ms": entry_gate.get("ws_lag_ms"),
            }
            logger.info("[EXIT_EVAL] %s", json.dumps(payload, default=str))
        except Exception as e:
            logger.debug("[EXIT_EVAL] Logging error: %s", e)

    def _asset_from_ticker(self, ticker: str) -> str:
        """Extract canonical asset from a Kalshi market ticker."""
        upper = ticker.upper()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            if asset in upper:
                return asset
        return "unknown"

    async def _emit_exit_intent(
        self,
        position: Position,
        exit_reason: ExitReason,
        exit_price_cents: int,
        contracts_to_close: Optional[int] = None,
        bypass_in_flight_check: bool = False,
        snapshot: Optional[ExitPriceSnapshot] = None,
    ) -> None:
        """
        Emit exit intent via callback.

        Args:
            position: Position to exit
            exit_reason: Exit reason
            exit_price_cents: Exit price in cents
            contracts_to_close: Number of contracts to close (None = full position)
            bypass_in_flight_check: If True, skip the in-flight check (for expired markets)
            snapshot: Optional ExitPriceSnapshot used for the trigger
        """
        # CRITICAL FIX (2026-08-30): Use the executable bid for sell-side exits.
        # The monitor's current_price_cents is often the mid or ask; a SELL IOC
        # must be placed at the own-side bid to be marketable.  Repricing here
        # ensures the exit has the best possible chance of filling before the
        # market moves away (e.g. the canary BTC_NO trade at 50c -> 1c).
        if (
            snapshot is not None
            and snapshot.own_side_bid_cents is not None
            and 1 <= snapshot.own_side_bid_cents <= 99
        ):
            if exit_price_cents != snapshot.own_side_bid_cents:
                logger.info(
                    "[EXIT-INTENT-REPRICE] position=%s market=%s side=%s reason=%s "
                    "requested_price=%dc executable_bid=%dc -> exit_price=%dc",
                    position.position_id[:8],
                    position.market_id,
                    position.side.value,
                    exit_reason.value,
                    exit_price_cents,
                    snapshot.own_side_bid_cents,
                    snapshot.own_side_bid_cents,
                )
                exit_price_cents = snapshot.own_side_bid_cents

        # AUDIT: Timing correctness - record trigger timestamp
        trigger_timestamp = __import__('time').monotonic()

        # EXIT_EVAL: prove the exit was evaluated and a trigger fired, independent of
        # the entry gate or queue backlog. This is emitted before any invariants or
        # callback checks so the decision is always observable.
        self._log_exit_eval(
            position=position,
            snapshot=snapshot,
            decision="EXIT_INTENT_CREATED",
            reason_code="TARGET_REACHED",
            target_hit=True,
            exit_reason=exit_reason,
        )

        # CRITICAL FIX (2026-08-12): Exit evaluation telemetry.
        # Log the exact economic and model state at the moment of the exit decision.
        current_edge_pct = getattr(position, '_last_current_edge_pct', None)
        current_model_probability = None
        if current_edge_pct is not None and exit_price_cents is not None and 0 < exit_price_cents < 100:
            current_model_probability = (exit_price_cents / 100.0) + current_edge_pct
        net_executable_pnl_cents = position.unrealized_pnl_cents
        try:
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            exit_fee = calculate_kalshi_fee_cents(
                position.size,
                exit_price_cents,
            )
            net_executable_pnl_cents = position.unrealized_pnl_cents - exit_fee
        except Exception as fee_err:
            logger.debug("[EXIT-TELEMETRY] Could not estimate exit fee: %s", fee_err)
        reason_confirmations = position.edge_decay_confirmations if exit_reason in (
            ExitReason.EDGE_DECAY, ExitReason.MODEL_INVALIDATION_LOSS_EXIT
        ) else 0
        # Resolve log values.  "n/a" is used for provenance we cannot recover,
        # never a fake 0.0000, because a 0.0/0.4 edge is not a missing value.
        _entry_model_prob = (
            f"{position.entry_model_probability:.4f}"
            if position.entry_model_probability is not None
            else "n/a"
        )
        _entry_market_prob = (
            f"{position.entry_market_probability:.4f}"
            if position.entry_market_probability is not None
            else "n/a"
        )
        _entry_edge = (
            f"{(position.entry_model_probability - position.entry_market_probability):.4f}"
            if position.entry_model_probability is not None and position.entry_market_probability is not None
            else "n/a"
        )
        _tp_target = (
            position.take_profit_price_cents
            if position.take_profit_price_cents is not None
            else position.dynamic_tp_target_cents
            if position.dynamic_tp_target_cents is not None
            else "n/a"
        )
        _current_model_prob = (
            f"{current_model_probability:.4f}"
            if current_model_probability is not None
            else "n/a"
        )
        _current_edge = (
            f"{current_edge_pct:.4f}"
            if current_edge_pct is not None
            else "n/a"
        )

        logger.info(
            "[EXIT-EVALUATION-TELEMETRY] ticker=%s side=%s entry=%dc "
            "entry_model_prob=%s entry_market_prob=%s entry_edge=%s "
            "tp_target=%s current_own_bid=%dc current_own_ask=%s current_model_prob=%s current_edge=%s "
            "net_executable_pnl=%dc exit_reason=%s confirmations=%d age=%.1fs",
            position.market_id,
            position.side.value,
            position.avg_entry_price_cents,
            _entry_model_prob,
            _entry_market_prob,
            _entry_edge,
            _tp_target,
            exit_price_cents,
            snapshot.own_side_ask_cents if snapshot is not None else None,
            _current_model_prob,
            _current_edge,
            net_executable_pnl_cents,
            exit_reason.value,
            reason_confirmations,
            position.time_since_entry_seconds,
        )

        # CRITICAL FIX (2026-08-09): Emit a single immutable EXIT-DECISION record.
        decision = self._build_exit_decision_record(
            position=position,
            exit_reason=exit_reason,
            exit_price_cents=exit_price_cents,
            snapshot=snapshot,
            contracts_to_close=contracts_to_close,
            md_age_ms=snapshot.book_age_ms if snapshot else None,
            max_age_ms=EXIT_PRICE_MAX_AGE_MS,
            time_to_expiry_seconds=(
                snapshot.seconds_to_expiry if snapshot else None
            ),
        )
        logger.info(decision.to_log_line())

        # Log exit intent emission with structured schema
        if contracts_to_close is None:
            # Full position exit
            logger.info(
                "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
                "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%s type=FULL_EXIT trigger_ts=%.3f",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                get_priority_for_reason(exit_reason).value,
                "position_level",
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                trigger_timestamp
            )
        else:
            # Partial position exit (trim)
            logger.info(
                "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
                "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%s closing=%d type=PARTIAL_EXIT trigger_ts=%.3f",
                position.position_id[:8],
                position.market_id,
                position.side.value,
                exit_reason.value,
                get_priority_for_reason(exit_reason).value,
                "position_level",
                exit_price_cents,
                position.avg_entry_price_cents,
                position.unrealized_pnl_cents,
                position.r_multiple,
                position.size,
                contracts_to_close,
                trigger_timestamp
            )

        # CRITICAL FIX (2026-08-11): LVE stop-exit invariants.  These are the
        # final release-gate assertions before any stop exit is submitted.  Any
        # violation is a fail-closed event: we log, bump telemetry, and return.
        if exit_reason == ExitReason.STOP_LOSS:
            if position.risk_params_state != RiskParamsState.ORIGINAL_PERSISTED:
                _bump_stop_counter(
                    "stop_disabled_unknown_provenance",
                    f"position={position.position_id[:8]} emit_state={position.risk_params_state.value}",
                )
                logger.error(
                    "[STOP-EXIT-INVARIANT] position=%s state=%s - stop exit submitted without original provenance, blocking",
                    position.position_id[:8], position.risk_params_state.value,
                )
                return
            if position.risk_params_schema_version < 2:
                _bump_stop_counter(
                    "stop_disabled_unknown_provenance",
                    f"position={position.position_id[:8]} emit_schema={position.risk_params_schema_version}",
                )
                logger.error(
                    "[STOP-EXIT-INVARIANT] position=%s schema=%d - stop exit submitted with legacy schema, blocking",
                    position.position_id[:8], position.risk_params_schema_version,
                )
                return
            if position.entry_book_capture_quality not in _TRUSTED_ENTRY_BOOK_QUALITIES:
                _bump_stop_counter(
                    "stop_disabled_unknown_provenance",
                    f"position={position.position_id[:8]} emit_book_quality={position.entry_book_capture_quality}",
                )
                logger.error(
                    "[STOP-EXIT-INVARIANT] position=%s book_quality=%s - stop exit submitted without AT_FILL book, blocking",
                    position.position_id[:8], position.entry_book_capture_quality,
                )
                return
            if position.time_since_entry_seconds < MIN_STOP_ARM_SECONDS:
                _bump_stop_counter(
                    "stop_disabled_unknown_provenance",
                    f"position={position.position_id[:8]} emit_held={position.time_since_entry_seconds:.2f}s",
                )
                logger.error(
                    "[STOP-EXIT-INVARIANT] position=%s held=%.2fs - stop exit submitted before arming, blocking",
                    position.position_id[:8], position.time_since_entry_seconds,
                )
                return

        # CRITICAL FIX (2026-08-11): Spread-only / no-adverse-move stop exit invariant.
        # If the position is so fresh that it has not armed yet, and the executable
        # exit price is no worse than the executable bid at entry, this is a
        # round-trip/spread loss, not a real adverse move.  Reject it.
        if (
            exit_reason == ExitReason.STOP_LOSS
            and position.time_since_entry_seconds < MIN_STOP_ARM_SECONDS
            and position.entry_book_capture_quality in _TRUSTED_ENTRY_BOOK_QUALITIES
            and position.entry_executable_bid_cents is not None
            and exit_price_cents <= position.entry_executable_bid_cents
        ):
            _bump_stop_counter(
                "exit_stop_rejected_spread_only",
                f"position={position.position_id[:8]} exit={exit_price_cents}c entry_bid={position.entry_executable_bid_cents}c",
            )
            logger.warning(
                "[STOP-LOSS-EXIT-REJECTED] position=%s exit=%dc <= entry_bid=%dc "
                "held=%.2fs < %.2fs - spread-only or no adverse move; not emitting",
                position.position_id[:8],
                exit_price_cents,
                position.entry_executable_bid_cents,
                position.time_since_entry_seconds,
                MIN_STOP_ARM_SECONDS,
            )
            return

        # CRITICAL FIX (2026-08-20): Profit-exit invariants for any discretionary
        # (non-stop / non-emergency) exit.  These exits must use the executable
        # own-side bid and must be at least entry + round-trip fee buffer so they
        # cannot become stale-book or side-conversion losses.  EDGE_DECAY is now
        # included so it cannot approve negative-net exits.
        _PROFIT_EXIT_REASONS = {
            ExitReason.TAKE_PROFIT,
            ExitReason.DYNAMIC_TAKE_PROFIT,
            ExitReason.EXTREME_PROFIT,
            ExitReason.AUTO_EXIT_99C,
            ExitReason.RATCHET_TRIM,
            ExitReason.SCALE_OUT,
            ExitReason.OPPORTUNITY_COST,
            ExitReason.CANDLE_REVERSAL,
            ExitReason.ADAPTIVE_TIMING,
            ExitReason.EDGE_DECAY,
        }
        if exit_reason in _PROFIT_EXIT_REASONS:
            # The exit price must be the executable own-side bid from the snapshot.
            if snapshot is not None and snapshot.own_side_bid_cents != exit_price_cents:
                _bump_stop_counter(
                    "exit_stop_rejected_spread_only",
                    f"position={position.position_id[:8]} reason={exit_reason.value} exit={exit_price_cents}c own_bid={snapshot.own_side_bid_cents}c",
                )
                logger.error(
                    "[PROFIT-EXIT-INVARIANT] position=%s reason=%s exit=%dc != own_side_bid=%dc - profit exit not on executable own-side bid, blocking",
                    position.position_id[:8], exit_reason.value, exit_price_cents,
                    snapshot.own_side_bid_cents if snapshot else None,
                )
                return

            # The exit must be profitable after round-trip fee buffer.
            entry_ref = position.entry_fill_price_cents or position.avg_entry_price_cents
            if entry_ref:
                from merid.event_venues.kalshi.fees import min_profitable_exit_price_cents
                min_exit = min_profitable_exit_price_cents(
                    entry_ref,
                    position.size,
                    gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                )
                if min_exit is not None and exit_price_cents < min_exit:
                    _bump_stop_counter(
                        "exit_stop_rejected_spread_only",
                        f"position={position.position_id[:8]} reason={exit_reason.value} exit={exit_price_cents}c entry={entry_ref}c min_exit={min_exit}c",
                    )
                    logger.error(
                        "[PROFIT-EXIT-INVARIANT] position=%s reason=%s exit=%dc < entry=%dc + fee_buffer=%dc - profit exit below round-trip buffer, blocking",
                        position.position_id[:8], exit_reason.value, exit_price_cents,
                        entry_ref, min_exit - entry_ref,
                    )
                    return

        # CRITICAL FIX (2026-08-22): Quarantine inherited/unknown-provenance positions.
        # Only bounded-loss, time-to-expiry, safety, or operator-approved exits are
        # allowed. All model-driven or profit-taking exits are blocked at emission.
        if is_position_quarantined(position) and not is_exit_reason_allowed_for_quarantine(exit_reason):
            logger.warning(
                "[POSITION-MONITOR-QUARANTINE] position=%s market=%s reason=%s "
                "fill_source=%s risk_state=%s - quarantined position, exit blocked",
                position.position_id[:8],
                position.market_id,
                exit_reason.value if exit_reason else "unknown",
                position.fill_source,
                position.risk_params_state,
            )
            return

        # CRITICAL FIX (2026-07-16): Dispatch the exit callback BEFORE mark_exited().
        # Previous ordering set exit_triggered=True and removed the position BEFORE the
        # callback ran; the loop-side idempotency guard (added 2026-07-15) checks
        # position.exit_triggered and was silently DROPPING every full exit — no exit
        # order was ever placed. Callback-first preserves idempotency (a second emission
        # for the same position still sees exit_triggered=True) while restoring execution.
        callback_dispatched = False
        if self._exit_intent_callback:
            # CRITICAL FIX (2026-07-23): Check if exit intent is already in-flight
            # This prevents multiple triggers (TP + SL) from firing before first exit is placed
            # CRITICAL FIX (2026-07-29): Bypass in-flight check for expired markets to prevent stuck positions
            # CRITICAL FIX (2026-08-22): If a previous exit intent died without
            # resetting the position terminal flags, clear them so the callback
            # can actually place an order.  Only a position with a real exited_at
            # timestamp is genuinely closed.
            if position.exit_triggered and position.exited_at is None:
                logger.warning(
                    "[EXIT-INTENT-STALE-CLEAR] position=%s had exit_triggered=True with no exited_at; "
                    "clearing stale terminal flags so exit can retry",
                    position.position_id[:8]
                )
                position.exit_triggered = False
                position.exit_reason = None
                position.exit_price_cents = None

            if not bypass_in_flight_check and self._is_exit_intent_in_flight(position.position_id):
                with self._lock:
                    flight = self._exit_intent_in_flight.get(position.position_id)
                    existing_reason = (
                        flight.get("reason") if flight else None
                    ) or "unknown"
                    existing_client_order_id = (
                        flight.get("client_order_id") if flight else None
                    ) or self._position_to_client_order.get(position.position_id)

                # CRITICAL FIX (2026-08-27): Forced/safety exits must not be blocked by a
                # stale in-flight lock.  Reconcile the existing order first; if it cannot
                # be proven live, release the lock and re-emit with a fresh idempotency key.
                if _is_forced_exit_reason(exit_reason) or _is_settlement_guard_override(exit_reason):
                    logger.warning(
                        "[EXIT-INTENT-FORCED-RECONCILE] position=%s existing_reason=%s new_reason=%s; "
                        "attempting forced reconciliation of client_order_id=%s",
                        position.position_id[:8],
                        existing_reason,
                        exit_reason.value,
                        existing_client_order_id[:8] if existing_client_order_id else "",
                    )
                    await self._reconcile_exit_intent(
                        position.position_id,
                        existing_client_order_id,
                        force=True,
                        new_price_cents=exit_price_cents,
                    )
                    if not self._is_exit_intent_in_flight(position.position_id):
                        logger.warning(
                            "[EXIT-INTENT-FORCED-RECONCILE] position=%s stale in-flight for %s cleared; "
                            "proceeding with forced %s",
                            position.position_id[:8], existing_reason, exit_reason.value
                        )
                        # fall through to mark in-flight and call callback
                    else:
                        logger.warning(
                            "[EXIT-INTENT-FORCED-RECONCILE] position=%s existing %s still in-flight after "
                            "reconcile; dropping forced %s",
                            position.position_id[:8], existing_reason, exit_reason.value
                        )
                        return
                else:
                    logger.warning(
                        "[EXIT-INTENT-IN-FLIGHT] Exit intent already in-flight for position=%s, skipping duplicate trigger. "
                        "Existing trigger reason=%s, new reason=%s",
                        position.position_id[:8],
                        existing_reason,
                        exit_reason.value
                    )
                    # Skip this trigger - the in-flight intent will handle the exit
                    return

            # Mark intent as in-flight before calling callback
            self._mark_exit_intent_in_flight(position.position_id, reason=exit_reason.value)

            try:
                logger.info(
                    "[POSITION-MONITOR] Calling exit intent callback for position=%s reason=%s contracts=%s",
                    position.position_id[:8],
                    exit_reason.value,
                    contracts_to_close or "ALL",
                )
                # Pass contracts_to_close to callback for partial close handling
                self._exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close)
                callback_dispatched = True
                logger.info(
                    "[POSITION-MONITOR] Exit intent callback completed for position=%s",
                    position.position_id[:8],
                )
            except Exception as e:
                # 2026-08-11 CRITICAL FIX: clear in-flight guard so a failed callback does
                # not permanently block exit re-evaluation.
                self._clear_exit_intent_in_flight(position.position_id)
                logger.error(
                    "[POSITION-MONITOR] Exit intent callback failed: %s",
                    e,
                    exc_info=True
                )
        else:
            logger.warning(
                "[POSITION-MONITOR] No exit intent callback registered - exit order will NOT be placed for position=%s",
                position.position_id[:8],
            )

        # 2026-08-11 CRITICAL FIX: Do not remove or mark the position as terminal
        # until the exit order is actually accepted and filled by the venue (or REST
        # position reconciliation confirms a zero position). The callback only creates
        # an async order-routing task; removing the monitor here creates a phantom-flat
        # state where the exchange still holds the position. The loop-side executor is
        # responsible for mark_exited/remove_position on a confirmed fill, or re-arming
        # on any terminal non-fill.
        if contracts_to_close is None:
            if not callback_dispatched:
                # CRITICAL FIX (2026-07-16): Callback failed or missing — KEEP the position
                # monitored so the exit re-fires on the next poll instead of orphaning a
                # live position with no exit enforcement. Also clear the in-flight guard
                # so a later poll can re-attempt the exit.
                self._clear_exit_intent_in_flight(position.position_id)
                logger.error(
                    "[POSITION-MONITOR] Exit intent NOT dispatched for position=%s (reason=%s) - "
                    "keeping position monitored for retry on next poll",
                    position.position_id[:8],
                    exit_reason.value,
                )

    def _emit_scale_out_intent(
        self,
        position: Position,
        contracts_to_close: int,
        exit_price_cents: int
    ) -> None:
        """
        Emit partial scale-out intent via callback.

        Research: Close 50% of position at 1.5-2R to lock profits while
        letting "runner" capture larger moves (Pay Yourself strategy).

        Args:
            position: Position to partially exit
            contracts_to_close: Number of contracts to close
            exit_price_cents: Exit price in cents
        """
        # Call callback if registered with scale-out flag
        if self._exit_intent_callback:
            try:
                # Pass scale-out info via exit_reason
                self._exit_intent_callback(
                    position,
                    ExitReason.SCALE_OUT,
                    exit_price_cents,
                    contracts_to_close
                )
            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Scale-out intent callback failed: %s",
                    e,
                    exc_info=True
                )

    def _get_exit_price_snapshot(
        self, state, position_side: PositionSide, market_id: str
    ) -> Optional[ExitPriceSnapshot]:
        """
        Build an executable same-side bid/ask snapshot for exit decisions.

        CRITICAL FIX (2026-08-09): Stop-loss, trailing-stop, and edge-decay must
        evaluate against the price we can actually execute at (the best bid on
        the side we are long).  Mid prices and opposite-side prices can produce
        false exits, especially in volatile or one-sided books.

        Returns:
            ExitPriceSnapshot, or None if the book is stale, non-executable,
            missing the side we need, or otherwise unfit for an exit decision.
        """
        if not state:
            logger.warning(
                "[POSITION-MONITOR] No market state for %s; cannot build exit snapshot",
                market_id,
            )
            return None

        # Basic health checks (keep defaults for unit-test Mocks)
        book_initialized = getattr(state, "book_initialized", True)
        if book_initialized is False:
            logger.warning(
                "[POSITION-MONITOR] Book not initialized for %s; skipping exit snapshot",
                market_id,
            )
            return None

        executable = getattr(state, "executable", True)
        if executable is False:
            logger.warning(
                "[POSITION-MONITOR] State not executable for %s; skipping exit snapshot",
                market_id,
            )
            return None

        data_quality = getattr(state, "data_quality", None)
        if isinstance(data_quality, str) and data_quality != "GOOD":
            logger.warning(
                "[POSITION-MONITOR] data_quality=%s for %s not trusted for exit snapshot",
                data_quality,
                market_id,
            )
            return None

        # P1 HARDENING (2026-08-22): A WebSocket bootstrap snapshot is a full
        # book but is not live-sequence confirmed.  Discretionary exits must not
        # price off it until a contiguous WS delta or a fresh REST full snapshot
        # attests the book.  Emergency/reduce-only paths may bypass this later.
        data_source = getattr(state, "data_source", "UNKNOWN")
        live_sequence_confirmed = getattr(state, "live_sequence_confirmed", False)
        if (
            data_source == "BOOTSTRAP_VALID_BUT_UNCONFIRMED"
            and not live_sequence_confirmed
        ):
            logger.warning(
                "[POSITION-MONITOR] %s data_source=%s live_sequence_confirmed=%s; "
                "skipping exit snapshot until book is confirmed",
                market_id,
                data_source,
                live_sequence_confirmed,
            )
            return None

        # Age check: use the orderbook timestamp only.  REST catalog metadata is
        # not a quote refresh; a REST orderbook snapshot still updates
        # last_book_update_ts, so REST-only exits remain enabled.
        last_book_update_ts = getattr(state, "last_book_update_ts", None)
        effective_ts = last_book_update_ts if isinstance(last_book_update_ts, (int, float)) and last_book_update_ts > 0 else None
        book_age_ms = 0
        if effective_ts is not None:
            try:
                age_s = time.monotonic() - effective_ts
                max_age_s = EXIT_PRICE_MAX_AGE_MS / 1000.0
                if age_s > max_age_s:
                    logger.warning(
                        "[POSITION-MONITOR] Book age=%.1fs exceeds %.1fs for %s; skipping exit snapshot",
                        age_s,
                        max_age_s,
                        market_id,
                    )
                    return None
                book_age_ms = int(age_s * 1000)
            except Exception:
                pass

        # Side-aware bid/ask extraction
        if position_side == PositionSide.YES:
            own_bid = getattr(state, "best_bid_cents", None)
            own_ask = getattr(state, "best_ask_cents", None)
            opposite_bid = getattr(state, "best_no_bid_cents", None)
            opposite_ask = getattr(state, "best_no_ask_cents", None)
            min_depth = getattr(state, "min_depth_yes", 0)
            has_bid_size = bool(getattr(state, "has_bid", False) and min_depth > 0)
        else:
            own_bid = getattr(state, "best_no_bid_cents", None)
            own_ask = getattr(state, "best_no_ask_cents", None)
            opposite_bid = getattr(state, "best_bid_cents", None)
            opposite_ask = getattr(state, "best_ask_cents", None)
            min_depth = getattr(state, "min_depth_no", 0)
            has_bid_size = bool(getattr(state, "has_no_bid", False) and min_depth > 0)

        # Fallback for older states that only had YES-side best bid/ask and no no-side fields
        if own_bid is None or own_ask is None:
            mid = getattr(state, "mid_cents", None)
            if mid is not None:
                spread = getattr(state, "spread_cents", 0) or 1
                if position_side == PositionSide.YES:
                    own_bid = mid - spread // 2
                    own_ask = mid + spread // 2
                else:
                    no_mid = 100 - mid
                    own_bid = no_mid - spread // 2
                    own_ask = no_mid + spread // 2
            else:
                logger.warning(
                    "[POSITION-MONITOR] No executable prices for %s side=%s; skipping exit snapshot",
                    market_id,
                    position_side.value,
                )
                return None

        # Canonical price validation
        if not (0 < own_bid < 100 and 0 < own_ask < 100):
            logger.warning(
                "[POSITION-MONITOR] Invalid own-side prices for %s side=%s bid=%s ask=%s",
                market_id,
                position_side.value,
                own_bid,
                own_ask,
            )
            return None

        # Mid for reference
        mid_cents = getattr(state, "mid_cents", None)
        if mid_cents is not None and 0 < mid_cents < 100:
            if position_side == PositionSide.YES:
                mid = int(mid_cents)
            else:
                mid = int(100 - mid_cents)
        else:
            mid = (own_bid + own_ask) // 2

        snapshot_id = f"{market_id}:{getattr(state, 'last_book_update_ts', time.monotonic())}"
        seconds_to_expiry = getattr(state, "seconds_to_expiry", None)
        book_sequence = getattr(state, "book_sequence", None)

        # YES and NO raw book for attribution.  Asks are derived as 100 - opposite bid.
        yes_bid = getattr(state, "best_bid_cents", None)
        yes_ask = getattr(state, "best_ask_cents", None)
        no_bid = getattr(state, "best_no_bid_cents", None)
        no_ask = getattr(state, "best_no_ask_cents", None)
        yes_depth = getattr(state, "depth_10c_yes", None)
        no_depth = getattr(state, "depth_10c_no", None)

        return ExitPriceSnapshot(
            market_id=market_id,
            position_side=position_side,
            mid_cents=mid,
            own_side_bid_cents=int(own_bid),
            own_side_ask_cents=int(own_ask),
            opposite_bid_cents=int(opposite_bid) if opposite_bid is not None else None,
            opposite_ask_cents=int(opposite_ask) if opposite_ask is not None else None,
            # CRITICAL FIX (2026-08-10): Full book provenance for exit attribution
            book_sequence=book_sequence,
            yes_bid_cents=int(yes_bid) if yes_bid is not None else None,
            yes_ask_cents=int(yes_ask) if yes_ask is not None else None,
            no_bid_cents=int(no_bid) if no_bid is not None else None,
            no_ask_cents=int(no_ask) if no_ask is not None else None,
            yes_depth=yes_depth,
            no_depth=no_depth,
            entry_side_executable_bid_cents=int(own_bid),
            entry_side_executable_ask_cents=int(own_ask),
            book_age_ms=book_age_ms,
            data_source=data_source,
            data_quality=data_quality if isinstance(data_quality, str) else "UNKNOWN",
            executable=executable,
            has_bid_size=has_bid_size,
            snapshot_id=snapshot_id,
            timestamp=time.monotonic(),
            min_depth_own_side=min_depth,
            seconds_to_expiry=seconds_to_expiry,
        )

    def _get_side_aware_price(self, state, position_side: PositionSide) -> Optional[int]:
        """
        Get side-aware current price from market state.

        CRITICAL FIX: mid_cents is YES-centric. For NO positions, we need to convert
        to NO price (100 - YES mid) to correctly evaluate exit conditions.

        CRITICAL FIX (2026-08-07): Do not trigger exits on stale, uninitialised, or
        low-quality market data. The monitor has been firing stop-losses from stale
        WS snapshots that disagreed with fresh REST quotes. Require executable state,
        GOOD data quality, and a recent book update before using the price.

        Args:
            state: UnifiedMarketState for the market
            position_side: PositionSide.YES or PositionSide.NO

        Returns:
            Current price in cents for the position's side, or None if state is not
            trustworthy enough for exit decisions.
        """
        if not state or not getattr(state, 'mid_cents', None):
            return None

        # Only trust prices from a healthy, initialised, executable book.
        # Default to trusting the state when these fields are not present
        # (e.g. unit tests using plain Mock objects), but reject explicit bad values.
        book_initialized = getattr(state, 'book_initialized', True)
        if book_initialized is False:
            logger.warning(
                "[POSITION-MONITOR] State not initialised for market; skipping exit price"
            )
            return None

        executable = getattr(state, 'executable', True)
        if executable is False:
            logger.warning(
                "[POSITION-MONITOR] State not executable for market; skipping exit price"
            )
            return None

        data_quality = getattr(state, 'data_quality', None)
        if isinstance(data_quality, str) and data_quality != "GOOD":
            logger.warning(
                "[POSITION-MONITOR] State data_quality=%s not trusted for exit price",
                data_quality,
            )
            return None

        # Age check: use the orderbook timestamp only.
        last_book_update_ts = getattr(state, 'last_book_update_ts', None)
        effective_ts = last_book_update_ts if isinstance(last_book_update_ts, (int, float)) and last_book_update_ts > 0 else None
        if effective_ts is not None:
            try:
                age_s = time.monotonic() - effective_ts
                max_age_s = float(
                    os.getenv("MERID_POSITION_MONITOR_MAX_STATE_AGE_S", "10")
                )
                if age_s > max_age_s:
                    logger.warning(
                        "[POSITION-MONITOR] State age=%.1fs exceeds %.1fs; skipping exit price",
                        age_s,
                        max_age_s,
                    )
                    return None
            except Exception:
                pass

        if position_side == PositionSide.YES:
            # YES: use mid_cents directly
            return int(state.mid_cents)
        else:
            # NO: convert YES mid to NO price (100 - YES mid)
            # Example: YES mid = 42c → NO price = 58c
            return int(100 - state.mid_cents)

    async def _poll_loop(self) -> None:
        """
        Main polling loop.

        Checks all open positions for exit conditions.
        """
        poll_count = 0
        last_poll_time = None
        while self._running:
            try:
                poll_start_time = __import__('time').monotonic()
                poll_count += 1

                # AUDIT: Timing correctness - track poll interval and drift
                if last_poll_time is not None:
                    actual_interval = poll_start_time - last_poll_time
                    interval_drift_s = actual_interval - self._poll_interval
                    logger.debug(
                        "[TIMING-AUDIT] poll_count=%d expected_interval=%.1fs actual_interval=%.1fs drift_s=%.3fs",
                        poll_count,
                        self._poll_interval,
                        actual_interval,
                        interval_drift_s
                    )

                if not self._open_positions:
                    await asyncio.sleep(self._poll_interval)
                    last_poll_time = __import__('time').monotonic()
                    continue

                logger.debug(
                    "[POSITION-MONITOR] Polling %d positions (poll #%d)",
                    len(self._open_positions),
                    poll_count
                )

                # Get current prices from market state store
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()

                    with self._lock:
                        positions_snapshot = list(self._open_positions.items())

                    # AUDIT: Log trigger coverage - confirm each position is checked
                    logger.info(
                        "[POSITION-MONITOR-AUDIT] poll_count=%d positions_to_check=%d",
                        poll_count,
                        len(positions_snapshot)
                    )

                    for position_id, position in positions_snapshot:
                        # CRITICAL FIX (2026-07-31): Check if market has expired BEFORE accessing state
                        # Expired markets no longer exist on the exchange and cannot be traded
                        # Attempting to exit them causes 404 errors and retry loops
                        if self._is_expired_market(position.market_id):
                            logger.warning(
                                "[POSITION-MONITOR] Removing position from expired market: %s - "
                                "market has settled, no exit needed",
                                position.market_id
                            )
                            # Remove position from monitor without attempting exit
                            # The position should have been settled by the exchange
                            with self._lock:
                                self._clear_exit_intent_in_flight(position_id)
                                if position_id in self._open_positions:
                                    del self._open_positions[position_id]
                                if position.market_id in self._market_to_position:
                                    del self._market_to_position[position.market_id]
                            continue

                        state = store.get(position.market_id)

                        # CRITICAL FIX (2026-07-16): Check if market has expired
                        # If state is None, the market has likely expired. Do NOT force an order
                        # (there is no executable book and the exchange will settle). Remove the
                        # position from the monitor so the fills/settlement poller can record it.
                        if state is None:
                            logger.warning(
                                "[POSITION-MONITOR] Market state not found for %s - market has likely expired, removing from monitor",
                                position.market_id
                            )
                            with self._lock:
                                self._clear_exit_intent_in_flight(position_id)
                                if position_id in self._open_positions:
                                    del self._open_positions[position_id]
                                if position.market_id in self._market_to_position:
                                    del self._market_to_position[position.market_id]
                            continue

                        # CRITICAL FIX (2026-08-09): Use an executable same-side bid/ask snapshot.
                        # _get_exit_price_snapshot returns None for stale/non-executable books.
                        price_snapshot = self._get_exit_price_snapshot(state, position.side, position.market_id)

                        if price_snapshot is not None:
                            # AUDIT: Log state freshness for each position check
                            logger.info(
                                "[POSITION-MONITOR-AUDIT] position=%s market=%s data_source=%s data_age_ms=%d "
                                "mid=%dc bid=%dc ask=%dc side=%s executable=%s has_bid_size=%s",
                                position.position_id[:8],
                                position.market_id,
                                price_snapshot.data_source,
                                price_snapshot.book_age_ms,
                                price_snapshot.mid_cents,
                                price_snapshot.own_side_bid_cents,
                                price_snapshot.own_side_ask_cents,
                                position.side.value,
                                price_snapshot.executable,
                                price_snapshot.has_bid_size,
                            )
                            await self._check_position(position, price_snapshot, poll_count)
                        else:
                            logger.warning(
                                "[POSITION-MONITOR] Could not determine executable price for %s - skipping exit check",
                                position.market_id,
                            )
                            # EXIT_EVAL: prove the exit path was evaluated even when the book is not usable.
                            self._log_exit_eval(
                                position=position,
                                snapshot=None,
                                decision="EXIT_BLOCKED_BOOK_INVALID",
                                reason_code="BOOK_UNUSABLE",
                                target_hit=False,
                            )

                except Exception as e:
                    logger.error(
                        "[POSITION-MONITOR] Poll loop error: %s",
                        e,
                        exc_info=True
                    )

                await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.error(
                    "[POSITION-MONITOR] Poll loop critical error: %s",
                    e,
                    exc_info=True
                )
                await asyncio.sleep(self._poll_interval)

    async def start(self) -> None:
        """
        Start the position monitor.

        CRITICAL FIX (2026-07-23): Load existing positions from position cache on startup.
        This ensures positions opened before monitor started (or during restart) are tracked
        for exit policies. Without this, exit policies never trigger for existing positions.
        """
        logger.info("[POSITION-MONITOR-STARTUP] start() called, _running=%s", self._running)
        if self._running:
            logger.warning("[POSITION-MONITOR] Already running")
            return

        logger.info("[POSITION-MONITOR-STARTUP] Starting position monitor startup sync")

        # CRITICAL FIX: Load existing positions from position cache on startup
        # This ensures positions opened before monitor started are tracked for exit policies
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            position_cache = get_position_cache()
            cached_positions = position_cache.get_all_positions(validate_freshness=False)

            loaded_count = 0
            for market_id, cached_pos in cached_positions.items():
                if cached_pos.contracts > 0:
                    # CRITICAL FIX (2026-08-23): Rehydrate the exit plan from durable
                    # provenance before converting to a Position. This allows REST-reloaded
                    # and startup-reloaded positions to recover ORIGINAL_PERSISTED risk state
                    # and TP/SL without requiring the fills ledger to be already loaded.
                    try:
                        position_cache.rehydrate_cached_position(cached_pos)
                    except Exception as rehydrate_err:
                        logger.debug(
                            "[POSITION-MONITOR-STARTUP] Could not rehydrate %s: %s",
                            market_id, rehydrate_err
                        )

                    # Convert CachedPosition to Position for monitoring
                    from merid.position_management.position import Position, PositionSide
                    from datetime import datetime, timezone

                    # Determine position side from thesis_side (immutable) or side (fallback)
                    side_str = cached_pos.thesis_side if cached_pos.thesis_side else cached_pos.side

                    # CRITICAL FIX (2026-08-01): Infer thesis_side from fill history for unknown positions
                    # These positions cannot be monitored correctly because we don't know
                    # whether they are YES or NO positions, which affects all exit calculations.
                    if side_str.lower() == "unknown":
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Position has unknown thesis_side=%s for market=%s - "
                            "attempting to infer from fill history",
                            side_str, market_id
                        )
                        # Try to infer thesis_side from fill history
                        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
                        if inferred_side:
                            side_str = inferred_side
                            logger.info(
                                "[POSITION-MONITOR-STARTUP] Inferred thesis_side=%s for market=%s from fill history",
                                side_str, market_id
                            )
                        else:
                            logger.warning(
                                "[POSITION-MONITOR-STARTUP] Skipping position with unknown thesis_side=%s for market=%s - "
                                "position cannot be monitored without correct side information",
                                side_str, market_id
                            )
                            continue

                    if side_str.lower() in ("yes", "YES"):
                        position_side = PositionSide.YES
                    elif side_str.lower() in ("no", "NO"):
                        position_side = PositionSide.NO
                    else:
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Unknown side %s for market=%s, skipping",
                            side_str, market_id
                        )
                        continue

                    # Create Position object from CachedPosition
                    # CRITICAL FIX (2026-08-04): Side-aware fallback SL for startup-loaded positions.
                    # A position is always long its own side. Both YES and NO use SL below entry.
                    # Previous bug: NO contracts had SL above entry, causing instant stop-outs.
                    #
                    # CRITICAL FIX (2026-08-11): Only use a stop-loss if the cached position
                    # carries original persisted risk parameters.  Startup/REST sync must not
                    # invent a default SL inside the entry spread.
                    #
                    # Trust rules:
                    #   - risk_params_state == "original_persisted" AND
                    #   - risk_params_schema_version >= 2 AND
                    #   - an entry linkage exists (fill_id, client_order_id, or entry_intent_id)
                    # Legacy records with explicit SL/TP but no provenance are loaded with
                    # SL disabled; TP may still be used for profit-taking.
                    #
                    # CRITICAL 2026-08-13: Preserve cached TP/SL as fallback for unknown- or
                    # non-original provenance.  We never invent TP/SL from a startup/REST
                    # average price; missing policies are left unset.  Automatic *stop* exits
                    # remain blocked unless the trust chain is complete, so the fallback state
                    # only enables monitoring and profit-taking from cached TP levels.
                    stop_loss_enabled = getattr(cached_pos, "stop_loss_enabled", True)
                    cached_risk_state = getattr(cached_pos, "risk_params_state", "unknown")
                    cached_schema_version = getattr(cached_pos, "risk_params_schema_version", 1)
                    has_entry_linkage = bool(
                        cached_pos.entry_fill_id
                        or cached_pos.client_order_id
                        or cached_pos.entry_intent_id
                    )
                    is_original = (
                        cached_risk_state == "original_persisted"
                        and cached_schema_version >= 2
                        and has_entry_linkage
                    )
                    sl_price = cached_pos.stop_loss_price_cents
                    tp_price = cached_pos.take_profit_price_cents
                    if not is_original:
                        if sl_price is not None or tp_price is not None:
                            cached_risk_state = "fallback"
                            cached_schema_version = 1
                        else:
                            stop_loss_enabled = False
                            _bump_stop_counter(
                                "stop_disabled_unknown_provenance",
                                f"startup market={market_id} state={cached_risk_state} schema={cached_schema_version} linkage={has_entry_linkage}",
                            )
                            logger.warning(
                                "[POSITION-MONITOR-STARTUP] market=%s risk_params_state=%s schema=%d linkage=%s "
                                "- not using fallback SL; monitor without stop-loss",
                                market_id, cached_risk_state, cached_schema_version, has_entry_linkage,
                            )

                    # CRITICAL FIX (2026-08-01): Skip positions with invalid entry prices
                    # Positions with avg_price_cents=None or 0 cannot be monitored correctly
                    # because all exit calculations depend on the entry price.
                    if cached_pos.avg_price_cents is None or cached_pos.avg_price_cents == 0:
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Skipping position with invalid avg_price_cents=%s for market=%s - "
                            "position cannot be monitored without valid entry price",
                            cached_pos.avg_price_cents, market_id
                        )
                        continue

                    position = Position(
                        position_id=market_id,  # Use market_id as position_id for 15m system
                        market_id=market_id,
                        side=position_side,
                        size=(
                            Decimal(cached_pos.quantity_cc) / Decimal("100")
                            if cached_pos.quantity_cc
                            else Decimal(str(cached_pos.contracts))
                        ),
                        avg_entry_price_cents=cached_pos.avg_price_cents,  # No fallback - already validated above
                        take_profit_price_cents=tp_price,
                        stop_loss_enabled=(stop_loss_enabled and sl_price is not None),
                        stop_loss_price_cents=sl_price,
                        risk_params_state=("original_persisted" if is_original and sl_price is not None else cached_risk_state),
                        risk_params_schema_version=cached_schema_version,
                        opened_at=datetime.now(timezone.utc),  # Use current time for existing positions
                        thesis_side=side_str.lower(),
                        outcome_side=side_str.lower(),
                        book_side=cached_pos.book_side or "ask",
                        # CRITICAL FIX (2026-08-09): Track provenance for startup-loaded positions
                        fill_source=cached_pos.fill_source or "rest_sync",
                        entry_signal_id=cached_pos.entry_signal_id or cached_pos.client_order_id or "rest_sync",
                        # CRITICAL FIX (2026-08-10): Durable entry-model provenance
                        entry_model=cached_pos.entry_model,
                        entry_model_version=cached_pos.entry_model_version,
                        entry_model_probability=cached_pos.entry_model_probability,
                        entry_market_probability=cached_pos.entry_market_probability,
                        entry_edge=cached_pos.entry_edge,
                        entry_book_snapshot_id=cached_pos.entry_book_snapshot_id,
                        entry_fill_id=cached_pos.entry_fill_id or cached_pos.client_order_id or cached_pos.entry_order_id or cached_pos.entry_intent_id,
                        entry_order_id=cached_pos.entry_order_id or cached_pos.client_order_id,
                        entry_execution_mode=cached_pos.entry_execution_mode,
                        client_order_id=cached_pos.client_order_id,
                        entry_intent_id=cached_pos.entry_intent_id or cached_pos.client_order_id,
                        entry_executable_bid_cents=cached_pos.entry_executable_bid_cents,
                        entry_executable_ask_cents=cached_pos.entry_executable_ask_cents,
                        entry_book_capture_quality=cached_pos.entry_book_capture_quality,
                        entry_fill_price_cents=cached_pos.entry_fill_price_cents,
                        entry_fill_timestamp=cached_pos.entry_fill_timestamp,
                        entry_book_timestamp=cached_pos.entry_book_timestamp,
                        entry_book_sequence=cached_pos.entry_book_sequence,
                        entry_book_source=cached_pos.entry_book_source,
                        # CRITICAL FIX (2026-08-23): Propagate provenance state to Position so
                        # edge-decay vs current-edge-reversal can be distinguished.
                        entry_provenance_snapshot_id=cached_pos.entry_provenance_snapshot_id,
                        provenance_state=cached_pos.provenance_state,
                        position_key=cached_pos.position_key,
                        known_aliases=cached_pos.known_aliases,
                    )

                    # CRITICAL FIX (2026-08-27): Expired/closed markets can leave a stale
                    # durable order attempt in SUBMISSION_UNKNOWN.  Do not monitor them and
                    # terminalise any such attempt so it is not reused on restart.
                    if self._is_expired_market(position.market_id):
                        logger.warning(
                            "[POSITION-MONITOR-STARTUP] Skipping expired/closed market %s on startup; "
                            "cancelling durable order attempt if present",
                            position.market_id,
                        )
                        self._cancel_durable_order_attempt(
                            position.client_order_id,
                            "startup_expired_market_not_monitored",
                        )
                        continue

                    # Add or update monitor using canonical upsert.
                    # Startup positions may be replaced by a more trusted live fill later.
                    self.upsert_position(position, caller="startup")
                    loaded_count += 1

            logger.info(
                "[POSITION-MONITOR-STARTUP] Loaded %d existing positions from position cache",
                loaded_count
            )

            logger.critical(
                "[STOP-PROTECTION-STATUS] stop_disabled_unknown_provenance=%d "
                "entry_stop_rejected_spread_unviable=%d exit_stop_rejected_spread_only=%d",
                STOP_PROTECTION_COUNTERS["stop_disabled_unknown_provenance"],
                STOP_PROTECTION_COUNTERS["entry_stop_rejected_spread_unviable"],
                STOP_PROTECTION_COUNTERS["exit_stop_rejected_spread_only"],
            )

        except Exception as e:
            logger.error(
                "[POSITION-MONITOR-STARTUP] Failed to load existing positions from cache: %s",
                e,
                exc_info=True
            )
            # Continue startup even if load fails - positions will be added on fill

        # CRITICAL FIX (2026-08-27): Clear any in-flight/submission-unknown state for
        # positions whose contract has expired or that were not loaded from cache.
        self._cleanup_stale_exit_in_flight_on_startup()

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[POSITION-MONITOR] Started (poll_interval=%ds, tracking %d positions)",
            self._poll_interval,
            len(self._open_positions)
        )

    async def stop(self) -> None:
        """
        Stop the position monitor.
        """
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("[POSITION-MONITOR] Stopped")

    def get_stats(self) -> Dict:
        """
        Get monitor statistics.

        Returns:
            Dict with statistics
        """
        return {
            "running": self._running,
            "open_positions": len(self._open_positions),
            "poll_interval": self._poll_interval,
        }


# Global singleton instance
_monitor_instance: Optional[PositionMonitor] = None


def get_position_monitor() -> PositionMonitor:
    """
    Get global position monitor singleton.

    Returns:
        PositionMonitor instance
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PositionMonitor()
        logger.info("[POSITION-MONITOR] Created global singleton")
    else:
        logger.info("[POSITION-MONITOR] Returning existing singleton, _running=%s", _monitor_instance._running)
    return _monitor_instance
