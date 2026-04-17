"""Polymarket models - Data transfer objects for Polymarket API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class MarketOutcome:
    """Represents a market outcome."""
    outcome: str
    price: Decimal
    probability: Decimal
    best_ask_price: Optional[Decimal] = None
    best_bid_price: Optional[Decimal] = None


@dataclass
class Market:
    """Represents a Polymarket market."""
    id: str
    question: str
    description: str
    outcomes: List[MarketOutcome]
    end_date: Optional[datetime] = None
    active: bool = True
    volume: Optional[Decimal] = None
    liquidity: Optional[Decimal] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None


@dataclass
class Order:
    """Represents a trading order."""
    id: str
    market_id: str
    outcome: str
    side: str  # "buy" or "sell"
    size: Decimal
    price: Decimal
    filled: Decimal = Decimal("0")
    remaining: Optional[Decimal] = None
    status: str = "pending"  # pending, filled, cancelled
    created_at: Optional[datetime] = None


@dataclass
class Position:
    """Represents a user position."""
    market_id: str
    outcome: str
    size: Decimal
    average_price: Decimal
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    created_at: Optional[datetime] = None


@dataclass
class Trade:
    """Represents a trade execution."""
    id: str
    market_id: str
    outcome: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime


@dataclass
class OrderBook:
    """Represents market order book."""
    market_id: str
    outcome: str
    bids: List[tuple[Decimal, Decimal]]  # (price, size)
    asks: List[tuple[Decimal, Decimal]]  # (price, size)
    timestamp: datetime


@dataclass
class PolymarketConfig:
    """Configuration for Polymarket client."""
    
    gamma_api_base: str = "https://gamma-api.polymarket.com"
    clob_api_base: str = "https://clob.polymarket.com"
    data_api_base: str = "https://data.polymarket.com"
    graphql_url: str = "https://polymarket.com/graphql"
    ws_url: str = "wss://ws.polymarket.com"
    
    # Authentication
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    wallet_address: Optional[str] = None
    private_key: Optional[str] = None
    
    # Request timeouts
    timeout: float = 30.0
    ws_timeout: float = 60.0
    
    def __post_init__(self):
        import os
        if self.api_key is None:
            self.api_key = os.getenv("POLYMARKET_API_KEY")
        if self.api_secret is None:
            self.api_secret = os.getenv("POLYMARKET_API_SECRET")
        if self.wallet_address is None:
            self.wallet_address = os.getenv("POLYMARKET_WALLET_ADDRESS")
        if self.private_key is None:
            self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
