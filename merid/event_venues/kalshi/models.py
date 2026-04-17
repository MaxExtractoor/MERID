"""Kalshi models - Data transfer objects for Kalshi API."""

from __future__ import annotations

from utils.logger import get_logger
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


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
    """Represents Kalshi account balance."""
    balance: Decimal  # Available balance in cents
    locked_balance: Decimal  # Locked in orders
    total_balance: Decimal
    currency: str = "USD"


@dataclass
class KalshiConfig:
    """Configuration for Kalshi client."""
    
    # API endpoints — live production matches Kalshi quick-start (authenticated REST + WS).
    # Demo: demo-api.kalshi.co; live: api.elections.kalshi.com (see Kalshi API docs).
    rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    ws_api_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    demo_rest_api_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    demo_ws_api_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    
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
        # Override the active URL if KALSHI_API_HOST is set explicitly
        if _api_host:
            if self.use_demo:
                self.demo_rest_api_url = _api_host
            else:
                self.rest_api_url = _api_host
    
    @property
    def base_url(self) -> str:
        """Get base URL based on environment."""
        return self.demo_rest_api_url if self.use_demo else self.rest_api_url
    
    @property
    def ws_url(self) -> str:
        """Get WebSocket URL based on environment."""
        return self.demo_ws_api_url if self.use_demo else self.ws_api_url


@dataclass
class KalshiMarketState:
    """Live per-ticker state maintained by KalshiMarketStateStore.

    Two independent write paths own disjoint slices:
    - WS orderbook path: book_initialized, best_bid/ask_cents, mid_cents,
      spread_cents, top_of_book_size, depth_10c, yes_bids, no_bids,
      last_book_update_ts.
    - REST path: volume_24h, open_interest, notional_value_cents, all three
      expiry fields, seconds_to_expiry, last_rest_update_ts,
      underlying, strike_price, floor_strike, cap_strike.
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
    floor_strike: Optional[float] = None  # Floor for range markets
    cap_strike: Optional[float] = None    # Cap for range markets
    external_spot: Optional[float] = None  # CF Benchmarks RTI / external feed

    # Book-owned fields (dynamic from WS orderbook)
    book_initialized: bool = False
    best_bid_cents: Optional[int] = None
    best_ask_cents: Optional[int] = None
    mid_cents: Optional[int] = None
    spread_cents: Optional[float] = None
    top_of_book_size: int = 0
    depth_10c: int = 0
    yes_bids: List[Any] = field(default_factory=list)
    no_bids: List[Any] = field(default_factory=list)

    # Timestamps (monotonic)
    last_book_update_ts: float = 0.0
    last_rest_update_ts: float = 0.0

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
