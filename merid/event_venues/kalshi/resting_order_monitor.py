"""Dynamic resting order monitor for coherent risk contract enforcement.

This module periodically re-checks resting/limit orders against current
market signals (regime, volatility, model quality) and cancels or adjusts
orders that no longer satisfy the original risk contract.

Key features:
- Re-evaluates WindowResolution for each resting order
- Cancels orders when regime flips to defensive/halt
- Cancels orders when model quality degrades below threshold
- Cancels orders near expiry (pre-expiry cancel rule)
- Logs all dynamic cancellations for audit trail
- Health monitoring for loop liveness and data quality
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Any

logger = logging.getLogger(__name__)

# Market order fallback integration
try:
    from merid.event_venues.kalshi.market_order_fallback import (
        MarketOrderFallbackEngine,
        FallbackConfig,
        get_market_order_fallback_engine
    )
    _FALLBACK_AVAILABLE = True
except ImportError:
    _FALLBACK_AVAILABLE = False
    logger.warning("[RESTING_ORDER_MONITOR] Market order fallback module not available")

# Pre-expiry cancel rule: cancel resting orders when time to expiry below threshold
PRE_EXPIRY_CANCEL_THRESHOLD_MIN = 2  # 2 minutes before settlement

# Max hold time for 15m markets: cancel unfilled limit orders after 2-3 minutes
# This prevents stale orders from resting too long in fast-moving 15m markets
MAX_HOLD_SECONDS_15M = 60  # 1 minute for 15m markets - stale IOC/GTC orders must not persist

# Status constants for Kalshi portfolio endpoint normalization
TERMINAL_STATUSES = {"filled", "canceled", "expired", "rejected", "executed"}
RESTING_STATUSES = {"resting", "open", "partially_filled"}


def _normalize_status(raw_status: str) -> str:
    """Normalize Kalshi API status to internal vocabulary.
    
    Args:
        raw_status: Status string from Kalshi portfolio endpoint
        
    Returns:
        Normalized status string
    """
    status = (raw_status or "").lower()
    
    # Map known Kalshi statuses to internal vocabulary
    status_mapping = {
        "resting": "resting",
        "open": "open",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "executed": "filled",  # Kalshi may use "executed" synonymously with "filled"
        "canceled": "canceled",
        "cancelled": "canceled",  # Handle both spellings
        "expired": "expired",
        "rejected": "rejected",
    }
    
    return status_mapping.get(status, status)


@dataclass
class RestingOrderRecord:
    """Record of a resting order with its original risk contract.
    
    Primary key is (venue, kalshi_order_id) - intent_id is only for diagnostics.
    All state transitions come from Kalshi's portfolio view, not intent inference.
    """
    kalshi_order_id: str  # Server-side order ID from Kalshi (canonical handle)
    venue: str = "kalshi"
    ticker: str = ""
    side: str = ""
    action: str = ""
    original_size: int = 0
    remaining_size: int = 0  # Tracked from portfolio endpoint, not calculated
    filled_size: int = 0  # Cumulative filled size (original_size - remaining_size)
    price_cents: int = 0
    created_at: datetime = None
    asset: str = ""
    
    # Risk contract linkage
    window_resolution_id: str = ""
    exit_policy_id: str = ""
    risk_tier: str = ""
    max_hold_seconds: int = 600
    
    # Kalshi API fields for enforcement
    time_in_force: str = "gtc"  # Only "good_till_canceled" orders can rest
    order_expiration_ts: Optional[int] = None  # Unix timestamp from Kalshi
    stp: str = "taker_at_cross"  # Self-trade prevention: "taker_at_cross" or "maker"
    
    # Diagnostic fields (not primary keys)
    intent_id: str = ""  # For reconciling with original OrderIntent
    client_order_id: Optional[str] = None  # For idempotency checks
    
    # Original signal context
    original_minutes_to_expiry: Optional[float] = None
    original_edge_pct: Optional[float] = None
    confidence: Optional[float] = None
    
    # Status tracking (from portfolio endpoint)
    status: str = ""  # Set at registration time, not as default
    last_sync_at: Optional[datetime] = None
    missing_data_count: int = 0  # Count consecutive "no data" responses
    
    # Health monitoring
    last_heartbeat: Optional[datetime] = None  # Last successful poll/sync
    consecutive_sync_failures: int = 0  # Count consecutive sync failures
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.remaining_size == 0:
            self.remaining_size = self.original_size


@dataclass
class RecheckResult:
    """Result of re-checking a resting order."""
    intent_id: str
    ticker: str
    action: str  # "keep", "cancel", "adjust"
    reason: str
    current_regime: Optional[str] = None
    current_vol_tier: Optional[str] = None
    model_quality_good: Optional[bool] = None


@dataclass
class ExitOrderState:
    """State tracking for exit orders with retry logic.
    
    Exit orders are critical for risk management and must be actively managed
    until filled. This state tracks retry attempts, aggressiveness adjustments,
    and timeout handling for exit orders that don't fill immediately.
    """
    order_id: str  # Kalshi order ID
    asset: str  # Asset ticker (BTC, ETH, SOL, XRP, DOGE)
    side: str  # Order side (yes/no)
    action: str  # Order action (buy/sell)
    base_price_cents: int  # Original exit price
    current_aggressiveness: float  # Current aggressiveness level (0.0-1.0)
    retries_left: int  # Remaining retry attempts
    last_action_ts: float  # Timestamp of last action (Unix time)
    status: str  # "pending", "resting", "rejected", "filled", "cancelled", "gave_up"
    
    # Intent reconstruction for retries
    intent_id: str = ""  # Original intent ID
    ticker: str = ""  # Market ticker
    count: int = 0  # Order size
    exit_reason: str = ""  # Exit reason (tp, sl, 99c, etc.)
    exit_policy_id: str = ""  # Exit policy ID
    
    # Retry tracking
    total_retries: int = 0  # Total retry attempts made
    last_retry_ts: Optional[float] = None  # Timestamp of last retry


class RestingOrderMonitor:
    """Monitors and dynamically re-checks resting orders against current signals.
    
    Primary key is (venue, kalshi_order_id) - all state comes from Kalshi portfolio view.
    """
    
    def __init__(self, recheck_interval_seconds: int = 60, poll_interval_seconds: int = 30):
        """Initialize the resting order monitor.
        
        Args:
            recheck_interval_seconds: How often to re-check resting orders against signals (default 60s)
            poll_interval_seconds: How often to poll Kalshi portfolio for status (default 30s)
        """
        self.recheck_interval = recheck_interval_seconds
        self.poll_interval = poll_interval_seconds
        # Primary key is (venue, kalshi_order_id)
        self._resting_orders: Dict[str, RestingOrderRecord] = {}  # kalshi_order_id -> record
        # Secondary index for intent_id lookup
        self._intent_to_order_id: Dict[str, str] = {}  # intent_id -> kalshi_order_id
        # Exit order state tracking (kalshi_order_id -> ExitOrderState)
        self._exit_states: Dict[str, ExitOrderState] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._cancel_count = 0
        self._keep_count = 0
        self._poll_count = 0
        self._last_poll_time: Optional[datetime] = None  # Health monitoring

        # Market order fallback engine
        self._fallback_engine: Optional[MarketOrderFallbackEngine] = None
        self._fallback_enabled: bool = False

        # Exit policy configuration (loaded from profile YAML)
        self._load_exit_policy_config()
        
    def _load_exit_policy_config(self) -> None:
        """Load exit policy configuration from profile YAML.
        
        CRITICAL FIX (2026-07-30): Load from kalshi_crypto_15m_v2.yaml instead of hardcoding.
        Falls back to hardcoded defaults if YAML loading fails.
        """
        try:
            import yaml
            import os
            from merid.risk.profiles.crypto_15m_profile import get_active_profile

            adapter = get_active_profile()
            if adapter is not None:
                config_path = adapter.profile_path
            else:
                profile_name = os.getenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
                config_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / f"{profile_name}.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                
                exit_policy = config.get("exit_policy", {})
                
                self._exit_policy_enabled = exit_policy.get("enabled", True)
                self._exit_max_retries = exit_policy.get("max_retries", 5)
                self._exit_retry_interval_ms = exit_policy.get("retry_interval_ms", 500)
                self._exit_retry_backoff_multiplier = exit_policy.get("retry_backoff_multiplier", 1.5)
                self._exit_aggressiveness_step = exit_policy.get("aggressiveness_step", 0.05)
                self._exit_max_aggressiveness = exit_policy.get("max_aggressiveness", 1.0)
                
                # CRITICAL FIX (2026-07-30): Increase timeout from 15s to 60s for 15m markets
                # Research shows 15s is too aggressive for 15-minute markets (1.67% of cycle)
                # 60s allows market to move to favorable price before forcing aggressive retry
                self._exit_time_to_give_up_ms = exit_policy.get("time_to_give_up_ms", 60000)
                
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Loaded exit policy config from {config_path.name}: "
                    f"enabled={self._exit_policy_enabled}, max_retries={self._exit_max_retries}, "
                    f"time_to_give_up_ms={self._exit_time_to_give_up_ms}ms"
                )
            else:
                logger.warning(f"[RESTING_ORDER_MONITOR] Config file not found: {config_path}, using defaults")
                self._set_default_exit_policy_config()
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Failed to load exit policy config: {e}, using defaults")
            self._set_default_exit_policy_config()
    
    def _set_default_exit_policy_config(self) -> None:
        """Set default exit policy configuration (fallback if YAML loading fails)."""
        self._exit_policy_enabled = True
        self._exit_max_retries = 5
        self._exit_retry_interval_ms = 500
        self._exit_retry_backoff_multiplier = 1.5
        self._exit_aggressiveness_step = 0.05
        self._exit_max_aggressiveness = 1.0
        # CRITICAL FIX (2026-07-30): Default to 60s instead of 15s for 15m markets
        self._exit_time_to_give_up_ms = 60000
        
    def register_order(self, record: RestingOrderRecord) -> None:
        """Register a resting order for monitoring.
        
        Only registers if:
        - type == "limit"
        - time_in_force == "good_till_canceled"
        
        Args:
            record: RestingOrderRecord with kalshi_order_id and risk contract
        """
        # IOC/FOK filtering: only GTC orders can rest
        tif_lower = (record.time_in_force or "").lower()
        if tif_lower in ("ioc", "immediate_or_cancel", "fok", "fill_or_kill"):
            logger.debug(
                f"[RESTING_ORDER_MONITOR] Skipping IOC/FOK order: kalshi_order_id={record.kalshi_order_id} "
                f"time_in_force={record.time_in_force} - these orders never rest"
            )
            return
        
        # CRITICAL FIX: Convert side/action to Kalshi format for consistency
        # RestingOrderRecord may receive lowercase sides (yes/no) from loop_15m
        # but monitor expects Kalshi format (BUY_YES, BUY_NO, etc.) for duplicate detection
        if record.side and record.action:
            try:
                from merid.event_venues.kalshi.binary_price_space import to_kalshi_side
                record.side = to_kalshi_side(record.side, record.action)
            except ValueError:
                # If conversion fails, keep original side
                pass
        
        # Assert we have the required server-side ID
        if not record.kalshi_order_id:
            logger.warning(
                f"[RESTING_ORDER_MONITOR] Cannot register order without kalshi_order_id: intent_id={record.intent_id}"
            )
            return
        
        # Detect 15m markets and set appropriate max hold time
        # 15m markets have ticker patterns like "KXBTC-15M" or contain "15M"
        if "15M" in record.ticker.upper() or "-15M" in record.ticker.upper():
            record.max_hold_seconds = MAX_HOLD_SECONDS_15M
            logger.info(
                f"[RESTING_ORDER_MONITOR] Set max_hold_seconds={MAX_HOLD_SECONDS_15M}s for 15m market: ticker={record.ticker}"
            )
        
        # Store with kalshi_order_id as primary key
        # Set initial status to "open" at registration time
        if not record.status:
            record.status = "open"
        
        self._resting_orders[record.kalshi_order_id] = record
        if record.intent_id:
            self._intent_to_order_id[record.intent_id] = record.kalshi_order_id
        
        logger.info(
            f"[RESTING_ORDER_MONITOR] Registered order: kalshi_order_id={record.kalshi_order_id} "
            f"intent_id={record.intent_id} ticker={record.ticker} risk_tier={record.risk_tier} "
            f"original_size={record.original_size} remaining_size={record.remaining_size} status={record.status} "
            f"max_hold_seconds={record.max_hold_seconds}"
        )
    
    def unregister_order(self, kalshi_order_id: str) -> None:
        """Unregister an order by server-side order_id.
        
        Args:
            kalshi_order_id: Kalshi server-side order ID to unregister
        """
        if kalshi_order_id in self._resting_orders:
            record = self._resting_orders[kalshi_order_id]
            del self._resting_orders[kalshi_order_id]
            if record.intent_id and record.intent_id in self._intent_to_order_id:
                del self._intent_to_order_id[record.intent_id]
            logger.debug(f"[RESTING_ORDER_MONITOR] Unregistered order: kalshi_order_id={kalshi_order_id}")
    
    def find_open_order(
        self,
        ticker: str,
        side: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Optional[str]:
        """Find a live (non-terminal, unfilled) resting order matching the given keys.

        Used by the order router's anti-stacking guard to prevent submitting a new
        order while an equivalent one is still resting on the book.

        Args:
            ticker: Market ticker (case-insensitive match, required)
            side: Optional side filter (case-insensitive, e.g. "BUY_YES")
            action: Optional action filter (case-insensitive, e.g. "buy")

        Returns:
            kalshi_order_id of the first matching live order, or None
        """
        ticker_norm = (ticker or "").upper()
        side_norm = (side or "").upper()
        action_norm = (action or "").upper()

        for record in list(self._resting_orders.values()):
            if (record.ticker or "").upper() != ticker_norm:
                continue
            if side_norm and (record.side or "").upper() != side_norm:
                continue
            if action_norm and (record.action or "").upper() != action_norm:
                continue
            if record.status in TERMINAL_STATUSES:
                continue
            if record.remaining_size <= 0:
                continue
            return record.kalshi_order_id

        return None

    def get_orders_by_ticker(self, ticker: str) -> List[RestingOrderRecord]:
        """Get all resting orders for a given ticker.

        CRITICAL FIX (2026-07-23): Added for duplicate exit order detection.
        Used by exit order logic to check if a resting exit order already exists
        for a position before placing a new one (one-position-one-exit invariant).

        Args:
            ticker: Market ticker (case-insensitive match, required)

        Returns:
            List of RestingOrderRecord objects matching the ticker
        """
        ticker_norm = (ticker or "").upper()
        matching_orders = []

        for record in list(self._resting_orders.values()):
            if (record.ticker or "").upper() == ticker_norm:
                matching_orders.append(record)

        return matching_orders

    def unregister_by_intent_id(self, intent_id: str) -> None:
        """Unregister an order by intent_id (fallback for legacy code).
        
        Args:
            intent_id: Intent ID to unregister
        """
        if intent_id in self._intent_to_order_id:
            kalshi_order_id = self._intent_to_order_id[intent_id]
            self.unregister_order(kalshi_order_id)
    
    def enable_fallback(self, config: Optional[FallbackConfig] = None) -> None:
        """Enable market order fallback.
        
        Args:
            config: Optional FallbackConfig with custom settings
        """
        if not _FALLBACK_AVAILABLE:
            logger.warning("[RESTING_ORDER_MONITOR] Cannot enable fallback - module not available")
            return
        
        if config:
            self._fallback_engine = MarketOrderFallbackEngine(config)
        else:
            self._fallback_engine = get_market_order_fallback_engine()
        
        self._fallback_enabled = True
        logger.info("[RESTING_ORDER_MONITOR] Market order fallback enabled")
    
    def disable_fallback(self) -> None:
        """Disable market order fallback."""
        self._fallback_enabled = False
        logger.info("[RESTING_ORDER_MONITOR] Market order fallback disabled")
    
    async def _execute_fallback_async(self, decision: Any) -> None:
        """Execute market order fallback asynchronously.
        
        Args:
            decision: FallbackDecision with should_fallback=True
        """
        try:
            if self._fallback_engine:
                result = await self._fallback_engine.execute_fallback(decision)
                logger.info(f"[RESTING_ORDER_MONITOR] Fallback result: {result}")
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Fallback execution failed: {e}")
    
    async def _recheck_order(self, record: RestingOrderRecord) -> RecheckResult:
        """Re-check a single resting order against current signals.
        
        Args:
            record: RestingOrderRecord to re-check
        
        Returns:
            RecheckResult with action and reason
        """
        try:
            # CRITICAL FIX (2026-07-16): Exempt exit orders from cancel rules
            # Exit orders (TP, SL, trailing, etc.) should not be cancelled by regime flips,
            # entry window changes, or other entry-specific conditions. They must be allowed
            # to execute to ensure position exit enforcement.
            from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
            
            # Check if this is an exit order using client_order_id or intent_id as source
            # CRITICAL FIX (2026-08-10): Use canonical signed-YES exposure against
            # the current position, not the raw action string. A SELL that reduces
            # an existing same-side position is an exit; a SELL that opens new
            # exposure is an entry and may be cancelled by entry-specific rules.
            is_exit = False
            if record.client_order_id and is_exit_order_from_source(record.client_order_id):
                is_exit = True
            elif record.intent_id and is_exit_order_from_source(record.intent_id):
                is_exit = True
            elif record.exit_policy_id and is_exit_order_from_source(record.exit_policy_id):
                is_exit = True
            else:
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    from merid.event_venues.kalshi.exit_order_utils import (
                        is_exit_order_from_signed_yes,
                    )
                    from merid.event_venues.kalshi.binary_price_space import yes_delta
                    position = get_position_cache().get_position(record.ticker)
                    if position is not None:
                        pre_yes_cc = position._yes_exposure()
                        size_cc = int(getattr(record, "remaining_size", 0) or 0) * 100
                        order_yes_delta_cc = int(yes_delta(
                            (record.action or "").lower(),
                            (record.side or "").lower(),
                            size_cc,
                        ))
                        is_exit = is_exit_order_from_signed_yes(pre_yes_cc, order_yes_delta_cc)
                except Exception:
                    is_exit = False
            
            if is_exit:
                logger.info(
                    "[RESTING-ORDER-MONITOR] Exit order exempted from cancel rules: kalshi_order_id=%s ticker=%s source=%s - allowing execution",
                    record.kalshi_order_id, record.ticker, record.client_order_id or record.intent_id
                )
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="keep",
                    reason="exit_order_exempt",
                    current_regime=None,
                    current_vol_tier=None,
                    model_quality_good=None,
                )
            
            # CRITICAL FIX (2026-07-17): Resting order sweeper - cancel old orders
            # Check if order has exceeded max hold time (age-based cancellation)
            now = datetime.utcnow()
            if record.created_at:
                age_seconds = (now - record.created_at).total_seconds()
                if age_seconds > record.max_hold_seconds:
                    logger.warning(
                        "[RESTING-ORDER-SWEEPER] Order exceeded max hold time: kalshi_order_id=%s ticker=%s "
                        "age=%.1fs max_hold=%ds - cancelling stale order",
                        record.kalshi_order_id, record.ticker, age_seconds, record.max_hold_seconds
                    )
                    return RecheckResult(
                        intent_id=record.intent_id,
                        ticker=record.ticker,
                        action="cancel",
                        reason=f"max_hold_exceeded:{age_seconds:.1f}s",
                        current_regime=None,
                        current_vol_tier=None,
                        model_quality_good=None,
                    )
            
            from merid.prediction.dynamic_entry_window import resolve_entry_window
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            
            # Get current regime
            regime = "normal"  # Default fallback
            try:
                from merid.signals.unified_regime_classifier import get_unified_regime_classifier
                classifier = get_unified_regime_classifier()
                state = classifier.get_current_state()
                if state:
                    regime = state.regime.value
            except Exception as e:
                logger.debug(f"[RESTING_ORDER_MONITOR] Could not get regime: {e}")
            
            # Get model quality
            model_quality_good = False
            try:
                from merid.metrics.calibration import get_calibration_store
                from merid.metrics.hit_ratio import get_hit_ratio_tracker
                
                cal_store = get_calibration_store()
                hit_tracker = get_hit_ratio_tracker()
                
                brier = cal_store.get_brier("edge_model_v1", "crypto")
                hit_stats = hit_tracker.stats
                hit_ratio = hit_stats.get("hit_ratio", 0.5)
                
                model_quality_good = (brier < 0.20 and hit_ratio > 0.55)
            except Exception as e:
                logger.debug(f"[RESTING_ORDER_MONITOR] Could not get model quality: {e}")
            
            # Re-resolve entry window
            now = datetime.utcnow()
            minutes_to_expiry = None
            if record.original_minutes_to_expiry:
                # Update based on elapsed time
                elapsed_minutes = (now - record.created_at).total_seconds() / 60.0
                minutes_to_expiry = max(0, record.original_minutes_to_expiry - elapsed_minutes)
            
            window_res = resolve_entry_window(
                asset=record.asset,
                minutes_to_expiry=minutes_to_expiry,
                edge_pct=record.original_edge_pct,
                ticker=record.ticker
            )
            
            # Check if order should be cancelled
            # 1. Defensive regime or halt
            if regime in ("defensive", "halt"):
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"regime_{regime}",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 2. Entry window no longer allowed
            if not window_res.allowed:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"window_not_allowed:{window_res.reason.value}",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 3. Model quality degraded and order was Tier A
            if record.risk_tier == "A" and not model_quality_good:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason="model_quality_degraded",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 4. Pre-expiry cancel rule: cancel resting orders near settlement
            if minutes_to_expiry is not None and minutes_to_expiry < PRE_EXPIRY_CANCEL_THRESHOLD_MIN:
                logger.warning(
                    "[RESTING-CANCEL-BEFORE-EXPIRY] ticker=%s kalshi_order_id=%s tte=%.1fmin < %dmin - cancelling resting order",
                    record.ticker, record.kalshi_order_id, minutes_to_expiry, PRE_EXPIRY_CANCEL_THRESHOLD_MIN
                )
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"pre_expiry_cancel:{minutes_to_expiry:.1f}min",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 4. Max hold time exceeded
            elapsed_seconds = (now - record.created_at).total_seconds()
            if elapsed_seconds > record.max_hold_seconds:
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason="max_hold_time_exceeded",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
            
            # 5. Market order fallback check (NEW)
            if self._fallback_enabled and self._fallback_engine and _FALLBACK_AVAILABLE:
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    market_state_store = get_kalshi_market_state_store()
                    market_state = market_state_store.get(record.ticker) if market_state_store else None
                    
                    fallback_decision = self._fallback_engine.evaluate_fallback(record, market_state)
                    
                    if fallback_decision.should_fallback:
                        logger.info(
                            "[RESTING_ORDER_MONITOR] Market order fallback triggered: kalshi_order_id=%s "
                            "ticker=%s reason=%s",
                            record.kalshi_order_id, record.ticker, fallback_decision.reason
                        )
                        # Execute fallback asynchronously (don't block recheck loop)
                        asyncio.create_task(self._execute_fallback_async(fallback_decision))
                        
                        # Unregister order (will be replaced by market order)
                        return RecheckResult(
                            intent_id=record.intent_id,
                            ticker=record.ticker,
                            action="cancel",
                            reason=f"market_order_fallback:{fallback_decision.reason}",
                            current_regime=regime,
                            current_vol_tier=window_res.volatility_tier,
                            model_quality_good=model_quality_good,
                        )
                except Exception as e:
                    logger.error(f"[RESTING_ORDER_MONITOR] Fallback evaluation failed: {e}")
            
            # Keep the order
            return RecheckResult(
                intent_id=record.intent_id,
                ticker=record.ticker,
                action="keep",
                reason="still_valid",
                current_regime=regime,
                current_vol_tier=window_res.volatility_tier,
                model_quality_good=model_quality_good,
            )
            
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Re-check failed for {record.intent_id}: {e}")
            # On error, keep order to avoid spurious cancellations
            return RecheckResult(
                intent_id=record.intent_id,
                ticker=record.ticker,
                action="keep",
                reason="recheck_error",
            )
    
    async def _sync_order_status(self, record: RestingOrderRecord) -> bool:
        """Sync order status from Kalshi portfolio endpoint.
        
        This is the source of truth for order state - no state is inferred from intents.
        
        Args:
            record: RestingOrderRecord to sync
        
        Returns:
            True if order should be removed (terminal status), False otherwise
        """
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            
            client = get_kalshi_client()
            result = await client.get_order_result(record.kalshi_order_id, record.ticker)
            
            # Handle "no data" case - order may be gone or never existed
            if not result.data:
                record.missing_data_count += 1
                logger.warning(
                    f"[RESTING_ORDER_MONITOR] No order data for {record.kalshi_order_id} "
                    f"(missing_count={record.missing_data_count}) - treating as non-terminal for now"
                )
                # After 3 consecutive "no data" responses, treat as terminal
                if record.missing_data_count >= 3:
                    logger.error(
                        f"[RESTING_ORDER_MONITOR] Order {record.kalshi_order_id} has {record.missing_data_count} "
                        f"consecutive missing data responses - treating as unknown terminal, manual reconciliation needed"
                    )
                    return True
                return False
            
            # Reset missing data counter on successful data fetch
            record.missing_data_count = 0
            
            # CRITICAL FIX (2026-07-31): result.data is a PlacedOrder object, not a dict
            # Access attributes directly instead of using .get()
            order_data = result.data
            raw_status = order_data.status if order_data else ""
            remaining_size = int(order_data.remaining_size) if order_data and order_data.remaining_size else 0
            
            # Normalize status to internal vocabulary
            status = _normalize_status(raw_status)
            
            old_status = record.status
            record.status = status
            record.last_sync_at = datetime.utcnow()
            
            # Always keep remaining_size in sync (even for all-at-once fills)
            record_remaining_before = record.remaining_size
            record.remaining_size = remaining_size
            
            # Update filled_size (cumulative filled amount)
            record.filled_size = record.original_size - remaining_size
            
            # Partial fill detection
            if remaining_size > 0 and record_remaining_before > remaining_size:
                fill_amount = record_remaining_before - remaining_size
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Partial fill: kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} filled={fill_amount} remaining={remaining_size} "
                    f"total_filled={record.filled_size}/{record.original_size}"
                )
                # Emit resting_order_partially_filled event to venue event stream
                logger.info(
                    f"[EVENT] resting_order_partially_filled | kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} fill_amount={fill_amount} remaining={remaining_size} "
                    f"total_filled={record.filled_size}/{record.original_size}"
                )
            
            # Terminal handling - use terminal status as primary signal
            # remaining_size == 0 is a sanity check
            if status in TERMINAL_STATUSES or remaining_size == 0:
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Order terminal: kalshi_order_id={record.kalshi_order_id} "
                    f"status={status} remaining_size={remaining_size} - removing from monitor"
                )
                # Emit filled/canceled/expired/rejected event based on status
                if status == "filled":
                    logger.info(
                        f"[EVENT] resting_order_filled | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "canceled":
                    logger.info(
                        f"[EVENT] resting_order_canceled | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "expired":
                    logger.info(
                        f"[EVENT] resting_order_expired | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                elif status == "rejected":
                    logger.info(
                        f"[EVENT] resting_order_rejected | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} remaining_size={remaining_size}"
                    )
                return True
            
            # Check expiration discrepancy - check all resting statuses, not just "open"
            if record.order_expiration_ts:
                now = int(datetime.utcnow().timestamp())
                if now >= record.order_expiration_ts and status in RESTING_STATUSES:
                    logger.error(
                        f"[RESTING_ORDER_MONITOR] EXPIRATION DISCREPANCY: kalshi_order_id={record.kalshi_order_id} "
                        f"should be expired but status={status} - manual reconciliation needed"
                    )
                    # Trigger manual reconciliation alert
                    logger.warning(
                        f"[ALERT] manual_reconciliation_needed | kalshi_order_id={record.kalshi_order_id} "
                        f"ticker={record.ticker} status={status} expiration_ts={record.order_expiration_ts} "
                        f"now={now} - expiration discrepancy detected"
                    )
            
            self._poll_count += 1
            return False
            
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Failed to sync order status for {record.kalshi_order_id}: {e}")
            return False
    
    async def _poll_all_orders(self) -> None:
        """Poll all resting orders from Kalshi portfolio endpoint.
        
        Uses round-robin polling with backpressure to avoid rate limits.
        """
        if not self._resting_orders:
            logger.debug("[RESTING_ORDER_MONITOR] No orders to poll")
            return
        
        logger.info(f"[RESTING_ORDER_MONITOR] Polling {len(self._resting_orders)} orders from portfolio")
        
        orders_to_remove = []
        for kalshi_order_id, record in list(self._resting_orders.items()):
            should_remove = await self._sync_order_status(record)
            if should_remove:
                orders_to_remove.append(kalshi_order_id)
        
        # Remove terminal orders
        for kalshi_order_id in orders_to_remove:
            self.unregister_order(kalshi_order_id)
        
        logger.info(
            f"[RESTING_ORDER_MONITOR] Poll complete: {len(orders_to_remove)} removed, "
            f"{len(self._resting_orders)} still resting (total_polls={self._poll_count})"
        )
    
    async def _recheck_all_orders(self) -> List[RecheckResult]:
        """Re-check all registered resting orders against current signals.
        
        This is separate from portfolio polling - it checks if orders should be
        dynamically cancelled based on regime/volatility/model quality changes.
        
        Returns:
            List of RecheckResult for each order
        """
        results = []
        for record in list(self._resting_orders.values()):
            result = await self._recheck_order(record)
            results.append(result)
            
            if result.action == "cancel":
                self._cancel_count += 1
                logger.warning(
                    f"[RESTING_ORDER_MONITOR] Cancelling order: kalshi_order_id={record.kalshi_order_id} "
                    f"ticker={record.ticker} reason={result.reason}"
                )
                # Cancel the order on Kalshi
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client
                    client = get_kalshi_client()
                    await client.cancel_order(record.kalshi_order_id, record.ticker)
                except Exception as e:
                    logger.error(f"[RESTING_ORDER_MONITOR] Failed to cancel order {record.kalshi_order_id}: {e}")
                
                # Unregister cancelled order
                self.unregister_order(record.kalshi_order_id)
            else:
                self._keep_count += 1
        
        return results
    
    async def _run_loop(self) -> None:
        """Main monitoring loop for signal-based re-checks.
        
        This is separate from portfolio polling - it checks if orders should be
        dynamically cancelled based on regime/volatility/model quality changes.
        """
        while self._running:
            try:
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Re-checking {len(self._resting_orders)} orders against signals"
                )
                results = await self._recheck_all_orders()
                
                cancel_count = sum(1 for r in results if r.action == "cancel")
                keep_count = sum(1 for r in results if r.action == "keep")
                
                logger.info(
                    f"[RESTING_ORDER_MONITOR] Re-check complete: {cancel_count} cancelled, "
                    f"{keep_count} kept (total_cancelled={self._cancel_count}, total_kept={self._keep_count})"
                )
                
            except Exception as e:
                logger.error(f"[RESTING_ORDER_MONITOR] Re-check loop error: {e}")
            
            await asyncio.sleep(self.recheck_interval)
    
    async def _poll_loop(self) -> None:
        """Portfolio polling loop for status sync.
        
        This is the source of truth for order state - polls Kalshi's portfolio
        endpoints to detect fills, cancels, expirations, and partial fills.
        """
        while self._running:
            try:
                self._last_poll_time = datetime.utcnow()
                await self._poll_all_orders()
                self._poll_count += 1
            except Exception as e:
                logger.error(f"[RESTING_ORDER_MONITOR] Poll loop error: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    async def start(self) -> None:
        """Start the resting order monitor.

        Starts both the portfolio polling loop and the signal re-check loop.
        Before starting the loops, reconciles local risk exposure with the venue
        and cancels stale resting orders so old GTC orders cannot block new IOC
        entries.
        """
        if self._running:
            logger.warning("[RESTING_ORDER_MONITOR] Already running")
            return

        # STARTUP RECONCILIATION: cancel stale resting orders and align local
        # exposure tracking with the venue before any new signals are handled.
        try:
            from merid.event_venues.kalshi.kalshi_risk import reconcile_unified_risk_with_venue
            recon_result = await reconcile_unified_risk_with_venue()
            logger.info(
                "[RESTING_ORDER_MONITOR] Startup reconciliation complete: "
                "canceled=%s quarantined=%s confirmed_open_notional=$%.2f",
                recon_result.get("canceled_order_ids", []),
                recon_result.get("quarantined_order_ids", []),
                recon_result.get("confirmed_open_notional_usd", 0.0),
            )
        except Exception as e:
            logger.error("[RESTING_ORDER_MONITOR] Startup reconciliation failed (proceeding): %s", e)

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[RESTING_ORDER_MONITOR] Started (poll_interval={self.poll_interval}s, "
            f"recheck_interval={self.recheck_interval}s)"
        )
    
    async def stop(self) -> None:
        """Stop the resting order monitor."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel both tasks
        for task in [self._task, self._poll_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._task = None
        self._poll_task = None
        
        logger.info("[RESTING_ORDER_MONITOR] Stopped")
    
    def get_stats(self) -> Dict:
        """Get monitor statistics.
        
        Returns:
            Dict with current stats
        """
        return {
            "running": self._running,
            "resting_orders_count": len(self._resting_orders),
            "cancel_count": self._cancel_count,
            "keep_count": self._keep_count,
            "poll_count": self._poll_count,
            "recheck_interval_seconds": self.recheck_interval,
            "poll_interval_seconds": self.poll_interval,
            "last_poll_time": self._last_poll_time,
            "orders_with_missing_data": self._count_orders_with_missing_data(),
        }
    
    def _count_orders_with_missing_data(self) -> int:
        """Count orders with missing_data_count exceeding threshold."""
        MISSING_DATA_THRESHOLD = 3  # Alert after 3 consecutive failures
        return sum(
            1 for order in self._resting_orders.values()
            if order.missing_data_count >= MISSING_DATA_THRESHOLD
        )
    
    def check_health(self) -> Dict:
        """Check health of the resting order monitor.
        
        Returns:
            Dict with health status and any issues found
        """
        issues = []
        
        # Check if poll loop is running
        if self._running:
            if self._last_poll_time:
                time_since_last_poll = (datetime.utcnow() - self._last_poll_time).total_seconds()
                # Alert if no poll in 2x the poll interval
                if time_since_last_poll > self.poll_interval * 2:
                    issues.append(
                        f"Poll loop stale: last poll {time_since_last_poll:.0f}s ago "
                        f">(threshold: {self.poll_interval * 2:.0f}s)"
                    )
            else:
                issues.append("Poll loop running but no polls recorded yet")
        else:
            issues.append("Poll loop not running")
        
        # Check for orders with excessive missing data
        missing_data_orders = self._count_orders_with_missing_data()
        if missing_data_orders > 0:
            issues.append(
                f"{missing_data_orders} orders with missing_data_count >= 3 "
                f"(portfolio polling failures)"
            )
        
        # Check for orders with consecutive sync failures
        sync_failure_orders = sum(
            1 for order in self._resting_orders.values()
            if order.consecutive_sync_failures >= 3
        )
        if sync_failure_orders > 0:
            issues.append(
                f"{sync_failure_orders} orders with consecutive_sync_failures >= 3"
            )
        
        healthy = len(issues) == 0
        
        if not healthy:
            for issue in issues:
                logger.error(f"[RESTING_ORDER_MONITOR_HEALTH] {issue}")
        
        return {
            "healthy": healthy,
            "issues": issues,
            "running": self._running,
            "resting_orders_count": len(self._resting_orders),
            "last_poll_time": self._last_poll_time,
        }

    # ── Exit Order Retry Logic (2026-07-29) ───────────────────────────────────────

    def register_exit_state(self, state: ExitOrderState) -> None:
        """Register an exit order state for active management.
        
        Args:
            state: ExitOrderState to track
        """
        self._exit_states[state.order_id] = state
        logger.info(
            f"[EXIT-RETRY] Registered exit state: order_id={state.order_id} asset={state.asset} "
            f"side={state.side} base_price={state.base_price_cents}c retries_left={state.retries_left}"
        )

    def update_exit_state(self, order_id: str, status: str) -> None:
        """Update exit order state based on order status change.
        
        Args:
            order_id: Kalshi order ID
            status: New status (filled, cancelled, rejected, etc.)
        """
        if order_id not in self._exit_states:
            return

        state = self._exit_states[order_id]
        state.last_action_ts = time.time()
        state.status = status

        logger.info(
            f"[EXIT-RETRY] Updated exit state: order_id={order_id} status={status}"
        )

        # Trigger retry logic for rejected orders
        if status == "rejected":
            self._schedule_exit_retry(state, reason="rejected")
        # Trigger timeout for resting orders
        elif status == "resting":
            self._schedule_exit_timeout(state)
        # Clean up terminal states
        elif status in ("filled", "cancelled", "gave_up"):
            logger.info(
                f"[EXIT-RETRY] Cleaning up terminal exit state: order_id={order_id} status={status}"
            )

    def _schedule_exit_retry(self, state: ExitOrderState, reason: str) -> None:
        """Schedule a retry for a rejected or timed-out exit order.
        
        Args:
            state: ExitOrderState to retry
            reason: Reason for retry (rejected, timeout, etc.)
        """
        if not self._exit_policy_enabled or state.retries_left <= 0:
            state.status = "gave_up"
            logger.warning(
                f"[EXIT-RETRY-GAVE-UP] order_id={state.order_id} asset={state.asset} "
                f"reason={reason} total_retries={state.total_retries}"
            )
            return

        # Compute new aggressiveness
        new_agg = min(
            self._exit_max_aggressiveness,
            state.current_aggressiveness + self._exit_aggressiveness_step,
        )

        # Compute new price: for exit, "more aggressive" means:
        # - long exit (sell): lower price -> more likely to hit
        # - short exit (buy): higher price -> more likely to hit
        base = state.base_price_cents
        aggressiveness_delta = new_agg - state.current_aggressiveness

        # CRITICAL FIX (2026-07-30): Same logic for YES and NO contracts
        # More aggressive = more likely to fill:
        # - Sell orders (both YES and NO): lower price
        # - Buy orders (both YES and NO): higher price
        if state.action == "sell":
            # Sell orders: lower price = more aggressive (more likely to hit bids)
            new_price_cents = max(1, int(base * (1 - aggressiveness_delta)))
        else:
            # Buy orders: higher price = more aggressive (more likely to hit asks)
            new_price_cents = int(base * (1 + aggressiveness_delta))

        # Schedule retry after backoff
        delay_ms = self._exit_retry_interval_ms * (
            self._exit_retry_backoff_multiplier ** (self._exit_max_retries - state.retries_left)
        )
        state.retries_left -= 1
        state.current_aggressiveness = new_agg
        state.total_retries += 1
        state.last_retry_ts = time.time()

        logger.info(
            f"[EXIT-RETRY-SCHEDULED] order_id={state.order_id} asset={state.asset} reason={reason} "
            f"retries_left={state.retries_left} new_aggressiveness={new_agg:.2f} "
            f"new_price={new_price_cents}c delay_ms={delay_ms:.0f}"
        )

        # Schedule async retry
        asyncio.create_task(self._retry_exit_order(state, new_price_cents, delay_ms))

    async def _retry_exit_order(self, state: ExitOrderState, new_price_cents: int, delay_ms: int) -> None:
        """Execute a retry for an exit order with adjusted price.
        
        Args:
            state: ExitOrderState to retry
            new_price_cents: New price for retry
            delay_ms: Delay before retry (backoff)
        """
        await asyncio.sleep(delay_ms / 1000.0)

        # Check if state has been resolved (filled/cancelled) during backoff
        if state.status in ("filled", "cancelled", "gave_up"):
            logger.info(
                f"[EXIT-RETRY-SKIPPED] order_id={state.order_id} status={state.status} - already resolved"
            )
            return

        try:
            # Import order router for retry
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

            # Build new exit intent with updated price & aggressiveness
            new_intent = OrderIntent(
                ticker=state.ticker,
                side=state.side,
                action=state.action,
                price_cents=new_price_cents,
                count=state.count,
                order_type="limit",
                time_in_force="gtc",
                source="position_monitor_exit_retry",
                agent_id="merid.position_management.position_monitor",
                aggressiveness=state.current_aggressiveness,
                entry_or_exit="exit",
                exit_reason=state.exit_reason,
                exit_policy_id=state.exit_policy_id,
            )

            logger.info(
                f"[EXIT-RETRY-EXECUTING] order_id={state.order_id} new_price={new_price_cents}c "
                f"aggressiveness={state.current_aggressiveness:.2f}"
            )

            # Route the retry order
            result = await route_order_async(new_intent)

            # Exit retries are only successful when they actually execute.
            # A zero-fill IOC or resting order still leaves the original position open.
            if result and result.has_execution:
                # Update tracking with new order ID
                new_order_id = result.order_id
                del self._exit_states[state.order_id]
                state.order_id = new_order_id
                state.status = "pending"
                self._exit_states[new_order_id] = state

                logger.info(
                    f"[EXIT-RETRY-SUCCESS] old_order_id={state.order_id} new_order_id={new_order_id} "
                    f"status={result.status}"
                )
            else:
                logger.error(
                    f"[EXIT-RETRY-FAILED] order_id={state.order_id} reason={result.reason}"
                )
                # Schedule another retry if retries remain
                if state.retries_left > 0:
                    self._schedule_exit_retry(state, reason="retry_failed")

        except Exception as e:
            logger.error(
                f"[EXIT-RETRY-ERROR] order_id={state.order_id} error={e}",
                exc_info=True
            )
            # Schedule another retry if retries remain
            if state.retries_left > 0:
                self._schedule_exit_retry(state, reason="retry_error")

    def _schedule_exit_timeout(self, state: ExitOrderState) -> None:
        """Schedule timeout-based replacement for a resting exit order.
        
        If an exit order is resting but not filling within the configured time,
        cancel it and retry with more aggressive pricing.
        
        Args:
            state: ExitOrderState to monitor for timeout
        """
        if not self._exit_policy_enabled:
            return

        async def timeout_handler():
            await asyncio.sleep(self._exit_time_to_give_up_ms / 1000.0)

            # Check if state is still resting
            if state.status != "resting":
                logger.info(
                    f"[EXIT-TIMEOUT-SKIPPED] order_id={state.order_id} status={state.status} - not resting"
                )
                return

            resting_ms = (time.time() - state.last_action_ts) * 1000
            logger.warning(
                f"[EXIT-TIMEOUT] order_id={state.order_id} asset={state.asset} "
                f"resting_ms={resting_ms:.0f} - cancelling and retrying"
            )

            # Cancel the resting order
            try:
                from merid.event_venues.kalshi.order_router import cancel_order_async
                await cancel_order_async(state.order_id)
            except Exception as cancel_err:
                logger.error(
                    f"[EXIT-TIMEOUT-CANCEL-FAILED] order_id={state.order_id} error={cancel_err}"
                )

            # Schedule retry with more aggressive pricing
            self._schedule_exit_retry(state, reason="timeout")

        asyncio.create_task(timeout_handler())


# Global singleton instance
_monitor_instance: Optional[RestingOrderMonitor] = None


def get_resting_order_monitor() -> RestingOrderMonitor:
    """Get the global resting order monitor singleton.
    
    Returns:
        RestingOrderMonitor instance
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = RestingOrderMonitor()
    return _monitor_instance
