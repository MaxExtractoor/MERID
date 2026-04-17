"""
Kalshi Market Wiring Layer

Complete market coverage, explicit mapping, and strong safety constraints
for Kalshi prediction markets integration with MERID unified signal system.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring")


class RiskProfile(Enum):
    """Risk profile classification for Kalshi markets"""
    MACRO_ELECTION = "macro_election"
    CRYPTO_LINKED = "crypto_linked"
    EQUITY_LINKED = "equity_linked"
    IDIOSYNCRATIC = "idiosyncratic"


class MarketStatus(Enum):
    """Market status from Kalshi"""
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


@dataclass
class KalshiMarketRecord:
    """Complete Kalshi market record with all required fields"""
    # Kalshi identifiers
    market_ticker: str  # Primary key, e.g. "KXBTCD-25JUN-T100000"
    event_ticker: str   # From Kalshi
    series_ticker: str  # From Kalshi
    
    # Kalshi metadata
    category: str       # Kalshi series category
    tags: List[str]     # Kalshi tags/labels
    title: str          # Human-readable name
    subtitle: str       # Additional description
    close_ts: float     # Market close/settlement time
    
    # Status and timing
    status: MarketStatus
    enabled_for_merid: bool
    
    # Risk management
    risk_profile: RiskProfile
    max_notional_per_trade: float
    max_daily_notional: float
    max_open_risk: float
    
    # Context and metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            "market_ticker": self.market_ticker,
            "event_ticker": self.event_ticker,
            "series_ticker": self.series_ticker,
            "category": self.category,
            "tags": json.dumps(self.tags),
            "title": self.title,
            "subtitle": self.subtitle,
            "close_ts": self.close_ts,
            "status": self.status.value,
            "enabled_for_merid": self.enabled_for_merid,
            "risk_profile": self.risk_profile.value,
            "max_notional_per_trade": self.max_notional_per_trade,
            "max_daily_notional": self.max_daily_notional,
            "max_open_risk": self.max_open_risk,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KalshiMarketRecord":
        """Create from database record"""
        return cls(
            market_ticker=data["market_ticker"],
            event_ticker=data["event_ticker"],
            series_ticker=data["series_ticker"],
            category=data["category"],
            tags=json.loads(data.get("tags", "[]")),
            title=data["title"],
            subtitle=data.get("subtitle", ""),
            close_ts=data["close_ts"],
            status=MarketStatus(data["status"]),
            enabled_for_merid=data["enabled_for_merid"],
            risk_profile=RiskProfile(data["risk_profile"]),
            max_notional_per_trade=data["max_notional_per_trade"],
            max_daily_notional=data["max_daily_notional"],
            max_open_risk=data["max_open_risk"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


@dataclass
class MarketMapping:
    """Single source of truth for market-to-MERID mappings"""
    # Kalshi identifiers
    market_ticker: str            # "KXBTCD-25JUN-T100000"
    event_ticker: str             # "E-BTC-DAILY-..."
    series_ticker: str            # "S-BTC-DAILY-..."
    
    # Classification
    category: str                 # "crypto", "macro", "elections", "equity", "idiosyncratic"
    risk_profile: RiskProfile
    
    # MERID symbol mappings
    underlying_symbol: str        # Internal underlying, e.g. "BTC"
    merid_symbol: str             # MERID trading symbol, e.g. "BTC", "BTC-USD"
    sentiment_symbols: List[str]  # Symbols for sentiment, e.g. ["BTC", "BTC-USD"]
    debate_symbol: Optional[str]  # Internal debate symbol if any
    
    # Control flags
    enabled: bool
    requires_crypto_context: bool
    requires_debate_context: bool
    requires_sentiment_context: bool
    
    # Data freshness constraints (seconds)
    max_crypto_staleness: float = 300.0  # 5 minutes
    max_sentiment_staleness: float = 600.0  # 10 minutes
    max_debate_staleness: float = 900.0   # 15 minutes
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            "market_ticker": self.market_ticker,
            "event_ticker": self.event_ticker,
            "series_ticker": self.series_ticker,
            "category": self.category,
            "risk_profile": self.risk_profile.value,
            "underlying_symbol": self.underlying_symbol,
            "merid_symbol": self.merid_symbol,
            "sentiment_symbols": json.dumps(self.sentiment_symbols),
            "debate_symbol": self.debate_symbol,
            "enabled": self.enabled,
            "requires_crypto_context": self.requires_crypto_context,
            "requires_debate_context": self.requires_debate_context,
            "requires_sentiment_context": self.requires_sentiment_context,
            "max_crypto_staleness": self.max_crypto_staleness,
            "max_sentiment_staleness": self.max_sentiment_staleness,
            "max_debate_staleness": self.max_debate_staleness,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketMapping":
        """Create from database record"""
        return cls(
            market_ticker=data["market_ticker"],
            event_ticker=data["event_ticker"],
            series_ticker=data["series_ticker"],
            category=data["category"],
            risk_profile=RiskProfile(data["risk_profile"]),
            underlying_symbol=data["underlying_symbol"],
            merid_symbol=data["merid_symbol"],
            sentiment_symbols=json.loads(data.get("sentiment_symbols", "[]")),
            debate_symbol=data.get("debate_symbol"),
            enabled=data["enabled"],
            requires_crypto_context=data["requires_crypto_context"],
            requires_debate_context=data["requires_debate_context"],
            requires_sentiment_context=data["requires_sentiment_context"],
            max_crypto_staleness=data.get("max_crypto_staleness", 300.0),
            max_sentiment_staleness=data.get("max_sentiment_staleness", 600.0),
            max_debate_staleness=data.get("max_debate_staleness", 900.0),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


@dataclass
class CoverageReport:
    """Coverage check report for market completeness"""
    total_open_markets: int
    mapped_markets: int
    enabled_markets: int
    unmapped_markets: int
    disabled_markets: int
    
    # Detailed breakdown
    unmapped_market_tickers: List[str]
    disabled_market_tickers: List[str]
    coverage_by_risk_profile: Dict[str, int]
    
    # Timestamps
    checked_at: float = field(default_factory=time.time)
    
    @property
    def coverage_percentage(self) -> float:
        """Percentage of open markets that are mapped"""
        if self.total_open_markets == 0:
            return 0.0
        return (self.mapped_markets / self.total_open_markets) * 100.0
    
    @property
    def enablement_percentage(self) -> float:
        """Percentage of open markets that are enabled"""
        if self.total_open_markets == 0:
            return 0.0
        return (self.enabled_markets / self.total_open_markets) * 100.0


@dataclass
class MarketContextConfig:
    """Complete context configuration for a market"""
    market_mapping: MarketMapping
    kalshi_market: KalshiMarketRecord
    
    # Context availability flags
    crypto_context_available: bool = False
    sentiment_context_available: bool = False
    debate_context_available: bool = False
    
    # Freshness checks
    crypto_fresh: bool = False
    sentiment_fresh: bool = False
    debate_fresh: bool = False
    
    # Risk caps
    effective_max_notional: float = 0.0
    effective_daily_notional: float = 0.0
    effective_open_risk: float = 0.0
    
    @property
    def context_complete(self) -> bool:
        """Check if all required contexts are available and fresh"""
        if self.market_mapping.requires_crypto_context:
            if not (self.crypto_context_available and self.crypto_fresh):
                return False
        
        if self.market_mapping.requires_sentiment_context:
            if not (self.sentiment_context_available and self.sentiment_fresh):
                return False
        
        if self.market_mapping.requires_debate_context:
            if not (self.debate_context_available and self.debate_fresh):
                return False
        
        return True
    
    @property
    def safe_to_trade(self) -> bool:
        """Check if market is safe for trading"""
        return (
            self.market_mapping.enabled and
            self.kalshi_market.enabled_for_merid and
            self.context_complete
        )
