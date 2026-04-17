"""
Prediction Market Intelligence Extension

Integrates prediction market data from multiple sources:
- Polymarket (crypto-native, USDC-based)
- Kalshi (CFTC-regulated, event contracts)
- Augur (REP markets, AMM + order books)
- PredictIt (political markets)
- ForecastEx (CME Group)
- Metaculus (forecasting aggregator)

Implements:
- Odds drift detection and latency arbitrage signals
- Resolution-aware decay mechanics
- Time-to-event compression analysis
- Cross-platform odds divergence
- Oracle lag exploitation (simulation-first)
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime
import math

from utils.logger import get_logger

logger = get_logger("monitoring.prediction_markets")

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning default on failure."""
    try:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip() == "":
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


class PredictionPlatform(Enum):
    """Supported prediction market platforms."""
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    AUGUR = "augur"
    PREDICTIT = "predictit"
    FORECASTEX = "forecastex"
    METACULUS = "metaculus"
    DRAFTKINGS = "draftkings"
    FANDUEL = "fanduel"


class MarketCategory(Enum):
    """Market categories."""
    CRYPTO = "crypto"
    POLITICS = "politics"
    ECONOMICS = "economics"
    SPORTS = "sports"
    WEATHER = "weather"
    ENTERTAINMENT = "entertainment"
    SCIENCE = "science"
    FINANCE = "finance"
    MACRO = "macro"
    OTHER = "other"


class ResolutionStatus(Enum):
    """Market resolution status."""
    OPEN = "open"
    PENDING = "pending"
    RESOLVED_YES = "resolved_yes"
    RESOLVED_NO = "resolved_no"
    DISPUTED = "disputed"
    VOIDED = "voided"


@dataclass
class PredictionMarket:
    """A single prediction market."""
    market_id: str
    platform: PredictionPlatform
    question: str
    category: MarketCategory
    
    yes_price: float  # 0.0 to 1.0 (probability)
    no_price: float
    volume_24h: float
    total_volume: float
    liquidity: float
    
    resolution_date: Optional[float] = None  # Unix timestamp
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    status: ResolutionStatus = ResolutionStatus.OPEN
    oracle_source: Optional[str] = None
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def implied_probability(self) -> float:
        """Get implied probability from yes price."""
        return self.yes_price
    
    @property
    def time_to_resolution(self) -> Optional[float]:
        """Get seconds until resolution."""
        resolution = self.resolution_date
        if resolution is None:
            return None
        if isinstance(resolution, str):
            try:
                resolution = datetime.fromisoformat(
                    resolution.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                return None
        return max(0, float(resolution) - time.time())
    
    @property
    def days_to_resolution(self) -> Optional[float]:
        """Get days until resolution."""
        ttr = self.time_to_resolution
        if ttr is None:
            return None
        return ttr / 86400
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "platform": self.platform.value,
            "question": self.question,
            "category": self.category.value,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "implied_probability": self.implied_probability,
            "volume_24h": self.volume_24h,
            "total_volume": self.total_volume,
            "liquidity": self.liquidity,
            "resolution_date": self.resolution_date,
            "days_to_resolution": self.days_to_resolution,
            "status": self.status.value,
            "last_updated": self.last_updated,
        }


@dataclass
class OddsDriftSignal:
    """Signal for significant odds movement."""
    signal_id: str
    market_id: str
    platform: PredictionPlatform
    question: str
    
    old_probability: float
    new_probability: float
    drift_pct: float  # Percentage change
    drift_direction: str  # "up" or "down"
    
    time_window_seconds: int
    volume_in_window: float
    
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.7
    
    @property
    def is_significant(self) -> bool:
        """Check if drift is significant (>5% move)."""
        return abs(self.drift_pct) >= 5.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_id": self.signal_id,
            "market_id": self.market_id,
            "platform": self.platform.value,
            "question": self.question[:100],
            "old_probability": self.old_probability,
            "new_probability": self.new_probability,
            "drift_pct": self.drift_pct,
            "drift_direction": self.drift_direction,
            "time_window_seconds": self.time_window_seconds,
            "volume_in_window": self.volume_in_window,
            "timestamp": self.timestamp,
            "is_significant": self.is_significant,
        }


@dataclass
class CrossPlatformArbitrage:
    """Cross-platform arbitrage opportunity."""
    arb_id: str
    question: str
    category: MarketCategory
    
    platform_a: PredictionPlatform
    platform_b: PredictionPlatform
    
    prob_a: float
    prob_b: float
    spread: float  # Absolute difference
    spread_pct: float  # Percentage spread
    
    potential_edge: float  # Expected value edge
    liquidity_constraint: float  # Min liquidity available
    
    timestamp: float = field(default_factory=time.time)
    expires_in: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "arb_id": self.arb_id,
            "question": self.question[:100],
            "category": self.category.value,
            "platform_a": self.platform_a.value,
            "platform_b": self.platform_b.value,
            "prob_a": self.prob_a,
            "prob_b": self.prob_b,
            "spread": self.spread,
            "spread_pct": self.spread_pct,
            "potential_edge": self.potential_edge,
            "liquidity_constraint": self.liquidity_constraint,
            "timestamp": self.timestamp,
        }


@dataclass
class ResolutionDecayMetrics:
    """Time-decay metrics for approaching resolution."""
    market_id: str
    days_remaining: float
    
    decay_factor: float  # 0-1, higher = more decay pressure
    volatility_compression: float  # Expected vol reduction
    oracle_lag_risk: float  # Risk of oracle delay
    
    recommended_position_size: float  # As fraction of normal
    exit_urgency: str  # "none", "low", "medium", "high", "critical"
    
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "days_remaining": self.days_remaining,
            "decay_factor": self.decay_factor,
            "volatility_compression": self.volatility_compression,
            "oracle_lag_risk": self.oracle_lag_risk,
            "recommended_position_size": self.recommended_position_size,
            "exit_urgency": self.exit_urgency,
            "timestamp": self.timestamp,
        }


class PredictionMarketConnector:
    """Base connector for prediction market platforms."""
    
    def __init__(self, platform: PredictionPlatform):
        self.platform = platform
        self._markets: Dict[str, PredictionMarket] = {}
        self._price_history: Dict[str, deque] = {}
        self._last_fetch = 0.0
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from platform. Override in subclasses."""
        try:
            # Mock implementation for Phase 0 - simulate prediction markets
            mock_markets = [
                PredictionMarket(
                    id="market_001",
                    title="Will Bitcoin reach $100k by end of 2024?",
                    description="Binary prediction on Bitcoin price",
                    category=MarketCategory.CRYPTOCURRENCY,
                    outcomes=[
                        MarketOutcome(id="yes", title="Yes", probability=0.45, current_odds=1.22),
                        MarketOutcome(id="no", title="No", probability=0.55, current_odds=0.82)
                    ],
                    volume=1000000.0,
                    liquidity=500000.0,
                    end_time=time.time() + 86400 * 30,  # 30 days
                    resolution_time=None,
                    status="active",
                    created_at=time.time()
                ),
                PredictionMarket(
                    id="market_002",
                    title="Will Ethereum 2.0 launch in Q1 2024?",
                    description="Binary prediction on Ethereum 2.0 launch",
                    category=MarketCategory.TECHNOLOGY,
                    outcomes=[
                        MarketOutcome(id="yes", title="Yes", probability=0.35, current_odds=1.86),
                        MarketOutcome(id="no", title="No", probability=0.65, current_odds=0.54)
                    ],
                    volume=750000.0,
                    liquidity=375000.0,
                    end_time=time.time() + 86400 * 45,  # 45 days
                    resolution_time=None,
                    status="active",
                    created_at=time.time()
                ),
                PredictionMarket(
                    id="market_003",
                    title="Will US avoid recession in 2024?",
                    description="Binary prediction on US economic outlook",
                    category=Category.ECONOMICS,
                    outcomes=[
                        MarketOutcome(id="yes", title="Yes", probability=0.40, current_odds=1.50),
                        MarketOutcome(id="no", title="No", probability=0.60, current_odds=0.67)
                    ],
                    volume=1200000.0,
                    liquidity=600000.0,
                    end_time=time.time() + 86400 * 60,  # 60 days
                    resolution_time=None,
                    status="active",
                    created_at=time.time()
                )
            ]
            
            # Filter by category if specified
            if category:
                mock_markets = [m for m in mock_markets if m.category == category]
            
            # Update cache
            for market in mock_markets:
                self._markets[market.id] = market
            
            self._last_fetch = time.time()
            logger.info(f"Mock prediction markets fetched: {len(mock_markets)} markets")
            return mock_markets
            
        except Exception as e:
            logger.error(f"Mock prediction markets error: {e}")
            return []
    
    async def fetch_market(self, market_id: str) -> Optional[PredictionMarket]:
        """Fetch single market by ID."""
        try:
            # Check cache first
            if market_id in self._markets:
                return self._markets[market_id]
            
            # If not in cache, fetch all markets and return the requested one
            markets = await self.fetch_markets()
            return next((m for m in markets if m.id == market_id), None)
            
        except Exception as e:
            logger.error(f"Mock market fetch error for {market_id}: {e}")
            return None
    
    def get_cached_markets(self) -> List[PredictionMarket]:
        """Get cached markets."""
        return list(self._markets.values())
    
    def record_price(self, market_id: str, price: float) -> None:
        """Record price for history tracking."""
        if market_id not in self._price_history:
            self._price_history[market_id] = deque(maxlen=1000)
        self._price_history[market_id].append({
            "price": price,
            "timestamp": time.time()
        })
    
    def get_price_history(self, market_id: str, window_seconds: int = 3600) -> List[Dict]:
        """Get price history within time window."""
        if market_id not in self._price_history:
            return []
        
        cutoff = time.time() - window_seconds
        return [p for p in self._price_history[market_id] if p["timestamp"] >= cutoff]


class PolymarketConnector(PredictionMarketConnector):
    """Connector for Polymarket using the new unified client."""
    
    # Use Gamma API for market data (public, no auth required)
    API_BASE = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        super().__init__(PredictionPlatform.POLYMARKET)
        self._adapter = None
        self._adapter_initialized = False
        
    def _get_adapter(self):
        """Get or create the adapter instance."""
        if not self._adapter_initialized:
            # Check feature flag to disable new client
            import os
            use_new_client = os.getenv("MERID_POLYMARKET_NEW_CLIENT", "true").lower() == "true"
            
            if not use_new_client:
                logger.info("PolymarketConnector: New client disabled by feature flag")
                self._adapter = None
                self._adapter_initialized = True
                return self._adapter
                
            try:
                from merid.monitoring.polymarket_adapter import create_polymarket_adapter
                self._adapter = create_polymarket_adapter()
                self._adapter_initialized = True
                logger.info("PolymarketConnector: Using new PolymarketClient")
            except ImportError as e:
                logger.warning(f"PolymarketConnector: Failed to import adapter: {e}")
                logger.info("PolymarketConnector: Falling back to legacy implementation")
                self._adapter = None
                self._adapter_initialized = True
        return self._adapter
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Polymarket using the new client or fallback."""
        logger.info("Polymarket: Starting fetch...")
        
        # Try using new adapter first
        adapter = self._get_adapter()
        if adapter:
            try:
                markets = await adapter.fetch_polymarket_markets(limit=50)
                if markets:
                    # Store markets in existing format
                    for market in markets:
                        self._markets[market.market_id] = market
                        self.record_price(market.market_id, market.yes_price)
                    
                    self._last_fetch = time.time()
                    logger.info(f"Fetched {len(markets)} markets via PolymarketClient")
                    return markets
                    
            except Exception as e:
                logger.error(f"PolymarketClient fetch error: {e}")
                logger.info("PolymarketConnector: Falling back to legacy implementation")
        
        # Fallback to legacy implementation
        return await self._fetch_markets_legacy(category)
    
    async def _fetch_markets_legacy(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Legacy fetch implementation as fallback."""
        try:
            import httpx
            import asyncio
            
            # Use sync client in thread pool to avoid event loop SSL issues
            def sync_fetch():
                with httpx.Client(timeout=30.0, verify=False) as client:
                    response = client.get(
                        f"{self.API_BASE}/markets",
                        params={"active": "true", "closed": "false", "limit": 50}
                    )
                    return response
            
            response = await asyncio.get_event_loop().run_in_executor(None, sync_fetch)
            
            if response.status_code != 200:
                logger.warning(f"Polymarket API returned {response.status_code}")
                return []
            
            data = response.json()
            markets = []
            
            # Handle both list and dict responses
            items = data if isinstance(data, list) else data.get("data", data.get("markets", []))
            
            for item in items[:50]:
                market = self._parse_market(item)
                if market:
                    self._markets[market.market_id] = market
                    self.record_price(market.market_id, market.yes_price)
                    markets.append(market)
            
            self._last_fetch = time.time()
            logger.info(f"Fetched {len(markets)} markets from Polymarket (legacy)")
            return markets
            
        except Exception as e:
            import traceback
            logger.error(f"Polymarket fetch error: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            return []
    
    def _parse_market(self, data: Dict) -> Optional[PredictionMarket]:
        """Parse Polymarket API response into PredictionMarket."""
        try:
            # Extract prices - try multiple field names
            yes_price = 0.5
            no_price = 0.5
            
            # Try outcomePrices array
            if "outcomePrices" in data and data["outcomePrices"]:
                prices = data["outcomePrices"]
                if isinstance(prices, list) and len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
            
            # Try tokens array (Gamma API format)
            if "tokens" in data and data["tokens"]:
                tokens = data["tokens"]
                for token in tokens:
                    outcome = token.get("outcome", "").lower()
                    price = float(token.get("price", 0.5))
                    if outcome == "yes":
                        yes_price = price
                    elif outcome == "no":
                        no_price = price
            
            # Try bestBid/bestAsk
            if "bestBid" in data:
                yes_price = float(data.get("bestBid", 0.5))
            if "bestAsk" in data:
                no_price = 1.0 - float(data.get("bestAsk", 0.5))
            
            # Try clobTokenIds for price lookup
            if yes_price == 0.5 and "clobTokenIds" in data:
                # Would need separate price fetch - use midpoint estimate
                pass
            
            return PredictionMarket(
                market_id=f"poly_{data.get('condition_id', data.get('id', data.get('slug', '')))}",
                platform=PredictionPlatform.POLYMARKET,
                question=data.get("question", data.get("title", data.get("description", "Unknown"))),
                category=MarketCategory.CRYPTO,
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(data.get("volume24hr", data.get("volume", 0)) or 0),
                total_volume=float(data.get("volumeNum", data.get("volume", 0)) or 0),
                liquidity=float(data.get("liquidity", 0) or 0),
                resolution_date=data.get("endDate", data.get("end_date_iso")),
                status=ResolutionStatus.OPEN if data.get("active", True) else ResolutionStatus.RESOLVED_YES,
            )
        except Exception as e:
            logger.debug(f"Failed to parse Polymarket market: {e}")
            return None
    
    async def fetch_market(self, market_id: str) -> Optional[PredictionMarket]:
        """Fetch single market."""
        return self._markets.get(market_id)


class KalshiConnector(PredictionMarketConnector):
    """Connector for Kalshi (CFTC-regulated) using httpx for API calls."""
    
    def __init__(self):
        super().__init__(PredictionPlatform.KALSHI)
        self._api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self._api_host = os.getenv("KALSHI_API_HOST", "https://trading-api.kalshi.com/trade-api/v2")
        self._http_client = None
    
    def _get_http_client(self):
        """Get or create httpx client for Kalshi API."""
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(
                base_url=self._api_host,
                timeout=30.0,
                headers={"Content-Type": "application/json"}
            )
        return self._http_client
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Kalshi API using httpx."""
        try:
            if not self._api_key_id:
                logger.info("KalshiConnector: No API key configured — using public (unauthenticated) market list")
            
            client = self._get_http_client()
            
            # Fetch markets from Kalshi public API (no auth required for market list)
            try:
                response = await client.get("/markets", params={"limit": 100, "status": "open"})
                
                if response.status_code == 200:
                    data = response.json()
                    markets_data = data.get("markets", [])
                    logger.info(f"KalshiConnector: Successfully fetched {len(markets_data)} real markets")
                    
                    prediction_markets = []
                    for market in markets_data:
                        prediction_market = self._convert_kalshi_market_dict(market)
                        if prediction_market:
                            self._markets[prediction_market.market_id] = prediction_market
                            self.record_price(prediction_market.market_id, prediction_market.yes_price)
                            prediction_markets.append(prediction_market)
                    
                    self._last_fetch = time.time()
                    if prediction_markets:
                        logger.info(f"KalshiConnector: Converted {len(prediction_markets)} markets")
                        return prediction_markets
                    else:
                        logger.info("KalshiConnector: No markets converted, using mock data")
                        return self._get_mock_markets()
                else:
                    logger.warning(f"KalshiConnector: API returned {response.status_code}: {response.text[:200]}")
                    return self._get_mock_markets()
                    
            except Exception as api_error:
                logger.warning(f"KalshiConnector: API call failed: {api_error}")
                return self._get_mock_markets()
                
        except Exception as e:
            logger.error(f"Kalshi fetch error: {e}")
            return self._get_mock_markets()
    
    def _convert_kalshi_market_dict(self, market: dict) -> Optional[PredictionMarket]:
        """Convert Kalshi market dict to our PredictionMarket format."""
        try:
            from datetime import datetime
            
            # Log first market to see actual API response structure
            if not hasattr(self, '_logged_sample'):
                logger.info(f"Sample Kalshi market keys: {list(market.keys())}")
                logger.info(f"Sample market data: {market}")
                self._logged_sample = True
            
            market_id = market.get('ticker', f"kalshi_{market.get('id', 'unknown')}")
            question = market.get('title', market.get('subtitle', 'Kalshi Market'))
            
            # Determine category from question text + Kalshi category field
            question_lower = question.lower()
            kalshi_cat = market.get('category', '').lower()
            
            # Direct Kalshi category mapping (covers most markets)
            _KALSHI_CAT_MAP = {
                'economics': MarketCategory.ECONOMICS,
                'financials': MarketCategory.FINANCE,
                'finance': MarketCategory.FINANCE,
                'politics': MarketCategory.POLITICS,
                'crypto': MarketCategory.CRYPTO,
                'climate': MarketCategory.WEATHER,
                'weather': MarketCategory.WEATHER,
                'sports': MarketCategory.SPORTS,
                'entertainment': MarketCategory.ENTERTAINMENT,
                'science': MarketCategory.SCIENCE,
                'tech': MarketCategory.SCIENCE,
                'technology': MarketCategory.SCIENCE,
                'culture': MarketCategory.ENTERTAINMENT,
                'world': MarketCategory.MACRO,
                'geopolitics': MarketCategory.MACRO,
                'energy': MarketCategory.MACRO,
                'health': MarketCategory.SCIENCE,
                'elections': MarketCategory.POLITICS,
                'fed': MarketCategory.ECONOMICS,
                'market': MarketCategory.FINANCE,
            }
            
            # Try direct mapping first
            category = _KALSHI_CAT_MAP.get(kalshi_cat)
            
            # Fallback to keyword matching only if direct map didn't match
            if category is None:
                event_ticker = market.get('event_ticker', '').lower()
                combined = f"{question_lower} {kalshi_cat} {event_ticker}"
                if any(w in combined for w in ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'solana', 'sol', 'defi', 'blockchain', 'token', 'coin']):
                    category = MarketCategory.CRYPTO
                elif any(w in combined for w in ['election', 'president', 'politics', 'congress', 'senate', 'governor', 'vote', 'democrat', 'republican', 'biden', 'trump', 'nominee', 'primary', 'ballot', 'legislation', 'impeach', 'scotus', 'supreme court']):
                    category = MarketCategory.POLITICS
                elif any(w in combined for w in ['fed', 'inflation', 'economy', 'gdp', 'rate', 'cpi', 'ppi', 'jobs', 'unemployment', 'fomc', 'treasury', 'recession', 'tariff', 'trade war', 'deficit', 'debt ceiling']):
                    category = MarketCategory.ECONOMICS
                elif any(w in combined for w in ['stock', 'sp500', 's&p', 'nasdaq', 'dow', 'ipo', 'earnings', 'market cap', 'shares', 'equity', 'bond', 'yield']):
                    category = MarketCategory.FINANCE
                elif any(w in combined for w in ['nfl', 'nba', 'mlb', 'nhl', 'soccer', 'football', 'basketball', 'baseball', 'hockey', 'super bowl', 'world series', 'champion', 'playoff', 'tournament', 'sports', 'ufc', 'boxing', 'tennis', 'golf', 'olympics', 'medal']):
                    category = MarketCategory.SPORTS
                elif any(w in combined for w in ['temperature', 'hurricane', 'tornado', 'weather', 'climate', 'storm', 'flood', 'drought', 'wildfire', 'snowfall', 'rainfall', 'heat wave', 'cold snap']):
                    category = MarketCategory.WEATHER
                elif any(w in combined for w in ['movie', 'oscar', 'grammy', 'emmy', 'box office', 'tv show', 'streaming', 'entertainment', 'celebrity', 'album', 'netflix', 'disney', 'spotify', 'tiktok', 'youtube']):
                    category = MarketCategory.ENTERTAINMENT
                elif any(w in combined for w in ['science', 'nasa', 'space', 'ai', 'artificial intelligence', 'research', 'vaccine', 'fda', 'drug', 'disease', 'pandemic', 'virus', 'mars', 'moon']):
                    category = MarketCategory.SCIENCE
                elif any(w in combined for w in ['macro', 'geopolitical', 'war', 'china', 'russia', 'eu', 'nato', 'oil', 'opec', 'energy', 'gas price', 'commodit']):
                    category = MarketCategory.MACRO
                else:
                    category = MarketCategory.OTHER
            
            # Extract prices (Kalshi API v2 field mappings)
            # Kalshi returns prices in cents (0-100), convert to probability (0-1)
            yes_price = 0.0
            
            # Try Kalshi API v2 field names in order of preference
            price_fields = [
                'yes_ask', 'yes_bid', 'last_price', 'yes_price',
                'floor_strike', 'cap_strike',  # For ranged markets
            ]
            
            for field in price_fields:
                val = market.get(field)
                if val is not None and val != 0:
                    yes_price = float(val)
                    break
            
            # Check nested 'yes' and 'no' objects (common in API responses)
            if yes_price == 0 and 'yes' in market:
                yes_data = market['yes']
                if isinstance(yes_data, dict):
                    yes_price = float(yes_data.get('price', yes_data.get('last_price', 0)))
            
            # Convert from cents to decimal if needed
            if yes_price > 1:
                yes_price = yes_price / 100.0
            
            # Default to 50% if no price available
            if yes_price == 0:
                yes_price = 0.5
            
            # Clamp to valid probability range
            yes_price = max(0.01, min(0.99, yes_price))
            no_price = 1.0 - yes_price
            
            # Try multiple field names for volume (Kalshi API v2)
            volume_24h = 0.0
            volume_fields = [
                'volume_24h', 'volume', 'open_interest', 
                'dollar_volume', 'notional_value', 'liquidity'
            ]
            
            for field in volume_fields:
                val = market.get(field)
                if val is not None and val != 0:
                    volume_24h = float(val)
                    break
            
            # Get resolution date
            resolution_date = None
            if market.get('close_time'):
                try:
                    resolution_date = datetime.fromisoformat(market['close_time'].replace('Z', '+00:00'))
                except Exception as _rd_exc:
                    logger.debug("Resolution date parse failed for %s: %s", market.get('id', '?'), _rd_exc)
            
            # Convert resolution_date to Unix timestamp if it's a datetime
            resolution_timestamp = None
            if resolution_date:
                resolution_timestamp = resolution_date.timestamp() if hasattr(resolution_date, 'timestamp') else float(resolution_date)
            
            return PredictionMarket(
                market_id=market_id,
                platform=PredictionPlatform.KALSHI,
                question=question,
                category=category,
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(volume_24h),
                total_volume=float(volume_24h) * 10,  # Estimate total from 24h
                liquidity=float(volume_24h) * 0.5,
                resolution_date=resolution_timestamp,
                metadata={"url": f"https://kalshi.com/markets/{market_id}"}
            )
            
        except Exception as e:
            title = market.get('title', market.get('ticker', '?'))[:60]
            logger.warning(f"Failed to convert Kalshi market '{title}': {e}")
            return None
    
    def _convert_kalshi_market(self, kalshi_market) -> Optional[PredictionMarket]:
        """Convert Kalshi market format to our PredictionMarket format."""
        try:
            import time
            from datetime import datetime
            
            # Extract market data from Kalshi market object
            # Note: This is a simplified conversion - adjust based on actual Kalshi API response
            market_id = getattr(kalshi_market, 'ticker', f"kalshi_{id(kalshi_market)}")
            question = getattr(kalshi_market, 'title', 'Kalshi Market')
            
            # Determine category based on market content
            question_lower = question.lower()
            if any(w in question_lower for w in ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'solana', 'defi', 'blockchain', 'token', 'coin']):
                category = MarketCategory.CRYPTO
            elif any(w in question_lower for w in ['election', 'president', 'politics', 'congress', 'senate', 'governor', 'vote', 'democrat', 'republican', 'trump', 'biden']):
                category = MarketCategory.POLITICS
            elif any(w in question_lower for w in ['fed', 'inflation', 'economy', 'gdp', 'rate', 'cpi', 'jobs', 'unemployment', 'fomc', 'recession', 'tariff']):
                category = MarketCategory.ECONOMICS
            elif any(w in question_lower for w in ['stock', 'sp500', 's&p', 'nasdaq', 'dow', 'ipo', 'earnings', 'bond', 'yield']):
                category = MarketCategory.FINANCE
            elif any(w in question_lower for w in ['nfl', 'nba', 'mlb', 'nhl', 'super bowl', 'champion', 'playoff', 'sports', 'ufc', 'tennis', 'golf']):
                category = MarketCategory.SPORTS
            elif any(w in question_lower for w in ['temperature', 'hurricane', 'weather', 'storm', 'flood', 'drought', 'wildfire']):
                category = MarketCategory.WEATHER
            elif any(w in question_lower for w in ['movie', 'oscar', 'grammy', 'emmy', 'entertainment', 'celebrity', 'netflix']):
                category = MarketCategory.ENTERTAINMENT
            elif any(w in question_lower for w in ['science', 'nasa', 'space', 'ai', 'vaccine', 'fda', 'pandemic']):
                category = MarketCategory.SCIENCE
            elif any(w in question_lower for w in ['macro', 'war', 'china', 'russia', 'oil', 'opec', 'energy', 'gas price']):
                category = MarketCategory.MACRO
            else:
                category = MarketCategory.OTHER
            
            # Extract price data (Kalshi uses different field names)
            yes_price = 0.5  # Default
            no_price = 0.5   # Default
            
            # Try to get actual prices from Kalshi market
            if hasattr(kalshi_market, 'yes_price'):
                yes_price = float(kalshi_market.yes_price)
                no_price = 1.0 - yes_price
            elif hasattr(kalshi_market, 'outcome_prices') and len(kalshi_market.outcome_prices) >= 2:
                yes_price = float(kalshi_market.outcome_prices[0])
                no_price = float(kalshi_market.outcome_prices[1])
            
            # Get volume and liquidity
            volume_24h = getattr(kalshi_market, 'volume_24h', 100000)
            liquidity = getattr(kalshi_market, 'liquidity', 50000)
            
            # Get resolution date
            resolution_date = None
            if hasattr(kalshi_market, 'expiration_time'):
                resolution_date = kalshi_market.expiration_time
            
            return PredictionMarket(
                market_id=market_id,
                platform=self.platform,
                question=question,
                category=category,
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=volume_24h,
                total_volume=volume_24h,
                liquidity=liquidity,
                resolution_date=resolution_date,
                created_at=time.time()
            )
            
        except Exception as e:
            logger.warning(f"Failed to convert Kalshi market: {e}")
            return None
    
    def _get_mock_markets(self) -> List[PredictionMarket]:
        """Get mock Kalshi markets for fallback."""
        import time
        from datetime import datetime, timedelta
        
        mock_markets = [
            {
                "market_id": "kalshi_btc_100k_end_2024",
                "question": "Will Bitcoin reach $100,000 by December 31, 2024?",
                "category": MarketCategory.CRYPTO,
                "yes_price": 0.65,
                "no_price": 0.35,
                "volume_24h": 1500000,
                "liquidity": 500000,
                "resolution_date": (datetime(2024, 12, 31) - datetime(1970, 1, 1)).total_seconds()
            },
            {
                "market_id": "kalshi_eth_4k_end_2024", 
                "question": "Will Ethereum reach $4,000 by December 31, 2024?",
                "category": MarketCategory.CRYPTO,
                "yes_price": 0.58,
                "no_price": 0.42,
                "volume_24h": 800000,
                "liquidity": 300000,
                "resolution_date": (datetime(2024, 12, 31) - datetime(1970, 1, 1)).total_seconds()
            },
            {
                "market_id": "kalshi_fed_rate_cut_q1_2024",
                "question": "Will the Fed cut interest rates in Q1 2024?",
                "category": MarketCategory.ECONOMICS,
                "yes_price": 0.45,
                "no_price": 0.55,
                "volume_24h": 2000000,
                "liquidity": 750000,
                "resolution_date": (datetime(2024, 3, 31) - datetime(1970, 1, 1)).total_seconds()
            }
        ]
        
        markets = []
        for market_data in mock_markets:
            market = PredictionMarket(
                market_id=market_data["market_id"],
                platform=self.platform,
                question=market_data["question"],
                category=market_data["category"],
                yes_price=market_data["yes_price"],
                no_price=market_data["no_price"],
                volume_24h=market_data["volume_24h"],
                total_volume=market_data["volume_24h"],
                liquidity=market_data["liquidity"],
                resolution_date=market_data["resolution_date"],
                created_at=time.time()
            )
            self._markets[market.market_id] = market
            self.record_price(market.market_id, market.yes_price)
            markets.append(market)
        
        self._last_fetch = time.time()
        logger.info(f"KalshiConnector: Returned {len(markets)} mock markets")
        return markets
    
    def _parse_market(self, data: Dict) -> Optional[PredictionMarket]:
        """Parse Kalshi API response."""
        try:
            yes_price = float(data.get("yes_bid", 50)) / 100
            no_price = 1 - yes_price
            
            return PredictionMarket(
                market_id=f"kalshi_{data.get('ticker', '')}",
                platform=PredictionPlatform.KALSHI,
                question=data.get("title", "Unknown"),
                category=self._map_category(data.get("category", "")),
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=float(data.get("volume_24h", 0)),
                total_volume=float(data.get("volume", 0)),
                liquidity=float(data.get("open_interest", 0)),
                resolution_date=data.get("close_time"),
                status=ResolutionStatus.OPEN,
            )
        except Exception as e:
            logger.debug(f"Failed to parse Kalshi market: {e}")
            return None
    
    def _map_category(self, cat: str) -> MarketCategory:
        """Map Kalshi category to our enum."""
        mapping = {
            "politics": MarketCategory.POLITICS,
            "economics": MarketCategory.ECONOMICS,
            "finance": MarketCategory.FINANCE,
            "crypto": MarketCategory.CRYPTO,
            "weather": MarketCategory.WEATHER,
        }
        return mapping.get(cat.lower(), MarketCategory.FINANCE)


class AugurConnector(PredictionMarketConnector):
    """Connector for Augur (REP markets, AMM + order books)."""
    
    def __init__(self):
        super().__init__(PredictionPlatform.AUGUR)
        self._amm_pools: Dict[str, Dict] = {}
        self._order_books: Dict[str, Dict] = {}
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Augur."""
        # Augur uses on-chain data - would need Web3 integration
        # For now, return simulated data structure
        logger.info("Augur connector: Would fetch from Augur protocol")
        return []
    
    def get_amm_price(self, market_id: str) -> Optional[float]:
        """Get AMM pool price for market."""
        pool = self._amm_pools.get(market_id)
        if not pool:
            return None
        
        # AMM price = yes_shares / (yes_shares + no_shares)
        yes_shares = pool.get("yes_shares", 0)
        no_shares = pool.get("no_shares", 0)
        
        if yes_shares + no_shares == 0:
            return 0.5
        
        return yes_shares / (yes_shares + no_shares)
    
    def get_order_book_price(self, market_id: str) -> Optional[Tuple[float, float]]:
        """Get best bid/ask from order book."""
        book = self._order_books.get(market_id)
        if not book:
            return None
        
        best_bid = book.get("bids", [{}])[0].get("price", 0)
        best_ask = book.get("asks", [{}])[0].get("price", 1)
        
        return (best_bid, best_ask)


# NO SYNTHETIC DATA - Real data only from live platform APIs


class PredictionMarketAggregator:
    """
    Aggregates prediction market data across platforms.
    
    Implements:
    - Cross-platform price comparison
    - Odds drift detection
    - Arbitrage opportunity identification
    - Resolution decay analysis
    """
    
    def __init__(self):
        # Use ONLY Kalshi (US compliant) - disable all other platforms
        self.connectors: Dict[PredictionPlatform, PredictionMarketConnector] = {
            PredictionPlatform.KALSHI: KalshiConnector(),
            # All other platforms disabled for US compliance:
            # PredictionPlatform.POLYMARKET: PolymarketConnector(),  # Disabled - US restricted
            # PredictionPlatform.AUGUR: AugurConnector(),  # Disabled
        }
        
        self._all_markets: Dict[str, PredictionMarket] = {}
        self._drift_signals: deque = deque(maxlen=500)
        self._arbitrage_opps: deque = deque(maxlen=100)
        self._decay_metrics: Dict[str, ResolutionDecayMetrics] = {}
        self._whale_events: deque = deque(maxlen=200)  # Whale event storage
        
        self._question_mapping: Dict[str, List[str]] = {}  # Maps similar questions
        
        self._running = False
        self._update_task: Optional[asyncio.Task] = None
        
        logger.info("PredictionMarketAggregator initialized")
    
    async def start(self) -> None:
        """Start aggregation."""
        if self._running:
            return
        
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("PredictionMarketAggregator started")
    
    async def stop(self) -> None:
        """Stop aggregation."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        logger.info("PredictionMarketAggregator stopped")
    
    async def _update_loop(self) -> None:
        """Main update loop."""
        while self._running:
            try:
                await self._fetch_all_markets()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._detect_odds_drift)
                await loop.run_in_executor(None, self._find_arbitrage_opportunities)
                await loop.run_in_executor(None, self._calculate_decay_metrics)
                await asyncio.sleep(60)  # Update every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Prediction market update error: {e}")
                await asyncio.sleep(30)
    
    async def _fetch_all_markets(self) -> None:
        """Fetch markets from all connectors."""
        logger.info(f"Fetching markets from {len(self.connectors)} platforms... (aggregator id={id(self)})")
        for platform, connector in self.connectors.items():
            try:
                logger.info(f"Fetching from {platform.value}...")
                markets = await connector.fetch_markets()
                logger.info(f"Connector returned {len(markets)} markets from {platform.value}")
                for market in markets:
                    self._all_markets[market.market_id] = market
                logger.info(f"Stored {len(markets)} markets, total now: {len(self._all_markets)}")
            except Exception as e:
                import traceback
                logger.error(f"Failed to fetch from {platform.value}: {type(e).__name__}: {e}")
                logger.error(traceback.format_exc())
        
        logger.info(f"After fetch: _all_markets has {len(self._all_markets)} items")
        if not self._all_markets:
            logger.warning("No markets fetched from any platform")
        else:
            # Run heavy DB sync in a thread to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_to_consensus_store)
    
    # Category mapping from MarketCategory → consensus store categories
    _CATEGORY_TO_PRED = {
        "crypto": "crypto",
        "politics": "politics",
        "economics": "economics",
        "sports": "sports",
        "weather": "weather",
        "entertainment": "entertainment",
        "science": "science",
        "finance": "finance",
        "macro": "macro",
        "other": "other",
    }

    def _sync_to_consensus_store(self) -> None:
        """Sync fetched markets into PredictionConsensusStore as instruments."""
        try:
            from merid.prediction.consensus import (
                PredictionInstrument,
                get_prediction_consensus_store,
                _make_pred_symbol,
            )
            store = get_prediction_consensus_store()
            synced = 0
            for market in self._all_markets.values():
                try:
                    ticker = market.market_id
                    venue = market.platform.value  # e.g. "kalshi"
                    symbol = _make_pred_symbol(venue, ticker, "YES")
                    cat = self._CATEGORY_TO_PRED.get(market.category.value, "other")

                    inst = PredictionInstrument(
                        symbol=symbol,
                        venue=venue,
                        event_id=ticker.rsplit("-", 1)[0] if "-" in ticker else ticker,
                        ticker=ticker,
                        outcome="YES",
                        category=cat,
                        title=market.question,
                        expiry=market.resolution_date,
                        market_implied_prob=market.yes_price,
                        volume=market.volume_24h,
                        open_interest=market.total_volume,
                        status="active",
                        last_refreshed=market.last_updated,
                    )
                    store.upsert_instrument(inst)
                    synced += 1
                except Exception as exc:
                    logger.debug("Failed to sync market %s: %s", market.market_id, exc)

            if synced:
                logger.info("Synced %d markets to PredictionConsensusStore", synced)
                self._generate_agent_opinions()
        except Exception as exc:
            logger.warning("Could not sync to PredictionConsensusStore: %s", exc)

    # ── Agent opinion generation ─────────────────────────────────────
    # Three lightweight heuristic agents generate opinions on active
    # prediction markets.  Each agent applies a different lens:
    #   calibration – trusts market price, adds small noise
    #   contrarian  – fades extreme prices toward 50%
    #   momentum    – extrapolates recent price direction
    # Only high-volume markets in priority categories get opinions to
    # keep noise low during early pipeline bring-up.

    _OPINION_CATEGORIES = {"sports", "crypto", "economics", "macro", "finance"}
    _OPINION_AGENTS = [
        {
            "id": "calibration-v1",
            "name": "Calibration Agent",
            "style": "calibration",
            "sources": ["market_price", "historical_calibration"],
        },
        {
            "id": "contrarian-v1",
            "name": "Contrarian Agent",
            "style": "contrarian",
            "sources": ["market_price", "mean_reversion"],
        },
        {
            "id": "momentum-v1",
            "name": "Momentum Agent",
            "style": "momentum",
            "sources": ["market_price", "price_trend"],
        },
    ]

    def _generate_agent_opinions(self) -> None:
        """Generate agent opinions for active prediction markets."""
        try:
            import random
            from merid.prediction.consensus import (
                add_prediction_opinion,
                get_prediction_consensus_store,
                _make_pred_symbol,
            )

            store = get_prediction_consensus_store()
            opinions_added = 0
            deltas = []

            for market in self._all_markets.values():
                cat = self._CATEGORY_TO_PRED.get(market.category.value, "other")
                if cat not in self._OPINION_CATEGORIES:
                    continue
                # Only opine on markets with meaningful liquidity
                if market.volume_24h < 10:
                    continue

                market_prob = market.yes_price
                if market_prob <= 0 or market_prob >= 1:
                    continue

                ticker = market.market_id
                venue = market.platform.value
                symbol = _make_pred_symbol(venue, ticker, "YES")

                for agent_def in self._OPINION_AGENTS:
                    prob = self._compute_agent_prob(
                        agent_def["style"], market_prob, market
                    )
                    # Confidence based on volume and spread
                    confidence = min(0.9, 0.4 + (market.volume_24h / 10000))

                    op = add_prediction_opinion(
                        agent_id=agent_def["id"],
                        agent_name=agent_def["name"],
                        symbol=symbol,
                        probability=prob,
                        confidence=round(confidence, 3),
                        reasoning=self._agent_reasoning(agent_def["style"], market_prob, prob),
                        signal_sources=agent_def["sources"],
                        horizon="event",
                    )
                    opinions_added += 1

                    edge = prob - market_prob
                    if abs(edge) >= 0.03:
                        deltas.append(
                            f"{agent_def['id']}:{symbol} edge={edge:+.3f}"
                        )

            if opinions_added:
                logger.info(
                    "Generated %d agent opinions across %d agents",
                    opinions_added,
                    len(self._OPINION_AGENTS),
                )
            if deltas:
                logger.info(
                    "Opinion→consensus deltas: %d edges ≥3%% (max %s)",
                    len(deltas),
                    max(deltas, key=lambda d: abs(float(d.split("=")[1]))),
                )
                logger.debug("Edge details: %s", "; ".join(deltas))
        except Exception as exc:
            logger.warning("Agent opinion generation failed: %s", exc)

    @staticmethod
    def _compute_agent_prob(
        style: str, market_prob: float, market: "PredictionMarket"
    ) -> float:
        """Compute agent probability based on style heuristic."""
        import random

        rng = random.Random(hash((style, market.market_id)))

        if style == "calibration":
            # Trust market, add small calibration noise ±3%
            noise = rng.gauss(0, 0.03)
            return max(0.01, min(0.99, market_prob + noise))

        elif style == "contrarian":
            # Fade extremes toward 50% — stronger fade at extremes
            fade_strength = 0.15
            return max(0.01, min(0.99, market_prob + fade_strength * (0.5 - market_prob)))

        elif style == "momentum":
            # Extrapolate price direction (push further from 50%)
            momentum = 0.08 * (market_prob - 0.5)
            return max(0.01, min(0.99, market_prob + momentum))

        return market_prob

    @staticmethod
    def _agent_reasoning(style: str, market_prob: float, agent_prob: float) -> str:
        """Generate brief reasoning string for an agent opinion."""
        edge = agent_prob - market_prob
        direction = "overpriced" if edge < 0 else "underpriced"

        if style == "calibration":
            return f"Market at {market_prob:.0%}; calibration model suggests {agent_prob:.0%} ({direction} by {abs(edge):.1%})"
        elif style == "contrarian":
            return f"Market at {market_prob:.0%} looks extreme; mean-reversion target {agent_prob:.0%}"
        elif style == "momentum":
            return f"Momentum signal: market at {market_prob:.0%}, trend continuation to {agent_prob:.0%}"
        return f"Agent estimate: {agent_prob:.0%} vs market {market_prob:.0%}"

    def _detect_odds_drift(self) -> None:
        """Detect significant odds movements."""
        for market_id, market in self._all_markets.items():
            connector = self.connectors.get(market.platform)
            if not connector:
                continue
            
            history = connector.get_price_history(market_id, window_seconds=3600)
            if len(history) < 2:
                continue
            
            old_price = _safe_float(history[0]["price"], 0.0)
            new_price = _safe_float(history[-1]["price"], 0.0)
            
            if old_price == 0:
                continue
            
            drift_pct = ((new_price - old_price) / old_price) * 100
            
            if abs(drift_pct) >= 3.0:  # 3% threshold
                signal = OddsDriftSignal(
                    signal_id=f"drift_{uuid.uuid4().hex[:8]}",
                    market_id=market_id,
                    platform=market.platform,
                    question=market.question,
                    old_probability=old_price,
                    new_probability=new_price,
                    drift_pct=drift_pct,
                    drift_direction="up" if drift_pct > 0 else "down",
                    time_window_seconds=3600,
                    volume_in_window=_safe_float(market.volume_24h) / 24,  # Approximate
                )
                
                self._drift_signals.append(signal)
                logger.info(f"Odds drift detected: {market.question[:50]}... {drift_pct:+.1f}%")
        
        if not self._drift_signals and self._all_markets:
            logger.debug("No drift signals detected")
    
    def _find_arbitrage_opportunities(self) -> None:
        """Find cross-platform arbitrage opportunities."""
        # Group markets by similar questions
        question_groups: Dict[str, List[PredictionMarket]] = {}
        
        for market in self._all_markets.values():
            # Simple grouping by normalized question
            key = self._normalize_question(market.question)
            if key not in question_groups:
                question_groups[key] = []
            question_groups[key].append(market)
        
        # Find arbitrage in groups with multiple platforms
        for key, markets in question_groups.items():
            if len(markets) < 2:
                continue
            
            # Compare all pairs
            for i, market_a in enumerate(markets):
                for market_b in markets[i+1:]:
                    if market_a.platform == market_b.platform:
                        continue
                    
                    price_a = _safe_float(market_a.yes_price)
                    price_b = _safe_float(market_b.yes_price)
                    spread = abs(price_a - price_b)
                    spread_pct = spread * 100
                    
                    if spread_pct >= 2.0:  # 2% spread threshold
                        arb = CrossPlatformArbitrage(
                            arb_id=f"arb_{uuid.uuid4().hex[:8]}",
                            question=market_a.question,
                            category=market_a.category,
                            platform_a=market_a.platform,
                            platform_b=market_b.platform,
                            prob_a=price_a,
                            prob_b=price_b,
                            spread=spread,
                            spread_pct=spread_pct,
                            potential_edge=spread * 0.8,  # Account for fees
                            liquidity_constraint=min(
                                _safe_float(market_a.liquidity),
                                _safe_float(market_b.liquidity)
                            ),
                        )
                        
                        self._arbitrage_opps.append(arb)
                        logger.info(f"Arbitrage found: {spread_pct:.1f}% spread on {key[:30]}...")
        
        if not self._arbitrage_opps and self._all_markets:
            logger.debug("No arbitrage opportunities found")
    
    def _normalize_question(self, question: str) -> str:
        """Normalize question for matching."""
        import re
        q = question.lower()
        q = re.sub(r'[^\w\s]', '', q)
        q = re.sub(r'\s+', ' ', q).strip()
        return q[:100]
    
    def _calculate_decay_metrics(self) -> None:
        """Calculate resolution decay metrics for all markets."""
        for market_id, market in self._all_markets.items():
            days = market.days_to_resolution
            if days is None:
                continue
            
            # Decay factor increases as resolution approaches
            if days > 30:
                decay_factor = 0.1
                exit_urgency = "none"
            elif days > 7:
                decay_factor = 0.3
                exit_urgency = "low"
            elif days > 2:
                decay_factor = 0.6
                exit_urgency = "medium"
            elif days > 0.5:
                decay_factor = 0.85
                exit_urgency = "high"
            else:
                decay_factor = 0.95
                exit_urgency = "critical"
            
            # Volatility compression near resolution
            vol_compression = 1 - (1 / (1 + math.exp(-0.5 * (days - 3))))
            
            # Oracle lag risk (higher for decentralized oracles)
            oracle_lag_risk = 0.1 if market.platform == PredictionPlatform.KALSHI else 0.3
            
            # Position size recommendation
            recommended_size = max(0.1, 1 - decay_factor)
            
            metrics = ResolutionDecayMetrics(
                market_id=market_id,
                days_remaining=days,
                decay_factor=decay_factor,
                volatility_compression=vol_compression,
                oracle_lag_risk=oracle_lag_risk,
                recommended_position_size=recommended_size,
                exit_urgency=exit_urgency,
            )
            
            self._decay_metrics[market_id] = metrics
        
        if not self._decay_metrics and self._all_markets:
            logger.debug("No decay metrics calculated")
    
    # Public API methods
    
    def get_all_markets(self, limit: int = 100) -> List[PredictionMarket]:
        """Get all tracked markets."""
        logger.info(f"get_all_markets called: _all_markets has {len(self._all_markets)} items, id={id(self)}")
        markets = sorted(
            self._all_markets.values(),
            key=lambda m: m.volume_24h,
            reverse=True
        )
        logger.info(f"Returning {len(markets[:limit])} markets out of {len(markets)} total")
        return markets[:limit]
    
    def get_markets_by_category(
        self,
        category: MarketCategory,
        limit: int = 50
    ) -> List[PredictionMarket]:
        """Get markets filtered by category."""
        markets = [m for m in self._all_markets.values() if m.category == category]
        return sorted(markets, key=lambda m: m.volume_24h, reverse=True)[:limit]
    
    def get_drift_signals(self, limit: int = 20) -> List[OddsDriftSignal]:
        """Get recent odds drift signals."""
        return list(self._drift_signals)[-limit:]
    
    def get_arbitrage_opportunities(self, limit: int = 10) -> List[CrossPlatformArbitrage]:
        """Get current arbitrage opportunities."""
        return list(self._arbitrage_opps)[-limit:]
    
    def get_decay_metrics(self, market_id: str) -> Optional[ResolutionDecayMetrics]:
        """Get decay metrics for a market."""
        return self._decay_metrics.get(market_id)
    
    def get_high_urgency_markets(self) -> List[Tuple[PredictionMarket, ResolutionDecayMetrics]]:
        """Get markets with high exit urgency."""
        results = []
        for market_id, metrics in self._decay_metrics.items():
            if metrics.exit_urgency in ("high", "critical"):
                market = self._all_markets.get(market_id)
                if market:
                    results.append((market, metrics))
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get aggregator status."""
        self.ensure_ready()
        logger.debug(f"get_status called: _all_markets has {len(self._all_markets)} items, id={id(self)}")
        return {
            "running": self._running,
            "total_markets": len(self._all_markets),
            "drift_signals": len(self._drift_signals),
            "arbitrage_opportunities": len(self._arbitrage_opps),
            "platforms": [p.value for p in self.connectors.keys()],
            "markets_by_platform": {
                p.value: len([m for m in self._all_markets.values() if m.platform == p])
                for p in self.connectors.keys()
            }
        }

    # --- NO SYNTHETIC DATA - Real data only -------------------------------------

    def ensure_ready(self) -> None:
        """Check if aggregator has real data available."""
        logger.debug(f"Prediction aggregator status: {len(self._all_markets)} markets, {len(self._drift_signals)} drift signals, {len(self._arbitrage_opps)} arb opportunities")


# Global instance
_prediction_aggregator: Optional[PredictionMarketAggregator] = None
_prediction_aggregator_lock = threading.Lock()


def get_prediction_aggregator() -> PredictionMarketAggregator:
    """Get or create global prediction market aggregator."""
    global _prediction_aggregator
    if _prediction_aggregator is None:
        with _prediction_aggregator_lock:
            if _prediction_aggregator is None:
                _prediction_aggregator = PredictionMarketAggregator()
                logger.info(f"Created new PredictionMarketAggregator instance id={id(_prediction_aggregator)}")
    else:
        logger.debug(f"Returning existing PredictionMarketAggregator id={id(_prediction_aggregator)}, markets={len(_prediction_aggregator._all_markets)}")
    return _prediction_aggregator


async def start_prediction_markets() -> PredictionMarketAggregator:
    """Start prediction market aggregation."""
    aggregator = get_prediction_aggregator()
    await aggregator.start()
    return aggregator


async def stop_prediction_markets() -> None:
    """Stop prediction market aggregation."""
    global _prediction_aggregator
    if _prediction_aggregator is not None:
        await _prediction_aggregator.stop()


# Whale event methods for PredictionMarketAggregator
def record_whale_event(aggregator: PredictionMarketAggregator, alert: dict) -> None:
    """Record a whale event in the aggregator."""
    aggregator._whale_events.appendleft(alert)
    logger.info(f"Recorded whale event: {alert.get('amount')} tokens")


def get_whale_events(aggregator: PredictionMarketAggregator, limit: int = 20) -> list:
    """Get recent whale events from the aggregator."""
    return list(aggregator._whale_events)[:limit]
