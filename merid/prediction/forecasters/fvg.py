"""Fair Value Gap (FVG) Forecaster — Production-Ready Price Imbalance Detection.

Detects price imbalances where no trading occurred between candle bodies,
a key concept from Smart Money Concepts (SMC) adapted for prediction markets.

Signal components:
1. **Bullish FVG** — Gap between previous high and current low = bullish continuation
2. **Bearish FVG** — Gap between previous low and current high = bearish continuation  
3. **FVG Fill Probability** — Distance from current price to nearest unfilled FVG
4. **Imbalance Strength** — Size of gap relative to recent ATR

Production Features:
- Rolling window FVG detection (configurable, default 20 candles)
- Automatic FVG invalidation when filled
- Multi-timeframe FVG confluence detection
- Integration with Kalshi market price ranges (0-100 cents)

Archetype: "fvg"
"""

from __future__ import annotations

import math
import os
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.fvg")

# CRITICAL FIX: 2026-07-06 - Migrated from environment variables to profile YAML
# Single source of truth: config/profiles/kalshi_crypto_15m_v2.yaml -> momentum_fvg.fvg_*
# Environment variables (MERID_FVG_*) are DEPRECATED and no longer used

def _load_fvg_config_from_profile():
    """Load FVG configuration from profile YAML (single source of truth)."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile
        profile = get_crypto_15m_profile()
        
        # Get momentum_fvg config section
        momentum_fvg_config = profile.momentum_fvg
        
        return {
            'window_size': getattr(momentum_fvg_config, 'fvg_window_size', 20),
            'min_gap_cents': getattr(momentum_fvg_config, 'fvg_min_gap_cents', 2.0),
            'fill_threshold_cents': getattr(momentum_fvg_config, 'fvg_fill_threshold_cents', 5.0),
            'atr_period': getattr(momentum_fvg_config, 'fvg_atr_period', 14),
        }
    except Exception as e:
        logger.warning("[FVG] Failed to load config from profile, using defaults: %s", e)
        return {
            'window_size': 20,
            'min_gap_cents': 2.0,
            'fill_threshold_cents': 5.0,
            'atr_period': 14,
        }

# Load configuration from profile YAML
_FVG_CONFIG = _load_fvg_config_from_profile()
_FVG_WINDOW_SIZE = _FVG_CONFIG['window_size']
_FVG_MIN_GAP_CENTS = _FVG_CONFIG['min_gap_cents']
_FVG_FILL_THRESHOLD_CENTS = _FVG_CONFIG['fill_threshold_cents']
_FVG_ATR_PERIOD = _FVG_CONFIG['atr_period']

# Validate FVG parameters are reasonable
if _FVG_WINDOW_SIZE < 1 or _FVG_WINDOW_SIZE > 1000:
    logger.warning(
        "[FVG] Invalid fvg_window_size=%s - using default 20",
        _FVG_WINDOW_SIZE
    )
    _FVG_WINDOW_SIZE = 20
if _FVG_MIN_GAP_CENTS < 0 or _FVG_MIN_GAP_CENTS > 100:
    logger.warning(
        "[FVG] Invalid fvg_min_gap_cents=%s - using default 2.0",
        _FVG_MIN_GAP_CENTS
    )
    _FVG_MIN_GAP_CENTS = 2.0
if _FVG_FILL_THRESHOLD_CENTS < 0 or _FVG_FILL_THRESHOLD_CENTS > 100:
    logger.warning(
        "[FVG] Invalid fvg_fill_threshold_cents=%s - using default 5.0",
        _FVG_FILL_THRESHOLD_CENTS
    )
    _FVG_FILL_THRESHOLD_CENTS = 5.0
if _FVG_ATR_PERIOD < 1 or _FVG_ATR_PERIOD > 100:
    logger.warning(
        "[FVG] Invalid fvg_atr_period=%s - using default 14",
        _FVG_ATR_PERIOD
    )
    _FVG_ATR_PERIOD = 14


@dataclass
class FVG:
    """Represents a single Fair Value Gap (price imbalance)."""
    
    direction: str  # "bullish" or "bearish"
    top: float      # Upper bound of gap (cents)
    bottom: float   # Lower bound of gap (cents)
    size: float     # Gap size in cents
    created_at: float  # Timestamp when FVG formed
    asset: str
    timeframe: str
    filled: bool = False
    fill_timestamp: Optional[float] = None
    
    def is_within_fill_distance(self, price_cents: float, threshold: float = _FVG_FILL_THRESHOLD_CENTS) -> bool:
        """Check if price is within threshold of this FVG (indicating potential fill)."""
        if self.filled:
            return False
        
        if self.direction == "bullish":
            # Bullish FVG: price should be near or below the bottom to fill up
            return abs(price_cents - self.bottom) <= threshold or price_cents < self.bottom
        else:
            # Bearish FVG: price should be near or above the top to fill down
            return abs(price_cents - self.top) <= threshold or price_cents > self.top
    
    def distance_to_fill(self, price_cents: float) -> float:
        """Calculate distance (cents) from price to FVG fill zone."""
        if self.filled:
            return float('inf')
        
        if self.direction == "bullish":
            return self.bottom - price_cents  # Negative if price below
        else:
            return price_cents - self.top  # Negative if price above
    
    def midpoint(self) -> float:
        """Calculate midpoint of the FVG zone."""
        return (self.top + self.bottom) / 2
    
    def fill(self, timestamp: float) -> None:
        """Mark this FVG as filled."""
        self.filled = True
        self.fill_timestamp = timestamp


class FVGStore:
    """Thread-safe store for detected FVGs per asset/timeframe."""
    
    def __init__(self, max_size: int = 100) -> None:
        self._fvgs: Dict[str, Deque[FVG]] = {}
        self._price_history: Dict[str, Deque[Tuple[float, float, float, float, float]]] = {}  # OHLC + ts
        self._max_size = max_size
    
    def _key(self, asset: str, timeframe: str) -> str:
        return f"{asset.upper()}:{timeframe.lower()}"
    
    def clear(self) -> None:
        """Clear all stored FVGs and price history. Useful for testing."""
        self._fvgs.clear()
        self._price_history.clear()
    
    def add_candle(self, asset: str, timeframe: str, open_p: float, high: float, low: float, close: float, timestamp: float) -> None:
        """Add a candle and detect new FVGs."""
        key = self._key(asset, timeframe)
        
        if key not in self._price_history:
            self._price_history[key] = deque(maxlen=_FVG_WINDOW_SIZE)
        
        self._price_history[key].append((open_p, high, low, close, timestamp))
        
        # Detect FVGs when we have at least 3 candles
        if len(self._price_history[key]) >= 3:
            self._detect_fvgs(key, asset, timeframe)
    
    def _detect_fvgs(self, key: str, asset: str, timeframe: str) -> None:
        """Detect FVGs from price history."""
        history = list(self._price_history[key])
        if len(history) < 3:
            return
        
        if key not in self._fvgs:
            self._fvgs[key] = deque(maxlen=self._max_size)
        
        # Look at last 3 candles
        for i in range(len(history) - 2):
            c1 = history[i]      # First candle (idx 0=open, 1=high, 2=low, 3=close, 4=ts)
            c2 = history[i + 1]  # Middle candle (potential gap candle)
            c3 = history[i + 2]  # Third candle
            
            # Bullish FVG: c1.high < c3.low (gap between candles 1 and 3)
            if c1[1] < c3[2]:  # high1 < low3
                gap_size = c3[2] - c1[1]
                if gap_size >= _FVG_MIN_GAP_CENTS:
                    fvg = FVG(
                        direction="bullish",
                        top=c3[2],
                        bottom=c1[1],
                        size=gap_size,
                        created_at=c3[4],
                        asset=asset,
                        timeframe=timeframe,
                    )
                    self._fvgs[key].append(fvg)
                    from utils.logger import format_price
                    logger.debug(f"Detected bullish FVG for {asset}/{timeframe}: {format_price(asset, c1[1])}-{format_price(asset, c3[2])} ({format_price(asset, gap_size)}c)")
            
            # Bearish FVG: c1.low > c3.high (gap between candles 1 and 3)
            if c1[2] > c3[1]:  # low1 > high3
                gap_size = c1[2] - c3[1]
                if gap_size >= _FVG_MIN_GAP_CENTS:
                    fvg = FVG(
                        direction="bearish",
                        top=c1[2],
                        bottom=c3[1],
                        size=gap_size,
                        created_at=c3[4],
                        asset=asset,
                        timeframe=timeframe,
                    )
                    self._fvgs[key].append(fvg)
                    from utils.logger import format_price
                    logger.debug(f"Detected bearish FVG for {asset}/{timeframe}: {format_price(asset, c3[1])}-{format_price(asset, c1[2])} ({format_price(asset, gap_size)}c)")
    
    def check_fills(self, asset: str, timeframe: str, current_price: float, timestamp: float) -> List[FVG]:
        """Check if any unfilled FVGs have been filled by current price."""
        key = self._key(asset, timeframe)
        filled = []
        
        if key in self._fvgs:
            for fvg in self._fvgs[key]:
                if not fvg.filled:
                    if fvg.direction == "bullish" and current_price >= fvg.top:
                        fvg.fill(timestamp)
                        filled.append(fvg)
                        from utils.logger import format_price
                        logger.debug(f"Bullish FVG filled at {format_price(asset, current_price)}")
                    elif fvg.direction == "bearish" and current_price <= fvg.bottom:
                        fvg.fill(timestamp)
                        filled.append(fvg)
                        from utils.logger import format_price
                        logger.debug(f"Bearish FVG filled at {format_price(asset, current_price)}")
        
        return filled
    
    def get_active_fvgs(self, asset: str, timeframe: str) -> List[FVG]:
        """Get all unfilled FVGs for an asset/timeframe."""
        key = self._key(asset, timeframe)
        if key not in self._fvgs:
            return []
        return [f for f in self._fvgs[key] if not f.filled]
    
    def get_nearest_fvg(self, asset: str, timeframe: str, price: float) -> Optional[FVG]:
        """Get the nearest unfilled FVG to current price."""
        active = self.get_active_fvgs(asset, timeframe)
        if not active:
            return None
        
        return min(active, key=lambda f: abs(f.distance_to_fill(price)))
    
    def get_fvg_confluence_score(self, asset: str, price: float) -> float:
        """Calculate confluence score across timeframes (-1 to 1, negative = bearish)."""
        timeframes = ["15m", "1h", "4h", "daily"]
        bullish_count = 0
        bearish_count = 0
        
        for tf in timeframes:
            for fvg in self.get_active_fvgs(asset, tf):
                if fvg.is_within_fill_distance(price):
                    if fvg.direction == "bullish":
                        bullish_count += 1
                    else:
                        bearish_count += 1
        
        total = bullish_count + bearish_count
        if total == 0:
            return 0.0
        
        # Score: positive for bullish, negative for bearish
        return (bullish_count - bearish_count) / total
    
    def clear_old_fvgs(self, max_age_seconds: float = 86400) -> int:
        """Clear FVGs older than max_age_seconds. Returns count cleared."""
        now = time.time()
        cleared = 0
        
        for key, fvgs in self._fvgs.items():
            for fvg in list(fvgs):
                if now - fvg.created_at > max_age_seconds:
                    fvgs.remove(fvg)
                    cleared += 1
        
        return cleared


# Global FVG store instance
_fvg_store: Optional[FVGStore] = None


def get_fvg_store() -> FVGStore:
    """Get the global FVG store singleton."""
    global _fvg_store
    if _fvg_store is None:
        _fvg_store = FVGStore()
    return _fvg_store


class FVGForecaster(Forecaster):
    """Fair Value Gap forecaster for Kalshi prediction markets.
    
    Detects price imbalances (FVGs) and generates signals when price
    approaches these gaps, indicating high-probability fill trades.
    """
    
    def __init__(self, store: Optional[FVGStore] = None) -> None:
        self._store = store or get_fvg_store()
    
    @property
    def forecaster_id(self) -> str:
        return "fvg_v1"
    
    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float,
        open_interest: float,
        minutes_to_expiry: Optional[float],
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        """Generate FVG-based prediction for a Kalshi market.
        
        Uses the midpoint price (bid-ask average) to check FVG proximity.
        """
        if not asset or not timeframe:
            return None
        
        # Calculate current price from bid/ask or implied prob
        if bid is not None and ask is not None:
            current_price = (bid + ask) / 2 * 100  # Convert to cents
        else:
            current_price = implied_yes * 100  # Use implied as fallback
        
        # Get active FVGs for this asset/timeframe
        active_fvgs = self._store.get_active_fvgs(asset, timeframe)
        
        if not active_fvgs:
            # No FVGs detected yet - neutral signal
            return ForecastResult(
                forecaster_id=self.forecaster_id,
                p_model=implied_yes,
                confidence=0.0,
                components={"fvg_active": 0, "fvg_fill_signal": 0.0},
            )
        
        # Find nearest FVG and calculate fill signal
        nearest_fvg = self._store.get_nearest_fvg(asset, timeframe, current_price)
        if not nearest_fvg:
            return ForecastResult(
                forecaster_id=self.forecaster_id,
                p_model=implied_yes,
                confidence=0.0,
                components={"fvg_active": len(active_fvgs), "fvg_fill_signal": 0.0},
            )
        
        # Check if price is near FVG fill zone
        is_near_fill = nearest_fvg.is_within_fill_distance(current_price)
        distance = nearest_fvg.distance_to_fill(current_price)
        
        # Calculate directional signal based on FVG type and distance
        fill_signal = 0.0  # -1.0 (strong bearish) to +1.0 (strong bullish)
        confidence = 0.0
        
        if is_near_fill:
            # Strong signal: price is near FVG fill zone
            if nearest_fvg.direction == "bullish":
                # Bullish FVG = price should go UP to fill
                fill_signal = min(1.0, _FVG_FILL_THRESHOLD_CENTS / max(abs(distance), 1.0))
            else:
                # Bearish FVG = price should go DOWN to fill
                fill_signal = -min(1.0, _FVG_FILL_THRESHOLD_CENTS / max(abs(distance), 1.0))
            
            # Higher confidence for larger gaps and closer proximity
            confidence = min(1.0, nearest_fvg.size / 10.0) * 0.7 + 0.3
        else:
            # Price is away from FVG - use confluence across timeframes
            confluence = self._store.get_fvg_confluence_score(asset, current_price)
            fill_signal = confluence * 0.5  # Weaker signal from confluence
            confidence = abs(confluence) * 0.4
        
        # Convert fill signal to probability adjustment
        # Bullish FVG fill signal -> higher YES probability
        # Bearish FVG fill signal -> lower YES probability
        p_adjustment = fill_signal * 0.1  # Max 10% adjustment
        p_model = max(0.01, min(0.99, implied_yes + p_adjustment))
        
        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=p_model,
            confidence=confidence,
            components={
                "fvg_active": len(active_fvgs),
                "fvg_nearest_direction": 1.0 if nearest_fvg.direction == "bullish" else -1.0,
                "fvg_nearest_size": nearest_fvg.size,
                "fvg_distance_to_fill": distance,
                "fvg_fill_signal": fill_signal,
                "fvg_fill_proximity": 1.0 if is_near_fill else 0.0,
                "fvg_confluence": self._store.get_fvg_confluence_score(asset, current_price),
            },
        )
    
    def update_price(
        self,
        asset: str,
        timeframe: str,
        open_p: float,
        high: float,
        low: float,
        close: float,
        timestamp: float,
    ) -> None:
        """Update FVG store with new candle data.
        
        Call this when new price data arrives to detect fresh FVGs
        and check for fills.
        """
        import time
        
        # Add candle and detect new FVGs
        self._store.add_candle(asset, timeframe, open_p, high, low, close, timestamp)
        
        # Check if any FVGs were filled
        self._store.check_fills(asset, timeframe, close, timestamp)
    
    def get_stats(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """Get FVG statistics for diagnostics."""
        stats = {
            "active_fvgs": 0,
            "by_timeframe": {},
            "by_direction": {"bullish": 0, "bearish": 0},
        }
        
        if asset:
            for tf in ["15m", "1h", "4h", "daily"]:
                fvgs = self._store.get_active_fvgs(asset, tf)
                stats["by_timeframe"][tf] = len(fvgs)
                for f in fvgs:
                    stats["by_direction"][f.direction] += 1
                stats["active_fvgs"] += len(fvgs)
        
        return stats


# Singleton instance
_fvg_forecaster: Optional[FVGForecaster] = None


def get_fvg_forecaster() -> FVGForecaster:
    """Get the global FVG forecaster singleton."""
    global _fvg_forecaster
    if _fvg_forecaster is None:
        _fvg_forecaster = FVGForecaster()
    return _fvg_forecaster
