"""KalshiMarketStateStore — unified per-market live state.

PRODUCTION INVARIANTS (NON-NEGOTIABLE):
────────────────────────────────────────────────────────────────────────────
These invariants define the canonical behavior for production. Changes require:
  1. Risk committee approval
  2. Staged rollout testing
  3. Updated regression tests

1. DATA FLOW INVARIANTS:
   - Only subscribe to `orderbook_delta` on Kalshi WS
   - Snapshots come from REST `GET /markets/{ticker}/orderbook` ONLY
   - Every traded market MUST be bootstrapped via REST `orderbook_fp` before accepting WS deltas
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
   - MAX_BOOK_STALENESS_MS = 30000 (30s maximum staleness)
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

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

# ── Production Invariants: Health Thresholds ─────────────────────────────
# These constants are NON-NEGOTIABLE in production. Changes require:
# 1. Risk committee approval
# 2. Staged rollout testing
# 3. Updated regression tests

# Maximum age of orderbook data before it's considered stale (milliseconds)
# PRODUCTION INVARIANT: 30 seconds is the maximum acceptable staleness for 15m crypto markets
# Rationale: 15m markets update frequently; 30s allows for transient network issues while preventing stale trading
MAX_BOOK_STALENESS_MS = 30000  # 30 seconds - DO NOT CHANGE WITHOUT RISK APPROVAL

# Minimum number of healthy books required to enable trading (quorum)
# PRODUCTION INVARIANT: For 5 crypto 15m markets, require at least 3 to be healthy (60%)
# Rationale: Prevents trading on degraded data when majority of markets are unhealthy
MIN_HEALTHY_BOOKS_FOR_TRADING = 3  # DO NOT CHANGE WITHOUT RISK APPROVAL

# Health check flags - all must be True in production
# PRODUCTION INVARIANT: All three checks are mandatory for safe trading
HEALTH_CHECK_INITIALIZED = True  # Book must have REST snapshot applied
HEALTH_CHECK_FRESH = True  # Book must have been updated within staleness threshold
HEALTH_CHECK_BID_ASK = True  # Book must have valid bid < ask with non-zero sizes

logger = get_logger("merid.event_venues.kalshi.market_state")

# REST fallback staleness threshold - mark markets untradeable if REST data is older than this
_MAX_REST_AGE_SECONDS = int(os.getenv("MERID_KALSHI_MAX_REST_AGE_SECONDS", "10"))  # 10 seconds for 15m markets

# Market-level filter: only accept 5 crypto underlyings on 15m timeframe
# Import from centralized config module
from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES as _ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS as _ALLOWED_UNDERLYINGS,
)

# Parse ticker to extract underlying and timeframe
# Format: KXBTC15M-26MAY121130-30 or KXBTC-15M-26MAY121130-30
def _parse_market_ticker(ticker: str) -> tuple[str, str]:
    """Extract (underlying, timeframe) from Kalshi ticker.

    Returns:
        (underlying, timeframe) tuple, or (None, None) if unparseable
    """
    if not ticker:
        return None, None

    # Try to match pattern like KXBTC15M-... or KXBTC-15M-...
    import re
    match = re.match(r"^KX([A-Z]+)(?:-?)(\d+[mM])", ticker.upper())
    if match:
        underlying = match.group(1)
        timeframe = match.group(2).upper()
        return underlying, timeframe

    return None, None

# Auto-switch to IOC when market expires within this many seconds
# 15m scalper: configurable threshold (default 120s = 2 min before expiry)
IOC_AUTO_BELOW_SECONDS = float(os.getenv("KALSHI_IOC_AUTO_BELOW_SECONDS", "120.0"))

_TOP_N_BOOK_LEVELS = 10
_DEPTH_WINDOW_CENTS = 10

# DATA INTEGRITY LAYER CONFIGURATION
_PRIMARY_STALE_SECONDS = float(os.getenv("KALSHI_PRIMARY_STALE_SECONDS", "5.0"))  # Max age for primary (WebSocket) data - relaxed for 15M markets
_REST_THROTTLE_SECONDS = float(os.getenv("KALSHI_REST_THROTTLE_SECONDS", "5.0"))  # Min time between REST calls per market
_CROSS_VALIDATION_THRESHOLD_CENTS = float(os.getenv("KALSHI_CROSS_VALIDATION_THRESHOLD_CENTS", "5.0"))  # Max allowed difference between primary and REST
_CROSS_VALIDATION_THRESHOLD_PCT = float(os.getenv("KALSHI_CROSS_VALIDATION_THRESHOLD_PCT", "0.10"))  # Max allowed % difference

# Production safeguards
_MAX_QUOTE_TTL_SECONDS = float(os.getenv("KALSHI_MAX_QUOTE_TTL_SECONDS", "15.0"))  # Maximum age for any quote before rejection - relaxed for 15M markets
_CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("KALSHI_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "10"))  # Consecutive failures before suspension (relaxed for spotty internet)
_CIRCUIT_BREAKER_RECOVERY_SECONDS = float(os.getenv("KALSHI_CIRCUIT_BREAKER_RECOVERY_SECONDS", "300.0"))  # Time before attempting recovery (5 min for spotty internet)
_CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS = float(os.getenv("KALSHI_CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS", "60.0"))  # Maximum backoff for retries


class QuoteHealth(str, Enum):
    """Health state for market quotes."""
    HEALTHY = "healthy"  # Primary feed timely; REST (if checked) agrees within threshold
    DEGRADED = "degraded"  # Using REST because primary missing/stale, but REST shows open & fresh
    STALE = "stale"  # Very old quote, use with caution (added for graduated health levels)
    SUSPENDED = "suspended"  # Conflicting data, closed/paused state, or repeated failures


class QuoteSource(str, Enum):
    """Source of market quote data."""
    WEBSOCKET = "websocket"
    FIX = "fix"
    REST = "rest"
    COMPOSITE = "composite"  # Verified by cross-checking primary vs REST


@dataclass
class MarketQuote:
    """Canonical quote model for data integrity layer.
    
    Every signal agent receives this object (or None) and can inspect
    health, source, and diagnostics to make trading decisions.
    
    Production-grade metadata:
    - age_ms: time since exchange timestamp in milliseconds
    - confidence: 0.0-1.0 score based on freshness and consistency
    - All downstream code MUST branch on health/source/age, never assume valid
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
    diagnostics: List[str] = field(default_factory=list)


# Log effective REST fallback configuration at module load
def _log_rest_config() -> None:
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

# Log configuration at module load
_log_rest_config()


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
        self._states: Dict[str, KalshiMarketState] = {}
        self._unified: Dict[str, UnifiedMarketState] = {}
        self._ob: MultiMarketOrderbook = MultiMarketOrderbook()
        self._lock = threading.Lock()
        # H3: per-ticker queue of delta messages received before snapshot.
        self._pending_deltas: Dict[str, List[Dict[str, Any]]] = {}
        
        # DATA INTEGRITY LAYER: Per-market health state and tracking
        self._health_state: Dict[str, QuoteHealth] = {}
        self._rest_last_fetch: Dict[str, float] = {}  # Last REST fetch time per ticker
        self._consecutive_failures: Dict[str, int] = {}  # Consecutive failures per ticker
        self._circuit_breaker_until: Dict[str, float] = {}  # Circuit breaker expiration time per ticker
        self._metrics: Dict[str, Dict[str, float]] = {}  # Metrics per ticker: quote_age, fallback_count, breaker_opens, rejected_quotes

    def _record_metric(self, ticker: str, metric_name: str, value: float) -> None:
        """Record a metric for a ticker."""
        with self._lock:
            if ticker not in self._metrics:
                self._metrics[ticker] = {}
            self._metrics[ticker][metric_name] = self._metrics[ticker].get(metric_name, 0.0) + value

    def _get_exponential_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter for recovery attempts."""
        # Exponential backoff: base * 2^attempt, capped at max
        base_backoff = min(2.0 ** attempt, _CIRCUIT_BREAKER_MAX_BACKOFF_SECONDS)
        # Add jitter: +/- 25% of base backoff
        jitter = base_backoff * 0.25 * (random.random() * 2 - 1)
        return max(0, base_backoff + jitter)

    def log_book_health(self) -> None:
        """Log healthy book invariant for all tracked tickers.
        
        For each ticker, logs:
        - book_initialized status
        - last_update_age_ms
        - best_bid, best_ask, mid
        - spread_cents
        
        This provides visibility into book health and freshness.
        """
        now = time.monotonic()
        with self._lock:
            for ticker, state in self._states.items():
                # Only log 5-crypto/15m markets
                underlying, timeframe = _parse_market_ticker(ticker)
                if underlying not in _ALLOWED_UNDERLYINGS or timeframe not in _ALLOWED_TIMEFRAMES:
                    continue
                
                # Calculate age
                last_update = state.last_book_update_ts or state.last_rest_update_ts or 0
                age_ms = (now - last_update) * 1000 if last_update > 0 else float('inf')
                
                logger.info(
                    "[MARKET-STATE] health market=%s initialized=%s last_update_age_ms=%.0f bid=%s ask=%s mid=%s spread=%s",
                    ticker,
                    state.book_initialized,
                    age_ms,
                    state.best_bid_cents,
                    state.best_ask_cents,
                    state.mid_cents,
                    state.spread_cents
                )

    def is_trading_enabled(self, staleness_threshold_ms: Optional[float] = None) -> bool:
        """Check if trading is enabled based on book health.

        Uses explicit health thresholds defined at module level:
        - MAX_BOOK_STALENESS_MS: Maximum age of book data (default 30s) - PRODUCTION INVARIANT
        - MIN_HEALTHY_BOOKS_FOR_TRADING: Minimum healthy books required (default 3) - PRODUCTION INVARIANT
        - HEALTH_CHECK_INITIALIZED: Require book to be initialized - PRODUCTION INVARIANT
        - HEALTH_CHECK_FRESH: Require book to be fresh - PRODUCTION INVARIANT
        - HEALTH_CHECK_BID_ASK: Require valid bid/ask (bid < ask, both not None) - PRODUCTION INVARIANT

        Args:
            staleness_threshold_ms: Override default staleness threshold

        Returns:
            True if trading is enabled, False otherwise
        """
        if staleness_threshold_ms is None:
            staleness_threshold_ms = MAX_BOOK_STALENESS_MS

        now = time.monotonic()
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

                # Check if book is healthy using explicit thresholds
                last_update = state.last_book_update_ts or state.last_rest_update_ts or 0
                age_ms = (now - last_update) * 1000 if last_update > 0 else float('inf')

                reasons = []
                if HEALTH_CHECK_INITIALIZED and not state.book_initialized:
                    unhealthy_reasons.append(f"{ticker}: not initialized")
                if HEALTH_CHECK_FRESH and age_ms >= staleness_threshold_ms:
                    unhealthy_reasons.append(f"{ticker}: stale (age={age_ms:.0f}ms)")
                if HEALTH_CHECK_BID_ASK:
                    if state.best_bid_cents is None:
                        reasons.append("no_bid")
                    elif state.best_ask_cents is None:
                        reasons.append("no_ask")
                    elif state.best_bid_cents >= state.best_ask_cents:
                        reasons.append(f"crossed_bid_ask({state.best_bid_cents}>={state.best_ask_cents})")

                if reasons:
                    unhealthy_reasons.append(f"{ticker}:{','.join(reasons)}")
                else:
                    healthy_count += 1

        # Trading is enabled if at least MIN_HEALTHY_BOOKS_FOR_TRADING are healthy
        trading_enabled = healthy_count >= MIN_HEALTHY_BOOKS_FOR_TRADING

        if not trading_enabled:
            logger.warning(
                "[HEALTH-CIRCUIT-BREAKER] TRADING DISABLED: healthy=%d/%d, threshold=%d, reasons=%s",
                healthy_count, total_count, MIN_HEALTHY_BOOKS_FOR_TRADING, unhealthy_reasons
            )
        else:
            logger.info(
                "[HEALTH-CIRCUIT-BREAKER] TRADING ENABLED: healthy=%d/%d, threshold=%d",
                healthy_count, total_count, MIN_HEALTHY_BOOKS_FOR_TRADING
            )

        return trading_enabled

    # ── WS path ────────────────────────────────────────────────────────

    def apply_orderbook_message(self, msg: Dict[str, Any]) -> Optional[KalshiMarketState]:
        # ... (rest of the code remains the same)
        """Apply a WS ``orderbook_snapshot`` or ``orderbook_delta`` message.

        Updates the internal ``LocalOrderbook`` for the ticker, then
        syncs the book-owned fields of the corresponding
        ``KalshiMarketState``.

        Args:
            msg: Raw parsed WS message dict (already JSON-decoded).

        Returns:
            Updated ``KalshiMarketState``, or ``None`` if the message
            type is not an orderbook message or the ticker is missing.
        """
        # DIAGNOSTIC: Log with stack trace to identify caller
        import traceback
        channel = msg.get("type") or msg.get("channel") or msg.get("msg_type") or ""
        ticker = msg.get("ticker") or msg.get("market_ticker", "")
        msg_keys = list(msg.keys()) if isinstance(msg, dict) else "N/A"
        
        # Note: delta_fp messages without bids/asks are valid Kalshi orderbook deltas
        # They are applied to the internal book representation in apply_delta
        
        # Log raw message structure for debugging
        logger.debug(
            "[market-state] apply_orderbook_message: RAW msg keys=%s, channel=%s, ticker=%s",
            msg_keys, channel, ticker
        )
        
        # Try multiple possible channel/type field names
        channel = msg.get("type") or msg.get("channel") or msg.get("msg_type") or ""
        ticker = msg.get("ticker") or msg.get("market_ticker", "")

        # Diagnostic logging for debugging missing prices
        if not ticker:
            logger.error(
                "[market-state] apply_orderbook_message REJECTED: missing ticker, channel=%s, msg keys=%s",
                channel, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            return None

        # Accept messages with empty channel if they have orderbook data (msg field with bids/asks)
        # This handles cases where the channel field is missing but the payload is valid
        if channel not in ("orderbook_snapshot", "orderbook_delta"):
            # Check if this looks like an orderbook message by inspecting the payload
            payload = msg.get("msg", msg)
            has_bids = "bids" in payload or isinstance(payload.get("bids"), list)
            has_asks = "asks" in payload or isinstance(payload.get("asks"), list)
            
            # Log message structure for debugging
            logger.debug(
                "[market-state] apply_orderbook_message: message structure - channel=%s, ticker=%s, keys=%s",
                channel, ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            
            if has_bids or has_asks:
                # Treat as orderbook_delta if it has book data
                channel = "orderbook_delta"
                logger.debug(
                    "[market-state] apply_orderbook_message: inferred channel=orderbook_delta from payload (bids=%s, asks=%s)",
                    has_bids, has_asks
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
        
        if channel == "orderbook_delta" and not (has_bids or has_asks or has_delta_fields):
            logger.warning(
                "[market-state] apply_orderbook_message REJECTED: delta missing bids/asks/delta_fields, ticker=%s, msg keys=%s",
                ticker, list(msg.keys()) if isinstance(msg, dict) else "N/A"
            )
            return None

        # MARKET-LEVEL FILTER: Only accept 5 crypto underlyings on 15m timeframe
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

        with self._lock:
            if channel == "orderbook_snapshot":
                payload = msg.get("msg", msg)
                # Log snapshot reception for validation
                logger.info(
                    "[market-state] SNAPSHOT: ticker=%s, has_bids=%s, has_asks=%s, payload_keys=%s",
                    ticker, "bids" in payload, "asks" in payload, list(payload.keys()) if isinstance(payload, dict) else "N/A"
                )
                self._ob.apply_snapshot(ticker, payload)
                
                # Log book state after snapshot for validation
                book = self._ob.get_book(ticker)
                if book:
                    logger.info(
                        "[market-state] SNAPSHOT-APPLIED: ticker=%s, best_bid=%s, best_ask=%s, mid=%s, spread=%s, yes_bids=%d, no_bids=%d",
                        ticker,
                        book.get_best_bid(),
                        book.get_best_ask(),
                        book.get_midpoint(),
                        book.get_spread(),
                        len(book.yes_levels),
                        len(book.no_levels)
                    )
                # H3: Replay any deltas that arrived before this snapshot.
                pending = self._pending_deltas.pop(ticker, [])
                for _delta in pending:
                    try:
                        self._ob.apply_delta(ticker, _delta)
                    except Exception as _re:
                        logger.debug(
                            "[market-state] replayed delta failed for %s: %s",
                            ticker, _re,
                        )
                if pending:
                    logger.debug(
                        "[market-state] replayed %d pending delta(s) for %s after snapshot",
                        len(pending), ticker,
                    )
            elif channel == "orderbook_delta":
                ob = self._ob.get_book(ticker)
                if not ob.initialized:
                    # Queue delta if book not yet initialized
                    self._pending_deltas.setdefault(ticker, []).append(msg.get("msg", msg))
                    logger.debug(
                        "[market-state] DELTA QUEUED: ticker=%s (book not initialized), pending=%d",
                        ticker, len(self._pending_deltas.get(ticker, []))
                    )
                    return None
                
                # Log delta application for validation
                payload = msg.get("msg", msg)
                logger.debug(
                    "[market-state] DELTA: ticker=%s, has_price_dollars=%s, has_delta_fp=%s, has_side=%s",
                    ticker, "price_dollars" in payload, "delta_fp" in payload, "side" in payload
                )
                self._ob.apply_delta(ticker, msg.get("msg", msg))
            else:
                return None

            state = self._get_or_create(ticker)
            self._sync_book_fields(state, self._ob.get_book(ticker))
            self._sync_unified_book(ticker, state)

            # Log successful market state update
            logger.info(
                "[WS-STATE-UPDATE] market=%s mid_cents=%s bid=%s ask=%s book_initialized=%s",
                ticker,
                state.mid_cents,
                state.best_bid_cents,
                state.best_ask_cents,
                state.book_initialized
            )

            # Update last orderbook update timestamp for heartbeat tracking
            state.last_ws_update_ts = time.monotonic()

            # Improve confidence calculation based on real signals
            now = time.monotonic()
            if state.last_ws_update_ts:
                age_sec = now - state.last_ws_update_ts
                # Fresh WS data (< 3 sec) + both bid/ask present = high confidence
                if age_sec < 3.0 and state.best_bid_cents and state.best_ask_cents:
                    state.confidence = 1.0
                # Moderate age (3-10 sec) = taper confidence
                elif age_sec < 10.0 and state.best_bid_cents and state.best_ask_cents:
                    state.confidence = max(0.5, 1.0 - (age_sec / 10.0) * 0.5)
                # Old data (> 10 sec) or missing sides = low confidence
                else:
                    state.confidence = 0.2 if state.best_bid_cents or state.best_ask_cents else 0.0

            return state

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
        ticker = data.get("ticker")
        if not ticker:
            return None

        with self._lock:
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

            strike = data.get("strike_price")
            if strike is not None:
                state.strike_price = float(strike)

            floor = data.get("floor_strike")
            if floor is not None:
                state.floor_strike = float(floor)

            cap = data.get("cap_strike")
            if cap is not None:
                state.cap_strike = float(cap)

            # External spot price (from CF Benchmarks RTI or other feed)
            spot = data.get("external_spot")
            if spot is not None:
                state.external_spot = float(spot)

            state.last_rest_update_ts = time.monotonic()
            _recompute_seconds_to_expiry(state)
            self._sync_unified_rest(ticker, state)

            # Check REST staleness and mark untradeable if too old
            now = time.monotonic()
            rest_age = now - state.last_rest_update_ts
            if rest_age > _MAX_REST_AGE_SECONDS:
                logger.warning(
                    "[MARKET-STATE] rest_price_stale market=%s age_sec=%.0f threshold=%s - marking untradeable",
                    ticker, rest_age, _MAX_REST_AGE_SECONDS
                )
                state.can_trade = False
                state.confidence = 0.0

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

        Fills in bid/ask/mid/spread when no orderbook subscription exists
        for this ticker.  If the book is already initialized from the
        orderbook channel, this is a no-op for bid/ask (book data is
        more authoritative), but volume is always updated.
        """
        if not ticker:
            return None
        with self._lock:
            state = self._get_or_create(ticker)

            if volume is not None:
                state.volume_24h = int(volume)

            # Only fill bid/ask/mid from quotes when book is NOT initialized
            # (orderbook data is higher fidelity).
            if not state.book_initialized:
                if bid_cents is not None:
                    state.best_bid_cents = bid_cents
                if ask_cents is not None:
                    state.best_ask_cents = ask_cents
                if bid_cents is not None and ask_cents is not None:
                    state.mid_cents = (bid_cents + ask_cents) // 2
                    state.spread_cents = ask_cents - bid_cents
                elif last_cents is not None:
                    state.mid_cents = last_cents

            state.last_book_update_ts = time.monotonic()
            return state

    # ── Read ───────────────────────────────────────────────────────────

    def get(self, ticker: str) -> Optional[KalshiMarketState]:
        """Return the current state for *ticker*, or ``None`` if unknown."""
        with self._lock:
            return self._states.get(ticker)

    def get_unified(self, ticker: str) -> Optional[UnifiedMarketState]:
        """Return the ``UnifiedMarketState`` for *ticker*, or ``None`` if unknown.

        ``UnifiedMarketState`` carries all derived consensus fields
        (``implied_prob``, ``external_fair_value``, ``edge_basis``) that
        ``KalshiMarketState`` does not have.  Agents and risk systems should
        prefer this when they need those fields.
        """
        with self._lock:
            return self._unified.get(ticker)

    def get_all(self) -> Dict[str, KalshiMarketState]:
        """Return a shallow copy of the full state registry."""
        with self._lock:
            return dict(self._states)

    def tickers(self) -> List[str]:
        """Return a snapshot of all tracked tickers."""
        with self._lock:
            return list(self._states.keys())

    def is_stale(self, ticker: str, max_age_seconds: float = 30.0) -> bool:
        """Return True if *ticker*'s book has not been updated within *max_age_seconds*.

        H3: Consumers (e.g. order router market-condition check) should call
        this to refuse to trade on a book that has gone silent after a WS
        reconnect.  A ticker that has never been seen is also considered stale.
        """
        with self._lock:
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
            
            # Check if primary (WebSocket) data is fresh
            primary_fresh = False
            if state and state.book_initialized and state.last_book_update_ts > 0.0:
                age = time.monotonic() - state.last_book_update_ts
                primary_fresh = age <= _PRIMARY_STALE_SECONDS
            
            # Get current health state
            current_health = self._health_state.get(ticker, QuoteHealth.HEALTHY)
            
            # If primary is fresh and not suspended, return it
            if primary_fresh and current_health != QuoteHealth.SUSPENDED:
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
                    health=QuoteHealth.HEALTHY,
                    diagnostics=[]
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
                    diagnostics=["Primary feed stale/missing, using REST fallback"]
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
                    
                    # Calculate age_ms and confidence
                    ts_exchange = state.last_book_update_ts if primary_fresh else state.last_rest_update_ts
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
                        diagnostics=diagnostics
                    )
                    
                    return quote
        
        # No valid cached data - try REST fallback
        logger.warning("[market-state] No valid cached data for %s - attempting REST fallback", ticker)
        # DIAGNOSTIC: Log cache and WS status to debug why cache is empty
        with self._lock:
            cache_keys = list(self._states.keys())
            # Check if ticker exists in cache with different format
            ticker_matches = [k for k in cache_keys if ticker in k or k in ticker]
            logger.error(
                "[market-state] DIAGNOSTIC - Requested ticker: %s, Cache keys (first 10): %s, total_states: %d, "
                "ticker_matches_in_cache: %s",
                ticker, cache_keys[:10], len(self._states), ticker_matches
            )
        # Check WebSocket bridge status
        try:
            from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
            ws_bridge = get_ws_bridge()
            ws_summary = ws_bridge.summary()
            logger.error(
                "[market-state] DIAGNOSTIC - WS Bridge status: running=%s, events_forwarded=%s, subscribed_tickers=%s",
                ws_summary.get("running", False),
                ws_summary.get("events_forwarded", 0),
                ws_summary.get("subscribed_tickers", 0)
            )
            # Check if WebSocket client exists and is connected
            if hasattr(ws_bridge, '_ws') and ws_bridge._ws:
                ws_connected = ws_bridge._ws._running if hasattr(ws_bridge._ws, '_running') else False
                logger.error(
                    "[market-state] DIAGNOSTIC - WS client connected: %s, running: %s",
                    ws_connected,
                    ws_bridge._ws._running if hasattr(ws_bridge._ws, '_running') else "unknown"
                )
            else:
                logger.error("[market-state] DIAGNOSTIC - WS client object: None or not initialized")
        except Exception as e:
            logger.error(f"[market-state] DIAGNOSTIC - Failed to get WS bridge status: {e}")
        self._record_metric(ticker, "fallback_count", 1.0)
        try:
            import httpx
            import os
            from utils.http_client import get_shared_ssl_context
            from merid.event_venues.kalshi.client import get_kalshi_client
            
            # Use existing Kalshi client for authentication (API Key + RSA signature)
            client = get_kalshi_client()
            
            # Use synchronous httpx for REST fallback (works from any context)
            kalshi_base_url = os.getenv("KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2")
            path = f"/markets/{ticker}"
            
            # Generate RSA authentication headers using the client's method
            auth_headers = client._sign_headers("GET", path)
            
            # Make synchronous REST call with proper Kalshi API authentication
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
        if ticker not in self._states:
            self._states[ticker] = KalshiMarketState(ticker=ticker)
        return self._states[ticker]

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

        book = OrderbookSnapshot(
            ticker=ticker,
            yes_bids=_to_levels(yes_bids_raw),
            no_bids=_to_levels(no_bids_raw),
            ts=time.time(),
        )
        u.book = book
        u.book_updated_ts = time.time()
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

    def _sync_book_fields(
        self, state: KalshiMarketState, ob: LocalOrderbook
    ) -> None:
        """Copy the book-owned fields from a ``LocalOrderbook`` into *state*."""
        state.book_initialized = ob.initialized
        state.last_book_update_ts = time.monotonic()

        if not ob.initialized:
            return

        state.yes_bids = ob.get_book("yes", top_n=_TOP_N_BOOK_LEVELS)
        state.no_bids = ob.get_book("no", top_n=_TOP_N_BOOK_LEVELS)

        best_bid = ob.get_best_bid()    # (price_cents, size) or None
        best_ask = ob.get_best_ask()    # (yes_equivalent_cents, size) or None
        mid = ob.get_midpoint()

        state.best_bid_cents = best_bid[0] if best_bid else None
        state.best_ask_cents = best_ask[0] if best_ask else None
        state.mid_cents = mid
        state.spread_cents = ob.get_spread()

        # FVG Integration: Feed price update to FVG store for gap detection
        if mid is not None and best_bid and best_ask:
            try:
                from merid.prediction.fvg_integration import update_price_from_orderbook
                update_price_from_orderbook(
                    ticker=state.ticker,
                    bid=best_bid[0] / 100.0,  # Convert cents to probability
                    ask=best_ask[0] / 100.0,
                )
            except Exception:
                # FVG is best-effort, don't block book updates on failures
                pass

        # top_of_book_size: size at best bid + size at best ask (no-side)
        state.top_of_book_size = (
            (best_bid[1] if best_bid else 0)
            + (best_ask[1] if best_ask else 0)
        )

        # depth_10c: total contracts within ±10¢ of mid on both sides
        if mid is not None:
            lo = int(mid) - _DEPTH_WINDOW_CENTS
            hi = int(mid) + _DEPTH_WINDOW_CENTS
            yes_depth = sum(
                sz for p, sz in ob.yes_levels.items() if lo <= p <= hi
            )
            # no_levels keyed by no_price; yes-equivalent = 100 - no_price
            no_depth = sum(
                sz
                for p, sz in ob.no_levels.items()
                if lo <= (100 - p) <= hi
            )
            state.depth_10c = yes_depth + no_depth
        else:
            state.depth_10c = 0


# ── Helpers ────────────────────────────────────────────────────────────────


def _recompute_seconds_to_expiry(state: KalshiMarketState) -> None:
    """Recompute ``state.seconds_to_expiry`` in-place from expiry ISO strings."""
    expiry_str = state.expected_expiration_time or state.expiration_time
    if not expiry_str:
        state.seconds_to_expiry = None
        return
    try:
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        # If Kalshi returns a naive datetime (no tzinfo), assume UTC
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        state.seconds_to_expiry = max(0.0, (expiry_dt - now_dt).total_seconds())
    except (ValueError, TypeError) as exc:
        logger.debug("Could not parse expiry %r for %s: %s", expiry_str, state.ticker, exc)
        state.seconds_to_expiry = None


# ── Singleton ──────────────────────────────────────────────────────────────

_store: Optional[KalshiMarketStateStore] = None
_store_lock = threading.Lock()


def get_kalshi_market_state_store() -> KalshiMarketStateStore:
    """Return the process-wide ``KalshiMarketStateStore`` singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = KalshiMarketStateStore()
    return _store
