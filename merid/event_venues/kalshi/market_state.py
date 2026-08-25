"""KalshiMarketStateStore — unified per-market live state.

PRODUCTION INVARIANTS (NON-NEGOTIABLE):
────────────────────────────────────────────────────────────────────────────
These invariants define the canonical behavior for production. Changes require:
  1. Risk committee approval
  2. Staged rollout testing
  3. Updated regression tests

1. DATA FLOW INVARIANTS:
   - Subscribe to `orderbook_delta` and `orderbook_snapshot` on Kalshi WS for depth
   - REST `GET /markets/{ticker}/orderbook` used for bootstrapping and fallback when WS is stale
   - Every traded market MUST be bootstrapped via REST `orderbook_fp` before accepting WS deltas
   - Single source of truth: KalshiMarketStateStore merges WS orderbook and REST snapshots
   - Scope is strictly BTC/ETH/SOL/XRP/DOGE 15m, enforced at:
     * Subscription (ws_bridge.py)
     * Snapshot bootstrap (ws_bridge.py)
     * apply_orderbook_message (market_state.py)
     * Router selection

2. SINGLE SOURCE OF TRUTH:
   - market_state + LocalOrderbook are the ONLY authoritative source of bid/ask/mid
   - UI/API layers MUST read from this state, not invent their own book or call Kalshi directly
   - No duplicate orderbook logic outside this module

3. HEALTH & CIRCUIT BREAKER INVARIANTS:
   - MAX_BOOK_STALENESS_MS = 120000 (120s maximum staleness, from threshold_config)
   - MIN_HEALTHY_BOOKS_FOR_TRADING = 3 (60% quorum for 5 markets)
   - HEALTH_CHECK_INITIALIZED = True (book must have REST snapshot)
   - HEALTH_CHECK_FRESH = True (book must be within staleness threshold)
   - HEALTH_CHECK_BID_ASK = True (book must have valid bid < ask with non-zero sizes)
   - is_trading_enabled() enforces these thresholds
   - Trading disabled if any market unhealthy

4. STARTUP SEQUENCE INVARIANTS:
   - WS-BOOT: bridge started with tickers and channels logged
   - SNAPSHOT-BOOTSTRAP: started markets=N logged
   - SNAPSHOT-BOOTSTRAP: complete market=... levels=... bid=... ask=... mid=... logged
   - Trading only enabled after ALL configured markets have snapshots or marked unsupported
   - [PRODUCTION-INVARIANT] log confirms trading ready state

5. MONITORING INVARIANTS:
   - log_book_health() every 60s logs: initialized, last_update_age_ms, bid/ask/mid/spread
   - /internal/kalshi_health endpoint returns detailed metrics for all markets
   - Circuit breaker logs [HEALTH-CIRCUIT-BREAKER] when trading state changes

OWNERSHIP:
────────────────────────────────────────────────────────────────────────────
Owns the merge point between:
  - WS ``orderbook_snapshot`` / ``orderbook_delta`` messages
  - REST ``GET /markets`` responses

Produces ``KalshiMarketState`` per ticker so every consumer — agents,
order router, UI API — reads a single consistent structure instead of
separate ad-hoc dicts.

Usage::

    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

    store = get_kalshi_market_state_store()

    # WS side (called from your ws bridge/handler):
    store.apply_orderbook_message(ws_msg)

    # REST side (called from your market scanner/A5 check):
    store.apply_rest_market(market_dict)

    # Consumers:
    state = store.get("KXBTCD-25JUN-T100000")
    if state and state.seconds_to_expiry is not None:
        use(state.seconds_to_expiry)
"""

from __future__ import annotations

import os
import random
import threading
import time
import asyncio
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.orderbook import LocalOrderbook, MultiMarketOrderbook
from merid.event_venues.kalshi.unified_market_state import (
    Candlestick,
    ExternalIndexSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
    UnifiedMarketState,
    recompute_derived,
)
from utils.logger import get_logger

# CRITICAL FIX 2026-08-03: Import get_market_catalog at module level for testability
# This allows tests to patch it for cross-validation testing
from merid.event_venues.kalshi.market_catalog import get_market_catalog

# Production scope validation
# DISABLED IN TESTS: Set TRADING_SCOPE_AVAILABLE=False to allow synthetic test tickers
# Production: Set TRADING_SCOPE_AVAILABLE=True to enforce scope validation
import os
TRADING_SCOPE_AVAILABLE = os.getenv("MERID_ENABLE_SCOPE_VALIDATION", "false").lower() in ("true", "1", "yes")
if TRADING_SCOPE_AVAILABLE:
    try:
        from config.trading_scope import (
            validate_series_ticker_for_trading,
            validate_asset_for_trading,
        )
    except ImportError:
        TRADING_SCOPE_AVAILABLE = False

# Import timing-aware SLA functions for unified staleness checking
from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds

# ── Production Invariants: Health Thresholds ─────────────────────────────
# These constants are NON-NEGOTIABLE in production. Changes require:
# 1. Risk committee approval
# 2. Staged rollout testing
# 3. Updated regression tests

# Maximum age of orderbook data before it's considered stale (milliseconds)
# PRODUCTION INVARIANT: 15 seconds is the maximum acceptable staleness for 15m crypto markets
# Rationale: 15m markets update frequently; 15s allows for transient network issues while preventing stale trading
# CRITICAL FIX: Reduced from 30s to 15s for production safety and faster stale detection
# HARDENING-FIX: Now read from threshold_config.py instead of hardcoded literal
from merid.event_venues.kalshi.threshold_config import get_threshold_config
_threshold_config = get_threshold_config()
MAX_BOOK_STALENESS_MS = _threshold_config.get_staleness_thresholds().max_book_staleness_s * 1000  # Convert to ms

# Minimum number of healthy books required to enable trading (quorum)
# PRODUCTION INVARIANT: For 5 crypto 15m markets, require at least 4 to be healthy (80%)
# Rationale: Increased from 60% to 80% for production safety - prevents trading on degraded data
MIN_HEALTHY_BOOKS_FOR_TRADING = 4  # PRODUCTION INVARIANT: 80% quorum for 5 markets

# Health check flags - all must be True in production
# PRODUCTION INVARIANT: All three checks are mandatory for safe trading
HEALTH_CHECK_INITIALIZED = True  # Book must have REST snapshot applied
HEALTH_CHECK_FRESH = True  # Book must have been updated within staleness threshold
HEALTH_CHECK_BID_ASK = True  # Book must have valid bid < ask with non-zero sizes

logger = get_logger("merid.event_venues.kalshi.market_state")

# LagTracker import for spot-to-book lag measurement
try:
    from merid.market_data.lag_tracker import get_lag_tracker
    _lag_tracker_available = True
except ImportError:
    _lag_tracker_available = False
    logger.debug("[MARKET-STATE] LagTracker not available - spot-to-book lag tracking disabled")

# REST fallback staleness threshold - mark markets untradeable if REST data is older than this
_MAX_REST_AGE_SECONDS = int(os.getenv("MERID_KALSHI_MAX_REST_AGE_SECONDS", "10"))  # 10 seconds for 15m markets

# Prometheus metrics for market data staleness (P2 Task 7)
try:
    from prometheus_client import Gauge

    market_data_staleness_seconds = Gauge(
        'merid_market_data_staleness_seconds',
        'Seconds since last market data update per ticker',
        ['asset', 'ticker']
    )

    market_health_status = Gauge(
        'merid_market_health_status',
        'Health status of market data (0=unhealthy, 1=degraded, 2=stale, 3=suspended, 4=healthy)',
        ['asset', 'ticker']
    )

    # Edge/lag ratio metrics for spot-to-book lag tracking
    orderbook_lag_mean_ms = Gauge(
        'merid_orderbook_lag_mean_ms',
        'Mean spot-to-book lag in milliseconds per asset',
        ['asset']
    )

    orderbook_lag_p95_ms = Gauge(
        'merid_orderbook_lag_p95_ms',
        'P95 spot-to-book lag in milliseconds per asset',
        ['asset']
    )

    orderbook_lag_sample_count = Gauge(
        'merid_orderbook_lag_sample_count',
        'Number of lag samples collected per asset',
        ['asset']
    )

    # Liquidity status metrics
    liquidity_ok_pct = Gauge(
        'merid_liquidity_ok_pct',
        'Percentage of time with OK liquidity status per asset',
        ['asset']
    )
except ImportError:
    # Prometheus client not available - metrics will be no-ops
    market_data_staleness_seconds = None
    market_health_status = None
    orderbook_lag_mean_ms = None
    orderbook_lag_p95_ms = None
    orderbook_lag_sample_count = None
    liquidity_ok_pct = None

# Market-level filter: only accept 5 crypto underlyings on 15m timeframe
# Import from centralized config module
from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES as _ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS as _ALLOWED_UNDERLYINGS,
)

# Parse ticker to extract underlying and timeframe
# Format: KXBTC15M-26MAY121130-30 or KXBTC-15M-26MAY121130-30 or KXBTC15M-T (test)
def _parse_market_ticker(ticker: str) -> tuple[str, str]:
    """Extract (underlying, timeframe) from Kalshi ticker.

    Returns:
        (underlying, timeframe) tuple, or (None, None) if unparseable
    """
    if not ticker:
        return None, None

    # Try to match pattern like KXBTC15M-... or KXBTC-15M-...
    # Also handles test tickers like KXBTC15M-T
    import re
    match = re.match(r"^KX([A-Z]+)(?:-?)(\d+[mM])", ticker.upper())
    if match:
        underlying = match.group(1)
        timeframe = match.group(2).upper()
        return underlying, timeframe

    return None, None

# Auto-switch to IOC when market expires within this many seconds
# 15m scalper: configurable threshold (default 120s = 2 min before expiry)
# IOC auto-below threshold for TIF resolution
# CONSOLIDATED: Single source of truth is profile YAML (kalshi_crypto_15m.yaml)
# This env var is DEPRECATED and kept only for backward compatibility
# All TIF resolution code should use profile.venue_invariants_ioc_auto_below_seconds instead
# DEPRECATION: Remove KALSHI_IOC_AUTO_BELOW_SECONDS after profile integration is complete
IOC_AUTO_BELOW_SECONDS = float(os.getenv("KALSHI_IOC_AUTO_BELOW_SECONDS", "120.0"))  # DEPRECATED

_TOP_N_BOOK_LEVELS = 10
_DEPTH_WINDOW_CENTS = 10

# DATA INTEGRITY LAYER CONFIGURATION
_PRIMARY_STALE_SECONDS = float(os.getenv("KALSHI_PRIMARY_STALE_SECONDS", "5.0"))  # Max age for primary (WebSocket) data - relaxed for 15M markets
# CRITICAL FIX 2026-08-03: Reduced REST throttle from 5s to 2s for 15m markets
# 15-minute markets update frequently; faster REST refresh catches stale data before it poisons gates
_REST_THROTTLE_SECONDS = float(os.getenv("KALSHI_REST_THROTTLE_SECONDS", "2.0"))  # Min time between REST calls per market (was 5.0)
_CROSS_VALIDATION_THRESHOLD_CENTS = float(os.getenv("KALSHI_CROSS_VALIDATION_THRESHOLD_CENTS", "5.0"))  # Max allowed difference between primary and REST
_CROSS_VALIDATION_THRESHOLD_PCT = float(os.getenv("KALSHI_CROSS_VALIDATION_THRESHOLD_PCT", "0.10"))  # Max allowed % difference

# Production safeguards
_MAX_QUOTE_TTL_SECONDS = float(os.getenv("KALSHI_MAX_QUOTE_TTL_SECONDS", "15.0"))  # Maximum age for any quote before rejection - relaxed for 15M markets
_MAX_QUOTE_OVERRIDE_AGE_SECONDS = float(os.getenv("KALSHI_MAX_QUOTE_OVERRIDE_AGE_SECONDS", "5.0"))  # Max age for ticker fallback override
_CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("KALSHI_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "10"))  # Consecutive failures before suspension (relaxed for spotty internet)
_CIRCUIT_BREAKER_RECOVERY_SECONDS = float(os.getenv("KALSHI_CIRCUIT_BREAKER_RECOVERY_SECONDS", "300.0"))  # Time before attempting recovery (5 min for spotty internet)
_CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS = float(os.getenv("KALSHI_CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS", "60.0"))  # Maximum backoff for retries

# P0-1 DOWNSTREAM: Maximum age for WS data before refusing to trade
_MAX_WS_AGE_SECONDS = float(os.getenv("KALSHI_MAX_WS_AGE_SECONDS", "30.0"))  # 30s default

# P0-2 UPSTREAM: Duality violation threshold (YES + NO should be ~100c)
_DUALITY_EPSILON_CENTS = float(os.getenv("KALSHI_DUALITY_EPSILON_CENTS", "1.0"))  # 1c tolerance

# ── State recovery attestation constants (2026-08-22) ──────────────────────
# Only these sources are allowed to lift an INVALID or CIRCUIT_BREAKER state
# and mark a market executable again.  Catalog metadata / REST market feeds,
# quote-only fallbacks, or unconfirmed WS snapshots must not silently recover.
_RECOVERY_SOURCES = {"REST_FULL_ORDERBOOK", "WS_ORDERBOOK_DELTA_LIVE", "WS_CLEAN_SNAPSHOT"}

# Bootstrap snapshot sources carry a full book but are not live-sequence
# confirmed.  They can initialize a fresh market, but cannot recover an
# INVALID/CIRCUIT_BREAKER state.
_BOOTSTRAP_SOURCES = {"BOOTSTRAP_VALID_BUT_UNCONFIRMED"}


def _recovery_required_for_transition(transition: Optional[str]) -> str:
    """Return the class of recovery source required for a transition label."""
    if transition == "CIRCUIT_BREAKER":
        return "FULL_SNAPSHOT"
    if transition == "INVALID_SEQUENCE_GAP":
        return "FULL_SNAPSHOT"
    if transition == "INVALID_UNKNOWN_MARKET":
        return "FULL_SNAPSHOT"
    if transition == "INVALID_INVERTED":
        return "LIVE_DELTA"
    return "LIVE_DELTA"


def _source_satisfies_recovery(source: str, required: str) -> bool:
    """Check whether ``source`` satisfies the ``required`` recovery class."""
    if not required:
        return source in _RECOVERY_SOURCES
    if required == "LIVE_DELTA":
        return source == "WS_ORDERBOOK_DELTA_LIVE"
    if required == "FULL_SNAPSHOT":
        return source in {"REST_FULL_ORDERBOOK", "WS_CLEAN_SNAPSHOT"}
    if required == "OPERATOR_RESET":
        return False  # not attested by any data feed
    return source in _RECOVERY_SOURCES

# ── Connection Health Watchdog Configuration ───────────────────────────────
# Separate from data staleness - tracks WS connection health
_WS_HEALTH_WATCHDOG_SECONDS = float(os.getenv("KALSHI_WS_HEALTH_WATCHDOG_SECONDS", "15.0"))  # 15s watchdog for WS health
# If no WS message (heartbeat, ping/pong, or orderbook delta) received within this time, mark connection suspect

# 2026-08-24: Maximum time to wait for a first/reset snapshot before declaring
# a snapshot timeout and actively requesting a fresh one.
_SNAPSHOT_TIMEOUT_SECONDS = float(os.getenv("MERID_KALSHI_SNAPSHOT_TIMEOUT_SECONDS", "10.0"))

# ── Regime-Aware Staleness Thresholds ───────────────────────────────────────
# Based on time-to-expiry and market conditions
_STALENESS_REGIME_RELAXED_SECONDS = float(os.getenv("KALSHI_STALENESS_REGIME_RELAXED_SECONDS", "120.0"))  # 120s far from expiry
_STALENESS_REGIME_NORMAL_SECONDS = float(os.getenv("KALSHI_STALENESS_REGIME_NORMAL_SECONDS", "60.0"))  # 60s normal conditions
_STALENESS_REGIME_STRICT_SECONDS = float(os.getenv("KALSHI_STALENESS_REGIME_STRICT_SECONDS", "10.0"))  # 10s near expiry

# Time-to-expiry thresholds for regime determination
_EXPIRY_STRICT_THRESHOLD_SECONDS = float(os.getenv("KALSHI_EXPIRY_STRICT_THRESHOLD_SECONDS", "60.0"))  # 60s = strict regime
_EXPIRY_RELAXED_THRESHOLD_SECONDS = float(os.getenv("KALSHI_EXPIRY_RELAXED_THRESHOLD_SECONDS", "180.0"))  # 180s = relaxed regime

# ── Lag Classification Thresholds ───────────────────────────────────────────
# Thresholds for rule-based lag classification
_WS_PING_GAP_MULTIPLIER = float(os.getenv("KALSHI_WS_PING_GAP_MULTIPLIER", "3.0"))  # 3x expected interval = connection issue
_WS_PING_GAP_THRESHOLD_SECONDS = 10.0 * _WS_PING_GAP_MULTIPLIER  # 30s default (10s expected interval)
_NETWORK_LATENCY_THRESHOLD_MS = float(os.getenv("KALSHI_NETWORK_LATENCY_THRESHOLD_MS", "200.0"))  # 200ms = elevated network latency
_REST_LATENCY_THRESHOLD_MS = float(os.getenv("KALSHI_REST_LATENCY_THRESHOLD_MS", "500.0"))  # 500ms = elevated REST latency
_REST_USER_TS_LAG_THRESHOLD_S = float(os.getenv("KALSHI_REST_USER_TS_LAG_THRESHOLD_S", "30.0"))  # 30s = exchange API delay
_PROCESSING_LAG_THRESHOLD_MS = float(os.getenv("KALSHI_PROCESSING_LAG_THRESHOLD_MS", "100.0"))  # 100ms = local processing lag


class QuoteHealth(str, Enum):
    """Health state for market quotes."""
    HEALTHY = "healthy"  # Primary feed timely; REST (if checked) agrees within threshold
    DEGRADED = "degraded"  # Using REST because primary missing/stale, but REST shows open & fresh
    STALE = "stale"  # Very old quote, use with caution (added for graduated health levels)
    SUSPENDED = "suspended"  # Conflicting data, closed/paused state, or repeated failures


class BookHealth(str, Enum):
    """Explicit lifecycle state for an orderbook under loss-aware WS processing.

    These states are the canonical source of truth for the book's trustworthiness
    and are designed to make every transition observable in logs.
    """
    NO_SNAPSHOT = "NO_SNAPSHOT"                # No snapshot yet; deltas are pending
    SNAPSHOT_RECEIVED = "SNAPSHOT_RECEIVED"    # Authoritative full book received
    SEQUENCE_VALIDATING = "SEQUENCE_VALIDATING"  # Checking first/next delta sequence
    LIVE = "LIVE"                              # Contiguous deltas confirmed; book trusted
    GAP_DETECTED = "GAP_DETECTED"              # Non-contiguous sequence observed
    INVALID = "INVALID"                        # Book deemed untrusted
    RESYNC_REQUESTED = "RESYNC_REQUESTED"      # Resync scheduled/in-flight
    RECOVERED = "RECOVERED"                    # Clean snapshot or contiguous delta restored trust


def is_book_degenerate(yes_bid_cents: Optional[int], yes_ask_cents: Optional[int],
                      no_bid_cents: Optional[int], no_ask_cents: Optional[int]) -> tuple[bool, str]:
    """
    Detect degenerate orderbook conditions that indicate invalid or corrupted data.

    Based on industry best practices for orderbook validity detection:
    - Check for extreme prices near boundaries (ask >= 98c indicates missing liquidity)
    - Check for one-sided books (only bids or only asks with valid prices)
    - Check for dust-only books (both sides present but at extreme boundary values)

    Args:
        yes_bid_cents: Best bid price for YES contract
        yes_ask_cents: Best ask price for YES contract
        no_bid_cents: Best bid price for NO contract
        no_ask_cents: Best ask price for NO contract

    Returns:
        (is_degenerate, reason) tuple where is_degenerate is True if book is invalid,
        and reason is a string explaining why.
    """
    # Check for extreme boundary prices (indicates missing liquidity)
    if yes_ask_cents is not None and yes_ask_cents >= 98:
        return True, f"yes_ask_near_boundary({yes_ask_cents}c >= 98c)"
    if no_ask_cents is not None and no_ask_cents >= 98:
        return True, f"no_ask_near_boundary({no_ask_cents}c >= 98c)"

    # Check for one-sided books (only one side has valid prices)
    yes_side_valid = yes_bid_cents is not None and yes_ask_cents is not None and 0 < yes_bid_cents < 100 and 0 < yes_ask_cents < 100
    no_side_valid = no_bid_cents is not None and no_ask_cents is not None and 0 < no_bid_cents < 100 and 0 < no_ask_cents < 100

    if yes_side_valid and not no_side_valid:
        return True, "one_sided_book(only_yes_valid)"
    if no_side_valid and not yes_side_valid:
        return True, "one_sided_book(only_no_valid)"

    # Check for dust-only books (both sides at extreme boundaries)
    if yes_side_valid and no_side_valid:
        # If YES bid is very low and NO bid is very low, likely dust-only
        if yes_bid_cents <= 2 and no_bid_cents <= 2:
            return True, f"dust_only_book(yes_bid={yes_bid_cents}c, no_bid={no_bid_cents}c <= 2c)"

    return False, ""


def cross_validate_with_catalog(ticker: str, yes_bid_cents: Optional[int], yes_ask_cents: Optional[int],
                                 no_bid_cents: Optional[int], no_ask_cents: Optional[int]) -> tuple[bool, str]:
    """
    Cross-validate stored orderbook against Kalshi catalog ticker quotes.

    This provides an independent data source check to detect corrupted local state.
    The catalog provides the canonical best bid/ask from Kalshi's REST API.

    Args:
        ticker: Market ticker to validate
        yes_bid_cents: Local YES bid price
        yes_ask_cents: Local YES ask price
        no_bid_cents: Local NO bid price
        no_ask_cents: Local NO ask price

    Returns:
        (is_valid, reason) tuple where is_valid is False if catalog cross-check fails,
        and reason is a string explaining the discrepancy.
    """
    try:
        catalog = get_market_catalog()
        if not catalog:
            return True, "catalog_unavailable"  # Can't validate, assume OK

        # Extract asset from ticker (e.g., KXBTC15M-... -> BTC)
        import re
        match = re.match(r"^KX([A-Z]+)", ticker.upper())
        if not match:
            return True, "unparseable_ticker"
        asset = match.group(1)

        # Get current 15m market from catalog
        current_market = catalog.get_current_15m_market(asset)
        if not current_market:
            return True, "no_catalog_market"

        # Get ticker quotes from catalog
        market_data = current_market.market.raw_data or {}
        catalog_yes_bid = market_data.get("yes_bid")
        catalog_yes_ask = market_data.get("yes_ask")
        catalog_no_bid = market_data.get("no_bid")
        catalog_no_ask = market_data.get("no_ask")

        # Cross-validation threshold (in cents)
        # Allow 5c difference due to latency between catalog refresh and local updates
        CROSS_VALIDATION_THRESHOLD_CENTS = 5

        # Compare YES bid
        if yes_bid_cents is not None and catalog_yes_bid is not None:
            if abs(yes_bid_cents - catalog_yes_bid) > CROSS_VALIDATION_THRESHOLD_CENTS:
                return False, f"yes_bid_mismatch(local={yes_bid_cents}c, catalog={catalog_yes_bid}c)"

        # Compare YES ask
        if yes_ask_cents is not None and catalog_yes_ask is not None:
            if abs(yes_ask_cents - catalog_yes_ask) > CROSS_VALIDATION_THRESHOLD_CENTS:
                return False, f"yes_ask_mismatch(local={yes_ask_cents}c, catalog={catalog_yes_ask}c)"

        # Compare NO bid
        if no_bid_cents is not None and catalog_no_bid is not None:
            if abs(no_bid_cents - catalog_no_bid) > CROSS_VALIDATION_THRESHOLD_CENTS:
                return False, f"no_bid_mismatch(local={no_bid_cents}c, catalog={catalog_no_bid}c)"

        # Compare NO ask
        if no_ask_cents is not None and catalog_no_ask is not None:
            if abs(no_ask_cents - catalog_no_ask) > CROSS_VALIDATION_THRESHOLD_CENTS:
                return False, f"no_ask_mismatch(local={no_ask_cents}c, catalog={catalog_no_ask}c)"

        return True, "catalog_match"

    except Exception as e:
        logger.warning(f"[CATALOG-CROSS-VALIDATION] Exception during cross-validation for {ticker}: {e}")
        return True, "catalog_validation_error"  # Don't fail on catalog errors


class QuoteSource(str, Enum):
    """Source of market quote data."""
    WEBSOCKET = "websocket"
    FIX = "fix"
    REST = "rest"
    COMPOSITE = "composite"  # Verified by cross-checking primary vs REST


class LiquidityStatus(str, Enum):
    """Liquidity status classification for market data."""
    MISSING = "MISSING"  # No state at all
    STALE = "STALE"  # State present but too old
    ONE_SIDED = "ONE_SIDED"  # State present but only bid or ask
    DEPTH_TOO_LOW = "DEPTH_TOO_LOW"  # Two-sided but insufficient depth
    UNAVAILABLE = "UNAVAILABLE"  # API failure, timeout, or network issue (not the same as MISSING)
    OK = "OK"  # Two-sided with sufficient depth


class StalenessRegime(str, Enum):
    """Staleness regime based on time-to-expiry and market conditions.

    RELAXED: Far from expiry (>2-3 min), allow longer book age (60-120s)
    NORMAL: Normal trading conditions, moderate thresholds (30-60s)
    STRICT: Near expiry (<1 min) or high volatility, tight thresholds (5-10s)
    """
    RELAXED = "relaxed"
    NORMAL = "normal"
    STRICT = "strict"


class LagClassifier(str, Enum):
    """Classification of lag type for diagnostic purposes.

    WS_CONNECTION_ISSUE: WebSocket connection problem (pings late, connection dropped)
    NETWORK_LATENCY: General network latency (elevated RTT, packet loss)
    EXCHANGE_API_DELAY: Kalshi REST API lagging behind exchange events
    LOCAL_PROCESSING_LAG: Internal processing delay (CPU, event loop)
    NORMAL: No significant lag detected
    """
    WS_CONNECTION_ISSUE = "ws_connection_issue"
    NETWORK_LATENCY = "network_latency"
    EXCHANGE_API_DELAY = "exchange_api_delay"
    LOCAL_PROCESSING_LAG = "local_processing_lag"
    NORMAL = "normal"


@dataclass
class MarketQuote:
    """Canonical quote model for data integrity layer.

    Every signal agent receives this object (or None) and can inspect
    health, source, and diagnostics to make trading decisions.

    Production-grade metadata:
    - age_ms: time since exchange timestamp in milliseconds
    - confidence: 0.0-1.0 score based on freshness and consistency
    - executable: True only when quote is from live orderbook and market is healthy
    - All downstream code MUST branch on health/source/age/executable, never assume valid
    """
    market_ticker: str  # Kalshi ticker for that 15m contract
    series_ticker: str  # BTC15M / ETH15M / etc
    best_bid_cents: Optional[int] = None  # in cents
    best_ask_cents: Optional[int] = None
    mid_cents: Optional[int] = None
    status: str = "unknown"  # open/closed/paused/unknown
    source: QuoteSource = QuoteSource.WEBSOCKET
    ts_exchange: float = 0.0  # derived from Kalshi timestamp
    ts_received: float = 0.0  # local monotonic time
    age_ms: float = 0.0  # milliseconds since exchange timestamp
    confidence: float = 1.0  # 0.0-1.0 confidence score based on freshness/consistency
    is_fallback: bool = False
    health: QuoteHealth = QuoteHealth.HEALTHY
    executable: bool = False  # True only when live orderbook data is available and healthy
    diagnostics: List[str] = field(default_factory=list)
    # New fields for liquidity audit
    last_update_ts: float = 0.0  # monotonic timestamp of last update
    has_bid: bool = False  # whether bid side exists
    has_ask: bool = False  # whether ask side exists
    min_depth_yes: int = 0  # depth on yes side at best bid
    min_depth_no: int = 0  # depth on no side at best ask
    liquidity_status: LiquidityStatus = LiquidityStatus.MISSING


# Log effective REST fallback configuration (call during startup, not import)
def log_rest_config() -> None:
    """Log effective REST fallback configuration at startup."""
    import os
    _rest_healthy_threshold_ms = float(os.getenv("MERID_KALSHI_REST_HEALTHY_THRESHOLD_MS", "5000"))
    _rest_degraded_threshold_ms = float(os.getenv("MERID_KALSHI_REST_DEGRADED_THRESHOLD_MS", "30000"))
    _rest_high_confidence = float(os.getenv("MERID_KALSHI_REST_HIGH_CONFIDENCE", "0.8"))
    _rest_mid_confidence = float(os.getenv("MERID_KALSHI_REST_MID_CONFIDENCE", "0.6"))
    _rest_low_confidence = float(os.getenv("MERID_KALSHI_REST_LOW_CONFIDENCE", "0.5"))

    # Apply same validation as runtime
    if _rest_healthy_threshold_ms < 0:
        _rest_healthy_threshold_ms = 0
    if _rest_degraded_threshold_ms <= _rest_healthy_threshold_ms:
        _rest_degraded_threshold_ms = _rest_healthy_threshold_ms + 30000

    for name, val in [("high", _rest_high_confidence), ("mid", _rest_mid_confidence), ("low", _rest_low_confidence)]:
        if not (0.0 <= val <= 1.0):
            if val < 0:
                val = 0.0
            else:
                val = 1.0
            if name == "high":
                _rest_high_confidence = val
            elif name == "mid":
                _rest_mid_confidence = val
            else:
                _rest_low_confidence = val

    logger.info(
        "[market-state] REST fallback config: healthy_threshold=%.1fms, degraded_threshold=%.1fms, "
        "high_conf=%.2f, mid_conf=%.2f, low_conf=%.2f",
        _rest_healthy_threshold_ms, _rest_degraded_threshold_ms,
        _rest_high_confidence, _rest_mid_confidence, _rest_low_confidence
    )


class KalshiMarketStateStore:
    """Thread-safe registry of KalshiMarketState keyed by ticker.

    Two independent write paths — neither blocks the other:

    **WS path** (``apply_orderbook_message``)
      Feeds ``orderbook_snapshot`` and ``orderbook_delta`` WS messages
      into a ``MultiMarketOrderbook``, then syncs the book-owned slice
      of ``KalshiMarketState``.

    **REST path** (``apply_rest_market``)
      Feeds a raw market dict from ``GET /markets`` into the REST-owned
      slice (volume_24h, open_interest, notional_value_cents, expiry).
      Also recomputes ``seconds_to_expiry``.
    """

    # H3: Max number of pending deltas queued per ticker while waiting for
    #     a snapshot.  Keeps memory bounded.  Oldest deltas are dropped when
    #     the queue is full so only the most recent context is replayed.
    _MAX_PENDING_DELTAS = 20

    def __init__(self) -> None:
        logger.debug("[BOOT-TRACE] KalshiMarketStateStore.__init__: starting initialization")
        logger.info(f"[MD-STORE-INIT] Creating new KalshiMarketStateStore instance id={id(self)}")
        self._states: Dict[str, KalshiMarketState] = {}
        self._unified: Dict[str, UnifiedMarketState] = {}
        logger.debug("[BOOT-TRACE] KalshiMarketStateStore.__init__: about to create MultiMarketOrderbook")
        self._ob: MultiMarketOrderbook = MultiMarketOrderbook()
        logger.debug("[BOOT-TRACE] KalshiMarketStateStore.__init__: MultiMarketOrderbook created")
        # EVENT-STORM-FIX: Throttling to prevent event loop deadlock from orderbook_delta flood
        # DISABLED: Throttle was causing MD staleness (18-30s) by skipping frequent delta updates
        # Kalshi sends many deltas per second, we need to process them all for fresh MD
        self._last_delta_update: Dict[str, float] = {}
        self._min_delta_interval = 0.0  # Disabled - process all delta updates
        # PERFORMANCE FIX: Cache scope validation results to avoid repeated checks
        self._scope_validation_cache: Dict[str, tuple[bool, Optional[str]]] = {}
        # HARDENING-FIX: Per-ticker locks to reduce contention
        # Each ticker has its own lock for orderbook/state updates
        self._ticker_locks: Dict[str, threading.Lock] = {}
        self._ticker_locks_lock = threading.Lock()  # Protects _ticker_locks dict itself
        # Global lock for multi-ticker operations (get_all, prune_stale, etc.)
        # CRITICAL FIX: Use RLock (reentrant) to prevent deadlock when apply_rest_market calls _get_or_create
        # Regular Lock is not reentrant and causes deadlock when the same thread tries to acquire it twice
        self._global_lock = threading.RLock()
        # P0-3 FIX: Add _lock as alias to _global_lock for backward compatibility
        # Some code (market_catalog.py) expects store._lock to exist
        self._lock = self._global_lock
        logger.debug("[BOOT-TRACE] KalshiMarketStateStore.__init__: per-ticker locks initialized")

        # CRITICAL FIX: Store reference to main event loop for use by batch worker thread
        # This allows run_coroutine_threadsafe to work from the batch worker thread
        try:
            import asyncio
            self._main_event_loop = asyncio.get_event_loop()
            logger.debug("[MD-STORE-INIT] Captured main event loop: %s", self._main_event_loop)
        except Exception as e:
            logger.warning("[MD-STORE-INIT] Failed to capture main event loop: %s", e)
            self._main_event_loop = None

        # LOCK CONTENTION FIX: Per-ticker queues for batched delta application
        # This eliminates LOCK BUSY drops by buffering deltas and applying them in batches
        self._delta_queues: Dict[str, deque] = {}  # Per-ticker queues for orderbook deltas
        self._delta_queue_locks: Dict[str, threading.Lock] = {}  # Per-ticker locks for the queues
        self._MAX_PER_TICKER_QUEUE = 50000  # Max deltas per ticker before overflow (increased to handle extreme WS volume)
        self._batch_worker_running = False
        self._batch_worker_thread: Optional[threading.Thread] = None
        # CRITICAL FIX: Increase batch size and reduce interval to handle extreme WS volume.
        # With the bridge queue at ~30k/32k, the batch worker must drain faster than the
        # orderbook delta rate. Process 500 deltas every 10ms = 50k deltas/sec/ticker.
        self._batch_interval_ms = 10.0  # Process batches every 10ms
        # Event-driven adaptive batching: wake worker immediately on new deltas.
        self._batch_worker_event = threading.Event()

        # DIAGNOSTIC: Update counter for tracking MD updates
        self._update_count = 0

        # H3: per-ticker queue of delta messages received before snapshot (legacy, kept for compatibility)
        self._pending_deltas: Dict[str, List[Dict[str, Any]]] = {}

        # DATA INTEGRITY LAYER: Per-market health state and tracking
        self._health_state: Dict[str, QuoteHealth] = {}
        self._rest_last_fetch: Dict[str, float] = {}  # Last REST fetch time per ticker
        self._consecutive_failures: Dict[str, int] = {}  # Consecutive failures per ticker
        self._circuit_breaker_until: Dict[str, float] = {}  # Circuit breaker expiration time per ticker
        self._metrics: Dict[str, Dict[str, float]] = {}  # Metrics per ticker: quote_age, fallback_count, breaker_opens, rejected_quotes
        self._quote_retry_count: Dict[str, int] = {}  # Total retry attempts per ticker (capped at 3 to prevent thrashing)

        # QUARANTINE: Per-ticker invariant violation tracking and quarantine
        self._invariant_violations: Dict[str, int] = {}  # Invariant violation count per ticker
        self._quarantine_until: Dict[str, float] = {}  # Quarantine expiration time per ticker
        self._last_violation_ts: Dict[str, float] = {}  # Last violation timestamp per ticker
        self._QUARANTINE_THRESHOLD = 5  # Violations before quarantine
        self._QUARANTINE_DURATION_SECONDS = 300  # 5 minutes quarantine

        # QUEUE OVERFLOW RECOVERY: Per-ticker resync tracking
        self._needs_resync: Dict[str, bool] = {}  # Tickers that need snapshot resync after overflow
        self._overflow_count: Dict[str, int] = {}  # Overflow count per ticker for metrics

        # P3 Gap 16: Per-asset lock contention monitoring
        self._lock_contention_count: Dict[str, int] = {}  # Lock contention count per ticker
        self._lock_wait_time_ms: Dict[str, float] = {}  # Total lock wait time per ticker (ms)
        self._last_lock_wait_ms: Dict[str, float] = {}  # Last per-acquisition lock wait (ms)
        self._last_batch_duration_ms: Dict[str, float] = {}  # Last batch processing duration per ticker (ms)

        # 2026-08-24: Snapshot timeout tracking.  Records when a ticker last
        # transitioned to ``snapshot_complete=False`` so we can resubscribe/request
        # a fresh snapshot instead of staying stuck in ``NO_SNAPSHOT`` forever.
        self._snapshot_wait_start_ts: Dict[str, float] = {}

        # DIAGNOSTIC: Track last log time per ticker for rate-limited update logging
        self._last_log_ts: Dict[str, float] = {}

        # AUDIT: Per-ticker snapshot counters for data path verification
        self._snapshots_applied_total: Dict[str, int] = {}  # Total snapshots applied per ticker
        self._last_snapshot_ts: Dict[str, float] = {}  # Last snapshot timestamp per ticker

        # Liquidity metrics tracking
        self._liquidity_samples: Dict[str, int] = {}  # Total liquidity samples per asset
        self._liquidity_ok_samples: Dict[str, int] = {}  # OK liquidity samples per asset

        # SUBSCRIPTION MECHANISM: Callbacks for state updates
        self._subscribers: Dict[str, List[callable]] = {}  # ticker -> list of callbacks

        # ── Connection Health Watchdog Tracking ───────────────────────────────
        # Separate from data staleness - tracks WS connection health
        self._ws_last_msg_monotonic: Dict[str, float] = {}  # Last time ANY WS message received per ticker
        self._ws_connection_healthy: Dict[str, bool] = {}  # WS connection health state per ticker
        self._ws_connection_suspect_since: Dict[str, float] = {}  # When connection became suspect per ticker

        # ── REST updated_time Cross-Check Tracking ─────────────────────────────
        # Track REST updated_time to detect true WS lag
        self._rest_updated_time: Dict[str, float] = {}  # Last REST updated_time per ticker (exchange timestamp)
        self._rest_updated_time_fetched: Dict[str, float] = {}  # When we fetched the REST updated_time per ticker

        # ── Lag Classification Tracking ───────────────────────────────────────
        # Track various signals for lag classification
        self._ws_last_ping_monotonic: float = 0.0  # Last time Kalshi ping received
        self._ws_last_pong_sent_monotonic: float = 0.0  # Last time we sent pong
        self._ws_pong_rtt_ms: float = 0.0  # Last ping-pong round-trip time in ms
        self._ws_expected_ping_interval: float = 10.0  # Kalshi sends pings every ~10s
        self._rest_latency_ms: float = 0.0  # Last REST call latency in ms
        self._rest_user_ts_lag_s: float = 0.0  # Lag between now and user data timestamp
        self._net_ping_ms: float = 0.0  # Last network ping to Kalshi/VPS in ms
        self._processing_lag_ms: float = 0.0  # Internal processing delay in ms
        self._current_lag_class: LagClassifier = LagClassifier.NORMAL  # Current lag classification

        # ── Processing Lag Tracking (recv vs proc timestamps) ───────────────
        # Track message arrival vs processing time to measure internal lag
        self._msg_recv_monotonic: Dict[str, float] = {}  # When WS message was received per ticker
        self._msg_proc_monotonic: Dict[str, float] = {}  # When WS message was processed per ticker

        # ── WS Message Cadence Tracking ─────────────────────────────────────
        # Track update frequency per market to detect staleness anomalies
        self._book_update_timestamps: Dict[str, List[float]] = {}  # Rolling window of update timestamps per ticker
        self._cadence_window_seconds: float = 60.0  # Window size for cadence calculation
        self._baseline_update_intervals: Dict[str, float] = {}  # Median update interval per ticker (baseline)
        self._updates_per_minute: Dict[str, float] = {}  # Current updates per minute per ticker

        # ── RTT Volatility Tracking ─────────────────────────────────────────
        # Track rolling mean and std of RTT to detect network issues
        self._ws_rtt_samples: List[float] = []  # Rolling window of WS ping/pong RTT samples
        self._rest_rtt_samples: List[float] = []  # Rolling window of REST latency samples
        self._rtt_window_seconds: float = 300.0  # 5-minute window for RTT volatility
        self._rtt_sample_timestamps: List[float] = []  # Timestamps for RTT samples (for pruning)
        self._ws_rtt_mean: float = 0.0  # Rolling mean of WS RTT
        self._ws_rtt_std: float = 0.0  # Rolling std of WS RTT
        self._rest_rtt_mean: float = 0.0  # Rolling mean of REST RTT
        self._rest_rtt_std: float = 0.0  # Rolling std of REST RTT

        # ── Rate Limiting & Adaptive Polling ───────────────────────────────
        # Track rate limit status and adapt polling intervals
        self._rest_calls_per_minute: float = 0.0  # Current REST call rate
        self._rest_call_timestamps: List[float] = []  # Timestamps of REST calls (for rate tracking)
        self._adaptive_poll_interval: float = 60.0  # Current adaptive polling interval (seconds)
        self._base_poll_interval: float = 60.0  # Base polling interval
        self._min_poll_interval: float = 30.0  # Minimum polling interval
        self._max_poll_interval: float = 300.0  # Maximum polling interval
        self._rate_limit_hits: int = 0  # Count of 429 responses
        self._last_429_timestamp: float = 0.0  # Last time we got a 429
        self._backoff_until: float = 0.0  # Backoff until this timestamp

        logger.debug("[BOOT-TRACE] KalshiMarketStateStore.__init__: initialization complete")

    def set_main_event_loop(self, loop) -> None:
        """Register the running event loop used to schedule async resync tasks.

        KalshiMarketStateStore may be created before the WebSocket forwarder
        event loop exists.  Call this from the forwarder thread once its loop
        is running so REST re-sync tasks can be scheduled correctly.
        """
        import asyncio
        if (
            loop is not None
            and isinstance(loop, asyncio.AbstractEventLoop)
            and loop.is_running()
        ):
            self._main_event_loop = loop
            logger.info("[MD-STORE-LOOP] Registered main event loop: %s", loop)

    def _get_ticker_lock(self, ticker: str) -> threading.Lock:
        """Get or create a lock for a specific ticker.

        HARDENING-FIX: Per-ticker locks reduce contention by allowing concurrent
        updates to different tickers.

        P3 Gap 16: Track lock contention for monitoring.
        """
        with self._ticker_locks_lock:
            if ticker not in self._ticker_locks:
                self._ticker_locks[ticker] = threading.Lock()
            return self._ticker_locks[ticker]

    def _get_delta_queue_lock(self, ticker: str) -> threading.Lock:
        """Get or create a lock for a specific ticker delta queue.

        LOCK CONTENTION FIX: Per-ticker queue locks allow concurrent enqueue
        on different tickers and decouple enqueue from the orderbook state lock.
        """
        with self._ticker_locks_lock:
            if ticker not in self._delta_queue_locks:
                self._delta_queue_locks[ticker] = threading.Lock()
            return self._delta_queue_locks[ticker]

    def _resolve_book_source(self, via: str, channel: str) -> str:
        """Map transport provenance to a canonical data-source label.

        REST-derived full snapshots are authoritative.  WS snapshots from the
        real-time bridge are bootstraps that require a contiguous delta to
        become ``LIVE_SEQUENCE_CONFIRMED``.  Contiguous deltas are the only
        source that confirms live sequence.
        """
        if via in ("rest_bootstrap", "ws_fallback", "subscribe_fallback", "rest_polling", "ws_subscribe_bootstrap"):
            return "REST_FULL_ORDERBOOK"
        if via == "bridge_queue":
            if channel == "orderbook_snapshot":
                return "BOOTSTRAP_VALID_BUT_UNCONFIRMED"
            if channel == "orderbook_delta":
                return "WS_ORDERBOOK_DELTA_LIVE"
            return "UNKNOWN"
        if via in ("manual", "test"):
            if channel == "orderbook_delta":
                return "WS_ORDERBOOK_DELTA_LIVE"
            return "WS_CLEAN_SNAPSHOT"
        if via == "quote_fallback":
            return "WS_QUOTE"
        return "UNKNOWN"

    def _attest_state_recovery(
        self,
        state: KalshiMarketState,
        source: str,
        *,
        prior_quality: Optional[str] = None,
        prior_transition: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """Central recovery attestation gate.

        A state that is currently ``INVALID`` or has ``transition == CIRCUIT_BREAKER``
        may only be restored to ``GOOD`` / ``executable`` by an authoritative source:
        a full REST orderbook snapshot, a contiguous WS delta stream, or an explicit
        clean WS snapshot (test/manually attested).  Quote fallbacks, catalog REST
        market feeds, or unconfirmed WS snapshots must not silently lift a circuit
        breaker.

        Args:
            state: The ``KalshiMarketState`` being promoted.
            source: The provenance label for this recovery attempt.
            prior_quality: Quality *before* the current update was applied, if known.
            prior_transition: Transition label *before* the current update, if known.
            force: If True, bypass the attestation gate (for test fixtures only).

        Returns:
            True if the state was promoted to / kept executable, False if recovery
            was rejected and the state remains INVALID.
        """
        if prior_quality is None:
            prior_quality = state.data_quality
        if prior_transition is None:
            prior_transition = state.transition

        if not force and (prior_quality == "INVALID" or prior_transition == "CIRCUIT_BREAKER"):
            # Determine the class of source required for recovery.  An explicit
            # ``recovery_required_source`` on the state (set when the invalidation
            # occurred) wins; otherwise derive from the transition label.
            required = state.recovery_required_source or _recovery_required_for_transition(prior_transition)
            if not _source_satisfies_recovery(source, required):
                logger.critical(
                    "[STATE-RECOVERY-REJECTED] ticker=%s prior_quality=%s prior_transition=%s "
                    "attempted_source=%s required=%s - non-attested source tried to clear INVALID/CIRCUIT_BREAKER; "
                    "keeping state invalid",
                    state.ticker,
                    prior_quality,
                    prior_transition,
                    source,
                    required,
                )
                # Re-assert the invalid state in case a previous line softened it.
                state.data_quality = "INVALID"
                state.executable = False
                state.book_initialized = False
                # Preserve the most specific transition label.
                if prior_transition == "CIRCUIT_BREAKER":
                    state.transition = "CIRCUIT_BREAKER"
                self._set_snapshot_complete(state.ticker, False, "recovery_rejected")
                return False

        state.data_quality = "GOOD"
        state.book_consistency = "GOOD"
        state.transition = "VALID"
        state.executable = True
        state.recovery_attested = True
        state.recovery_source = source
        state.recovery_ts = time.monotonic()
        state.recovery_required_source = ""
        state.invalidation_cause = ""
        if source == "WS_ORDERBOOK_DELTA_LIVE":
            state.live_sequence_confirmed = True
        else:
            # Snapshots (even authoritative REST ones) are not a confirmed live
            # sequence; a contiguous WS delta is required to clear the bootstrap
            # flag for new-entry gating.
            state.live_sequence_confirmed = False
        return True

    def _start_batch_worker(self) -> None:
        """Start the batch worker thread for processing queued deltas.

        LOCK CONTENTION FIX: This worker processes deltas in batches to eliminate
        LOCK BUSY drops. It cycles through all tickers and applies queued deltas
        while holding the per-ticker lock for the minimum time.
        """
        logger.info("[BATCH-WORKER] _start_batch_worker ENTRY - _batch_worker_running=%s", self._batch_worker_running)
        if self._batch_worker_running:
            logger.info("[BATCH-WORKER] Batch worker already running, skipping start")
            return

        self._batch_worker_running = True
        logger.info("[BATCH-WORKER] Setting _batch_worker_running=True and starting thread")

        def _batch_worker_loop():
            """Batch worker loop that processes queued deltas.

            LOCK CONTENTION FIX: Pops batches under a per-ticker queue lock, then
            applies them under the per-ticker orderbook lock. This decouples
            enqueue from apply and removes the global _ticker_locks_lock from
            the hot path.
            """
            logger.info("[BATCH-WORKER] Starting batch worker thread")
            while self._batch_worker_running:
                try:
                    # Event-driven adaptive batching: clear the wake event so new deltas
                    # that arrive during/after this batch can wake the worker immediately.
                    self._batch_worker_event.clear()

                    # Snapshot ticker list under the global dict lock (fast).
                    with self._ticker_locks_lock:
                        tickers_to_process = list(self._delta_queues.keys())

                    if tickers_to_process:
                        logger.debug(f"[BATCH-WORKER] Processing {len(tickers_to_process)} tickers: {tickers_to_process}")

                    for ticker in tickers_to_process:
                        if not self._batch_worker_running:
                            break

                        # CRITICAL FIX (2026-08-24): Resolve lock-order inversion between the
                        # batch worker and the enqueue forwarder. The worker was acquiring
                        # queue_lock then _ticker_locks_lock, while the forwarder acquires
                        # _ticker_locks_lock then queue_lock. This produced constant 0.1s
                        # queue-lock timeouts at high message cadence. Both paths now
                        # acquire _ticker_locks_lock first to look up the queue/lock, then
                        # acquire queue_lock; the worker releases _ticker_locks_lock before
                        # waiting on queue_lock so a forwarder can still append.
                        with self._ticker_locks_lock:
                            if ticker not in self._delta_queues:
                                self._delta_queues[ticker] = deque()
                            if ticker not in self._delta_queue_locks:
                                self._delta_queue_locks[ticker] = threading.Lock()
                            queue = self._delta_queues[ticker]
                            queue_lock = self._delta_queue_locks[ticker]

                        lock_start = time.monotonic()
                        if not queue_lock.acquire(blocking=True, timeout=2.0):
                            logger.warning(
                                "[BATCH-WORKER] Queue lock acquisition timeout for ticker=%s - contention detected",
                                ticker
                            )
                            with self._ticker_locks_lock:
                                self._lock_contention_count[ticker] = self._lock_contention_count.get(ticker, 0) + 1
                            continue

                        batch: List[Dict[str, Any]] = []
                        try:
                            if not queue:
                                continue

                            # Check for overflow
                            if len(queue) > self._MAX_PER_TICKER_QUEUE:
                                self._overflow_count[ticker] = self._overflow_count.get(ticker, 0) + 1
                                logger.error(
                                    f"[BOOK-OVERFLOW] ticker={ticker} queue_len={len(queue)} "
                                    f"max={self._MAX_PER_TICKER_QUEUE} overflow_count={self._overflow_count.get(ticker, 0)} "
                                    f"marking SUSPECT"
                                )
                                # Mark as SUSPECT and trigger REST bootstrap
                                state = self._states.get(ticker)
                                if state:
                                    state.book_consistency = "SUSPECT"
                                    self._set_book_health(ticker, BookHealth.INVALID, "queue_overflow")
                                    self._set_book_health(ticker, BookHealth.RESYNC_REQUESTED, "queue_overflow")
                                    try:
                                        import asyncio
                                        loop = asyncio.get_event_loop()
                                        if loop.is_running():
                                            asyncio.create_task(self._sync_invariant_violation_with_rest(ticker))
                                    except Exception as e:
                                        logger.error("[BATCH-WORKER] Failed to schedule REST bootstrap for %s: %s", ticker, e, exc_info=True)
                                queue.clear()
                                continue

                            # Pop a batch while holding the queue lock.
                            batch_size = min(500, len(queue))
                            batch = [queue.popleft() for _ in range(batch_size)]
                        finally:
                            queue_lock.release()
                            lock_wait_ms = (time.monotonic() - lock_start) * 1000
                            with self._ticker_locks_lock:
                                self._lock_wait_time_ms[ticker] = self._lock_wait_time_ms.get(ticker, 0.0) + lock_wait_ms
                                self._last_lock_wait_ms[ticker] = lock_wait_ms

                        if not batch:
                            continue

                        # Apply the batch under the orderbook ticker lock.
                        ticker_lock = self._get_ticker_lock(ticker)
                        lock_start = time.monotonic()
                        if not ticker_lock.acquire(blocking=True, timeout=2.0):
                            logger.warning(
                                "[BATCH-WORKER] Orderbook lock acquisition timeout for ticker=%s - contention detected",
                                ticker
                            )
                            with self._ticker_locks_lock:
                                self._lock_contention_count[ticker] = self._lock_contention_count.get(ticker, 0) + 1
                            continue

                        try:
                            batch_count = 0
                            batch_start = time.monotonic()
                            # Coalesce contiguous same-(side, price) delta_fp messages
                            # before applying.  This reduces orderbook churn and CPU
                            # under burst conditions while preserving sequence
                            # contiguity and gap detection.
                            coalesced = self._coalesce_deltas(ticker, batch)
                            applied_batch = coalesced if coalesced is not None else batch
                            for msg in applied_batch:
                                try:
                                    self._apply_delta_internal(ticker, msg)
                                    batch_count += 1
                                except Exception as e:
                                    logger.error("[BATCH-WORKER] Failed to apply delta for %s: %s", ticker, e, exc_info=True)

                            if batch_count > 0:
                                batch_duration_ms = (time.monotonic() - batch_start) * 1000
                                with self._ticker_locks_lock:
                                    self._last_batch_duration_ms[ticker] = batch_duration_ms
                                logger.debug(
                                    "[BATCH-WORKER] Processed %d deltas for %s in %.1fms",
                                    batch_count, ticker, batch_duration_ms
                                )
                        finally:
                            ticker_lock.release()
                            lock_wait_ms = (time.monotonic() - lock_start) * 1000
                            with self._ticker_locks_lock:
                                self._lock_wait_time_ms[ticker] = self._lock_wait_time_ms.get(ticker, 0.0) + lock_wait_ms
                                self._last_lock_wait_ms[ticker] = lock_wait_ms

                    # Event-driven adaptive batching: block until the next delta
                    # arrives or the batch interval elapses. This replaces the fixed
                    # 10ms sleep, cutting latency when the queue is busy and throttling
                    # when it is idle.
                    self._batch_worker_event.wait(self._batch_interval_ms / 1000.0)

                except Exception as e:
                    logger.error("[BATCH-WORKER] Batch worker error: %s", e, exc_info=True)
                    time.sleep(0.1)

            logger.info("[BATCH-WORKER] Batch worker thread stopped")

        self._batch_worker_thread = threading.Thread(target=_batch_worker_loop, name="kalshi_batch_worker", daemon=False)
        self._batch_worker_thread.start()
        logger.info("[BATCH-WORKER] Batch worker thread started, _batch_worker_running=%s", self._batch_worker_running)

    def _stop_batch_worker(self) -> None:
        """Stop the batch worker thread."""
        self._batch_worker_running = False
        if self._batch_worker_thread and self._batch_worker_thread.is_alive():
            self._batch_worker_thread.join(timeout=2.0)
            logger.info("[BATCH-WORKER] Batch worker thread stopped")

    def _enqueue_delta(self, ticker: str, msg: Dict[str, Any]) -> bool:
        """Enqueue a delta message for batch processing.

        Returns True if enqueued successfully, False if queue overflow.

        On overflow, triggers immediate snapshot recovery to prevent selective staleness.

        LOCK CONTENTION FIX: Uses a per-ticker queue lock so concurrent enqueues
        for different tickers no longer serialize on the global _ticker_locks_lock.
        """
        # Ensure the queue and its lock exist under the global dict lock.
        with self._ticker_locks_lock:
            if ticker not in self._delta_queues:
                self._delta_queues[ticker] = deque()
            if ticker not in self._delta_queue_locks:
                self._delta_queue_locks[ticker] = threading.Lock()
            queue = self._delta_queues[ticker]
            queue_lock = self._delta_queue_locks[ticker]

        with queue_lock:
            if len(queue) >= self._MAX_PER_TICKER_QUEUE:
                # Extract asset from ticker for selective staleness detection
                asset = None
                if ticker.startswith("KXBTC"):
                    asset = "BTC"
                elif ticker.startswith("KXETH"):
                    asset = "ETH"
                elif ticker.startswith("KXSOL"):
                    asset = "SOL"
                elif ticker.startswith("KXXRP"):
                    asset = "XRP"
                elif ticker.startswith("KXDOGE"):
                    asset = "DOGE"

                # Increment overflow counter for metrics
                self._overflow_count[ticker] = self._overflow_count.get(ticker, 0) + 1

                # P1 FIX: Trigger immediate snapshot recovery instead of just marking for resync
                # This prevents selective staleness by requesting fresh data immediately
                logger.error(
                    f"[BOOK-OVERFLOW] ticker={ticker} asset={asset} queue_len={len(queue)} "
                    f"max={self._MAX_PER_TICKER_QUEUE} overflow_count={self._overflow_count[ticker]} "
                    f"triggering_immediate_snapshot_recovery"
                )

                state = self._states.get(ticker)
                if state:
                    state.book_consistency = "SUSPECT"
                    state.data_quality = "INVALID"
                    state.transition = "RESYNC_REQUIRED"
                    state.executable = False
                    self._set_snapshot_complete(ticker, False, "delta_queue_overflow")
                    self._set_book_health(ticker, BookHealth.INVALID, "queue_overflow_enqueue")
                    self._set_book_health(ticker, BookHealth.RESYNC_REQUESTED, "queue_overflow_enqueue")

                # Trigger immediate snapshot recovery via WebSocket
                try:
                    import asyncio
                    loop = self._main_event_loop
                    if loop and loop.is_running():
                        # Schedule snapshot request on the event loop
                        asyncio.run_coroutine_threadsafe(
                            self._trigger_snapshot_recovery(ticker),
                            loop
                        )
                except Exception as e:
                    logger.error(f"[BOOK-OVERFLOW] Failed to trigger snapshot recovery for {ticker}: {e}")

                return False

            queue.append(msg)
            self._batch_worker_event.set()
            return True

    def _apply_delta_internal(self, ticker: str, msg: Dict[str, Any]) -> None:
        """Internal method to apply a delta message (called by batch worker).

        This method assumes the ticker lock is already held.
        """
        ob = self._ob.get_book(ticker)
        if not ob or not ob.initialized:
            # Queue delta if book not yet initialized (legacy path)
            # 2026-08-24: Guard against an indefinitely stuck NO_SNAPSHOT state.
            self._check_snapshot_timeout(ticker)
            # CRITICAL FIX: Check pending deltas queue size to prevent unbounded growth
            pending = self._pending_deltas.get(ticker, [])
            if len(pending) >= self._MAX_PENDING_DELTAS:
                logger.warning(
                    "[DELTA-QUEUE-FULL] ticker=%s pending_deltas=%d >= max=%d - dropping delta",
                    ticker, len(pending), self._MAX_PENDING_DELTAS
                )
                return
            self._pending_deltas.setdefault(ticker, []).append(msg)

            # CRITICAL FIX (2026-08-22): A queued delta is NOT a book update.  Do not
            # touch book staleness timestamps; doing so makes the health check report
            # a fresh book while we are still waiting for a snapshot.  Only the
            # all-purpose last_update_ts and data_source are updated so we can still
            # see the connection is alive.
            state = self._get_or_create(ticker)
            state.last_update_ts = time.monotonic()
            state.data_source = "WS_ORDERBOOK_DELTA_PENDING"  # More specific: delta waiting for snapshot

            # CONNECTION HEALTH: Update WS connection health tracking
            self._update_ws_connection_health(ticker)

            # CRITICAL FIX (2026-08-02): Update book freshness tracker from pending delta
            # This ensures even queued deltas refresh the state machine
            try:
                from merid.event_venues.kalshi.book_freshness import get_book_freshness_tracker
                freshness_tracker = get_book_freshness_tracker()

                # Extract timestamp from delta message
                timestamp_str = msg.get("timestamp")
                received_ts = None
                if timestamp_str:
                    try:
                        from datetime import datetime
                        if isinstance(timestamp_str, str):
                            received_ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).timestamp()
                    except Exception as ts_error:
                        logger.debug("[BOOK-FRESHNESS] Failed to parse timestamp for %s: %s", ticker, ts_error)

                freshness_tracker.update_from_ws(ticker, exchange_ts=None, received_ts=received_ts)
                logger.debug("[BOOK-FRESHNESS] Updated state for %s from pending delta", ticker)
            except ImportError:
                logger.warning("[BOOK-FRESHNESS] book_freshness module not available, skipping freshness update")
            except Exception as e:
                logger.error(f"[BOOK-FRESHNESS] Failed to update freshness state for {ticker} from pending delta: {e}")

            # PROCESSING LAG: Record processing timestamp
            self._record_msg_proc_timestamp(ticker)

            # Rate-limit logging to avoid spam
            now = time.monotonic()
            if now - self._last_log_ts.get(ticker, 0) > 30:
                pending_count = len(self._pending_deltas.get(ticker, []))
                logger.info(
                    "[WS-DELTA-QUEUED] ticker=%s pending_deltas=%d waiting_for_snapshot=true",
                    ticker, pending_count
                )
                self._last_log_ts[ticker] = now

            # CRITICAL FIX: Trigger REST snapshot if we have many pending deltas but no initialized book
            # This handles the case where WS deltas arrive but no snapshot is ever received
            pending_count = len(self._pending_deltas.get(ticker, []))
            if pending_count >= 5 and pending_count % 5 == 0:
                logger.warning(
                    "[WS-DELTA-BOOTSTRAP] ticker=%s has %d pending deltas but no initialized book - triggering REST and WS snapshot bootstrap",
                    ticker, pending_count
                )
                # 2026-08-24: Explicitly request a WebSocket snapshot to break the
                # dead-ready state where the book is subscribed but no snapshot is
                # arriving.  This is the resubscribe/snapshot recovery path.
                try:
                    import asyncio
                    loop = self._main_event_loop
                    if loop and loop.is_running():
                        ws_future = asyncio.run_coroutine_threadsafe(
                            self._trigger_snapshot_recovery(ticker),
                            loop,
                        )
                        logger.info(
                            "[WS-SNAPSHOT-RECOVERY] Scheduled WS snapshot request for %s (future=%s)",
                            ticker, ws_future,
                        )
                    else:
                        logger.warning("[WS-SNAPSHOT-RECOVERY] Event loop not available for %s", ticker)
                except Exception as e:
                    logger.error("[WS-SNAPSHOT-RECOVERY] Failed to schedule WS snapshot for %s: %s", ticker, e, exc_info=True)

                try:
                    import asyncio
                    loop = self._main_event_loop
                    if loop and loop.is_running():
                        # Use run_coroutine_threadsafe to schedule from a different thread
                        future = asyncio.run_coroutine_threadsafe(
                            self._sync_invariant_violation_with_rest(ticker),
                            loop
                        )
                        logger.info("[WS-DELTA-BOOTSTRAP] Successfully scheduled REST bootstrap for %s (future=%s)", ticker, future)

                        # Add callback to log completion or error
                        def log_future_result(fut):
                            try:
                                result = fut.result()
                                logger.info("[WS-DELTA-BOOTSTRAP] REST bootstrap completed for %s: result=%s", ticker, result)
                            except Exception as e:
                                logger.error("[WS-DELTA-BOOTSTRAP] REST bootstrap failed for %s: %s", ticker, e, exc_info=True)

                        future.add_done_callback(log_future_result)
                    else:
                        logger.warning("[WS-DELTA-BOOTSTRAP] Event loop not available or not running for %s (loop=%s)", ticker, loop)
                except Exception as e:
                    logger.error("[WS-DELTA-BOOTSTRAP] Failed to schedule REST bootstrap for %s: %s", ticker, e, exc_info=True)

            return

        # CRITICAL FIX (2026-08-22): Lightweight WS sequence validator, separated
        # from the orderbook state applier below.  A non-contiguous sequence means
        # the in-memory book is missing levels and cannot be trusted for execution.
        ob = self._ob.get_book(ticker)
        is_valid, expected, msg_seq = self._validate_delta_sequence(ticker, msg, ob)
        if not is_valid:
            state = self._get_or_create(ticker)
            state.data_quality = "INVALID"
            state.book_consistency = "SUSPECT"
            state.transition = "INVALID_SEQUENCE_GAP"
            state.invalidation_cause = "INVALID_SEQUENCE_GAP"
            state.recovery_required_source = "FULL_SNAPSHOT"
            state.executable = False
            self._set_snapshot_complete(ticker, False, "ws_sequence_gap")
            self._set_book_health(
                ticker,
                BookHealth.GAP_DETECTED,
                f"expected_seq={expected} got_seq={msg_seq}",
            )
            logger.warning(
                "[WS-SEQUENCE-GAP] ticker=%s expected_seq=%d got_seq=%d - "
                "invalidating book and scheduling resync",
                ticker, expected, msg_seq
            )
            self._schedule_duality_resync(ticker)
            self._set_book_health(
                ticker,
                BookHealth.RESYNC_REQUESTED,
                f"expected_seq={expected} got_seq={msg_seq}",
            )
            # Drop the non-contiguous delta; a snapshot will rebuild.
            return

        if ob and ob.initialized and ob.last_seq is not None:
            state = self._get_or_create(ticker)
            if state.book_health != BookHealth.LIVE.value:
                self._set_book_health(ticker, BookHealth.SEQUENCE_VALIDATING, f"expected_seq={ob.last_seq + 1}")

        # Apply delta
        self._ob.apply_delta(ticker, msg)

        # Sync state
        state = self._get_or_create(ticker)
        prior_quality = state.data_quality
        prior_transition = state.transition

        self._sync_book_fields(state, self._ob.get_book(ticker), ticker, via="bridge_queue")
        self._sync_unified_book(ticker, state)

        state.data_source = "WS_ORDERBOOK_DELTA_LIVE"

        # A contiguous live delta can attest recovery from INVALID/CIRCUIT_BREAKER.
        # _sync_book_fields has already provisionally set GOOD/SUSPECT/INVALID for
        # this delta; we now apply the recovery-source gate.
        if state.data_quality not in ("SUSPECT", "INVALID"):
            self._attest_state_recovery(
                state,
                "WS_ORDERBOOK_DELTA_LIVE",
                prior_quality=prior_quality,
                prior_transition=prior_transition,
            )
            if state.live_sequence_confirmed:
                self._set_book_health(ticker, BookHealth.LIVE, "contiguous_delta_confirmed")
            else:
                self._set_book_health(ticker, BookHealth.SNAPSHOT_RECEIVED, "delta_without_live_sequence")
        else:
            # Duality or crossed-market invariant failed for this delta.
            self._set_book_health(ticker, BookHealth.INVALID, f"data_quality={state.data_quality} transition={state.transition}")
            # 2026-08-24: A delta that invalidates the book means the last trusted
            # snapshot no longer represents the current book; require a fresh one.
            self._set_snapshot_complete(ticker, False, f"delta_invalidated_book data_quality={state.data_quality}")

        # Log raw book after delta (rate-limited to avoid spam)
        book = self._ob.get_book(ticker)
        if book and book.initialized:
            try:
                yes_levels = list(book.yes_levels) if book.yes_levels and not isinstance(book.yes_levels, slice) else []
                no_levels = list(book.no_levels) if book.no_levels and not isinstance(book.no_levels, slice) else []
            except (TypeError, AttributeError):
                yes_levels = []
                no_levels = []
            yes_raw = yes_levels[:5] if yes_levels else []
            no_raw = no_levels[:5] if no_levels else []
            logger.debug(
                "[KALSHI-RAW-BOOK] ticker=%s yes_raw=%s no_raw=%s side=orderbook_delta source=WS",
                ticker, yes_raw, no_raw
            )

            # DIAGNOSTIC: Log book summary after delta application
            try:
                # Handle both tuple format (price, size) and index format (just integers)
                total_yes_size = 0
                total_no_size = 0
                for level in yes_levels:
                    if isinstance(level, (list, tuple)) and len(level) > 1:
                        total_yes_size += level[1]
                    elif isinstance(level, (int, float)):
                        # Index-based format - count as 1 level per index
                        total_yes_size += 1
                for level in no_levels:
                    if isinstance(level, (list, tuple)) and len(level) > 1:
                        total_no_size += level[1]
                    elif isinstance(level, (int, float)):
                        # Index-based format - count as 1 level per index
                        total_no_size += 1
                logger.debug(
                    "[OB-SUMMARY] ticker=%s best_yes=%s best_no=%s depth_yes=%d depth_no=%d total_yes_levels=%d total_no_levels=%d yes_levels_sample=%s no_levels_sample=%s",
                    ticker,
                    state.best_bid_cents,
                    state.best_ask_cents,
                    total_yes_size,
                    total_no_size,
                    len(yes_levels),
                    len(no_levels),
                    str(yes_levels[:3]) if yes_levels else [],
                    str(no_levels[:3]) if no_levels else []
                )
            except Exception as e:
                logger.warning("[OB-SUMMARY] Failed to compute summary for %s: %s", ticker, e)

        # Log parsed book after computing top prices
        if state.best_bid_cents is not None or state.best_ask_cents is not None:
            logger.debug(
                "[KALSHI-PARSED-BOOK] ticker=%s yes_best=%s no_best=%s source=WS",
                ticker, state.best_bid_cents, state.best_ask_cents
            )

        # Log state after write (rate-limited)
        logger.debug(
            "[STATE-AFTER-WRITE] ticker=%s bid=%s ask=%s initialized=%s executable=%s",
            ticker,
            state.best_bid_cents,
            state.best_ask_cents,
            state.book_initialized,
            state.executable
        )

        # CRITICAL FIX (2026-08-02): Update book freshness tracker from delta data
        # This ensures WebSocket delta updates also refresh the state machine
        try:
            from merid.event_venues.kalshi.book_freshness import get_book_freshness_tracker
            freshness_tracker = get_book_freshness_tracker()

            # Extract timestamp from delta message
            timestamp_str = msg.get("timestamp")
            received_ts = None
            if timestamp_str:
                try:
                    from datetime import datetime
                    if isinstance(timestamp_str, str):
                        received_ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).timestamp()
                except Exception as ts_error:
                    logger.debug("[BOOK-FRESHNESS] Failed to parse timestamp for %s: %s", ticker, ts_error)

            freshness_tracker.update_from_ws(ticker, exchange_ts=None, received_ts=received_ts)
            logger.debug("[BOOK-FRESHNESS] Updated state for %s from delta data", ticker)
        except ImportError:
            logger.warning("[BOOK-FRESHNESS] book_freshness module not available, skipping freshness update")
        except Exception as e:
            logger.error("[BOOK-FRESHNESS] Failed to update freshness state for %s from delta: %s", ticker, e)

    def _record_metric(self, ticker: str, metric_name: str, value: float) -> None:
        """Record a metric for a ticker."""
        # HARDENING-FIX: Use per-ticker lock for metrics
        ticker_lock = self._get_ticker_lock(ticker)
        with ticker_lock:
            if ticker not in self._metrics:
                self._metrics[ticker] = {}
            self._metrics[ticker][metric_name] = self._metrics[ticker].get(metric_name, 0.0) + value

    def _record_invariant_violation(self, ticker: str, violation_type: str) -> bool:
        """Record an invariant violation and check if ticker should be quarantined.

        Args:
            ticker: Market ticker
            violation_type: Type of violation (e.g., 'duality', 'invariant')

        Returns:
            True if ticker is quarantined, False otherwise
        """
        now = time.monotonic()
        # Use the reentrant global lock.  This method may be called from
        # _sync_book_fields which already holds the per-ticker lock; the
        # per-ticker lock is a plain Lock and would deadlock if re-acquired.
        with self._lock:
            # Reset violation count if last violation was > 5 minutes ago
            if ticker in self._last_violation_ts and now - self._last_violation_ts[ticker] > 300:
                self._invariant_violations[ticker] = 0

            # Increment violation count
            self._invariant_violations[ticker] = self._invariant_violations.get(ticker, 0) + 1
            self._last_violation_ts[ticker] = now

            logger.warning(
                f"[QUARANTINE] Invariant violation for {ticker}: type={violation_type} "
                f"count={self._invariant_violations[ticker]} threshold={self._QUARANTINE_THRESHOLD}"
            )

            # Check if quarantine threshold is reached
            if self._invariant_violations[ticker] >= self._QUARANTINE_THRESHOLD:
                self._quarantine_until[ticker] = now + self._QUARANTINE_DURATION_SECONDS
                logger.error(
                    f"[QUARANTINE] Ticker {ticker} quarantined for {self._QUARANTINE_DURATION_SECONDS}s "
                    f"due to {self._invariant_violations[ticker]} invariant violations"
                )
                return True

            return False

    def _is_quarantined(self, ticker: str) -> bool:
        """Check if a ticker is currently quarantined."""
        now = time.monotonic()
        # HARDENING-FIX: Use per-ticker lock for quarantine check
        ticker_lock = self._get_ticker_lock(ticker)
        with ticker_lock:
            if ticker in self._quarantine_until:
                if now < self._quarantine_until[ticker]:
                    return True
                else:
                    # Quarantine expired, clean up
                    del self._quarantine_until[ticker]
                    self._invariant_violations[ticker] = 0
                    logger.info("[QUARANTINE] Quarantine expired for %s", ticker)
                    return False
            return False

    def _needs_snapshot_resync(self, ticker: str) -> bool:
        """Check if a ticker needs snapshot resync due to queue overflow."""
        with self._ticker_locks_lock:
            return self._needs_resync.get(ticker, False)

    def _mark_resync_complete(self, ticker: str) -> None:
        """Mark ticker as having completed resync (clear overflow flags)."""
        with self._ticker_locks_lock:
            if ticker in self._needs_resync:
                del self._needs_resync[ticker]
                logger.info(f"[RESYNC-COMPLETE] ticker={ticker} cleared resync flag")
            # Clear delta queue to prevent stale deltas after resync
            if ticker in self._delta_queues:
                self._delta_queues[ticker].clear()
                logger.info(f"[RESYNC-COMPLETE] ticker={ticker} cleared delta queue")

    async def _trigger_snapshot_recovery(self, ticker: str) -> None:
        """P1 FIX: Trigger immediate snapshot recovery via WebSocket.

        This method requests a fresh snapshot via the WebSocket client's
        request_orderbook_snapshot method, maintaining single ingestion path.
        """
        try:
            logger.info("[SNAPSHOT-RECOVERY] Triggering WebSocket snapshot recovery for %s", ticker)

            # Get the WebSocket client
            from merid.event_venues.kalshi.ws import get_kalshi_websocket
            ws_client = get_kalshi_websocket()

            if ws_client and ws_client._ws:
                # Request snapshot via WebSocket API
                await ws_client.request_orderbook_snapshot(ticker)
                logger.info("[SNAPSHOT-RECOVERY] Snapshot request sent for %s", ticker)
            else:
                logger.warning("[SNAPSHOT-RECOVERY] WebSocket client not available for %s - skipping", ticker)

        except Exception as e:
            logger.error("[SNAPSHOT-RECOVERY] Failed to trigger snapshot recovery for %s: %s", ticker, e)

    def _get_exponential_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter for recovery attempts."""
        # Exponential backoff: base * 2^attempt, capped at max
        base_backoff = min(2.0 ** attempt, _CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS)
        # Add jitter: +/- 25% of base backoff
        jitter = base_backoff * 0.25 * (random.random() * 2 - 1)
        return max(0, base_backoff + jitter)

    def log_book_health(self) -> None:
        """Log healthy book invariant for all tracked tickers.

        PRODUCTION AUDIT (Step 7): Green state heartbeat - confirms system health and scope enforcement.
        Kalshi alignment: Only counts markets with status=active as tradable.

        For each ticker, logs:
        - book_initialized status
        - last_update_age_ms
        - best_bid, best_ask, mid
        - spread_cents
        - overflow_count (P3 Gap 15: delta queue overflow monitoring)

        This provides visibility into book health and freshness.
        """
        try:
            now = time.monotonic()
            with self._global_lock:  # Use global lock for multi-ticker operations
                healthy_books = 0
                total_books = 0
                stale_books = 0
                scope_violations = 0
                total_overflows = 0

                for ticker, state in self._states.items():
                    # Only log 5-crypto/15m markets
                    underlying, timeframe = _parse_market_ticker(ticker)

                    if underlying not in _ALLOWED_UNDERLYINGS or timeframe not in _ALLOWED_TIMEFRAMES:
                        continue

                    total_books += 1

                    # P1 FIX: Use new check_health method to separate transport from liquidity health
                    health = state.check_health()

                    # P3 Gap 15: Track overflow count for alerting
                    overflow_count = self._overflow_count.get(ticker, 0)
                    total_overflows += overflow_count

                    # Alert if overflow count exceeds threshold
                    if overflow_count >= 3:
                        logger.warning(
                            f"[OVERFLOW-ALERT] ticker={ticker} overflow_count={overflow_count} "
                            f"exceeds threshold (3) - may indicate WS volume surge or processing bottleneck"
                        )

                    # P3 Gap 16: Track lock contention for alerting
                    lock_contention = self._lock_contention_count.get(ticker, 0)
                    lock_wait_time = self._lock_wait_time_ms.get(ticker, 0.0)

                    # Alert if lock contention is high
                    if lock_contention >= 10:
                        logger.warning(
                            f"[LOCK-CONTENTION-ALERT] ticker={ticker} lock_contention={lock_contention} "
                            f"total_wait_time_ms={lock_wait_time:.1f} - may indicate hot ticker or processing bottleneck"
                        )

                    # Phase 3: Use proper timestamp hierarchy for staleness calculation
                    # Prefer exchange timestamp for accurate data age, fallback to local timestamps
                    last_update = state.last_book_update_ts  # Already uses proper hierarchy
                    age_ms = (now - last_update) * 1000 if last_update > 0 else float('inf')

                    # Log timestamp source for debugging
                    timestamp_source = "exchange" if state.last_book_update_ts > 0 else "local"
                    if timestamp_source == "exchange":
                        logger.debug(
                            f"[MARKET-STATE] Using exchange timestamp for {ticker}: age={age_ms:.0f}ms"
                        )

                    # Kalshi alignment: Check market status for tradability
                    # Markets with status=closed/paused are not tradable even if books are fresh
                    market_status = getattr(state, 'status', 'unknown').lower()
                    is_tradable_status = market_status == 'open'  # Kalshi API uses "open" for active markets

                    # P1 FIX: Log separated health metrics
                    # Handle None values for spread_cents to avoid logging TypeError
                    spread_cents = health.get("spread_cents")
                    if spread_cents is None:
                        spread_cents = 0
                    logger.info(
                        "[HEALTH-SEPARATED] ticker=%s transport_healthy=%s liquidity_healthy=%s state_consistent=%s "
                        "transport_mode=%s ws_age_s=%.1f rest_age_s=%.1f spread_cents=%.0f",
                        ticker,
                        health["transport_healthy"],
                        health["liquidity_healthy"],
                        health["state_consistent"],
                        health["transport_mode"],
                        health["ws_age_s"],
                        health["rest_age_s"],
                        spread_cents
                    )

                    logger.info(
                        "[MARKET-STATE] health market=%s initialized=%s status=%s last_update_age_ms=%.0f bid=%s ask=%s mid=%s spread=%s",
                        ticker,
                        state.book_initialized,
                        market_status,
                        age_ms,
                        state.best_bid_cents,
                        state.best_ask_cents,
                        state.mid_cents,
                        state.spread_cents
                    )

                    # Calculate timing-aware staleness threshold based on minutes_to_expiry
                    minutes_to_expiry = state.seconds_to_expiry / 60.0 if hasattr(state, 'seconds_to_expiry') and state.seconds_to_expiry else None
                    staleness_threshold_ms = get_md_max_age_seconds(minutes_to_expiry) * 1000 if minutes_to_expiry is not None else MAX_BOOK_STALENESS_MS

                    # Track health status - only count as healthy if:
                    # 1. Book is fresh (within timing-aware staleness threshold)
                    # 2. Book is initialized
                    # 3. Market status is tradable (Kalshi alignment)
                    if age_ms < staleness_threshold_ms and state.book_initialized and is_tradable_status:
                        healthy_books += 1
                    else:
                        stale_books += 1
                        # If stale due to age, log queue info to detect midstream issues
                        if age_ms >= staleness_threshold_ms:
                            with self._ticker_locks_lock:
                                queue_len = len(self._delta_queues.get(ticker, []))
                            age_str = f"{age_ms:.0f}ms" if age_ms is not None and age_ms != float('inf') else "inf"
                            expiry_str = f"{minutes_to_expiry:.1f}min" if minutes_to_expiry is not None else "N/A"
                            logger.warning(
                                f"[STALE-MD-QUEUE] ticker={ticker} age_ms={age_str} "
                                f"threshold={staleness_threshold_ms:.0f}ms expiry={expiry_str} "
                                f"queue_len={queue_len} midstream_risk={queue_len > 0}"
                            )

                    # P2 Task 7: Update Prometheus staleness and health metrics
                    if market_data_staleness_seconds:
                        # Extract asset from ticker for labeling
                        asset = None
                        if ticker.startswith("KXBTC"):
                            asset = "BTC"
                        elif ticker.startswith("KXETH"):
                            asset = "ETH"
                        elif ticker.startswith("KXSOL"):
                            asset = "SOL"
                        elif ticker.startswith("KXXRP"):
                            asset = "XRP"
                        elif ticker.startswith("KXDOGE"):
                            asset = "DOGE"

                        if asset:
                            # Update staleness metric (convert ms to seconds)
                            staleness_sec = age_ms / 1000.0 if age_ms != float('inf') else 999.0
                            market_data_staleness_seconds.labels(asset=asset, ticker=ticker).set(staleness_sec)

                            # Update health status metric
                            if market_health_status:
                                # Map health to numeric: 4=healthy, 3=suspended, 2=stale, 1=degraded, 0=unhealthy
                                # Use timing-aware staleness threshold for health status
                                if age_ms < staleness_threshold_ms and state.book_initialized and is_tradable_status:
                                    health_val = 4  # healthy
                                elif not is_tradable_status:
                                    health_val = 3  # suspended (closed/paused)
                                elif age_ms >= staleness_threshold_ms:
                                    health_val = 2  # stale
                                elif not state.book_initialized:
                                    health_val = 0  # unhealthy
                                else:
                                    health_val = 1  # degraded
                                market_health_status.labels(asset=asset, ticker=ticker).set(health_val)

            # Export lag metrics from LagTracker
            if _lag_tracker_available:
                try:
                    lag_tracker = get_lag_tracker()
                    all_stats = lag_tracker.get_all_stats()
                    for asset, stats in all_stats.items():
                        if orderbook_lag_mean_ms and stats.get("count", 0) >= 100:  # Only export if we have enough samples
                            orderbook_lag_mean_ms.labels(asset=asset).set(stats["mean_ms"])
                            orderbook_lag_p95_ms.labels(asset=asset).set(stats["p95_ms"])
                            orderbook_lag_sample_count.labels(asset=asset).set(stats["count"])
                            logger.debug(
                                "[LAG-METRICS] asset=%s mean_ms=%.2f p95_ms=%.2f count=%.0f",
                                asset, stats["mean_ms"], stats["p95_ms"], stats["count"]
                            )
                except Exception as e:
                    logger.warning("[LAG-METRICS] Failed to export lag metrics: %s", e)

            # PRODUCTION AUDIT (Step 7): Green state heartbeat summary
            logger.info(
                "[GREEN-STATE-HEARTBEAT] scope_enforced=TRUE assets=BTC/ETH/SOL/XRP/DOGE timeframe=15m "
                f"total_books={total_books} healthy={healthy_books} stale={stale_books} scope_violations={scope_violations} "
                f"trading_enabled={healthy_books >= MIN_HEALTHY_BOOKS_FOR_TRADING}"
            )
        except Exception as exc:
            logger.error("[HEARTBEAT-ERROR] log_book_health crashed: %s", exc, exc_info=True)
            raise

    def is_trading_enabled(self, staleness_threshold_ms: Optional[float] = None) -> bool:
        """Check if trading is enabled based on book health.

        Uses timing-aware health thresholds via get_md_max_age_seconds():
        - Per-contract staleness thresholds based on minutes_to_expiry
        - MIN_HEALTHY_BOOKS_FOR_TRADING: Minimum healthy books required (4/5 = 80%) - PRODUCTION INVARIANT
        - HEALTH_CHECK_INITIALIZED: Require book to be initialized - PRODUCTION INVARIANT
        - HEALTH_CHECK_FRESH: Require book to be fresh - PRODUCTION INVARIANT
        - HEALTH_CHECK_BID_ASK: Require valid bid/ask (bid < ask, both not None) - PRODUCTION INVARIANT

        Args:
            staleness_threshold_ms: Override default staleness threshold (deprecated, uses timing-aware by default)

        Returns:
            True if trading is enabled, False otherwise
        """
        # Note: staleness_threshold_ms parameter is deprecated for production 15m markets
        # Timing-aware thresholds are calculated per-contract in the loop below

        healthy_count = 0
        total_count = 0
        unhealthy_reasons = []

        with self._lock:
            for ticker, state in self._states.items():
                # Only check 5-crypto/15m markets
                underlying, timeframe = _parse_market_ticker(ticker)
                if underlying not in _ALLOWED_UNDERLYINGS or timeframe not in _ALLOWED_TIMEFRAMES:
                    continue

                total_count += 1

                # CRITICAL FIX (2026-08-22): Use the authoritative execution-readiness
                # gate for every ticker.  This guarantees that the health check and the
                # order-router stale-data gate evaluate the same predicate under the same
                # monotonic clock domain.
                ready, reason = self.is_market_execution_ready(ticker)
                if ready:
                    healthy_count += 1
                else:
                    unhealthy_reasons.append(f"{ticker}:{reason}")

        # Trading is enabled if at least MIN_HEALTHY_BOOKS_FOR_TRADING are healthy
        trading_enabled = healthy_count >= MIN_HEALTHY_BOOKS_FOR_TRADING

        if not trading_enabled:
            logger.warning(
                "[TRADING-GATE] Trading DISABLED: healthy=%d/%d required=%d reasons=%s",
                healthy_count, total_count, MIN_HEALTHY_BOOKS_FOR_TRADING, unhealthy_reasons
            )

        return trading_enabled

    def is_market_execution_ready(
        self,
        ticker: str,
        max_age_seconds: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Authoritative per-ticker execution readiness gate.

        This is the single source of truth for whether a market is safe to use
        for both signal generation and order submission.  It evaluates the same
        predicate under a single monotonic clock domain.

        A ticker is execution-ready only when:
        - state exists and the orderbook is initialized;
        - the book is marked executable (duality/quality OK);
        - the data source is a post-snapshot live or bootstrap source;
        - no snapshot resync is in progress;
        - the most recent monotonic orderbook timestamp is within threshold;
        - valid, non-crossed bid/ask are present.

        Note: the orderbook timestamp (``last_book_update_ts``) is set by both
        WebSocket and REST orderbook snapshots/deltas, so a REST-only book is
        still covered.  Catalog metadata (``last_rest_update_ts``) is intentionally
        not used here because it does not reflect quote freshness.
        """
        state = self.get(ticker)
        if not state:
            return False, "STATE-NONE"

        if not state.book_initialized:
            return False, "BOOK-NOT-INITIALIZED"

        if not state.executable:
            return False, "NOT-EXECUTABLE"

        if self._needs_snapshot_resync(ticker):
            return False, "RESYNC-IN-PROGRESS"

        valid_sources = {
            "WS_LIVE",
            "WS_ORDERBOOK_DELTA_LIVE",
            "rest_refresh",
            "REST_BOOTSTRAP",
            "REST_FULL_ORDERBOOK",
            "BOOTSTRAP_VALID_BUT_UNCONFIRMED",
            "WS_CLEAN_SNAPSHOT",
            "WS_QUOTE",
        }
        if state.data_source not in valid_sources:
            return False, (
                f"DATA-SOURCE:{state.data_source} "
                f"quality={state.data_quality} "
                f"live_sequence_confirmed={getattr(state, 'live_sequence_confirmed', False)}"
            )

        if getattr(state, "data_quality", "UNKNOWN") != "GOOD":
            return False, f"DATA-QUALITY:{state.data_quality}"

        now = time.monotonic()
        last_update = state.last_book_update_ts or 0.0
        if last_update <= 0.0:
            return False, "NO-BOOK-UPDATE-TIMESTAMP"

        age_seconds = now - last_update
        if max_age_seconds is None:
            minutes_to_expiry = getattr(state, "seconds_to_expiry", None)
            mte = minutes_to_expiry / 60.0 if minutes_to_expiry is not None else None
            try:
                from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds
                max_age_seconds = get_md_max_age_seconds(mte)
            except Exception:
                max_age_seconds = 60.0
        if age_seconds > max_age_seconds:
            return False, (
                f"STALE:age={age_seconds:.1f}s>threshold={max_age_seconds:.1f}s "
                f"last_book_update_ts={state.last_book_update_ts:.1f}"
            )

        best_bid = getattr(state, "best_bid_cents", None)
        best_ask = getattr(state, "best_ask_cents", None)
        if best_bid is None or best_ask is None:
            return False, "NO-BIDASK"
        if best_bid > best_ask:
            return False, f"CROSSED-BOOK:bid={best_bid}c>ask={best_ask}c"

        return True, ""

    def is_ticker_tradeable(self, ticker: str) -> bool:
        """Compatibility wrapper around :meth:`is_market_execution_ready`."""
        ready, reason = self.is_market_execution_ready(ticker)
        if not ready:
            logger.warning("[TICKER-TRADEABLE-GATE] ticker=%s not tradeable: %s", ticker, reason)
        return ready

    def is_market_entry_ready(
        self,
        ticker: str,
        max_age_seconds: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Authoritative per-ticker *new entry* readiness gate.

        A market may be execution-ready (suitable for exits and signal display)
        but not yet confirmed for new capital commitment.  New entries require a
        contiguous live WS delta sequence (``live_sequence_confirmed=True``) in
        addition to the standard execution-ready checks.
        """
        ready, reason = self.is_market_execution_ready(ticker, max_age_seconds=max_age_seconds)
        if not ready:
            return False, reason

        state = self.get(ticker)

        # P0-1 15m crypto metadata guard: a live 15m market cannot be tradeable
        # without an authoritative strike (floor, window, or single strike).  This
        # prevents the agent from entering with a missing-strike model and surfacing
        # a generic signal rejection later.
        underlying = state.underlying if state else None
        if not underlying:
            underlying, _ = _parse_market_ticker(ticker)
        if (
            state
            and "15M" in (ticker or "").upper()
            and underlying in ("BTC", "ETH", "SOL", "XRP", "DOGE")
        ):
            strike_fields = (
                getattr(state, "floor_strike", None),
                getattr(state, "window_strike_price", None),
                getattr(state, "strike_price", None),
            )
            has_strike = any(
                v is not None and isinstance(v, (int, float)) and not isinstance(v, bool)
                and v > 0 and math.isfinite(float(v))
                for v in strike_fields
            )
            if not has_strike:
                logger.warning(
                    "[ENTRY-READY] ticker=%s METADATA-INVALID: missing floor/window/strike fields",
                    ticker,
                )
                return False, "METADATA-INVALID: missing floor/window/strike"

        if state and getattr(state, "live_sequence_confirmed", False):
            return True, ""

        # Allow new entries on an authoritative REST full snapshot only when it
        # has been explicitly attested as a recovery source; this is a degraded
        # but safe path for REST-only fallback operation.
        if state and getattr(state, "recovery_source", None) == "REST_FULL_ORDERBOOK":
            return True, ""

        return False, (
            f"NOT-LIVE-SEQUENCE-CONFIRMED "
            f"data_source={getattr(state, 'data_source', 'UNKNOWN')} "
            f"live_sequence_confirmed={getattr(state, 'live_sequence_confirmed', False)}"
        )

    def is_quote_coherent(
        self,
        ticker: str,
        max_divergence_cents: Optional[int] = None,
        max_rest_age_s: Optional[float] = None,
        max_ws_age_s: Optional[float] = None,
        rest_mandatory: Optional[bool] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Return True if the last WS quote for this ticker is usable.

        WS is the primary feed and must be present and fresh.  REST is optional:
        a fresh REST quote is used for cross-feed divergence validation, but a
        stale or missing REST quote is ignored unless
        ``MERID_QUOTE_COHERENCE_REST_MANDATORY=true`` (or ``rest_mandatory=True``).
        This prevents a slow REST orderbook refresh from blocking new entries on
        an otherwise healthy WebSocket book.

        Quote freshness is evaluated against ``last_rest_quote_update_ts`` (set
        only by REST orderbook snapshots/deltas), not the general
        ``last_rest_update_ts`` that catalog metadata refreshes.
        """
        import os

        state = self.get(ticker)
        if state is None:
            return False, "NO_STATE"

        if rest_mandatory is None:
            rest_mandatory = os.getenv("MERID_QUOTE_COHERENCE_REST_MANDATORY", "false").lower() in ("true", "1", "yes")

        max_ws_age_s = max_ws_age_s or float(os.getenv("MERID_QUOTE_COHERENCE_MAX_WS_AGE_S", "5.0"))
        max_rest_age_s = max_rest_age_s or float(os.getenv("MERID_QUOTE_COHERENCE_MAX_REST_AGE_S", "5.0"))
        max_divergence_cents = max_divergence_cents or int(os.getenv("MERID_QUOTE_COHERENCE_MAX_DIVERGENCE_CENTS", "10"))

        ws_age_s = time.monotonic() - state.last_ws_update_ts if state.last_ws_update_ts > 0 else float("inf")
        rest_age_s = time.monotonic() - state.last_rest_quote_update_ts if state.last_rest_quote_update_ts > 0 else float("inf")

        has_ws = state.last_ws_bid_cents is not None and state.last_ws_ask_cents is not None
        has_rest = state.last_rest_bid_cents is not None and state.last_rest_ask_cents is not None
        rest_usable = has_rest and rest_age_s <= max_rest_age_s

        if not has_ws and not has_rest:
            return False, "NO_QUOTES"

        # WS is mandatory.  A stale primary quote is a hard failure regardless of REST.
        if has_ws and ws_age_s > max_ws_age_s:
            return False, f"WS_STALE age_s={ws_age_s:.1f}"

        if has_rest and not rest_usable:
            if rest_mandatory:
                return False, f"REST_STALE age_s={rest_age_s:.1f}"
            logger.debug(
                "[QUOTE-COHERENCE] ticker=%s REST quote stale (%.1fs > %.1fs) and "
                "not mandatory; falling back to WS-only coherence",
                ticker, rest_age_s, max_rest_age_s,
            )
            if not has_ws:
                # No WS and stale REST means there is no fresh quote at all.
                return False, f"REST_STALE age_s={rest_age_s:.1f}"

        if not has_ws or not rest_usable:
            # Single fresh feed: no cross-feed divergence to assert.
            return True, None

        # Both feeds have fresh quotes.  Validate cross-feed divergence.
        bid_div = abs(state.last_ws_bid_cents - state.last_rest_bid_cents)
        ask_div = abs(state.last_ws_ask_cents - state.last_rest_ask_cents)
        max_div = max(bid_div, ask_div)

        if max_div > max_divergence_cents:
            return False, (
                f"DIVERGENCE {max_div}c > {max_divergence_cents}c "
                f"WS={state.last_ws_bid_cents}/{state.last_ws_ask_cents} "
                f"REST={state.last_rest_bid_cents}/{state.last_rest_ask_cents}"
            )

        return True, None

    def get_queue_lock_metrics(self, ticker: str) -> Dict[str, Any]:
        """Return per-ticker queue/lock instrumentation for boundary diagnosis.

        These metrics expose how long the batch worker is waiting on and holding
        locks, and the duration of the last batch.  The ``total_lock_wait_ms``
        field now reports the *last* observed lock wait (not a cumulative total)
        so the ENTRY-READINESS ``queue_healthy`` threshold is sensitive to
        current contention rather than an ever-growing lifetime total.
        """
        with self._ticker_locks_lock:
            queue_depth = len(self._delta_queues.get(ticker, deque()))
            last_wait = self._last_lock_wait_ms.get(ticker, 0.0)
            cumulative_wait = self._lock_wait_time_ms.get(ticker, 0.0)
            last_batch = self._last_batch_duration_ms.get(ticker, 0.0)

            # INVARIANT ALARM: high per-ticker lock wait with an empty queue is a
            # strong signal of a stuck consumer, a lock-order issue, or a stale
            # metric poisoning the health gate.
            if queue_depth == 0 and last_wait > 500.0:
                logger.warning(
                    "[QUEUE-INVARIANT] ticker=%s queue_depth=0 last_lock_wait_ms=%.1f "
                    "cumulative_lock_wait_ms=%.1f - queue empty but lock wait exceeds threshold",
                    ticker, last_wait, cumulative_wait,
                )

            return {
                "lock_contention_count": self._lock_contention_count.get(ticker, 0),
                "total_lock_wait_ms": last_wait,
                "last_batch_duration_ms": last_batch,
                "cumulative_lock_wait_ms": cumulative_wait,
                "queue_depth": queue_depth,
            }

    # ── WS path ────────────────────────────────────────────────────────

    def _validate_yes_no_invariants(self, ticker: str, yes_bid: Optional[int], yes_ask: Optional[int],
                                  no_bid: Optional[int], no_ask: Optional[int]) -> bool:
        """PRODUCTION: Validate YES/NO price consistency invariants.

        Checks:
        1. YES bid + NO ask ≈ 100¢ (within ±2¢ tolerance)
        2. YES ask + NO bid ≈ 100¢ (within ±2¢ tolerance)
        3. bid ≤ ask for both YES and NO
        4. Spread sanity (≥0, <50¢ for liquid markets)

        Returns True if all invariants pass, False if any fail.
        """
        # PRODUCTION: Tolerance for YES/NO sum invariant (±2¢)
        SUM_TOLERANCE = 2

        # Check if we have complete price data
        # Allow one-sided orderbooks (only bids or only asks) during bootstrap
        # Only validate full invariants when we have complete bid/ask data
        if not all(x is not None for x in [yes_bid, yes_ask, no_bid, no_ask]):
            logger.debug(f"[MARKET-STATE-SIDE-AWARE] Incomplete price data for {ticker}: yes_bid={yes_bid}, yes_ask={yes_ask}, no_bid={no_bid}, no_ask={no_ask} - allowing one-sided book")
            return True  # Allow one-sided books to build gradually

        # Invariant 1: YES bid + NO ask ≈ 100¢
        yes_bid_plus_no_ask = yes_bid + no_ask
        if abs(yes_bid_plus_no_ask - 100) > SUM_TOLERANCE:
            logger.critical(
                f"[PRODUCTION-INVARIANT] YES bid + NO ask sum violation: "
                f"ticker={ticker}, yes_bid={yes_bid}, no_ask={no_ask}, "
                f"sum={yes_bid_plus_no_ask}, expected≈100±{SUM_TOLERANCE}"
            )
            return False

        # Invariant 2: YES ask + NO bid ≈ 100¢
        yes_ask_plus_no_bid = yes_ask + no_bid
        if abs(yes_ask_plus_no_bid - 100) > SUM_TOLERANCE:
            logger.critical(
                f"[PRODUCTION-INVARIANT] YES ask + NO bid sum violation: "
                f"ticker={ticker}, yes_ask={yes_ask}, no_bid={no_bid}, "
                f"sum={yes_ask_plus_no_bid}, expected≈100±{SUM_TOLERANCE}"
            )
            return False

        # Invariant 3: Bid ≤ Ask ordering
        if yes_bid > yes_ask:
            logger.critical(
                f"[PRODUCTION-INVARIANT] YES bid/ask ordering violation: "
                f"ticker={ticker}, yes_bid={yes_bid}, yes_ask={yes_ask}"
            )
            return False

        if no_bid > no_ask:
            logger.critical(
                f"[PRODUCTION-INVARIANT] NO bid/ask ordering violation: "
                f"ticker={ticker}, no_bid={no_bid}, no_ask={no_ask}"
            )
            return False

        # Invariant 4: Spread sanity
        yes_spread = yes_ask - yes_bid
        no_spread = no_ask - no_bid

        # Check spread is non-negative
        if yes_spread < 0 or no_spread < 0:
            logger.critical(
                f"[PRODUCTION-INVARIANT] Negative spread: "
                f"ticker={ticker}, yes_spread={yes_spread}, no_spread={no_spread}"
            )
            return False

        # Check spread is not absurdly large (>85¢ for realistic 15m markets)
        MAX_SPREAD_CENTS = 85  # Reduced from 95 to 85 for production safety and illiquidity detection
        if yes_spread > MAX_SPREAD_CENTS or no_spread > MAX_SPREAD_CENTS:
            logger.warning(
                f"[PRODUCTION-INVARIANT] Large spread (possible illiquidity): "
                f"ticker={ticker}, yes_spread={yes_spread}, no_spread={no_spread}, max_allowed={MAX_SPREAD_CENTS}"
            )
            # Don't reject for large spread, just warn - could be genuine illiquidity

        # Invariant 5: Mid-price computation consistency
        # Calculate mids using standard formula: (bid + ask) / 2
        yes_mid = (yes_bid + yes_ask) // 2  # Integer division for cents
        no_mid = (no_bid + no_ask) // 2

        # Check YES mid + NO mid ≈ 100¢ (within ±2¢ tolerance)
        mid_sum = yes_mid + no_mid
        if abs(mid_sum - 100) > SUM_TOLERANCE:
            logger.critical(
                f"[PRODUCTION-INVARIANT] Mid-price sum violation: "
                f"ticker={ticker}, yes_mid={yes_mid}, no_mid={no_mid}, "
                f"sum={mid_sum}, expected≈100±{SUM_TOLERANCE}"
            )
            return False

        # Validate mid is within bid-ask range (should be exactly midpoint)
        if not (yes_bid <= yes_mid <= yes_ask):
            logger.critical(
                f"[PRODUCTION-INVARIANT] YES mid outside bid-ask range: "
                f"ticker={ticker}, yes_bid={yes_bid}, yes_mid={yes_mid}, yes_ask={yes_ask}"
            )
            return False

        if not (no_bid <= no_mid <= no_ask):
            logger.critical(
                f"[PRODUCTION-INVARIANT] NO mid outside bid-ask range: "
                f"ticker={ticker}, no_bid={no_bid}, no_mid={no_mid}, no_ask={no_ask}"
            )
            return False

        logger.debug(
            f"[PRODUCTION-INVARIANT] All invariants passed for {ticker}: "
            f"yes_bid={yes_bid}, yes_ask={yes_ask}, no_bid={no_bid}, no_ask={no_ask}, "
            f"yes_spread={yes_spread}, no_spread={no_spread}, yes_mid={yes_mid}, no_mid={no_mid}"
        )

        return True

    async def _sync_invariant_violation_with_rest(self, ticker: str) -> None:
        """PRODUCTION: Sync invariant violations with REST snapshot recovery.

        When YES/NO invariants are violated, fetch a fresh REST snapshot to restore
        data consistency and mark the ticker as rebuilding until sync completes.
        """
        try:
            logger.info("[PRODUCTION-SYNC-SIDE-AWARE] ENTRY: Starting REST sync for invariant violation: %s", ticker)

            # Mark ticker as rebuilding to prevent trading during sync
            with self._lock:
                state = self._get_or_create(ticker)
                state.executable = False
                state.book_initialized = False
                # 2026-08-24: Clear snapshot completion while we refetch; a stale
                # completed flag could let entries through before the new book is
                # validated.
                self._set_snapshot_complete(ticker, False, "rest_sync_started")

            # Fetch fresh REST snapshot through the normalized execution port.
            from merid.event_venues.kalshi.port import get_kalshi_execution_port
            port = get_kalshi_execution_port()

            ob_result = await asyncio.wait_for(
                port.get_orderbook(ticker),
                timeout=5.0
            )

            if ob_result.success:
                # Port returns price in cents; convert to dollars for the snapshot.
                yes_levels = [[level.price_cents / 100.0, float(level.size)] for level in ob_result.yes_levels]
                no_levels = [[level.price_cents / 100.0, float(level.size)] for level in ob_result.no_levels]

                # Create snapshot message
                snapshot_msg = {
                    "ticker": ticker,
                    "type": "orderbook_snapshot",
                    "no": no_levels,
                    "yes": yes_levels,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Apply snapshot directly (bypass invariant validation to avoid loop)
                logger.info(f"[PRODUCTION-SYNC-SIDE-AWARE] Applying REST snapshot for {ticker}")

                # Apply snapshot to orderbook
                with self._lock:
                    self._ob.apply_snapshot(ticker, snapshot_msg)

                    # Update state from fresh book
                    state = self._get_or_create(ticker)
                    prior_quality = state.data_quality
                    prior_transition = state.transition

                    book = self._ob.get_book(ticker)
                    if book and book.initialized:
                        self._sync_book_fields(state, book, ticker, via="rest_bootstrap")
                        self._sync_unified_book(ticker, state)

                        # Validate the REST snapshot itself
                        yes_bid_ask = book.get_best_bid()
                        yes_ask = book.get_best_ask()
                        yes_bid_cents = yes_bid_ask[0] if yes_bid_ask else None
                        yes_ask_cents = yes_ask[0] if yes_ask else None

                        # CRITICAL FIX (2026-08-01): Extract actual NO bid/ask from book instead of deriving from YES
                        # The book now has actual NO bid data from no_dollars, so we should use it directly
                        # For validation, we need NO-space prices (not YES-space derived prices)
                        # NO-space: NO bid is the highest NO price, NO ask is the lowest NO price
                        # Since book.get_best_bid() returns YES-space, we need to get NO-side best bid/ask
                        # For now, derive from YES-space (this is acceptable for validation only)
                        # TODO: Add book.get_best_no_bid() and book.get_best_no_ask() methods to LocalOrderbook
                        no_ask_cents = 100 - yes_bid_cents if yes_bid_cents is not None else None
                        no_bid_cents = 100 - yes_ask_cents if yes_ask_cents is not None else None

                        if self._validate_yes_no_invariants(ticker, yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents):
                            # A fresh REST snapshot is an authoritative recovery source.
                            state.data_source = "REST_FULL_ORDERBOOK"
                            self._attest_state_recovery(
                                state,
                                "REST_FULL_ORDERBOOK",
                                prior_quality=prior_quality,
                                prior_transition=prior_transition,
                            )
                            self._set_snapshot_complete(
                                ticker, True, "rest_sync_snapshot_applied"
                            )
                            logger.info(f"[PRODUCTION-SYNC] REST sync completed successfully for {ticker}")
                        else:
                            logger.error(f"[PRODUCTION-SYNC-SIDE-AWARE] REST snapshot also violates invariants for {ticker}")
                            # Keep non-executable - will retry on next update
                            state.data_quality = "INVALID"
                            state.executable = False
                            state.book_initialized = False
                            state.transition = "INVALID_REST_SYNC"
                            state.invalidation_cause = "INVALID_REST_SYNC"
                            state.recovery_required_source = "FULL_SNAPSHOT"
                            self._set_snapshot_complete(
                                ticker, False, "rest_sync_snapshot_invalid"
                            )
                    else:
                        logger.error(f"[PRODUCTION-SYNC] REST snapshot failed to initialize book for {ticker}")

            else:
                logger.error(f"[PRODUCTION-SYNC] REST sync failed for {ticker}: {ob_result.error}")

        except Exception as e:
            logger.error(f"[PRODUCTION-SYNC] Exception during invariant sync for {ticker}: {type(e).__name__}: {e}")

    def apply_orderbook_message(self, msg: Dict[str, Any], via: str = "unknown") -> Optional[KalshiMarketState]:
        """Apply a WS ``orderbook_snapshot`` or ``orderbook_delta`` message.

        Updates the internal ``LocalOrderbook`` for the ticker, then
        syncs the book-owned fields of the corresponding
        ``KalshiMarketState``.

        Phase 3: Enhanced with proper timestamp hierarchy for data freshness.

        Args:
            msg: Raw parsed WS message dict (already JSON-decoded).
            via: Provenance tag ("bridge_queue", "rest_snapshot", "manual", "unknown").

        Returns:
            Updated ``KalshiMarketState``, or ``None`` if the message
            type is not an orderbook message or the ticker is missing.
        """
        channel = msg.get("type") or msg.get("channel") or msg.get("msg_type") or ""
        # P0 FIX: Extract ticker from nested msg structure (Kalshi WS format)
        # The ws_bridge forwards events with nested msg field containing market_ticker
        payload = msg.get("msg", msg) if "msg" in msg else msg
        ticker = payload.get("market_ticker") or payload.get("ticker") or payload.get("series_ticker") or ""
        msg_keys = list(msg.keys()) if isinstance(msg, dict) else "N/A"

        # P0 FIX: Use explicit via parameter for provenance tracking
        # Dev mode: warn on unknown via values to catch missing provenance tags
        _DEV_MODE = os.getenv("MERID_DEV_MODE", "false").lower() in ("true", "1", "yes")
        if _DEV_MODE and via == "unknown":
            logger.warning(
                "[WS-MSTATE-INGEST] apply_orderbook_message called with via=unknown: ticker=%s, channel=%s, msg_keys=%s",
                ticker,
                channel,
                msg_keys,
            )
        # DISABLED: Excessive logging - 1 log line per orderbook message (80K+ events = massive log volume)
        # This detects if any path is bypassing the bridge queue
        # logger.info(
        #     "[WS-MSTATE-INGEST] via=%s type=%s ticker=%s",
        #     via, channel, ticker
        # )

        # Note: delta_fp messages without bids/asks are valid Kalshi orderbook deltas
        # They are applied to the internal book representation in apply_delta

        # DISABLED: Excessive diagnostic logging - causing slow WS callbacks
        # logger.debug(
        #     "[market-state] apply_orderbook_message: RAW msg keys=%s, channel=%s, ticker=%s",
        #     msg_keys, channel, ticker
        # )

        # Try multiple possible channel/type field names
        channel = msg.get("type") or msg.get("channel") or msg.get("msg_type") or ""

        # Diagnostic logging for debugging missing prices
        if not ticker:
            logger.error(
                "[market-state] apply_orderbook_message REJECTED: missing ticker, channel=%s, msg keys=%s",
                channel, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            return None

        # DISABLED: Excessive logging - 1 log line per orderbook message (80K+ events = massive log volume)
        # logger.debug(
        #     "[market-state] apply_orderbook_message RECEIVED ticker=%s channel=%s",
        #     ticker, channel
        # )

        # DISABLED: Excessive diagnostic logging for snapshot/delta messages - causing slow WS callbacks
        # if "snapshot" in channel.lower() or "delta" in channel.lower():
        #     import json
        #     msg_str = json.dumps(msg, default=str)
        #     logger.info(
        #         "[WS-RAW] channel=%s ticker=%s first_200_bytes=%s",
        #         channel, ticker, msg_str[:200]
        #     )
        #     # DIAGNOSTIC: Log payload structure to understand nested format
        #     if "msg" in msg and isinstance(msg["msg"], dict):
        #         payload_keys = list(msg["msg"].keys())
        #         logger.info(
        #             "[WS-RAW-PAYLOAD] channel=%s ticker=%s payload_keys=%s",
        #             channel, ticker, payload_keys
        #         )
        #         # Check for bids/asks in payload
        #         has_bids = "bids" in msg["msg"]
        #         has_asks = "asks" in msg["msg"]
        #         has_delta_fp = "delta_fp" in msg["msg"]
        #         logger.info(
        #             "[WS-RAW-PAYLOAD] channel=%s ticker=%s has_bids=%s has_asks=%s has_delta_fp=%s",
        #             channel, ticker, has_bids, has_asks, has_delta_fp
        #         )

        # ORDERBOOK-SHAPE-ASSERTION: Validate message shape against canonical schema
        # This catches malformed messages before they reach LocalOrderbook
        # P0 FIX: Skip validation for nested payload format - let LocalOrderbook handle it
        # The validation functions expect flat message structure, but Kalshi WS uses nested msg
        # We'll rely on LocalOrderbook's internal validation instead
        try:
            from merid.event_venues.kalshi.orderbook import (
                validate_orderbook_snapshot,
                validate_orderbook_delta,
                KalshiOrderbookShapeError
            )

            # Only validate if message is flat (no nested msg)
            if "msg" not in msg:
                if "snapshot" in channel.lower() or (channel == "" and "yes" in msg and "no" in msg):
                    validate_orderbook_snapshot(msg)
                elif "delta" in channel.lower():
                    validate_orderbook_delta(msg)
                    # DISABLED: Excessive logging - 1 log line per delta (20K+ events = massive log volume)
                    # logger.info(
                    #     "[market-state] Delta validation passed for ticker=%s channel=%s",
                    #     ticker, channel
                    # )
        except KalshiOrderbookShapeError as e:
            logger.error(
                f"[ORDERBOOK-SHAPE-ERROR] KalshiMarketStateStore rejecting malformed orderbook message: {e}. "
                f"ticker={ticker}, channel={channel}, msg_keys={list(msg.keys()) if isinstance(msg, dict) else 'N/A'}"
            )
            return None
        except Exception as e:
            logger.error(
                f"[ORDERBOOK-SHAPE-ERROR] Unexpected error during orderbook shape validation: {e}. "
                f"ticker={ticker}, channel={channel}"
            )
            return None

        # PERFORMANCE FIX: Removed delta throttling to eliminate sequence gaps
        # Research shows any throttling causes sequence gaps in high-frequency trading
        # Even 5ms throttling was causing 200,000+ sequence gaps
        # Event loop will handle bursts via async queue processing
        # If event loop overload occurs, we'll add adaptive throttling based on queue size

        # PERFORMANCE FIX: Cache scope validation results to avoid repeated checks
        # Asset extraction and validation adds ~5-10ms per callback
        # We'll validate once per ticker and cache the result
        if TRADING_SCOPE_AVAILABLE:
            # Check cache first
            if ticker in self._scope_validation_cache:
                is_valid, reason = self._scope_validation_cache[ticker]
                if not is_valid:
                    return None
            else:
                # Extract asset from ticker
                asset = None
                if ticker.startswith("KXBTC"):
                    asset = "BTC"
                elif ticker.startswith("KXETH"):
                    asset = "ETH"
                elif ticker.startswith("KXSOL"):
                    asset = "SOL"
                elif ticker.startswith("KXXRP"):
                    asset = "XRP"
                elif ticker.startswith("KXDOGE"):
                    asset = "DOGE"

                # Check if asset is allowed
                if asset and not validate_asset_for_trading(asset):
                    self._scope_validation_cache[ticker] = (False, "asset_not_whitelisted")
                    logger.warning(
                        f"[SCOPE_FILTER] WS orderbook rejected: asset={asset} not in production whitelist | ticker={ticker}"
                    )
                    return None

                # Check if ticker is 15m series
                if not validate_series_ticker_for_trading(ticker):
                    self._scope_validation_cache[ticker] = (False, "not_15m_series")
                    logger.warning(
                        f"[SCOPE_FILTER] WS orderbook rejected: ticker={ticker} not 15m timeframe"
                    )
                    return None

                # Cache valid result
                self._scope_validation_cache[ticker] = (True, None)

        # Accept messages with empty channel if they have orderbook data (msg field with bids/asks or yes/no)
        # This handles cases where the channel field is missing but the payload is valid
        if channel not in ("orderbook_snapshot", "orderbook_delta"):
            # Check if this looks like an orderbook message by inspecting the payload
            # msg is already the msg_body (nested structure extracted by ws_bridge)
            has_bids = "bids" in msg or isinstance(msg.get("bids"), list)
            has_asks = "asks" in msg or isinstance(msg.get("asks"), list)
            # Kalshi uses yes/no instead of bids/asks
            has_yes = "yes" in msg or isinstance(msg.get("yes"), list)
            has_no = "no" in msg or isinstance(msg.get("no"), list)
            # Kalshi delta_fp messages are valid orderbook deltas (have delta_fp + side + price_dollars)
            has_delta_fp = "delta_fp" in msg and "side" in msg

            # CRITICAL DIAGNOSTIC: Log message structure to understand why batch worker isn't starting
            logger.debug(
                "[market-state] apply_orderbook_message: channel=%s ticker=%s keys=%s has_bids=%s has_asks=%s has_yes=%s has_no=%s has_delta_fp=%s",
                channel, ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A",
                has_bids, has_asks, has_yes, has_no, has_delta_fp
            )

            if has_bids or has_asks or has_yes or has_no or has_delta_fp:
                # Treat as orderbook_delta if it has book data or delta_fp
                channel = "orderbook_delta"
                logger.debug(
                    "[market-state] apply_orderbook_message: inferred channel=orderbook_delta from payload (bids=%s, asks=%s, yes=%s, no=%s, delta_fp=%s)",
                    has_bids, has_asks, has_yes, has_no, has_delta_fp
                )
            else:
                # These might be individual price updates (delta_fp + side) rather than full orderbooks
                # Log the actual message to understand the format
                logger.warning(
                    "[market-state] apply_orderbook_message REJECTED: unexpected channel=%s, ticker=%s, msg keys=%s, payload=%s",
                    channel, ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A",
                    {k: v for k, v in msg.items() if k not in ['msg']} if isinstance(msg, dict) else "N/A"
                )
                return None

        # FINAL CHECK: Snapshots must have bids/asks OR no/yes (Kalshi format), deltas may have price_dollars/delta_fp/side
        # This catches cases where the WS client forwards raw messages with wrong type field
        payload = msg.get("msg", msg)
        has_bids = "bids" in payload or isinstance(payload.get("bids"), list)
        has_asks = "asks" in payload or isinstance(payload.get("asks"), list)
        # Kalshi snapshot format uses "no"/"yes" instead of "bids"/"asks"
        has_no = "no" in payload or isinstance(payload.get("no"), list)
        has_yes = "yes" in payload or isinstance(payload.get("yes"), list)
        has_delta_fields = "delta_fp" in payload and "price_dollars" in payload and "side" in payload

        if channel == "orderbook_snapshot" and not ((has_bids or has_asks) or (has_no or has_yes)):
            logger.warning(
                "[market-state] apply_orderbook_message REJECTED: snapshot missing bids/asks/no/yes, ticker=%s, msg keys=%s",
                ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            return None

        if channel == "orderbook_delta" and not (has_bids or has_asks or has_no or has_yes or has_delta_fields):
            logger.warning(
                "[market-state] apply_orderbook_message REJECTED: delta missing bids/asks/no/yes/delta_fields, ticker=%s, msg keys=%s",
                ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            return None

        # MARKET-LEVEL FILTER: Only accept 5 crypto underlyings on 15m timeframe
        # DISABLED IN TESTS: Set MERID_ENABLE_SCOPE_VALIDATION=true to enforce
        if TRADING_SCOPE_AVAILABLE:
            underlying, timeframe = _parse_market_ticker(ticker)
            if underlying not in _ALLOWED_UNDERLYINGS:
                logger.warning(
                    "[market-state] REJECTED: unsupported underlying=%s ticker=%s (allowed=%s)",
                    underlying, ticker, _ALLOWED_UNDERLYINGS
                )
                return None
            if timeframe not in _ALLOWED_TIMEFRAMES:
                logger.warning(
                    "[market-state] REJECTED: unsupported timeframe=%s ticker=%s (allowed=%s)",
                    timeframe, ticker, _ALLOWED_TIMEFRAMES
                )
                return None

        # LOCK CONTENTION FIX: Use queue-based approach instead of direct lock acquisition
        # Enqueue deltas for batch processing, apply snapshots directly
        if channel == "orderbook_delta":
            # DIAGNOSTIC: Log delta enqueue
            payload = msg.get("msg", msg)
            logger.debug(
                "[OB-APPLY] ticker=%s channel=%s enqueuing_delta=True batch_worker_running=%s",
                ticker, channel, self._batch_worker_running
            )

            # Start batch worker if not running
            if not self._batch_worker_running:
                self._start_batch_worker()

            # Enqueue delta for batch processing
            enqueued = self._enqueue_delta(ticker, payload)
            if not enqueued:
                # Queue overflow - mark as SUSPECT and trigger REST bootstrap
                state = self._states.get(ticker)
                if state:
                    state.book_consistency = "SUSPECT"
                    logger.warning(
                        "[BOOK-CONSISTENCY] ticker=%s marked as SUSPECT due to queue overflow - will trigger REST bootstrap",
                        ticker
                    )
                    try:
                        import asyncio
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(self._sync_invariant_violation_with_rest(ticker))
                    except Exception as e:
                        logger.error("[market-state] Failed to schedule REST bootstrap for %s: %s", ticker, e, exc_info=True)
            else:
                # DIAGNOSTIC: Log successful enqueue
                queue = self._delta_queues.get(ticker)
                queue_size = len(queue) if queue else 0
                logger.debug(
                    "[OB-APPLY] ticker=%s delta_enqueued=True queue_size=%d",
                    ticker, queue_size
                )
            return None

        # For snapshots, apply directly (they're less frequent and need immediate effect)
        # Start batch worker if not running (for any subsequent deltas)
        if not self._batch_worker_running:
            self._start_batch_worker()

        # Apply snapshots directly under lock (they're infrequent)
        if channel == "orderbook_snapshot":
            ticker_lock = self._get_ticker_lock(ticker)
            with ticker_lock:
                payload = msg.get("msg", msg)

                # CRITICAL FIX (2026-08-01): Validate snapshot BEFORE applying to prevent state corruption
                # Check if snapshot has any orderbook data
                yes_levels = payload.get("yes", [])
                no_levels = payload.get("no", [])
                yes_count = len(yes_levels) if yes_levels else 0
                no_count = len(no_levels) if no_levels else 0

                # EMPTY-SNAPSHOT POLICY: A completely empty snapshot is valid for a
                # contract that has just opened and has no resting orders yet.  We
                # must allow the LocalOrderbook to become initialized so that the
                # first WebSocket orderbook deltas can be applied.  If a book is
                # already initialized, an empty snapshot is suspect and is ignored
                # to avoid overwriting live data.
                ob = self._ob.get_book(ticker)
                if yes_count == 0 and no_count == 0 and ob.initialized:
                    logger.warning(
                        "[EMPTY-BOOK-REJECTION] Ignoring empty snapshot for %s: existing book already initialized",
                        ticker,
                    )
                    return None

                # Apply snapshot (empty snapshots are accepted for uninitialized books)
                self._ob.apply_snapshot(ticker, payload)

                # Log book state after snapshot for validation
                book = self._ob.get_book(ticker)
                if book and yes_count == 0 and no_count == 0:
                    logger.info(
                        "[EMPTY-BOOK-INIT] %s initialized with empty orderbook; expecting deltas to populate",
                        ticker,
                    )

                # CRITICAL FIX (2026-08-01): Clear pending deltas after snapshot application
                # The snapshot is the source of truth - replaying pending deltas can apply stale data
                # to fresh state, causing orderbook corruption. Deltas received after the snapshot
                # will be processed normally through the batch worker.
                with self._ticker_locks_lock:
                    pending_count = len(self._pending_deltas.get(ticker, []))
                    if pending_count > 0:
                        logger.info(
                            "[SNAPSHOT-DELTA-CLEAR] ticker=%s cleared %d pending deltas after snapshot (preventing stale data application)",
                            ticker, pending_count
                        )
                        self._pending_deltas.pop(ticker, None)

                # Sync state and mark as recovered (only if the snapshot is clean).
                # A clean snapshot is authoritative: reset any previous SUSPECT/INVALID
                # state, then let _sync_book_fields downgrade again if the new book still
                # violates duality or is crossed/locked.
                state = self._get_or_create(ticker)
                prior_quality = state.data_quality
                prior_transition = state.transition

                source = self._resolve_book_source(via, "orderbook_snapshot")
                state.data_source = source

                self._sync_book_fields(state, self._ob.get_book(ticker), ticker, via)
                self._sync_unified_book(ticker, state)

                # A clean, authoritative snapshot can lift a circuit breaker;
                # a bootstrap-only snapshot (unconfirmed WS snapshot) cannot.
                if state.data_quality not in ("SUSPECT", "INVALID"):
                    self._attest_state_recovery(
                        state,
                        source,
                        prior_quality=prior_quality,
                        prior_transition=prior_transition,
                    )
                    # A successful snapshot resets the inversion counter.
                    if hasattr(self, "_book_inversion_counts"):
                        self._book_inversion_counts.pop(ticker, None)
                else:
                    # _sync_book_fields already set the appropriate SUSPECT/INVALID
                    # data_quality and executable flag; nothing to attest.
                    pass

                # Update explicit BookHealth state machine.
                if state.data_quality in ("SUSPECT", "INVALID"):
                    self._set_book_health(
                        ticker,
                        BookHealth.INVALID,
                        f"snapshot_quality={state.data_quality} transition={state.transition}",
                    )
                    if state.recovery_required_source:
                        self._set_book_health(ticker, BookHealth.RESYNC_REQUESTED, "invalid_snapshot_requires_resync")
                elif state.recovery_attested and state.live_sequence_confirmed:
                    self._set_book_health(ticker, BookHealth.LIVE, "snapshot_recovered_with_live_sequence")
                elif state.recovery_attested:
                    self._set_book_health(ticker, BookHealth.RECOVERED, "authoritative_snapshot_restored")
                else:
                    self._set_book_health(ticker, BookHealth.SNAPSHOT_RECEIVED, f"source={source}")

                # 2026-08-24: Persist or reset the snapshot completion flag.  A clean
                # full-book snapshot sets it; an invalid snapshot clears it so entries
                # remain blocked until the next clean snapshot.
                if state.data_quality in ("SUSPECT", "INVALID"):
                    self._set_snapshot_complete(
                        ticker, False, f"ws_orderbook_snapshot_invalid source={source}"
                    )
                    self._check_snapshot_timeout(ticker)
                else:
                    self._set_snapshot_complete(
                        ticker, True, f"ws_orderbook_snapshot_applied source={source}"
                    )

                # CRITICAL FIX: Ensure transport_mode is set to WS for WS snapshots
                # This aligns with the data_source being WS-based
                if via == "bridge_queue":
                    state.transport_mode = "ws"
                elif via.startswith("rest"):
                    state.transport_mode = "rest"

                # CRITICAL FIX (2026-08-02): Update book freshness tracker from orderbook data
                # This prevents the DEAD state from blocking all trading when valid data exists
                try:
                    from merid.event_venues.kalshi.book_freshness import get_book_freshness_tracker
                    freshness_tracker = get_book_freshness_tracker()

                    # Extract timestamp from message
                    timestamp_str = payload.get("timestamp") or msg.get("timestamp")
                    received_ts = None
                    if timestamp_str:
                        try:
                            from datetime import datetime
                            # Parse ISO format timestamp
                            if isinstance(timestamp_str, str):
                                received_ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).timestamp()
                        except Exception as ts_error:
                            logger.debug("[BOOK-FRESHNESS] Failed to parse timestamp for %s: %s", ticker, ts_error)

                    # Update freshness state based on data source
                    if via == "bridge_queue":
                        # WebSocket data
                        freshness_tracker.update_from_ws(ticker, exchange_ts=None, received_ts=received_ts)
                    else:
                        # REST data (bootstrap, fallback, polling)
                        is_fallback = via in ("ws_fallback", "rest_polling")
                        freshness_tracker.update_from_rest(ticker, received_ts=received_ts, is_fallback=is_fallback)

                    if logger.isEnabledFor(10):
                        logger.debug(
                            "[BOOK-FRESHNESS] Updated state for %s via=%s state=%s",
                            ticker,
                            via,
                            freshness_tracker.get_state(ticker).state.value,
                        )
                except ImportError:
                    logger.warning("[BOOK-FRESHNESS] book_freshness module not available, skipping freshness update")
                except Exception as e:
                    logger.error("[BOOK-FRESHNESS] Failed to update freshness state for %s: %s", ticker, e)

                # Log raw book after snapshot
                book = self._ob.get_book(ticker)
                if book and book.initialized:
                    try:
                        yes_levels = list(book.yes_levels) if book.yes_levels and not isinstance(book.yes_levels, slice) else []
                        no_levels = list(book.no_levels) if book.no_levels and not isinstance(book.no_levels, slice) else []
                    except (TypeError, AttributeError):
                        yes_levels = []
                        no_levels = []
                    yes_raw = yes_levels[:5] if yes_levels else []
                    no_raw = no_levels[:5] if no_levels else []
                    logger.debug(
                        "[KALSHI-RAW-BOOK] ticker=%s yes_raw=%s no_raw=%s side=%s source=WS",
                        ticker, yes_raw, no_raw, channel
                    )

                # Log parsed book after computing top prices
                if state.best_bid_cents is not None or state.best_ask_cents is not None:
                    logger.debug(
                        "[KALSHI-PARSED-BOOK] ticker=%s yes_best=%s no_best=%s source=WS",
                        ticker, state.best_bid_cents, state.best_ask_cents
                    )

                # CRITICAL FIX: Return the updated state after snapshot application
                return state
        else:
            return None

    # ── REST path ──────────────────────────────────────────────────────

    def apply_rest_market(self, data: Dict[str, Any]) -> Optional[KalshiMarketState]:
        """Merge REST ``GET /markets`` fields into a ``KalshiMarketState``.

        Owns: ``volume_24h``, ``open_interest``, ``notional_value_cents``,
        all three expiry fields, and strike/underlying metadata.

        ``liquidity`` / ``liquidity_dollars`` are intentionally ignored —
        they are deprecated and always return 0.  Use ``top_of_book_size``
        and ``depth_10c`` (book-computed) instead.

        Args:
            data: Raw market dict from the Kalshi REST API.  SDK
                  ``Market`` objects should be converted via
                  ``model.model_dump()`` or ``vars(model)`` first.

        Returns:
            Updated ``KalshiMarketState``, or ``None`` if no ticker.
        """
        import threading
        ticker = data.get("ticker")
        if not ticker:
            return None

        logger.info("[APPLY-REST-MARKET] ENTER ticker=%s thread=%s states_count=%d",
                   ticker, threading.current_thread().name, len(self._states))

        # CRITICAL FIX: Call _get_or_create directly without outer lock
        # _get_or_create already handles thread safety with its own global_lock
        # This prevents deadlock when catalog refresh thread calls apply_rest_market
        state = self._get_or_create(ticker)

        v24 = data.get("volume_24h")
        if v24 is not None:
            state.volume_24h = int(v24)

        oi = data.get("open_interest")
        if oi is not None:
            state.open_interest = int(oi)

        nv = data.get("notional_value")
        if nv is not None:
            state.notional_value_cents = int(nv)

        for attr, key in (
            ("expiration_time", "expiration_time"),
            ("expected_expiration_time", "expected_expiration_time"),
            ("latest_expiration_time", "latest_expiration_time"),
        ):
            val = data.get(key)
            if val:
                setattr(state, attr, str(val))

        # NEW: Underlying asset and strike info (from catalog)
        underlying = data.get("underlying")
        if underlying:
            state.underlying = underlying

        # PRODUCTION FIX (2026-05-18): Set market status for health check
        # Default to "open" if not provided - markets with orderbook data should be tradable
        status = data.get("status", "open").lower()
        if hasattr(state, 'status'):
            state.status = status

        # Capture the exchange shard index for sharded order routing.
        # Crypto 15m markets live on exchange_index=2; routing without this lands
        # on the default shard and returns 404 market_not_found.
        exchange_index = data.get("exchange_index")
        if exchange_index is not None:
            try:
                state.exchange_index = int(exchange_index)
            except (TypeError, ValueError):
                pass

        strike = data.get("strike_price")
        if strike is not None:
            state.strike_price = float(strike)

        floor = data.get("floor_strike")
        if floor is not None:
            state.floor_strike = float(floor)
            # CRITICAL: Capture window strike price for 15-minute markets
            # For 15m UP/DOWN markets, floor_strike is Kalshi's reference price at window start
            # This is the authoritative source for strike price determination
            if state.window_strike_price is None or state.window_strike_source == "":
                state.window_strike_price = float(floor)
                state.window_strike_source = "kalshi_floor_strike"
                state.window_strike_ts = time.time()
                logger.info(
                    "[WINDOW-STRIKE-CAPTURE] ticker=%s floor_strike=%.4f captured as window_strike_price (source=kalshi_floor_strike)",
                    ticker, float(floor)
                )

        cap = data.get("cap_strike")
        if cap is not None:
            state.cap_strike = float(cap)

        # External spot price (from CF Benchmarks RTI or other feed)
        spot = data.get("external_spot")
        if spot is not None:
            state.external_spot = float(spot)

            # CRITICAL: 2026-07-01 - Update strike divergence tracking
            # Calculate how far spot has moved from window strike price
            if state.window_strike_price is not None and state.window_strike_price > 0:
                current_spot = float(spot)
            strike = state.window_strike_price
            divergence_pct = abs((current_spot - strike) / strike) * 100

            # Update current divergence
            state.current_divergence_pct = divergence_pct
            state.last_divergence_update_ts = time.time()

            # Track maximum divergence
            if divergence_pct > state.max_divergence_pct:
                state.max_divergence_pct = divergence_pct

            # Add to history (keep last 180 points = 15 minutes at 5-second cadence)
            state.strike_divergence_history.append((time.time(), divergence_pct, current_spot))
            if len(state.strike_divergence_history) > 180:
                state.strike_divergence_history = state.strike_divergence_history[-180:]

            # Divergence alerts (2026 best practice from Buildix)
            if divergence_pct >= 10.0:
                logger.warning(
                    "[DIVERGENCE-CRITICAL] ticker=%s strike=%.4f spot=%.4f divergence=%.2f%% (threshold=10%%)",
                    ticker, strike, current_spot, divergence_pct
                )
            elif divergence_pct >= 5.0:
                logger.info(
                    "[DIVERGENCE-WARNING] ticker=%s strike=%.4f spot=%.4f divergence=%.2f%% (threshold=5%%)",
                    ticker, strike, current_spot, divergence_pct
                )

        # REST updated_time cross-check: track exchange timestamp for lag detection
        updated_time = data.get("updated_time")
        if updated_time:
            try:
                # Parse ISO timestamp to Unix timestamp
                from datetime import datetime
                if isinstance(updated_time, str):
                    # Handle ISO format with or without Z suffix
                    if updated_time.endswith('Z'):
                        updated_time = updated_time[:-1] + '+00:00'
                    dt = datetime.fromisoformat(updated_time)
                    self._rest_updated_time[ticker] = dt.timestamp()
                    self._rest_updated_time_fetched[ticker] = time.time()

                    # Calculate user timestamp lag for lag classification
                    now_wall = time.time()
                    self._rest_user_ts_lag_s = now_wall - dt.timestamp()

                    # Check for WS lag
                    lag = self._check_rest_updated_time_lag(ticker)
                    if lag is not None:
                        logger.warning(
                            "[REST-CROSS-CHECK] ticker=%s WS lag detected during REST fetch lag_s=%.1f",
                            ticker, lag
                        )
            except Exception as e:
                logger.warning("[APPLY-REST-MARKET] Failed to parse updated_time for %s: %s", ticker, e)

        # General REST metadata timestamp.  This must NOT update
        # last_rest_quote_update_ts / last_rest_bid/ask_cents — those are owned
        # exclusively by REST orderbook snapshots applied through _sync_book_fields.
        state.last_rest_update_ts = time.monotonic()
        logger.info("[APPLY-REST-MARKET] BEFORE _recompute_seconds_to_expiry ticker=%s", ticker)
        _recompute_seconds_to_expiry(state)
        logger.info("[APPLY-REST-MARKET] AFTER _recompute_seconds_to_expiry ticker=%s", ticker)

        logger.info("[APPLY-REST-MARKET] BEFORE _sync_unified_rest ticker=%s", ticker)
        self._sync_unified_rest(ticker, state)
        logger.info("[APPLY-REST-MARKET] AFTER _sync_unified_rest ticker=%s", ticker)

        # Check REST staleness and mark untradeable if too old
        # CRITICAL FIX (2026-08-03): Also check the EXCHANGE data age. Previously this
        # only measured time-since-we-fetched (set to monotonic() a few lines above,
        # so the check could never fire) - hours-old REST data counted as fresh as
        # long as we re-fetched it recently.
        rest_age = time.monotonic() - state.last_rest_update_ts
        exchange_updated = self._rest_updated_time.get(ticker)
        exchange_data_age = (time.time() - exchange_updated) if exchange_updated else None
        if exchange_data_age is not None and exchange_data_age > _MAX_REST_AGE_SECONDS:
            logger.warning(
                "[MARKET-STATE] rest_exchange_data_stale market=%s exchange_age_sec=%.0f fetch_age_sec=%.1f threshold=%s - marking untradeable",
                ticker, exchange_data_age, rest_age, _MAX_REST_AGE_SECONDS
            )
            state.can_trade = False
            state.confidence = 0.0
        elif rest_age > _MAX_REST_AGE_SECONDS:
            logger.warning(
                "[MARKET-STATE] rest_price_stale market=%s age_sec=%.0f threshold=%s - marking untradeable",
                ticker, rest_age, _MAX_REST_AGE_SECONDS
            )
            state.can_trade = False
            state.confidence = 0.0

        # CRITICAL FIX (2026-08-02): Update book freshness tracker from REST market data
        # This ensures REST-based updates also refresh the state machine
        try:
            from merid.event_venues.kalshi.book_freshness import get_book_freshness_tracker
            freshness_tracker = get_book_freshness_tracker()
            freshness_tracker.update_from_rest(ticker, received_ts=time.time(), is_fallback=False)
            logger.debug(f"[BOOK-FRESHNESS] Updated state for {ticker} from REST market data")
        except ImportError:
            logger.warning("[BOOK-FRESHNESS] book_freshness module not available, skipping freshness update")
        except Exception as e:
            logger.error(f"[BOOK-FRESHNESS] Failed to update freshness state for {ticker} from REST market: {e}")

        # CRITICAL FIX (2026-08-02): Skip callback notification for catalog feed
        # This prevents deadlock when catalog refresh thread calls apply_rest_market
        # Callbacks will be notified by WS bridge updates instead
        logger.info("[APPLY-REST-MARKET] EXIT ticker=%s (skipping callback notification for catalog feed)", ticker)
        return state

    # ── Quote path (from WS QuoteEvent) ─────────────────────────────────

    def apply_quote(
        self,
        ticker: str,
        *,
        bid_cents: Optional[int] = None,
        ask_cents: Optional[int] = None,
        last_cents: Optional[int] = None,
        volume: Optional[int] = None,
    ) -> Optional[KalshiMarketState]:
        """Lightweight update from a WS quote/ticker channel event.

        Stores the most recent ticker BBO as a fallback.  The ticker quote is
        used as a redundant source of top-of-book prices when the orderbook
        channel is one-sided or crossed due to one-sided delta streams.
        """
        if not ticker:
            return None
        with self._lock:
            state = self._get_or_create(ticker)

            if volume is not None:
                state.volume_24h = int(volume)

            now = time.monotonic()

            # Always record the latest quote for potential fallback use.
            # These are diagnostic fields only and must never overwrite executable
            # BBO on an already-initialized or invalid book.
            if bid_cents is not None:
                state.quoted_bid_cents = bid_cents
                state.fallback_yes_bid_cents = bid_cents
                state.last_ws_bid_cents = bid_cents
            if ask_cents is not None:
                state.quoted_ask_cents = ask_cents
                state.fallback_yes_ask_cents = ask_cents
                state.last_ws_ask_cents = ask_cents
            state.quote_received_ts = now
            state.last_ws_update_ts = now
            if not state.book_initialized:
                state.quote_owner = "WS_QUOTE"

            # Capture pre-update quality/transition for the recovery attestation gate.
            prior_quality = state.data_quality
            prior_transition = state.transition

            # If we have no orderbook yet, the quote is a *fallback* source only.
            # It must not mark the book as initialized/executable, because a ticker
            # quote is not a full orderbook and can become stale quickly (e.g. the
            # orderbook channel has not caught up to a new window).  The executable
            # BBO is only set by an orderbook snapshot or a contiguous delta stream.
            if not state.book_initialized:
                if bid_cents is not None and ask_cents is not None:
                    state.mid_cents = int(round((bid_cents + ask_cents) / 2))
                    state.spread_cents = int(round(ask_cents - bid_cents))
                elif last_cents is not None:
                    state.mid_cents = int(round(last_cents))

                if bid_cents is not None and ask_cents is not None and bid_cents >= ask_cents:
                    # Crossed quote on a fresh market: record it as a fallback but
                    # do not initialize the executable book.
                    state.data_quality = "SUSPECT"
                    state.book_consistency = "INVERTED"
                    state.transition = "RESYNC_REQUIRED"
                    state.executable = False
                    state.book_initialized = False

                # Propagate the quote-derived top-of-book into the unified state so
                # fills, PnL, and risk all see the same mid/last.
                self._sync_unified_book(ticker, state)

                # FIX: Reset retry counter when we receive fresh WebSocket data
                if ticker in self._quote_retry_count:
                    del self._quote_retry_count[ticker]

            # DIAGNOSTIC: Rate-limited per-ticker update logging (every 30s)
            now = time.monotonic()
            if now - self._last_log_ts.get(ticker, 0) > 30:
                last_update = state.last_book_update_ts if state else 0
                age_s = now - last_update if last_update > 0 else float('inf')
                logger.info(
                    "[WS-STATE-UPDATE] ticker=%s age_s=%.1f last_book_update_ts=%.1f",
                    ticker, age_s, last_update,
                )
                self._last_log_ts[ticker] = now

            # CONNECTION HEALTH: Update WS connection health tracking
            self._update_ws_connection_health(ticker)

            # CRITICAL FIX (2026-08-02): Update book freshness tracker from quote data
            # This ensures quote-based updates also refresh the state machine
            try:
                from merid.event_venues.kalshi.book_freshness import get_book_freshness_tracker
                freshness_tracker = get_book_freshness_tracker()
                freshness_tracker.update_from_ws(ticker, exchange_ts=None, received_ts=time.time())
                logger.debug(f"[BOOK-FRESHNESS] Updated state for {ticker} from quote data")
            except ImportError:
                logger.warning("[BOOK-FRESHNESS] book_freshness module not available, skipping freshness update")
            except Exception as e:
                logger.error(f"[BOOK-FRESHNESS] Failed to update freshness state for {ticker} from quote: {e}")

            # CRITICAL FIX: Capture callbacks while holding lock, then release before notifying
            callbacks = []
            if ticker in self._subscribers:
                callbacks = list(self._subscribers[ticker])

        # Lock is now released - notify subscribers without re-acquiring lock
        self._notify_subscribers(ticker, state, callbacks)
        return state

    # ── Read ───────────────────────────────────────────────────────────

    def get(self, ticker: str) -> Optional[KalshiMarketState]:
        """Return the current state for *ticker*, or ``None`` if unknown.

        BUG-FIX (2026-05-12): No lock - rely on Python GIL for atomic dict reads.
        Dict get is atomic in CPython.
        """
        result = self._states.get(ticker)
        if result is None:
            # 2026-08-11: A miss is normal during startup/rolloff before the state
            # store has processed a ticker.  Log at INFO; callers must handle None.
            logger.info(
                "[MARKET-STATE-GET-MISS] ticker=%s total_states=%d registered_keys=%s",
                ticker, len(self._states), list(self._states.keys())[:10]
            )
        return result

    def get_unified(self, ticker: str) -> Optional[UnifiedMarketState]:
        """Return the ``UnifiedMarketState`` for *ticker*, or ``None`` if unknown.

        ``UnifiedMarketState`` carries all derived consensus fields
        (``implied_prob``, ``external_fair_value``, ``edge_basis``) that
        ``KalshiMarketState`` does not have.  Agents and risk systems should
        prefer this when they need those fields.

        BUG-FIX (2026-05-12): No lock - rely on Python GIL for atomic dict reads.
        Dict get is atomic in CPython.
        """
        return self._unified.get(ticker)

    def get_all(self) -> Dict[str, KalshiMarketState]:
        """Return a shallow copy of the full state registry.

        BUG-FIX (2026-05-12): No lock - rely on Python GIL for atomic dict reads.
        Shallow copy of dict is atomic in CPython.
        """
        return dict(self._states)

    def get_all_states(self) -> Dict[str, KalshiMarketState]:
        """Return a shallow copy of the full state registry.

        Alias for get_all() to match API endpoint expectations.
        """
        return self.get_all()

    def tickers(self) -> List[str]:
        """Return a snapshot of all tracked tickers.

        BUG-FIX (2026-05-12): No lock - rely on Python GIL for atomic dict reads.
        Dict keys() is atomic in CPython.
        """
        return list(self._states.keys())

    def get_all_tickers(self) -> List[str]:
        """Return a snapshot of all tracked tickers.

        Compatibility method for universe consistency checks.
        Alias for tickers() to match expected API.
        """
        return self.tickers()

    def getalltickers(self) -> List[str]:
        """Return a snapshot of all tracked tickers.

        Compatibility method for universe consistency checks.
        Handles incorrect method name that's being called.
        """
        logger.warning("[market-state] getalltickers() called - using correct get_all_tickers() instead")
        return self.get_all_tickers()

    # ── Subscription Mechanism ──────────────────────────────────────────────

    def subscribe_to_updates(self, ticker: str, callback: callable) -> None:
        """Subscribe to state updates for a specific ticker.

        Args:
            ticker: Market ticker to subscribe to (e.g., "KXBTCD-25JUN-T100000")
            callback: Callable that takes (ticker, state) as arguments
        """
        with self._lock:
            if ticker not in self._subscribers:
                self._subscribers[ticker] = []
            if callback not in self._subscribers[ticker]:
                self._subscribers[ticker].append(callback)
                logger.debug("[market-state] Subscribed callback for ticker=%s (subscribers=%d)",
                           ticker, len(self._subscribers[ticker]))

    def unsubscribe_from_updates(self, ticker: str, callback: callable) -> None:
        """Unsubscribe a callback from state updates for a specific ticker.

        Args:
            ticker: Market ticker to unsubscribe from
            callback: Callable to remove from subscribers
        """
        with self._lock:
            if ticker in self._subscribers and callback in self._subscribers[ticker]:
                self._subscribers[ticker].remove(callback)
                logger.debug("[market-state] Unsubscribed callback for ticker=%s (subscribers=%d)",
                           ticker, len(self._subscribers[ticker]))

    def cleanup_stale_states(self, active_tickers: List[str]) -> None:
        """Remove market states for tickers that are no longer active.

        Called when catalog refreshes or on WS reconnect to prevent expired
        state from leaking into signal/edge computation and order routing.

        Args:
            active_tickers: List of currently active tickers from catalog
        """
        active_set = set(active_tickers)
        with self._lock:
            stale_tickers = [t for t in self._states if t not in active_set]

            for ticker in stale_tickers:
                del self._states[ticker]
                self._unified.pop(ticker, None)
                self._subscribers.pop(ticker, None)
                self._pending_deltas.pop(ticker, None)
                self._overflow_count.pop(ticker, None)
                self._last_snapshot_ts.pop(ticker, None)
                self._snapshot_wait_start_ts.pop(ticker, None)
                self._snapshots_applied_total.pop(ticker, None)
                self._ticker_locks.pop(ticker, None)
                self._delta_queues.pop(ticker, None)
                self._needs_resync.pop(ticker, None)
                logger.info(f"[MARKET-STATE-CLEANUP] Removed stale state for ticker={ticker}")

            if stale_tickers:
                logger.info(f"[MARKET-STATE-CLEANUP] Cleaned up {len(stale_tickers)} stale tickers: {stale_tickers}")

    def invalidate_all_live_sequence(self) -> None:
        """Clear live_sequence_confirmed for all tracked markets.

        Called on every WebSocket session recycle/reconnect so that new capital
        commitment is gated until a fresh snapshot + contiguous WS delta sequence
        has been observed.
        """
        with self._lock:
            count = 0
            for ticker, state in self._states.items():
                if getattr(state, "live_sequence_confirmed", False):
                    state.live_sequence_confirmed = False
                    count += 1
                # 2026-08-24: A session recycle invalidates any prior snapshot
                # completion; entries must wait for a fresh snapshot.
                self._set_snapshot_complete(ticker, False, "ws_reconnect")
            logger.info(
                "[MARKET-STATE] Invalidated live_sequence_confirmed for %d/%d states",
                count,
                len(self._states),
            )

    def prune_expired_markets(self, max_age_seconds: float = 86400.0) -> int:
        """Remove market states that haven't been updated in a long time.

        This prevents state bloat by removing markets that expired long ago
        and are no longer receiving updates. This is a time-based pruning
        mechanism complementary to catalog-based pruning.

        Args:
            max_age_seconds: Maximum age in seconds before a market is pruned (default 24h)

        Returns:
            Number of markets pruned
        """
        now = time.monotonic()
        pruned_count = 0

        with self._lock:
            expired_tickers = []
            for ticker, state in self._states.items():
                # Check if the market has never been updated or is very old
                if state.last_book_update_ts <= 0.0:
                    # Never updated - check creation time if available
                    # For now, skip these as they might be newly registered
                    continue

                age = now - state.last_book_update_ts
                if age > max_age_seconds:
                    expired_tickers.append((ticker, age))

            # Remove expired states
            for ticker, age in expired_tickers:
                del self._states[ticker]
                if ticker in self._subscribers:
                    del self._subscribers[ticker]
                pruned_count += 1
                logger.info(
                    f"[MARKET-STATE-PRUNE] Pruned expired ticker={ticker} age={age:.0f}s "
                    f"(threshold={max_age_seconds:.0f}s)"
                )

            if pruned_count > 0:
                logger.info(
                    f"[MARKET-STATE-PRUNE] Pruned {pruned_count} expired markets "
                    f"(age > {max_age_seconds:.0f}s)"
                )

        return pruned_count

    def _notify_subscribers(self, ticker: str, state: KalshiMarketState, callbacks: Optional[List] = None) -> None:
        """Notify all subscribers of a state update.

        Called after state is updated via apply_orderbook_message or apply_rest_market.

        CRITICAL FIX: Callbacks are passed as a parameter to avoid re-acquiring the lock.
        If callbacks is None, they will be fetched from _subscribers (for backward compatibility).
        Callbacks are executed in a background thread to prevent blocking
        the catalog refresh or other state updates. If a callback hangs or deadlocks,
        it will not block the entire market state system.

        Args:
            ticker: Market ticker that was updated
            state: New state after update
            callbacks: Optional list of callback functions to execute. If None, fetch from _subscribers.
        """
        import threading
        # Backward compatibility: if callbacks not provided, fetch them
        if callbacks is None:
            callbacks = []
            with self._lock:
                if ticker in self._subscribers:
                    callbacks = list(self._subscribers[ticker])

        logger.info("[APPLY-REST-MARKET] _notify_subscribers ENTER ticker=%s thread=%s callbacks=%d", ticker, threading.current_thread().name, len(callbacks))

        # Execute callbacks in background thread to prevent blocking
        # This prevents deadlocks where callbacks try to acquire locks held by the caller
        if callbacks:
            logger.info("[APPLY-REST-MARKET] _notify_subscribers Starting callback thread for ticker=%s", ticker)

            def _run_callbacks():
                for callback in callbacks:
                    try:
                        callback(ticker, state)
                    except Exception as exc:
                        logger.error("[market-state] Subscriber callback failed for ticker=%s: %s", ticker, exc, exc_info=True)

            # Start background thread for callback execution
            callback_thread = threading.Thread(
                target=_run_callbacks,
                name=f"market-state-callback-{ticker[:20]}",
                daemon=True
            )
            callback_thread.start()
            logger.info("[APPLY-REST-MARKET] _notify_subscribers Callback thread started for ticker=%s", ticker)
        else:
            logger.info("[APPLY-REST-MARKET] _notify_subscribers No callbacks for ticker=%s", ticker)

        logger.info("[APPLY-REST-MARKET] _notify_subscribers EXIT ticker=%s", ticker)

    def _determine_staleness_regime(self, ticker: str) -> StalenessRegime:
        """Determine staleness regime based on time-to-expiry and market conditions.

        Args:
            ticker: Kalshi market ticker

        Returns:
            StalenessRegime (RELAXED, NORMAL, or STRICT)
        """
        state = self._states.get(ticker)
        if not state or state.seconds_to_expiry is None:
            # Default to NORMAL if we don't have expiry info
            return StalenessRegime.NORMAL

        seconds_to_expiry = state.seconds_to_expiry

        # STRICT regime: near expiry (<60s)
        if seconds_to_expiry <= _EXPIRY_STRICT_THRESHOLD_SECONDS:
            return StalenessRegime.STRICT

        # RELAXED regime: far from expiry (>180s)
        if seconds_to_expiry >= _EXPIRY_RELAXED_THRESHOLD_SECONDS:
            return StalenessRegime.RELAXED

        # NORMAL regime: between thresholds
        return StalenessRegime.NORMAL

    def _get_regime_threshold_seconds(self, regime: StalenessRegime) -> float:
        """Get staleness threshold for a given regime.

        Args:
            regime: StalenessRegime

        Returns:
            Maximum allowed book age in seconds for this regime
        """
        if regime == StalenessRegime.RELAXED:
            return _STALENESS_REGIME_RELAXED_SECONDS
        elif regime == StalenessRegime.STRICT:
            return _STALENESS_REGIME_STRICT_SECONDS
        else:  # NORMAL
            return _STALENESS_REGIME_NORMAL_SECONDS

    def _check_ws_connection_health(self, ticker: str) -> bool:
        """Check if WS connection is healthy based on message receipt.

        This is separate from data staleness - it tracks whether we're receiving
        ANY WS messages (heartbeat, ping/pong, or orderbook delta).

        Args:
            ticker: Kalshi market ticker

        Returns:
            True if connection is healthy, False if suspect
        """
        now = time.monotonic()
        last_msg = self._ws_last_msg_monotonic.get(ticker, 0.0)

        if last_msg == 0.0:
            # Never received a message - assume healthy until we get first message
            return True

        # Check if we've received any WS message within watchdog window
        age = now - last_msg
        if age > _WS_HEALTH_WATCHDOG_SECONDS:
            # Connection suspect - no messages for too long
            logger.warning(
                "[WS-HEALTH-WATCHDOG] ticker=%s connection_suspect age_s=%.1f threshold_s=%.1f",
                ticker, age, _WS_HEALTH_WATCHDOG_SECONDS
            )
            return False

        return True

    def _update_ws_connection_health(self, ticker: str) -> None:
        """Update WS connection health tracking when a message is received.

        Args:
            ticker: Kalshi market ticker
        """
        now = time.monotonic()
        self._ws_last_msg_monotonic[ticker] = now

        # If connection was suspect, mark it healthy again
        if not self._ws_connection_healthy.get(ticker, True):
            logger.info(
                "[WS-HEALTH-RECOVERY] ticker=%s connection_recovered",
                ticker
            )
            self._ws_connection_healthy[ticker] = True
            if ticker in self._ws_connection_suspect_since:
                del self._ws_connection_suspect_since[ticker]

    def _check_rest_updated_time_lag(self, ticker: str) -> Optional[float]:
        """Check if REST updated_time indicates WS lag.

        Compares REST updated_time (exchange timestamp) with our last WS update.
        If REST shows significantly newer data, WS may be lagging.

        Args:
            ticker: Kalshi market ticker

        Returns:
            Lag in seconds if detected, None if no lag or can't determine
        """
        rest_updated = self._rest_updated_time.get(ticker)
        if not rest_updated:
            return None

        state = self._states.get(ticker)
        if not state or state.last_book_update_ts <= 0.0:
            return None

        # CRITICAL FIX (2026-08-03): Prefer the wall-clock sibling timestamp
        # recorded at update time. The previous monotonic->wall conversion
        # (last_book_update_ts + (now_wall - now_monotonic)) drifted whenever the
        # system clock was adjusted (NTP/manual), producing false lag readings.
        if getattr(state, "last_book_update_wall_ts", 0.0) > 0.0:
            last_ws_wall = state.last_book_update_wall_ts
        else:
            # Legacy fallback: approximate conversion
            now_wall = time.time()
            now_monotonic = time.monotonic()
            monotonic_offset = now_wall - now_monotonic
            last_ws_wall = state.last_book_update_ts + monotonic_offset

        # Calculate lag
        lag = rest_updated - last_ws_wall

        # If REST is significantly newer (>30s), WS may be lagging
        if lag > 30.0:
            logger.warning(
                "[REST-LAG-DETECTED] ticker=%s rest_updated_ts=%.1f last_ws_wall_ts=%.1f lag_s=%.1f",
                ticker, rest_updated, last_ws_wall, lag
            )
            return lag

        return None

    def _classify_lag(self) -> LagClassifier:
        """Classify the current lag type based on collected signals.

        Rule-based classifier that distinguishes between:
        - WS_CONNECTION_ISSUE: WebSocket connection problem
        - NETWORK_LATENCY: General network latency
        - EXCHANGE_API_DELAY: Kalshi REST API lagging
        - LOCAL_PROCESSING_LAG: Internal processing delay
        - NORMAL: No significant lag

        Returns:
            LagClassifier classification
        """
        now = time.monotonic()

        # Check WS ping gap
        ws_ping_gap = 0.0
        if self._ws_last_ping_monotonic > 0.0:
            ws_ping_gap = now - self._ws_last_ping_monotonic

        # Check if WS connection has issues
        if ws_ping_gap > _WS_PING_GAP_THRESHOLD_SECONDS:
            logger.warning(
                "[LAG-CLASSIFIER] WS connection issue detected: ping_gap_s=%.1f threshold_s=%.1f",
                ws_ping_gap, _WS_PING_GAP_THRESHOLD_SECONDS
            )
            return LagClassifier.WS_CONNECTION_ISSUE

        # Check network latency (both network ping and REST latency elevated)
        if (self._net_ping_ms > _NETWORK_LATENCY_THRESHOLD_MS and
            self._rest_latency_ms > _REST_LATENCY_THRESHOLD_MS):
            logger.warning(
                "[LAG-CLASSIFIER] Network latency detected: net_ping_ms=%.1f rest_latency_ms=%.1f thresholds=%.1f/%.1f",
                self._net_ping_ms, self._rest_latency_ms,
                _NETWORK_LATENCY_THRESHOLD_MS, _REST_LATENCY_THRESHOLD_MS
            )
            return LagClassifier.NETWORK_LATENCY

        # Check exchange API delay (WS fine, but REST user timestamp lagging)
        if self._rest_user_ts_lag_s > _REST_USER_TS_LAG_THRESHOLD_S:
            logger.warning(
                "[LAG-CLASSIFIER] Exchange API delay detected: rest_user_ts_lag_s=%.1f threshold_s=%.1f",
                self._rest_user_ts_lag_s, _REST_USER_TS_LAG_THRESHOLD_S
            )
            return LagClassifier.EXCHANGE_API_DELAY

        # Check local processing lag
        if self._processing_lag_ms > _PROCESSING_LAG_THRESHOLD_MS:
            logger.warning(
                "[LAG-CLASSIFIER] Local processing lag detected: processing_lag_ms=%.1f threshold_ms=%.1f",
                self._processing_lag_ms, _PROCESSING_LAG_THRESHOLD_MS
            )
            return LagClassifier.LOCAL_PROCESSING_LAG

        # No significant lag detected
        return LagClassifier.NORMAL

    def _update_ws_ping_tracking(self, ping_received: bool = False, pong_sent: bool = False) -> None:
        """Update WS ping/pong tracking.

        Args:
            ping_received: True if we just received a ping from Kalshi
            pong_sent: True if we just sent a pong to Kalshi
        """
        now = time.monotonic()

        if ping_received:
            self._ws_last_ping_monotonic = now
            # Calculate RTT if we had sent a pong recently
            if self._ws_last_pong_sent_monotonic > 0.0:
                rtt_ms = (now - self._ws_last_pong_sent_monotonic) * 1000.0
                self._ws_pong_rtt_ms = rtt_ms
                # Track RTT for volatility analysis
                self._record_rtt_sample("ws", rtt_ms, now)

        if pong_sent:
            self._ws_last_pong_sent_monotonic = now

    def _update_rest_latency_tracking(self, latency_ms: float) -> None:
        """Update REST latency tracking.

        Args:
            latency_ms: Round-trip time for the REST call in milliseconds
        """
        self._rest_latency_ms = latency_ms
        # Track RTT for volatility analysis
        self._record_rtt_sample("rest", latency_ms, time.monotonic())

    def _record_rtt_sample(self, source: str, rtt_ms: float, timestamp: float) -> None:
        """Record an RTT sample for volatility tracking.

        Args:
            source: "ws" or "rest"
            rtt_ms: Round-trip time in milliseconds
            timestamp: Monotonic timestamp
        """
        now = time.monotonic()

        # Prune old samples outside the window
        window_start = now - self._rtt_window_seconds

        # Prune WS samples
        if source == "ws":
            self._ws_rtt_samples.append(rtt_ms)
            self._rtt_sample_timestamps.append(timestamp)
            # Prune old samples
            while self._rtt_sample_timestamps and self._rtt_sample_timestamps[0] < window_start:
                self._rtt_sample_timestamps.pop(0)
                if self._ws_rtt_samples:
                    self._ws_rtt_samples.pop(0)
            # Recalculate mean/std
            self._update_rtt_stats("ws")

        # Prune REST samples
        elif source == "rest":
            self._rest_rtt_samples.append(rtt_ms)
            # Prune old samples (use separate timestamp tracking for REST if needed)
            # For now, assume samples are added in order and prune by count
            # Keep last N samples based on window (approximate)
            max_samples = int(self._rtt_window_seconds / 10)  # Approx 1 sample per 10s
            if len(self._rest_rtt_samples) > max_samples:
                self._rest_rtt_samples.pop(0)
            # Recalculate mean/std
            self._update_rtt_stats("rest")

    def _update_rtt_stats(self, source: str) -> None:
        """Update rolling mean and std for RTT samples.

        Args:
            source: "ws" or "rest"
        """
        if source == "ws":
            samples = self._ws_rtt_samples
        elif source == "rest":
            samples = self._rest_rtt_samples
        else:
            return

        if not samples:
            return

        # Calculate mean
        mean = sum(samples) / len(samples)

        # Calculate std
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)
        std = variance ** 0.5

        # Update stored values
        if source == "ws":
            self._ws_rtt_mean = mean
            self._ws_rtt_std = std
        else:
            self._rest_rtt_mean = mean
            self._rest_rtt_std = std

    def _get_rtt_volatility_score(self, source: str) -> float:
        """Get RTT volatility score (coefficient of variation).

        Args:
            source: "ws" or "rest"

        Returns:
            Coefficient of variation (std/mean), or 0 if no data
        """
        if source == "ws":
            mean = self._ws_rtt_mean
            std = self._ws_rtt_std
        else:
            mean = self._rest_rtt_mean
            std = self._rest_rtt_std

        if mean == 0:
            return 0.0

        return std / mean

    def _record_rest_call(self) -> None:
        """Record a REST call for rate limit tracking."""
        now = time.monotonic()
        self._rest_call_timestamps.append(now)

        # Prune old calls outside 1-minute window
        window_start = now - 60.0
        self._rest_call_timestamps = [ts for ts in self._rest_call_timestamps if ts >= window_start]

        # Update calls per minute
        self._rest_calls_per_minute = len(self._rest_call_timestamps)

    def _record_rate_limit_hit(self) -> None:
        """Record a 429 rate limit hit and trigger backoff."""
        now = time.monotonic()
        self._rate_limit_hits += 1
        self._last_429_timestamp = now

        # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, max 60s
        backoff_seconds = min(2 ** min(self._rate_limit_hits, 6), 60.0)
        self._backoff_until = now + backoff_seconds

        logger.warning(
            "[RATE-LIMIT] 429 hit #%d, backoff for %.1fs until %.1f",
            self._rate_limit_hits, backoff_seconds, self._backoff_until
        )

    def _check_backoff(self) -> bool:
        """Check if we're currently in backoff.

        Returns:
            True if in backoff (should not make REST calls), False otherwise
        """
        now = time.monotonic()
        if now < self._backoff_until:
            return True

        # Reset backoff if we're past the backoff period
        if self._backoff_until > 0 and now >= self._backoff_until:
            self._backoff_until = 0.0
            logger.info("[RATE-LIMIT] Backoff period ended, resuming normal operations")

        return False

    def _update_adaptive_poll_interval(self, ws_healthy: bool, market_activity: float) -> None:
        """Update adaptive polling interval based on conditions.

        Args:
            ws_healthy: True if WebSocket is healthy
            market_activity: Current market activity metric (0-1)
        """
        # Base interval
        interval = self._base_poll_interval

        # If WS is healthy and market is calm, increase interval (reduce REST load)
        if ws_healthy and market_activity < 0.3:
            interval = min(interval * 1.5, self._max_poll_interval)
        # If WS is unhealthy or market is active, decrease interval (more frequent checks)
        elif not ws_healthy or market_activity > 0.7:
            interval = max(interval * 0.8, self._min_poll_interval)

        # If we've had recent 429s, use longer interval
        if self._rate_limit_hits > 0:
            time_since_429 = time.monotonic() - self._last_429_timestamp
            if time_since_429 < 300.0:  # Within 5 minutes of last 429
                interval = max(interval * 2.0, self._max_poll_interval)

        self._adaptive_poll_interval = interval

        logger.debug(
            "[ADAPTIVE-POLL] interval=%.1fs ws_healthy=%s activity=%.2f rate_limit_hits=%d",
            interval, ws_healthy, market_activity, self._rate_limit_hits
        )

    def _get_adaptive_poll_interval(self) -> float:
        """Get current adaptive polling interval.

        Returns:
            Polling interval in seconds
        """
        return self._adaptive_poll_interval

    def _update_network_ping_tracking(self, ping_ms: float) -> None:
        """Update network ping tracking.

        Args:
            ping_ms: Round-trip time to Kalshi/VPS in milliseconds
        """
        self._net_ping_ms = ping_ms

    def _update_processing_lag_tracking(self, lag_ms: float) -> None:
        """Update processing lag tracking.

        Args:
            lag_ms: Internal processing delay in milliseconds
        """
        self._processing_lag_ms = lag_ms

    def _record_msg_recv_timestamp(self, ticker: str) -> None:
        """Record when a WS message was received for a ticker.

        Args:
            ticker: Market ticker
        """
        self._msg_recv_monotonic[ticker] = time.monotonic()

    def _record_msg_proc_timestamp(self, ticker: str) -> None:
        """Record when a WS message was processed for a ticker and calculate lag.

        Args:
            ticker: Market ticker
        """
        now = time.monotonic()
        self._msg_proc_monotonic[ticker] = now

        # Calculate processing lag if we have a recv timestamp
        if ticker in self._msg_recv_monotonic:
            lag_ms = (now - self._msg_recv_monotonic[ticker]) * 1000.0
            self._processing_lag_ms = lag_ms

        # Track cadence for orderbook updates
        self._record_book_update_timestamp(ticker, now)

    def _record_book_update_timestamp(self, ticker: str, timestamp: float) -> None:
        """Record a book update timestamp for cadence tracking.

        Args:
            ticker: Market ticker
            timestamp: Monotonic timestamp of the update
        """
        now = time.monotonic()

        # Initialize list if needed
        if ticker not in self._book_update_timestamps:
            self._book_update_timestamps[ticker] = []

        # Add timestamp
        self._book_update_timestamps[ticker].append(timestamp)

        # Prune old timestamps outside the window
        window_start = now - self._cadence_window_seconds
        self._book_update_timestamps[ticker] = [
            ts for ts in self._book_update_timestamps[ticker] if ts >= window_start
        ]

        # Calculate updates per minute
        if self._book_update_timestamps[ticker]:
            self._updates_per_minute[ticker] = len(self._book_update_timestamps[ticker]) / (self._cadence_window_seconds / 60.0)

    def _get_updates_per_minute(self, ticker: str) -> float:
        """Get current updates per minute for a ticker.

        Args:
            ticker: Market ticker

        Returns:
            Updates per minute (0 if no data)
        """
        return self._updates_per_minute.get(ticker, 0.0)

    def _update_baseline_interval(self, ticker: str) -> None:
        """Update the baseline update interval for a ticker based on recent history.

        Args:
            ticker: Market ticker
        """
        if ticker not in self._book_update_timestamps or len(self._book_update_timestamps[ticker]) < 2:
            return

        # Calculate intervals between consecutive updates
        timestamps = sorted(self._book_update_timestamps[ticker])
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]

        if intervals:
            # Use median as baseline (robust to outliers)
            intervals.sort()
            median_idx = len(intervals) // 2
            if len(intervals) % 2 == 0:
                median_interval = (intervals[median_idx - 1] + intervals[median_idx]) / 2
            else:
                median_interval = intervals[median_idx]

            self._baseline_update_intervals[ticker] = median_interval

    def _reconcile_with_rest(self, ticker: str, rest_data: Dict[str, Any]) -> Optional[str]:
        """Reconcile WS state with REST data to detect desync.

        Compares WS book with REST book and timestamps to detect:
        - WS lag (REST leads WS)
        - Expected REST delay (WS leads REST)
        - Validation (WS and REST agree)

        Args:
            ticker: Market ticker
            rest_data: REST market data dict

        Returns:
            Reconciliation status: "validated", "ws_lag", "rest_lag", or None if insufficient data
        """
        with self._lock:
            state = self._states.get(ticker)
            if not state or not state.book_initialized:
                return None

            # Extract REST bid/ask
            rest_bid = rest_data.get("best_bid")
            rest_ask = rest_data.get("best_ask")
            rest_updated = rest_data.get("updated_time")

            if rest_bid is None or rest_ask is None:
                return None

            # Get WS bid/ask
            ws_bid = state.best_bid_cents
            ws_ask = state.best_ask_cents

            if ws_bid is None or ws_ask is None:
                return None

            # Convert to cents for comparison
            rest_bid_cents = int(rest_bid) if isinstance(rest_bid, (int, float)) else None
            rest_ask_cents = int(rest_ask) if isinstance(rest_ask, (int, float)) else None

            if rest_bid_cents is None or rest_ask_cents is None:
                return None

            # Check if prices are within tolerance (1 tick = 1 cent)
            tick_tolerance = 1  # 1 cent tolerance
            bid_diff = abs(ws_bid - rest_bid_cents)
            ask_diff = abs(ws_ask - rest_ask_cents)

            # Parse REST updated_time
            rest_updated_ts = None
            if rest_updated:
                try:
                    from datetime import datetime
                    if isinstance(rest_updated, str):
                        if rest_updated.endswith('Z'):
                            rest_updated = rest_updated[:-1] + '+00:00'
                        dt = datetime.fromisoformat(rest_updated)
                        rest_updated_ts = dt.timestamp()
                except Exception as e:
                    logger.warning(
                        "[REST-RECONCILIATION] Failed to parse rest updated_time=%r for %s: %s - "
                        "timestamp comparison disabled for this check",
                        rest_updated, ticker, e
                    )

            # Compare timestamps
            ws_updated_ts = state.last_book_update_ts
            if ws_updated_ts > 0 and rest_updated_ts:
                # CRITICAL FIX (2026-08-03): Prefer exact wall-clock sibling; the
                # monotonic->wall approximation drifts on clock adjustments.
                if getattr(state, "last_book_update_wall_ts", 0.0) > 0.0:
                    ws_wall_ts = state.last_book_update_wall_ts
                else:
                    now_wall = time.time()
                    now_monotonic = time.monotonic()
                    ws_wall_ts = now_wall - (now_monotonic - ws_updated_ts)

                timestamp_diff = rest_updated_ts - ws_wall_ts

                # Reconciliation logic
                if bid_diff <= tick_tolerance and ask_diff <= tick_tolerance:
                    # Prices agree - check timestamps
                    if abs(timestamp_diff) < 5.0:  # Within 5 seconds
                        logger.debug(
                            "[REST-RECONCILIATION] ticker=%s status=validated bid_diff=%.1f ask_diff=%.1f ts_diff=%.1f",
                            ticker, bid_diff, ask_diff, timestamp_diff
                        )
                        return "validated"
                    elif timestamp_diff > 5.0:
                        # REST is significantly newer than WS
                        logger.warning(
                            "[REST-RECONCILIATION] ticker=%s status=ws_lag bid_diff=%.1f ask_diff=%.1f ts_diff=%.1f (REST leads)",
                            ticker, bid_diff, ask_diff, timestamp_diff
                        )
                        return "ws_lag"
                    else:
                        # WS is newer than REST (expected due to REST delay)
                        logger.debug(
                            "[REST-RECONCILIATION] ticker=%s status=rest_lag bid_diff=%.1f ask_diff=%.1f ts_diff=%.1f (WS leads - expected)",
                            ticker, bid_diff, ask_diff, timestamp_diff
                        )
                        return "rest_lag"
                else:
                    # Prices disagree - check if REST leads
                    if timestamp_diff > 5.0:
                        logger.warning(
                            "[REST-RECONCILIATION] ticker=%s status=ws_lag_prices_differ bid_diff=%.1f ask_diff=%.1f ts_diff=%.1f",
                            ticker, bid_diff, ask_diff, timestamp_diff
                        )
                        return "ws_lag"
                    else:
                        logger.warning(
                            "[REST-RECONCILIATION] ticker=%s status=price_divergence bid_diff=%.1f ask_diff=%.1f ts_diff=%.1f",
                            ticker, bid_diff, ask_diff, timestamp_diff
                        )
                        return "price_divergence"

            return None

    def is_stale(self, ticker: str, max_age_seconds: float = 30.0) -> bool:
        """Return True if *ticker*'s book has not been updated within *max_age_seconds*.

        H3: Consumers (e.g. order router market-condition check) should call
        this to refuse to trade on a book that has gone silent after a WS
        reconnect.  A ticker that has never been seen is also considered stale.

        BUG-FIX (2026-05-12): No lock - rely on Python GIL for atomic dict reads.
        Dict get is atomic in CPython.
        """
        state = self._states.get(ticker)
        if state is None or not state.book_initialized:
            return True
        # D-H3: use explicit > 0.0 guard so that the never-set sentinel
        # (last_book_update_ts=0.0) is treated as infinite age rather than
        # computing (monotonic() - 0.0) = monotonic() which could be less
        # than a very large max_age_seconds.
        if state.last_book_update_ts <= 0.0:
            return True
        age = time.monotonic() - state.last_book_update_ts
        return age > max_age_seconds

    # ── Data Integrity Layer ───────────────────────────────────────────────

    async def get_trusted_quote(self, ticker: str) -> Optional[MarketQuote]:
        """Get a trusted quote for *ticker* with health state and cross-validation.

        This is the main entry point for signal agents to fetch market data.
        It implements the data integrity layer logic:
        - Primary feed (WebSocket) is preferred
        - REST fallback is used when primary is stale or missing
        - Cross-validation between feeds detects discrepancies
        - Health state (healthy/degraded/suspended) guides trading decisions

        Args:
            ticker: Kalshi market ticker (e.g., "KXBTC15M-26MAY112345-45")

        Returns:
            MarketQuote with health state, or None if suspended
        """
        import asyncio
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket

        # Extract series ticker from market ticker
        asset = kalshi_ticker_to_asset(ticker) or "UNKNOWN"
        timeframe = get_series_timeframe_bucket(ticker) or "UNKNOWN"
        series_ticker = f"{asset.upper()}{timeframe.upper()}" if asset != "UNKNOWN" else "UNKNOWN"

        with self._lock:
            state = self._states.get(ticker)

            # Check if primary (WebSocket) data is fresh using regime-aware thresholds
            primary_fresh = False
            ws_connection_healthy = True
            regime = StalenessRegime.NORMAL
            regime_threshold = _PRIMARY_STALE_SECONDS  # Fallback to old threshold

            if state and state.book_initialized and state.last_book_update_ts > 0.0:
                age = time.monotonic() - state.last_book_update_ts

                # Determine staleness regime based on time-to-expiry
                regime = self._determine_staleness_regime(ticker)
                regime_threshold = self._get_regime_threshold_seconds(regime)

                # Check if data is fresh according to regime threshold
                primary_fresh = age <= regime_threshold

                # Also check WS connection health separately
                ws_connection_healthy = self._check_ws_connection_health(ticker)

                # Log regime decision for diagnostics
                logger.debug(
                    "[STALENESS-REGIME] ticker=%s regime=%s threshold_s=%.1f age_s=%.1f fresh=%s ws_healthy=%s",
                    ticker, regime, regime_threshold, age, primary_fresh, ws_connection_healthy
                )

                # Update baseline interval periodically
                self._update_baseline_interval(ticker)

                # Get cadence metrics
                updates_per_min = self._get_updates_per_minute(ticker)
                baseline_interval = self._baseline_update_intervals.get(ticker, 0.0)

                # Classify lag type for diagnostics
                lag_class = self._classify_lag()
                self._current_lag_class = lag_class
                logger.debug(
                    "[LAG-CLASSIFIER] ticker=%s lag_class=%s ws_ping_gap_s=%.1f ws_pong_rtt_ms=%.1f rest_latency_ms=%.1f rest_user_ts_lag_s=%.1f net_ping_ms=%.1f processing_lag_ms=%.1f updates_per_min=%.1f baseline_interval_s=%.1f",
                    ticker, lag_class,
                    (time.monotonic() - self._ws_last_ping_monotonic) if self._ws_last_ping_monotonic > 0 else 0,
                    self._ws_pong_rtt_ms,
                    self._rest_latency_ms,
                    self._rest_user_ts_lag_s,
                    self._net_ping_ms,
                    self._processing_lag_ms,
                    updates_per_min,
                    baseline_interval
                )

            # Get current health state
            current_health = self._health_state.get(ticker, QuoteHealth.HEALTHY)

            # If primary is fresh and not suspended, return it
            if primary_fresh and current_health != QuoteHealth.SUSPENDED:
                # CRITICAL: Check for (0,100) anomaly before marking executable
                # This pattern indicates empty orderbook or parsing anomaly
                # However, one-sided books (e.g., bid=99, ask=0 with depth) are valid for trading
                has_valid_bid = state.best_bid_cents is not None and state.best_bid_cents > 0
                has_valid_ask = state.best_ask_cents is not None and state.best_ask_cents < 100
                has_anomaly = state.best_bid_cents == 0 and state.best_ask_cents == 100

                # Allow one-sided books if there's depth on the available side
                # This aligns with agent_grid's one-sided book validation
                # Use depth_10c or check yes_bids/no_bids lists for depth
                has_depth = (state.depth_10c or 0) > 0 or len(state.yes_bids) > 0 or len(state.no_bids) > 0
                has_valid_bid_ask = (has_valid_bid or has_valid_ask) and not has_anomaly and has_depth

                # Build quote from primary
                quote = MarketQuote(
                    market_ticker=ticker,
                    series_ticker=series_ticker,
                    best_bid_cents=state.best_bid_cents,
                    best_ask_cents=state.best_ask_cents,
                    mid_cents=state.mid_cents,
                    status="open",  # Assume open if book is initialized
                    source=QuoteSource.WEBSOCKET,
                    ts_exchange=state.last_book_update_ts,
                    ts_received=time.monotonic(),
                    is_fallback=False,
                    health=QuoteHealth.HEALTHY if has_valid_bid_ask else QuoteHealth.DEGRADED,
                    executable=has_valid_bid_ask,  # Only executable if bid/ask are valid
                    diagnostics=[] if has_valid_bid_ask else ["(0,100) bid/ask pattern detected"]
                )

                # Cross-validate with REST if needed (every 30s or on health transition)
                last_rest = self._rest_last_fetch.get(ticker, 0.0)
                if time.monotonic() - last_rest > 30.0:
                    # Schedule async REST validation (non-blocking)
                    asyncio.create_task(self._cross_validate_with_rest(ticker, quote))

                return quote

            # Primary is stale or missing - try REST fallback
            last_rest = self._rest_last_fetch.get(ticker, 0.0)
            if time.monotonic() - last_rest >= _REST_THROTTLE_SECONDS:
                # Can fetch REST data
                pass  # Will fetch below outside lock
            else:
                # REST throttled - return degraded if we have cached data
                if state and state.mid_cents:
                    return MarketQuote(
                        market_ticker=ticker,
                        series_ticker=series_ticker,
                        best_bid_cents=state.best_bid_cents,
                        best_ask_cents=state.best_ask_cents,
                        mid_cents=state.mid_cents,
                        status="open",
                        source=QuoteSource.REST,
                        ts_exchange=state.last_rest_update_ts,
                        ts_received=time.monotonic(),
                        is_fallback=True,
                        health=QuoteHealth.DEGRADED,
                        executable=False,  # Fallback quotes are not executable
                        diagnostics=["REST throttled, using cached data"]
                    )
                return None

        # Fetch REST data outside lock
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            market = await client.get_market(ticker)

            if market:
                # Update REST timestamp
                with self._lock:
                    self._rest_last_fetch[ticker] = time.monotonic()
                    self._consecutive_failures[ticker] = 0

                # Build quote from REST
                best_bid = None
                best_ask = None
                mid = None

                if hasattr(market, 'yes_bid'):
                    best_bid = int(market.yes_bid * 100) if market.yes_bid else None
                if hasattr(market, 'yes_ask'):
                    best_ask = int(market.yes_ask * 100) if market.yes_ask else None
                if hasattr(market, 'last_price'):
                    mid = int(market.last_price * 100) if market.last_price else None

                # Determine market status
                status = "open"
                if hasattr(market, 'status'):
                    status = str(market.status).lower()

                # If market is closed/paused, mark as suspended
                if status in ("closed", "paused"):
                    with self._lock:
                        self._health_state[ticker] = QuoteHealth.SUSPENDED
                    return None

                # Check profile for fallback trade allowance (no-synthetic-pricing invariant)
                allow_fallback = False
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile
                    adapter = get_active_profile()
                    if adapter and adapter.profile:
                        allow_fallback = adapter.profile.allow_fallback_trades
                except Exception:
                    pass  # Default to False (no fallback trades)

                # Build quote
                quote = MarketQuote(
                    market_ticker=ticker,
                    series_ticker=series_ticker,
                    best_bid_cents=best_bid,
                    best_ask_cents=best_ask,
                    mid_cents=mid,
                    status=status,
                    source=QuoteSource.REST,
                    ts_exchange=time.time(),
                    ts_received=time.monotonic(),
                    is_fallback=True,
                    health=QuoteHealth.DEGRADED,
                    executable=allow_fallback,  # Only executable if profile allows fallback trades
                    diagnostics=[
                        "Primary feed stale/missing, using REST fallback",
                        f"fallback_trades_allowed={allow_fallback}"
                    ]
                )

                # Cross-validate if primary exists
                with self._lock:
                    state = self._states.get(ticker)
                    if state and state.mid_cents and mid:
                        diff = abs(state.mid_cents - mid)
                        threshold_cents = _CROSS_VALIDATION_THRESHOLD_CENTS
                        threshold_pct = _CROSS_VALIDATION_THRESHOLD_PCT

                        # Check absolute difference
                        if diff > threshold_cents:
                            # Check relative difference
                            if state.mid_cents > 0:
                                rel_diff = diff / state.mid_cents
                                if rel_diff > threshold_pct:
                                    # Discrepancy detected - mark as suspended
                                    self._health_state[ticker] = QuoteHealth.SUSPENDED
                                    quote.health = QuoteHealth.SUSPENDED
                                    quote.diagnostics.append(
                                        f"Primary vs REST discrepancy: {diff}¢ > {threshold_cents}¢ "
                                        f"({rel_diff:.1%} > {threshold_pct:.1%})"
                                    )
                                    return None

                # Update health to degraded if using REST
                with self._lock:
                    if self._health_state.get(ticker) != QuoteHealth.SUSPENDED:
                        self._health_state[ticker] = QuoteHealth.DEGRADED

                return quote

            else:
                # REST fetch failed
                with self._lock:
                    self._consecutive_failures[ticker] = self._consecutive_failures.get(ticker, 0) + 1
                    # Suspend after 3 consecutive failures
                    if self._consecutive_failures[ticker] >= 3:
                        self._health_state[ticker] = QuoteHealth.SUSPENDED
                return None

        except Exception as e:
            logger.error("[market-state] REST fetch failed for %s: %s", ticker, e)
            with self._lock:
                self._consecutive_failures[ticker] = self._consecutive_failures.get(ticker, 0) + 1
                if self._consecutive_failures[ticker] >= 3:
                    self._health_state[ticker] = QuoteHealth.SUSPENDED
            return None

    async def _cross_validate_with_rest(self, ticker: str, primary_quote: MarketQuote) -> None:
        """Cross-validate primary quote with REST data (background task).

        This is called asynchronously to avoid blocking the main quote fetch.
        It updates health state based on cross-validation results.
        """
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            market = await client.get_market(ticker)

            if not market:
                return

            with self._lock:
                self._rest_last_fetch[ticker] = time.monotonic()

            # Get REST price
            rest_mid = None
            if hasattr(market, 'last_price') and market.last_price:
                rest_mid = int(market.last_price * 100)

            if rest_mid and primary_quote.mid_cents:
                diff = abs(primary_quote.mid_cents - rest_mid)
                threshold_cents = _CROSS_VALIDATION_THRESHOLD_CENTS
                threshold_pct = _CROSS_VALIDATION_THRESHOLD_PCT

                # Check absolute difference
                if diff > threshold_cents:
                    # Check relative difference
                    if primary_quote.mid_cents > 0:
                        rel_diff = diff / primary_quote.mid_cents
                        if rel_diff > threshold_pct:
                            # Discrepancy detected - mark as suspended
                            with self._lock:
                                self._health_state[ticker] = QuoteHealth.SUSPENDED
                            logger.warning(
                                "[market-state] Cross-validation failed for %s: "
                                "primary=%d¢, REST=%d¢, diff=%d¢ (%.1%% > %.1%%)",
                                ticker, primary_quote.mid_cents, rest_mid, diff, rel_diff, threshold_pct
                            )
                            return

            # Cross-validation passed - mark as healthy
            with self._lock:
                if self._health_state.get(ticker) != QuoteHealth.SUSPENDED:
                    self._health_state[ticker] = QuoteHealth.HEALTHY
                    primary_quote.health = QuoteHealth.HEALTHY
                    primary_quote.source = QuoteSource.COMPOSITE

        except Exception as e:
            logger.debug("[market-state] Cross-validation failed for %s: %s", ticker, e)

    def get_trusted_quote_sync(self, ticker: str) -> Optional[MarketQuote]:
        """Synchronous version of get_trusted_quote with REST fallback.

        This is for use in synchronous contexts where async/await is not available.
        It first checks cached data, then falls back to a synchronous REST fetch if needed.

        Args:
            ticker: Kalshi market ticker (e.g., "KXBTC15M-26MAY112345-45")

        Returns:
            MarketQuote with health state, or None if no data available
        """
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket

        # Extract series ticker from market ticker
        asset = kalshi_ticker_to_asset(ticker) or "UNKNOWN"
        timeframe = get_series_timeframe_bucket(ticker) or "UNKNOWN"
        series_ticker = f"{asset.upper()}{timeframe.upper()}" if asset != "UNKNOWN" else "UNKNOWN"

        # First, try to get from cache
        with self._lock:
            state = self._states.get(ticker)

            if state:
                # Check circuit breaker
                circuit_breaker_until = self._circuit_breaker_until.get(ticker, 0.0)
                if circuit_breaker_until > time.monotonic():
                    remaining = circuit_breaker_until - time.monotonic()
                    logger.warning(
                        "[market-state] Circuit breaker active for %s until %.1fs - rejecting quote",
                        ticker, remaining
                    )
                    # Record rejected quote metric
                    self._record_metric(ticker, "rejected_quotes", 1.0)
                    return None

                # Check if primary (WebSocket) data is fresh
                primary_fresh = False
                age = 0.0
                if state.book_initialized and state.last_book_update_ts > 0.0:
                    age = time.monotonic() - state.last_book_update_ts
                    primary_fresh = age <= _PRIMARY_STALE_SECONDS

                # Get current health state
                current_health = self._health_state.get(ticker, QuoteHealth.HEALTHY)

                # If suspended, return None
                if current_health == QuoteHealth.SUSPENDED:
                    logger.warning("[market-state] Market %s suspended - rejecting quote", ticker)
                    return None

                # Check if we have valid prices
                has_valid_prices = (
                    (state.mid_cents and 0 < state.mid_cents < 100) or
                    (state.best_bid_cents and 0 < state.best_bid_cents < 100) or
                    (state.best_ask_cents and 0 < state.best_ask_cents < 100)
                )

                # DIAGNOSTIC: Log cached state when ticker exists but has no valid prices
                if not has_valid_prices:
                    logger.error(
                        "[market-state] DIAGNOSTIC - Ticker %s found in cache but has no valid prices. "
                        "Cached state: mid_cents=%s, best_bid_cents=%s, best_ask_cents=%s, "
                        "book_initialized=%s, last_book_update_ts=%s, last_rest_update_ts=%s, "
                        "health=%s",
                        ticker,
                        state.mid_cents, state.best_bid_cents, state.best_ask_cents,
                        state.book_initialized, state.last_book_update_ts, state.last_rest_update_ts,
                        self._health_state.get(ticker, "unknown")
                    )

                if has_valid_prices:
                    # Build quote from cached state
                    source = QuoteSource.WEBSOCKET if primary_fresh else QuoteSource.REST
                    health = QuoteHealth.HEALTHY if primary_fresh else QuoteHealth.DEGRADED
                    is_fallback = not primary_fresh

                    # Calculate age_ms and confidence from the actual orderbook
                    # timestamp; catalog metadata does not refresh prices.
                    ts_exchange = state.last_book_update_ts
                    age_ms = (time.monotonic() - ts_exchange) * 1000.0

                    # Record quote age metric
                    self._record_metric(ticker, "quote_age", age_ms)

                    # Confidence based on freshness: 1.0 if fresh, decays to 0.0 at TTL
                    confidence = max(0.0, 1.0 - (age_ms / 1000.0) / _MAX_QUOTE_TTL_SECONDS)

                    # TTL enforcement: reject if older than max TTL
                    if age_ms / 1000.0 > _MAX_QUOTE_TTL_SECONDS:
                        logger.warning(
                            "[market-state] Quote for %s rejected due to TTL: age=%.1fms > max=%.1fms",
                            ticker, age_ms, _MAX_QUOTE_TTL_SECONDS * 1000.0
                        )
                        self._record_metric(ticker, "rejected_quotes", 1.0)
                        return None

                    diagnostics = []
                    if not primary_fresh:
                        diagnostics.append(f"Primary feed stale (age={age:.1f}s), using cached data")
                        logger.info("[market-state] Using degraded quote for %s: age=%.1fms, confidence=%.2f", ticker, age_ms, confidence)

                    quote = MarketQuote(
                        market_ticker=ticker,
                        series_ticker=series_ticker,
                        best_bid_cents=state.best_bid_cents,
                        best_ask_cents=state.best_ask_cents,
                        mid_cents=state.mid_cents,
                        status="open",  # Assume open if book is initialized
                        source=source,
                        ts_exchange=ts_exchange,
                        ts_received=time.monotonic(),
                        age_ms=age_ms,
                        confidence=confidence,
                        is_fallback=is_fallback,
                        health=health,
                        executable=primary_fresh,  # Only executable if primary is fresh
                        diagnostics=diagnostics
                    )

                    return quote

        # FIX: Cap retry loops to prevent thrashing (3 attempts max)
        with self._lock:
            retry_count = self._quote_retry_count.get(ticker, 0)
            if retry_count >= 3:
                # Already exceeded retry limit, return None to prevent thrashing
                if retry_count == 3:
                    # Log once when hitting the limit to reduce log noise
                    logger.error(
                        "[market-state] Quote retry limit exceeded for %s (3 attempts) - "
                        "marking as DEAD to prevent thrashing. WS Bridge may not be subscribed.",
                        ticker
                    )
                    # Increment to 4 so we don't log again
                    self._quote_retry_count[ticker] = 4
                return None
            # Increment retry counter before attempting REST fallback
            self._quote_retry_count[ticker] = retry_count + 1

        logger.warning("[market-state] No valid cached data for %s - attempting REST fallback (attempt %d/3)", ticker, retry_count + 1)
        # DIAGNOSTIC: Log cache status to debug why cache is empty (store-level only)
        with self._lock:
            cache_keys = list(self._states.keys())
            # Check if ticker exists in cache with different format
            ticker_matches = [k for k in cache_keys if ticker in k or k in ticker]
            logger.error(
                "[market-state] DIAGNOSTIC - Requested ticker: %s, Cache keys (first 10): %s, total_states: %d, "
                "ticker_matches_in_cache: %s",
                ticker, cache_keys[:10], len(self._states), ticker_matches
            )
        # Note: WS bridge status diagnostics moved to bridge module to avoid circular coupling
        self._record_metric(ticker, "fallback_count", 1.0)
        try:
            import httpx
            import os
            from utils.http_client import get_shared_ssl_context
            from merid.event_venues.kalshi.client import get_kalshi_client

            # Use existing Kalshi client for authentication (API Key + RSA signature)
            client = get_kalshi_client()

            # Use synchronous httpx for REST fallback (works from any context)
            kalshi_base_url = os.getenv("KALSHI_API_URL", "https://external-api.kalshi.com/trade-api/v2")
            path = f"/markets/{ticker}"

            # Generate RSA authentication headers using the client's method
            auth_headers = client._sign_headers("GET", path)

            # BUG-FIX (2026-05-12): Added explicit timeout to prevent indefinite blocking
            # This is a sync function for sync contexts; if called from async, it will block.
            # Use get_trusted_quote (async version) instead from async contexts.
            ssl_context = get_shared_ssl_context()
            with httpx.Client(verify=ssl_context, timeout=10.0) as http_client:
                response = http_client.get(
                    f"{kalshi_base_url}{path}",
                    headers=auth_headers
                )
                response.raise_for_status()
                market_data = response.json()

                # DIAGNOSTIC: Log full REST API response to understand structure
                logger.error(
                    "[market-state] DIAGNOSTIC - REST API response for %s: status_code=%s, "
                    "response_keys=%s, has_market=%s",
                    ticker,
                    response.status_code,
                    list(market_data.keys()) if market_data else "None",
                    "market" in market_data
                )
                if "market" in market_data:
                    market = market_data["market"]
                    logger.error(
                        "[market-state] DIAGNOSTIC - Market object for %s: market_keys=%s, "
                        "status=%s, yes_bid=%s, yes_ask=%s, last_price=%s",
                        ticker,
                        list(market.keys()) if market else "None",
                        market.get("status") if market else "None",
                        market.get("yes_bid") if market else "None",
                        market.get("yes_ask") if market else "None",
                        market.get("last_price") if market else "None"
                    )

            if market_data and "market" in market_data:
                # Update REST timestamp and reset failures
                with self._lock:
                    self._rest_last_fetch[ticker] = time.monotonic()
                    self._consecutive_failures[ticker] = 0
                    # Clear circuit breaker on successful fetch and record half-open success
                    if ticker in self._circuit_breaker_until:
                        del self._circuit_breaker_until[ticker]
                        self._record_metric(ticker, "half_open_successes", 1.0)
                        logger.info("[market-state] Circuit breaker half-open success for %s - breaker cleared", ticker)

                # Parse market data from REST response
                market = market_data["market"]
                best_bid = None
                best_ask = None
                mid = None

                # Parse yes_bid/yes_ask from market data
                price_source = "standard"

                def safe_parse_dollar_field(value, field_name):
                    """Safely parse a dollar-denominated price field, handling malformed data."""
                    if value is None:
                        return None
                    original_value = str(value) if not isinstance(value, str) else value
                    try:
                        # Handle malformed strings like '0.90200.90200.90200...' by extracting first valid float
                        if isinstance(value, str):
                            # Check for repeated pattern (malformed API response)
                            if value.count('.') > 1:
                                # Extract first valid float (e.g., '0.90200.90200...' -> '0.90200')
                                import re
                                match = re.match(r'^(\d+\.\d+)', value)
                                if match:
                                    extracted = match.group(1)
                                    logger.debug("[market-state] Malformed %s detected: '%s' -> extracted '%s'", field_name, value[:50], extracted)
                                    value = extracted
                                else:
                                    logger.warning("[market-state] Malformed %s value (repeated pattern): %s - skipping", field_name, value[:50])
                                    return None
                        parsed = float(value)
                        # Validate dollar value is in sane range (0-100 dollars, i.e., 0-10000 cents)
                        if not (0 <= parsed <= 100):
                            logger.warning("[market-state] %s value %s out of sane range (0-100 dollars) - skipping", field_name, parsed)
                            return None
                        return parsed
                    except (ValueError, TypeError) as e:
                        logger.warning("[market-state] Failed to parse %s value '%s': %s - skipping", field_name, str(value)[:50], e)
                        return None

                if "yes_bid" in market and market["yes_bid"] is not None:
                    best_bid = int(market["yes_bid"] * 100)
                elif "yes_bid_dollars" in market and market["yes_bid_dollars"] is not None:
                    bid_dollars = safe_parse_dollar_field(market["yes_bid_dollars"], "yes_bid_dollars")
                    if bid_dollars is not None:
                        best_bid = int(bid_dollars * 100)
                        price_source = "dollars"
                if "yes_ask" in market and market["yes_ask"] is not None:
                    best_ask = int(market["yes_ask"] * 100)
                elif "yes_ask_dollars" in market and market["yes_ask_dollars"] is not None:
                    ask_dollars = safe_parse_dollar_field(market["yes_ask_dollars"], "yes_ask_dollars")
                    if ask_dollars is not None:
                        best_ask = int(ask_dollars * 100)
                        price_source = "dollars"
                if "last_price" in market and market["last_price"] is not None:
                    mid = int(market["last_price"] * 100)
                elif "last_price_dollars" in market and market["last_price_dollars"] is not None:
                    last_dollars = safe_parse_dollar_field(market["last_price_dollars"], "last_price_dollars")
                    if last_dollars is not None:
                        mid = int(last_dollars * 100)
                        price_source = "dollars"

                # Sanity check: bid must be <= ask
                if best_bid is not None and best_ask is not None and best_bid > best_ask:
                    logger.warning(
                        "[market-state] REST fetch for %s has inverted bid/ask (bid=%s > ask=%s) - rejecting",
                        ticker, best_bid, best_ask
                    )
                    return None

                # Determine market status
                status = "open"
                if "status" in market:
                    status = str(market["status"]).lower()

                # If market is closed/paused, mark as suspended
                if status in ("closed", "paused"):
                    with self._lock:
                        self._health_state[ticker] = QuoteHealth.SUSPENDED
                    logger.warning("[market-state] Market %s is %s - suspending and rejecting quote", ticker, status)
                    return None

                # Check if we have valid prices from REST
                has_valid_prices = (
                    (mid and 0 < mid < 100) or
                    (best_bid and 0 < best_bid < 100) or
                    (best_ask and 0 < best_ask < 100)
                )

                if not has_valid_prices:
                    # DIAGNOSTIC: Log actual values to understand why validation fails
                    logger.error(
                        "[market-state] REST fetch for %s returned invalid prices - rejecting. "
                        "Price source: %s. "
                        "Raw market data: yes_bid=%s, yes_ask=%s, last_price=%s, "
                        "yes_bid_dollars=%s, yes_ask_dollars=%s, last_price_dollars=%s. "
                        "Parsed values: mid=%s, best_bid=%s, best_ask=%s. "
                        "Validation checks: mid_valid=%s, bid_valid=%s, ask_valid=%s",
                        ticker, price_source,
                        market.get("yes_bid"), market.get("yes_ask"), market.get("last_price"),
                        market.get("yes_bid_dollars"), market.get("yes_ask_dollars"), market.get("last_price_dollars"),
                        mid, best_bid, best_ask,
                        (mid and 0 < mid < 100), (best_bid and 0 < best_bid < 100), (best_ask and 0 < best_ask < 100)
                    )
                    return None

                # Log when dollar fields were used as fallback
                if price_source == "dollars":
                    logger.info(
                        "[market-state] REST fallback using dollar-denominated fields for %s: "
                        "mid=%s, bid=%s, ask=%s",
                        ticker, mid, best_bid, best_ask
                    )

                # Calculate age_ms and confidence for REST quote
                # Use updated_time from REST response if available, otherwise use current time
                ts_exchange = market.get("updated_time", time.time())
                if isinstance(ts_exchange, str):
                    # Parse ISO timestamp if it's a string
                    try:
                        from datetime import datetime
                        ts_exchange = datetime.fromisoformat(ts_exchange.replace("Z", "+00:00")).timestamp()
                    except (ValueError, AttributeError):
                        ts_exchange = time.time()
                elif not isinstance(ts_exchange, (int, float)):
                    ts_exchange = time.time()

                # Use time.time() for both to ensure consistent clock comparison
                now = time.time()
                age_ms = (now - ts_exchange) * 1000.0

                # Calculate confidence based on age (configurable thresholds)
                # REST fallback gets lower confidence but can be HEALTHY if fresh
                import os
                _rest_healthy_threshold_ms = float(os.getenv("MERID_KALSHI_REST_HEALTHY_THRESHOLD_MS", "5000"))  # Default 5s
                _rest_degraded_threshold_ms = float(os.getenv("MERID_KALSHI_REST_DEGRADED_THRESHOLD_MS", "30000"))  # Default 30s
                _rest_high_confidence = float(os.getenv("MERID_KALSHI_REST_HIGH_CONFIDENCE", "0.8"))  # Default 0.8
                _rest_mid_confidence = float(os.getenv("MERID_KALSHI_REST_MID_CONFIDENCE", "0.6"))  # Default 0.6
                _rest_low_confidence = float(os.getenv("MERID_KALSHI_REST_LOW_CONFIDENCE", "0.5"))  # Default 0.5

                # Validate and clamp thresholds to sane ranges
                if _rest_healthy_threshold_ms < 0:
                    logger.warning("[market-state] REST healthy threshold must be >= 0ms, clamping to 0ms")
                    _rest_healthy_threshold_ms = 0
                if _rest_degraded_threshold_ms <= _rest_healthy_threshold_ms:
                    logger.warning(
                        "[market-state] REST degraded threshold (%.1fms) must be > healthy threshold (%.1fms), setting degraded to healthy + 30s",
                        _rest_degraded_threshold_ms, _rest_healthy_threshold_ms
                    )
                    _rest_degraded_threshold_ms = _rest_healthy_threshold_ms + 30000

                # Validate and clamp confidence values to [0, 1]
                _rest_high_confidence_clamped = _rest_high_confidence
                _rest_mid_confidence_clamped = _rest_mid_confidence
                _rest_low_confidence_clamped = _rest_low_confidence
                for name, val in [("high", _rest_high_confidence), ("mid", _rest_mid_confidence), ("low", _rest_low_confidence)]:
                    if not (0.0 <= val <= 1.0):
                        logger.warning(
                            "[market-state] REST %s confidence %.2f is outside [0,1], clamping to nearest bound",
                            name, val
                        )
                        if val < 0:
                            val = 0.0
                        else:
                            val = 1.0
                        if name == "high":
                            _rest_high_confidence_clamped = val
                        elif name == "mid":
                            _rest_mid_confidence_clamped = val
                        else:
                            _rest_low_confidence_clamped = val

                # Use clamped values for actual assignment
                _rest_high_confidence = _rest_high_confidence_clamped
                _rest_mid_confidence = _rest_mid_confidence_clamped
                _rest_low_confidence = _rest_low_confidence_clamped

                if age_ms < _rest_healthy_threshold_ms:
                    confidence = _rest_high_confidence
                    health = QuoteHealth.HEALTHY
                    logger.info(
                        "[market-state] REST fallback quote for %s is fresh (age=%.1fms < %.1fms): confidence=%.2f, health=HEALTHY",
                        ticker, age_ms, _rest_healthy_threshold_ms, confidence
                    )
                elif age_ms < _rest_degraded_threshold_ms:
                    confidence = _rest_mid_confidence
                    health = QuoteHealth.HEALTHY
                    logger.info(
                        "[market-state] REST fallback quote for %s is moderately fresh (age=%.1fms < %.1fms): confidence=%.2f, health=HEALTHY",
                        ticker, age_ms, _rest_degraded_threshold_ms, confidence
                    )
                else:
                    confidence = _rest_low_confidence
                    health = QuoteHealth.DEGRADED
                    logger.warning(
                        "[market-state] REST fallback quote for %s is stale (age=%.1fms >= %.1fms): confidence=%.2f, health=DEGRADED",
                        ticker, age_ms, _rest_degraded_threshold_ms, confidence
                    )

                # Build quote
                quote = MarketQuote(
                    market_ticker=ticker,
                    series_ticker=series_ticker,
                    best_bid_cents=best_bid,
                    best_ask_cents=best_ask,
                    mid_cents=mid,
                    status=status,
                    source=QuoteSource.REST,
                    ts_exchange=ts_exchange,
                    ts_received=now,
                    age_ms=age_ms,
                    confidence=confidence,
                    is_fallback=True,
                    health=health,
                    diagnostics=[f"No cached data, using REST fallback (age={age_ms/1000:.1f}s)"]
                )

                # Update health state based on calculated health (not hardcoded to DEGRADED)
                with self._lock:
                    if self._health_state.get(ticker) != QuoteHealth.SUSPENDED:
                        self._health_state[ticker] = health

                logger.info(
                    "[market-state] REST fallback successful for %s: age=%.1fms, confidence=%.2f, health=%s, status=%s",
                    ticker, age_ms, confidence, health, status
                )
                return quote

            return None

        except Exception as e:
            logger.error("[market-state] REST fetch failed for %s: %s", ticker, e)
            with self._lock:
                self._consecutive_failures[ticker] = self._consecutive_failures.get(ticker, 0) + 1
                # Trigger circuit breaker if threshold reached with exponential backoff
                if self._consecutive_failures[ticker] >= _CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                    self._health_state[ticker] = QuoteHealth.SUSPENDED
                    # Use exponential backoff for recovery time
                    backoff = self._get_exponential_backoff(self._consecutive_failures[ticker] - _CIRCUIT_BREAKER_FAILURE_THRESHOLD)
                    recovery_time = max(_CIRCUIT_BREAKER_RECOVERY_SECONDS, backoff)
                    self._circuit_breaker_until[ticker] = time.monotonic() + recovery_time
                    self._record_metric(ticker, "breaker_opens", 1.0)
                    logger.error(
                        "[market-state] Circuit breaker triggered for %s after %d consecutive failures - suspended for %.1fs (backoff: %.1fs)",
                        ticker, self._consecutive_failures[ticker], recovery_time, backoff
                    )
            return None

    # ── Candle / external-index write paths ────────────────────────────

    def apply_candle_dict(
        self,
        ticker: str,
        bar: Dict[str, Any],
        *,
        period_interval: int = 60,
    ) -> Optional[UnifiedMarketState]:
        """Merge a raw candlestick dict into the per-ticker ``UnifiedMarketState``.

        Called by ``CandlePoller`` after each successful REST fetch.
        The bar dict is expected to have Kalshi-style keys:
        ``ts``, ``open``, ``high``, ``low``, ``close``, ``volume``.
        Price values are in cents (0–100).

        Returns the updated ``UnifiedMarketState``, or ``None`` if *ticker*
        or the bar dict is invalid.
        """
        if not ticker or not bar:
            return None

        # ── Synthetic bar guard ─────────────────────────────────────────────
        # Kalshi's include_latest_before_start can prepend a synthetic candle
        # where OHLC are null and only previous_price is set. Reject these
        # to avoid feeding fake 0-price bars into the state machine.
        close = bar.get("close") or bar.get("close_cents")
        ts = bar.get("ts") or bar.get("start_ts")
        if close is None or ts is None:
            logger.debug("[market-state] Ignoring synthetic/malformed bar for %s", ticker)
            return None
        # ─────────────────────────────────────────────────────────────────────

        try:
            candle = Candlestick(
                ticker=ticker,
                ts=float(bar.get("ts") or bar.get("start_ts") or time.time()),
                open_cents=int(bar.get("open") or bar.get("open_cents") or 0),
                high_cents=int(bar.get("high") or bar.get("high_cents") or 0),
                low_cents=int(bar.get("low") or bar.get("low_cents") or 0),
                close_cents=int(bar.get("close") or bar.get("close_cents") or 0),
                volume=int(bar.get("volume") or 0),
                open_interest=int(bar.get("open_interest") or 0),
                period_interval=period_interval,
            )
        except (TypeError, ValueError) as exc:
            logger.debug("[market-state] apply_candle_dict bad bar for %s: %s", ticker, exc)
            return None

        with self._lock:
            u = self._get_or_create_unified(ticker)
            u.latest_candle = candle
            # Keep candles list bounded to last 100 bars (newest at end)
            u.candles.append(candle)
            if len(u.candles) > 100:
                u.candles = u.candles[-100:]
            u.candle_updated_ts = candle.ts
            recompute_derived(u)
            return u

    def apply_external_index(
        self,
        ticker: str,
        snapshot: ExternalIndexSnapshot,
    ) -> Optional[UnifiedMarketState]:
        """Merge an ``ExternalIndexSnapshot`` into the per-ticker ``UnifiedMarketState``.

        Called by the CFB RTI adapter or any external price feed after each tick.
        Triggers ``recompute_derived()`` so ``index_updated_ts``, ``edge_basis``,
        and ``external_fair_value`` are updated immediately.

        D-C1 safety: ``recompute_derived`` guards against ``snapshot.ts is None``
        internally — no crash even if the feed delivers a corrupt tick.
        """
        if not ticker or snapshot is None:
            return None
        with self._lock:
            u = self._get_or_create_unified(ticker)
            u.external = snapshot
            recompute_derived(u)
            return u

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_or_create(self, ticker: str) -> KalshiMarketState:
        # CRITICAL FIX: Remove scope validation from state store
        # The catalog already filters to only allowed markets (BTC/ETH/SOL/XRP/DOGE 15m)
        # The state store should accept any ticker that the catalog feeds it
        # This ensures expiry data is persisted for all 5 markets
        # RACE CONDITION FIX: Use global lock to prevent concurrent creation of same ticker state
        # This method is called from multiple code paths with different locks held, so we need
        # to ensure atomic check-and-create to avoid duplicate state objects
        with self._global_lock:
            if ticker not in self._states:
                self._states[ticker] = KalshiMarketState(ticker=ticker)
                # 2026-08-24: Start the snapshot timeout clock when a ticker is first
                # registered; if no valid snapshot arrives in time, we resubscribe.
                self._snapshot_wait_start_ts[ticker] = time.monotonic()
                underlying, timeframe = _parse_market_ticker(ticker)
                logger.info(
                    "[MARKET-STATE] book_registered ticker=%s underlying=%s timeframe=%s total_states=%d",
                    ticker, underlying, timeframe, len(self._states)
                )
            return self._states[ticker]

    def _set_book_health(
        self,
        ticker: str,
        health: BookHealth,
        reason: str = "",
    ) -> None:
        """Set the explicit book health state for *ticker* and emit a canonical log.

        The BookHealth state machine is the single source of truth for the
        orderbook trust lifecycle.  It is updated at every snapshot, delta,
        sequence gap, and resync boundary while leaving the legacy
        data_quality / book_consistency / transition fields in place for
        downstream compatibility.
        """
        state = self._get_or_create(ticker)
        old = state.book_health
        new = health.value
        if old == new:
            return
        state.book_health = new
        logger.info(
            "[BOOK-HEALTH] ticker=%s old=%s new=%s reason=%s",
            ticker, old, new, reason or "state_transition",
        )

    def _set_snapshot_complete(
        self,
        ticker: str,
        complete: bool,
        reason: str,
    ) -> None:
        """Set the ``snapshot_complete`` flag and emit a canonical lifecycle log.

        This is the single mutation point for the snapshot completion flag.  It
        is set to True only when a full, valid orderbook snapshot is applied (WS
        orderbook_snapshot or authoritative REST snapshot) and reset to False on
        sequence gaps, invalidation, resync, reconnect, or ticker rollover.  Deltas
        alone must never set or re-assert this flag.
        """
        state = self._get_or_create(ticker)
        old = bool(state.snapshot_complete)
        new = bool(complete)
        if old == new:
            # Still log the reason when the state is being re-affirmed for
            # traceability, but only at debug level to avoid spam.
            logger.debug(
                "[SNAPSHOT-COMPLETE-LIFECYCLE] ticker=%s ws_snapshot_complete=%s reason=%s (unchanged)",
                ticker, new, reason,
            )
            return
        state.snapshot_complete = new
        if new:
            self._snapshot_wait_start_ts.pop(ticker, None)
        else:
            self._snapshot_wait_start_ts[ticker] = time.monotonic()
        logger.info(
            "[SNAPSHOT-COMPLETE-LIFECYCLE] ticker=%s ws_snapshot_complete=%s reason=%s",
            ticker, new, reason,
        )

    def _check_snapshot_timeout(self, ticker: str) -> None:
        """If a ticker has been waiting for a snapshot too long, invalidate it
        and request a fresh snapshot.  This breaks the dead-ready state where the
        WebSocket is subscribed but no orderbook snapshot is ever received.
        """
        state = self._states.get(ticker)
        if state is None or state.snapshot_complete:
            return

        wait_start = self._snapshot_wait_start_ts.get(ticker)
        if wait_start is None:
            # First time we have noticed this ticker needs a snapshot; start the clock.
            self._snapshot_wait_start_ts[ticker] = time.monotonic()
            return

        elapsed = time.monotonic() - wait_start
        if elapsed <= _SNAPSHOT_TIMEOUT_SECONDS:
            return

        # Only act once per timeout window by refreshing the wait start.
        self._snapshot_wait_start_ts[ticker] = time.monotonic()

        logger.warning(
            "[SNAPSHOT-TIMEOUT] ticker=%s elapsed_since_reset=%.1fs timeout=%.1fs - "
            "invalidating book and requesting fresh snapshot",
            ticker, elapsed, _SNAPSHOT_TIMEOUT_SECONDS,
        )

        state.data_quality = "INVALID"
        state.executable = False
        state.book_initialized = False
        state.transition = "SNAPSHOT_TIMEOUT"
        state.invalidation_cause = "SNAPSHOT_TIMEOUT"
        state.recovery_required_source = "FULL_SNAPSHOT"
        self._set_book_health(ticker, BookHealth.RESYNC_REQUESTED, "snapshot_timeout")
        self._set_snapshot_complete(ticker, False, "snapshot_timeout")

        # Request a fresh WebSocket snapshot if the event loop is available.
        try:
            loop = self._main_event_loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._trigger_snapshot_recovery(ticker), loop
                )
        except Exception as e:
            logger.error("[SNAPSHOT-TIMEOUT] Failed to schedule snapshot recovery for %s: %s", ticker, e)

    def _validate_delta_sequence(
        self,
        ticker: str,
        msg: Dict[str, Any],
        ob: Any,
    ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Lightweight sequence-gap validator for a single WS orderbook delta.

        Returns (is_valid, expected_seq, got_seq).  is_valid is True when the
        message is contiguous with ``ob.last_seq`` (or when no sequence check
        can be performed, e.g. no prior sequence).  This is intentionally stateless
        with respect to ``KalshiMarketState``; callers handle invalidation and resync.
        """
        if not ob or not ob.initialized or ob.last_seq is None:
            return True, None, None

        msg_seq = msg.get("seq_first") or msg.get("seq")
        if msg_seq is None:
            return True, None, None

        try:
            msg_seq = int(msg_seq)
        except Exception:
            return True, None, None

        expected = ob.last_seq + 1
        if msg_seq != expected:
            return False, expected, msg_seq

        return True, expected, msg_seq

    def _coalesce_deltas(
        self,
        ticker: str,
        batch: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Coalesce a contiguous run of same-(side, price) delta_fp messages.

        Returns a list of merged messages.  Each merged message carries:
        - ``seq_first``: the first sequence number in the run (for the gap validator)
        - ``seq``: the last sequence number in the run (for ``_last_seq``)
        - ``delta_fp``: the sum of signed size changes
        - ``price_dollars`` and ``side`` from the run

        If the batch is not contiguous, or any message is not in the simple
        ``delta_fp`` form, the original batch is returned unchanged.
        """
        ob = self._ob.get_book(ticker)
        if not ob or not ob.initialized or ob.last_seq is None or not batch:
            return batch

        def _delta_key(msg: Dict[str, Any]) -> Tuple[Optional[str], Optional[int], Optional[float], Optional[int]]:
            # Extract side
            side = msg.get("side") or msg.get("outcome_side") or msg.get("kalshi_side")
            if side is None:
                return None, None, None, None
            side = side.lower()
            if side not in ("yes", "no"):
                return None, None, None, None

            # Extract price in cents
            price_cents: Optional[int] = None
            if "price_dollars" in msg:
                try:
                    price_dollars = float(msg["price_dollars"]) if isinstance(msg["price_dollars"], str) else msg["price_dollars"]
                    price_cents = int(round(price_dollars * 100))
                except Exception:
                    pass
            elif "price" in msg:
                try:
                    price_cents = int(round(float(msg["price"])))
                except Exception:
                    pass

            if price_cents is None or not 1 <= price_cents <= 99:
                return None, None, None, None

            # Extract size delta
            size_delta: Optional[float] = None
            if "delta_fp" in msg:
                try:
                    size_delta = float(msg["delta_fp"]) if isinstance(msg["delta_fp"], str) else float(msg["delta_fp"])
                except Exception:
                    pass
            elif "size_delta" in msg:
                try:
                    size_delta = float(msg["size_delta"])
                except Exception:
                    pass
            elif "delta" in msg:
                try:
                    size_delta = float(msg["delta"])
                except Exception:
                    pass

            if size_delta is None:
                return None, None, None, None

            # Extract sequence
            msg_seq = msg.get("seq")
            if msg_seq is None:
                return None, None, None, None
            try:
                msg_seq = int(msg_seq)
            except Exception:
                return None, None, None, None

            return side, price_cents, size_delta, msg_seq

        coalesced: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        contiguous = True
        last_seq = ob.last_seq

        for msg in batch:
            side, price_cents, size_delta, msg_seq = _delta_key(msg)
            if side is None:
                # Cannot coalesce this message; flush any current group and fall back.
                if current:
                    coalesced.append(current)
                    current = None
                return batch

            if msg_seq != last_seq + 1:
                contiguous = False
                break

            if (
                current is not None
                and current["side"] == side
                and current["price_cents"] == price_cents
                and msg_seq == current["seq"] + 1
            ):
                # Extend the current contiguous same-(side, price) run.
                current["delta_fp"] += size_delta
                current["seq"] = msg_seq
                current["_last_msg"] = msg
            else:
                if current is not None:
                    coalesced.append(current)
                template = dict(msg)
                template["side"] = side
                template["price_dollars"] = price_cents / 100.0
                template["delta_fp"] = size_delta
                template["seq"] = msg_seq
                template["seq_first"] = msg_seq
                template["price_cents"] = price_cents
                template.pop("_last_msg", None)
                current = template

            last_seq = msg_seq

        if current is not None:
            coalesced.append(current)

        if not contiguous or not coalesced:
            return batch

        # The first coalesced message must be contiguous with the book.
        if coalesced[0]["seq_first"] != ob.last_seq + 1:
            return batch

        # Finalize: keep the last message as a template for metadata, but override
        # the aggregated values and use the last message's timestamp if present.
        finalized: List[Dict[str, Any]] = []
        for c in coalesced:
            last_msg = c.pop("_last_msg", None)
            out = dict(last_msg) if last_msg is not None else c
            out.update({
                "side": c["side"],
                "price_dollars": c["price_dollars"],
                "delta_fp": round(c["delta_fp"], 8),
                "seq": c["seq"],
                "seq_first": c["seq_first"],
                "price_cents": c["price_cents"],
            })
            finalized.append(out)

        return finalized

    def _get_or_create_unified(self, ticker: str) -> UnifiedMarketState:
        """Return the ``UnifiedMarketState`` for *ticker*, creating it if absent.

        Must be called with ``self._lock`` held.
        """
        if ticker not in self._unified:
            self._unified[ticker] = UnifiedMarketState(ticker=ticker)
        return self._unified[ticker]

    def _sync_unified_book(self, ticker: str, state: KalshiMarketState) -> None:
        """Rebuild the book snapshot in ``UnifiedMarketState`` from *state* and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)

        # Build typed OrderbookSnapshot from the flat KalshiMarketState fields.
        # D-H2: require BOTH sides to be non-empty before assembling a snapshot.
        # A one-sided book produces spread_cents=None, mid_cents=None, and
        # implied_prob=None — all None — which confuses downstream consumers.
        yes_bids_raw = state.yes_bids or []
        no_bids_raw = state.no_bids or []

        if not yes_bids_raw or not no_bids_raw:
            # One-sided or empty book — do not assemble a snapshot.
            # Leave u.book as-is (None on first update; keep last valid book
            # until a two-sided book arrives so stale-book detection still fires).
            u.book = None
            recompute_derived(u)
            return

        def _to_levels(raw: list) -> tuple:
            levels = []
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    levels.append(OrderbookLevel(price_cents=int(item[0]), size=int(item[1])))
                elif isinstance(item, dict):
                    levels.append(
                        OrderbookLevel(
                            price_cents=int(item.get("price", item.get("price_cents", 0))),
                            size=int(item.get("size", item.get("quantity", 0))),
                        )
                    )
            return tuple(levels)

        # CRITICAL FIX (2026-08-02): Preserve upstream timestamp instead of discarding it
        state_ts = state.last_book_update_ts if hasattr(state, 'last_book_update_ts') else None
        # CRITICAL FIX (2026-08-02): Ensure timestamp is never None or 0.0 - use current time as fallback
        # This prevents book_age_s from returning infinity and causing order rejections
        if state_ts is None or state_ts == 0.0:
            book_ts = time.time()
            logger.debug(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} Using current time as timestamp: state.last_book_update_ts={state_ts} -> book_ts={book_ts}")
        else:
            book_ts = state_ts

        book = OrderbookSnapshot(
            ticker=ticker,
            yes_bids=_to_levels(yes_bids_raw),
            no_bids=_to_levels(no_bids_raw),
            ts=book_ts,
        )
        u.book = book
        u.book_updated_ts = book_ts
        logger.info(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} PRESERVED timestamp: state.last_book_update_ts={state_ts} u.book_updated_ts={u.book_updated_ts}")
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        recompute_derived(u)

    def _sync_unified_rest(self, ticker: str, state: KalshiMarketState) -> None:
        """Propagate REST-owned fields into ``UnifiedMarketState`` and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        u.rest_updated_ts = time.time()
        recompute_derived(u)

    def _track_duality_violation(self, ticker: str, gap: Optional[int]) -> None:
        """Track duality violations and trigger resync if threshold exceeded.

        CRITICAL FIX (2026-07-29): Added violation counting to prevent resync storms.
        Only trigger REST re-sync if violations exceed threshold within time window.
        This prevents cascading failures from transient duality gaps in thin markets.

        Args:
            ticker: Market ticker
            gap: Duality gap in cents (None if NO ladder empty)
        """
        # CRITICAL FIX (2026-07-29): Record telemetry for duality violations
        try:
            from merid.event_venues.kalshi.metrics import get_metrics_collector
            metrics = get_metrics_collector()
            metrics.record_duality_violation(ticker, gap)
        except Exception as e:
            logger.debug("[METRICS] Failed to record duality violation telemetry: %s", e)

        now = time.monotonic()
        if not hasattr(self, "_duality_violation_counts"):
            self._duality_violation_counts = {}
        if not hasattr(self, "_duality_violation_window_ts"):
            self._duality_violation_window_ts = {}

        # Initialize tracking for ticker
        if ticker not in self._duality_violation_counts:
            self._duality_violation_counts[ticker] = 0
            self._duality_violation_window_ts[ticker] = now

        # Reset count if window expired (30s window)
        if now - self._duality_violation_window_ts[ticker] > 30.0:
            self._duality_violation_counts[ticker] = 0
            self._duality_violation_window_ts[ticker] = now

        # Increment violation count
        self._duality_violation_counts[ticker] += 1

        # Only trigger resync if violations exceed threshold (3 in 30s)
        if self._duality_violation_counts[ticker] >= 3:
            logger.warning(
                "[DUALITY-RESYNC-TRIGGER] ticker=%s violations=%d in 30s window - triggering REST re-sync",
                ticker, self._duality_violation_counts[ticker]
            )
            self._schedule_duality_resync(ticker)
        else:
            logger.info(
                "[DUALITY-RESYNC-SUPPRESSED] ticker=%s violations=%d (threshold=3) - resync suppressed",
                ticker, self._duality_violation_counts[ticker]
            )
            # CRITICAL FIX (2026-07-29): Record telemetry for suppressed resyncs
            try:
                from merid.event_venues.kalshi.metrics import get_metrics_collector
                metrics = get_metrics_collector()
                metrics.record_duality_resync_suppressed(ticker, self._duality_violation_counts[ticker])
            except Exception as e:
                logger.debug("[METRICS] Failed to record suppressed resync telemetry: %s", e)

    def _clear_duality_violation(self, ticker: str) -> None:
        """Clear duality violation tracking for a ticker.

        Called when book passes duality check, resetting violation counters.
        """
        if hasattr(self, "_duality_violation_counts") and ticker in self._duality_violation_counts:
            self._duality_violation_counts[ticker] = 0
            logger.debug("[DUALITY-CLEAR] ticker=%s violation count cleared", ticker)

    def _schedule_duality_resync(self, ticker: str) -> None:
        """Schedule a REST snapshot re-sync for a book that violated YES/NO duality.

        Rate-limited with exponential backoff (10s base, doubling to 60s max) per ticker
        and thread-safe: uses ``run_coroutine_threadsafe`` against the captured main
        event loop, matching the WS-DELTA-BOOTSTRAP pattern. Safe to call while holding
        ``self._lock`` since it only schedules work.

        CRITICAL FIX (2026-07-29): Added exponential backoff to prevent circuit breaker
        trips from repeated duality violations. Thin 15m crypto markets can have persistent
        duality gaps due to one-sided flow; aggressive resync loops were triggering event
        loop resets and tripping the circuit breaker (5 resets in 60s).
        """
        now = time.monotonic()
        if not hasattr(self, "_last_duality_resync_ts"):
            self._last_duality_resync_ts = {}
        if not hasattr(self, "_duality_resync_backoff_s"):
            self._duality_resync_backoff_s = {}

        last_ts = self._last_duality_resync_ts.get(ticker, 0.0)
        backoff_s = self._duality_resync_backoff_s.get(ticker, 10.0)

        if now - last_ts < backoff_s:
            return

        # Exponential backoff: 10s → 20s → 40s → 60s (max)
        self._duality_resync_backoff_s[ticker] = min(backoff_s * 2, 60.0)
        self._last_duality_resync_ts[ticker] = now

        # CRITICAL FIX (2026-07-29): Record telemetry for triggered resyncs
        try:
            from merid.event_venues.kalshi.metrics import get_metrics_collector
            metrics = get_metrics_collector()
            metrics.record_duality_resync_triggered(ticker, backoff_s)
        except Exception as e:
            logger.debug("[METRICS] Failed to record triggered resync telemetry: %s", e)

        try:
            import asyncio
            loop = getattr(self, "_main_event_loop", None)
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._sync_invariant_violation_with_rest(ticker), loop
                )
                logger.info(
                    "[DUALITY-RESYNC] Scheduled REST re-sync for %s (backoff=%.1fs)",
                    ticker, backoff_s
                )
            else:
                logger.warning("[DUALITY-RESYNC] Event loop unavailable for %s", ticker)
        except Exception as e:
            logger.error("[DUALITY-RESYNC] Failed to schedule REST re-sync for %s: %s", ticker, e)

    def _sync_book_fields(
        self, state: KalshiMarketState, ob: LocalOrderbook, ticker: str, via: str = "unknown"
    ) -> None:
        """Copy the book-owned fields from a ``LocalOrderbook`` into *state*.

        DEADLOCK-FIX (2026-05-12): This method is called from apply_orderbook_message
        which already holds self._lock. Therefore, this method must NOT acquire the lock.
        All state mutations happen here under the caller's lock.

        Thread-safety: LocalOrderbook is shared across threads via MultiMarketOrderbook.
        This method assumes the caller already holds self._lock.

        Args:
            state: KalshiMarketState to update
            ob: LocalOrderbook to copy from
            ticker: Market ticker
            via: Provenance tag for transport health tracking
        """
        # All operations here are under the caller's lock (from apply_orderbook_message)

        # CRITICAL FIX (2026-08-22): Capture the pre-update quality/transition so
        # that quote overrides and tentatively-set GOOD values do not silently
        # clear an INVALID / CIRCUIT_BREAKER state.
        prior_quality = state.data_quality
        prior_transition = state.transition

        # If the local orderbook has a fresh snapshot/delta, start from GOOD and
        # let the invariant checks downgrade it.  A non-initialized book does not
        # change the stored quality; callers (or apply_quote) attest recovery.
        if ob.initialized:
            state.data_quality = "GOOD"
            state.book_consistency = "GOOD"
            state.transition = "VALID"

        # CRITICAL FIX (2026-08-22): Use a single monotonic clock for in-process
        # staleness.  ``ob._snapshot_ts`` and any exchange ``ts`` are logged via
        # wall-clock fields but are not safe for ``time.monotonic()`` subtraction.
        state.last_book_update_ts = time.monotonic()
        state.last_book_update_wall_ts = time.time()
        ob_ts = getattr(ob, '_last_exchange_ts', None) or getattr(ob, '_snapshot_ts', None)
        if ob_ts is not None:
            logger.debug(f"[BOUNDARY-3-LOCAL→STATE] ticker={ticker} snapshot_applied exchange_ts={ob_ts} local_ts={state.last_book_update_ts}")
        else:
            logger.debug(f"[BOUNDARY-3-LOCAL→STATE] ticker={ticker} snapshot_applied local_ts={state.last_book_update_ts}")

        state.book_initialized = ob.initialized
        state.last_update_ts = time.monotonic()  # FIX: Update last_update_ts for staleness checks

        # P1 FIX: Set transport health fields based on via parameter
        if via == "bridge_queue":
            state.transport_mode = "ws"
        elif via.startswith("rest"):
            state.transport_mode = "rest"
        else:
            state.transport_mode = "unknown"

        if not ob.initialized:
            return

        yes_bids = ob.get_book("yes", top_n=_TOP_N_BOOK_LEVELS)
        no_bids = ob.get_book("no", top_n=_TOP_N_BOOK_LEVELS)

        # DIAGNOSTIC: Log ladder levels for debugging best_ask_cents issue
        logger.debug(
            "[WS-ORDERBOOK-PARSED] ticker=%s yes_levels=%d no_levels=%d best_yes=%s best_no=%s",
            ticker,
            len(ob.yes_levels),
            len(ob.no_levels),
            max(ob.yes_levels.keys()) if ob.yes_levels else None,
            max(ob.no_levels.keys()) if ob.no_levels else None,
        )

        best_bid = ob.get_best_bid()    # (price_cents, size) or None
        best_ask = ob.get_best_ask()    # (yes_equivalent_cents, size) or None
        mid = ob.get_midpoint()
        spread = ob.get_spread()

        # PRODUCTION INVARIANT: YES/NO duality check
        # Kalshi binary markets have YES + NO = 100 cents invariant.
        # The orderbook carries YES bids and NO bids (asks are derived as 100 - opposite bid),
        # so the correct invariant is: YES_bid + NO_bid = 100 - spread, i.e.
        #   0 <= 100 - (YES_bid + NO_bid) <= tolerance
        # CRITICAL FIX (2026-07-26): The previous check compared abs(YES_bid - NO_bid),
        # which is mathematically wrong (a healthy 32/66 book "diverged" while a corrupt
        # 33/1 one-sided book could pass). Corrupt books were then accepted and fed into
        # signal generation and execution pricing, producing synthetic 99c asks and
        # non-marketable orders.
        # CRITICAL FIX (2026-07-29): Separated book_initialized from executable.
        # book_initialized=True once any snapshot is loaded (data availability).
        # executable=False only when duality violations exceed threshold (data quality).
        # This prevents BOOK_NOT_INITIALIZED rejections when book is loaded but has duality issues.
        duality_violation = False
        if best_bid is not None and best_ask is not None:
            best_yes_bid = best_bid[0]
            best_yes_ask = best_ask[0]

            # Get actual NO bid from NO levels if available
            if ob.no_levels:
                actual_best_no_bid = max(ob.no_levels.keys())

                # HARDENING-FIX: Read from threshold_config instead of hardcoded literal
                duality_tolerance_cents = _threshold_config.get_duality_thresholds().duality_tolerance_cents
                duality_gap = 100 - (best_yes_bid + actual_best_no_bid)
                yes_no_sum = best_yes_bid + actual_best_no_bid

                # CRITICAL FIX (2026-07-26): Use absolute gap for symmetric tolerance
                # A gap of -1c (YES+NO=101c) is as acceptable as +1c (YES+NO=99c)
                # Both represent 1c deviation from perfect duality
                if abs(duality_gap) > duality_tolerance_cents:
                    duality_violation = True
                    logger.warning(
                        "[DUALITY-RAW-OB-VIOLATION] ticker=%s "
                        "yes_bid=%dc no_bid=%dc sum=%dc gap=%dc (tolerance=%dc) | "
                        "yes_levels=%s no_levels=%s | "
                        "Book violates YES+NO=100 duality - marking non-executable and "
                        "triggering REST re-sync.",
                        ticker,
                        best_yes_bid, actual_best_no_bid, yes_no_sum, duality_gap, duality_tolerance_cents,
                        sorted(ob.yes_levels.items())[-3:], sorted(ob.no_levels.items())[-3:]
                    )
                    # Track violation count and window before triggering resync
                    self._track_duality_violation(ticker, duality_gap)
                else:
                    # Clear violation count on healthy book
                    self._clear_duality_violation(ticker)
            else:
                # NO side of the book is entirely missing - one-sided/corrupt book.
                duality_violation = True
                logger.warning(
                    "[DUALITY-RAW-OB-VIOLATION] ticker=%s NO ladder empty (yes_bid=%dc) - "
                    "one-sided book, marking non-executable and triggering REST re-sync.",
                    ticker, best_yes_bid
                )
                self._track_duality_violation(ticker, None)

        # DIAGNOSTIC: Log computed best_bid/best_ask for debugging
        logger.debug(
            "[WS-ORDERBOOK-BBA] ticker=%s yes_bid=%s yes_ask=%s no_bid=%s no_ask=%s",
            ticker,
            best_bid[0] if best_bid else None,
            best_ask[0] if best_ask else None,
            max(ob.no_levels.keys()) if ob.no_levels else None,
            100 - max(ob.yes_levels.keys()) if ob.yes_levels else None,
        )

        state.yes_bids = yes_bids
        state.no_bids = no_bids
        state.best_bid_cents = best_bid[0] if best_bid else None
        state.best_ask_cents = best_ask[0] if best_ask else None

        # 2026-08-24: Track per-feed BBO ownership and timestamps.
        now = time.monotonic()
        if via == "bridge_queue":
            state.last_ws_bid_cents = state.best_bid_cents
            state.last_ws_ask_cents = state.best_ask_cents
            state.last_ws_update_ts = now
            state.quote_owner = "WS"
        elif via.startswith("rest") or via == "ws_fallback" or via == "subscribe_fallback" or via == "rest_polling" or via == "ws_subscribe_bootstrap":
            state.last_rest_bid_cents = state.best_bid_cents
            state.last_rest_ask_cents = state.best_ask_cents
            # Quote freshness is tracked separately from general REST metadata so
            # that catalog/apply_rest_market cannot overwrite the quote clock.
            state.last_rest_quote_update_ts = now
            # Keep the legacy REST freshness marker for transport/health consumers.
            state.last_rest_update_ts = now
            state.quote_owner = "REST"

        # Ticker quote fallback: the orderbook_delta stream is one-sided, so the
        # local ladder can become crossed or one-sided if the opposite tape lags.
        # The ticker channel is an independent top-of-book source; use it as a
        # temporary BBO fallback while the orderbook rebuilds a consistent ladder.
        # CRITICAL FIX (2026-08-22): Quote fallbacks must not clear an
        # INVALID / CIRCUIT_BREAKER state; only authoritative REST snapshots or
        # contiguous WS deltas can attest recovery.
        quote_override_allowed = (
            prior_quality != "INVALID"
            and prior_transition != "CIRCUIT_BREAKER"
        )
        quote_override_used = False
        if state.quoted_bid_cents is not None and state.quoted_ask_cents is not None:
            quote_age_s = time.monotonic() - state.quote_received_ts if state.quote_received_ts > 0 else float('inf')
            quote_valid = (
                state.quoted_bid_cents < state.quoted_ask_cents
                and 1 <= state.quoted_bid_cents <= 99
                and 1 <= state.quoted_ask_cents <= 99
                and quote_age_s <= _MAX_QUOTE_OVERRIDE_AGE_SECONDS
            )
            if quote_valid and quote_override_allowed:
                ob_crossed = (
                    state.best_bid_cents is not None
                    and state.best_ask_cents is not None
                    and state.best_bid_cents >= state.best_ask_cents
                )
                ob_one_sided = state.best_bid_cents is None or state.best_ask_cents is None
                if ob_crossed or ob_one_sided:
                    state.best_bid_cents = state.quoted_bid_cents
                    state.best_ask_cents = state.quoted_ask_cents
                    quote_override_used = True
                    duality_violation = False
                    self._clear_duality_violation(ticker)
                    logger.debug(
                        "[WS-TICKER-FALLBACK] ticker=%s bid=%s ask=%s quote_age_s=%.2f - "
                        "using ticker BBO because orderbook was %s",
                        ticker,
                        state.quoted_bid_cents,
                        state.quoted_ask_cents,
                        quote_age_s,
                        "crossed" if ob_crossed else "one-sided",
                    )

        # CRITICAL FIX (2026-08-01): Populate NO-side specific fields from the
        # canonical YES BBO (which may come from ticker fallback).
        if state.best_ask_cents is not None:
            state.best_no_bid_cents = 100 - state.best_ask_cents
        else:
            state.best_no_bid_cents = None
        if state.best_bid_cents is not None:
            state.best_no_ask_cents = 100 - state.best_bid_cents
        else:
            state.best_no_ask_cents = None

        # Crossed/locked detection.  Locked (bid == ask) is allowed; a strict
        # cross (bid > ask) indicates a corrupt or split-tape book.  We no
        # longer use an unbounded inversion counter that can spiral to a
        # permanent CIRCUIT_BREAKER when transient one-sided deltas arrive.
        book_inverted = False
        if (
            state.best_bid_cents is not None
            and state.best_ask_cents is not None
            and state.best_bid_cents > state.best_ask_cents
        ):
            book_inverted = True
            cross_cents = state.best_bid_cents - state.best_ask_cents
            logger.error(
                "[MARKET-STATE-QUOTE-INVALID] ticker=%s bid=%dc ask=%dc cross=%dc - "
                "crossed book. Marking non-executable, data_quality=SUSPECT, "
                "transition=RESYNC_REQUIRED and scheduling REST/WS resync.",
                ticker,
                state.best_bid_cents,
                state.best_ask_cents,
                cross_cents,
            )
            state.executable = False
            state.data_quality = "SUSPECT"
            state.book_consistency = "INVERTED"
            state.transition = "RESYNC_REQUIRED"

            quarantined = self._record_invariant_violation(ticker, "crossed_book")
            if quarantined:
                state.book_initialized = False
                state.data_quality = "INVALID"
                state.transition = "CIRCUIT_BREAKER"
                state.invalidation_cause = "CIRCUIT_BREAKER"
                state.recovery_required_source = "FULL_SNAPSHOT"
                state.executable = False
                self._set_snapshot_complete(ticker, False, "crossed_book_quarantine")
                logger.critical(
                    "[MARKET-STATE-QUOTE-SUSPEND] ticker=%s quarantined - "
                    "circuit-breaker. A clean snapshot or contiguous clean delta "
                    "sequence is required before resuming.",
                    ticker,
                )

            self._schedule_duality_resync(ticker)

        # Store mid/spread as whole cents. Recompute from a valid BBO only when
        # the book is not strictly crossed.  Locked or quote-fallback books are
        # allowed for pricing.
        if not book_inverted and state.best_bid_cents is not None and state.best_ask_cents is not None:
            state.mid_cents = int(round((state.best_bid_cents + state.best_ask_cents) / 2.0))
            state.spread_cents = state.best_ask_cents - state.best_bid_cents
        else:
            state.mid_cents = None
            state.spread_cents = None

        # Update last good book tracking (for audit - tracks last known good state)
        from datetime import datetime, timezone
        if not book_inverted and state.best_bid_cents is not None and state.best_ask_cents is not None:
            # Only update last good book if we have valid bid/ask
            state.last_good_bid_cents = state.best_bid_cents
            state.last_good_ask_cents = state.best_ask_cents
            state.last_good_mid_cents = state.mid_cents
            state.last_good_book_ts = datetime.now(timezone.utc)
            state.last_update = datetime.now(timezone.utc)

        # Set executable flag: True only when we have live bid/ask data and the
        # book is not strictly crossed.
        state.executable = (
            state.best_bid_cents is not None
            and state.best_ask_cents is not None
            and not book_inverted
        )

        # CRITICAL FIX (2026-07-26): Books that violate YES/NO duality are corrupt
        # (stale window, missing snapshot, or one-sided ladder). Never mark them
        # executable - downstream pricing would produce non-marketable orders.
        if duality_violation:
            state.executable = False
            # Do not downgrade an already-INVALID book to SUSPECT.
            if state.data_quality != "INVALID":
                state.data_quality = "SUSPECT"
                state.book_consistency = "SUSPECT"
                state.transition = "RESYNC_REQUIRED"

        # CRITICAL: Detect (0,100) anomaly - indicates no real liquidity
        # This pattern occurs when orderbook has no executable resting orders
        # or parsing/rounding anomaly resulted in default values
        if state.best_bid_cents == 0 and state.best_ask_cents == 100:
            logger.warning(
                "[MARKET-STATE-ANOMALY] %s has (bid=0, ask=100) pattern - no real liquidity detected. "
                "This indicates either empty orderbook or parsing/rounding anomaly. Marking as non-liquid.",
                ticker
            )
            state.executable = False  # Override executable flag for (0,100) anomaly

        # Calculate depth.  If the orderbook channel is one-sided but the ticker
        # quote gave us a valid mid, use the quote mid for the depth window.
        if mid is None and state.mid_cents is not None:
            mid = state.mid_cents

        top_of_book_size = (
            (best_bid[1] if best_bid else 0)
            + (best_ask[1] if best_ask else 0)
        )

        # Initialize depth variables
        yes_depth = 0
        no_depth = 0
        depth_10c = 0

        if mid is not None:
            lo = int(mid) - _DEPTH_WINDOW_CENTS
            hi = int(mid) + _DEPTH_WINDOW_CENTS
            yes_depth = sum(sz for p, sz in ob.yes_levels.items() if lo <= p <= hi)
            # CRITICAL FIX: NO depth calculation - convert NO price range to YES-equivalent range
            # NO prices should be converted to YES-equivalent: yes_equiv = 100 - no_price
            # So for NO price range, we need: lo <= 100 - no_price <= hi
            # Which means: 100 - hi <= no_price <= 100 - lo
            no_lo = 100 - hi
            no_hi = 100 - lo
            no_depth = sum(sz for p, sz in ob.no_levels.items() if no_lo <= p <= no_hi)
            depth_10c = yes_depth + no_depth

        state.top_of_book_size = top_of_book_size
        state.depth_10c = depth_10c
        state.depth_10c_yes = yes_depth
        state.depth_10c_no = no_depth

        # AUDIT: Populate new liquidity audit fields
        state.last_update_ts = time.monotonic()
        state.has_bid = state.best_bid_cents is not None
        state.has_ask = state.best_ask_cents is not None
        # CRITICAL FIX (2026-08-01): Populate NO-side liquidity flags
        state.has_no_bid = state.best_no_bid_cents is not None
        state.has_no_ask = state.best_no_ask_cents is not None
        # YES best bid and YES best ask are the two top levels of the unified order
        # book.  In a binary market each YES level is also a NO level at (100 - p),
        # so these sizes are reused for the opposite-side executable accessors.
        # Use the quote-override price if present, otherwise the raw orderbook BBO.
        if state.best_bid_cents is not None:
            new_depth_yes = ob.yes_levels.get(state.best_bid_cents, 0)
        else:
            new_depth_yes = best_bid[1] if best_bid else 0
        if state.best_ask_cents is not None:
            # YES ask = 100 - NO bid.  Look up the NO bid level that yields this ask.
            new_depth_no = ob.no_levels.get(100 - state.best_ask_cents, 0)
        else:
            new_depth_no = best_ask[1] if best_ask else 0

        # Depth anomaly detection
        prev_depth_yes = state.min_depth_yes if hasattr(state, 'min_depth_yes') else None
        prev_depth_no = state.min_depth_no if hasattr(state, 'min_depth_no') else None

        state.min_depth_yes = new_depth_yes
        state.min_depth_no = new_depth_no

        # Log depth anomalies (order-of-magnitude changes)
        # Reduce log level to DEBUG - these are normal market microstructure events during active trading
        if prev_depth_yes is not None and prev_depth_yes > 0 and new_depth_yes < prev_depth_yes / 10:
            logger.debug(
                "[DEPTH-ANOMALY] ticker=%s YES depth drop %d -> %d",
                ticker,
                prev_depth_yes,
                new_depth_yes,
            )
        if prev_depth_yes is not None and new_depth_yes > prev_depth_yes * 10:
            logger.debug(
                "[DEPTH-ANOMALY] ticker=%s YES depth spike %d -> %d",
                ticker,
                prev_depth_yes,
                new_depth_yes,
            )
        if prev_depth_no is not None and prev_depth_no > 0 and new_depth_no < prev_depth_no / 10:
            logger.debug(
                "[DEPTH-ANOMALY] ticker=%s NO depth drop %d -> %d",
                ticker,
                prev_depth_no,
                new_depth_no,
            )
        if prev_depth_no is not None and new_depth_no > prev_depth_no * 10:
            logger.debug(
                "[DEPTH-ANOMALY] ticker=%s NO depth spike %d -> %d",
                ticker,
                prev_depth_no,
                new_depth_no,
            )

        # Classify liquidity status
        if not state.has_bid and not state.has_ask:
            state.liquidity_status = LiquidityStatus.MISSING
        elif state.has_bid and not state.has_ask:
            state.liquidity_status = LiquidityStatus.ONE_SIDED
        elif state.has_ask and not state.has_bid:
            state.liquidity_status = LiquidityStatus.ONE_SIDED
        else:
            # Two-sided book, check depth
            if depth_10c < 5:  # Minimum depth threshold
                state.liquidity_status = LiquidityStatus.DEPTH_TOO_LOW
            else:
                state.liquidity_status = LiquidityStatus.OK

        # Track liquidity metrics per asset
        underlying, _ = _parse_market_ticker(ticker)
        if underlying:
            self._liquidity_samples[underlying] = self._liquidity_samples.get(underlying, 0) + 1
            if state.liquidity_status == LiquidityStatus.OK:
                self._liquidity_ok_samples[underlying] = self._liquidity_ok_samples.get(underlying, 0) + 1

            # Update Prometheus gauge
            if liquidity_ok_pct is not None:
                total_samples = self._liquidity_samples[underlying]
                ok_samples = self._liquidity_ok_samples.get(underlying, 0)
                ok_pct = (ok_samples / total_samples * 100) if total_samples > 0 else 0.0
                liquidity_ok_pct.labels(asset=underlying).set(ok_pct)

        # CRITICAL FIX (2026-08-23): Never leave a good book with an UNKNOWN source.
        # Some callers (e.g., ws_subscribe_bootstrap) used an unmapped `via` and
        # therefore set source=UNKNOWN, which fail-closed execution gates rejected.
        if state.data_source == "UNKNOWN" and ob.initialized:
            if via == "bridge_queue":
                state.data_source = "WS_ORDERBOOK_DELTA_LIVE"
            elif via in ("rest_bootstrap", "ws_fallback", "subscribe_fallback", "rest_polling", "ws_subscribe_bootstrap"):
                state.data_source = "REST_FULL_ORDERBOOK"
            elif via == "quote_fallback":
                state.data_source = "WS_QUOTE"
            elif via in ("manual", "test"):
                state.data_source = "WS_CLEAN_SNAPSHOT"
            else:
                state.data_source = "BOOTSTRAP_VALID_BUT_UNCONFIRMED"
            logger.debug(
                "[BOOK-SOURCE-FALLBACK] ticker=%s via=%s source set to %s",
                ticker, via, state.data_source,
            )

        # CRITICAL FIX (2026-08-23): An initialized but empty orderbook is a valid
        # bootstrap for a newly opened contract, but it is not yet usable.  Keep it
        # SUSPECT and non-executable until a contiguous delta populates at least one
        # side.  Quote fallbacks must not make an empty book appear executable.
        if ob.initialized and not ob.yes_levels and not ob.no_levels:
            state.executable = False
            state.live_sequence_confirmed = False
            if state.data_quality != "INVALID":
                state.data_quality = "SUSPECT"
                state.book_consistency = "SUSPECT"
                state.transition = "BOOTSTRAP_EMPTY"
            state.best_bid_cents = None
            state.best_ask_cents = None
            state.best_no_bid_cents = None
            state.best_no_ask_cents = None
            state.mid_cents = None
            state.spread_cents = None
            state.has_bid = False
            state.has_ask = False
            state.has_no_bid = False
            state.has_no_ask = False
            state.liquidity_status = LiquidityStatus.MISSING

        # AUDIT: Update per-ticker snapshot counters
        self._snapshots_applied_total[ticker] = self._snapshots_applied_total.get(ticker, 0) + 1
        self._last_snapshot_ts[ticker] = state.last_update_ts

        # AUDIT: Log STATE-AFTER-WRITE with new liquidity audit fields
        logger.debug(
            "[STATE-AFTER-WRITE] ticker=%s bid=%s ask=%s initialized=%s executable=%s "
            "update_ts=%.3f has_bid=%s has_ask=%s depth_yes=%s depth_no=%s liquidity_status=%s "
            "snapshots_total=%s",
            ticker,
            state.best_bid_cents,
            state.best_ask_cents,
            state.book_initialized,
            state.executable,
            state.last_update_ts,
            state.has_bid,
            state.has_ask,
            state.min_depth_yes,
            state.min_depth_no,
            state.liquidity_status.value if hasattr(state, 'liquidity_status') else "N/A",
            self._snapshots_applied_total.get(ticker, 0),
        )

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_or_create_unified(self, ticker: str) -> UnifiedMarketState:
        """Return the ``UnifiedMarketState`` for *ticker*, creating it if absent.

        Must be called with ``self._lock`` held.
        """
        if ticker not in self._unified:
            self._unified[ticker] = UnifiedMarketState(ticker=ticker)
        return self._unified[ticker]

    def _sync_unified_book(self, ticker: str, state: KalshiMarketState) -> None:
        """Rebuild the book snapshot in ``UnifiedMarketState`` from *state* and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)

        # Build typed OrderbookSnapshot from the flat KalshiMarketState fields.
        # D-H2: require BOTH sides to be non-empty before assembling a snapshot.
        # A one-sided book produces spread_cents=None, mid_cents=None, and
        # implied_prob=None — all None — which confuses downstream consumers.
        yes_bids_raw = state.yes_bids or []
        no_bids_raw = state.no_bids or []

        if not yes_bids_raw or not no_bids_raw:
            # One-sided or empty book — do not assemble a snapshot.
            # Leave u.book as-is (None on first update; keep last valid book
            # until a two-sided book arrives so stale-book detection still fires).
            u.book = None
            recompute_derived(u)
            return

        def _to_levels(raw: list) -> tuple:
            levels = []
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    levels.append(OrderbookLevel(price_cents=int(item[0]), size=int(item[1])))
                elif isinstance(item, dict):
                    levels.append(
                        OrderbookLevel(
                            price_cents=int(item.get("price", item.get("price_cents", 0))),
                            size=int(item.get("size", item.get("quantity", 0))),
                        )
                    )
            return tuple(levels)

        # CRITICAL FIX (2026-08-02): Preserve upstream timestamp instead of discarding it
        state_ts = state.last_book_update_ts if hasattr(state, 'last_book_update_ts') else None
        # CRITICAL FIX (2026-08-02): Ensure timestamp is never None or 0.0 - use current time as fallback
        # This prevents book_age_s from returning infinity and causing order rejections
        if state_ts is None or state_ts == 0.0:
            book_ts = time.time()
            logger.debug(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} Using current time as timestamp: state.last_book_update_ts={state_ts} -> book_ts={book_ts}")
        else:
            book_ts = state_ts

        book = OrderbookSnapshot(
            ticker=ticker,
            yes_bids=_to_levels(yes_bids_raw),
            no_bids=_to_levels(no_bids_raw),
            ts=book_ts,
        )
        u.book = book
        u.book_updated_ts = book_ts
        logger.info(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} PRESERVED timestamp: state.last_book_update_ts={state_ts} u.book_updated_ts={u.book_updated_ts}")
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        recompute_derived(u)

    def _sync_unified_rest(self, ticker: str, state: KalshiMarketState) -> None:
        """Propagate REST-owned fields into ``UnifiedMarketState`` and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        u.rest_updated_ts = time.time()
        recompute_derived(u)


# ── Helpers ────────────────────────────────────────────────────────────────


def _recompute_seconds_to_expiry(state: KalshiMarketState) -> None:
    """Recompute ``state.seconds_to_expiry`` in-place from expiry ISO strings.

    STAGE 1 FIX: Use authoritative normalization function for 15m crypto contracts.
    This enforces symmetric treatment across BTC/ETH/SOL/XRP/DOGE.
    For non-15m contracts, use original fail-fast logic (legacy path).
    """
    # Check if this is a 15m crypto contract
    is_15m_crypto = any(
        state.ticker.startswith(prefix) and "15M" in state.ticker.upper()
        for prefix in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]
    )

    if is_15m_crypto:
        # Use authoritative normalization function for 15m crypto contracts
        # This is the SINGLE SOURCE OF TRUTH for expiry metadata
        try:
            from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract
            normalized = normalize_kalshi_contract(
                ticker=state.ticker,
                expiration_time=state.expiration_time,
                expected_expiration_time=state.expected_expiration_time,
                end_date=None,  # Not available in KalshiMarketState
                close_time=None,  # Not available in KalshiMarketState
                now=datetime.now(timezone.utc)
            )
            state.seconds_to_expiry = normalized.seconds_to_expiry
            logger.debug(
                "[STATE-NORMALIZE] ticker=%s normalized_status=%s seconds_to_expiry=%.1f reason=%s",
                state.ticker, normalized.status, normalized.seconds_to_expiry, normalized.status_reason
            )
        except Exception as exc:
            # Fallback to original logic if normalization fails (should not happen)
            logger.warning(
                "[STATE-NORMALIZE-FAIL] ticker=%s normalization failed, using fallback: %s",
                state.ticker, exc
            )
            _recompute_seconds_to_expiry_fallback(state)

        # Never report negative time-to-expiry; downstream logic treats this as a live value.
        if state.seconds_to_expiry is not None and state.seconds_to_expiry < 0:
            state.seconds_to_expiry = 0.0
    else:
        # Non-15m: use original fail-fast logic (legacy path)
        # TODO: Eventually migrate these to use normalization function as well
        _recompute_seconds_to_expiry_fallback(state)
        # Ensure past expiry is floored at 0.0 for non-15m fallback too.
        if state.seconds_to_expiry is not None and state.seconds_to_expiry < 0:
            state.seconds_to_expiry = 0.0


def _recompute_seconds_to_expiry_fallback(state: KalshiMarketState) -> None:
    """Fallback expiry computation for non-15m contracts.

    P0 FIX: Fail-fast on missing or invalid expiry.
    If expiry cannot be computed, set seconds_to_expiry to 0 (already expired)
    and log a warning to prevent downstream processing of invalid markets.
    """
    expiry_str = state.expected_expiration_time or state.expiration_time
    if not expiry_str:
        # P0 FIX: Set to 0 (already expired) instead of None to prevent downstream issues
        state.seconds_to_expiry = 0.0
        logger.warning(
            "[EXPIRY-FAIL-FAST] ticker=%s has no expiry string (expected_expiration_time=%s, expiration_time=%s) → treating as expired (seconds_to_expiry=0.0)",
            state.ticker, state.expected_expiration_time, state.expiration_time
        )
        return
    try:
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        # If Kalshi returns a naive datetime (no tzinfo), assume UTC
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        state.seconds_to_expiry = (expiry_dt - now_dt).total_seconds()
    except (ValueError, TypeError) as exc:
        # P0 FIX: Set to 0 (already expired) instead of None to prevent downstream issues
        state.seconds_to_expiry = 0.0
        logger.warning(
            "[EXPIRY-FAIL-FAST] ticker=%s has invalid expiry string %r (error: %s) → treating as expired (seconds_to_expiry=0.0)",
            state.ticker, expiry_str, exc
        )


# ── Singleton ──────────────────────────────────────────────────────────────

_store: Optional[KalshiMarketStateStore] = None
_store_lock = threading.Lock()
# CRITICAL FIX (2026-08-01): Remove lazy async lock initialization to prevent race conditions
# The previous lazy initialization could create locks in the wrong event loop during
# concurrent access. We now eagerly initialize locks during store creation.
_store_lock_async: Optional[asyncio.Lock] = None


def _ensure_store_lock_async() -> asyncio.Lock:
    """Get the async store lock (eagerly initialized)."""
    global _store_lock_async
    if _store_lock_async is None:
        # This should only happen if get_kalshi_market_state_store() hasn't been called yet
        # Create lock in current event loop as fallback
        import asyncio
        _store_lock_async = asyncio.Lock()
    return _store_lock_async


def get_kalshi_market_state_store() -> KalshiMarketStateStore:
    """Return the process-wide ``KalshiMarketStateStore`` singleton.

    CRITICAL FIX: Thread-safe singleton with double-checked locking.
    The module-level _store variable is shared across the entire process,
    so all calls from any thread/event loop will return the same instance.

    CRITICAL FIX (2026-08-01): Eagerly initialize async lock during store creation
    to prevent race conditions where locks are created in the wrong event loop.
    """
    import threading
    global _store, _store_lock_async
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: checking if _store is None thread=%s",
               threading.current_thread().name)
    if _store is None:
        with _store_lock:
            if _store is None:
                logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: _store is None, creating new instance thread=%s",
                          threading.current_thread().name)
                logger.info("[MARKET-STATE] store init starting")
                try:
                    _store = KalshiMarketStateStore()
                    logger.info("[MARKET-STATE] store init completed id=%d thread=%s",
                              id(_store), threading.current_thread().name)
                    # CRITICAL FIX (2026-08-01): Eagerly initialize async lock in current event loop
                    # This prevents race conditions where locks are created in wrong event loop
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        _store_lock_async = asyncio.Lock()
                        logger.debug("[MARKET-STATE] Async lock eagerly initialized in event loop")
                    except RuntimeError:
                        # No event loop running yet - will be initialized on first async call
                        logger.debug("[MARKET-STATE] No event loop running, async lock will be initialized on first async call")
                        _store_lock_async = None
                except Exception as e:
                    logger.error(f"[MARKET-STATE] store init failed: {e}")
                    raise RuntimeError(f"Market state store initialization failed: {e}")
            else:
                logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: another thread created store_id=%s", id(_store))
    else:
        logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: returning existing store_id=%s thread=%s",
                   id(_store), threading.current_thread().name)
    logger.debug("[BOOT-TRACE] get_kalshi_market_state_store: returning _store")
    return _store
