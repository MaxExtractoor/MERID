"""Canonical Kalshi Fills Ledger — Single source of truth for all executed trades.

This module provides:
- KalshiFill: Data model for a single fill with all Kalshi fields + metadata
- KalshiFillsLedger: Dual-ingestion (HTTP + WebSocket) persistent store
- FillsReconciler: Validates computed positions vs Kalshi-reported positions
- IntentTracker: Tracks order intents and matches them to fills

Design principles:
1. Kalshi is the ONLY source of truth — we never fabricate fills
2. Dual ingestion (HTTP poller + WS) ensures completeness
3. Idempotent upserts prevent duplicates
4. All fills have fill_id from Kalshi — no exceptions
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import numbers
import os
import sqlite3
import threading
import time

from merid.event_venues.kalshi.risk_parameters import (
    DEFAULT_KALSHI_PRICE_CENTS,
    DEEP_OTM_THRESHOLD_CENTS,  # DEPRECATED: Use profile when available
    DEEP_ITM_THRESHOLD_CENTS,  # DEPRECATED: Use profile when available
)

# Helper to get deep OTM/ITM thresholds from profile (Task 30: Single source of truth)
def _get_deep_otm_threshold() -> int:
    """Get deep OTM threshold from profile or fallback to deprecated constant."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        adapter = get_active_profile()
        if adapter is not None and adapter.profile is not None:
            return adapter.profile.venue_invariants_deep_otm_threshold_cents
    except Exception:
        pass
    return DEEP_OTM_THRESHOLD_CENTS  # Fallback

def _get_deep_itm_threshold() -> int:
    """Get deep ITM threshold from profile or fallback to deprecated constant."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        adapter = get_active_profile()
        if adapter is not None and adapter.profile is not None:
            return adapter.profile.venue_invariants_deep_itm_threshold_cents
    except Exception:
        pass
    return DEEP_ITM_THRESHOLD_CENTS  # Fallback

# Deployment safety metrics (if available)
try:
    from merid.event_venues.kalshi.kalshi_deployment_safety_metrics import (
        inc_deep_otm_fill,
        inc_deep_itm_fill,
    )
    SAFETY_METRICS_AVAILABLE = True
except ImportError:
    SAFETY_METRICS_AVAILABLE = False
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fills_ledger")


def _is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test market ticker.
    
    Test tickers are identified by patterns like:
    - Contains "TEST" or "KXTEST"
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"
    - Timeframe-based test tickers like "KXBTC-15M", "KXETH-15M" (if they are test-related)
    
    Args:
        ticker: The market ticker to check
        
    Returns:
        True if the ticker is a test market, False otherwise
    """
    if not ticker:
        return False
    
    ticker_upper = ticker.upper()
    
    # Explicit test markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True
    
    # Short codes (test development tickers)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True
    
    # Timeframe-based tickers for crypto (may be test-related)
    # These patterns are used for test markets in development
    if ticker_upper.startswith(("KXBTC-", "KXETH-", "KXSOL-", "KXXRP-", "KXDOGE-")):
        parts = ticker_upper.split("-")
        if len(parts) >= 2:
            last_part = parts[-1]
            # Check for timeframe suffixes that indicate test markets
            if last_part in ("15M", "1H", "H", "D", "W", "M", "A"):
                return True
    
    return False

if TYPE_CHECKING:
    from merid.hedging.pnl_tracker import HedgePnLTracker
    from merid.event_venues.kalshi.fills_persistence import HedgePersistenceManager

# PRODUCTION FIX (2026-05-01): DB configuration from environment
_FILLS_DB_BUSY_TIMEOUT_MS: int = int(os.getenv("MERID_FILLS_DB_BUSY_TIMEOUT_MS", "30000"))  # 30s default
_FILLS_DB_RETRY_ATTEMPTS: int = int(os.getenv("MERID_FILLS_DB_RETRY_ATTEMPTS", "3"))
_FILLS_DB_RETRY_DELAY_INITIAL: float = float(os.getenv("MERID_FILLS_DB_RETRY_DELAY_INITIAL", "0.05"))
_FILLS_DB_RETRY_DELAY_MAX: float = float(os.getenv("MERID_FILLS_DB_RETRY_DELAY_MAX", "0.5"))
_FILLS_WRITER_QUEUE_TIMEOUT: float = float(os.getenv("MERID_FILLS_WRITER_QUEUE_TIMEOUT", "0.5"))
_FILLS_WRITER_ERROR_SLEEP: float = float(os.getenv("MERID_FILLS_WRITER_ERROR_SLEEP", "0.05"))
_FILLS_SHUTDOWN_TIMEOUT: float = float(os.getenv("MERID_FILLS_SHUTDOWN_TIMEOUT", "5.0"))

# Test fixture fill ID prefixes — never from real Kalshi API
_TEST_FILL_PREFIXES = (
    "fill_integrity_", "fill_a_", "fill_b_", "fill_ghost_",
    "fill_immutable_", "fill_legit_", "fill_test_", "test_fill_",
    "fill_dup_", "fill_stale_", "ws-fill-", "fill-",
)

# Exact match test fill IDs (single IDs like f1, f2, etc.)
_TEST_FILL_EXACT = {"f1", "f2", "f3", "f4", "f5", "test", "mock", "sample"}

def _is_test_fixture_fill(fill_id: str) -> bool:
    """Return True if fill_id looks like a test fixture, not a real Kalshi fill."""
    if not fill_id:
        return True
    if fill_id in _TEST_FILL_EXACT:
        return True
    return any(fill_id.startswith(p) for p in _TEST_FILL_PREFIXES)


class ReconciliationStatus(Enum):
    """Status of fills vs positions reconciliation."""
    OK = "ok"
    DEGRADED = "degraded"  # Minor discrepancies (< 5%)
    BROKEN = "broken"      # Significant divergence
    UNKNOWN = "unknown"    # Haven't run yet


# ═══════════════════════════════════════════════════════════════════════════════
# FEE VALIDATION — "No Surprises" Integration
# Compare pre-trade fee estimates with actual Kalshi fee_cost
# ═══════════════════════════════════════════════════════════════════════════════

# PRODUCTION FIX (2026-05-01): Fee mismatch threshold from environment
FEE_MISMATCH_THRESHOLD_PCT: float = float(os.getenv("MERID_FEE_MISMATCH_THRESHOLD_PCT", "5.0"))  # 5% default


def validate_fee_vs_estimate(
    actual_fee_cents: Decimal,
    estimated_fee_cents: Optional[Decimal],
    fill_id: str,
    ticker: str,
    contracts: int,
    price_cents: float,
) -> Tuple[bool, Optional[str]]:
    """Validate actual fee against pre-trade estimate.
    
    Detects:
    - Kalshi fee schedule changes (unexpected tier changes)
    - Incorrect fee estimation in sizing logic
    - Data corruption or API changes
    
    Args:
        actual_fee_cents: Fee from Kalshi fill (fee_cost field)
        estimated_fee_cents: Our pre-trade estimate (from intent, if available)
        fill_id: For logging context
        ticker: Market ticker for logging
        contracts: Number of contracts (for context)
        price_cents: Fill price in cents (for context)
        
    Returns:
        (is_valid, alert_message_if_mismatch)
    """
    if estimated_fee_cents is None or estimated_fee_cents <= 0:
        # No estimate to compare against - skip validation
        return True, None
    
    if actual_fee_cents <= 0:
        # Invalid actual fee - this is a problem
        return False, f"[FEE_INVALID] fill={fill_id} ticker={ticker} actual_fee={actual_fee_cents}"
    
    # Calculate percentage deviation
    estimated = float(estimated_fee_cents)
    actual = float(actual_fee_cents)
    
    if estimated == 0:
        return True, None
    
    deviation_pct = abs(actual - estimated) / estimated * 100
    
    if deviation_pct > FEE_MISMATCH_THRESHOLD_PCT:
        alert = (
            f"[FEE_MISMATCH] fill={fill_id} ticker={ticker} "
            f"contracts={contracts} price={price_cents}c "
            f"estimated_fee={estimated:.2f}c actual_fee={actual:.2f}c "
            f"deviation={deviation_pct:.1f}% threshold={FEE_MISMATCH_THRESHOLD_PCT}%"
        )
        return False, alert
    
    return True, None


@dataclass
class KalshiFill:
    """Canonical representation of a Kalshi fill/trade.
    
    All fields from Kalshi API preserved, plus MERID metadata.
    Primary key: fill_id (from Kalshi — never null for real fills)
    """
    # Kalshi core fields (from /portfolio/fills or WS)
    fill_id: str  # Kalshi's unique fill ID — THE primary key
    trade_id: Optional[str] = None  # May be same as fill_id or different
    order_id: Optional[str] = None  # Parent order ID
    market_ticker: str = ""  # e.g., "KXBTC-25DEC-ABOVE-100000"
    side: str = ""  # "yes" or "no"
    action: str = ""  # "buy" or "sell"
    count_fp: int = 0  # Number of contracts (fixed-point integer)
    yes_price_dollars: Optional[Decimal] = None  # Price if side=yes
    no_price_dollars: Optional[Decimal] = None  # Price if side=no
    fee_cost: Decimal = Decimal("0")  # Fee paid
    proceeds_dollars: Optional[Decimal] = None  # Net proceeds (price * count - fees)
    client_order_id: Optional[str] = None  # Our idempotency key
    subaccount_number: Optional[int] = None
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Idempotency and schema metadata (paper fills)
    idempotency_key: Optional[str] = None  # For replay-safety and dedupe
    canonical_hash_version: Optional[str] = None  # Schema version for hash evolution
    hash_preimage: Optional[str] = None  # Forensic debug: hash inputs
    
    # Raw preservation for debugging
    raw_payload: Optional[Dict[str, Any]] = None  # Original JSON from Kalshi
    
    # MERID metadata
    ingestion_source: str = ""  # "http_poller", "websocket", "backfill"
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: Optional[str] = None  # Which MERID agent generated the intent
    intent_id: Optional[str] = None  # Link to our intent record
    decision_trace_id: Optional[str] = None  # End-to-end audit: swarm → sizer → order
    # Phase 5.4: Raw logit for probability calibration
    raw_logit: Optional[float] = None  # Raw model logit for Platt scaling calibration
    
    # P1-9: Hedge Order Lifecycle Tracking
    fill_source: str = ""  # "alpha", "hedge", "manual" — distinguishes hedge fills
    hedge_reason: Optional[str] = None  # e.g., "cross_asset_SOL_to_BTC", "same_asset_same_horizon"
    hedge_pnl_cents: int = 0  # Separate PnL tracking for hedge positions
    related_alpha_fill_id: Optional[str] = None  # Links hedge to originating alpha position
    
    # Reconciliation tracking
    reconciled: bool = False  # Has been matched to position ledger
    reconciliation_ts: Optional[datetime] = None
    
    # Slippage tracking (per-coin statistics)
    slippage_cents: Optional[int] = None  # Slippage in cents (actual - expected)
    expected_price_cents: Optional[int] = None  # Expected price at order time
    asset: Optional[str] = None  # Derived from ticker (BTC, ETH, SOL, XRP, DOGE)
    
    # Strict mode tracking (production safety)
    derived_id: bool = False  # True if fill_id was synthesized (not from Kalshi)
    confirmed_by_rest: bool = False  # True if this fill was later confirmed by HTTP REST API
    
    # LIVE vs PAPER tracking (CRITICAL for bankroll reconciliation)
    is_live: bool = False  # True if this was a LIVE trade with real money
    # Note: is_live is determined at ingestion time based on process trade mode
    # In strict mode, live trades MUST have derived_id=False (real Kalshi fill ID)
    
    def resolved_asset(self) -> Optional[str]:
        """Crypto asset code (BTC, ETH, …) from market ticker via canonical prefix map."""
        if not self.market_ticker:
            return None
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            return kalshi_ticker_to_asset(self.market_ticker)
        except Exception:
            return None
    
    def is_incomplete(self) -> bool:
        """True when size or price is missing/zero — UI should show placeholder, not fake zeros."""
        if self.count_fp <= 0:
            return True
        if self.price_cents <= 0:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for API responses."""
        d = asdict(self)
        # Convert Decimal to float for JSON serialization
        for key in ["yes_price_dollars", "no_price_dollars", "fee_cost"]:
            if d.get(key) is not None:
                d[key] = float(d[key])
        # Convert datetime to ISO string
        for key in ["created_time", "ingested_at", "reconciliation_ts"]:
            if d.get(key) is not None:
                d[key] = d[key].isoformat() if isinstance(d[key], datetime) else d[key]
        # is_live is already bool, no conversion needed
        return d
    
    @property
    def price_cents(self) -> int:
        """Get price in cents (0-100) for unified handling."""
        # Defensive: Handle cases where API returns dict instead of Decimal
        def safe_to_cents(price_val) -> Optional[int]:
            if price_val is None:
                return None
            if isinstance(price_val, int):
                return price_val
            if isinstance(price_val, float):
                return int(price_val * 100)
            if isinstance(price_val, Decimal):
                return int(price_val * 100)
            # If it's a dict or other unexpected type, log and return None
            logger.warning(
                "[FILL-LEDGER] Unexpected price type for price_cents: type=%s value=%s",
                type(price_val).__name__, str(price_val)[:100]
            )
            return None
        
        if self.side == "yes" and self.yes_price_dollars is not None:
            cents = safe_to_cents(self.yes_price_dollars)
            if cents is not None:
                return cents
        if self.side == "no" and self.no_price_dollars is not None:
            cents = safe_to_cents(self.no_price_dollars)
            if cents is not None:
                return cents
        # Legacy / WS: side missing or mis-set — use whichever leg has a price
        if self.yes_price_dollars is not None:
            cents = safe_to_cents(self.yes_price_dollars)
            if cents is not None:
                return cents
        if self.no_price_dollars is not None:
            cents = safe_to_cents(self.no_price_dollars)
            if cents is not None:
                return cents
        return 0
    
    @property
    def notional_usd(self) -> Decimal:
        """Calculate notional value (count * price)."""
        price = self.yes_price_dollars if self.side == "yes" else self.no_price_dollars
        if price is None:
            return Decimal("0")
        return Decimal(str(self.count_fp)) * price


@dataclass
class OrderIntent:
    """Record of an order intent before it becomes a fill.
    
    NOTE: This is NOT a duplicate of order_router.OrderIntent.
    - order_router.OrderIntent: Used for routing orders through risk checks and execution
    - fills_ledger.OrderIntent: Used for tracking fill history and reconciliation
    
    These serve different purposes and have different fields. Do not consolidate.
    """
    intent_id: str  # Our internal ID (client_order_id)
    ticker: str  # Renamed from market_ticker to match order_router.OrderIntent
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int  # Total intended count
    price_cents: int
    agent_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, submitted, filled, cancelled, rejected
    order_id: Optional[str] = None  # Kalshi order ID once submitted
    fill_ids: List[str] = field(default_factory=list)  # Linked fills
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # BUG-6 FIX: Partial fill tracking
    # Track filled quantity to handle partial fills correctly
    filled_count: int = 0  # Total contracts filled so far
    
    # Sizing context for TRADE-TRACE observability
    # Links fill back to original edge/sizing decision
    edgepct: float = 0.0
    netedgecents: float = 0.0
    band: str = ""
    regime: str = ""
    size_contracts: int = 0
    notional_usd: float = 0.0
    
    # Phase 5.4: Raw logit for probability calibration
    raw_logit: Optional[float] = None  # Raw model logit for Platt scaling calibration
    
    def add_fill(self, fill_id: str, fill_count: int) -> None:
        """Add a fill to this intent and update status.
        
        This handles partial fills by tracking the cumulative filled quantity.
        Status transitions from 'submitted' -> 'partially_filled' -> 'filled'.
        
        Args:
            fill_id: The fill ID to add
            fill_count: Number of contracts in this fill
        """
        if fill_id not in self.fill_ids:
            self.fill_ids.append(fill_id)
            self.filled_count += fill_count
            self.last_update = datetime.now(timezone.utc)
            
            # Update status based on fill completeness
            if self.filled_count >= self.count:
                self.status = "filled"
            elif self.filled_count > 0:
                self.status = "partially_filled"
            else:
                self.status = "pending"
    
    @property
    def remaining_count(self) -> int:
        """Number of contracts still to be filled."""
        return max(0, self.count - self.filled_count)
    
    @property
    def fill_progress_pct(self) -> float:
        """Percentage of the order that has been filled (0-100)."""
        if self.count == 0:
            return 0.0
        return min(100.0, (self.filled_count / self.count) * 100)


class KalshiFillsLedger:
    """Canonical ledger for all Kalshi fills — dual ingestion, persistent storage.
    
    Usage:
        ledger = get_fills_ledger()
        
        # From HTTP poller
        await ledger.ingest_http_fills(fills_list)  # returns (count, new_fill_ids)
        
        # From WebSocket
        await ledger.ingest_ws_fill(fill_dict)
        
        # Query
        fills = ledger.get_fills(since=datetime.now(timezone.utc) - timedelta(hours=24))
        
        # Reconciliation
        status = await ledger.reconcile_with_kalshi_positions()
    """
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._initialized = True
        
        # In-memory cache: fill_id -> KalshiFill
        self._fills: Dict[str, KalshiFill] = {}
        
        # Order intents: intent_id -> OrderIntent
        self._intents: Dict[str, OrderIntent] = {}
        
        # Index by order_id for quick lookup
        self._fills_by_order: Dict[str, List[str]] = {}  # order_id -> [fill_id, ...]
        
        # Index by market for position reconstruction
        self._fills_by_market: Dict[str, List[str]] = {}  # ticker -> [fill_id, ...]
        
        # Reconciliation state
        self._last_reconciliation: Optional[datetime] = None
        self._reconciliation_status = ReconciliationStatus.UNKNOWN
        self._reconciliation_issues: List[Dict[str, Any]] = []
        
        # Stats
        self._http_ingested = 0
        self._ws_ingested = 0
        self._duplicates_dropped = 0
        
        self._db_path = "data/kalshi_fills.db"
        
        # Async queue for single-writer pattern (prevents DB lock contention)
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._persist_queue: Optional[asyncio.Queue[Optional[KalshiFill]]] = None
        self._writer_task: Optional[asyncio.Task] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        
        # Lock for thread safety (protects all dict mutations)
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._mutex: Optional[asyncio.Lock] = None
        
        # Initialize DB with WAL mode on first use
        self._db_initialized = False
        
        # Load persisted fills on startup
        self._loaded_count = 0
        
        # DEFENSIVE-FIX-001: Circuit breaker and error tracking
        self._schema_error_count: int = 0
        self._schema_error_window_start: Optional[datetime] = None
        self._circuit_open: bool = False
        self._circuit_reason: Optional[str] = None
        self._circuit_opened_at: Optional[datetime] = None
        self._fills_dropped_count: int = 0
        
        # DEFENSIVE-FIX-002: Rate-limited logging state
        self._last_schema_error_log: Optional[datetime] = None
        self._schema_error_log_count: int = 0
        
        # DEFENSIVE-FIX-003: Dead Letter Queue (DLQ) for failed fills
        self._dlq_db_path = "data/kalshi_fills_dlq.db"
        self._dlq_buffer: List[Dict[str, Any]] = []
        self._dlq_buffer_max = 50  # Flush buffer at this size
        
        # Task 4: PnL tracker integration for hedge fill callbacks
        self._pnl_tracker: Optional["HedgePnLTracker"] = None
        
        # Task 7: Persistence manager for auto-save triggers
        self._persistence_manager: Optional["HedgePersistenceManager"] = None
        self._auto_save_interval_minutes = int(os.getenv("MERID_HEDGE_AUTO_SAVE_MINUTES", "5"))
        self._last_auto_save: Optional[datetime] = None
        
        # EOD snapshot storage for daily unrealized PnL change calculation
        # Key: account_id -> EODSnapshot
        self._eod_snapshots: Dict[str, "EODSnapshot"] = {}
        self._last_eod_snapshot_date: Optional[str] = None  # Track last EOD snapshot date
        
        # Session-based PnL tracking
        self._last_session_start_date: Optional[str] = None
        self._session_realized_pnl: Decimal = Decimal("0")
        self._session_unrealized_pnl: Decimal = Decimal("0")
        self._cumulative_realized_pnl: Decimal = Decimal("0")
        self._open_positions: Dict[str, Dict[str, Any]] = {}  # instrument_key -> position state
        self._processed_fill_ids: Set[str] = set()
        
        # Load session metadata on startup
        self._load_session_metadata()
        
        logger.info("KalshiFillsLedger initialized")

    def _ensure_persist_queue(self) -> asyncio.Queue[Optional[KalshiFill]]:
        """Lazy-initialize the persist queue in the current event loop."""
        if self._persist_queue is None:
            self._persist_queue = asyncio.Queue(maxsize=10000)
        return self._persist_queue

    def _ensure_shutdown_event(self) -> asyncio.Event:
        """Lazy-initialize the shutdown event in the current event loop."""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    def _ensure_mutex(self) -> asyncio.Lock:
        """Lazy-initialize the mutex in the current event loop."""
        if self._mutex is None:
            self._mutex = asyncio.Lock()
        return self._mutex
    
    def _classify_error(self, error: Exception) -> tuple[str, bool]:
        """Classify error as permanent (no retry) or transient (retry ok).
        
        Returns:
            Tuple of (error_category: str, is_permanent: bool)
        """
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # Permanent errors - retrying will never succeed
        permanent_markers = [
            "no column named",
            "table .* has no column",
            "constraint failed",
            "foreign key constraint",
            "datatype mismatch",
            "syntax error",
            "table not found",
            "no such table",
        ]
        for marker in permanent_markers:
            if marker in error_str:
                return ("schema_permanent", True)
        
        # Connection errors - may succeed on retry
        transient_markers = [
            "database is locked",
            "busy",
            "timeout",
            "unable to open",
            "disk i/o error",
            "connection",
        ]
        for marker in transient_markers:
            if marker in error_str:
                return ("transient", False)
        
        # Default: unknown errors treated as transient (safer to retry once)
        return ("unknown", False)
    
    def _should_log_schema_error(self) -> bool:
        """Rate-limit schema error logging to prevent log spam."""
        now = datetime.now(timezone.utc)
        
        if self._last_schema_error_log is None:
            self._last_schema_error_log = now
            self._schema_error_log_count = 1
            return True
        
        # Reset counter every 60 seconds
        if (now - self._last_schema_error_log).total_seconds() > 60:
            self._last_schema_error_log = now
            self._schema_error_log_count = 0
            return True
        
        # Allow first 5 errors per minute, then suppress
        self._schema_error_log_count += 1
        return self._schema_error_log_count <= 5
    
    def _check_circuit_breaker(self, error: Exception) -> bool:
        """Check and update circuit breaker state. Returns True if circuit should open."""
        category, is_permanent = self._classify_error(error)
        
        if not is_permanent:
            return False
        
        now = datetime.now(timezone.utc)
        
        # Initialize window if needed
        if self._schema_error_window_start is None:
            self._schema_error_window_start = now
            self._schema_error_count = 1
            return False
        
        # Reset window after 60 seconds
        if (now - self._schema_error_window_start).total_seconds() > 60:
            self._schema_error_window_start = now
            self._schema_error_count = 1
            return False
        
        # Increment error count
        self._schema_error_count += 1
        
        # Open circuit after 10 permanent errors in 60 seconds
        if self._schema_error_count >= 10 and not self._circuit_open:
            self._circuit_open = True
            self._circuit_reason = f"{category}: {str(error)[:100]}"
            self._circuit_opened_at = now
            logger.error(
                "CIRCUIT BREAKER OPEN: kalshi_fills persistence halted due to repeated errors. "
                "Reason: %s. Fills will be queued to DLQ until circuit resets.",
                self._circuit_reason
            )
            return True
        
        return False
    
    async def _write_to_dlq(self, fill: KalshiFill, error: Exception, category: str) -> None:
        """Write failed fill to Dead Letter Queue for later replay."""
        try:
            import aiosqlite
            
            record = {
                "fill_id": fill.fill_id,
                "error_type": type(error).__name__,
                "error_category": category,
                "error_message": str(error)[:500],
                "market_ticker": fill.market_ticker,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fill_json": json.dumps(fill.to_dict()) if hasattr(fill, 'to_dict') else str(fill),
            }
            
            self._dlq_buffer.append(record)
            
            # Flush buffer if full
            if len(self._dlq_buffer) >= self._dlq_buffer_max:
                await self._flush_dlq_buffer()
                
        except Exception as dlq_error:
            # Last resort - log but don't fail
            logger.error(f"Failed to write to DLQ: {dlq_error} (original error: {error})")
    
    async def _flush_dlq_buffer(self) -> None:
        """Flush buffered DLQ records to SQLite."""
        if not self._dlq_buffer:
            return
        
        try:
            import aiosqlite
            import os
            
            os.makedirs(os.path.dirname(self._dlq_db_path) if os.path.dirname(self._dlq_db_path) else ".", exist_ok=True)
            
            async with aiosqlite.connect(self._dlq_db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS failed_fills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fill_id TEXT,
                        error_type TEXT,
                        error_category TEXT,
                        error_message TEXT,
                        market_ticker TEXT,
                        timestamp TEXT,
                        fill_json TEXT,
                        replayed INTEGER DEFAULT 0
                    )
                """)
                
                records = [
                    (r["fill_id"], r["error_type"], r["error_category"], 
                     r["error_message"], r["market_ticker"], r["timestamp"], r["fill_json"])
                    for r in self._dlq_buffer
                ]
                
                await db.executemany("""
                    INSERT INTO failed_fills 
                    (fill_id, error_type, error_category, error_message, market_ticker, timestamp, fill_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, records)
                await db.commit()
            
            flushed = len(self._dlq_buffer)
            self._dlq_buffer.clear()
            logger.info(f"DLQ flush complete: {flushed} records written")
            
        except Exception as e:
            logger.error(f"Failed to flush DLQ buffer: {e}")
    
    async def reset_circuit_breaker(self) -> Dict[str, Any]:
        """Manual reset of circuit breaker and replay eligible DLQ fills.
        
        Call this after schema migration is applied.
        """
        was_open = self._circuit_open
        
        # Reset circuit state
        self._circuit_open = False
        self._circuit_reason = None
        self._circuit_opened_at = None
        self._schema_error_count = 0
        self._schema_error_window_start = None
        
        # Flush any pending DLQ records
        await self._flush_dlq_buffer()
        
        # Replay eligible fills
        replayed = await self._replay_dlq_fills()
        
        result = {
            "circuit_was_open": was_open,
            "circuit_now_closed": True,
            "dlq_replayed_count": replayed,
            "fills_dropped_total": self._fills_dropped_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if was_open:
            logger.info(f"Circuit breaker manually reset: {result}")
        
        return result
    
    async def _replay_dlq_fills(self) -> int:
        """Replay fills from DLQ that failed due to schema errors."""
        try:
            import aiosqlite
            
            replayed = 0
            async with aiosqlite.connect(self._dlq_db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Get failed fills that haven't been replayed
                async with db.execute("""
                    SELECT * FROM failed_fills 
                    WHERE replayed = 0
                    AND error_category = 'schema_permanent'
                    ORDER BY timestamp ASC
                    LIMIT 1000
                """) as cursor:
                    rows = await cursor.fetchall()
                    
                    for row in rows:
                        try:
                            fill_id = row["fill_id"]
                            fill_json = row["fill_json"]
                            
                            # Parse the fill JSON and re-insert
                            fill_data = json.loads(fill_json)
                            
                            # Check if already in memory
                            if fill_id in self._fills:
                                # Already have it - mark as replayed
                                replayed += 1
                                continue
                            
                            # Re-parse and add to ledger
                            fill = self._parse_fill(fill_data, "dlq_replay")
                            if fill and fill.fill_id:
                                mutex = self._ensure_mutex()
                                async with mutex:
                                    self._fills[fill.fill_id] = fill
                                    self._index_fill(fill)
                                replayed += 1
                                
                        except Exception as replay_error:
                            logger.warning(f"Failed to replay fill {fill_id}: {replay_error}")
                
                # Mark replayed records
                if replayed > 0:
                    await db.execute("""
                        UPDATE failed_fills 
                        SET replayed = 1
                        WHERE replayed = 0
                        AND error_category = 'schema_permanent'
                    """)
                    await db.commit()
            
            if replayed > 0:
                logger.info(f"Replayed {replayed} fills from DLQ")
                # Trigger persistence
                await self._persist()
            
            return replayed
            
        except Exception as e:
            logger.error(f"Failed to replay DLQ fills: {e}")
            return 0
    
    async def get_dlq_status(self) -> Dict[str, Any]:
        """Get status of the dead letter queue."""
        try:
            import aiosqlite
            
            await self._flush_dlq_buffer()
            
            async with aiosqlite.connect(self._dlq_db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Count by category
                async with db.execute("""
                    SELECT error_category, COUNT(*) as cnt 
                    FROM failed_fills 
                    WHERE replayed = 0
                    GROUP BY error_category
                """) as cursor:
                    by_category = {row["error_category"]: row["cnt"] for row in await cursor.fetchall()}
                
                # Count replayed
                async with db.execute("""
                    SELECT COUNT(*) as cnt FROM failed_fills WHERE replayed = 1
                """) as cursor:
                    replayed = (await cursor.fetchone())["cnt"]
                
                # Total
                async with db.execute("""
                    SELECT COUNT(*) as cnt FROM failed_fills
                """) as cursor:
                    total = (await cursor.fetchone())["cnt"]
                
                return {
                    "circuit_open": self._circuit_open,
                    "circuit_reason": self._circuit_reason,
                    "pending_by_category": by_category,
                    "replayed_count": replayed,
                    "total_count": total,
                    "buffered_count": len(self._dlq_buffer),
                    "fills_dropped_count": self._fills_dropped_count,
                }
                
        except Exception as e:
            return {"error": str(e), "circuit_open": self._circuit_open}
    
    async def start(self) -> int:
        """Bootstrap ledger by loading persisted fills from SQLite.
        
        Returns:
            Number of fills loaded from database.
        """
        if self._loaded_count == 0:
            self._loaded_count = await self.load_from_db()
        return self._loaded_count
    
    async def clear_incomplete_fills(self) -> int:
        """Remove incomplete/false fills from the fills ledger DB.
        
        Incomplete fills are those with count_fp <= 0 or price_cents <= 0.
        These are phantom fills that should not be counted as positions.
        
        Returns:
            Number of fills removed.
        """
        try:
            import aiosqlite
            
            removed = 0
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Delete incomplete fills (count_fp <= 0 or price data missing)
                async with db.execute("""
                    DELETE FROM kalshi_fills
                    WHERE count_fp <= 0
                    OR (yes_price_dollars IS NULL AND no_price_dollars IS NULL)
                    OR yes_price_dollars <= 0
                    OR no_price_dollars <= 0
                """) as cursor:
                    removed = cursor.rowcount
                
                await db.commit()
            
            if removed > 0:
                logger.warning(f"Cleared {removed} incomplete/false fills from DB (phantom fills)")
                # Clear in-memory cache too
                mutex = self._ensure_mutex()
                async with mutex:
                    to_remove = [fill_id for fill_id, fill in self._fills.items() if fill.is_incomplete()]
                    for fill_id in to_remove:
                        del self._fills[fill_id]
                    logger.info(f"Cleared {len(to_remove)} incomplete fills from in-memory cache")
            
            return removed
            
        except Exception as e:
            logger.error(f"Failed to clear incomplete fills: {e}")
            return 0
    
    async def clear_all_fills(self) -> int:
        """Clear all fills from the fills ledger DB and in-memory cache.
        
        This is used when REST API returns 0 positions but fills ledger has stale data.
        REST API is the single source of truth - if it says 0 positions, fills ledger should be 0.
        
        Returns:
            Number of fills removed.
        """
        try:
            import aiosqlite
            
            removed = 0
            async with aiosqlite.connect(self._db_path) as db:
                # Get count before deletion
                async with db.execute("SELECT COUNT(*) FROM kalshi_fills") as cursor:
                    count_row = await cursor.fetchone()
                    removed = count_row[0] if count_row else 0
                
                # Delete all fills
                await db.execute("DELETE FROM kalshi_fills")
                await db.commit()
            
            if removed > 0:
                logger.warning(f"Cleared {removed} fills from DB (sync with REST API ground truth)")
                # Clear in-memory cache too
                mutex = self._ensure_mutex()
                async with mutex:
                    self._fills.clear()
                    self._fills_by_order.clear()
                    self._fills_by_market.clear()
                    self._intents.clear()
                    logger.info(f"Cleared all fills from in-memory cache")
            
            return removed
            
        except Exception as e:
            logger.error(f"Failed to clear all fills: {e}")
            return 0
    
    async def ingest_http_fills(self, fills: List[Dict[str, Any]], 
                                agent_map: Optional[Dict[str, str]] = None) -> Tuple[int, List[str]]:
        """Ingest fills from HTTP /portfolio/fills endpoint.
        
        Args:
            fills: List of fill dicts from Kalshi API
            agent_map: Optional mapping of client_order_id -> agent_id
            
        Returns:
            (new_count, new_fill_ids) — IDs are new rows only (for bus/UI hooks)
        """
        new_count = 0
        new_fill_ids: List[str] = []
        merged_duplicate = False
        
        mutex = self._ensure_mutex()
        async with mutex:
            for raw in fills:
                fill = self._parse_fill(raw, "http_poller")
                if _is_test_fixture_fill(fill.fill_id):
                    continue
                if fill.fill_id in self._fills:
                    # HTTP upsert over prior WS row: enrich without zeroing good data.
                    existing = self._fills[fill.fill_id]
                    if fill.action in ("buy", "sell") and existing.action not in ("buy", "sell"):
                        existing.action = fill.action
                        from merid.event_venues.kalshi.kalshi_ledger_metrics import inc_http_upserts as _incu
                        _incu()
                    if not existing.confirmed_by_rest:
                        existing.confirmed_by_rest = True
                        logger.debug("Fill %s confirmed by REST API", fill.fill_id)
                    # Count: never replace positive with zero
                    if fill.count_fp > 0:
                        existing.count_fp = fill.count_fp
                    elif existing.count_fp <= 0:
                        existing.count_fp = fill.count_fp
                    
                    # FIX: Derive count from proceeds if count is missing but proceeds exists
                    # This handles cases where Kalshi API returns proceeds but not count
                    if existing.count_fp <= 0 and fill.proceeds_dollars is not None and fill.proceeds_dollars != 0:
                        # Derive count from proceeds: proceeds = price * count - fees
                        # Approximate: count ≈ proceeds / price (ignoring fees for estimation)
                        price = fill.yes_price_dollars if fill.yes_price_dollars else fill.no_price_dollars
                        if price and price > 0:
                            derived_count = int(abs(float(fill.proceeds_dollars)) / float(price))
                            if derived_count > 0:
                                existing.count_fp = derived_count
                                logger.info(
                                    "Fill %s: derived count_fp=%d from proceeds=%s price=%s",
                                    fill.fill_id, derived_count, fill.proceeds_dollars, price
                                )
                    # Prices: HTTP source is authoritative - upgrade even if existing has value
                    # This ensures WebSocket incomplete fills get completed by HTTP poller
                    if fill.yes_price_dollars is not None and float(fill.yes_price_dollars) > 0:
                        existing.yes_price_dollars = fill.yes_price_dollars
                        logger.debug("Fill %s: upgraded yes_price from HTTP: %s", fill.fill_id, fill.yes_price_dollars)
                    if fill.no_price_dollars is not None and float(fill.no_price_dollars) > 0:
                        existing.no_price_dollars = fill.no_price_dollars
                        logger.debug("Fill %s: upgraded no_price from HTTP: %s", fill.fill_id, fill.no_price_dollars)
                    
                    # Log if fill is still incomplete after HTTP upsert
                    if existing.is_incomplete():
                        logger.warning(
                            "Fill %s still incomplete after HTTP upsert: count_fp=%s price_cents=%s yes_price=%s no_price=%s",
                            fill.fill_id, existing.count_fp, existing.price_cents,
                            existing.yes_price_dollars, existing.no_price_dollars
                        )
                    if fill.order_id and not existing.order_id:
                        existing.order_id = fill.order_id
                    if fill.client_order_id and not existing.client_order_id:
                        existing.client_order_id = fill.client_order_id
                    if fill.side and not existing.side:
                        existing.side = fill.side
                    merged_duplicate = True
                    self._duplicates_dropped += 1
                    continue

                # Link to intent and resolve action
                if fill.client_order_id and fill.client_order_id in self._intents:
                    intent = self._intents[fill.client_order_id]
                    intent.fill_ids.append(fill.fill_id)
                    intent.status = "filled"
                    intent.last_update = datetime.now(timezone.utc)
                    fill.intent_id = intent.intent_id
                    fill.agent_id = intent.agent_id
                    # Phase 5.4: Copy raw_logit from intent for calibration
                    if hasattr(intent, 'raw_logit') and intent.raw_logit is not None:
                        fill.raw_logit = intent.raw_logit
                    # Resolve action from intent when fill has no explicit action.
                    if intent.action in ("buy", "sell") and fill.action not in ("buy", "sell"):
                        fill.action = intent.action
                    # Task 5: Check intent tags for hedge fills
                    if hasattr(intent, 'tags') and intent.tags:
                        if 'hedge' in intent.tags:
                            fill.fill_source = "hedge"
                            fill.hedge_reason = intent.tags.get('hedge_reason', 'unknown')
                elif agent_map and fill.client_order_id in agent_map:
                    fill.agent_id = agent_map[fill.client_order_id]
                
                # Task 5: Detect hedge fills by client_order_id prefix
                if fill.client_order_id and fill.client_order_id.startswith('HEDGE_'):
                    fill.fill_source = "hedge"
                    # Extract hedge reason from client_order_id (format: HEDGE_reason_timestamp)
                    parts = fill.client_order_id.split('_')
                    if len(parts) >= 2:
                        fill.hedge_reason = parts[1]
                elif not fill.fill_source:
                    fill.fill_source = "alpha"  # Default to alpha if not hedge
                
                self._fills[fill.fill_id] = fill
                self._index_fill(fill)
                new_count += 1
                new_fill_ids.append(fill.fill_id)
                
                # FILL-INGEST: Log fill with TRADE-TRACE linking to original edge/sizing decision
                intent = self._intents.get(fill.client_order_id) if fill.client_order_id else None
                logger.info(
                    "[FILL-INGEST] fill_id=%s ticker=%s side=%s count=%d price_cents=%d notional_usd=%.2f "
                    "edgepct=%.4f netedgecents=%.2f band=%s regime=%s source=%s",
                    fill.fill_id, fill.market_ticker, fill.side, fill.count_fp, fill.price_cents, float(fill.notional_usd),
                    intent.edgepct if intent else 0.0,
                    intent.netedgecents if intent else 0.0,
                    intent.band if intent else "",
                    intent.regime if intent else "",
                    fill.fill_source
                )
                
                # CRITICAL FIX: Call on_fill to update position state for HTTP fills
                # Without this, _open_positions is not updated when fills come via HTTP polling
                self.on_fill(fill)
                
                # Track deep OTM/ITM fills for deployment safety monitoring
                deep_otm_threshold = _get_deep_otm_threshold()
                deep_itm_threshold = _get_deep_itm_threshold()
                # Defensive: Ensure thresholds are ints (profile may return dict in some cases)
                if isinstance(deep_otm_threshold, dict) and 'value' in deep_otm_threshold:
                    deep_otm_threshold = deep_otm_threshold['value']
                if not isinstance(deep_otm_threshold, int):
                    logger.warning(
                        "[DEPLOYMENT-SAFETY] Invalid deep_otm_threshold type: type=%s value=%s",
                        type(deep_otm_threshold).__name__, str(deep_otm_threshold)[:100]
                    )
                    deep_otm_threshold = 0  # Safe fallback
                if isinstance(deep_itm_threshold, dict) and 'value' in deep_itm_threshold:
                    deep_itm_threshold = deep_itm_threshold['value']
                if not isinstance(deep_itm_threshold, int):
                    logger.warning(
                        "[DEPLOYMENT-SAFETY] Invalid deep_itm_threshold type: type=%s value=%s",
                        type(deep_itm_threshold).__name__, str(deep_itm_threshold)[:100]
                    )
                    deep_itm_threshold = 100  # Safe fallback
                # Defensive: Ensure price_cents is an int before comparison (API may return dict in some cases)
                price_cents = fill.price_cents
                if not isinstance(price_cents, int):
                    logger.warning(
                        "[DEPLOYMENT-SAFETY] Invalid price_cents type for deep OTM/ITM check: ticker=%s price_cents=%s type=%s fill_id=%s",
                        fill.market_ticker, price_cents, type(price_cents).__name__, fill.fill_id
                    )
                elif price_cents < deep_otm_threshold:
                    logger.warning(
                        "[DEPLOYMENT-SAFETY] Deep OTM fill detected (HTTP): ticker=%s price=%dc threshold=%dc fill_id=%s",
                        fill.market_ticker, price_cents, deep_otm_threshold, fill.fill_id
                    )
                    if SAFETY_METRICS_AVAILABLE:
                        inc_deep_otm_fill(
                            ticker=fill.market_ticker,
                            source="http_poller",
                            price_cents=price_cents,
                        )
                elif price_cents > deep_itm_threshold:
                    logger.warning(
                        "[DEPLOYMENT-SAFETY] Deep ITM fill detected (HTTP): ticker=%s price=%dc threshold=%dc fill_id=%s",
                        fill.market_ticker, price_cents, deep_itm_threshold, fill.fill_id
                    )
                    if SAFETY_METRICS_AVAILABLE:
                        inc_deep_itm_fill(
                            ticker=fill.market_ticker,
                            source="http_poller",
                            price_cents=price_cents,
                        )
                
                logger.info(
                    "fills_ledger http_ingest fill_id=%s order_id=%s ticker=%s side=%s action=%s size=%s src=http_poller",
                    fill.fill_id,
                    fill.order_id,
                    fill.market_ticker,
                    fill.side,
                    fill.action,
                    fill.count_fp,
                )
                
            self._http_ingested += new_count
            
        if new_count > 0 or merged_duplicate:
            if new_count > 0:
                logger.info(f"Ingested {new_count} new fills from HTTP (total: {len(self._fills)})")
            await self._persist()
            
            # Task 4: Notify PnL tracker of any new hedge fills
            for fill_id in new_fill_ids:
                fill = self._fills.get(fill_id)
                if fill and fill.fill_source == "hedge":
                    await self._notify_pnl_tracker_of_hedge_fill(fill)
            
            # Task 7: Trigger auto-save if interval elapsed
            await self._maybe_trigger_auto_save()
            
            # CRITICAL FIX: Auto-export to CSV after new fills are ingested
            # This ensures trade_history_7days.csv is always up-to-date
            try:
                self.export_to_csv("trade_history_7days.csv", days=7)
            except Exception as e:
                logger.warning(f"Failed to auto-export CSV after HTTP ingest: {e}")
            
        return new_count, new_fill_ids
    
    async def ingest_ws_fill(self, raw: Dict[str, Any], agent_id: Optional[str] = None) -> bool:
        """Ingest a single fill from WebSocket.
        
        Args:
            raw: Fill dict from WebSocket trade event
            agent_id: Agent ID if known from context
            
        Returns:
            True if new fill, False if duplicate
        """
        mutex = self._ensure_mutex()
        async with mutex:
            fill = self._parse_fill(raw, "websocket")
            
            if fill.fill_id in self._fills:
                self._duplicates_dropped += 1
                return False
            
            # WebSocket may not have all fields - try to enrich
            if not fill.agent_id and agent_id:
                fill.agent_id = agent_id
                
            # Link to intent and resolve action
            if fill.client_order_id and fill.client_order_id in self._intents:
                intent = self._intents[fill.client_order_id]
                intent.fill_ids.append(fill.fill_id)
                intent.status = "filled"
                intent.last_update = datetime.now(timezone.utc)
                fill.intent_id = intent.intent_id
                fill.agent_id = intent.agent_id
                # Resolve action from intent when fill has no explicit action
                if intent.action in ("buy", "sell") and fill.action not in ("buy", "sell"):
                    fill.action = intent.action
                # Task 5: Check intent tags for hedge fills
                if hasattr(intent, 'tags') and intent.tags:
                    if 'hedge' in intent.tags:
                        fill.fill_source = "hedge"
                        fill.hedge_reason = intent.tags.get('hedge_reason', 'unknown')
            
            # Task 5: Detect hedge fills by client_order_id prefix
            if fill.client_order_id and fill.client_order_id.startswith('HEDGE_'):
                fill.fill_source = "hedge"
                # Extract hedge reason from client_order_id (format: HEDGE_reason_timestamp)
                parts = fill.client_order_id.split('_')
                if len(parts) >= 2:
                    fill.hedge_reason = parts[1]
            elif not fill.fill_source:
                fill.fill_source = "alpha"  # Default to alpha if not hedge
            
            # Leave action blank when the wire omits it — HTTP ``/portfolio/fills``
            # upserts canonical buy/sell (see ingest_http_fills duplicate branch).

            if fill.is_incomplete():
                # P2: Incomplete WebSocket fills are expected - WS may not have full data
                # HTTP poller will upsert complete data later. This is normal dual-ingestion behavior.
                logger.debug(
                    "fills_ledger ws_fill_incomplete fill_id=%s order_id=%s ticker=%s "
                    "size=%s price_cents=%s (HTTP will complete via upsert)",
                    fill.fill_id,
                    fill.order_id,
                    fill.market_ticker,
                    fill.count_fp,
                    fill.price_cents,
                )
                return False

            self._fills[fill.fill_id] = fill
            self._index_fill(fill)
            self._ws_ingested += 1
            
            # FILL-INGEST: Log fill with TRADE-TRACE linking to original edge/sizing decision
            intent = self._intents.get(fill.client_order_id) if fill.client_order_id else None
            logger.info(
                "[FILL-INGEST] fill_id=%s ticker=%s side=%s count=%d price_cents=%d notional_usd=%.2f "
                "edgepct=%.4f netedgecents=%.2f band=%s regime=%s source=%s",
                fill.fill_id, fill.market_ticker, fill.side, fill.count_fp, fill.price_cents, float(fill.notional_usd),
                intent.edgepct if intent else 0.0,
                intent.netedgecents if intent else 0.0,
                intent.band if intent else "",
                intent.regime if intent else "",
                fill.fill_source
            )
            
            # Track deep OTM/ITM fills for deployment safety monitoring
            deep_otm_threshold = _get_deep_otm_threshold()
            deep_itm_threshold = _get_deep_itm_threshold()
            # Defensive: Ensure thresholds are ints (profile may return dict in some cases)
            if isinstance(deep_otm_threshold, dict) and 'value' in deep_otm_threshold:
                deep_otm_threshold = deep_otm_threshold['value']
            if not isinstance(deep_otm_threshold, int):
                logger.warning(
                    "[DEPLOYMENT-SAFETY] Invalid deep_otm_threshold type: type=%s value=%s",
                    type(deep_otm_threshold).__name__, str(deep_otm_threshold)[:100]
                )
                deep_otm_threshold = 0  # Safe fallback
            if isinstance(deep_itm_threshold, dict) and 'value' in deep_itm_threshold:
                deep_itm_threshold = deep_itm_threshold['value']
            if not isinstance(deep_itm_threshold, int):
                logger.warning(
                    "[DEPLOYMENT-SAFETY] Invalid deep_itm_threshold type: type=%s value=%s",
                    type(deep_itm_threshold).__name__, str(deep_itm_threshold)[:100]
                )
                deep_itm_threshold = 100  # Safe fallback
            # Defensive: Ensure price_cents is an int before comparison (API may return dict in some cases)
            price_cents = fill.price_cents
            if not isinstance(price_cents, int):
                logger.warning(
                    "[DEPLOYMENT-SAFETY] Invalid price_cents type for deep OTM/ITM check: ticker=%s price_cents=%s type=%s fill_id=%s",
                    fill.market_ticker, price_cents, type(price_cents).__name__, fill.fill_id
                )
            elif price_cents < deep_otm_threshold:
                logger.warning(
                    "[DEPLOYMENT-SAFETY] Deep OTM fill detected: ticker=%s price=%dc threshold=%dc fill_id=%s",
                    fill.market_ticker, price_cents, deep_otm_threshold, fill.fill_id
                )
                if SAFETY_METRICS_AVAILABLE:
                    inc_deep_otm_fill(
                        ticker=fill.market_ticker,
                        source="websocket",
                        price_cents=price_cents,
                    )
            elif price_cents > deep_itm_threshold:
                logger.warning(
                    "[DEPLOYMENT-SAFETY] Deep ITM fill detected: ticker=%s price=%dc threshold=%dc fill_id=%s",
                    fill.market_ticker, price_cents, deep_itm_threshold, fill.fill_id
                )
                if SAFETY_METRICS_AVAILABLE:
                    inc_deep_itm_fill(
                        ticker=fill.market_ticker,
                        source="websocket",
                        price_cents=price_cents,
                    )
            
            # Session-based PnL tracking: call on_fill() for new fills
            self.on_fill(fill)
            
        logger.info(
            "fills_ledger ws_ingest fill_id=%s order_id=%s ticker=%s side=%s action=%s size=%s asset=%s src=websocket fill_source=%s",
            fill.fill_id,
            fill.order_id,
            fill.market_ticker,
            fill.side,
            fill.action,
            fill.count_fp,
            fill.resolved_asset(),
            fill.fill_source or "alpha",
        )
        await self._persist()
        
        # Task 4: Notify PnL tracker if this is a hedge fill
        if fill.fill_source == "hedge":
            await self._notify_pnl_tracker_of_hedge_fill(fill)
        
        # Task 7: Trigger auto-save if interval elapsed
        await self._maybe_trigger_auto_save()
        
        # CRITICAL FIX: Auto-export to CSV after new fills are ingested
        # This ensures trade_history_7days.csv is always up-to-date
        try:
            self.export_to_csv("trade_history_7days.csv", days=7)
        except Exception as e:
            logger.warning(f"Failed to auto-export CSV after WS ingest: {e}")
        
        # Task 5: Validate hedge fill consistency
        if fill.fill_source == "hedge":
            validation_errors = self._validate_hedge_fill(fill)
            if validation_errors:
                logger.warning(
                    "fills_ledger hedge_fill_validation_failed fill_id=%s errors=%s",
                    fill.fill_id,
                    validation_errors
                )
        
        return True
    
    def record_intent(self, intent: OrderIntent) -> None:
        """Record an order intent before submission."""
        self._intents[intent.intent_id] = intent
        logger.debug(f"Recorded intent: {intent.intent_id} for {intent.ticker}")
        # Prune stale intents to prevent unbounded growth (runs every 100 adds)
        if len(self._intents) % 100 == 0:
            self._prune_stale_intents()
    
    def _validate_hedge_fill(self, fill: KalshiFill) -> List[str]:
        """Validate a hedge fill for consistency.
        
        Task 5: Check hedge fill metadata for consistency.
        
        Args:
            fill: The KalshiFill to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Check for missing hedge_reason
        if not fill.hedge_reason:
            errors.append("missing_hedge_reason")
        
        # Check for invalid hedge_reason format
        if fill.hedge_reason and not any(
            prefix in fill.hedge_reason 
            for prefix in ["cross_asset", "direct", "timeframe", "unwind"]
        ):
            errors.append(f"unrecognized_hedge_reason_format: {fill.hedge_reason}")
        
        # Check client_order_id has HEDGE_ prefix
        if fill.client_order_id and not fill.client_order_id.startswith("HEDGE_"):
            errors.append("client_order_id_missing_HEDGE_prefix")
        
        # Check for orphaned hedge (no related_alpha_fill_id when expected)
        if fill.hedge_reason and "cross_asset" in fill.hedge_reason:
            # Cross-asset hedges should have a related alpha fill
            if not fill.related_alpha_fill_id:
                # This might be a new hedge, so only warn if it's old
                age_hours = (datetime.now(timezone.utc) - fill.created_time).total_seconds() / 3600
                if age_hours > 1:
                    errors.append(f"orphaned_cross_asset_hedge_age_{age_hours:.1f}h")
        
        return errors
    
    # Task 4: PnL tracker integration methods
    def set_pnl_tracker(self, tracker: "HedgePnLTracker") -> None:
        """Set the PnL tracker for hedge fill callbacks.
        
        Task 4: Enables automatic PnL tracking when hedge fills are recorded.
        """
        self._pnl_tracker = tracker
        logger.info("PnL tracker registered with fills ledger")
    
    # Task 7: Persistence manager integration methods
    def set_persistence_manager(self, manager: "HedgePersistenceManager") -> None:
        """Set the persistence manager for auto-save triggers.
        
        Task 7: Enables automatic persistence of hedge fills.
        """
        self._persistence_manager = manager
        logger.info("Persistence manager registered with fills ledger")
    
    async def _maybe_trigger_auto_save(self) -> None:
        """Trigger auto-save if interval has elapsed.
        
        Task 7: Periodic auto-save of hedge state for recovery.
        """
        if not self._persistence_manager or not self._pnl_tracker:
            return
        
        now = datetime.now(timezone.utc)
        if self._last_auto_save is None:
            self._last_auto_save = now
            return
        
        elapsed_minutes = (now - self._last_auto_save).total_seconds() / 60
        if elapsed_minutes >= self._auto_save_interval_minutes:
            try:
                # Get hedge fills only
                hedge_fills = self.get_hedge_fills(limit=10000)
                # BUG-FIX: Call save_all() instead of non-existent methods
                # HedgePersistenceManager.save_all() handles both fills and tracker
                self._persistence_manager.save_all(hedge_fills, self._pnl_tracker)
                self._last_auto_save = now
                logger.debug(f"Auto-saved {len(hedge_fills)} hedge fills and PnL state")
            except Exception as e:
                logger.warning(f"Auto-save failed: {e}")
    
    async def _notify_pnl_tracker_of_hedge_fill(self, fill: KalshiFill) -> None:
        """Notify PnL tracker of a new hedge fill.
        
        Task 4: Creates PnL record when hedge fill is ingested.
        """
        if not self._pnl_tracker:
            return
        
        try:
            # Check if this fill is linked to an alpha fill
            if fill.related_alpha_fill_id:
                # This is a closing hedge fill - record the exit
                # BUG-FIX: Extract price_cents and count from fill, not pass fill object
                self._pnl_tracker.record_hedge_exit(
                    hedge_fill_id=fill.fill_id,
                    exit_price_cents=fill.price_cents,
                    exit_count=int(fill.count_fp),
                )
            else:
                # This is an opening hedge fill - create a new record
                # Need to find the related alpha fill from hedge_reason
                # Format: "cross_asset_SOL_to_BTC" or "direct_BTC"
                alpha_fill_id = None
                if fill.hedge_reason and "cross_asset" in fill.hedge_reason:
                    # Extract source asset from reason
                    parts = fill.hedge_reason.split("_")
                    if len(parts) >= 3:
                        # Find recent alpha fills for that asset
                        source_asset = parts[2]  # e.g., "SOL" from "cross_asset_SOL_to_BTC"
                        alpha_fills = self.get_alpha_fills(limit=100)
                        for alpha_fill in alpha_fills:
                            if source_asset in alpha_fill.market_ticker:
                                alpha_fill_id = alpha_fill.fill_id
                                break
                
                if alpha_fill_id:
                    # BUG-FIX: Match create_record signature exactly (no notional params)
                    self._pnl_tracker.create_record(
                        alpha_fill_id=alpha_fill_id,
                        alpha_ticker=fill.market_ticker,  # Use hedge ticker as proxy for alpha
                        alpha_side=fill.side,
                        alpha_entry_price_cents=fill.price_cents,
                        alpha_entry_count=int(fill.count_fp),
                        hedge_fill_id=fill.fill_id,
                        hedge_ticker=fill.market_ticker,
                        hedge_side=fill.side,
                        hedge_entry_price_cents=fill.price_cents,
                        hedge_entry_count=int(fill.count_fp),
                        hedge_reason=fill.hedge_reason or "unknown",
                    )
        except Exception as e:
            logger.warning(f"Failed to notify PnL tracker of hedge fill {fill.fill_id}: {e}")

    def _prune_stale_intents(self) -> None:
        """Remove intents that are terminal+old or just very old."""
        now = datetime.now(timezone.utc)
        _terminal = {"filled", "cancelled", "rejected", "expired"}
        to_delete = [
            iid for iid, intent in self._intents.items()
            if (
                (intent.status in _terminal and (now - intent.created_at).total_seconds() > 120)
                or (now - intent.created_at).total_seconds() > 600
            )
        ]
        for iid in to_delete:
            del self._intents[iid]
        if to_delete:
            logger.debug("Pruned %d stale intents (remaining=%d)", len(to_delete), len(self._intents))
    
    def update_intent_status(self, intent_id: str, status: str, 
                            order_id: Optional[str] = None) -> None:
        """Update intent status (submitted, rejected, etc.)."""
        if intent_id in self._intents:
            intent = self._intents[intent_id]
            intent.status = status
            if order_id:
                intent.order_id = order_id
            intent.last_update = datetime.now(timezone.utc)
    
    def get_fills(self, 
                  since: Optional[datetime] = None,
                  market_ticker: Optional[str] = None,
                  agent_id: Optional[str] = None,
                  asset: Optional[str] = None,
                  limit: int = 500) -> List[KalshiFill]:
        """Query fills with filters."""
        # Take snapshot to avoid dict mutation during iteration
        fills = list(self._fills.values())
        
        if since:
            fills = [f for f in fills if f.created_time >= since]
        if market_ticker:
            fills = [f for f in fills if f.market_ticker == market_ticker]
        if agent_id:
            fills = [f for f in fills if f.agent_id == agent_id]
        if asset:
            fills = [f for f in fills if f.asset == asset]
            
        # Sort by created_time descending
        fills.sort(key=lambda f: f.created_time, reverse=True)
        return fills[:limit]
    
    def get_fill_by_id(self, fill_id: str) -> Optional[KalshiFill]:
        """Get a single fill by ID."""
        return self._fills.get(fill_id)
    
    def get_slippage_stats(self, asset: Optional[str] = None, 
                          since: Optional[datetime] = None) -> Dict[str, Dict[str, float]]:
        """Get per-coin slippage statistics.
        
        Args:
            asset: Optional asset filter (BTC, ETH, SOL, XRP, DOGE)
            since: Optional time filter
            
        Returns:
            Dict mapping asset -> stats dict with keys:
            - count: number of fills with slippage data
            - mean_slippage_cents: average slippage in cents
            - max_slippage_cents: maximum slippage in cents
            - min_slippage_cents: minimum slippage in cents
            - total_slippage_cents: sum of all slippage
        """
        fills = list(self._fills.values())
        
        if since:
            fills = [f for f in fills if f.created_time >= since]
        if asset:
            fills = [f for f in fills if f.asset == asset]
        
        # Group by asset
        stats_by_asset: Dict[str, Dict[str, float]] = {}
        for fill in fills:
            if fill.asset and fill.slippage_cents is not None:
                if fill.asset not in stats_by_asset:
                    stats_by_asset[fill.asset] = {
                        "count": 0,
                        "mean_slippage_cents": 0.0,
                        "max_slippage_cents": float('-inf'),
                        "min_slippage_cents": float('inf'),
                        "total_slippage_cents": 0.0,
                    }
                
                stats = stats_by_asset[fill.asset]
                stats["count"] += 1
                stats["total_slippage_cents"] += fill.slippage_cents
                stats["max_slippage_cents"] = max(stats["max_slippage_cents"], fill.slippage_cents)
                stats["min_slippage_cents"] = min(stats["min_slippage_cents"], fill.slippage_cents)
        
        # Compute means
        for asset_stats in stats_by_asset.values():
            if asset_stats["count"] > 0:
                asset_stats["mean_slippage_cents"] = asset_stats["total_slippage_cents"] / asset_stats["count"]
            else:
                asset_stats["mean_slippage_cents"] = 0.0
        
        return stats_by_asset
    
    def get_fill_rate_stats(self, asset: Optional[str] = None,
                           since: Optional[datetime] = None) -> Dict[str, Dict[str, float]]:
        """Get per-coin fill rate statistics.
        
        Fill rate = (number of fills) / (number of order intents)
        
        Args:
            asset: Optional asset filter (BTC, ETH, SOL, XRP, DOGE)
            since: Optional time filter
            
        Returns:
            Dict mapping asset -> stats dict with keys:
            - intents: number of order intents
            - fills: number of fills
            - fill_rate: fills / intents (0.0 to 1.0)
            - partial_fills: number of partially filled orders
        """
        intents = list(self._intents.values())
        fills = list(self._fills.values())
        
        if since:
            intents = [i for i in intents if i.created_at >= since]
            fills = [f for f in fills if f.created_time >= since]
        
        # Group intents by asset (derive from ticker)
        intents_by_asset: Dict[str, int] = {}
        for intent in intents:
            asset = None
            ticker = intent.ticker.upper() if intent.ticker else ""
            if "KXBTC" in ticker:
                asset = "BTC"
            elif "KXETH" in ticker:
                asset = "ETH"
            elif "KXSOL" in ticker:
                asset = "SOL"
            elif "KXXRP" in ticker:
                asset = "XRP"
            elif "KXDOGE" in ticker:
                asset = "DOGE"
            
            if asset:
                intents_by_asset[asset] = intents_by_asset.get(asset, 0) + 1
        
        # Group fills by asset
        fills_by_asset: Dict[str, int] = {}
        partial_fills_by_asset: Dict[str, int] = {}
        for fill in fills:
            if fill.asset:
                fills_by_asset[fill.asset] = fills_by_asset.get(fill.asset, 0) + 1
                # Check if this was a partial fill (count < total intent count)
                if fill.intent_id and fill.intent_id in self._intents:
                    intent = self._intents[fill.intent_id]
                    if fill.count_fp < intent.count:
                        partial_fills_by_asset[fill.asset] = partial_fills_by_asset.get(fill.asset, 0) + 1
        
        # Compute stats for all assets
        all_assets = set(intents_by_asset.keys()) | set(fills_by_asset.keys())
        stats_by_asset: Dict[str, Dict[str, float]] = {}
        
        for asset in all_assets:
            intents_count = intents_by_asset.get(asset, 0)
            fills_count = fills_by_asset.get(asset, 0)
            partial_count = partial_fills_by_asset.get(asset, 0)
            
            fill_rate = fills_count / intents_count if intents_count > 0 else 0.0
            
            stats_by_asset[asset] = {
                "intents": float(intents_count),
                "fills": float(fills_count),
                "fill_rate": fill_rate,
                "partial_fills": float(partial_count),
            }
        
        # Apply asset filter if specified
        if asset:
            stats_by_asset = {k: v for k, v in stats_by_asset.items() if k == asset}
        
        return stats_by_asset
    
    # Task 9: Optimized hedge fill query methods
    def get_hedge_fills(
        self,
        since: Optional[datetime] = None,
        hedge_reason: Optional[str] = None,
        related_alpha_fill_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[KalshiFill]:
        """Query hedge fills with optimized filtering.
        
        Task 9: Uses in-memory filter but designed for DB-backed partial indexes.
        With partial indexes, this would query: WHERE fill_source = 'hedge'
        
        Args:
            since: Only returns fills after this timestamp
            hedge_reason: Filter by specific hedge reason (e.g., "cross_asset_SOL_to_BTC")
            related_alpha_fill_id: Find hedge linked to specific alpha fill
            limit: Maximum results to return
            
        Returns:
            List of hedge KalshiFill objects
        """
        # Use fill_source index hint: WHERE fill_source = 'hedge'
        hedge_fills = [
            f for f in self._fills.values()
            if f.fill_source == "hedge"
        ]
        
        if since:
            hedge_fills = [f for f in hedge_fills if f.created_time >= since]
        if hedge_reason:
            hedge_fills = [f for f in hedge_fills if f.hedge_reason == hedge_reason]
        if related_alpha_fill_id:
            hedge_fills = [f for f in hedge_fills if f.related_alpha_fill_id == related_alpha_fill_id]
        
        # Sort by created_time descending
        hedge_fills.sort(key=lambda f: f.created_time, reverse=True)
        return hedge_fills[:limit]
    
    def get_alpha_fills(
        self,
        since: Optional[datetime] = None,
        market_ticker: Optional[str] = None,
        limit: int = 500,
    ) -> List[KalshiFill]:
        """Query alpha (non-hedge) fills with optimized filtering.
        
        Task 9: Uses in-memory filter but designed for DB-backed partial index.
        With partial index: WHERE fill_source = 'alpha' OR fill_source IS NULL
        
        Args:
            since: Only returns fills after this timestamp
            market_ticker: Filter by market ticker
            limit: Maximum results to return
            
        Returns:
            List of alpha KalshiFill objects
        """
        # Query where fill_source is 'alpha' or NULL (defaults to alpha)
        alpha_fills = [
            f for f in self._fills.values()
            if f.fill_source in ("alpha", None)
        ]
        
        if since:
            alpha_fills = [f for f in alpha_fills if f.created_time >= since]
        if market_ticker:
            alpha_fills = [f for f in alpha_fills if f.market_ticker == market_ticker]
        
        # Sort by created_time descending
        alpha_fills.sort(key=lambda f: f.created_time, reverse=True)
        return alpha_fills[:limit]
    
    def get_fill_source_stats(self) -> Dict[str, int]:
        """Get counts by fill_source for monitoring.
        
        Task 9: Quick aggregation for dashboard/analytics.
        
        Returns:
            Dict with counts: {"alpha": N, "hedge": N, "unknown": N}
        """
        stats = {"alpha": 0, "hedge": 0, "unknown": 0}
        
        for fill in self._fills.values():
            source = fill.fill_source
            if source == "alpha":
                stats["alpha"] += 1
            elif source == "hedge":
                stats["hedge"] += 1
            else:
                stats["unknown"] += 1
        
        return stats
    
    def get_hedge_metrics(self) -> Dict[str, Any]:
        """Get comprehensive hedge metrics for health monitoring.
        
        Task 2: Quick health check endpoint for hedge system status.
        
        Returns:
            Dict with hedge system metrics including:
            - fill_counts: alpha/hedge/unknown breakdown
            - recent_hedge_fills: count in last hour
            - hedge_fill_rate: fills per minute
            - unlinked_hedges: fills without related_alpha_fill_id
        """
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        
        # Basic counts
        stats = self.get_fill_source_stats()
        
        # Recent hedge fills
        recent_hedge_fills = [
            f for f in self._fills.values()
            if f.fill_source == "hedge" and f.created_time >= one_hour_ago
        ]
        
        # Unlinked hedge fills (orphaned hedges)
        unlinked_hedges = [
            f for f in self._fills.values()
            if f.fill_source == "hedge" and not f.related_alpha_fill_id
        ]
        
        # Calculate rate (fills per minute in last hour)
        hedge_fill_rate = len(recent_hedge_fills) / 60.0 if recent_hedge_fills else 0.0
        
        # Time since last hedge fill
        last_hedge_fill = None
        for fill in self._fills.values():
            if fill.fill_source == "hedge":
                if last_hedge_fill is None or fill.created_time > last_hedge_fill:
                    last_hedge_fill = fill.created_time
        
        seconds_since_last_hedge = None
        if last_hedge_fill:
            seconds_since_last_hedge = (now - last_hedge_fill).total_seconds()
        
        return {
            "timestamp": now.isoformat(),
            "fill_counts": stats,
            "recent_hedge_fills_1h": len(recent_hedge_fills),
            "hedge_fill_rate_per_min": round(hedge_fill_rate, 3),
            "unlinked_hedge_fills": len(unlinked_hedges),
            "seconds_since_last_hedge_fill": int(seconds_since_last_hedge) if seconds_since_last_hedge else None,
            "is_healthy": (
                stats["hedge"] > 0 and  # Has hedge fills
                len(unlinked_hedges) < 10 and  # Not too many orphaned hedges
                (seconds_since_last_hedge is None or seconds_since_last_hedge < 3600)  # Recent activity
            ),
        }
    
    def get_intent(self, intent_id: str) -> Optional[OrderIntent]:
        """Get an intent by ID."""
        return self._intents.get(intent_id)
    
    def get_unfilled_intents(self, older_than_seconds: int = 60) -> List[OrderIntent]:
        """Get intents that haven't filled within N seconds."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        return [
            intent for intent in self._intents.values()
            if intent.status in ("submitted", "pending")
            and intent.created_at < cutoff
        ]
    
    def get_orphan_fills(self) -> List[KalshiFill]:
        """Get fills with no linked intent (surprise executions)."""
        # Use list() to avoid dict mutation during iteration
        return [
            fill for fill in list(self._fills.values())
            if fill.intent_id is None and fill.client_order_id is None
        ]
    
    async def compute_position_from_fills_async(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Async wrapper for compute_position_from_fills - runs in thread pool to avoid blocking."""
        import asyncio
        return await asyncio.to_thread(self.compute_position_from_fills, market_ticker)
    
    async def compute_net_positions_async(self) -> Dict[str, Dict[str, Any]]:
        """Async wrapper for compute_net_positions - runs in thread pool to avoid blocking."""
        import asyncio
        return await asyncio.to_thread(self.compute_net_positions)

    def compute_position_from_fills(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Recompute position for a market purely from fills ledger."""
        fill_ids = self._fills_by_market.get(market_ticker, [])
        if not fill_ids:
            return None
            
        yes_contracts = 0
        no_contracts = 0
        yes_cost = Decimal("0")
        no_cost = Decimal("0")
        fees = Decimal("0")
        
        for fill_id in fill_ids:
            fill = self._fills[fill_id]
            fees += fill.fee_cost
            
            if fill.side == "yes":
                if fill.action == "buy":
                    yes_contracts += fill.count_fp
                    yes_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally to maintain correct avg price
                    if yes_contracts > 0:
                        yes_cost -= (yes_cost / yes_contracts) * fill.count_fp
                    yes_contracts -= fill.count_fp
            else:  # side == "no"
                if fill.action == "buy":
                    no_contracts += fill.count_fp
                    no_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally
                    if no_contracts > 0:
                        no_cost -= (no_cost / no_contracts) * fill.count_fp
                    no_contracts -= fill.count_fp
        
        # Net position (positive = long, negative = short)
        net_contracts = yes_contracts - no_contracts
        
        if net_contracts == 0:
            return None
            
        side = "yes" if net_contracts > 0 else "no"
        avg_price = (
            (yes_cost / Decimal(yes_contracts) if yes_contracts > 0 else Decimal("0")) if net_contracts > 0
            else (no_cost / Decimal(no_contracts) if no_contracts > 0 else Decimal("0"))
        )
        
        return {
            "market_ticker": market_ticker,
            "side": side,
            "contracts": abs(net_contracts),
            "avg_price_dollars": float(avg_price),
            "avg_price_cents": int(avg_price * 100),
            "total_fees_usd": float(fees),
            "computed_from_fills": len(fill_ids),
        }
    
    def _compute_position_from_fill_ids(self, market_ticker: str, fill_ids: List[str]) -> Optional[Dict[str, Any]]:
        """Compute position from a specific list of fill IDs (helper for time-filtered positions)."""
        if not fill_ids:
            return None
            
        yes_contracts = 0
        no_contracts = 0
        yes_cost = Decimal("0")
        no_cost = Decimal("0")
        fees = Decimal("0")
        
        for fill_id in fill_ids:
            fill = self._fills.get(fill_id)
            if not fill:
                continue
            fees += fill.fee_cost
            
            if fill.side == "yes":
                if fill.action == "buy":
                    yes_contracts += fill.count_fp
                    yes_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally to maintain correct avg price
                    if yes_contracts > 0:
                        yes_cost -= (yes_cost / yes_contracts) * fill.count_fp
                    yes_contracts -= fill.count_fp
            else:  # side == "no"
                if fill.action == "buy":
                    no_contracts += fill.count_fp
                    no_cost += fill.notional_usd
                else:  # sell — reduce cost basis proportionally
                    if no_contracts > 0:
                        no_cost -= (no_cost / no_contracts) * fill.count_fp
                    no_contracts -= fill.count_fp
        
        # Net position (positive = long, negative = short)
        net_contracts = yes_contracts - no_contracts
        
        if net_contracts == 0:
            return None
            
        side = "yes" if net_contracts > 0 else "no"
        avg_price = (
            (yes_cost / Decimal(yes_contracts) if yes_contracts > 0 else Decimal("0")) if net_contracts > 0
            else (no_cost / Decimal(no_contracts) if no_contracts > 0 else Decimal("0"))
        )
        
        return {
            "market_ticker": market_ticker,
            "side": side,
            "contracts": abs(net_contracts),
            "avg_price_dollars": float(avg_price),
            "avg_price_cents": int(avg_price * 100),
            "total_fees_usd": float(fees),
            "computed_from_fills": len(fill_ids),
        }

    def compute_net_positions(self, since_hours: int = 24) -> Dict[str, Dict[str, Any]]:
        """Compute positions for all markets from fills ledger.
        
        PRODUCTION FIX (2026-05-10): Filter out test positions to prevent bleeding into production.
        PRODUCTION FIX (2026-07-03): Filter by time to exclude stale fills from previous sessions.
        
        Args:
            since_hours: Only include fills from the last N hours (default: 24)
        
        Returns:
            Dict mapping market_ticker -> position dict (same format as compute_position_from_fills)
        """
        from datetime import datetime, timedelta, timezone
        
        positions: Dict[str, Dict[str, Any]] = {}
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        # Iterate over all markets that have fills
        for market_ticker in self._fills_by_market.keys():
            # PRODUCTION FIX (2026-05-10): Skip test tickers
            if _is_test_ticker(market_ticker):
                logger.debug(f"Skipping test ticker in compute_net_positions: {market_ticker}")
                continue
            
            # PRODUCTION FIX (2026-07-03): Time-filter fills to exclude stale data
            fill_ids = self._fills_by_market.get(market_ticker, [])
            recent_fill_ids = [
                fill_id for fill_id in fill_ids
                if self._fills[fill_id].created_time >= cutoff_time
            ]
            
            if not recent_fill_ids:
                continue
            
            # Compute position from recent fills only
            pos = self._compute_position_from_fill_ids(market_ticker, recent_fill_ids)
            if pos:  # Only include non-zero positions
                positions[market_ticker] = pos
        
        return positions
    
    def get_open_exposure_usd(self) -> float:
        """Compute total open notional exposure in USD from fills ledger.
        
        CRITICAL for GlobalRiskGuard: Returns sum of all open position notionals
        so the guard can enforce 2% cycle cap across all agents.
        
        DEPRECATED FOR RISK CALC: Use position_cache.get_all_positions() instead.
        This method includes stale/test fills and manually closed positions which
        incorrectly inflate existing risk beyond actual Kalshi positions.
        
        Returns:
            Total open exposure in USD (cents / 100)
        """
        try:
            # Filter out manually closed positions (those detected in reconciliation)
            # Use 24-hour filter to exclude stale positions from previous sessions
            positions = self.compute_net_positions(since_hours=24)
            total = 0.0
            for ticker, pos in positions.items():
                # Skip markets marked as manually closed in reconciliation
                if hasattr(self, '_manually_closed_logged') and ticker in self._manually_closed_logged:
                    continue
                contracts = pos.get("contracts", 0)
                # PRODUCTION-FIX: Try to get avg_price_cents from market state if not in position data
                avg_price_cents = pos.get("avg_price_cents")
                if avg_price_cents is None:
                    try:
                        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                        state = get_kalshi_market_state_store().get_unified(ticker)
                        if state and state.mid_cents > 0:
                            avg_price_cents = state.mid_cents
                    except Exception as _exc:
                        logger.debug("[FILLS_LEDGER] failed to fetch market state for %s, using 50c fallback: %s", ticker, _exc)
                avg_price_cents = avg_price_cents or DEFAULT_KALSHI_PRICE_CENTS
                total += contracts * (avg_price_cents / 100.0)
            return total
        except Exception as e:
            logger.debug(f"[FILLS_LEDGER] get_open_exposure_usd failed: {e}")
            return 0.0
    
    async def reconcile_with_kalshi_positions(self, 
                                              kalshi_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare computed positions from fills vs Kalshi-reported positions.
        
        PURELY DIAGNOSTIC: Reports facts only, never makes risk decisions.
        The risk engine consumes this report and applies its own thresholds
        based on KalshiRiskConfig to determine trading halts or alerts.
        
        Returns reconciliation report with divergences (facts only, no severity).
        """
        divergences = []
        matched = 0
        ghost_trade_candidates = 0
        
        # Track which markets we've checked
        checked_markets: Set[str] = set()
        
        # Debug: Log fills ledger state for reconciliation diagnostics
        logger.debug(f"Reconciliation starting: {len(kalshi_positions)} Kalshi positions, {len(self._fills)} fills in ledger, {len(self._fills_by_market)} markets with fills")

        for kalshi_pos in kalshi_positions:
            ticker = kalshi_pos.get("market_ticker") or kalshi_pos.get("ticker")
            if not ticker:
                continue

            checked_markets.add(ticker)
            computed = await self.compute_position_from_fills_async(ticker)

            # Debug: Log computed vs Kalshi position for diagnostics
            if computed:
                logger.debug(f"Reconciliation compare {ticker}: Kalshi={kalshi_pos.get('contracts', 0)}@{kalshi_pos.get('side', 'yes')}, Ledger={computed['contracts']}@{computed['side']}")
            else:
                logger.debug(f"Reconciliation compare {ticker}: Kalshi={kalshi_pos.get('contracts', 0)}@{kalshi_pos.get('side', 'yes')}, Ledger=None (no fills)")
            
            kalshi_contracts = int(kalshi_pos.get("contracts", 0) or kalshi_pos.get("count", 0))
            kalshi_side = kalshi_pos.get("side", "yes")
            kalshi_avg_price_cents = int(kalshi_pos.get("avg_price_cents", 0) or kalshi_pos.get("avg_price", 0))
            
            if computed is None:
                # Kalshi has position but we have no fills — ghost trade candidate
                if kalshi_contracts > 0:
                    ghost_trade_candidates += 1
                    divergences.append({
                        "type": "position_without_fills",
                        "market": ticker,
                        "kalshi_contracts": kalshi_contracts,
                        "kalshi_side": kalshi_side,
                        "ledger_contracts": 0,
                        "contract_diff": kalshi_contracts,
                        "pct_diff": 100.0,  # 100% divergence
                    })
                continue
            
            our_contracts = computed["contracts"]
            our_side = computed["side"]
            our_avg_price_cents = computed["avg_price_cents"]
            
            # Calculate divergence metrics (facts only, no thresholds)
            contract_diff = abs(kalshi_contracts - our_contracts)
            price_diff_cents = abs(kalshi_avg_price_cents - our_avg_price_cents)
            
            # Percentage diff using Kalshi as reference (avoid div by zero)
            if kalshi_contracts > 0:
                pct_diff = (contract_diff / kalshi_contracts) * 100.0
            else:
                pct_diff = 100.0 if our_contracts > 0 else 0.0
            
            # Side mismatch is always reported
            side_mismatch = kalshi_side != our_side
            
            # Report all divergences > 0 (facts only)
            if contract_diff > 0 or side_mismatch or price_diff_cents > 1:
                divergences.append({
                    "type": "side_mismatch" if side_mismatch else "contract_divergence",
                    "market": ticker,
                    "kalshi_contracts": kalshi_contracts,
                    "kalshi_side": kalshi_side,
                    "kalshi_avg_price_cents": kalshi_avg_price_cents,
                    "ledger_contracts": our_contracts,
                    "ledger_side": our_side,
                    "ledger_avg_price_cents": our_avg_price_cents,
                    "contract_diff": contract_diff,
                    "price_diff_cents": price_diff_cents,
                    "pct_diff": round(pct_diff, 2),
                })
            else:
                matched += 1
                # Mark fills as reconciled (data integrity bookkeeping only)
                for fill_id in self._fills_by_market.get(ticker, []):
                    fill = self._fills[fill_id]
                    fill.reconciled = True
                    fill.reconciliation_ts = datetime.now(timezone.utc)
        
        # Check for fills without positions (unexpected but not necessarily wrong)
        fills_without_positions = 0
        # settled_tickers: markets we hold fills for but Kalshi no longer reports a position.
        # These are candidate settled/closed markets — callers (FillsPoller) use this to
        # fire AgentPerformanceTracker.record_outcome() for wins/losses recording.
        settled_tickers: List[str] = []
        for ticker in self._fills_by_market:
            if ticker not in checked_markets:
                # We have fills for a market Kalshi didn't report in positions
                # (could be closed position, or settlement, or subaccount filtering)
                fills_without_positions += len(self._fills_by_market[ticker])
                # Only include if we actually have a computed open position for this market
                # (i.e., net long/short > 0 in fills) to avoid counting already-closed markets
                net_pos = self.compute_position_from_fills(ticker)
                if net_pos and net_pos.get("contracts", 0) > 0:
                    settled_tickers.append(ticker)
        
        self._last_reconciliation = datetime.now(timezone.utc)
        self._reconciliation_issues = divergences  # Store for API access
        
        # Determine status based ONLY on existence of divergences (not severity)
        # OK = perfect match, DEGRADED = any divergence exists, BROKEN = ghost trades suspected
        if ghost_trade_candidates > 0:
            self._reconciliation_status = ReconciliationStatus.BROKEN
        elif len(divergences) > 0:
            self._reconciliation_status = ReconciliationStatus.DEGRADED
        else:
            self._reconciliation_status = ReconciliationStatus.OK
        
        # Purely diagnostic report - all facts, no judgments
        report = {
            "status": self._reconciliation_status.value,
            "timestamp": self._last_reconciliation.isoformat(),
            "positions_checked": len(kalshi_positions),
            "positions_matched": matched,
            "divergences": divergences,
            "divergence_count": len(divergences),
            "ghost_trade_candidates": ghost_trade_candidates,
            "fills_without_positions": fills_without_positions,
            "settled_tickers": settled_tickers,  # Markets that settled since last reconcile
            # Ledger metadata
            "fills_total": len(self._fills),
            "fills_from_http": self._http_ingested,
            "fills_from_ws": self._ws_ingested,
            "duplicates_dropped": self._duplicates_dropped,
        }
        
        # Log facts at appropriate levels (not risk decisions)
        if ghost_trade_candidates > 0:
            logger.error(f"RECONCILIATION: {ghost_trade_candidates} positions exist without fills (ghost trade risk)")
        if divergences:
            logger.warning(f"RECONCILIATION: {len(divergences)} divergences found")
        else:
            logger.info(f"RECONCILIATION: {matched} positions matched exactly")
            
        return report
    
    def get_reconciliation_status(self) -> Dict[str, Any]:
        """Get current reconciliation status for API/UI.
        
        Returns diagnostic facts only. Risk engine consumes this and applies
        its own thresholds from KalshiRiskConfig to make trading decisions.
        """
        return {
            "status": self._reconciliation_status.value,
            "last_run": self._last_reconciliation.isoformat() if self._last_reconciliation else None,
            "divergence_count": len(self._reconciliation_issues),
            "divergences": self._reconciliation_issues[:10],  # Limit for API
            # Ghost trade detection metric
            "ghost_trade_candidates": sum(
                1 for d in self._reconciliation_issues 
                if d.get("type") == "position_without_fills"
            ),
        }
    
    def summary(self) -> Dict[str, Any]:
        """Get ledger summary for dashboards.

        Returns keys consumed by ``web/api/kalshi_api.py`` risk endpoint:
        - ``daily_realized_pnl_usd``  — realized PnL from today's fills
        - ``total_realized_pnl_usd``  — realized PnL from all fills
        - ``total_fees_usd``          — sum of all fees
        - ``total_fills``             — fill count
        Plus the original metadata fields.
        
        STRICT MODE: In production (MERID_STRICT_FILL_ID=1), derived fills
        (those without canonical Kalshi IDs) are excluded from PnL until
        confirmed by REST API reconciliation.
        
        Prior day close tracking for daily unrealized PnL change is deferred to future work.
        Current implementation tracks daily realized PnL and total unrealized PnL.
        For daily unrealized PnL change, would need: daily_pnl = daily_realized + (current_unrealized - prior_close_unrealized).
        This requires tracking unrealized_pnl_at_prior_close across process restarts.
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check strict mode
        strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"

        total_realized_pnl = Decimal("0")
        daily_realized_pnl = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        total_fees = Decimal("0")
        
        # LIVE vs PAPER tracking (CRITICAL for bankroll reconciliation)
        live_realized_pnl = Decimal("0")  # Real money trades only
        live_fees = Decimal("0")  # Fees from live trades
        live_fills_count = 0  # Count of live fills
        paper_realized_pnl = Decimal("0")  # Paper/simulated trades
        paper_fills_count = 0  # Count of paper fills

        # Track derived-only fills for reporting
        derived_fills_excluded = 0
        derived_fills_pending = 0

        # Determine which markets have CLOSED positions.
        # BUG-FIX: Use position_cache (which syncs with Kalshi REST) as PRIMARY source
        # instead of compute_position_from_fills(). This ensures manually closed positions
        # and settled markets are correctly identified as closed.
        closed_markets: set = set()
        open_markets: set = set()
        manually_closed_detected: List[str] = []
        
        # Get current positions from position_cache (Kalshi REST-synced)
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            cached_positions = cache.get_all_positions()
            
            # Build set of markets with actual positions from Kalshi
            markets_with_kalshi_position: set = set()
            for pos in cached_positions:
                ticker = getattr(pos, 'market_id', None) or getattr(pos, 'ticker', None)
                contracts = getattr(pos, 'contracts', 0) or getattr(pos, 'size', 0)
                if ticker and contracts > 0:
                    markets_with_kalshi_position.add(ticker.upper())
                    open_markets.add(ticker.upper())
                    # Track unrealized PnL from cache
                    unrealized = getattr(pos, 'unrealized_pnl_cents', 0) or 0
                    total_unrealized_pnl += Decimal(str(unrealized)) / Decimal("100")
            
            # Markets with fills but no Kalshi position are CLOSED (manually settled or expired)
            # Track which manually closed positions we've already logged to prevent spam
            if not hasattr(self, '_manually_closed_logged'):
                self._manually_closed_logged: set = set()
            
            for ticker in self._fills_by_market:
                # PRODUCTION FIX (2026-05-18): Skip test tickers in reconciliation to prevent log spam
                if _is_test_ticker(ticker):
                    logger.debug(f"Skipping test ticker in reconciliation: {ticker}")
                    continue
                    
                if ticker.upper() not in markets_with_kalshi_position:
                    closed_markets.add(ticker.upper())
                    if self.compute_position_from_fills(ticker):
                        # We have fills showing a position, but Kalshi says none - manually closed
                        manually_closed_detected.append(ticker)
                        # Only log once per session to prevent log spam
                        if ticker not in self._manually_closed_logged:
                            logger.info(f"Detected manually closed position: {ticker} (fills show position, Kalshi shows none)")
                            self._manually_closed_logged.add(ticker)
            
            logger.debug(f"Position cache: {len(open_markets)} open, {len(closed_markets)} closed markets")
            
        except Exception as e:
            # SINGLE SOURCE OF TRUTH: Do NOT fall back to fills-based computation
            # If position cache is unavailable, return empty sets - Kalshi API is the only source of truth
            logger.debug(f"Position cache unavailable for summary (will retry): {e}")
            # Return empty sets - will retry when position cache is available
            # This prevents phantom positions from fills-based computation

        # Take snapshot under lock to avoid dict mutation during iteration
        fills_snapshot = list(self._fills.values())

        for fill in fills_snapshot:
            total_fees += fill.fee_cost

            # SKIP TEST FIXTURE FILLS: These are fake test data that leak into production
            if _is_test_fixture_fill(fill.fill_id):
                continue

            # SKIP INVALID FILLS: Zero count or None notional means corrupted/incomplete data
            if fill.count_fp <= 0 or fill.notional_usd is None or fill.notional_usd <= 0:
                continue

            # STRICT MODE SAFETY: Skip derived fills not confirmed by REST
            if strict_mode and fill.derived_id and not fill.confirmed_by_rest:
                derived_fills_excluded += 1
                continue

            # Count derived fills that are still pending confirmation
            if fill.derived_id and not fill.confirmed_by_rest:
                derived_fills_pending += 1

            # REALIZED PnL: only include fills for CLOSED markets (completed round-trips).
            # Open-position buy fills are excluded — they are UNREALIZED until settlement.
            # This prevents showing the cost basis of open positions as "realized losses".
            if fill.market_ticker and fill.market_ticker not in closed_markets:
                continue

            # FIX: Skip PnL calculation for markets without settlement data
            # Binary options require settlement outcome to calculate true PnL
            # Without settlement data, we cannot determine actual profit/loss
            # For now, only count fills that have proceeds_dollars from Kalshi
            if fill.proceeds_dollars is not None:
                # BUG-FIX: Use proceeds_dollars correctly for PnL (Reddit post pitfall: "counting notional as loss")
                # proceeds_dollars is net cash flow: negative for buys (cost), positive for sells (proceeds)
                # For closed markets with both buys and sells, summing all proceeds gives correct PnL:
                #   Buy at 70¢, 10 contracts: proceeds = -7.00 - fees (cost)
                #   Sell at 60¢, 10 contracts: proceeds = +6.00 - fees (proceeds)
                #   Total PnL = -7.00 + 6.00 = -1.00 (correct)
                # This works because proceeds_dollars already includes fees and proper sign convention
                pnl_contribution = fill.proceeds_dollars
                total_realized_pnl += pnl_contribution
            else:
                # Skip fills without proceeds - they're not settled yet
                continue

            # LIVE vs PAPER split (CRITICAL for bankroll reconciliation)
            if fill.is_live:
                live_realized_pnl += pnl_contribution
                live_fees += fill.fee_cost
                live_fills_count += 1
            else:
                paper_realized_pnl += pnl_contribution
                paper_fills_count += 1

            if fill.created_time >= today_start:
                daily_realized_pnl += pnl_contribution

        # Log strict mode exclusions for observability
        if strict_mode and derived_fills_excluded > 0:
            logger.warning(
                f"STRICT MODE: Excluded {derived_fills_excluded} derived fills from PnL "
                f"(pending REST confirmation: {derived_fills_pending})"
            )

        from merid.event_venues.kalshi.kalshi_ledger_metrics import snapshot as _metrics_snap
        # Calculate daily unrealized change if prior close snapshot exists
        # Formula: daily_pnl = daily_realized + (current_unrealized - prior_close_unrealized)
        daily_unrealized_change_usd = 0.0
        has_prior_snapshot = False
        try:
            # For now, use a default account_id (should be parameterized in production)
            account_id = "default"
            snapshot = self._eod_snapshots.get(account_id)
            
            if snapshot is None:
                # Edge case: New user or first day - no prior snapshot
                logger.debug("No prior EOD snapshot found for account=%s, using daily_realized only", account_id)
                daily_unrealized_change_usd = 0.0
            else:
                # Check if snapshot is stale (older than 2 days)
                snapshot_date = datetime.fromisoformat(snapshot.snapshot_date)
                current_date = datetime.now(timezone.utc).date()
                snapshot_age = (current_date - snapshot_date.date()).days
                
                if snapshot_age > 2:
                    # Edge case: Stale snapshot (missed EOD)
                    logger.warning(
                        "Stale EOD snapshot for account=%s (age=%d days), using daily_realized only. "
                        "Consider recording fresh EOD snapshot.",
                        account_id, snapshot_age
                    )
                    daily_unrealized_change_usd = 0.0
                else:
                    # Normal case: Calculate daily unrealized change
                    has_prior_snapshot = True
                    prior_close_unrealized_cents = snapshot.unrealized_pnl_eod_cents
                    current_unrealized_cents = int(total_unrealized_pnl * 100)
                    daily_unrealized_change_cents = current_unrealized_cents - prior_close_unrealized_cents
                    daily_unrealized_change_usd = float(daily_unrealized_change_cents) / 100.0
                    
                    logger.debug(
                        "Daily unrealized change: prior_close=%dc current=%dc change=%dc (%.2f USD) snapshot_age=%d days",
                        prior_close_unrealized_cents, current_unrealized_cents, 
                        daily_unrealized_change_cents, daily_unrealized_change_usd, snapshot_age
                    )
        except Exception as e:
            logger.debug("Failed to calculate daily unrealized change: %s", e)
            daily_unrealized_change_usd = 0.0
        
        # FIX: Use open_markets_count from position_cache as canonical open_positions_count
        # _open_positions internal state may not be synchronized correctly
        canonical_open_positions_count = len(open_markets)
        
        return {
            # Keys expected by kalshi_api.py risk endpoint
            "daily_realized_pnl_usd": float(daily_realized_pnl),
            "total_realized_pnl_usd": float(total_realized_pnl),
            "total_unrealized_pnl_usd": float(total_unrealized_pnl),
            "daily_unrealized_change_usd": daily_unrealized_change_usd,  # NEW: change in unrealized PnL since prior close
            # Session-based PnL metrics (NEW)
            # session_total_pnl_usd = session_realized_pnl_usd + session_unrealized_pnl_usd (this session only)
            # cumulative_realized_pnl_usd = sum of all closed trades across all sessions
            "session_realized_pnl_usd": float(self._session_realized_pnl),
            "session_unrealized_pnl_usd": float(self._session_unrealized_pnl),
            "session_total_pnl_usd": float(self._session_realized_pnl + self._session_unrealized_pnl),
            "cumulative_realized_pnl_usd": float(self._cumulative_realized_pnl),
            "session_date": self._last_session_start_date,
            "open_positions_count": canonical_open_positions_count,
            # Original fields
            "open_markets_count": len(open_markets),
            "closed_markets_count": len(closed_markets),
            "total_fees_usd": float(total_fees),
            "total_fills": len(self._fills),
            # LIVE vs PAPER breakdown (CRITICAL for bankroll reconciliation)
            "live_realized_pnl_usd": float(live_realized_pnl),
            "live_fees_usd": float(live_fees),
            "live_fills_count": live_fills_count,
            "paper_realized_pnl_usd": float(paper_realized_pnl),
            "paper_fills_count": paper_fills_count,
            "current_trade_mode": os.getenv("MERID_PM_TRADING_MODE", "unknown"),
            # Original metadata
            "fills_total": len(self._fills),
            "fills_from_http": self._http_ingested,
            "fills_from_ws": self._ws_ingested,
            "duplicates_dropped": self._duplicates_dropped,
            "intents_recorded": len(self._intents),
            "unfilled_intents": len(self.get_unfilled_intents()),
            "orphan_fills": len(self.get_orphan_fills()),
            "reconciliation": self.get_reconciliation_status(),
            # Strict mode tracking
            "strict_mode": strict_mode,
            "derived_fills_excluded": derived_fills_excluded,
            "derived_fills_pending": derived_fills_pending,
            # Position tracking
            "manually_closed_detected": manually_closed_detected,
            "open_markets_list": sorted(list(open_markets)),
            "closed_markets_list": sorted(list(closed_markets)),
            # Observability counters from kalshi_ledger_metrics
            **_metrics_snap(),
        }
    
    def record_eod_snapshot(self, account_id: str, cash_eod_cents: int, 
                           portfolio_value_eod_cents: int, unrealized_pnl_eod_cents: int) -> None:
        """Record end-of-day snapshot for daily PnL change calculation.
        
        Args:
            account_id: Account identifier
            cash_eod_cents: Cash balance at end of day
            portfolio_value_eod_cents: Portfolio value at end of day
            unrealized_pnl_eod_cents: Unrealized PnL at end of day
        """
        from merid.event_venues.kalshi.portfolio_models import EODSnapshot
        from datetime import datetime, timezone
        
        snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snapshot = EODSnapshot(
            account_id=account_id,
            snapshot_date=snapshot_date,
            cash_eod_cents=cash_eod_cents,
            portfolio_value_eod_cents=portfolio_value_eod_cents,
            unrealized_pnl_eod_cents=unrealized_pnl_eod_cents,
        )
        self._eod_snapshots[account_id] = snapshot
        logger.info(
            "EOD snapshot recorded for account=%s date=%s cash=%dc portfolio=%dc unrealized=%dc",
            account_id, snapshot_date, cash_eod_cents, portfolio_value_eod_cents, unrealized_pnl_eod_cents
        )
    
    def get_prior_close_unrealized(self, account_id: str) -> int:
        """Get unrealized PnL at prior day close for daily change calculation.
        
        Args:
            account_id: Account identifier
            
        Returns:
            Unrealized PnL at prior close in cents, or 0 if no snapshot exists
        """
        snapshot = self._eod_snapshots.get(account_id)
        if snapshot is None:
            return 0
        return snapshot.unrealized_pnl_eod_cents
    
    def _get_current_session_date(self) -> str:
        """Get current session date (YYYY-MM-DD)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    def start_new_session(self, session_date: Optional[str] = None) -> None:
        """Start a new trading session, resetting session state.
        
        Args:
            session_date: Session date (YYYY-MM-DD), defaults to current date
        """
        if session_date is None:
            session_date = self._get_current_session_date()
        
        # Only reset if session boundary changed
        if self._last_session_start_date == session_date:
            logger.debug("Session boundary unchanged: %s", session_date)
            return
        
        logger.info("Starting new session: %s (previous: %s)", session_date, self._last_session_start_date)
        
        self._last_session_start_date = session_date
        self._session_realized_pnl = Decimal("0")
        self._session_unrealized_pnl = Decimal("0")
        # Note: Do NOT reset cumulative_realized_pnl - it persists across sessions
        # Do NOT reset open_positions or processed_fill_ids - they persist for reconciliation
        # These are cleared only on full system reset
        
        self._persist_session_metadata(session_date)
    
    def _persist_session_metadata(self, session_date: str) -> None:
        """Persist session metadata to storage.
        
        Args:
            session_date: Session date (YYYY-MM-DD)
        """
        try:
            metadata = {
                "session_date": session_date,
                "session_realized_pnl": str(self._session_realized_pnl),
                "session_unrealized_pnl": str(self._session_unrealized_pnl),
                "cumulative_realized_pnl": str(self._cumulative_realized_pnl),
                "processed_fill_ids": list(self._processed_fill_ids),  # Persist for restart safety
                "last_eod_snapshot_date": self._last_eod_snapshot_date,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # Store in data directory
            import json
            from pathlib import Path
            session_file = Path("data") / "kalshi_session_metadata.json"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(session_file, "w") as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug("Session metadata persisted: %s (fills=%d)", session_date, len(self._processed_fill_ids))
        except Exception as e:
            logger.warning("Failed to persist session metadata: %s", e)
    
    def maybe_record_eod_snapshot(self, account_id: str = "default") -> bool:
        """Record EOD snapshot if day has changed since last snapshot.
        
        This should be called periodically (e.g., every minute) to automatically
        record EOD snapshots at market close for accurate daily PnL calculation.
        
        Args:
            account_id: Account identifier
            
        Returns:
            True if snapshot was recorded, False if already recorded for today
        """
        current_date = self._get_current_session_date()
        
        # Check if we already recorded a snapshot for today
        if self._last_eod_snapshot_date == current_date:
            return False
        
        # Get current unrealized PnL from summary
        try:
            s = self.summary()
            unrealized_pnl_cents = int(float(s.get("total_unrealized_pnl_usd", 0)) * 100)
            
            # Get current balance from bankroll service v2 (single source of truth)
            cash_eod_cents = 0
            portfolio_value_eod_cents = 0
            try:
                # CRITICAL FIX: Use cached bankroll to avoid blocking during initialization
                # get_summary_sync() uses run_coroutine_threadsafe with 30s timeout which blocks
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import _BANKROLL_SERVICE_V2
                    # Use cached value from bankroll service if available
                    if _BANKROLL_SERVICE_V2 and _BANKROLL_SERVICE_V2._current and _BANKROLL_SERVICE_V2._current.equity_usd:
                        cash_eod_cents = int(float(_BANKROLL_SERVICE_V2._current.equity_usd) * 100)
                        portfolio_value_eod_cents = cash_eod_cents + unrealized_pnl_cents
                except Exception as bankroll_exc:
                    logger.warning(f"[FILLS-LEDGER] Bankroll service unavailable during initialization: {bankroll_exc}")
            except Exception:
                # Fallback: use unrealized PnL as proxy for portfolio value
                portfolio_value_eod_cents = unrealized_pnl_cents
            
            # Record the snapshot
            self.record_eod_snapshot(
                account_id=account_id,
                cash_eod_cents=cash_eod_cents,
                portfolio_value_eod_cents=portfolio_value_eod_cents,
                unrealized_pnl_eod_cents=unrealized_pnl_cents
            )
            
            self._last_eod_snapshot_date = current_date
            self._persist_session_metadata(current_date)
            
            logger.info(
                "Automatic EOD snapshot recorded for date=%s account=%s unrealized=%dc",
                current_date, account_id, unrealized_pnl_cents
            )
            return True
            
        except Exception as e:
            logger.warning("Failed to record automatic EOD snapshot: %s", e)
            return False
    
    def _load_session_metadata(self) -> None:
        """Load session metadata from storage on startup.
        
        BUG-FIX (2026-05-12): Skip file I/O if called from async context to prevent
        event loop blocking. Session metadata is best-effort for PnL tracking,
        not critical for fill processing.
        """
        try:
            # Check if we're in an async context - if so, skip file I/O
            try:
                asyncio.get_running_loop()
                logger.debug(
                    "Skipping session metadata load in async context to avoid blocking event loop. "
                    "Session PnL tracking will start fresh."
                )
                return
            except RuntimeError:
                # No event loop, safe to do blocking I/O
                pass
            
            from pathlib import Path
            session_file = Path("data") / "kalshi_session_metadata.json"
            
            if not session_file.exists():
                logger.debug("No session metadata file found, starting fresh")
                return
            
            import json
            with open(session_file, "r") as f:
                metadata = json.load(f)
            
            self._last_session_start_date = metadata.get("session_date")
            self._session_realized_pnl = Decimal(metadata.get("session_realized_pnl", "0"))
            self._session_unrealized_pnl = Decimal(metadata.get("session_unrealized_pnl", "0"))
            self._cumulative_realized_pnl = Decimal(metadata.get("cumulative_realized_pnl", "0"))
            self._last_eod_snapshot_date = metadata.get("last_eod_snapshot_date")
            
            logger.info(
                "Session metadata loaded: date=%s session_realized=%s cumulative_realized=%s last_eod=%s",
                self._last_session_start_date, self._session_realized_pnl, self._cumulative_realized_pnl, self._last_eod_snapshot_date
            )
        except Exception as e:
            logger.warning("Failed to load session metadata: %s", e)
    
    def _update_cumulative_realized_pnl(self, trade_pnl: Decimal) -> None:
        """Update cumulative realized PnL when a trade closes.
        
        Args:
            trade_pnl: Realized PnL from closed trade
        """
        self._cumulative_realized_pnl += trade_pnl
        logger.debug("Cumulative realized PnL updated: %s (trade_pnl=%s)", self._cumulative_realized_pnl, trade_pnl)
        # Persist immediately to avoid loss on crash
        self._persist_session_metadata(self._get_current_session_date())
    
    def export_to_csv(self, csv_path: str = "trade_history_7days.csv", days: int = 7) -> int:
        """Export fills to CSV file for analysis and audit.
        
        This writes all fills from the last N days to the specified CSV file,
        maintaining the format expected by analysis scripts.
        
        Args:
            csv_path: Path to the CSV file to write
            days: Number of days of history to include
            
        Returns:
            Number of fills written to CSV
        """
        import csv
        from pathlib import Path
        
        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get fills within date range
        recent_fills = self.get_fills(since=cutoff_date, limit=10000)
        
        # Filter out test fixtures
        recent_fills = [f for f in recent_fills if not _is_test_fixture_fill(f.fill_id)]
        
        # Prepare CSV path
        csv_file = Path(csv_path)
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write CSV
        fieldnames = [
            "fill_id", "order_id", "market_ticker", "side", "action",
            "quantity", "price", "yes_price", "no_price", "total_cost",
            "fee", "net_cost", "created_time", "asset", "is_taker"
        ]
        
        written_count = 0
        try:
            with open(csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for fill in recent_fills:
                    # Extract asset from ticker
                    asset = fill.resolved_asset() or ""
                    
                    # Calculate total cost
                    total_cost = fill.count_fp * (fill.yes_price_dollars or 0) if fill.side == "yes" else fill.count_fp * (fill.no_price_dollars or 0)
                    
                    # Net cost includes fees
                    net_cost = total_cost + fill.fee_cost
                    
                    row = {
                        "fill_id": fill.fill_id,
                        "order_id": fill.order_id or "",
                        "market_ticker": fill.market_ticker,
                        "side": fill.side,
                        "action": fill.action,
                        "quantity": fill.count_fp,
                        "price": float(fill.price_cents) / 100.0 if fill.price_cents else 0,
                        "yes_price": float(fill.yes_price_dollars) if fill.yes_price_dollars else 0,
                        "no_price": float(fill.no_price_dollars) if fill.no_price_dollars else 0,
                        "total_cost": float(total_cost),
                        "fee": float(fill.fee_cost),
                        "net_cost": float(net_cost),
                        "created_time": fill.created_time.isoformat() if fill.created_time else "",
                        "asset": asset,
                        "is_taker": "True" if fill.ingestion_source == "websocket" else "False"
                    }
                    writer.writerow(row)
                    written_count += 1
            
            logger.info(
                "Exported %d fills to CSV: %s (last %d days)",
                written_count, csv_path, days
            )
            
        except Exception as e:
            logger.error("Failed to export fills to CSV: %s", e)
        
        return written_count
    
    def _get_instrument_key(self, fill: KalshiFill) -> str:
        """Get instrument key for position tracking.
        
        Args:
            fill: KalshiFill object
            
        Returns:
            Instrument key (e.g., "market_ticker:side")
        """
        return f"{fill.market_ticker}:{fill.side}"
    
    def _create_new_position(self, fill: KalshiFill) -> Dict[str, Any]:
        """Create new position state from fill.
        
        Args:
            fill: KalshiFill object
            
        Returns:
            Position state dictionary
        """
        return {
            "market_ticker": fill.market_ticker,
            "side": fill.side,
            "total_contracts": fill.count_fp,
            "avg_price_cents": fill.price_cents,
            "total_cost_cents": fill.count_fp * fill.price_cents,
            "fees_cents": int(fill.fee_cost * 100) if fill.fee_cost else 0,
            "fills": [fill.fill_id],
            "created_at": fill.created_time.isoformat(),
        }
    
    def _update_position_with_fill(self, position: Dict[str, Any], fill: KalshiFill) -> None:
        """Update position state with new fill.
        
        Args:
            position: Existing position state
            fill: New fill to apply
        """
        position["fills"].append(fill.fill_id)
        
        # Update weighted average price
        old_contracts = position["total_contracts"]
        old_cost = position["total_cost_cents"]
        new_contracts = fill.count_fp
        new_cost = new_contracts * fill.price_cents
        
        total_contracts = old_contracts + new_contracts
        if total_contracts > 0:
            position["avg_price_cents"] = (old_cost + new_cost) // total_contracts
            position["total_contracts"] = total_contracts
            position["total_cost_cents"] = old_cost + new_cost
        
        # Add fees
        position["fees_cents"] += int(fill.fee_cost * 100) if fill.fee_cost else 0
    
    def _position_is_closed(self, position: Dict[str, Any]) -> bool:
        """Check if position is closed (net contracts = 0).
        
        Args:
            position: Position state
            
        Returns:
            True if position is closed
        """
        return position["total_contracts"] == 0
    
    def _compute_realized_pnl(self, position: Dict[str, Any]) -> Decimal:
        """Compute realized PnL from closed position.
        
        Args:
            position: Closed position state
            
        Returns:
            Realized PnL in USD
        """
        # For Kalshi binary options, realized PnL is calculated from fill proceeds
        # Sum proceeds from all closing fills minus cost basis and fees
        total_proceeds = Decimal("0")
        total_cost = Decimal("0")
        total_fees = Decimal("0")
        
        # Iterate through fills in position to calculate total proceeds
        for fill_id in position["fills"]:
            fill = self._fills.get(fill_id)
            if fill:
                # For sells, proceeds_dollars is the cash received
                # For buys, proceeds_dollars is negative (cash spent)
                if fill.proceeds_dollars is not None:
                    if fill.action == "sell":
                        total_proceeds += fill.proceeds_dollars
                    else:
                        total_cost += fill.proceeds_dollars  # Cost is negative for buys
                total_fees += fill.fee_cost if fill.fee_cost else Decimal("0")
        
        # Realized PnL = total proceeds - total cost - total fees
        realized_pnl = total_proceeds - total_cost - total_fees
        return realized_pnl
    
    def on_fill(self, fill: KalshiFill) -> None:
        """Handle fill event with position state machine.
        
        Args:
            fill: KalshiFill object
        """
        # Deduplicate fills
        if fill.fill_id in self._processed_fill_ids:
            return
        
        self._processed_fill_ids.add(fill.fill_id)
        
        # CRITICAL FIX: Notify agent_performance_tracker of fill for wins/losses tracking
        if fill.agent_id and fill.action in ("buy", "sell"):
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                
                # Calculate predicted edge from price (if not provided)
                # For YES: edge = (1 - price) if we expect YES to resolve true
                # For NO: edge = price if we expect NO to resolve false
                predicted_edge = 0.0
                confidence = 0.5
                if fill.side == "yes":
                    predicted_edge = (1.0 - float(fill.price_cents) / 100.0)
                elif fill.side == "no":
                    predicted_edge = float(fill.price_cents) / 100.0
                
                # Extract velocity from fill if available (from raw_payload or decision_trace)
                velocity = None
                try:
                    if fill.raw_payload:
                        import json
                        payload = json.loads(fill.raw_payload) if isinstance(fill.raw_payload, str) else fill.raw_payload
                        velocity = payload.get('velocity')
                except Exception:
                    pass
                
                tracker.record_fill(
                    agent_id=fill.agent_id,
                    market_id=fill.market_ticker,
                    side=fill.side,
                    price_cents=fill.price_cents,
                    contracts=fill.count_fp,
                    predicted_edge=predicted_edge,
                    confidence=confidence,
                    velocity=velocity
                )
                logger.debug(
                    "Recorded fill in agent_performance_tracker: agent=%s market=%s side=%s price=%dc contracts=%d",
                    fill.agent_id, fill.market_ticker, fill.side, fill.price_cents, fill.count_fp
                )
            except Exception as e:
                logger.debug("Failed to record fill in agent_performance_tracker: %s", e)
        
        # Get or create position
        instrument_key = self._get_instrument_key(fill)
        position = self._open_positions.get(instrument_key)
        
        if position is None:
            position = self._create_new_position(fill)
            self._open_positions[instrument_key] = position
            
            # CRITICAL FIX: Add position to PositionMonitor for exit policy enforcement
            # This ensures fills_ledger-tracked positions have TP/SL/trailing stop coverage
            # Previously, fills_ledger maintained separate position state without exit monitoring
            try:
                from merid.position_management.position_monitor import get_position_monitor
                from merid.position_management.position import Position, PositionSide, TrailingType
                
                monitor = get_position_monitor()
                
                # Read profile configuration for trailing stops
                trailing_enabled = False
                trailing_distance_cents = 5
                min_profit_cents = 12
                activation_delay_sec = 30
                
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                    if is_profile_active():
                        adapter = get_active_profile()
                        profile = adapter.profile
                        trailing_enabled = profile.trailing_stop_enabled
                        trailing_distance_cents = profile.trailing_stop_trailing_distance_cents
                        min_profit_cents = profile.trailing_stop_min_profit_cents
                        activation_delay_sec = profile.trailing_stop_activation_delay_sec
                except Exception as ts_err:
                    logger.debug("[FILLS-LEDGER] Could not read trailing stop config: %s", ts_err)
                
                # Assign default SL if missing
                sl_price = position.get("avg_price_cents", 0)
                if sl_price:
                    sl_price = max(1, sl_price - 5)
                
                # Calculate risk for trailing stop
                risk_cents = abs(position.get("avg_price_cents", 0) - sl_price) if sl_price else 5
                
                # Mandatory trailing stop (FIXED_CENTS mode)
                trailing_type = TrailingType.FIXED_CENTS
                trailing_param = trailing_distance_cents
                
                # Extract series_ticker from market_id
                market_id = fill.market_ticker
                series_ticker = market_id.split("-")[0] if "-" in market_id else market_id
                
                side_enum = PositionSide.YES if position.get("side") == "yes" else PositionSide.NO
                
                monitor_position = Position(
                    position_id=market_id,
                    market_id=market_id,
                    series_ticker=series_ticker,
                    side=side_enum,
                    size=position.get("total_contracts", 1),
                    avg_entry_price_cents=position.get("avg_price_cents", 0),
                    take_profit_price_cents=None,  # fills_ledger doesn't track TP
                    stop_loss_price_cents=sl_price,
                    trailing_type=trailing_type,
                    trailing_param=trailing_param,
                    exit_policy_id="fills_ledger",
                )
                
                monitor.add_position(monitor_position)
                logger.info(
                    "[FILLS-LEDGER-POSITION-MONITOR] Added position to monitor: market=%s side=%s size=%d SL=%dc",
                    market_id, position.get("side"), position.get("total_contracts"), sl_price
                )
            except Exception as monitor_err:
                logger.error("[FILLS-LEDGER] CRITICAL: Failed to add position to monitor: %s", monitor_err, exc_info=True)
                # CRITICAL: Do not silently swallow - this means exit policies won't execute
                raise RuntimeError(f"Failed to add fills_ledger position to monitor - exit policies will not execute: {monitor_err}")
        else:
            # Calculate PnL for partial exit before updating position
            old_contracts = position["total_contracts"]
            self._update_position_with_fill(position, fill)
            new_contracts = position["total_contracts"]
            
            # If this fill reduced position size, realize PnL incrementally
            if new_contracts < old_contracts:
                # Partial exit - realize PnL for the exited portion
                exited_contracts = old_contracts - new_contracts
                partial_pnl = self._compute_partial_exit_pnl(position, fill, exited_contracts)
                if partial_pnl != 0:
                    self._session_realized_pnl += partial_pnl
                    self._update_cumulative_realized_pnl(partial_pnl)
                    logger.debug(
                        "Partial exit realized: %s exited=%d pnl=%s session_realized=%s cumulative_realized=%s",
                        instrument_key, exited_contracts, partial_pnl, self._session_realized_pnl, self._cumulative_realized_pnl
                    )
        
        # Check if position is now closed
        if self._position_is_closed(position):
            trade_pnl = self._compute_realized_pnl(position)
            self._session_realized_pnl += trade_pnl
            self._update_cumulative_realized_pnl(trade_pnl)

            # Determine exit reason based on fill context
            exit_reason = "SETTLEMENT"  # Default for fills that close positions
            if fill.side == "sell" and fill.action == "sell":
                # Could be TP, SL, or manual - infer from price if possible
                # For now, use SETTLEMENT as default
                exit_reason = "SETTLEMENT"

            # Calculate realized R
            realized_r = 0.0
            avg_price = position.get("avg_price_cents", 0)
            if avg_price and avg_price > 0:
                # Risk is max loss (entry - 0 for YES, 100 - entry for NO)
                if position.get("side") == "yes":
                    risk_cents = avg_price
                else:
                    risk_cents = 100 - avg_price
                total_contracts = position.get("total_contracts", 1)
                if risk_cents > 0 and total_contracts > 0:
                    realized_r = float(trade_pnl) / (risk_cents * total_contracts)

            logger.info(
                "[EXIT] market=%s side=%s reason=%s realized_R=%.2f asset=N/A confidence=N/A time_in_trade=N/A pnl_cents=%d",
                fill.market_ticker, position.get("side", "unknown"), exit_reason, realized_r, int(trade_pnl * 100)
            )

            del self._open_positions[instrument_key]
            logger.info(
                "Position closed: %s pnl=%s session_realized=%s cumulative_realized=%s",
                instrument_key, trade_pnl, self._session_realized_pnl, self._cumulative_realized_pnl
            )
            
            # CRITICAL FIX: Remove position from PositionMonitor when closed
            # This ensures the monitor doesn't track closed positions
            try:
                from merid.position_management.position_monitor import get_position_monitor
                monitor = get_position_monitor()
                monitor.remove_position(fill.market_ticker)
                logger.info(
                    "[FILLS-LEDGER-POSITION-MONITOR] Removed position from monitor: market=%s",
                    fill.market_ticker
                )
            except Exception as monitor_err:
                logger.warning("[FILLS-LEDGER] Failed to remove position from monitor: %s", monitor_err)
            
            # CRITICAL FIX: Notify agent_performance_tracker of position close
            if fill.agent_id:
                try:
                    from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                    tracker = get_agent_performance_tracker()
                    tracker.record_close(
                        agent_id=fill.agent_id,
                        market_id=fill.market_ticker,
                        exit_price_cents=fill.price_cents,
                        profit_usd=trade_pnl
                    )
                    logger.debug(
                        "Recorded close in agent_performance_tracker: agent=%s market=%s pnl=%s",
                        fill.agent_id, fill.market_ticker, trade_pnl
                    )
                except Exception as e:
                    logger.debug("Failed to record close in agent_performance_tracker: %s", e)
        
        # Recompute unrealized PnL
        self._session_unrealized_pnl = self._recompute_unrealized_pnl()
        
        # Persist state
        self._persist_session_metadata(self._get_current_session_date())
    
    def _compute_partial_exit_pnl(self, position: Dict[str, Any], fill: KalshiFill, exited_contracts: int) -> Decimal:
        """Compute PnL for partial exit from position.
        
        Args:
            position: Position state
            fill: Exit fill
            exited_contracts: Number of contracts exited
            
        Returns:
            Realized PnL for partial exit
        """
        # For partial exit, PnL = (exit_price - avg_entry_price) * exited_contracts - fees
        # Use the fill's proceeds if available, otherwise calculate from prices
        if fill.action == "sell" and fill.proceeds_dollars is not None:
            # Proceeds already account for price and quantity
            exit_proceeds = fill.proceeds_dollars
            # Calculate cost basis for exited portion
            avg_entry_price = position["avg_price_cents"] / 100.0
            exit_cost = avg_entry_price * exited_contracts
            exit_fees = fill.fee_cost if fill.fee_cost else Decimal("0")
            return exit_proceeds - exit_cost - exit_fees
        elif fill.action == "buy":
            # Adding to position, no PnL realization
            return Decimal("0")
        else:
            # Fallback calculation
            exit_price_cents = fill.price_cents
            avg_entry_price_cents = position["avg_price_cents"]
            price_diff_cents = exit_price_cents - avg_entry_price_cents
            pnl_cents = price_diff_cents * exited_contracts
            pnl_usd = Decimal(pnl_cents) / Decimal("100")
            # Subtract fees
            exit_fees = fill.fee_cost if fill.fee_cost else Decimal("0")
            return pnl_usd - exit_fees
    
    def _recompute_unrealized_pnl(self) -> Decimal:
        """Recompute unrealized PnL from all open positions.
        
        Returns:
            Total unrealized PnL in USD
        """
        total = Decimal("0")
        
        # Try to get current market prices from KalshiPositionCache
        try:
            from merid.event_venues.kalshi.position_cache import get_kalshi_position_cache
            position_cache = get_kalshi_position_cache()
        except Exception:
            position_cache = None
        
        for position in self._open_positions.values():
            contracts = position["total_contracts"]
            if contracts == 0:
                continue
            
            avg_entry_price_cents = position["avg_price_cents"]
            
            # Try to get current market price
            current_price_cents = avg_entry_price_cents  # Default to entry price if no current price
            
            if position_cache:
                try:
                    # Get current price from position cache
                    current_state = position_cache.get(position["market_ticker"])
                    if current_state and hasattr(current_state, "last_yes_price"):
                        if position["side"] == "yes":
                            current_price_cents = int(current_state.last_yes_price * 100)
                        else:
                            current_price_cents = int(current_state.last_no_price * 100)
                except Exception:
                    pass
            
            # Calculate unrealized PnL = (current_price - avg_entry_price) * contracts
            # CRITICAL FIX (2026-07-16): SIDE-SPACE semantics - both YES and NO are long their own side
            # PnL = (own-side current price - own-side entry price) * contracts
            # This matches the side-space convention used in position.py and position_cache.py
            price_diff_cents = current_price_cents - avg_entry_price_cents
            unrealized_cents = price_diff_cents * contracts
            unrealized_usd = Decimal(unrealized_cents) / Decimal("100")
            total += unrealized_usd
        
        return total
    
    def on_market_settlement(self, market_ticker: str, outcome: str) -> None:
        """Handle market settlement event for open positions.
        
        Args:
            market_ticker: Market ticker that settled
            outcome: Settlement outcome ("yes" or "no")
        """
        # Find all open positions for this market
        positions_to_close = []
        for instrument_key, position in list(self._open_positions.items()):
            if position["market_ticker"] == market_ticker:
                positions_to_close.append((instrument_key, position))
        
        if not positions_to_close:
            return
        
        logger.info(
            "Market settlement: %s outcome=%s closing %d positions",
            market_ticker, outcome, len(positions_to_close)
        )
        
        # Close each position and realize PnL based on outcome
        for instrument_key, position in positions_to_close:
            # Calculate settlement PnL based on outcome
            settlement_pnl = self._compute_settlement_pnl(position, outcome)
            
            self._session_realized_pnl += settlement_pnl
            self._update_cumulative_realized_pnl(settlement_pnl)
            
            del self._open_positions[instrument_key]
            
            logger.info(
                "Position settled: %s outcome=%s pnl=%s session_realized=%s cumulative_realized=%s",
                instrument_key, outcome, settlement_pnl, self._session_realized_pnl, self._cumulative_realized_pnl
            )
        
        # Recompute unrealized PnL
        self._session_unrealized_pnl = self._recompute_unrealized_pnl()
        
        # Persist state
        self._persist_session_metadata(self._get_current_session_date())
    
    def _compute_settlement_pnl(self, position: Dict[str, Any], outcome: str) -> Decimal:
        """Compute PnL from market settlement.
        
        Args:
            position: Position state
            outcome: Settlement outcome ("yes" or "no")
            
        Returns:
            Realized PnL from settlement
        """
        # For Kalshi binary options:
        # YES contracts pay $1 if YES wins, $0 if NO wins
        # NO contracts pay $1 if NO wins, $0 if YES wins
        # Settlement PnL = (payout - cost_basis) - fees
        
        contracts = position["total_contracts"]
        avg_entry_price_cents = position["avg_price_cents"]
        fees_cents = position["fees_cents"]
        
        if contracts == 0:
            return Decimal("0")
        
        # Determine payout based on outcome and side
        if position["side"] == "yes":
            payout_per_contract = 1.0 if outcome == "yes" else 0.0
        else:  # side == "no"
            payout_per_contract = 1.0 if outcome == "no" else 0.0
        
        total_payout = payout_per_contract * contracts
        cost_basis = (avg_entry_price_cents * contracts) / 100.0
        fees = fees_cents / 100.0
        
        settlement_pnl = total_payout - cost_basis - fees
        return Decimal(str(settlement_pnl))
    
    def on_market_price_update(self, market_ticker: str, last_price_cents: int) -> None:
        """Handle market price update for unrealized PnL recompute.
        
        Args:
            market_ticker: Market ticker
            last_price_cents: Last price in cents
        """
        # Check if any open positions for this market
        updated = False
        for instrument_key, position in list(self._open_positions.items()):
            if position["market_ticker"] == market_ticker:
                # Mark position to market with new price
                # Placeholder: would update position's mark-to-market value
                updated = True
        
        if updated:
            self._session_unrealized_pnl = self._recompute_unrealized_pnl()
            self._persist_session_metadata(self._get_current_session_date())
            logger.debug(
                "Market price update: %s price=%dc unrealized_pnl=%s",
                market_ticker, last_price_cents, self._session_unrealized_pnl
            )
    
    async def clear_open_positions_on_empty_cache(self) -> None:
        """Clear open positions when position cache shows no open positions.
        
        CRITICAL FIX (2026-07-13): This prevents phantom positions from old fills
        being reported when the actual system has no open positions. Called when
        position cache sync returns zero open positions but fills ledger still has
        _open_positions state from previous sessions.
        
        THREAD-SAFETY FIX (2026-07-13): Made async with mutex protection to prevent
        race conditions with concurrent on_fill() calls that also modify _open_positions.
        """
        # Ensure mutex is initialized
        if self._mutex is None:
            import asyncio
            self._mutex = asyncio.Lock()
        
        async with self._mutex:
            if not self._open_positions:
                return  # Nothing to clear
            
            count = len(self._open_positions)
            self._open_positions = {}
            logger.warning(
                "[FILLS-LEDGER] Cleared %d phantom open positions (position cache shows zero open positions)",
                count
            )
    
    def rebuild_session_pnl_from_fills(self) -> None:
        """Rebuild session PnL from historical fills after restart.
        
        This is called on system startup to reconcile session state with fill history.
        """
        if self._last_session_start_date is None:
            logger.debug("No prior session date, skipping rebuild")
            return
        
        # Load fills since last session start
        from datetime import datetime, timezone, timedelta
        session_start_dt = datetime.fromisoformat(f"{self._last_session_start_date}T00:00:00+00:00")
        
        fills = self.get_fills(since=session_start_dt)
        fills_sorted = sorted(fills, key=lambda f: f.created_time)
        
        logger.info(
            "Rebuilding session PnL from %d fills since %s",
            len(fills_sorted), self._last_session_start_date
        )
        
        # Reset session state (but keep cumulative_realized_pnl)
        self._session_realized_pnl = Decimal("0")
        self._session_unrealized_pnl = Decimal("0")
        self._open_positions = {}
        self._processed_fill_ids = set()
        
        # Replay fills in chronological order
        for fill in fills_sorted:
            if fill.fill_id not in self._processed_fill_ids:
                self.on_fill(fill)
        
        logger.info(
            "Session PnL rebuilt: session_realized=%s session_unrealized=%s cumulative_realized=%s",
            self._session_realized_pnl, self._session_unrealized_pnl, self._cumulative_realized_pnl
        )
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for the fills ledger - consumed by health endpoints.
        
        Returns health status including:
        - circuit_breaker state
        - DLQ status
        - persistence health
        - event loop impact indicators
        """
        try:
            dlq_status = await self.get_dlq_status()
        except Exception as e:
            dlq_status = {"error": str(e)}
        
        # Check if writer task is running
        writer_healthy = (
            self._writer_task is not None 
            and not self._writer_task.done()
            and not self._writer_task.cancelled()
        )
        
        # Determine overall status
        if self._circuit_open:
            status = "degraded"
            message = f"Circuit breaker open: {self._circuit_reason}"
        elif dlq_status.get("pending_by_category", {}).get("schema_permanent", 0) > 0:
            status = "degraded"
            message = "Schema errors in DLQ - migration may be needed"
        elif not writer_healthy and self._fills:
            status = "degraded"
            message = "Writer task not running but fills pending"
        else:
            status = "healthy"
            message = "Fills ledger operating normally"
        
        return {
            "status": status,
            "message": message,
            "circuit_breaker": {
                "open": self._circuit_open,
                "reason": self._circuit_reason,
                "opened_at": self._circuit_opened_at.isoformat() if self._circuit_opened_at else None,
                "error_count_60s": self._schema_error_count,
            },
            "dlq": {
                "pending_total": sum(dlq_status.get("pending_by_category", {}).values()),
                "by_category": dlq_status.get("pending_by_category", {}),
                "replayed": dlq_status.get("replayed_count", 0),
                "buffered": dlq_status.get("buffered_count", 0),
            },
            "persistence": {
                "writer_healthy": writer_healthy,
                "db_initialized": self._db_initialized,
                "fills_in_memory": len(self._fills),
                "fills_dropped": self._fills_dropped_count,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # OPERATOR MANUAL INTERVENTION — Position Management
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def mark_position_closed(
        self, 
        ticker: str, 
        reason: str = "manual_operator_close",
        closed_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Mark a position as manually closed by operator.
        
        This is for when positions are closed outside the system (e.g., via Kalshi website)
        and need to be manually reconciled. Adds a synthetic "close" fill to zero out
        the computed position.
        
        Args:
            ticker: Market ticker to close (e.g., "KXFED-27APR-T3.25")
            reason: Why the position is being marked closed
            closed_at: When the close occurred (default: now)
            
        Returns:
            Result dict with status and position before/after
        """
        mutex = self._ensure_mutex()
        async with mutex:
            ticker = ticker.upper()
            closed_at = closed_at or datetime.now(timezone.utc)
            
            # Compute current position from fills
            current_pos = self.compute_position_from_fills(ticker)
            if not current_pos or current_pos.get("contracts", 0) == 0:
                return {
                    "status": "no_position",
                    "ticker": ticker,
                    "message": f"No open position found for {ticker}",
                }
            
            contracts = current_pos.get("contracts", 0)
            # PRODUCTION-FIX: Try to get avg_price_cents from market state for manual close
            avg_price_cents = current_pos.get("avg_price_cents")
            if avg_price_cents is None:
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    state = get_kalshi_market_state_store().get_unified(ticker)
                    if state and state.mid_cents > 0:
                        avg_price_cents = state.mid_cents
                except Exception as _exc:
                    logger.debug("[FILLS_LEDGER] failed to fetch market state for %s, using 50c fallback: %s", ticker, _exc)
            avg_price_cents = avg_price_cents or 50
            
            # Create synthetic "close" fill to zero out the position
            # This is the OPPOSITE action of the position (if long, create sell)
            close_action = "sell" if contracts > 0 else "buy"
            close_count = abs(contracts)
            
            synthetic_fill = KalshiFill(
                fill_id=f"manual_close_{ticker}_{int(closed_at.timestamp())}",
                market_ticker=ticker,
                side=current_pos.get("side", "yes"),
                action=close_action,
                count_fp=close_count,
                yes_price_dollars=Decimal(str(avg_price_cents / 100)) if current_pos.get("side") == "yes" else None,
                no_price_dollars=Decimal(str(avg_price_cents / 100)) if current_pos.get("side") == "no" else None,
                fee_cost=Decimal("0"),  # No fee for manual reconciliation
                created_time=closed_at,
                ingestion_source="manual_operator_close",
                derived_id=True,  # Mark as synthetic
                is_live=False,  # Not a real trade
            )
            
            # Add the synthetic fill
            self._fills[synthetic_fill.fill_id] = synthetic_fill
            self._index_fill(synthetic_fill)
            
            logger.warning(
                f"MANUAL_POSITION_CLOSE: {ticker} closed via operator. "
                f"Contracts: {contracts} -> 0. Reason: {reason}. "
                f"Synthetic fill ID: {synthetic_fill.fill_id}"
            )
            
            # Persist the change
            await self._persist()
            
            return {
                "status": "closed",
                "ticker": ticker,
                "previous_contracts": contracts,
                "previous_side": current_pos.get("side"),
                "reason": reason,
                "synthetic_fill_id": synthetic_fill.fill_id,
                "closed_at": closed_at.isoformat(),
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # REST vs WS RECONCILIATION — "No Surprises" Integration
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def reconcile_ws_vs_rest(
        self,
        rest_fills: List[Dict[str, Any]],
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Reconcile WebSocket fills against REST API fills.
        
        This is the 5-minute periodic reconciliation check that ensures
        no fills are lost between WS (real-time) and REST (authoritative).
        
        Args:
            rest_fills: List of fills from REST /portfolio/fills endpoint
            since: Optional time window for reconciliation
            
        Returns:
            Reconciliation report with mismatches and actions taken
            
        Log Line (on mismatch):
            [RECON_MISMATCH] ws_fills=47 rest_fills=52 missing=5 tickers=KXBTC...,KXETH...
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        # Get WS fills from our ledger within the window
        ws_fill_ids = set()
        ws_fills_by_ticker: Dict[str, List[str]] = {}
        
        for fill_id, fill in self._fills.items():
            if fill.created_time >= since:
                ws_fill_ids.add(fill_id)
                ticker = fill.market_ticker or "unknown"
                if ticker not in ws_fills_by_ticker:
                    ws_fills_by_ticker[ticker] = []
                ws_fills_by_ticker[ticker].append(fill_id)
        
        # Get REST fill IDs
        rest_fill_ids = set()
        rest_only_fills: List[Dict[str, Any]] = []
        
        for raw in rest_fills:
            fill_id = raw.get("fill_id") or raw.get("trade_id") or raw.get("id")
            if fill_id:
                rest_fill_ids.add(fill_id)
                if fill_id not in ws_fill_ids:
                    rest_only_fills.append(raw)
        
        # Calculate mismatches
        ws_only = ws_fill_ids - rest_fill_ids  # In WS but not REST (should be empty)
        rest_only = rest_fill_ids - ws_fill_ids  # In REST but not WS (need backfill)
        
        result = {
            "ws_count": len(ws_fill_ids),
            "rest_count": len(rest_fill_ids),
            "ws_only_count": len(ws_only),
            "rest_only_count": len(rest_only),
            "rest_only_fills": rest_only_fills,  # For backfill
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Alert on significant mismatches
        if len(rest_only) > 3 or len(ws_only) > 3:
            affected_tickers = set()
            for fill_id in rest_only:
                # Find ticker for missing fill
                for raw in rest_fills:
                    fid = raw.get("fill_id") or raw.get("trade_id") or raw.get("id")
                    if fid == fill_id:
                        ticker = raw.get("market_ticker") or raw.get("ticker") or "unknown"
                        affected_tickers.add(ticker)
                        break
            
            logger.error(
                "[RECON_MISMATCH] ws_fills=%d rest_fills=%d ws_only=%d rest_only=%d tickers=%s",
                len(ws_fill_ids),
                len(rest_fill_ids),
                len(ws_only),
                len(rest_only),
                ",".join(sorted(affected_tickers)) if affected_tickers else "none"
            )
        
        return result
    
    async def reconcile_pnl_vs_portfolio(
        self,
        kalshi_portfolio_pnl: float,
        tolerance_usd: float = 1.0,
    ) -> Dict[str, Any]:
        """Reconcile our computed PnL against Kalshi's portfolio endpoint.
        
        This is the daily/periodic PnL invariant check that ensures our
        fills-based PnL calculation matches Kalshi's authoritative PnL.
        
        Args:
            kalshi_portfolio_pnl: PnL from Kalshi /portfolio endpoint (USD)
            tolerance_usd: Max allowed difference (default $1.00 for rounding)
            
        Returns:
            Reconciliation result with matched/mismatched status
            
        Log Line (on mismatch):
            [PNL_RECON_ERROR] ledger_pnl=1234.56 kalshi_pnl=1230.00 diff=4.56 tolerance=1.00
        """
        # Get our computed PnL
        pnl_summary = self.get_pnl_summary()
        ledger_pnl = float(pnl_summary.get("total_realized_pnl_usd", 0))
        
        diff = abs(ledger_pnl - kalshi_portfolio_pnl)
        matched = diff <= tolerance_usd
        
        result = {
            "ledger_pnl": ledger_pnl,
            "kalshi_pnl": kalshi_portfolio_pnl,
            "diff": diff,
            "tolerance": tolerance_usd,
            "matched": matched,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        if not matched:
            logger.error(
                "[PNL_RECON_ERROR] ledger_pnl=%.2f kalshi_pnl=%.2f diff=%.2f tolerance=%.2f",
                ledger_pnl, kalshi_portfolio_pnl, diff, tolerance_usd
            )
        else:
            logger.debug(
                "[PNL_RECON_OK] ledger_pnl=%.2f kalshi_pnl=%.2f diff=%.2f (within tolerance)",
                ledger_pnl, kalshi_portfolio_pnl, diff
            )
        
        return result
    
    # ── Private methods ─────────────────────────────────────────────────────
    
    def _parse_fill(self, raw: Dict[str, Any], source: str) -> KalshiFill:
        """Parse raw fill dict from Kalshi into KalshiFill model."""
        # Handle both HTTP and WS formats
        fill_id = raw.get("fill_id") or raw.get("trade_id") or raw.get("id")
        derived_id_flag = False
        if not fill_id:
            # Generate deterministic ID from content for safety
            fill_id = f"derived_{int(hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:8], 16)}"
            derived_id_flag = True
            # BUG-FIX: Removed nested 'import os' - os is already imported at module level
            strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"
            
            # Log at DEBUG for non-strict, WARNING for strict - and throttle to every 100th
            ticker = raw.get("market_ticker") or raw.get("ticker")
            if not ticker:
                # Critical: fill without market identifier - always log this
                logger.warning(f"Fill missing BOTH ID and ticker from source='{source}' - potential data integrity issue")
            
            # Use periodic logging to avoid spam (log every 100th derived fill)
            self._derived_fill_counter = getattr(self, '_derived_fill_counter', 0) + 1
            if self._derived_fill_counter % 100 == 1:
                log_fn = logger.warning if strict_mode else logger.debug
                log_fn(f"Fill missing ID from source='{source}', derived: {fill_id} (ticker={ticker}, action={raw.get('action')}) [showing 1/100]")
        
        # Parse timestamp
        ts_str = raw.get("created_time") or raw.get("created_at") or raw.get("timestamp")
        created_time = datetime.now(timezone.utc)
        if ts_str:
            try:
                if isinstance(ts_str, numbers.Real) and not isinstance(ts_str, bool):
                    created_time = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
                elif isinstance(ts_str, str):
                    created_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.debug(f"Timestamp parse failed: {e}")
        
        # Parse price - handle both cents and dollars
        # NEW API FORMAT: yes_price_dollars, no_price_dollars (strings) - these are in dollars already
        yes_price = raw.get("yes_price_dollars") or raw.get("yes_price")
        no_price = raw.get("no_price_dollars") or raw.get("no_price")
        price = raw.get("price")
        
        def normalize_price(p) -> Optional[Decimal]:
            if p is None:
                return None
            try:
                p = float(p)
                # NEW API FORMAT: yes_price_dollars and no_price_dollars are already in dollars (0.0-1.0)
                # OLD API FORMAT: yes_price and no_price are in cents (0-99)
                # Check if the value looks like dollars (< 1.0) or cents (> 1.0)
                if p < 1.0:
                    # Already in dollars (new API format)
                    return Decimal(str(p))
                elif p >= 1.0 and p <= 100:
                    # In cents (old API format) - convert to dollars
                    return Decimal(str(p / 100.0))
                else:
                    # > 100, assume cents and convert
                    return Decimal(str(p / 100.0))
            except Exception:
                return None
        
        yes_price_dollars = normalize_price(yes_price) if yes_price else None
        no_price_dollars = normalize_price(no_price) if no_price else None
        
        # CRITICAL FIX: Kalshi quotes everything from YES side - do NOT trust raw.get("side")
        # Kalshi's "side" field always reports "yes" because they quote from YES side perspective
        # We must derive the correct side from the original intent using client_order_id
        client_order_id = raw.get("client_order_id")
        derived_side = raw.get("side", "yes")  # Fallback to Kalshi's reported side
        
        if client_order_id and client_order_id in self._intents:
            intent = self._intents[client_order_id]
            if intent and intent.side:
                # Extract side from Kalshi-formatted intent.side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
                if "YES" in intent.side:
                    derived_side = "yes"
                elif "NO" in intent.side:
                    derived_side = "no"
                else:
                    # Fallback to intent.side if not in Kalshi format
                    derived_side = intent.side.lower() if intent.side else derived_side
                logger.debug(
                    "[HTTP-FILL-SIDE-FIX] fill_id=%s client_order_id=%s | "
                    "Kalshi reported side=%s | Derived from intent.side=%s -> %s",
                    fill_id, client_order_id, raw.get("side", ""), intent.side, derived_side
                )
        
        # If we only have generic price, assign to side
        if price and not yes_price_dollars and not no_price_dollars:
            if derived_side == "yes":
                yes_price_dollars = normalize_price(price)
            else:
                no_price_dollars = normalize_price(price)
        
        # Parse fee
        fee = raw.get("fee") or raw.get("fee_cost") or raw.get("fee_paid") or 0
        try:
            fee_decimal = Decimal(str(fee))
            if fee_decimal > 1:  # Assume cents
                fee_decimal = fee_decimal / 100
        except Exception:
            fee_decimal = Decimal("0")
        
        # Resolve action: explicit "buy"/"sell" wins; taker_action is fallback.
        # CRITICAL FIX: Kalshi WS fill messages have action nested in "msg" field
        # Format: {"type": "fill", "msg": {"action": "buy", ...}}
        # Extract from "msg" first, then top-level, then taker_action
        _raw_act = (raw.get("msg", {}).get("action", "") if isinstance(raw.get("msg"), dict) else "") or \
                   raw.get("action") or raw.get("taker_action") or ""
        _action = _raw_act if _raw_act in ("buy", "sell") else ""
        
        # FIX: Parse count with explicit None check (not 'or' which treats 0 as falsy)
        # Kalshi API uses various field names across endpoints
        # NEW API FORMAT: count_fp (string), yes_price_dollars (string), no_price_dollars (string)
        _count_raw = raw.get("count_fp")  # Check new format first
        if _count_raw is None:
            _count_raw = raw.get("count")
        if _count_raw is None:
            _count_raw = raw.get("contracts")
        if _count_raw is None:
            _count_raw = raw.get("size")
        if _count_raw is None:
            _count_raw = raw.get("filled_count")
        if _count_raw is None:
            _count_raw = raw.get("quantity")
        if _count_raw is None:
            _count_raw = raw.get("amount")
        _count_fp = int(float(_count_raw)) if _count_raw is not None else 0
        
        if not _action:
            from merid.event_venues.kalshi.kalshi_ledger_metrics import inc_fills_missing_action as _inct
            _inct()
            # HTTP source with positive count: default to "buy" rather than storing invalid.
            if source != "websocket" and _count_fp > 0:
                _action = "buy"
            elif source == "websocket" and _count_fp > 0:
                # CRITICAL FIX: WebSocket fills often arrive without action field.
                # Previous bug: Inferred action from position (if position exists -> sell). This caused
                # BUY fills to be misclassified as SELL when adding to existing positions.
                # New fix: Use price heuristic from _infer_kalshi_trade_action to determine actual action.
                # Price > 0.5 likely indicates BUY (paying more for YES), price < 0.5 likely indicates SELL.
                ticker = (raw.get("market_ticker") or raw.get("ticker") or "").upper()
                price_dollars = yes_price_dollars if yes_price_dollars is not None else no_price_dollars
                if price_dollars is not None:
                    from merid.event_venues.kalshi.ws import _infer_kalshi_trade_action
                    _action = _infer_kalshi_trade_action(raw, price_dollars)
                    logger.debug(f"WS fill {fill_id} for {ticker}: inferred action='{_action}' from price={price_dollars:.2f}")
                else:
                    # No price available, default to buy (safer for accounting)
                    _action = "buy"
                    logger.debug(f"WS fill {fill_id} for {ticker}: inferred action='buy' (no price available, defaulting to buy)")
            else:
                # P2 Task 10: Zero-count fills (settlements, cancels, info events)
                # MUST still get a non-empty action so downstream PnL aggregation
                # (compute_position_from_fills, _compute_yes_no_contracts) does not
                # silently misclassify them. Use "settle" as a sentinel — these
                # fills are not buys or sells; they should be skipped by accounting
                # paths that filter on action in ("buy", "sell").
                _action = "settle"

        # Calculate proceeds_dollars (net cash flow after fees)
        # Buy: negative (money out), Sell: positive (money in)
        proceeds = Decimal("0")
        if yes_price_dollars is not None and _count_fp > 0:
            if _action == "buy":
                proceeds = -(yes_price_dollars * _count_fp) - fee_decimal
            else:  # sell
                proceeds = (yes_price_dollars * _count_fp) - fee_decimal
        elif no_price_dollars is not None and _count_fp > 0:
            if _action == "buy":
                proceeds = -(no_price_dollars * _count_fp) - fee_decimal
            else:  # sell
                proceeds = (no_price_dollars * _count_fp) - fee_decimal

        # Determine if this is a LIVE trade (real money)
        # This is critical for bankroll reconciliation
        # CRITICAL FIX (2026-07-15): Use VenueGate as canonical source of truth for Kalshi venue mode
        # Previously used trading.trade_mode which is a different enum than merid.prediction.trading_mode
        try:
            from merid.prediction.venue_gate import get_venue_gate
            from merid.prediction.trading_mode import TradingMode
            gate = get_venue_gate()
            is_live_trade = (gate.mode == TradingMode.LIVE)
        except Exception:
            # Fallback: check env var directly
            is_live_trade = os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live" and \
                           os.getenv("MERID_ALLOW_LIVE_TRADES", "").lower() in ("1", "true")
        
        # LIVE SAFETY: In strict mode, live trades MUST have real Kalshi fill IDs
        strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"
        if is_live_trade and derived_id_flag and strict_mode:
            # This should never happen in production - log CRITICAL
            logger.critical(
                f"LIVE TRADE WITH DERIVED ID DETECTED: fill_id={fill_id} ticker={raw.get('market_ticker')} "
                f"source={source} - This indicates a serious data integrity issue!"
            )
        
        # Extract asset from ticker (BTC, ETH, SOL, XRP, DOGE)
        ticker = (raw.get("market_ticker") or raw.get("ticker") or "").upper()
        asset = None
        if ticker:
            if "KXBTC" in ticker:
                asset = "BTC"
            elif "KXETH" in ticker:
                asset = "ETH"
            elif "KXSOL" in ticker:
                asset = "SOL"
            elif "KXXRP" in ticker:
                asset = "XRP"
            elif "KXDOGE" in ticker:
                asset = "DOGE"
        
        return KalshiFill(
            fill_id=str(fill_id),
            trade_id=raw.get("trade_id"),
            order_id=raw.get("order_id"),
            market_ticker=ticker,
            side=derived_side,  # CRITICAL FIX: Use derived side from intent, not Kalshi's reported side
            action=_action,
            count_fp=_count_fp,
            yes_price_dollars=yes_price_dollars,
            no_price_dollars=no_price_dollars,
            fee_cost=fee_decimal,
            proceeds_dollars=proceeds,
            client_order_id=raw.get("client_order_id"),
            subaccount_number=raw.get("subaccount_number"),
            created_time=created_time,
            idempotency_key=raw.get("idempotency_key"),
            canonical_hash_version=raw.get("canonical_hash_version"),
            hash_preimage=raw.get("hash_preimage"),
            raw_payload=raw if source != "websocket" else None,  # Don't store full WS payload
            ingestion_source=source,
            ingested_at=datetime.now(timezone.utc),
            derived_id=derived_id_flag,  # Track if ID was synthesized
            confirmed_by_rest=(source == "http_poller"),  # HTTP fills are canonical
            decision_trace_id=raw.get("decision_trace_id"),
            is_live=is_live_trade,  # CRITICAL: Track if this was a real money trade
            asset=asset,  # Per-coin slippage tracking
            agent_id=raw.get("agent_id"),  # CRITICAL: Extract agent_id from raw payload
            intent_id=raw.get("intent_id"),  # CRITICAL: Extract intent_id from raw payload
        )
    
    def _index_fill(self, fill: KalshiFill) -> None:
        """Add fill to secondary indexes."""
        # Index by order_id
        if fill.order_id:
            if fill.order_id not in self._fills_by_order:
                self._fills_by_order[fill.order_id] = []
            self._fills_by_order[fill.order_id].append(fill.fill_id)
        
        # Index by market
        if fill.market_ticker:
            if fill.market_ticker not in self._fills_by_market:
                self._fills_by_market[fill.market_ticker] = []
            self._fills_by_market[fill.market_ticker].append(fill.fill_id)
    
    async def _init_db(self) -> None:
        """Initialize SQLite with WAL mode and proper settings.
        
        CRITICAL: This method ALWAYS runs schema migrations, even if _db_initialized
        is True. This ensures that existing databases get new columns added.
        """
        import aiosqlite
        import os
        
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        
        async with aiosqlite.connect(self._db_path) as db:
            # WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute(f"PRAGMA busy_timeout={_FILLS_DB_BUSY_TIMEOUT_MS};")  # From environment
            await db.execute("PRAGMA temp_store=MEMORY;")
            await db.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
            
            # Get current columns BEFORE creating table (to detect if table exists)
            async with db.execute("PRAGMA table_info(kalshi_fills)") as cur:
                existing_cols = {r[1] for r in await cur.fetchall()}
            
            # Create tables (if not exists)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS kalshi_fills (
                    fill_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    order_id TEXT,
                    market_ticker TEXT NOT NULL,
                    side TEXT,
                    action TEXT,
                    count_fp INTEGER,
                    yes_price_dollars REAL,
                    no_price_dollars REAL,
                    fee_cost REAL,
                    proceeds_dollars REAL,
                    client_order_id TEXT,
                    subaccount_number INTEGER,
                    created_time TEXT,
                    ingestion_source TEXT,
                    ingested_at TEXT,
                    agent_id TEXT,
                    intent_id TEXT,
                    reconciled INTEGER DEFAULT 0,
                    raw_payload TEXT,
                    decision_trace_id TEXT,
                    fill_source TEXT,
                    hedge_reason TEXT,
                    hedge_pnl_cents INTEGER DEFAULT 0,
                    related_alpha_fill_id TEXT
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_market ON kalshi_fills(market_ticker)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_order ON kalshi_fills(order_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_time ON kalshi_fills(created_time)
            """)
            
            # NOTE: Indexes referencing fill_source, hedge_reason, related_alpha_fill_id
            # are created AFTER the migrations below to ensure those columns exist on
            # legacy databases. Creating them here would fail with "no such column" on
            # pre-existing tables and abort the entire schema init before migrations run.
            
            # NOTE: idx_fills_proceeds is created AFTER the proceeds_dollars migration below
            
            # CRITICAL: ALWAYS run migrations, regardless of _db_initialized
            # Get updated column list after table creation
            async with db.execute("PRAGMA table_info(kalshi_fills)") as cur:
                _cols = {r[1] for r in await cur.fetchall()}
            
            # Migrate: decision_trace_id for audit (nullable)
            if "decision_trace_id" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding decision_trace_id column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN decision_trace_id TEXT")
                    await db.commit()
                    logger.info("Migration complete: decision_trace_id column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add decision_trace_id column: {migrate_exc}")
            
            # SCHEMA-FIX-001: Migrate proceeds_dollars column (fixes production incident)
            if "proceeds_dollars" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding proceeds_dollars column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN proceeds_dollars REAL")
                    await db.commit()
                    logger.info("Migration complete: proceeds_dollars column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add proceeds_dollars column: {migrate_exc}")
                    # Continue anyway - fills will go to DLQ if writes fail
            
            # Create index on proceeds_dollars AFTER migration ensures column exists
            try:
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fills_proceeds ON kalshi_fills(proceeds_dollars)
                """)
            except Exception as idx_exc:
                logger.warning(f"Could not create idx_fills_proceeds (column may not exist): {idx_exc}")
            
            # SCHEMA-FIX-002: Migrate fill_source column (fixes production incident)
            if "fill_source" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding fill_source column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN fill_source TEXT")
                    await db.commit()
                    logger.info("Migration complete: fill_source column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add fill_source column: {migrate_exc}")
            
            # SCHEMA-FIX-003: Migrate hedge_reason column
            if "hedge_reason" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding hedge_reason column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN hedge_reason TEXT")
                    await db.commit()
                    logger.info("Migration complete: hedge_reason column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add hedge_reason column: {migrate_exc}")
            
            # SCHEMA-FIX-004: Migrate hedge_pnl_cents column
            if "hedge_pnl_cents" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding hedge_pnl_cents column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN hedge_pnl_cents INTEGER DEFAULT 0")
                    await db.commit()
                    logger.info("Migration complete: hedge_pnl_cents column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add hedge_pnl_cents column: {migrate_exc}")
            
            # SCHEMA-FIX-005: Migrate related_alpha_fill_id column
            if "related_alpha_fill_id" not in _cols:
                try:
                    logger.info("Migrating kalshi_fills: adding related_alpha_fill_id column")
                    await db.execute("ALTER TABLE kalshi_fills ADD COLUMN related_alpha_fill_id TEXT")
                    await db.commit()
                    logger.info("Migration complete: related_alpha_fill_id column added")
                except Exception as migrate_exc:
                    logger.error(f"Failed to add related_alpha_fill_id column: {migrate_exc}")
            
            # Now that all columns exist, create indexes that reference them.
            # Each is wrapped individually so a failure on one does not block others.
            for _idx_sql in (
                "CREATE INDEX IF NOT EXISTS idx_fills_source ON kalshi_fills(fill_source) WHERE fill_source IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_fills_hedge_reason ON kalshi_fills(hedge_reason, fill_source) WHERE fill_source = 'hedge'",
                "CREATE INDEX IF NOT EXISTS idx_fills_related_alpha ON kalshi_fills(related_alpha_fill_id) WHERE related_alpha_fill_id IS NOT NULL",
            ):
                try:
                    await db.execute(_idx_sql)
                except Exception as idx_exc:
                    logger.warning(f"Could not create index (post-migration): {idx_exc} | sql={_idx_sql}")
            
            await db.commit()
        
        self._db_initialized = True
        logger.info("SQLite DB initialized with WAL mode and schema migrations complete")
    
    async def _execute_with_retry(self, db, sql: str, params: tuple = (), retries: int = None) -> None:
        """Execute SQL with retry on database locked errors.
        
        DEFENSIVE-FIX-004: Reduced retries from 8 to 3, added error classification.
        Permanent errors (schema mismatch) are never retried.
        """
        if retries is None:
            retries = _FILLS_DB_RETRY_ATTEMPTS
        delay = _FILLS_DB_RETRY_DELAY_INITIAL  # Start with configured delay
        last_error = None
        
        for i in range(retries):
            try:
                await db.execute(sql, params)
                return
            except sqlite3.OperationalError as e:
                last_error = e
                error_str = str(e).lower()
                
                # Classify error
                category, is_permanent = self._classify_error(e)
                
                # Permanent errors: don't retry at all
                if is_permanent:
                    raise
                
                # Only retry on database locked errors
                if "database is locked" not in error_str and "busy" not in error_str:
                    raise
                
                if i < retries - 1:
                    # Use shorter backoff to reduce event-loop blocking
                    logger.debug(f"DB locked, retrying in {delay}s (attempt {i+1}/{retries})")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, _FILLS_DB_RETRY_DELAY_MAX)  # Exponential backoff
            except Exception:
                raise
        
        # All retries exhausted
        raise last_error if last_error else sqlite3.OperationalError("database is locked after retries")
    
    async def _persist(self) -> None:
        """Queue a fill for persistence (single-writer pattern).
        
        Instead of writing directly to DB (which causes lock contention),
        we queue the fill and let the dedicated writer task handle it.
        """
        # Start writer task if not running
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop(), name="fills_writer")
            def _task_done_cb(task: asyncio.Task) -> None:
                if not task.cancelled() and task.exception():
                    logger.error("FillsLedger writer task crashed: %s", task.exception())
            self._writer_task.add_done_callback(_task_done_cb)
        
        # Signal that there's work to do (writer will read from queue)
        # We don't actually queue fills here - the writer reads from _fills dict
        # This is a signal-only pattern to wake the writer
        try:
            self._ensure_persist_queue().put_nowait(None)  # Wake signal
        except asyncio.QueueFull:
            pass  # Writer is already processing
    
    async def _writer_loop(self) -> None:
        """Dedicated writer task that batches and writes to SQLite.
        
        Holds a single persistent connection for the lifetime of the loop
        to avoid lock contention from opening/closing connections per flush.
        """
        logger.info("Fills writer loop started")
        
        import aiosqlite
        
        # FIX 3: CRITICAL - Initialize DB schema BEFORE opening persistent connection
        # This ensures migrations run first, so the persistent connection sees the correct schema
        try:
            await self._init_db()
            logger.info("Database schema initialized before writer connection")
        except Exception as e:
            logger.error(f"Fills writer: failed to initialize DB schema: {e}")
            # Continue anyway - will fail gracefully on first write attempt
        
        _writer_db = None
        try:
            _writer_db = await aiosqlite.connect(self._db_path)
            await _writer_db.execute("PRAGMA journal_mode=WAL;")
            await _writer_db.execute(f"PRAGMA busy_timeout={_FILLS_DB_BUSY_TIMEOUT_MS};")  # From environment
            await _writer_db.execute("PRAGMA synchronous=NORMAL;")
            logger.info("Fills writer: persistent DB connection established")
        except ImportError:
            logger.warning("aiosqlite not installed — writer loop running in no-op mode")
        except Exception as e:
            logger.error(f"Fills writer: failed to open DB connection: {e}")
        
        # EVENT-LOOP-FIX-001: Track DLQ flush timing
        import time
        _last_dlq_flush = time.monotonic()
        _dlq_flush_interval = 30.0  # Flush DLQ every 30 seconds
        
        while not self._ensure_shutdown_event().is_set():
            try:
                # Wait for work signal with shorter timeout to reduce event-loop lag
                try:
                    await asyncio.wait_for(
                        self._ensure_persist_queue().get(),
                        timeout=_FILLS_WRITER_QUEUE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # Periodic flush even if no signals - but don't block event loop
                    pass

                # Batch collect any additional signals (with limit to prevent starvation)
                batch_signals = 1
                max_batch_collect = 50  # Limit to prevent event loop blocking
                while batch_signals < max_batch_collect and not self._ensure_persist_queue().empty():
                    try:
                        self._ensure_persist_queue().get_nowait()
                        batch_signals += 1
                    except asyncio.QueueEmpty:
                        break
                    except Exception:
                        break

                # Perform the actual persistence with the persistent connection
                await self._flush_to_db(_writer_db)

                # Periodic DLQ flush (non-blocking)
                now = time.monotonic()
                if now - _last_dlq_flush > _dlq_flush_interval:
                    await self._flush_dlq_buffer()
                    _last_dlq_flush = now

            except asyncio.CancelledError:
                logger.info("Fills writer loop cancelled")
                break
            except Exception as e:
                logger.error(f"Writer loop error: {e}")
                await asyncio.sleep(_FILLS_WRITER_ERROR_SLEEP)
        
        # Final flush on shutdown
        try:
            await self._flush_to_db(_writer_db)
        except Exception as e:
            logger.warning(f"Final flush failed: {e}")
        
        # Close persistent connection
        if _writer_db is not None:
            try:
                await _writer_db.close()
                logger.info("Fills writer: persistent DB connection closed")
            except Exception as e:
                logger.debug(f"DB close failed: {e}")
        
        logger.info("Fills writer loop stopped")
    
    async def _flush_to_db(self, db=None) -> None:
        """Flush current fills to SQLite with snapshot iteration.
        
        Args:
            db: Optional persistent aiosqlite connection from _writer_loop.
                If None, opens a one-shot connection (fallback).
        """
        try:
            import aiosqlite
            
            # Ensure DB is initialized
            if not self._db_initialized:
                await self._init_db()
            
            # Take a SNAPSHOT of fills under lock to avoid "dict changed size during iteration"
            fills_snapshot: List[KalshiFill] = []
            mutex = self._ensure_mutex()
            async with mutex:
                fills_snapshot = list(self._fills.values())
            
            if not fills_snapshot:
                return
            
            async def _do_flush(_db) -> None:
                # Batch upsert using retry logic with circuit breaker and DLQ
                errors_by_category: Dict[str, int] = {}
                
                for fill in fills_snapshot:
                    try:
                        # PRODUCTION FIX (2026-05-18): Skip test fixture fills at write path
                        # This prevents test data from contaminating the database
                        if _is_test_fixture_fill(fill.fill_id):
                            logger.debug(f"Skipping test fixture fill at write path: {fill.fill_id}")
                            continue
                        
                        # Check circuit breaker before attempting write
                        if self._circuit_open:
                            self._fills_dropped_count += 1
                            await self._write_to_dlq(fill, Exception(f"Circuit open: {self._circuit_reason}"), "circuit_open")
                            continue
                        
                        await self._execute_with_retry(_db, """
                            INSERT OR REPLACE INTO kalshi_fills (
                                fill_id, trade_id, order_id, market_ticker, side, action,
                                count_fp, yes_price_dollars, no_price_dollars, fee_cost,
                                proceeds_dollars, client_order_id, subaccount_number, created_time,
                                ingestion_source, ingested_at, agent_id, intent_id,
                                reconciled, raw_payload, decision_trace_id, fill_source,
                                hedge_reason, hedge_pnl_cents, related_alpha_fill_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            fill.fill_id, fill.trade_id, fill.order_id, fill.market_ticker,
                            fill.side, fill.action, fill.count_fp,
                            float(fill.yes_price_dollars) if fill.yes_price_dollars else None,
                            float(fill.no_price_dollars) if fill.no_price_dollars else None,
                            float(fill.fee_cost),
                            float(fill.proceeds_dollars) if fill.proceeds_dollars else None,
                            fill.client_order_id, fill.subaccount_number,
                            fill.created_time.isoformat(),
                            fill.ingestion_source,
                            fill.ingested_at.isoformat(),
                            fill.agent_id, fill.intent_id,
                            1 if fill.reconciled else 0,
                            json.dumps(fill.raw_payload) if fill.raw_payload else None,
                            fill.decision_trace_id,
                            fill.fill_source,
                            fill.hedge_reason,
                            fill.hedge_pnl_cents,
                            fill.related_alpha_fill_id,
                        ))
                    except Exception as e:
                        # Classify error
                        category, is_permanent = self._classify_error(e)
                        errors_by_category[category] = errors_by_category.get(category, 0) + 1
                        
                        # Update circuit breaker
                        if is_permanent:
                            self._check_circuit_breaker(e)
                        
                        # Write to DLQ
                        await self._write_to_dlq(fill, e, category)
                        
                        # Rate-limited logging
                        if is_permanent and self._should_log_schema_error():
                            logger.error(
                                "kalshi_fills schema error (rate-limited): %s | fill_id=%s ticker=%s",
                                e, fill.fill_id, fill.market_ticker
                            )
                        elif not is_permanent:
                            logger.warning(f"Failed to persist fill {fill.fill_id}: {e}")
                        
                        # Continue with other fills - don't let one bad fill break the batch
                
                await _db.commit()
                
                # Aggregate logging for schema errors (once per batch)
                if errors_by_category:
                    for category, count in errors_by_category.items():
                        if category == "schema_permanent" and count > 0:
                            logger.error(
                                "kalshi_fills batch summary: %d permanent errors (schema mismatch) - "
                                "Fills queued to DLQ. Run migration or reset circuit breaker.",
                                count
                            )
            
            if db is not None:
                # Use the persistent writer connection (preferred path)
                await _do_flush(db)
            else:
                # Fallback: open a one-shot connection
                async with aiosqlite.connect(self._db_path) as fallback_db:
                    await fallback_db.execute("PRAGMA journal_mode=WAL;")
                    await fallback_db.execute(f"PRAGMA busy_timeout={_FILLS_DB_BUSY_TIMEOUT_MS};")  # From environment
                    await _do_flush(fallback_db)
                
        except ImportError:
            # aiosqlite not installed — fills survive only in RAM; restart loses them.
            # Log once per process so operators notice on first flush, not every flush.
            if not getattr(self, "_aiosqlite_warned", False):
                self._aiosqlite_warned = True
                logger.warning(
                    "aiosqlite not installed — KalshiFillsLedger running in-memory only. "
                    "Fills will be LOST on process restart. Install aiosqlite to enable persistence."
                )
        except Exception as e:
            logger.warning(f"Failed to persist fills batch: {e}")
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the ledger and flush remaining fills."""
        logger.info("Shutting down KalshiFillsLedger...")
        self._ensure_shutdown_event().set()
        
        # Signal writer to wake and flush
        try:
            await self._ensure_persist_queue().put(None)
        except Exception as e:
            logger.debug(f"Persist queue put failed: {e}")

        # Wait for writer task to complete
        if self._writer_task and not self._writer_task.done():
            try:
                await asyncio.wait_for(self._writer_task, timeout=_FILLS_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Writer task did not complete in time, cancelling")
                self._writer_task.cancel()
                try:
                    await self._writer_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                logger.warning(f"Error waiting for writer task: {e}")
        
        # Final DLQ flush
        try:
            await self._flush_dlq_buffer()
        except Exception as e:
            logger.warning(f"Final DLQ flush failed: {e}")
        
        logger.info("KalshiFillsLedger shutdown complete")

    async def load_from_db(self) -> int:
        """Load fills from SQLite on startup."""
        try:
            import aiosqlite
            
            # Ensure DB is initialized first
            if not self._db_initialized:
                await self._init_db()
            
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(f"PRAGMA busy_timeout={_FILLS_DB_BUSY_TIMEOUT_MS};")  # From environment
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM kalshi_fills ORDER BY created_time DESC LIMIT 10000"
                ) as cursor:
                    rows = await cursor.fetchall()

                skipped_test = 0
                for row in rows:
                    # Skip test fixture fills that leaked into the DB
                    if _is_test_fixture_fill(row["fill_id"]):
                        skipped_test += 1
                        continue
                    raw_payload = None
                    rp = row["raw_payload"] if "raw_payload" in row.keys() else None
                    if rp:
                        try:
                            raw_payload = json.loads(rp) if isinstance(rp, str) else rp
                        except Exception:
                            raw_payload = None
                    dtid = row["decision_trace_id"] if "decision_trace_id" in row.keys() else None
                    if not dtid and raw_payload:
                        dtid = (raw_payload or {}).get("decision_trace_id")
                    # SCHEMA-FIX-002: Handle optional proceeds_dollars for backward compatibility
                    pd_raw = row["proceeds_dollars"] if "proceeds_dollars" in row.keys() else None
                    proceeds_dollars = Decimal(str(pd_raw)) if pd_raw else None
                    
                    fill = KalshiFill(
                        fill_id=row["fill_id"],
                        trade_id=row["trade_id"],
                        order_id=row["order_id"],
                        market_ticker=row["market_ticker"],
                        side=row["side"],
                        action=row["action"],
                        count_fp=row["count_fp"],
                        yes_price_dollars=Decimal(str(row["yes_price_dollars"])) if row["yes_price_dollars"] else None,
                        no_price_dollars=Decimal(str(row["no_price_dollars"])) if row["no_price_dollars"] else None,
                        fee_cost=Decimal(str(row["fee_cost"])) if row["fee_cost"] else Decimal("0"),
                        proceeds_dollars=proceeds_dollars,
                        client_order_id=row["client_order_id"],
                        subaccount_number=row["subaccount_number"],
                        created_time=datetime.fromisoformat(row["created_time"]) if row["created_time"] else datetime.now(timezone.utc),
                        ingestion_source=row["ingestion_source"] or "db_restore",
                        ingested_at=datetime.fromisoformat(row["ingested_at"]) if row["ingested_at"] else datetime.now(timezone.utc),
                        agent_id=row["agent_id"],
                        intent_id=row["intent_id"],
                        reconciled=bool(row["reconciled"]),
                        raw_payload=raw_payload,
                        decision_trace_id=dtid,
                    )
                    self._fills[fill.fill_id] = fill
                    self._index_fill(fill)
                    
                loaded = len(rows) - skipped_test
                if skipped_test:
                    logger.warning(
                        "Filtered %d test-fixture fills from DB (prefixes: %s)",
                        skipped_test, ", ".join(_TEST_FILL_PREFIXES[:3]) + "..."
                    )
                logger.info(f"Loaded {loaded} fills from database")
                
                # Session-based PnL tracking: rebuild session PnL from loaded fills
                self.rebuild_session_pnl_from_fills()
                
                return loaded
        except Exception as e:
            logger.debug(f"No existing fills DB or load error: {e}")
            return 0


# Profile-aware singleton accessor to prevent legacy/production contamination
_ledgers: Dict[str, Optional[KalshiFillsLedger]] = {}
_ledger_lock = threading.Lock()


def get_fills_ledger(profile: Optional[str] = None) -> KalshiFillsLedger:
    """Get the profile-aware singleton KalshiFillsLedger instance.
    
    Args:
        profile: Optional profile name. If None, uses current MERID_PROFILE env var.
                This ensures legacy and production stacks get separate instances.
    
    Returns:
        KalshiFillsLedger instance for the specified profile.
    """
    import os
    if profile is None:
        profile = os.getenv("MERID_PROFILE", "default")
    
    global _ledgers
    if profile not in _ledgers or _ledgers[profile] is None:
        with _ledger_lock:
            # Double-checked: verify ledger is still None inside lock
            if profile not in _ledgers or _ledgers[profile] is None:
                _ledgers[profile] = KalshiFillsLedger()
                # Session-based PnL tracking: load session metadata on first access
                _ledgers[profile]._load_session_metadata()
                # Check if we need to start a new session
                _ledgers[profile].start_new_session()
    return _ledgers[profile]


# Convenience exports
__all__ = [
    "KalshiFill",
    "OrderIntent", 
    "KalshiFillsLedger",
    "get_fills_ledger",
    "ReconciliationStatus",
]
