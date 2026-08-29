"""Kalshi models - Data transfer objects for Kalshi API."""

from __future__ import annotations

import time
from utils.logger import get_logger
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

logger = get_logger("merid.event_venues.kalshi.models")


@dataclass
class KalshiOutcome:
    """Represents a Kalshi market outcome (Yes/No)."""
    outcome_id: str  # "yes" or "no"
    name: str
    price: Decimal  # Price in cents (0-100)
    probability: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None


@dataclass
class KalshiMarket:
    """Represents a Kalshi event market."""
    ticker: str  # Kalshi's unique ticker (e.g., "FED-25DEC-T3.00")
    event_ticker: str  # Parent event ticker
    title: str
    description: str
    outcomes: List[KalshiOutcome]
    category: Optional[str] = None
    series_ticker: Optional[str] = None
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    expiration_time: Optional[datetime] = None
    settlement_time: Optional[datetime] = None
    active: bool = True
    status: str = "active"  # active, paused, closed, settled
    volume: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None  # 24-hour rolling volume from REST API
    open_interest: Optional[Decimal] = None
    liquidity: Optional[Decimal] = None
    rules_primary: Optional[str] = None
    rules_secondary: Optional[str] = None
    resolution_source: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    can_close_position: bool = True
    created_at: Optional[datetime] = None
    strike_price: Optional[float] = None
    floor_strike: Optional[float] = None
    cap_strike: Optional[float] = None
    custom_strike: Optional[Dict[str, Any]] = None
    exchange_index: Optional[int] = None  # Kalshi exchange shard index (e.g. 2 for crypto 15m)

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class KalshiOrder:
    """Represents a Kalshi order."""
    order_id: str
    ticker: str
    action: str  # "buy" or "sell"
    side: str  # "yes" or "no"
    order_type: str  # "limit" or "market"
    price: Optional[Decimal]  # Price in cents (for limit orders)
    count: int  # Number of contracts
    filled_count: int = 0
    remaining_count: Optional[int] = None
    status: str = "pending"  # pending, executed, cancelled, rejected
    client_order_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class KalshiPosition:
    """Represents a Kalshi position."""
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price: Decimal  # Average entry price in cents
    total_cost: Decimal
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    created_at: Optional[datetime] = None


@dataclass
class KalshiTrade:
    """Represents a Kalshi trade/fill."""
    trade_id: str
    ticker: str
    order_id: str
    side: str  # "yes" or "no"
    count: int
    price: Decimal  # Fill price in cents
    fee: Decimal
    timestamp: datetime


@dataclass
class KalshiOrderBook:
    """Represents Kalshi order book (level 1)."""
    ticker: str
    yes_bid: Optional[Decimal] = None  # Best bid for Yes
    yes_ask: Optional[Decimal] = None  # Best ask for Yes
    no_bid: Optional[Decimal] = None   # Best bid for No
    no_ask: Optional[Decimal] = None   # Best ask for No
    yes_price: Optional[Decimal] = None  # Last trade price
    no_price: Optional[Decimal] = None
    timestamp: Optional[datetime] = None


@dataclass
class KalshiBalance:
    """Represents Kalshi account balance.

    DEPRECATED: Use RawVenueBalance from merid.event_venues.kalshi.types
    for new code. This class is kept for backward compatibility only.
    """
    balance: Decimal  # Available balance in cents
    locked_balance: Decimal  # Locked in orders
    total_balance: Decimal
    currency: str = "USD"


@dataclass
class KalshiConfig:
    """Configuration for Kalshi client.

    NOTE: URL defaults are overridden at runtime by get_kalshi_base_url() from invariants.py.
    These dataclass defaults are only used as fallbacks if invariants import fails.
    For production, set KALSHI_ENV=live/demo or KALSHI_API_BASE_URL explicitly.
    """

    # API endpoints — defaults overridden by invariants.get_kalshi_base_url()
    # Kalshi's recommended URLs: external-api.kalshi.com (live), external-api.demo.kalshi.co (demo)
    # CRITICAL FIX: Updated ws_api_url to match unified config (external-api-ws.kalshi.com)
    # Previous value (external-api.kalshi.com) was incorrect and caused connection failures
    rest_api_url: str = "https://external-api.kalshi.com/trade-api/v2"
    ws_api_url: str = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    demo_rest_api_url: str = "https://external-api.demo.kalshi.co/trade-api/v2"
    demo_ws_api_url: str = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"

    # Public market-data endpoint (unified, recommended host for discovery)
    public_rest_api_url: str = "https://external-api.kalshi.com/trade-api/v2"

    # Authentication
    email: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None  # For RSA auth
    private_key_path: Optional[str] = None  # Path to RSA private key file
    private_key_pem: Optional[str] = None   # Inline PEM string (alternative to file path)
    use_demo: bool = False

    # Request settings
    timeout: float = 30.0
    ws_timeout: float = 60.0

    def __post_init__(self):
        import os
        # ── URL Resolution: Use invariants module as single source of truth ─────
        # Respect KALSHI_API_BASE_URL from invariants.py instead of hard-coded defaults
        try:
            from merid.event_venues.kalshi.invariants import get_kalshi_base_url, get_kalshi_ws_url
            _base_url = get_kalshi_base_url()
            _ws_url = get_kalshi_ws_url()
            # Override hard-coded defaults with invariants-based URLs
            self.rest_api_url = _base_url
            self.ws_api_url = _ws_url
            # Demo URLs remain as-is (invariants returns live URL by default)
            # Demo mode selection happens via use_demo flag below
        except Exception as _url_exc:
            logger.warning(
                "KalshiConfig: failed to get base URL from invariants, using hard-coded defaults. Error: %s",
                _url_exc
            )
        # ── End URL Resolution ───────────────────────────────────────────────

        # Prefer merid.settings over raw env vars for consistency
        try:
            from merid.settings import settings as _s
            _email = _s.KALSHI_EMAIL
            _password = _s.KALSHI_PASSWORD
            _api_key = _s.KALSHI_API_KEY_ID or os.getenv("KALSHI_API_KEY")
            _key_path = _s.KALSHI_PRIVATE_KEY_PATH
            _key_pem = _s.KALSHI_PRIVATE_KEY_PEM
            _use_demo = _s.KALSHI_USE_DEMO
            _api_host = _s.KALSHI_API_HOST
        except Exception as _se:
            logger.warning(
                "KalshiConfig: merid.settings unavailable, falling back to env. "
                "Verify settings module in production. Error: %s", _se
            )
            _email = os.getenv("KALSHI_EMAIL")
            _password = os.getenv("KALSHI_PASSWORD")
            _api_key = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY")
            _key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
            _key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
            _use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"  # default: live (opt-in for demo)
            _api_host = os.getenv("KALSHI_API_HOST")
        if self.email is None:
            self.email = _email
        if self.password is None:
            self.password = _password

        # ── A7: KALSHI_ENV-aware key selection ─────────────────────────────
        # Explicit per-environment key pairs take precedence over legacy vars.
        _kalshi_env = os.getenv("KALSHI_ENV", "").lower()  # "demo" or "live"

        # Deprecation warning: if KALSHI_ENV is unset but KALSHI_USE_DEMO is set, warn user
        if not _kalshi_env and _use_demo:
            logger.warning(
                "KALSHI_ENV_DEPRECATED_BOOL_USED: KALSHI_ENV is unset but KALSHI_USE_DEMO=%s. "
                "Set KALSHI_ENV=demo explicitly instead. Treating as KALSHI_ENV=demo.",
                _use_demo
            )
            _kalshi_env = "demo" if _use_demo else "live"

        if _kalshi_env == "live":
            _env_key = os.getenv("KALSHI_LIVE_API_KEY_ID")
            _env_path = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
            _env_pem = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM")
            if not _env_key and not _api_key:
                raise ValueError(
                    "KALSHI_ENV=live but no live API key found. "
                    "Set KALSHI_LIVE_API_KEY_ID (and KALSHI_LIVE_PRIVATE_KEY_PATH)."
                )
            _api_key = _env_key or _api_key
            _key_path = _env_path or _key_path
            _key_pem = _env_pem or _key_pem
            _use_demo = False
        elif _kalshi_env == "demo":
            _env_key = os.getenv("KALSHI_DEMO_API_KEY_ID")
            _env_path = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH")
            _env_pem = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PEM")
            _api_key = _env_key or _api_key
            _key_path = _env_path or _key_path
            _key_pem = _env_pem or _key_pem
            _use_demo = True
        elif _kalshi_env:
            # Warn on invalid KALSHI_ENV values so typos don't go unnoticed
            logger.warning(
                "KalshiConfig: unknown KALSHI_ENV=%r; using legacy use_demo=%s. "
                "Valid values: 'live' or 'demo'", _kalshi_env, _use_demo
            )
        # ── End A7 ─────────────────────────────────────────────────────────

        if self.api_key is None:
            self.api_key = _api_key
        if self.private_key_path is None:
            path = _key_path
            # Treat placeholder as unset
            if path and path != "change_me":
                self.private_key_path = path
        if self.private_key_pem is None:
            self.private_key_pem = _key_pem
        # Only apply env-derived use_demo when caller left the field at its
        # dataclass default (False). An explicit use_demo=True from the caller
        # must not be silently overwritten by a missing env var.
        if not self.use_demo:
            self.use_demo = _use_demo
        # Override the active URL if KALSHI_API_HOST is set explicitly (legacy, deprecated)
        if _api_host:
            logger.warning(
                "KalshiConfig: KALSHI_API_HOST is deprecated. Use KALSHI_API_BASE_URL instead. "
                "KALSHI_API_HOST=%s will override invariants-based URL.", _api_host
            )
            if self.use_demo:
                self.demo_rest_api_url = _api_host
            else:
                self.rest_api_url = _api_host

        # MODE CONSISTENCY CHECK: Ensure use_demo matches TradeMode
        # This must happen after environment/host/key selection
        try:
            from merid.mode_resolver import ModeResolver
            ModeResolver.assert_mode_consistency()
        except Exception as mode_exc:
            logger.error("KalshiConfig mode consistency check failed: %s", mode_exc)
            raise

    @property
    def base_url(self) -> str:
        """Get base URL based on environment."""
        return self.demo_rest_api_url if self.use_demo else self.rest_api_url

    @property
    def ws_url(self) -> str:
        """Get WebSocket URL based on environment."""
        return self.demo_ws_api_url if self.use_demo else self.ws_api_url

    def log_startup_sanity(self):
        """Log startup sanity check for Kalshi configuration.

        This should be called during system startup to verify:
        - Correct API base URL (demo vs live)
        - Environment setting
        - Auth configuration status
        """
        env = "demo" if self.use_demo else "live"
        base_url = self.base_url
        ws_url = self.ws_url

        # Check auth configuration
        has_api_key = bool(self.api_key and self.api_key != "change_me")
        has_key_path = bool(self.private_key_path and self.private_key_path != "change_me")
        has_key_pem = bool(self.private_key_pem and self.private_key_pem != "change_me")
        has_auth = has_api_key and (has_key_path or has_key_pem)

        # Redact API key for logging
        redacted_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if self.api_key and len(self.api_key) > 8 else "NOT_SET"

        logger.info("=" * 80)
        logger.info("KALSHI CLIENT STARTUP SANITY CHECK")
        logger.info("=" * 80)
        logger.info(f"Environment: {env}")
        logger.info(f"REST API URL: {base_url}")
        logger.info(f"WebSocket URL: {ws_url}")
        logger.info(f"API Key: {redacted_key} (configured: {has_api_key})")
        logger.info(f"Private Key Path: {self.private_key_path} (configured: {has_key_path})")
        logger.info(f"Private Key PEM: {'SET' if has_key_pem else 'NOT_SET'} (configured: {has_key_pem})")
        logger.info(f"Auth Configured: {has_auth}")

        if not has_auth:
            logger.warning(
                "KALSHI AUTH NOT CONFIGURED - Order placement will fail. "
                "Set KALSHI_API_KEY_ID and either KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM"
            )

        if self.use_demo and "demo-api.kalshi.co" not in base_url:
            logger.warning(
                f"use_demo=True but base URL does not contain 'demo-api.kalshi.co': {base_url}"
            )

        if not self.use_demo and "external-api.kalshi.com" not in base_url:
            logger.warning(
                f"use_demo=False but base URL does not contain 'external-api.kalshi.com': {base_url}"
            )

        logger.info("=" * 80)


@dataclass
class KalshiMarketState:
    """Live per-ticker state maintained by KalshiMarketStateStore.

    Two independent write paths own disjoint slices:
    - WS orderbook path: book_initialized, best_bid/ask_cents, mid_cents,
      spread_cents, top_of_book_size, depth_10c, yes_bids, no_bids,
      last_book_update_ts.
    - REST metadata path: volume_24h, open_interest, notional_value_cents,
      all three expiry fields, seconds_to_expiry, last_rest_update_ts,
      underlying, strike_price, floor_strike, cap_strike.
    - REST quote path (per-feed BBO for cross-feed coherence): last_rest_bid_cents,
      last_rest_ask_cents, last_rest_quote_update_ts.  This is only touched by
      authoritative REST orderbook snapshots/deltas, never by catalog metadata.
    """

    ticker: str

    # REST-owned fields (static market metadata)
    volume_24h: int = 0
    open_interest: int = 0
    notional_value_cents: int = 0
    expiration_time: Optional[str] = None
    expected_expiration_time: Optional[str] = None
    latest_expiration_time: Optional[str] = None
    seconds_to_expiry: Optional[float] = None

    # NEW: Underlying asset and strike info (from catalog REST data)
    underlying: Optional[str] = None  # BTC, ETH, SOL, XRP, DOGE, etc.
    strike_price: Optional[float] = None  # Single strike for binary markets
    floor_strike: Optional[float] = None  # Floor for range markets (Kalshi's reference for 15m UP/DOWN)
    cap_strike: Optional[float] = None    # Cap for range markets
    external_spot: Optional[float] = None  # CF Benchmarks RTI / external feed

    # Dual-source strike price capture for 15-minute markets
    window_strike_price: Optional[float] = None  # Captured strike at window start (primary: floor_strike)
    window_strike_source: str = ""  # Source: "kalshi_floor_strike", "candle_open", "spot_fallback"
    window_strike_ts: float = 0.0  # Timestamp when strike was captured
    candle_open_price: Optional[float] = None  # 15-minute candle open price (secondary validation)
    candle_open_ts: float = 0.0  # Timestamp when candle open was captured

    # CRITICAL: 2026-07-01 - Continuous strike divergence tracking for 15-minute markets
    # Tracks how far spot price moves from strike throughout the 15-minute window
    # Best practice: Real-time monitoring for exit decisions and risk management
    strike_divergence_history: List[Tuple[float, float, float]] = field(default_factory=list)  # (timestamp, divergence_pct, spot_price)
    max_divergence_pct: float = 0.0  # Maximum divergence observed during window
    current_divergence_pct: float = 0.0  # Current divergence from strike
    last_divergence_update_ts: float = 0.0  # Timestamp of last divergence calculation

    # Book-owned fields (dynamic from WS orderbook)
    book_initialized: bool = False
    best_bid_cents: Optional[int] = None
    best_ask_cents: Optional[int] = None
    # CRITICAL FIX (2026-08-01): Add NO-side specific fields for proper NO-side tracking
    best_no_bid_cents: Optional[int] = None
    best_no_ask_cents: Optional[int] = None
    mid_cents: Optional[int] = None
    spread_cents: Optional[float] = None
    top_of_book_size: int = 0
    depth_10c: int = 0
    yes_bids: List[Any] = field(default_factory=list)
    no_bids: List[Any] = field(default_factory=list)

    # Timestamps (monotonic)
    last_book_update_ts: float = 0.0
    last_book_update_wall_ts: float = 0.0  # wall-clock sibling of last_book_update_ts (no monotonic->wall approximation)
    last_rest_update_ts: float = 0.0
    last_update: Optional[datetime] = None  # UTC datetime of last state update

    # Ticker quote fallback (from WS ticker channel).  Used as a redundant
    # source of top-of-book prices when the orderbook channel is crossed or
    # one-sided due to one-sided delta streams.
    quoted_bid_cents: Optional[int] = None
    quoted_ask_cents: Optional[int] = None
    quote_received_ts: float = 0.0

    # Diagnostic fallback quote in YES price space.  These are stored for
    # telemetry but must never overwrite executable BBO after a crossed/invalid
    # book has been detected.
    fallback_yes_bid_cents: Optional[int] = None
    fallback_yes_ask_cents: Optional[int] = None

    # Last good book tracking (for audit - tracks last known good state)
    last_good_bid_cents: Optional[int] = None
    last_good_ask_cents: Optional[int] = None
    last_good_mid_cents: Optional[int] = None
    last_good_book_ts: Optional[datetime] = None

    # Market status for health check (open/closed/paused/unknown)
    status: str = "open"

    # P0-1 DOWNSTREAM: Data source tracking (WS_LIVE, REST_BOOTSTRAP, STALE_WS)
    data_source: str = "UNKNOWN"

    # 2026-08-24: Quote ownership and timestamp tracking for WS/REST divergence
    # diagnosis.  Each feed records the last BBO it authored and the local time it
    # was received.  quote_owner is the feed that currently owns the executable BBO.
    last_ws_bid_cents: Optional[int] = None
    last_ws_ask_cents: Optional[int] = None
    last_ws_update_ts: float = 0.0
    last_rest_bid_cents: Optional[int] = None
    last_rest_ask_cents: Optional[int] = None
    last_rest_quote_update_ts: float = 0.0
    quote_owner: str = "UNKNOWN"

    # P0-2 UPSTREAM: Data quality tracking (GOOD, BAD_DUALITY, INCOMPLETE, UNKNOWN)
    data_quality: str = "UNKNOWN"

    # Book consistency tracking (GOOD, SUSPECT) for queue overflow detection
    book_consistency: str = "GOOD"

    # State-transition label for diagnostics and tests.
    # VALID, RESYNC_REQUIRED, CIRCUIT_BREAKER, INVALID_INVERTED,
    # INVALID_SEQUENCE_GAP, INVALID_UNKNOWN_MARKET
    transition: str = "VALID"

    # Explicit loss-aware book health state machine (2026-08-23).
    # Canonical source of truth for the book's trustworthiness lifecycle.
    book_health: str = "NO_SNAPSHOT"

    # P1 HARDENING (2026-08-22): Cause that made the book invalid/break.
    invalidation_cause: str = ""

    # P1 HARDENING (2026-08-22): Required source class to recover.
    #   LIVE_DELTA      - a contiguous WS delta after invariants pass
    #   FULL_SNAPSHOT   - a full REST or clean WS snapshot
    #   OPERATOR_RESET  - manual/admin override only
    recovery_required_source: str = ""

    # Trade eligibility flag (separate from quote availability)
    # True only when: book is initialized with live data, market is not suspended,
    # and health state allows trading. Fallback quotes are never executable.
    executable: bool = False

    # P0-2 HARDENING (2026-08-22): Attested recovery tracking.
    # recovery_attested is set to True only when a clean, authoritative source
    # (REST full orderbook, contiguous WS deltas, or an explicit test fixture)
    # restores an INVALID / CIRCUIT_BREAKER book.  Catalog metadata and quote
    # fallbacks must never clear a circuit breaker.
    recovery_attested: bool = False
    recovery_source: Optional[str] = None
    recovery_ts: float = 0.0

    # P1 HARDENING (2026-08-22): A bootstrap snapshot is a full book, but it is
    # not yet live-sequence confirmed.  New entries should remain blocked until
    # a contiguous WS delta (or REST refresh) confirms the sequence.
    live_sequence_confirmed: bool = False

    # 2026-08-24: Snapshot completion flag.  True only when a valid full
    # orderbook snapshot has been applied to this market.  It is set by
    # orderbook_snapshot messages and authoritative REST snapshots, persisted
    # across live deltas, and explicitly reset on sequence gaps, invalidation,
    # resync, reconnect, or ticker rollover.  This is the canonical gate behind
    # the ENTRY-READINESS ``ws_snapshot_complete`` field.
    snapshot_complete: bool = False

    # Liquidity audit fields (for MD-HEALTH logging and validation)
    has_bid: bool = False  # whether bid side exists
    has_ask: bool = False  # whether ask side exists
    # CRITICAL FIX (2026-08-01): Add NO-side liquidity flags
    has_no_bid: bool = False  # whether NO bid side exists
    has_no_ask: bool = False  # whether NO ask side exists
    min_depth_yes: int = 0  # size at best YES bid (same ladder as NO ask)
    min_depth_no: int = 0   # size at best YES ask (same ladder as NO bid)
    depth_10c_yes: int = 0  # window-based depth on yes side (±10c of mid)
    depth_10c_no: int = 0  # window-based depth on no side (±10c of mid, YES-equivalent)
    depth_10c: int = 0  # total window-based depth (YES + NO)
    last_update_ts: float = 0.0  # monotonic timestamp of last update

    # Aliases for backward compatibility (OBI filter uses these names)
    @property
    def depth_yes(self) -> int:
        """Alias for min_depth_yes for backward compatibility."""
        return self.min_depth_yes

    @property
    def depth_no(self) -> int:
        """Alias for min_depth_no for backward compatibility."""
        return self.min_depth_no

    # CRITICAL FIX (2026-08-13): Explicit executable ask-size accessors.
    # In Kalshi's binary book, the YES best ask and NO best bid share one ladder
    # (price p for YES ask == 100 - p for NO bid), and the YES best bid and NO
    # best ask share the other.  These aliases make the executable side explicit
    # for sizing, impact, and trace assertions.  Use these rather than the legacy
    # min_depth_* names whenever you mean "executable size at the ask".
    @property
    def yes_ask_size(self) -> int:
        """Executable size at the best YES ask (min_depth_no, the NO-bid ladder)."""
        return self.min_depth_no

    @property
    def no_ask_size(self) -> int:
        """Executable size at the best NO ask (min_depth_yes, the YES-bid ladder)."""
        return self.min_depth_yes

    @property
    def yes_bid_size(self) -> int:
        """Executable size at the best YES bid."""
        return self.min_depth_yes

    @property
    def no_bid_size(self) -> int:
        """Executable size at the best NO bid."""
        return self.min_depth_no

    def get_executable_ask_size(self, side: str, price_cents: Optional[int] = None) -> int:
        """Return the executable ask size for a given side and price.

        For BUY_YES this is the YES-ask size (which lives on the NO-bid ladder).
        For BUY_NO this is the NO-ask size (which lives on the YES-bid ladder).
        If ``price_cents`` matches the best ask for that side, the cached best-ask
        size is returned; otherwise the size at the exact price level is looked up.
        """
        side = (side or "yes").lower()
        if side == "yes":
            best_ask = self.best_ask_cents
            if best_ask is not None and (price_cents is None or price_cents == best_ask):
                return self.yes_ask_size
            target = 100 - (price_cents or 0)
            for p, s in self.no_bids:
                if p == target:
                    return s
            return 0
        else:
            best_no_ask = self.best_no_ask_cents
            if best_no_ask is not None and (price_cents is None or price_cents == best_no_ask):
                return self.no_ask_size
            target = 100 - (price_cents or 0)
            for p, s in self.yes_bids:
                if p == target:
                    return s
            return 0

    # Liquidity status classification
    # Note: Using str instead of LiquidityStatus enum to avoid circular import
    # Values: MISSING, ONE_SIDED, DEPTH_TOO_LOW, OK
    liquidity_status: str = "MISSING"

    # P1 FIX: Transport health fields (separate from liquidity)
    # These track WS/REST connectivity, not market conditions
    transport_stale: bool = False  # True if no recent updates
    transport_mode: str = "unknown"  # "ws", "rest", "none"

    # P1 FIX: Liquidity health fields (separate from transport)
    # These track market conditions, not pipeline health
    illiquid: bool = False  # True if spread wide but transport OK

    # P1 FIX: State consistency field
    # True if YES+NO != 100c (indicates orderbook application bug)
    state_inconsistent: bool = False

    # Kalshi exchange shard index (e.g. 2 for crypto 15m markets)
    exchange_index: Optional[int] = None

    # ── Derived helpers for UI ─────────────────────────────────────────

    @property
    def yes_bid(self) -> Optional[float]:
        """Best yes bid price as float (0-1 range), or None."""
        if self.best_bid_cents is None:
            return None
        return self.best_bid_cents / 100.0

    @property
    def yes_ask(self) -> Optional[float]:
        """Best yes ask price as float (0-1 range), or None."""
        if self.best_ask_cents is None:
            return None
        return self.best_ask_cents / 100.0

    @property
    def no_bid(self) -> Optional[float]:
        """Best no bid price as float (0-1 range), derived from yes ask."""
        yes_ask = self.yes_ask
        if yes_ask is None:
            return None
        return 1.0 - yes_ask

    @property
    def no_ask(self) -> Optional[float]:
        """Best no ask price as float (0-1 range), derived from yes bid."""
        yes_bid = self.yes_bid
        if yes_bid is None:
            return None
        return 1.0 - yes_bid

    @property
    def prob(self) -> Optional[float]:
        """Implied probability from mid price (0-1 range), or None.

        Uses the midpoint between best yes bid and best yes ask.
        Falls back to yes bid alone if no ask available.
        """
        if self.mid_cents is not None:
            return self.mid_cents / 100.0
        # Fallback: use bid price if that's all we have
        if self.best_bid_cents is not None:
            return self.best_bid_cents / 100.0
        return None

    @property
    def vol(self) -> int:
        """Volume for UI display (24h volume)."""
        return self.volume_24h

    @property
    def expiry(self) -> Optional[str]:
        """Human-readable expiration time (alias for expiration_time)."""
        return self.expiration_time

    def check_health(self) -> Dict[str, Any]:
        """Return health status separating transport from liquidity.

        This method distinguishes between:
        - Transport health: WS/REST connectivity
        - Liquidity health: Market conditions (spread, depth)
        - State consistency: Orderbook application correctness

        Returns:
            Dict with transport_healthy, liquidity_healthy, overall_healthy, and details
        """
        now = time.monotonic()

        # Constants for health thresholds
        _MAX_WS_AGE_SECONDS = 5.0  # 5 seconds for transport stale
        _MAX_REST_AGE_SECONDS = 60.0  # 60 seconds for REST stale
        # 2026-07-12: ALIGNED with industry research - 20c max for 15m crypto (industry: 15-20c for short-duration markets)
        _SPREAD_THRESHOLD_CENTS = 20  # 20 cents for illiquid threshold (aligned with industry standards)
        _DUALITY_EPSILON_CENTS = 2  # 2 cents tolerance for YES+NO sums

        # Transport health check
        ws_age = now - self.last_book_update_ts if self.last_book_update_ts > 0 else float('inf')
        rest_age = now - self.last_rest_update_ts if self.last_rest_update_ts > 0 else float('inf')

        transport_healthy = (ws_age < _MAX_WS_AGE_SECONDS) or (rest_age < _MAX_REST_AGE_SECONDS)
        self.transport_stale = not transport_healthy

        # Determine transport mode
        if ws_age < _MAX_WS_AGE_SECONDS:
            self.transport_mode = "ws"
        elif rest_age < _MAX_REST_AGE_SECONDS:
            self.transport_mode = "rest"
        else:
            self.transport_mode = "none"

        # Liquidity health check (only if transport is healthy)
        if transport_healthy:
            # Check spread and depth
            spread_ok = (self.spread_cents or 0) < _SPREAD_THRESHOLD_CENTS
            depth_ok = self.min_depth_yes > 0 and self.min_depth_no > 0
            self.illiquid = not (spread_ok and depth_ok)
        else:
            self.illiquid = False  # Can't determine liquidity if transport stale

        # State consistency check (YES+NO should sum to 100c for binary markets)
        yes_plus_no = (self.best_bid_cents or 0) + (self.best_ask_cents or 0)
        self.state_inconsistent = abs(yes_plus_no - 100) > _DUALITY_EPSILON_CENTS

        # Overall health
        overall_healthy = transport_healthy and not self.illiquid and not self.state_inconsistent

        return {
            "transport_healthy": transport_healthy,
            "liquidity_healthy": not self.illiquid,
            "state_consistent": not self.state_inconsistent,
            "overall_healthy": overall_healthy,
            "transport_mode": self.transport_mode,
            "ws_age_s": ws_age,
            "rest_age_s": rest_age,
            "spread_cents": self.spread_cents,
            "depth_yes": self.min_depth_yes,
            "depth_no": self.min_depth_no,
        }


# ── Typed venue response objects ──────────────────────────────────────


@dataclass(frozen=True)
class VenueBalance:
    """Typed balance response from Kalshi ``/portfolio/balance``.

    Replaces raw ``{"USD": Decimal, "locked": Decimal}`` dicts so
    callers never mis-key fields (e.g. ``"available"`` vs ``"USD"``).
    """
    available_usd: Decimal  # Spendable balance (USD)
    locked_usd: Decimal  # Balance locked in open orders (USD)

    @property
    def total_usd(self) -> Decimal:
        return self.available_usd + self.locked_usd

    def to_dict(self) -> Dict[str, Any]:
        return {
            "USD": str(self.available_usd),
            "locked": str(self.locked_usd),
            "total": str(self.total_usd),
        }

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "VenueBalance":
        """Build from the raw dict returned by ``KalshiVenueClient.get_balance()``.

        Accepts both ``{"USD": ..., "locked": ...}`` and
        ``{"available": ..., "locked": ...}`` for backward compat.
        """
        avail = raw.get("USD", raw.get("available", Decimal("0")))
        locked = raw.get("locked", Decimal("0"))
        return cls(
            available_usd=Decimal(str(avail)),
            locked_usd=Decimal(str(locked)),
        )
