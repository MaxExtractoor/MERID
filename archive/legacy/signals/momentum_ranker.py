"""Cross-sectional and time-series momentum ranking for crypto assets.

Implements Phase 4 of the MERID single-signal hierarchy:
- Multi-horizon returns (15m, 1h, 4h)
- Volatility-adjusted returns (return / realized vol)
- Cross-sectional ranking of BTC, ETH, SOL, XRP, DOGE
- Integration with Top-N allocator as sort key

References:
- Time Series and Cross-Sectional Momentum in Cryptocurrency Markets
  (https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/...)
- Short-term momentum in cryptocurrency markets
  (https://www.sciencedirect.com/science/article/abs/pii/S0275531919308062)
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Deque
from collections import deque
from enum import Enum
import math

from utils.logger import get_logger

logger = get_logger("merid.signals.momentum_ranker")

# Module-level singleton instance
_ranker_instance: Optional[CrossSectionalMomentumRanker] = None


class MomentumRegime(str, Enum):
    """Momentum regime classification."""
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


@dataclass
class AssetMomentum:
    """Momentum metrics for a single crypto asset."""
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    timestamp: float
    
    # Raw returns by horizon (as decimals, e.g., 0.05 = 5%)
    return_15m: float = 0.0
    return_1h: float = 0.0
    return_4h: float = 0.0
    return_24h: float = 0.0
    
    # Volatility metrics (annualized)
    volatility_15m: float = 0.0
    volatility_1h: float = 0.0
    volatility_4h: float = 0.0
    
    # Volatility-adjusted returns (Sharpe-like)
    sharpe_15m: float = 0.0
    sharpe_1h: float = 0.0
    sharpe_4h: float = 0.0
    
    # Composite score (weighted combination)
    composite_score: float = 0.0
    
    # Rank within universe (1 = strongest)
    rank: int = 0
    
    # Regime classification
    regime: MomentumRegime = MomentumRegime.NEUTRAL
    
    @property
    def is_bullish(self) -> bool:
        """Asset showing bullish momentum."""
        return self.composite_score > 0.02

    @property
    def is_bearish(self) -> bool:
        """Asset showing bearish momentum."""
        return self.composite_score < -0.02

    @property
    def is_strong_momentum(self) -> bool:
        """Strong momentum signal (either direction)."""
        return abs(self.composite_score) > 0.05


@dataclass
class MomentumRankings:
    """Complete cross-sectional momentum ranking for all assets."""
    timestamp: float
    assets: Dict[str, AssetMomentum] = field(default_factory=dict)
    
    # Sorted list (strongest to weakest)
    ranked_assets: List[str] = field(default_factory=list)
    
    # Universe-level metrics
    avg_momentum: float = 0.0
    dispersion: float = 0.0  # std dev of momentum scores
    top_bottom_spread: float = 0.0  # difference between #1 and last
    
    @property
    def strongest(self) -> Optional[str]:
        """Strongest momentum asset."""
        return self.ranked_assets[0] if self.ranked_assets else None
    
    @property
    def weakest(self) -> Optional[str]:
        """Weakest momentum asset."""
        return self.ranked_assets[-1] if self.ranked_assets else None
    
    def get_rank(self, asset: str) -> int:
        """Get momentum rank for asset (1 = strongest)."""
        if asset in self.ranked_assets:
            return self.ranked_assets.index(asset) + 1
        return 999
    
    def get_momentum(self, asset: str) -> Optional[AssetMomentum]:
        """Get momentum metrics for asset."""
        return self.assets.get(asset)
    
    def is_top_n(self, asset: str, n: int = 3) -> bool:
        """Check if asset is in top N by momentum."""
        return self.get_rank(asset) <= n


class CrossSectionalMomentumRanker:
    """Ranks crypto assets by cross-sectional momentum.
    
    Uses multiple time horizons and volatility-adjusted returns
    to produce a composite momentum score for each asset.
    """
    
    # Default lookback periods (in bars)
    DEFAULT_LOOKBACK_15M = 96  # 24 hours of 15m bars
    DEFAULT_LOOKBACK_1H = 24   # 24 hours of 1h bars
    DEFAULT_LOOKBACK_4H = 6    # 24 hours of 4h bars
    
    # Score weights for composite
    WEIGHT_15M = 0.2
    WEIGHT_1H = 0.3
    WEIGHT_4H = 0.5
    
    def __init__(
        self,
        assets: Optional[List[str]] = None,
        lookback_15m: int = DEFAULT_LOOKBACK_15M,
        lookback_1h: int = DEFAULT_LOOKBACK_1H,
        lookback_4h: int = DEFAULT_LOOKBACK_4H,
    ):
        self.assets = assets or ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.lookback_15m = lookback_15m
        self.lookback_1h = lookback_1h
        self.lookback_4h = lookback_4h
        
        # Price history by (asset, timeframe)
        self._prices: Dict[Tuple[str, str], Deque[Tuple[float, float]]] = {}
        # (asset, tf) -> deque of (timestamp, price)
        
        # Current rankings
        self._current_rankings: Optional[MomentumRankings] = None
        self._last_update: float = 0.0
        
        # Use threading lock for thread safety
        import threading
        self._lock = threading.Lock()
        
        logger.info(
            "CrossSectionalMomentumRanker initialized for %s (lookbacks: 15m=%d, 1h=%d, 4h=%d)",
            self.assets, lookback_15m, lookback_1h, lookback_4h
        )
    
    def add_price(self, asset: str, timeframe: str, price: float, timestamp: Optional[float] = None) -> None:
        """Add a price observation for an asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Bar timeframe ("15m", "1h", "4h")
            price: Asset price in USD
            timestamp: Optional timestamp (defaults to current time)
        """
        if asset not in self.assets:
            return
        
        key = (asset, timeframe)
        ts = timestamp or time.time()
        
        if self._lock is not None:
            with self._lock:
                if key not in self._prices:
                    self._prices[key] = deque(maxlen=self._get_maxlen(timeframe))
                self._prices[key].append((ts, price))
        else:
            # Lock disabled - direct update (startup workaround)
            if key not in self._prices:
                self._prices[key] = deque(maxlen=self._get_maxlen(timeframe))
            self._prices[key].append((ts, price))
    
    def _get_maxlen(self, timeframe: str) -> int:
        """Get maximum deque length for timeframe."""
        if timeframe == "15m":
            return self.lookback_15m
        elif timeframe == "1h":
            return self.lookback_1h
        elif timeframe == "4h":
            return self.lookback_4h
        else:
            return 100  # default
    
    def calculate_returns(self, prices: Deque[Tuple[float, float]]) -> List[float]:
        """Calculate log returns from price series."""
        if len(prices) < 2:
            return []
        
        price_list = [p for _, p in prices]
        returns = []
        for i in range(1, len(price_list)):
            if price_list[i - 1] > 0:
                log_return = math.log(price_list[i] / price_list[i - 1])
                returns.append(log_return)
        return returns
    
    def calculate_volatility(self, returns: List[float]) -> float:
        """Calculate annualized volatility from returns."""
        if len(returns) < 5:
            return 0.0
        
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        
        if variance <= 0:
            return 0.0
        
        # Annualize (approximate for crypto 24/7)
        return math.sqrt(variance * 365 * 24)
    
    def compute_momentum(self) -> MomentumRankings:
        """Compute cross-sectional momentum for all assets.
        
        Returns:
            MomentumRankings with composite scores and ranks
        """
        with self._lock:
            asset_momentum: Dict[str, AssetMomentum] = {}

            for asset in self.assets:
                momentum = self._compute_asset_momentum(asset)
                # Include if any return data was computed (even if Sharpe is 0 due to low vol)
                if momentum and (momentum.return_15m != 0 or momentum.return_1h != 0 or momentum.return_4h != 0):
                    asset_momentum[asset] = momentum
            
            # Rank by composite score (descending)
            sorted_assets = sorted(
                asset_momentum.items(),
                key=lambda x: x[1].composite_score,
                reverse=True
            )
            
            ranked_symbols = [asset for asset, _ in sorted_assets]
            
            # Assign ranks
            for rank, (asset, momentum) in enumerate(sorted_assets, 1):
                momentum.rank = rank
            
            # Calculate universe metrics
            scores = [m.composite_score for m in asset_momentum.values()]
            avg_momentum = sum(scores) / len(scores) if scores else 0.0
            dispersion = self._std_dev(scores) if scores else 0.0
            top_bottom_spread = (max(scores) - min(scores)) if scores else 0.0
            
            rankings = MomentumRankings(
                timestamp=time.time(),
                assets=asset_momentum,
                ranked_assets=ranked_symbols,
                avg_momentum=avg_momentum,
                dispersion=dispersion,
                top_bottom_spread=top_bottom_spread,
            )
            
            self._current_rankings = rankings
            self._last_update = time.time()
            
            return rankings
    
    def _compute_asset_momentum(self, asset: str) -> Optional[AssetMomentum]:
        """Compute momentum metrics for a single asset."""
        momentum = AssetMomentum(asset=asset, timestamp=time.time())
        
        # Compute for each timeframe
        for tf, lookback, attr_ret, attr_vol, attr_sharpe in [
            ("15m", self.lookback_15m, "return_15m", "volatility_15m", "sharpe_15m"),
            ("1h", self.lookback_1h, "return_1h", "volatility_1h", "sharpe_1h"),
            ("4h", self.lookback_4h, "return_4h", "volatility_4h", "sharpe_4h"),
        ]:
            key = (asset, tf)
            if key not in self._prices or len(self._prices[key]) < 2:
                continue
            
            prices = self._prices[key]
            returns = self.calculate_returns(prices)
            
            if returns:
                # Total return over period
                total_return = sum(returns)
                setattr(momentum, attr_ret, total_return)
                
                # Volatility
                vol = self.calculate_volatility(returns)
                setattr(momentum, attr_vol, vol)
                
                # Sharpe-like ratio (return per unit vol, capped to avoid extreme values)
                if vol > 0.0001:  # Minimum volatility threshold (lower for crypto micro-vol)
                    sharpe = total_return / (vol / math.sqrt(365 * 24))
                    sharpe = max(-100.0, min(100.0, sharpe))  # Cap extreme values
                    setattr(momentum, attr_sharpe, sharpe)
        
        # Compute composite score
        composite = (
            self.WEIGHT_15M * momentum.sharpe_15m +
            self.WEIGHT_1H * momentum.sharpe_1h +
            self.WEIGHT_4H * momentum.sharpe_4h
        )
        momentum.composite_score = composite
        
        # Classify regime
        momentum.regime = self._classify_regime(composite)
        
        return momentum
    
    def _classify_regime(self, composite_score: float) -> MomentumRegime:
        """Classify momentum regime from composite score."""
        if composite_score > 0.6:
            return MomentumRegime.STRONG_UP
        elif composite_score > 0.2:
            return MomentumRegime.UP
        elif composite_score < -0.6:
            return MomentumRegime.STRONG_DOWN
        elif composite_score < -0.2:
            return MomentumRegime.DOWN
        else:
            return MomentumRegime.NEUTRAL
    
    def _std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        return math.sqrt(variance) if variance > 0 else 0.0
    
    def get_current_rankings(self) -> Optional[MomentumRankings]:
        """Get most recent momentum rankings."""
        with self._lock:
            return self._current_rankings
    
    def is_fresh(self, max_age_seconds: float = 300.0) -> bool:
        """Check if rankings are fresh (not stale)."""
        with self._lock:
            return (time.time() - self._last_update) < max_age_seconds
    
    def reset(self) -> None:
        """Clear all price history and rankings."""
        with self._lock:
            self._prices.clear()
            self._current_rankings = None
            self._last_update = 0.0
            logger.info("CrossSectionalMomentumRanker reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_ranker: Optional[MomentumRanker] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_momentum_ranker(
    assets: Optional[List[str]] = None,
    lookback_15m: int = 96,
    lookback_1h: int = 24,
    lookback_4h: int = 6,
) -> CrossSectionalMomentumRanker:
    """Get or create the singleton CrossSectionalMomentumRanker."""
    global _ranker_instance
    if _ranker_instance is None:
        _ranker_instance = CrossSectionalMomentumRanker(
            assets=assets,
            lookback_15m=lookback_15m,
            lookback_1h=lookback_1h,
            lookback_4h=lookback_4h,
        )
        logger.info("CrossSectionalMomentumRanker singleton initialized")
    return _ranker_instance


def reset_momentum_ranker() -> None:
    """Reset the singleton (for testing)."""
    global _ranker_instance
    _ranker_instance = None
    logger.info("CrossSectionalMomentumRanker singleton reset")
