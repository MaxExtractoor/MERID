"""
CFGI (Crypto Fear & Greed Index) API Integration

Fetches real-time fear/greed data from the CFGI API for use in
sentiment analysis and risk sizing decisions.

API Documentation: https://cfgi.io

Usage:
    from merid.sentiment.cfgi_client import get_cfgi_client
    
    client = get_cfgi_client()
    fgi = client.get_fear_greed("BTC")  # Returns 0-100
    
    # Or get normalized 0-1
    normalized = client.get_normalized_fg("BTC")
    
    # Update MarketMoodBus
    client.update_mood_bus("BTC")
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
import os
import logging
from enum import Enum

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger(__name__)


class FearGreedRegime(Enum):
    """Fear/Greed index regimes."""
    EXTREME_FEAR = "extreme_fear"  # 0-20
    FEAR = "fear"                   # 21-40
    NEUTRAL = "neutral"             # 41-60
    GREED = "greed"                 # 61-80
    EXTREME_GREED = "extreme_greed" # 81-100


@dataclass
class FearGreedData:
    """CFGI fear/greed data for an asset."""
    asset: str
    fgi: int  # 0-100
    timestamp: datetime
    classification: FearGreedRegime
    
    # Optional detailed metrics if available
    volatility: Optional[float] = None
    market_momentum: Optional[float] = None
    social_sentiment: Optional[float] = None
    dominance: Optional[float] = None
    is_synthetic: bool = False  # True when real API unavailable; UI should warn
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses."""
        return {
            "asset": self.asset,
            "fgi": self.fgi,
            "classification": self.classification.value,
            "regime": self.classification.value,
            "timestamp": self.timestamp.isoformat(),
            "volatility": self.volatility,
            "market_momentum": self.market_momentum,
            "social_sentiment": self.social_sentiment,
            "dominance": self.dominance,
            "is_synthetic": self.is_synthetic,
        }

    def is_extreme(self) -> bool:
        """Check if in extreme fear or greed zone."""
        return self.fgi <= 20 or self.fgi >= 80
    
    def get_contrarian_signal(self) -> str:
        """Get contrarian trading signal based on extremes."""
        if self.fgi <= 20:
            return "bullish_contrarian"  # Extreme fear = buying opportunity
        elif self.fgi >= 80:
            return "bearish_contrarian"  # Extreme greed = selling opportunity
        return "neutral"
    
    def get_risk_multiplier(self) -> float:
        """Get position sizing multiplier based on regime."""
        # Reduce size in extremes, normal in neutral
        if self.fgi <= 20:
            return 0.6  # Extreme fear - be cautious
        elif self.fgi >= 80:
            return 0.6  # Extreme greed - be cautious
        elif self.fgi <= 40:
            return 0.8  # Fear - slightly cautious
        elif self.fgi >= 60:
            return 0.8  # Greed - slightly cautious
        return 1.0  # Neutral - normal sizing


class CFGIClient:
    """
    Client for the CFGI (Crypto Fear & Greed Index) API.
    
    Provides real-time fear/greed data for crypto assets to inform
    sentiment analysis and risk decisions.
    
    Usage:
        client = CFGIClient()
        
        # Get fear/greed for BTC
        data = client.get_fear_greed("BTC")
        print(f"BTC Fear/Greed: {data.fgi}/100 ({data.classification.value})")
        
        # Check if contrarian opportunity
        if data.is_extreme():
            print(f"Contrarian signal: {data.get_contrarian_signal()}")
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, api_key: Optional[str] = None):
        if self._initialized:
            return
        
        self.api_key = api_key or os.getenv("CFGI_API_KEY")
        self.base_url = "https://api.cfgi.io/v1"
        
        # Cache for API responses
        self._cache: Dict[str, FearGreedData] = {}
        self._cache_ttl_seconds = 300  # 5 minute cache
        
        if not self.api_key:
            logger.warning("CFGI_API_KEY not configured - fear/greed data will be synthetic")
        if not requests:
            logger.warning("requests not available - CFGI client disabled")
        
        self._initialized = True
        logger.info("CFGIClient initialized")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get auth headers for CFGI API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def _classify_fgi(self, fgi: int) -> FearGreedRegime:
        """Classify FGI value into regime."""
        if fgi <= 20:
            return FearGreedRegime.EXTREME_FEAR
        elif fgi <= 40:
            return FearGreedRegime.FEAR
        elif fgi <= 60:
            return FearGreedRegime.NEUTRAL
        elif fgi <= 80:
            return FearGreedRegime.GREED
        else:
            return FearGreedRegime.EXTREME_GREED
    
    def get_fear_greed(
        self,
        asset: str,
        use_cache: bool = True,
    ) -> FearGreedData:
        """
        Fetch fear/greed index for an asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            use_cache: Use cached data if fresh
        
        Returns:
            FearGreedData with index value and classification
        """
        cache_key = asset.upper()
        
        # Check cache
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
            if age < self._cache_ttl_seconds:
                logger.debug(f"Using cached CFGI data for {asset}")
                return cached
        
        # Fetch from API if configured
        if self.api_key and requests:
            try:
                resp = requests.get(
                    f"{self.base_url}/fgi",
                    params={"symbol": asset.upper()},
                    headers=self._get_headers(),
                    timeout=10,
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    
                    # Parse response - adjust based on actual API format
                    fgi = int(data.get("fgi", data.get("value", data.get("index", 50))))
                    
                    result = FearGreedData(
                        asset=asset.upper(),
                        fgi=fgi,
                        timestamp=datetime.now(timezone.utc),
                        classification=self._classify_fgi(fgi),
                        volatility=data.get("volatility"),
                        market_momentum=data.get("market_momentum"),
                        social_sentiment=data.get("social_sentiment"),
                        dominance=data.get("dominance"),
                    )
                    
                    self._cache[cache_key] = result
                    logger.info(f"CFGI {asset}: {fgi}/100 ({result.classification.value})")
                    return result
                    
                elif resp.status_code == 401:
                    logger.error("CFGI API unauthorized - check API key")
                elif resp.status_code == 429:
                    logger.warning("CFGI API rate limited")
                else:
                    logger.warning(f"CFGI API error: {resp.status_code}")
                    
            except requests.exceptions.Timeout:
                logger.warning("CFGI API timeout")
            except Exception as exc:
                logger.warning(f"CFGI fetch error: {exc}")
        
        # Fallback: generate synthetic FGI based on time (for testing)
        # In production, you'd want to fail or use alternative source
        logger.debug(f"Using synthetic CFGI data for {asset}")
        
        import math
        # Generate cyclical fear/greed (sin wave 0-100)
        hour_of_day = datetime.now(timezone.utc).hour
        synthetic_fgi = int(50 + 30 * math.sin(hour_of_day * math.pi / 12))
        synthetic_fgi = max(0, min(100, synthetic_fgi))
        
        result = FearGreedData(
            asset=asset.upper(),
            fgi=synthetic_fgi,
            timestamp=datetime.now(timezone.utc),
            classification=self._classify_fgi(synthetic_fgi),
            volatility=None,
            market_momentum=None,
            social_sentiment=None,
            dominance=None,
            is_synthetic=True,
        )
        
        self._cache[cache_key] = result
        return result
    
    def get_normalized_fg(self, asset: str) -> float:
        """
        Get fear/greed normalized to 0-1 range.
        
        Args:
            asset: Asset symbol
        
        Returns:
            Normalized value 0.0-1.0
        """
        data = self.get_fear_greed(asset)
        return data.fgi / 100.0
    
    def get_multi_fg(self, assets: List[str]) -> Dict[str, FearGreedData]:
        """Get fear/greed for multiple assets."""
        return {asset: self.get_fear_greed(asset) for asset in assets}
    
    def update_mood_bus(self, asset: str) -> bool:
        """
        Update MarketMoodBus with fear/greed data.
        
        Args:
            asset: Asset to update
        
        Returns:
            True if successful
        """
        try:
            data = self.get_fear_greed(asset)
            
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            
            bus.update_fear_greed(
                asset=asset,
                fg_index=data.fgi,
                source="cfgi",
            )
            
            logger.debug(f"Updated MarketMoodBus CFGI for {asset}")
            return True
            
        except Exception as exc:
            logger.warning(f"Failed to update mood bus for {asset}: {exc}")
            return False
    
    async def update_all_assets(self, assets: Optional[List[str]] = None):
        """Update fear/greed for all assets asynchronously."""
        if assets is None:
            assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        tasks = [self.update_mood_bus(asset) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Updated CFGI for {success_count}/{len(assets)} assets")
    
    def get_market_summary(self) -> Dict[str, Any]:
        """Get fear/greed summary for major assets."""
        assets = ["BTC", "ETH", "SOL"]
        data = self.get_multi_fg(assets)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "assets": {
                asset: {
                    "fgi": d.fgi,
                    "classification": d.classification.value,
                    "is_extreme": d.is_extreme(),
                    "risk_multiplier": d.get_risk_multiplier(),
                }
                for asset, d in data.items()
            },
            "average_fgi": sum(d.fgi for d in data.values()) / len(data),
            "extreme_count": sum(1 for d in data.values() if d.is_extreme()),
        }


# Singleton accessor
def get_cfgi_client(api_key: Optional[str] = None) -> CFGIClient:
    """Get the singleton CFGIClient instance."""
    return CFGIClient(api_key)


# ── Convenience functions ─────────────────────────────────────────────

def quick_fg(asset: str) -> int:
    """Quick one-liner to get fear/greed index (0-100)."""
    try:
        client = get_cfgi_client()
        data = client.get_fear_greed(asset)
        return data.fgi
    except Exception as _e:
        logger.debug("quick_fg(%s) failed, returning neutral 50: %s", asset, _e)
        return 50  # Neutral fallback


def quick_fg_normalized(asset: str) -> float:
    """Quick one-liner to get normalized fear/greed (0.0-1.0)."""
    return quick_fg(asset) / 100.0


def get_fg_regime(asset: str) -> str:
    """Get fear/greed regime as string."""
    try:
        client = get_cfgi_client()
        data = client.get_fear_greed(asset)
        return data.classification.value
    except Exception as _e:
        logger.debug("get_fg_regime(%s) failed, returning neutral: %s", asset, _e)
        return "neutral"


def should_reduce_size(asset: str, direction: str) -> Tuple[bool, float]:
    """
    Check if position size should be reduced based on fear/greed.
    
    Args:
        asset: Asset symbol
        direction: Proposed trade direction ("long" or "short")
    
    Returns:
        (should_reduce, multiplier) tuple
    """
    try:
        client = get_cfgi_client()
        data = client.get_fear_greed(asset)
        
        multiplier = data.get_risk_multiplier()
        should_reduce = multiplier < 1.0
        
        # Extra check: if going with the crowd in extremes
        if data.fgi >= 80 and direction == "long":
            # Extreme greed + going long = reduce more
            multiplier *= 0.8
            should_reduce = True
        elif data.fgi <= 20 and direction == "short":
            # Extreme fear + going short = reduce more
            multiplier *= 0.8
            should_reduce = True
        
        return should_reduce, multiplier
        
    except Exception as _e:
        logger.debug("should_reduce_size(%s, %s) failed, no reduction: %s", asset, direction, _e)
        return False, 1.0


# Import for async support
import asyncio
