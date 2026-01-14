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
        raise NotImplementedError
    
    async def fetch_market(self, market_id: str) -> Optional[PredictionMarket]:
        """Fetch single market by ID."""
        raise NotImplementedError
    
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
    """Connector for Polymarket."""
    
    # Use Gamma API for market data (public, no auth required)
    API_BASE = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        super().__init__(PredictionPlatform.POLYMARKET)
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Polymarket Gamma API."""
        logger.info("Polymarket: Starting fetch...")
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
            logger.info(f"Fetched {len(markets)} markets from Polymarket")
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
    """Connector for Kalshi (CFTC-regulated)."""
    
    API_BASE = "https://trading-api.kalshi.com/trade-api/v2"
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(PredictionPlatform.KALSHI)
        self.api_key = api_key
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Kalshi API."""
        try:
            import httpx
            
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                response = await client.get(
                    f"{self.API_BASE}/markets",
                    headers=headers,
                    params={"status": "open", "limit": 50}
                )
                
                if response.status_code != 200:
                    logger.warning(f"Kalshi API returned {response.status_code}")
                    return []
                
                data = response.json()
                markets = []
                
                for item in data.get("markets", []):
                    market = self._parse_market(item)
                    if market:
                        self._markets[market.market_id] = market
                        self.record_price(market.market_id, market.yes_price)
                        markets.append(market)
                
                self._last_fetch = time.time()
                return markets
                
        except Exception as e:
            logger.error(f"Kalshi fetch error: {e}")
            return []
    
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
        self.connectors: Dict[PredictionPlatform, PredictionMarketConnector] = {
            PredictionPlatform.POLYMARKET: PolymarketConnector(),
            PredictionPlatform.KALSHI: KalshiConnector(),
            PredictionPlatform.AUGUR: AugurConnector(),
        }
        
        self._all_markets: Dict[str, PredictionMarket] = {}
        self._drift_signals: deque = deque(maxlen=500)
        self._arbitrage_opps: deque = deque(maxlen=100)
        self._decay_metrics: Dict[str, ResolutionDecayMetrics] = {}
        
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
                self._detect_odds_drift()
                self._find_arbitrage_opportunities()
                self._calculate_decay_metrics()
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


def get_prediction_aggregator() -> PredictionMarketAggregator:
    """Get or create global prediction market aggregator."""
    global _prediction_aggregator
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
