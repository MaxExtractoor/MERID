"""
Real Prediction Markets - Live Data Implementation

Replaces mock data with actual US-compliant prediction market APIs.
Focuses on real-time data fetching, drift detection, and arbitrage.
"""

import asyncio
import aiohttp
import time
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import uuid
from collections import deque

from utils.logger import get_logger

logger = get_logger("monitoring.real_prediction_markets")
STRICT_CONNECTOR_ERRORS = os.getenv("PREDICTION_CONNECTOR_STRICT_ERRORS", "false").lower() in {"1", "true", "yes"}


class PredictionPlatform(Enum):
    """Supported prediction market platforms."""
    POLYMARKET = "polymarket"
    AUGUR = "augur"
    MANIFOLD = "manifold"


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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.market_id,
            "question": self.question,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "category": self.category.value,
            "volume": self.volume_24h,
            "liquidity": self.liquidity,
            "platform": self.platform.value,
            "resolution_date": self.resolution_date,
            "created_at": self.created_at,
            "last_updated": self.last_updated
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
    drift_pct: float
    drift_direction: str  # "up" or "down"
    time_window_seconds: int
    volume_in_window: float
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "signal_id": self.signal_id,
            "market_id": self.market_id,
            "platform": self.platform.value,
            "question": self.question,
            "old_probability": self.old_probability,
            "new_probability": self.new_probability,
            "drift_pct": self.drift_pct,
            "drift_direction": self.drift_direction,
            "time_window_seconds": self.time_window_seconds,
            "volume_in_window": self.volume_in_window,
            "timestamp": self.timestamp
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
    spread: float
    spread_pct: float
    potential_edge: float
    liquidity_constraint: float
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "arb_id": self.arb_id,
            "question": self.question,
            "category": self.category.value,
            "platform_a": self.platform_a.value,
            "platform_b": self.platform_b.value,
            "prob_a": self.prob_a,
            "prob_b": self.prob_b,
            "spread": self.spread,
            "spread_pct": self.spread_pct,
            "potential_edge": self.potential_edge,
            "liquidity_constraint": self.liquidity_constraint,
            "timestamp": self.timestamp
        }


class RealPredictionMarketConnector:
    """Base connector for real prediction market platforms."""
    
    def __init__(self, platform: PredictionPlatform):
        self.platform = platform
        self.session = None
        self._markets: Dict[str, PredictionMarket] = {}
        self._price_history: Dict[str, deque] = {}
        self._last_fetch = 0.0
        self._fetch_interval = 60.0  # 1 minute
        self._last_issue_log = 0.0
        self._issue_log_interval = 60.0

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'MERID-Prediction-Aggregator/1.0'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from platform. Override in subclasses."""
        raise NotImplementedError
    
    async def fetch_market(self, market_id: str) -> Optional[PredictionMarket]:
        """Fetch single market by ID."""
        markets = await self.fetch_markets()
        return next((m for m in markets if m.market_id == market_id), None)
    
    def get_cached_markets(self) -> List[PredictionMarket]:
        """Get cached markets."""
        return list(self._markets.values())
    
    def get_price_history(self, market_id: str, window_seconds: int = 3600) -> List[Dict[str, Any]]:
        """Get price history for a market."""
        if market_id not in self._price_history:
            return []
        
        cutoff_time = time.time() - window_seconds
        return [
            {"price": price, "timestamp": ts}
            for price, ts in self._price_history[market_id]
            if ts >= cutoff_time
        ]
    
    def _update_price_history(self, market: PredictionMarket):
        """Update price history for a market."""
        if market.market_id not in self._price_history:
            self._price_history[market.market_id] = deque(maxlen=1000)
        
        self._price_history[market.market_id].append((market.yes_price, time.time()))

    def _log_connector_issue(self, message: str) -> None:
        """Rate-limit expected connector issues and gate severity via config."""
        now = time.time()
        if now - self._last_issue_log < self._issue_log_interval:
            return

        if STRICT_CONNECTOR_ERRORS:
            logger.error(message)
        else:
            logger.warning(message)

        self._last_issue_log = now


class RealPolymarketConnector(RealPredictionMarketConnector):
    """Real connector for Polymarket using public API."""
    
    def __init__(self):
        super().__init__(PredictionPlatform.POLYMARKET)
        self.api_base = "https://gamma-api.polymarket.com"
        self.is_available = True  # Track availability
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Polymarket API."""
        try:
            if not self.session or not self.is_available:
                logger.warning("Polymarket connector not available, skipping fetch")
                return []
            
            # Fetch active markets
            url = f"{self.api_base}/markets"
            params = {
                "active": "true",
                "limit": 100  # Limit for performance
            }
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Polymarket API error: {response.status}")
=======
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    self._log_connector_issue(f"Polymarket API error: {response.status}")
                    self.is_available = False
                    return []
                
                data = await response.json()
                
                # Check if data is stale (old dates)
                if data and len(data) > 0:
                    first_market = data[0]
                    created_at = first_market.get("createdAt", "")
                    if "2020" in created_at or "2021" in created_at:
=======
                        self._log_connector_issue("Polymarket API returning stale data (2020-2021), marking as unavailable")
                        self.is_available = False
                        return []
                
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                markets = []
                
                for market_data in data:
                    try:
                        # Parse market data
                        market = PredictionMarket(
                            market_id=str(market_data.get("id", "")),
                            platform=self.platform,
                            question=market_data.get("question", ""),
                            category=self._infer_category(market_data.get("question", "")),
=======
                            yes_price=float(market_data.get("outcomePrices", "[0, 0]")[1:-1].split(",")[0].strip('"')) / 100,
                            no_price=float(market_data.get("outcomePrices", "[0, 0]")[1:-1].split(",")[1].strip('"')) / 100,
                            volume_24h=float(market_data.get("volume24hr", 0)),
                            total_volume=float(market_data.get("volumeNum", 0)),
                            liquidity=float(market_data.get("liquidityNum", 0)),
                            resolution_date=market_data.get("endDate"),
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                            created_at=market_data.get("createdAt", time.time()),
                            last_updated=time.time()
                        )
                        
=======
                        # Skip markets with zero prices (stale data)
                        if market.yes_price == 0 and market.no_price == 0:
                            continue
                        
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                        markets.append(market)
                        self._markets[market.market_id] = market
                        self._update_price_history(market)
                        
                    except (ValueError, KeyError, IndexError) as e:
=======
                    except (ValueError, KeyError, IndexError) as e:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                        logger.warning(f"Error parsing Polymarket market: {e}")
                        continue
                
                self._last_fetch = time.time()
                logger.info(f"Fetched {len(markets)} markets from Polymarket")
=======
                self.is_available = True
                return markets
                
        except asyncio.TimeoutError:
=======
            self._log_connector_issue("Polymarket fetch timeout - marking as unavailable")
            self.is_available = False
            return []
        except Exception as e:
            self._log_connector_issue(f"Polymarket fetch error: {e}")
            self.is_available = False
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
            return []
    
    def _infer_category(self, question: str) -> MarketCategory:
        """Infer category from question text."""
        question_lower = question.lower()
        
        if any(word in question_lower for word in ["bitcoin", "ethereum", "crypto", "btc", "eth"]):
            return MarketCategory.CRYPTO
        elif any(word in question_lower for word in ["election", "president", "politics", "vote"]):
            return MarketCategory.POLITICS
        elif any(word in question_lower for word in ["super bowl", "nfl", "nba", "sports", "game"]):
            return MarketCategory.SPORTS
        elif any(word in question_lower for word in ["economy", "inflation", "fed", "interest"]):
            return MarketCategory.ECONOMICS
        elif any(word in question_lower for word in ["weather", "temperature", "rain"]):
            return MarketCategory.WEATHER
        else:
            return MarketCategory.ENTERTAINMENT


class RealAugurConnector(RealPredictionMarketConnector):
    """Real connector for Augur using public API."""
    
    def __init__(self):
        super().__init__(PredictionPlatform.AUGUR)
        self.api_base = "https://api.augur.net"
        self.is_available = True  # Track availability
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Augur API."""
        try:
            if not self.session or not self.is_available:
                logger.warning("Augur connector not available, skipping fetch")
=======
            if not self.session or not self.is_available:
                logger.warning("Augur connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            if not self.session or not self.is_available:
                logger.warning("Augur connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            if not self.session or not self.is_available:
                self._log_connector_issue("Augur connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                return []
            
            # Fetch active markets
            url = f"{self.api_base}/markets"
            params = {
                "universe": "1",  # Main universe
                "state": "open",
                "limit": 50
            }
            
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Augur API error: {response.status}")
                    self.is_available = False  # Mark as unavailable
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    self._log_connector_issue(f"Augur API error: {response.status}")
                    self.is_available = False  # Mark as unavailable
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                    return []
                
                data = await response.json()
                markets = []
                
                for market_data in data.get("data", []):
                    try:
                        # Parse market data
                        market = PredictionMarket(
                            market_id=market_data.get("id", ""),
                            platform=self.platform,
                            question=market_data.get("description", ""),
                            category=self._infer_category(market_data.get("description", "")),
                            yes_price=float(market_data.get("bestBuyProbability", 0)),
                            no_price=1.0 - float(market_data.get("bestBuyProbability", 0)),
                            volume_24h=float(market_data.get("volume24h", 0)),
                            total_volume=float(market_data.get("volume", 0)),
                            liquidity=float(market_data.get("liquidity", 0)),
                            resolution_date=market_data.get("finalizationTime"),
                            created_at=market_data.get("creationTime", time.time()),
                            last_updated=time.time()
                        )
                        
                        markets.append(market)
                        self._markets[market.market_id] = market
                        self._update_price_history(market)
                        
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Error parsing Augur market: {e}")
                        continue
                
                self._last_fetch = time.time()
                logger.info(f"Fetched {len(markets)} markets from Augur")
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                self.is_available = True  # Mark as available
                return markets
                
        except asyncio.TimeoutError:
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            self._log_connector_issue("Augur fetch timeout - marking as unavailable")
            self.is_available = False
            return []
        except Exception as e:
            self._log_connector_issue(f"Augur fetch error: {e}")
            self.is_available = False
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
            return []
    
    def _infer_category(self, question: str) -> MarketCategory:
        """Infer category from question text."""
        question_lower = question.lower()
        
        if any(word in question_lower for word in ["bitcoin", "ethereum", "crypto", "btc", "eth"]):
            return MarketCategory.CRYPTO
        elif any(word in question_lower for word in ["election", "president", "politics", "vote"]):
            return MarketCategory.POLITICS
        elif any(word in question_lower for word in ["super bowl", "nfl", "nba", "sports", "game"]):
            return MarketCategory.SPORTS
        else:
            return MarketCategory.ENTERTAINMENT


class RealManifoldConnector(RealPredictionMarketConnector):
    """Real connector for Manifold using public API."""
    
    def __init__(self):
        super().__init__(PredictionPlatform.MANIFOLD)
        self.api_base = "https://api.manifold.markets"
        self.is_available = True  # Track availability
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
        self.is_available = True  # Track availability
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
    
    async def fetch_markets(self, category: Optional[MarketCategory] = None) -> List[PredictionMarket]:
        """Fetch markets from Manifold API."""
        try:
            if not self.session or not self.is_available:
                logger.warning("Manifold connector not available, skipping fetch")
=======
            if not self.session or not self.is_available:
                logger.warning("Manifold connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            if not self.session or not self.is_available:
                logger.warning("Manifold connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            if not self.session or not self.is_available:
                self._log_connector_issue("Manifold connector not available, skipping fetch")
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                return []
            
            # Fetch active markets
            url = f"{self.api_base}/markets"
            params = {
                "limit": 50,
                "count": "yes"  # Only markets with bets
            }
            
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Manifold API error: {response.status}")
                    self.is_available = False  # Mark as unavailable
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    self._log_connector_issue(f"Manifold API error: {response.status}")
                    self.is_available = False  # Mark as unavailable
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                    return []
                
                data = await response.json()
                markets = []
                
                for market_data in data:
                    try:
                        # Parse market data
                        probability = float(market_data.get("probability", 0))
                        
                        market = PredictionMarket(
                            market_id=market_data.get("id", ""),
                            platform=self.platform,
                            question=market_data.get("question", ""),
                            category=self._infer_category(market_data.get("question", "")),
                            yes_price=probability,
                            no_price=1.0 - probability,
                            volume_24h=float(market_data.get("volume24h", 0)),
                            total_volume=float(market_data.get("volume", 0)),
                            liquidity=float(market_data.get("liquidity", 0)),
                            resolution_date=market_data.get("closeTime"),
                            created_at=market_data.get("creationTime", time.time()),
                            last_updated=time.time()
                        )
                        
                        markets.append(market)
                        self._markets[market.market_id] = market
                        self._update_price_history(market)
                        
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Error parsing Manifold market: {e}")
                        continue
                
                self._last_fetch = time.time()
                logger.info(f"Fetched {len(markets)} markets from Manifold")
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                self.is_available = True  # Mark as available
                return markets
                
        except asyncio.TimeoutError:
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
            self._log_connector_issue("Manifold fetch timeout - marking as unavailable")
            self.is_available = False
            return []
        except Exception as e:
            self._log_connector_issue(f"Manifold fetch error: {e}")
            self.is_available = False
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
            return []
    
    def _infer_category(self, question: str) -> MarketCategory:
        """Infer category from question text."""
        question_lower = question.lower()
        
        if any(word in question_lower for word in ["bitcoin", "ethereum", "crypto", "btc", "eth"]):
            return MarketCategory.CRYPTO
        elif any(word in question_lower for word in ["election", "president", "politics", "vote"]):
            return MarketCategory.POLITICS
        elif any(word in question_lower for word in ["super bowl", "nfl", "nba", "sports", "game"]):
            return MarketCategory.SPORTS
        else:
            return MarketCategory.ENTERTAINMENT


class RealPredictionMarketAggregator:
    """
    Real aggregator for prediction markets with live data.
    
    Features:
    - Real-time data fetching from multiple platforms
    - Odds drift detection
    - Cross-platform arbitrage detection
    - No mock data - only real API data
    """
    
    def __init__(self):
        self.connectors: Dict[PredictionPlatform, RealPredictionMarketConnector] = {}
        self._all_markets: Dict[str, PredictionMarket] = {}
        self._drift_signals: deque = deque(maxlen=500)
        self._arbitrage_opps: deque = deque(maxlen=100)
        
        self._running = False
        self._update_task: Optional[asyncio.Task] = None
        
        logger.info("RealPredictionMarketAggregator initialized")
    
    async def start(self) -> None:
        """Start aggregation with real connectors."""
        if self._running:
            return
        
        # Initialize real connectors
        self.connectors = {
            PredictionPlatform.POLYMARKET: await RealPolymarketConnector().__aenter__(),
            PredictionPlatform.AUGUR: await RealAugurConnector().__aenter__(),
            PredictionPlatform.MANIFOLD: await RealManifoldConnector().__aenter__(),
        }
        
        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("RealPredictionMarketAggregator started with real data sources")
    
    async def stop(self) -> None:
        """Stop aggregation."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        
        # Close connectors
        for connector in self.connectors.values():
            await connector.__aexit__(None, None, None)
        
        logger.info("RealPredictionMarketAggregator stopped")
    
    async def _update_loop(self) -> None:
        """Main update loop with real data."""
        while self._running:
            try:
                await self._fetch_all_markets()
                self._detect_odds_drift()
                self._find_arbitrage_opportunities()
                await asyncio.sleep(30)  # Update every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Update loop error: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    
    async def _fetch_all_markets(self) -> None:
        """Fetch markets from all available connectors."""
        total_markets = 0
        successful_connectors = 0
=======
        """Fetch markets from all available connectors."""
        total_markets = 0
        successful_connectors = 0
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
        """Fetch markets from all available connectors."""
        total_markets = 0
        successful_connectors = 0
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
        
        for platform, connector in self.connectors.items():
            try:
                markets = await connector.fetch_markets()
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
                if markets:
                    self._all_markets.update({m.market_id: m for m in markets})
                    total_markets += len(markets)
                    successful_connectors += 1
                    logger.info(f"Successfully fetched {len(markets)} markets from {platform.value}")
                else:
                    logger.warning(f"No markets fetched from {platform.value} (connector may be unavailable)")
            except Exception as e:
                logger.error(f"Failed to fetch from {platform.value}: {e}")
        
        logger.info(f"Total markets fetched: {total_markets} from {successful_connectors}/{len(self.connectors)} connectors")
        self._last_fetch = time.time()
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\monitoring\real_prediction_markets.py
    
    def _detect_odds_drift(self) -> None:
        """Detect significant odds movements."""
        for market_id, market in self._all_markets.items():
            connector = self.connectors.get(market.platform)
            if not connector:
                continue
            
            history = connector.get_price_history(market_id, window_seconds=1800)  # 30 minutes
            if len(history) < 2:
                continue
            
            old_price = history[0]["price"]
            new_price = history[-1]["price"]
            
            if old_price == 0:
                continue
            
            drift_pct = ((new_price - old_price) / old_price) * 100
            
            if abs(drift_pct) >= 2.0:  # 2% threshold
                signal = OddsDriftSignal(
                    signal_id=f"drift_{uuid.uuid4().hex[:8]}",
                    market_id=market_id,
                    platform=market.platform,
                    question=market.question,
                    old_probability=old_price,
                    new_probability=new_price,
                    drift_pct=drift_pct,
                    drift_direction="up" if drift_pct > 0 else "down",
                    time_window_seconds=1800,
                    volume_in_window=market.volume_24h / 48,  # Approximate
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
                    
                    price_a = market_a.yes_price
                    price_b = market_b.yes_price
                    spread = abs(price_a - price_b)
                    spread_pct = spread * 100
                    
                    if spread_pct >= 1.0:  # 1% spread threshold
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
                            liquidity_constraint=min(market_a.liquidity, market_b.liquidity),
                        )
                        
                        self._arbitrage_opps.append(arb)
                        logger.info(f"Arbitrage found: {spread_pct:.1f}% spread on {key[:30]}...")
        
        if not self._arbitrage_opps and self._all_markets:
            logger.debug("No arbitrage opportunities found")
    
    def _normalize_question(self, question: str) -> str:
        """Normalize question for matching."""
        import re
        q = question.lower()
        # Remove common words and punctuation
        q = re.sub(r'[^\w\s]', '', q)
        q = re.sub(r'\b(the|will|what|when|how|who|where|why)\b', '', q)
        q = ' '.join(q.split())
        return q
    
    def get_all_markets(self) -> List[PredictionMarket]:
        """Get all markets."""
        return list(self._all_markets.values())
    
    def get_markets_by_category(self, category: MarketCategory) -> List[PredictionMarket]:
        """Get markets by category."""
        return [m for m in self._all_markets.values() if m.category == category]
    
    def get_drift_signals(self, limit: int = 20) -> List[OddsDriftSignal]:
        """Get recent drift signals."""
        return list(self._drift_signals)[-limit:]
    
    def get_arbitrage_opportunities(self, limit: int = 20) -> List[CrossPlatformArbitrage]:
        """Get recent arbitrage opportunities."""
        return list(self._arbitrage_opps)[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """Get aggregator status."""
        return {
            "running": self._running,
            "total_markets": len(self._all_markets),
            "active_platforms": len(self.connectors),
            "drift_signals": len(self._drift_signals),
            "arbitrage_opportunities": len(self._arbitrage_opps),
            "last_update": time.time()
        }


# Global instance
_real_aggregator = None

async def get_real_prediction_aggregator() -> RealPredictionMarketAggregator:
    """Get the global real prediction aggregator instance."""
    global _real_aggregator
    
    if _real_aggregator is None:
        _real_aggregator = RealPredictionMarketAggregator()
        await _real_aggregator.start()
    
    return _real_aggregator


# Testing
async def test_real_prediction_markets():
    """Test the real prediction markets aggregator."""
    aggregator = RealPredictionMarketAggregator()
    
    try:
        await aggregator.start()
        
        # Wait for initial data
        await asyncio.sleep(5)
        
        # Test markets
        markets = aggregator.get_all_markets()
        print(f"Fetched {len(markets)} markets")
        
        # Test drift signals
        drift_signals = aggregator.get_drift_signals()
        print(f"Found {len(drift_signals)} drift signals")
        
        # Test arbitrage opportunities
        arbitrage_opps = aggregator.get_arbitrage_opportunities()
        print(f"Found {len(arbitrage_opps)} arbitrage opportunities")
        
        # Wait for more updates
        await asyncio.sleep(30)
        
        # Check for new signals
        new_drift_signals = aggregator.get_drift_signals()
        print(f"Total drift signals: {len(new_drift_signals)}")
        
    finally:
        await aggregator.stop()


if __name__ == "__main__":
    asyncio.run(test_real_prediction_markets())
