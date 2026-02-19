"""Kalshi models - Data transfer objects for Kalshi API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


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
    
    # API endpoints
    rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    ws_api_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    demo_rest_api_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    demo_ws_api_url: str = "wss://demo-ws.kalshi.co/v2"
    
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
        except Exception:
            _email = os.getenv("KALSHI_EMAIL")
            _password = os.getenv("KALSHI_PASSWORD")
            _api_key = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY")
            _key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
            _key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
            _use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"
            _api_host = os.getenv("KALSHI_API_HOST")
        if self.email is None:
            self.email = _email
        if self.password is None:
            self.password = _password
        if self.api_key is None:
            self.api_key = _api_key
        if self.private_key_path is None:
            path = _key_path
            # Treat placeholder as unset
            if path and path != "change_me":
                self.private_key_path = path
        if self.private_key_pem is None:
            self.private_key_pem = _key_pem
        if not self.use_demo:
            self.use_demo = _use_demo
        # Override rest_api_url if KALSHI_API_HOST is set (e.g. elections endpoint)
        if _api_host and not self.use_demo:
            self.rest_api_url = _api_host
    
    @property
    def base_url(self) -> str:
        """Get base URL based on environment."""
        return self.demo_rest_api_url if self.use_demo else self.rest_api_url
    
    @property
    def ws_url(self) -> str:
        """Get WebSocket URL based on environment."""
        return self.demo_ws_api_url if self.use_demo else self.ws_api_url
